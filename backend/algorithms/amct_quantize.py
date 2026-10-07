"""④ 混合精度量化（真实实现）。

输入：workdir/selected_scheme.json（用户选定方案）、workdir/model.onnx；
产物：workdir/quantized.onnx（真实量化后的 ONNX，契约产物）
      workdir/quantized_fallback.onnx（FP16/FP32 降级版，仅当 INT8 成功时生成，
                                       供 ATC 不接受 QDQ 时回退，非契约产物）

为什么不用 AMCT：开源版 AMCT 只保留了 PyTorch 路径（ONNX 模块已移除），
且运行态需要昇腾 NPU 驱动与固件 —— 本机没有硬件。所以量化改用 onnxruntime
的 QDQ（Quantize/Dequantize）静态量化实现，产出的仍是标准 ONNX，ATC 能消费。

两段式，顺序不能反：
  Phase A 用 QDQ 静态量化把 INT8 层压成 8bit —— 标定阶段要真实跑前向推理，
          必须在 FP32 图上做（ORT CPU EP 的 FP16 算子覆盖不全）
  Phase B 把剩下的 FP16 层权重转成 float16 —— 纯图改写，不做推理
两者叠加即得"QDQ + FP16"的混合精度模型。

标定数据是按输入张量形状合成的确定性数据（固定种子、图像形用正弦网格）。
它只能保证量化范围有值且可复现，**不代表真实精度** —— 精度损失仍是估算口径。

依赖缺失（Windows 的 tools/py38 没有 onnxruntime）时回退为复制 model.onnx，
保持演示链路可用。
"""
import json
import shutil
import sys
import time
from pathlib import Path

STAGE = "quantizing"
SLEEP = 0.15
CALIB_SEED = 1234
DEFAULT_SAMPLES = 32
# onnxruntime 1.23 只认到 IR 11；onnx>=1.19 导出的模型默认写更高的版本
ORT_MAX_IR_VERSION = 10

try:
    import numpy as np
    import onnx
    from onnxruntime.quantization import (CalibrationDataReader, QuantFormat,
                                          QuantType, quantize_static)

    HAS_ORT = True
except ImportError:  # pragma: no cover - 只在无 onnxruntime 的环境走到
    HAS_ORT = False

BIT_ORDER = {"INT8": 0, "FP16": 1, "FP32": 2}   # 越大越保守


def emit(percent: int, message: str) -> None:
    print(json.dumps({"stage": STAGE, "percent": percent, "message": message},
                     ensure_ascii=False), flush=True)


def read_selected(workdir: Path):
    path = workdir / "selected_scheme.json"
    if not path.exists():
        return 0, {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return 0, {}
    config = data.get("layer_config", {}) or {}
    return data.get("index", 0), {str(k): str(v).upper() for k, v in config.items()}


def read_layer_names(workdir: Path):
    path = workdir / "layers.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return [str(item["name"]) for item in data
            if isinstance(item, dict) and "name" in item]


def _belongs(initializer: str, layer: str) -> bool:
    return initializer == layer or initializer.startswith(layer + ".")


def map_initializers(ordered_names, layer_names):
    """与 hawq_sensitivity.py 同一套映射语义（前缀直配 + 连续分桶）。"""
    buckets = {name: [] for name in layer_names}
    unmatched = []
    for init in ordered_names:
        for layer in layer_names:
            if _belongs(init, layer):
                buckets[layer].append(init)
                break
        else:
            unmatched.append(init)
    if not unmatched:
        return buckets

    empty = [name for name in layer_names if not buckets[name]]
    if not empty:
        return buckets
    total = len(unmatched)
    for position, layer in enumerate(empty):
        start = position * total // len(empty)
        end = (position + 1) * total // len(empty)
        buckets[layer] = unmatched[start:end]
    return buckets


def build_node_bits(model, layer_config, layer_names):
    """节点名 -> 位宽。同一个 initializer 被不同层共享时取最保守的那个。"""
    declared = {init.name for init in model.graph.initializer}
    ordered, seen = [], set()
    init_to_nodes = {}
    for node in model.graph.node:
        for name in node.input:
            if name in declared:
                init_to_nodes.setdefault(name, []).append(node.name)
                if name not in seen:
                    seen.add(name)
                    ordered.append(name)
    for init in model.graph.initializer:
        if init.name not in seen:
            seen.add(init.name)
            ordered.append(init.name)

    buckets = map_initializers(ordered, layer_names) if layer_names else {}

    node_bits = {}
    for layer, inits in buckets.items():
        bit = layer_config.get(layer, "FP32")
        if bit not in BIT_ORDER:
            bit = "FP32"
        for init_name in inits:
            for node_name in init_to_nodes.get(init_name, []):
                current = node_bits.get(node_name)
                if current is None or BIT_ORDER[bit] > BIT_ORDER[current]:
                    node_bits[node_name] = bit

    int8_nodes = sorted(n for n, b in node_bits.items() if b == "INT8")
    fp16_nodes = sorted(n for n, b in node_bits.items() if b == "FP16")
    fp32_nodes = sorted(n for n, b in node_bits.items() if b == "FP32")
    return int8_nodes, fp16_nodes, fp32_nodes


