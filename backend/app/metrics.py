"""性能指标估算（占位公式，与 algorithms/nsga2_search.py 保持一致）。

真实链路里延迟/内存/精度应由开发板上的 benchmark 实测
（config: deployment.bench_command）；未配置时用本模块估算，
响应里通过 metricsSource='estimated' 明确标注，避免把估算值当真机数据。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .layers import BIT_FACTOR

# 相对 FP32 的推理耗时系数
LAT_FACTOR: Dict[str, float] = {"INT8": 0.25, "FP16": 0.45, "FP32": 1.0}
# 各层量化到该位宽后的精度损失权重（乘以该层敏感度，单位：百分点）
ACC_LOSS_WEIGHT: Dict[str, float] = {"INT8": 13.0, "FP16": 2.0, "FP32": 0.0}
MS_PER_KB_FP32 = 0.004


def default_sensitivity(layers: List[Dict[str, Any]]) -> Dict[str, float]:
    """没有敏感度文件时的兜底：按层序号给一个确定性的中等敏感度。"""
    return {layer["name"]: 0.5 for layer in layers}


def read_sensitivity(workdir: Path) -> Dict[str, float]:
    """读 HAWQ 产出的 sensitivity.json：{layers: {层名: 敏感度}}。"""
    path = Path(workdir) / "sensitivity.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    layers = data.get("layers") if isinstance(data, dict) else None
    if not isinstance(layers, dict):
        return {}
    result = {}
    for name, value in layers.items():
        try:
            result[str(name)] = float(value)
        except (TypeError, ValueError):
            continue
    return result


def estimate_metrics(layers: List[Dict[str, Any]],
                     layer_config: Dict[str, str],
                     sensitivity: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """按层体积 + 位宽 + 敏感度估算体积/压缩率/延迟/精度损失。"""
    sensitivity = sensitivity or default_sensitivity(layers)
    original_kb = 0
    quantized_kb = 0
    latency_ms = 0.0
    loss_sum = 0.0
    counted = 0
    counts = {"INT8": 0, "FP16": 0, "FP32": 0}

    for layer in layers:
        name = layer["name"]
        size_kb = float(layer.get("sizeKb", 0))
        bit = str(layer_config.get(name, "FP32")).upper()
        factor = BIT_FACTOR.get(bit, 1.0)
        original_kb += int(size_kb)
        quantized_kb += int(round(size_kb * factor))
        latency_ms += size_kb * MS_PER_KB_FP32 * LAT_FACTOR.get(bit, 1.0)
        loss_sum += float(sensitivity.get(name, 0.5)) * ACC_LOSS_WEIGHT.get(bit, 0.0)
        counted += 1
        if bit in counts:
            counts[bit] += 1

    ratio = (1.0 - quantized_kb / original_kb) if original_kb else 0.0
    return {
        "sizeMb": round(quantized_kb / 1024.0, 2),
        "originalSizeMb": round(original_kb / 1024.0, 2),
        "compressionRatio": round(ratio, 4),
        "latencyMs": round(latency_ms, 2),
        "accuracyLossPct": round(loss_sum / counted, 2) if counted else 0.0,
        "int8Layers": counts["INT8"],
        "fp16Layers": counts["FP16"],
        "fp32Layers": counts["FP32"],
    }


def all_int8_config(layers: List[Dict[str, Any]]) -> Dict[str, str]:
    """全 INT8 基线方案（对比页的"传统量化"一列）。"""
    return {layer["name"]: "INT8" for layer in layers}


def estimate_deployment_metrics(layers: List[Dict[str, Any]],
                                layer_config: Dict[str, str],
                                sensitivity: Optional[Dict[str, float]] = None,
                                base_accuracy: float = 72.0) -> Dict[str, Any]:
    """部署后前端展示的三项指标：推理延迟(ms)/内存占用(MB)/Top-1 准确率(%)。"""
    estimated = estimate_metrics(layers, layer_config, sensitivity)
    size_mb = estimated["sizeMb"]
    memory_usage = round(size_mb * 18.0 + 120.0, 1)          # 权值驻留 + 运行时开销
    top1 = max(0.0, min(100.0, base_accuracy - estimated["accuracyLossPct"]))
    return {
        "inferenceSpeed": estimated["latencyMs"],
        "memoryUsage": memory_usage,
        "top1Accuracy": round(top1, 1),
    }


def build_comparison_rows(layers: List[Dict[str, Any]],
                          layer_config: Dict[str, str],
                          sensitivity: Optional[Dict[str, float]] = None,
                          base_accuracy: float = 72.0) -> List[Dict[str, Any]]:
    """前端 ComparisonResult[]：传统全 INT8 vs 混合精度。"""
    baseline = estimate_deployment_metrics(layers, all_int8_config(layers),
                                           sensitivity, base_accuracy)
    mixed = estimate_deployment_metrics(layers, layer_config, sensitivity, base_accuracy)
    return [
        {"metric": "Top-1 准确率 (%)", "traditionalINT8": baseline["top1Accuracy"],
         "mixedPrecision": mixed["top1Accuracy"], "unit": "%"},
        {"metric": "推理延迟 (ms)", "traditionalINT8": baseline["inferenceSpeed"],
         "mixedPrecision": mixed["inferenceSpeed"], "unit": "ms"},
        {"metric": "模型大小 (MB)", "traditionalINT8": estimate_metrics(layers, all_int8_config(layers), sensitivity)["sizeMb"],
         "mixedPrecision": estimate_metrics(layers, layer_config, sensitivity)["sizeMb"], "unit": "MB"},
        {"metric": "内存占用 (MB)", "traditionalINT8": baseline["memoryUsage"],
         "mixedPrecision": mixed["memoryUsage"], "unit": "MB"},
    ]
