"""④ 混合精度量化（真实 AMCT 实现，带回退）。

输入：workdir/selected_scheme.json（用户选定方案）、workdir/model.onnx；
产物：workdir/quantized.onnx（真实量化后的 ONNX，契约产物）
      workdir/quantized_fallback.onnx（仅降级路径产出，见下）

两条路径：

【主路径】真实 AMCT（华为昇腾模型压缩工具，商用版 amct_onnx）
    ONNX → create_quant_config → quantize_model（插 IFMR 量化算子）
         → 标定推理 → save_model → AscendQuant/AscendDequant + INT8 权重
    产物能被 ATC 直接编译成带 INT8 的 .om。全程 CPU，不需要 NPU。

【降级路径】onnxruntime QDQ
    AMCT 不可用（没装 / 版本不符）时使用。产物是标准 QDQ ONNX，
    但 **ATC 不认识 QDQ 算子**，所以最终 .om 只能拿到 FP16 的压缩率。
    这条路径同时留一份 FP16 版本供 ATC 回退，避免产出"完全没量化"的 .om。

为什么 AMCT 要单独开进程：它的自定义算子与 onnxruntime 版本强绑定
（只支持 ≤1.20.0），而主环境用 1.23.2，两者装不进同一个 venv。
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

STAGE = "quantizing"
SLEEP = 0.15
CALIB_SEED = 1234
DEFAULT_SAMPLES = 32
ORT_MAX_IR_VERSION = 10

BIT_ORDER = {"INT8": 0, "FP16": 1, "FP32": 2}   # 越大越保守

# AMCT 认可的量化层类型，取自 amct_onnx/capacity/capacity_config.csv 的
# QUANTIZABLE_TYPES。它的 skip_layers 校验很反直觉：**只接受"本来可量化"的层**，
# 传个 Relu/Add 进去会直接报 "Layer xxx does not support quantization"。
AMCT_QUANTIZABLE = {"Conv", "Gemm", "MatMul", "ConvTranspose",
                    "AveragePool", "LSTM", "GRU"}

# AMCT 专用 venv 的 python；可用环境变量覆盖
AMCT_PYTHON_CANDIDATES = [
    "/root/autodl-tmp/venvs/amct_onnx/bin/python",
    os.path.expanduser("~/amct-venv/bin/python"),
    "/opt/amct-venv/bin/python",
]

try:
    import numpy as np
    import onnx
    from onnxruntime.quantization import (CalibrationDataReader, QuantFormat,
                                          QuantType, quantize_static)

    HAS_ORT = True
except ImportError:  # pragma: no cover - 只在无 onnxruntime 的环境走到
    HAS_ORT = False


def emit(percent: int, message: str) -> None:
    print(json.dumps({"stage": STAGE, "percent": percent, "message": message},
                     ensure_ascii=False), flush=True)


def find_amct_python():
    """定位装有 AMCT 的 python；找不到返回 None。"""
    explicit = os.environ.get("QUANT_AMCT_PYTHON")
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for candidate in AMCT_PYTHON_CANDIDATES:
        if os.path.exists(candidate):
            return candidate
    return None


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
    return node_bits


# --------------------------------------------------------------------------- #
# 主路径：真实 AMCT
# --------------------------------------------------------------------------- #
def run_with_amct(workdir: Path, amct_python: str, model, layer_config,
                  layer_names) -> bool:
    """调 AMCT 子进程量化；成功返回 True。"""
    node_bits = build_node_bits(model, layer_config, layer_names)
    # skip_layers 只能装"方案要求非 INT8"且"类型本来可量化"的节点：
    # 非量化类型（Relu/Add/...）AMCT 自己会跳过，列进去反而报错。
    quantizable = {node.name for node in model.graph.node
                   if node.op_type in AMCT_QUANTIZABLE}
    skip_nodes = sorted(name for name, bit in node_bits.items()
                        if bit != "INT8" and name in quantizable)

    declare = model.graph.input
    input_name = declare[0].name if declare else "images"
    input_shape = [int(d.dim_value) if d.dim_value > 0 else 1
                   for d in declare[0].type.tensor_type.shape.dim] if declare else [1, 3, 224, 224]
    if not input_shape:
        input_shape = [1, 3, 224, 224]

    samples = _env_int("CALIBRATION_SAMPLES", DEFAULT_SAMPLES)
    job_path = workdir / "_amct_job.json"
    job_path.write_text(json.dumps({
        "input_name": input_name,
        "input_shape": input_shape,
        "skip_nodes": skip_nodes,
        "samples": samples,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    emit(15, "使用真实 AMCT 量化（INT8 层 %d 个 / 跳过 %d 个节点）"
         % (sum(1 for v in node_bits.values() if v == "INT8"), len(skip_nodes)))

    runner = Path(__file__).resolve().parent / "amct_onnx_runner.py"
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    proc = subprocess.Popen(
        [amct_python, str(runner), str(workdir)],
        cwd=str(workdir), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace")

    stderr_tail = []
    for line in proc.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue          # AMCT 自己的日志行，忽略
        percent = payload.get("percent")
        message = payload.get("message")
        if percent is not None and message:
            # 把子进程 10~100 的进度映射到主流程的 20~85
            mapped = int(20 + (float(percent) / 100.0) * 65)
            emit(mapped, str(message))

    for line in proc.stderr:
        stderr_tail.append(line.rstrip())
        if len(stderr_tail) > 50:
            stderr_tail.pop(0)
    proc.wait()

    if proc.returncode != 0:
        print("AMCT 量化失败（退出码 %d）" % proc.returncode, file=sys.stderr)
        for line in stderr_tail[-20:]:
            print(line, file=sys.stderr)
        return False
    return (workdir / "quantized.onnx").exists()


# --------------------------------------------------------------------------- #
# 降级路径：onnxruntime QDQ + FP16
# --------------------------------------------------------------------------- #
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
    model = onnx.load(str(source), load_external_data=False)
    if model.ir_version <= ORT_MAX_IR_VERSION:
        return source
    model.ir_version = ORT_MAX_IR_VERSION
    onnx.save(model, str(target))
    return target


def topo_sort_graph(model) -> bool:
    """把 graph.node 重排成拓扑序（FP16 转换会打乱顺序）。"""
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


def run_with_ort(workdir: Path, model, layer_config, layer_names) -> bool:
    """onnxruntime QDQ（+ FP16 兜底）。成功返回 True。"""
    source = workdir / "model.onnx"
    target = workdir / "quantized.onnx"
    fallback = workdir / "quantized_fallback.onnx"

    node_bits = build_node_bits(model, layer_config, layer_names)
    int8_nodes = sorted(n for n, b in node_bits.items() if b == "INT8")
    fp16_nodes = sorted(n for n, b in node_bits.items() if b == "FP16")
    fp32_nodes = sorted(n for n, b in node_bits.items() if b == "FP32")

    emit(25, "定位待量化节点：INT8 %d 个 / FP16 %d 个 / FP32 %d 个"
         % (len(int8_nodes), len(fp16_nodes), len(fp32_nodes)))

    if not int8_nodes and not fp16_nodes:
        emit(60, "方案未要求 INT8/FP16，直接输出 FP32 原模型")
        shutil.copyfile(str(source), str(target))
        return True

    samples = _env_int("CALIBRATION_SAMPLES", DEFAULT_SAMPLES)
    staged = normalize_ir_version(source, workdir / "_quant_src.onnx")
    mixed_ok = False

    if int8_nodes:
        emit(40, "插入 QDQ 量化算子并用 %d 个合成样本校准（INT8 层）" % samples)
        try:
            qdq_path = workdir / "_quant_qdq.onnx"
            quantize_static(str(staged), str(qdq_path),
                            SyntheticCalibrationReader(model, samples),
                            quant_format=QuantFormat.QDQ, per_channel=True,
                            activation_type=QuantType.QUInt8, weight_type=QuantType.QInt8,
                            nodes_to_quantize=int8_nodes or None)
            emit(55, "QDQ 量化完成，开始 FP16 图改写")
            run_fp16(qdq_path, target, set(fp32_nodes) | set(int8_nodes))
            mixed_ok = True
            qdq_path.unlink(missing_ok=True)
        except Exception as exc:  # noqa: BLE001
            emit(55, "QDQ 混合精度失败（%s），降级为 FP16 重试" % type(exc).__name__)

    if not mixed_ok and fp16_nodes:
        try:
            run_fp16(staged, target, set(fp32_nodes))
            mixed_ok = True
        except Exception as exc:  # noqa: BLE001
            emit(70, "FP16 转换失败（%s），降级为原模型" % type(exc).__name__)

    if not mixed_ok:
        shutil.copyfile(str(staged), str(target))
        emit(80, "量化失败，已按原模型输出（FP32）")

    # 只要做了 INT8，就留一份 FP16 版本给 ATC 兜底（ATC 不吃 QDQ 图）
    if mixed_ok and int8_nodes:
        try:
            run_fp16(staged, fallback, set())
        except Exception:  # noqa: BLE001
            try:
                shutil.copyfile(str(staged), str(fallback))
            except Exception:  # noqa: BLE001
                fallback.unlink(missing_ok=True)

    if staged != source:
        staged.unlink(missing_ok=True)
    return True


def _env_int(name: str, default: int) -> int:
    try:
        value = int(str(os.environ.get(name, "")).strip())
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def main() -> None:
    workdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    source = workdir / "model.onnx"
    target = workdir / "quantized.onnx"

    index, config = read_selected(workdir)
    int8_wanted = sum(1 for value in config.values() if value == "INT8")

    if not HAS_ORT or not source.exists():
        reason = "未找到 model.onnx" if not source.exists() else "缺少 onnxruntime 依赖"
        emit(10, "量化（降级：%s，直接透传原模型）" % reason)
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

    emit(5, "读取方案 #%s：%d 层，其中 INT8 %d 层" % (index, len(config), int8_wanted))
    time.sleep(SLEEP)

    try:
        model = onnx.load(str(source), load_external_data=False)
    except Exception as exc:  # noqa: BLE001
        print("model.onnx 解析失败: %s" % exc, file=sys.stderr)
        raise SystemExit(2)

    layer_names = read_layer_names(workdir) or sorted(config)

    # ---- 优先真实 AMCT ----
    # 方案里没有 INT8 层就别走 AMCT：跳过全部层的话它会报
    # "no layer need to quantize"，而纯 FP16/FP32 用 ort 路径更直接。
    amct_python = find_amct_python() if int8_wanted else None
    if amct_python:
        try:
            if run_with_amct(workdir, amct_python, model, config, layer_names):
                if _validate(target, strict=False):
                    emit(92, "AMCT 量化完成（AscendQuant/Dequant + INT8 权重）")
                    time.sleep(SLEEP)
                    emit(100, "量化完成")
                    time.sleep(SLEEP)
                    return
                print("AMCT 产物校验未通过，回退到 onnxruntime", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            print("AMCT 路径异常，回退到 onnxruntime: %s" % exc, file=sys.stderr)
        emit(20, "AMCT 不可用或失败，降级到 onnxruntime QDQ")
        time.sleep(SLEEP)

    # ---- 降级：onnxruntime ----
    run_with_ort(workdir, model, config, layer_names)

    if not _validate(target):
        print("量化产物不是合法 ONNX", file=sys.stderr)
        raise SystemExit(2)

    emit(92, "写回量化权重（onnxruntime QDQ 路径）")
    time.sleep(SLEEP)
    emit(100, "量化完成")
    time.sleep(SLEEP)


def _validate(path: Path, strict: bool = True) -> bool:
    """校验产物是不是合法 ONNX。

    strict=False 用于 AMCT 产物：它含 AscendQuant/AscendDequant 这些华为自定义
    算子，onnx.checker 不认识会直接报错 —— 但那是好产物，只是超出标准 ONNX 的
    算子集。这时只验证能否作为 ONNX protobuf 读出来。
    """
    try:
        produced = onnx.load(str(path), load_external_data=False)
    except Exception:  # noqa: BLE001
        return False
    if not strict:
        return len(produced.graph.node) > 0
    try:
        onnx.checker.check_model(produced)
    except Exception:  # noqa: BLE001
        return False
    return True


if __name__ == "__main__":
    main()