class SyntheticCalibrationReader(CalibrationDataReader):
    """按模型输入形状合成确定性标定数据。"""

    def __init__(self, model, samples):
        self.samples = max(1, samples)
        self.entries = []
        for value in model.graph.input:
            dims = value.type.tensor_type.shape.dim
            shape = [int(d.dim_value) if d.dim_value > 0 else 1 for d in dims]
            if not shape:
                shape = [1]
            self.entries.append((value.name, shape))
        rng = np.random.default_rng(CALIB_SEED)
        self.batches = [self._make_batch(rng) for _ in range(self.samples)]
        self.index = 0

    @staticmethod
    def _tensor(rng, shape):
        # 4D 按图像处理：正弦网格比纯随机噪声更接近真实激活分布
        if len(shape) == 4:
            batch, channels, height, width = shape
            rows = np.linspace(0.0, np.pi, max(height, 1), dtype=np.float32)
            cols = np.linspace(0.0, np.pi, max(width, 1), dtype=np.float32)
            grid = np.sin(rows)[:, None] * np.cos(cols)[None, :]
            planes = np.stack([grid * (channel + 1) for channel in range(channels)])
            return np.repeat(planes[None, ...], batch, axis=0).astype(np.float32)
        return rng.standard_normal(shape).astype(np.float32)

    def _make_batch(self, rng):
        return {name: self._tensor(rng, shape) for name, shape in self.entries}

    def get_next(self):
        if self.index >= len(self.batches):
            return None
        batch = self.batches[self.index]
        self.index += 1
        return batch

    def rewind(self):
        self.index = 0


def normalize_ir_version(source: Path, target: Path) -> Path:
    """把 IR 版本压到 onnxruntime 能接受的范围内；不需要压时直接返回原路径。"""
    model = onnx.load(str(source), load_external_data=False)
    if model.ir_version <= ORT_MAX_IR_VERSION:
        return source
    model.ir_version = ORT_MAX_IR_VERSION
    onnx.save(model, str(target))
    return target


def run_qdq(source: Path, target: Path, model, int8_nodes, samples):
    reader = SyntheticCalibrationReader(model, samples)
    quantize_static(str(source), str(target), reader,
                    quant_format=QuantFormat.QDQ,
                    per_channel=True,
                    activation_type=QuantType.QUInt8,
                    weight_type=QuantType.QInt8,
                    nodes_to_quantize=int8_nodes or None)
    return onnx.load(str(target))


def topo_sort_graph(model) -> bool:
    """把 graph.node 重排成拓扑序；成功返回 True。

    convert_float_to_float16(keep_io_types=True) 会在图输入处插 Cast 节点，
    但它把这些节点追加到节点表末尾，于是先于生产者被消费 —— onnx.checker 会报
    "Nodes in a graph must be topologically sorted"。这里重排一遍修掉。
    """
    nodes = list(model.graph.node)
    available = {init.name for init in model.graph.initializer}
    available |= {value.name for value in model.graph.input}
    emitted = [False] * len(nodes)
    ordered = []
    for _ in range(len(nodes)):
        progressed = False
        for position, node in enumerate(nodes):
            if emitted[position]:
                continue
            if all((name in available) or name == "" for name in node.input):
                ordered.append(node)
                emitted[position] = True
                progressed = True
                for output in node.output:
                    if output:
                        available.add(output)
        if not progressed:
            break
    if len(ordered) != len(nodes):
        return False
    del model.graph.node[:]
    model.graph.node.extend(ordered)
    return True


def run_fp16(source_path: Path, target: Path, blocked):
    from onnxruntime.transformers.float16 import convert_float_to_float16

    model = onnx.load(str(source_path), load_external_data=False)
    converted = convert_float_to_float16(
        model, keep_io_types=True, node_block_list=sorted(blocked) or None)
    topo_sort_graph(converted)
    onnx.save(converted, str(target))


def has_qdq_nodes(path: Path) -> bool:
    try:
        model = onnx.load(str(path), load_external_data=False)
    except Exception:  # noqa: BLE001
        return False
    return any(node.op_type in ("QuantizeLinear", "DequantizeLinear")
               for node in model.graph.node)


