"""① HAWQ 敏感度分析（真实实现）。

协议：stdout 输出 JSONL 进度行 {"stage","percent","message"}；
输入：workdir/layers.json（层名与体积，缺失时用内置层表兜底）、workdir/model.onnx；
产物：workdir/sensitivity.json = {"layers": {层名: 敏感度}, "generatedAt": ...}。

敏感度算法 —— 权重的**谱范数代理**：
  HAWQ 用 Hessian 谱衡量各层对量化的敏感程度。完整 Hessian 需要真实标定数据
  与反传，代价高且依赖框架。这里用每层权重矩阵的最大奇异值（谱范数）做代理：
  分段线性网络的 Hessian 迹与权重谱范数同阶，谱范数越大，同样的权重量化噪声
  被放得越大 —— 与 HAWQ "谱越大越敏感" 的排序结论一致。
  纯 numpy 幂迭代，无 torch 依赖，且由固定种子保证可复现。

依赖缺失（如 Windows 的 tools/py38 没有 numpy/onnx）时回退到层名 md5 派生，
保持演示链路可用；真实 ONNX 存在但解析失败则非零退出，让任务如实失败。
"""
import hashlib
import json
import sys
import time
from pathlib import Path

STAGE = "sensitivity_analysis"
SLEEP = 0.15
DEFAULT_LAYERS = ["conv1", "conv2", "conv3", "conv4", "conv5", "fc1", "fc2"]
POWER_ITER = 12
LOW_BOUND, HIGH_BOUND = 0.05, 0.95
NEUTRAL = 0.5

try:
    import numpy as np
    import onnx
    from onnx import numpy_helper

    HAS_ONNX = True
except ImportError:  # pragma: no cover - 只在无科学计算栈的环境走到
    HAS_ONNX = False


def emit(percent: int, message: str) -> None:
    print(json.dumps({"stage": STAGE, "percent": percent, "message": message},
                     ensure_ascii=False), flush=True)


def load_layer_names(workdir: Path):
    path = workdir / "layers.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            names = [str(item["name"]) for item in data if isinstance(item, dict) and "name" in item]
            if names:
                return names
        except (ValueError, OSError, KeyError, TypeError):
            pass
    return list(DEFAULT_LAYERS)


def sensitivity_of(name: str) -> float:
    """层名 -> [0.15, 0.95] 的确定性敏感度（无 ONNX 依赖时的降级路径）。"""
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return round(0.15 + (int(digest[:8], 16) % 1000) / 1000.0 * 0.8, 4)


def spectral_norm(weights, iters: int = POWER_ITER, seed: int = 0):
    """幂迭代求矩阵最大奇异值；不适用（1D 偏置、退化形状）返回 None。"""
    if weights is None or getattr(weights, "ndim", 0) < 2:
        return None
    matrix = weights.reshape(weights.shape[0], -1).astype(np.float64)
    if matrix.shape[0] < 2 or matrix.shape[1] < 2 or matrix.size < 4:
        return None
    rng = np.random.default_rng(seed)
    vector = rng.standard_normal(matrix.shape[1])
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return 0.0
    vector /= norm
    sigma = 0.0
    for _ in range(iters):
        forward = matrix @ vector
        forward_norm = float(np.linalg.norm(forward))
        if forward_norm == 0.0:
            return 0.0
        backward = matrix.T @ (forward / forward_norm)
        backward_norm = float(np.linalg.norm(backward))
        if backward_norm == 0.0:
            return 0.0
        vector = backward / backward_norm
        sigma = float(np.linalg.norm(matrix @ vector))
    return sigma


def collect_initializer_names(model):
    """按"图中首次被节点引用"的顺序收集 initializer 名（保证分桶稳定）。"""
    declared = {init.name for init in model.graph.initializer}
    ordered, seen = [], set()
    for node in model.graph.node:
        for name in node.input:
            if name in declared and name not in seen:
                seen.add(name)
                ordered.append(name)
    # 未被任何节点引用的残留 initializer 按声明顺序补在后面
    for init in model.graph.initializer:
        if init.name not in seen:
            seen.add(init.name)
            ordered.append(init.name)
    return ordered


