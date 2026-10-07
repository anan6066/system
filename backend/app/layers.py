"""层信息工具：模型层模板、位宽视图、量化方案统计。

层数据的来源优先级：
1. 预设模型的层模板（presets.py）；
2. 若环境里装了 onnx，直接读 ONNX initializer 得到真实层名与权重规模；
3. 兜底：按文件大小确定性推导出一组层（保证同一模型每次结果一致）。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import presets

# 位宽 -> 相对体积系数（与 algorithms/nsga2_search.py 的占位公式保持一致）
BIT_FACTOR: Dict[str, float] = {"INT8": 0.25, "FP16": 0.5, "FP32": 1.0}
BITWIDTHS: List[str] = ["INT8", "FP16", "FP32"]

_GENERIC_NAMES = ["conv1", "conv2", "conv3", "conv4", "conv5", "fc1", "fc2", "fc3",
                  "fc4", "fc5"]


def _onnx_layers(path: str) -> Optional[List[Dict[str, Any]]]:
    """尽力从 ONNX 文件读层（onnx 未安装或文件非法时返回 None）。"""
    try:
        import onnx  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    try:
        graph = onnx.load(path, load_external_data=False).graph
    except Exception:  # noqa: BLE001
        return None
    layers: List[Dict[str, Any]] = []
    for initializer in graph.initializer:
        dims = [max(int(d), 1) for d in initializer.dims]
        # 只把权重张量当"层"：1D 的偏置向量不是层，混进来会让层数虚高
        # （真实模型动辄上百个 initializer，全是 bias 的话界面就没法看了）
        if len(dims) < 2:
            continue
        count = 1
        for dim in dims:
            count *= dim
        layers.append({
            "name": initializer.name,
            "sizeKb": max(int(count * 4 / 1024), 1),   # 4 bytes/weight 近似
            "kind": "fc" if len(dims) <= 2 else "conv",
        })
    return layers or None


def guess_layers(file_size_bytes: int, count: int = 8) -> List[Dict[str, Any]]:
    """按文件大小确定性推导层列表（兜底路径，无随机）。"""
    names = _GENERIC_NAMES[:count]
    total_kb = max(int((file_size_bytes or 0) / 1024), count * 16)
    weights = [float((count - i) ** 2) for i in range(count)]
    weight_sum = sum(weights)
    layers = []
    for index, name in enumerate(names):
        size_kb = max(int(total_kb * 0.85 * weights[index] / weight_sum), 16)
        layers.append({"name": name, "sizeKb": size_kb,
                       "kind": "fc" if name.startswith("fc") else "conv"})
    return layers


def model_layers(model: Any) -> List[Dict[str, Any]]:
    """取某个 Model 记录的层列表。"""
    preset = presets.get_preset(model.preset) if getattr(model, "preset", None) else None
    if preset:
        return [dict(layer) for layer in preset["layers"]]
    if getattr(model, "filePath", None):
        parsed = _onnx_layers(model.filePath)
        if parsed:
            return parsed
    return guess_layers(getattr(model, "fileSize", 0) or 0)


def write_layers_json(workdir: Path, layers: List[Dict[str, Any]]) -> Path:
    path = Path(workdir) / "layers.json"
    path.write_text(json.dumps(layers, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_layers_json(workdir: Path) -> List[Dict[str, Any]]:
    path = Path(workdir) / "layers.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def scheme_layer_view(layers: List[Dict[str, Any]],
                      layer_config: Dict[str, str]) -> List[Dict[str, Any]]:
    """把 {层名: 位宽} 展开成前端 QuantizationLayer[]（含原/量化后体积 KB）。"""
    view = []
    for layer in layers:
        bit = str(layer_config.get(layer["name"], "FP32")).upper()
        factor = BIT_FACTOR.get(bit, 1.0)
        original = int(layer.get("sizeKb", 0))
        view.append({
            "name": layer["name"],
            "type": bit,
            "originalSize": original,
            "quantizedSize": int(round(original * factor)),
        })
    return view


def scheme_summary(layer_view: List[Dict[str, Any]]) -> Dict[str, Any]:
    """统计 INT8/FP16/FP32 层数与压缩率（前端"压缩率"卡片直接用）。"""
    original = sum(item["originalSize"] for item in layer_view)
    quantized = sum(item["quantizedSize"] for item in layer_view)
    ratio = (1.0 - quantized / original) if original else 0.0
    return {
        "int8Layers": sum(1 for item in layer_view if item["type"] == "INT8"),
        "fp16Layers": sum(1 for item in layer_view if item["type"] == "FP16"),
        "fp32Layers": sum(1 for item in layer_view if item["type"] == "FP32"),
        "originalSizeKb": original,
        "quantizedSizeKb": quantized,
        "compressionRatio": round(ratio, 4),
    }