def main() -> None:
    workdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    source = workdir / "model.onnx"
    target = workdir / "quantized.onnx"
    fallback = workdir / "quantized_fallback.onnx"

    index, config = read_selected(workdir)
    int8_wanted = sum(1 for value in config.values() if value == "INT8")

    if not HAS_ORT or not source.exists():
        reason = "未找到 model.onnx" if not source.exists() else "缺少 onnxruntime 依赖"
        emit(10, "AMCT 按方案 #%s 量化（降级：%s，直接透传原模型）" % (index, reason))
        time.sleep(SLEEP)
        emit(45, "插入量化算子并校准（跳过）")
        time.sleep(SLEEP)
        emit(75, "写回量化权重（跳过）")
        if source.exists():
            shutil.copyfile(str(source), str(target))
        else:
            target.write_bytes(b"FAKE-QUANTIZED-ONNX")
        time.sleep(SLEEP)
        emit(100, "量化完成")
        time.sleep(SLEEP)
        return

    emit(10, "读取方案 #%s：%d 层，其中 INT8 %d 层" % (index, len(config), int8_wanted))
    time.sleep(SLEEP)

    try:
        model = onnx.load(str(source), load_external_data=False)
    except Exception as exc:  # noqa: BLE001
        print("model.onnx 解析失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    layer_names = read_layer_names(workdir)
    if not layer_names:
        layer_names = sorted(config)
    int8_nodes, fp16_nodes, fp32_nodes = build_node_bits(model, config, layer_names)
    emit(25, "定位待量化节点：INT8 %d 个 / FP16 %d 个 / FP32 %d 个"
         % (len(int8_nodes), len(fp16_nodes), len(fp32_nodes)))
    time.sleep(SLEEP)

    if not int8_nodes and not fp16_nodes:
        emit(60, "方案未要求 INT8/FP16，直接输出 FP32 原模型")
        shutil.copyfile(str(source), str(target))
        emit(100, "量化完成（全 FP32）")
        time.sleep(SLEEP)
        return

    samples = int(_env_int("CALIBRATION_SAMPLES", DEFAULT_SAMPLES))
    staged = normalize_ir_version(source, workdir / "_quant_src.onnx")
    mixed_ok = False

    # 目标路径：QDQ(INT8) + FP16
    if int8_nodes:
        emit(40, "插入 QDQ 量化算子并用 %d 个合成样本校准（INT8 层）" % samples)
        time.sleep(SLEEP)
        try:
            qdq_path = workdir / "_quant_qdq.onnx"
            run_qdq(staged, qdq_path, model, int8_nodes, samples)
            emit(55, "QDQ 量化完成，开始 FP16 图改写")
            time.sleep(SLEEP)
            run_fp16(qdq_path, target, set(fp32_nodes) | set(int8_nodes))
            mixed_ok = True
            qdq_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            emit(55, "QDQ 混合精度失败（%s），降级为 FP16 重试" % type(exc).__name__)
            time.sleep(SLEEP)

    if not mixed_ok and fp16_nodes:
        try:
            run_fp16(staged, target, set(fp32_nodes))
            mixed_ok = True
        except Exception as exc:  # noqa: BLE001
            emit(70, "FP16 转换失败（%s），降级为原模型" % type(exc).__name__)
            time.sleep(SLEEP)

    if not mixed_ok:
        shutil.copyfile(str(staged), str(target))
        emit(80, "量化失败，已按原模型输出（FP32）")
        time.sleep(SLEEP)

    # 产物必须是合法 ONNX，否则如实失败
    try:
        produced = onnx.load(str(target), load_external_data=False)
        onnx.checker.check_model(produced)
    except Exception as exc:  # noqa: BLE001
        print("量化产物不是合法 ONNX: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    # 只要做了 INT8，就另留一份 FP16 版本给 ATC 兜底。
    #
    # 为什么不能只复制原模型：ATC 目前不接受 QDQ(INT8) 图（CANN 里没有
    # DequantizeLinear 插件），降级时要用这份。若方案是"全 INT8"、没有 FP16 层，
    # 按原逻辑会复制未量化的原模型 —— 用户拿到一个体积完全没变的 .om，
    # 与方案里承诺的压缩率对不上。这里统一转成 FP16：压缩做不到方案承诺的
    # 那么多，但至少真的压了。
    if mixed_ok and int8_nodes:
        try:
            run_fp16(staged, fallback, set())
        except Exception:  # noqa: BLE001 - 降级料缺失不影响主产物
            try:
                shutil.copyfile(str(staged), str(fallback))
            except Exception:  # noqa: BLE001
                fallback.unlink(missing_ok=True)

    if staged != source:
        staged.unlink(missing_ok=True)

    actual_int8 = sum(1 for node in produced.graph.node if node.op_type == "QuantizeLinear")
    emit(90, "写回量化权重（请求 INT8 %d 个，实际插入 QuantizeLinear %d 个）"
         % (len(int8_nodes), actual_int8))
    time.sleep(SLEEP)
    emit(100, "量化完成")
    time.sleep(SLEEP)


def _env_int(name: str, default: int) -> int:
    try:
        value = int(str(__import__("os").environ.get(name, "")).strip())
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    main()