def _belongs(initializer: str, layer: str) -> bool:
    """conv1.weight / conv1 都算属于层 conv1。"""
    return initializer == layer or initializer.startswith(layer + ".")


def map_initializers(ordered_names, layer_names):
    """把 initializer 归到层上 -> {层名: [initializer, ...]}。

    规则（与 amct_quantize.py 保持一致的映射语义）：
      1. 前缀直配：conv1.weight -> conv1
      2. 一层都没配上（预设模板名 vs 真实 initializer 名）时，
         按顺序把 initializer 切成 len(layer_names) 个连续桶
      3. 部分配上时，剩下的分给"没有直配成果"的层
    """
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

    if len(empty) == len(layer_names):
        # 完全对不上：整体连续分桶
        total = len(unmatched)
        for position, layer in enumerate(layer_names):
            start = position * total // len(layer_names)
            end = (position + 1) * total // len(layer_names)
            buckets[layer] = unmatched[start:end]
    else:
        total = len(unmatched)
        for position, layer in enumerate(empty):
            start = position * total // len(empty)
            end = (position + 1) * total // len(empty)
            buckets[layer] = unmatched[start:end]
    return buckets


def normalize(scores):
    """谱范数 -> [LOW_BOUND, HIGH_BOUND] 的敏感度；退化时全体中性值。"""
    values = [value for value in scores.values() if value is not None]
    if not values:
        return {name: NEUTRAL for name in scores}
    low, high = min(values), max(values)
    if high - low < 1e-12:
        return {name: NEUTRAL for name in scores}
    return {
        name: round(LOW_BOUND + (value - low) / (high - low) * (HIGH_BOUND - LOW_BOUND), 4)
        if value is not None else NEUTRAL
        for name, value in scores.items()
    }


def analyze(workdir: Path, names):
    """返回 {层名: 敏感度}；model.onnx 解析失败抛 ValueError。"""
    model = onnx.load(str(workdir / "model.onnx"), load_external_data=False)

    ordered = collect_initializer_names(model)
    by_name = {init.name: init for init in model.graph.initializer}
    buckets = map_initializers(ordered, names)

    raw = {}
    for layer in names:
        best = None
        for init_name in buckets.get(layer, []):
            try:
                # to_array 会复制一份权重，用完立即释放，控制大模型的内存峰值
                weights = numpy_helper.to_array(by_name[init_name])
                sigma = spectral_norm(weights)
                del weights
            except Exception:  # noqa: BLE001 - 单个张量坏了不影响其它层
                sigma = None
            if sigma is not None and (best is None or sigma > best):
                best = sigma
        raw[layer] = best
    return normalize(raw)


def main() -> None:
    workdir = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    model_path = workdir / "model.onnx"
    emit(10, "加载 ONNX 模型")
    time.sleep(SLEEP)
    names = load_layer_names(workdir)
    emit(35, "识别网络层结构（%d 层）" % len(names))
    time.sleep(SLEEP)

    if HAS_ONNX and model_path.exists():
        emit(60, "计算各层权重谱范数（Hessian 代理）")
        try:
            layers = analyze(workdir, names)
        except Exception as exc:  # noqa: BLE001 - ONNX 损坏时如实失败
            print("model.onnx 解析失败: %s" % exc, file=sys.stderr)
            raise SystemExit(2)
        emit(80, "权重谱范数计算完毕（%d 层）" % len(layers))
    else:
        reason = "未找到 model.onnx" if not model_path.exists() else "缺少 numpy/onnx 依赖"
        emit(60, "计算各层 Hessian 谱（降级：层名派生敏感度，%s）" % reason)
        time.sleep(SLEEP)
        layers = {name: sensitivity_of(name) for name in names}

    (workdir / "sensitivity.json").write_text(
        json.dumps({"layers": layers,
                    "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    emit(90, "汇总敏感度排名")
    time.sleep(SLEEP)
    emit(100, "敏感度分析完成")
    time.sleep(SLEEP)


if __name__ == "__main__":
    main()
