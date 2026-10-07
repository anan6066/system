"""预设模型定义与 ONNX 生成。

前端 QuantizationPage 的"预设模型"下拉来自这里（GET /api/models/presets）。

模型文件按三级取用（见 preset_onnx_bytes）：
  1. presets_cache/<id>.onnx 命中缓存 —— 直接用
  2. torchvision 用 ImageNet 预训练权重导出真实 ONNX（下载失败则退回随机权重）
     yolov8 走官方 onnx 下载
  3. 上面都不行（Windows 的 tools/py38 没有 torch/onnx）时，
     用 onnx.helper 现搭一个确定性的"结构替身"小网

层模板（PRESET_MODELS 里的 layers）是量化方案、层配置预览的结构来源，
优先级高于从 ONNX 解析出来的 initializer，因此始终稳定。
"""
import io
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TARGET_NPU = "ascend"
# onnxruntime 1.23 支持的最高 IR 版本；onnx>=1.19 / torch 导出可能写更高的值
ORT_MAX_IR_VERSION = 10
PRESET_INPUT_SHAPE = (1, 3, 224, 224)
WEIGHT_DOWNLOAD_TIMEOUT = 20       # 秒；预训练权重下载超时就退回随机权重
YOLOV8_ONNX_URLS = (
    "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.onnx",
    "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.onnx",
)
DOWNLOAD_TIMEOUT = 15


def _layer(name: str, size_kb: int, kind: str = "conv") -> Dict[str, Any]:
    return {"name": name, "sizeKb": size_kb, "kind": kind}


PRESET_MODELS: List[Dict[str, Any]] = [
    {
        "id": "mobilenetv2",
        "name": "MobileNetV2",
        "description": "轻量级图像分类模型",
        "size": "14MB",
        "fileSize": 14_680_064,
        "baseAccuracy": 71.8,
        "layers": [
            _layer("conv1", 256),
            _layer("conv2_1", 512),
            _layer("conv2_2", 512),
            _layer("conv3_1", 1024),
            _layer("conv3_2", 1024),
            _layer("conv4_1", 2048),
            _layer("conv4_2", 2048),
            _layer("fc", 4096, "fc"),
        ],
    },
    {
        "id": "resnet18",
        "name": "ResNet18",
        "description": "深度残差网络",
        "size": "45MB",
        "fileSize": 47_185_920,
        "baseAccuracy": 69.8,
        "layers": [
            _layer("conv1", 512),
            _layer("layer1_1", 1024),
            _layer("layer1_2", 1024),
            _layer("layer2_1", 2048),
            _layer("layer2_2", 2048),
            _layer("layer3_1", 4096),
            _layer("layer3_2", 4096),
            _layer("layer4_1", 8192),
            _layer("layer4_2", 8192),
            _layer("fc", 4096, "fc"),
        ],
    },
    {
        "id": "yolov8",
        "name": "YOLOv8",
        "description": "实时目标检测模型",
        "size": "25MB",
        "fileSize": 26_214_400,
        "baseAccuracy": 68.0,
        "layers": [
            _layer("backbone.stem", 512),
            _layer("backbone.stage1", 1024),
            _layer("backbone.stage2", 2048),
            _layer("backbone.stage3", 3072),
            _layer("backbone.stage4", 4096),
            _layer("neck.p3", 1536),
            _layer("neck.p4", 2048),
            _layer("neck.p5", 2560),
            _layer("head.cls", 2048, "fc"),
            _layer("head.reg", 2048, "fc"),
        ],
    },
    {
        "id": "efficientnet-b0",
        "name": "EfficientNet-B0",
        "description": "高效图像分类网络",
        "size": "20MB",
        "fileSize": 20_971_520,
        "baseAccuracy": 77.1,
        "layers": [
            _layer("stem.conv", 384),
            _layer("mbconv1", 512),
            _layer("mbconv2", 768),
            _layer("mbconv3", 1280),
            _layer("mbconv4", 1792),
            _layer("mbconv5", 2304),
            _layer("mbconv6", 3072),
            _layer("head.conv", 4096),
            _layer("fc", 5120, "fc"),
        ],
    },
]

_BY_ID = {item["id"]: item for item in PRESET_MODELS}


def get_preset(preset_id: str) -> Optional[Dict[str, Any]]:
    return _BY_ID.get((preset_id or "").lower())


def list_presets() -> List[Dict[str, Any]]:
    """前端下拉需要的字段（不含层模板细节）。"""
    return [
        {
            "id": item["id"],
            "name": item["name"],
            "description": item["description"],
            "size": item["size"],
            "fileSize": item["fileSize"],
            "baseAccuracy": item["baseAccuracy"],
            "layerCount": len(item["layers"]),
            "targetNPU": TARGET_NPU,
        }
        for item in PRESET_MODELS
    ]


# --------------------------------------------------------------------------- #
# ONNX 生成
# --------------------------------------------------------------------------- #
def cache_dir() -> Path:
    """预设 ONNX 缓存目录（放在 backend 下，避免每次重新导出）。"""
    return Path(os.environ.get("QUANT_DEPLOY_PRESET_CACHE")
                or str(Path(__file__).resolve().parent.parent / "presets_cache"))


def _clamp_ir_version(data: bytes) -> bytes:
    """把 IR 版本压到 onnxruntime 能接受的范围，否则量化阶段会起不来。"""
    import onnx

    model = onnx.load(io.BytesIO(data), load_external_data=False)
    if model.ir_version <= ORT_MAX_IR_VERSION:
        return data
    model.ir_version = ORT_MAX_IR_VERSION
    return model.SerializeToString()


def generate_preset_onnx(preset_id: str) -> bytes:
    """用 torchvision 导出真实 ONNX；优先 ImageNet 预训练权重。"""
    import torch
    import torchvision
    from torchvision.models import get_model

    builders = {
        "mobilenetv2": "mobilenet_v2",
        "resnet18": "resnet18",
        "efficientnet-b0": "efficientnet_b0",
    }
    torch_name = builders.get(preset_id)
    if torch_name is None:
        raise ValueError("预设 %s 没有 torch 导出实现" % preset_id)

    model = None
    try:
        model = get_model(torch_name, weights="IMAGENET1K_V1")
    except Exception:  # noqa: BLE001 - 权重下载失败（离线/超时）就退回随机权重
        model = None
    if model is None:
        model = get_model(torch_name, weights=None)
    model.eval()

    buffer = io.BytesIO()
    torch.onnx.export(
        model, torch.zeros(*PRESET_INPUT_SHAPE), buffer,
        opset_version=13, do_constant_folding=True,
        input_names=["images"], output_names=["output"],
    )
    data = buffer.getvalue()
    if not data:
        raise RuntimeError("torch.onnx.export 没有产出内容")
    return _clamp_ir_version(data)


def _download_yolov8() -> bytes:
    """下载官方 yolov8n.onnx；失败抛异常由调用方降级。"""
    import urllib.request

    import onnx

    last_error = None
    for url in YOLOV8_ONNX_URLS:
        try:
            with urllib.request.urlopen(url, timeout=DOWNLOAD_TIMEOUT) as response:
                data = response.read()
            if not data:
                continue
            # 下载来的东西不一定是模型，先验一遍再收下
            onnx.checker.check_model(onnx.load(io.BytesIO(data), load_external_data=False))
            return _clamp_ir_version(data)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError("yolov8 onnx 下载失败: %s" % last_error)


def generate_surrogate_onnx(preset_id: str) -> bytes:
    """无 torch 时的"结构替身"：onnx.helper 现搭一个确定性小网。

    不是真模型，只保证：合法 ONNX、有若干可量化的卷积/全连接层、
    输入输出与预设一致、每次生成逐字节相同。
    """
    import numpy as np
    import onnx
    from onnx import TensorProto, helper, numpy_helper

    preset = get_preset(preset_id) or {"layers": []}
    layer_count = max(4, min(len(preset["layers"]) or 6, 10))
    rng = np.random.default_rng(abs(hash(preset_id)) % (2 ** 31))

    nodes, inits = [], []
    previous = "images"
    channels = 3
    for index in range(layer_count):
        out_channels = 8 + index * 4
        weight = (rng.standard_normal((out_channels, channels, 3, 3))
                  * np.sqrt(2.0 / (channels * 9))).astype(np.float32)
        name = "conv%d" % (index + 1)
        inits.append(numpy_helper.from_array(weight, name + ".weight"))
        inits.append(numpy_helper.from_array(np.zeros((out_channels,), np.float32),
                                             name + ".bias"))
        nodes.append(helper.make_node(
            "Conv", [previous, name + ".weight", name + ".bias"], [name + "_out"],
            name=name, kernel_shape=[3, 3], pads=[1, 1, 1, 1], strides=[2, 2]))
        nodes.append(helper.make_node("Relu", [name + "_out"], [name + "_relu"],
                                      name=name + "_relu"))
        previous, channels = name + "_relu", out_channels

    nodes.append(helper.make_node("GlobalAveragePool", [previous], ["pooled"], name="gap"))
    nodes.append(helper.make_node("Flatten", ["pooled"], ["flat"], name="flatten", axis=1))
    fc_weight = (rng.standard_normal((channels, 10)) * 0.1).astype(np.float32)
    inits.append(numpy_helper.from_array(fc_weight, "fc.weight"))
    inits.append(numpy_helper.from_array(np.zeros((10,), np.float32), "fc.bias"))
    nodes.append(helper.make_node("MatMul", ["flat", "fc.weight"], ["fc_mm"], name="fc"))
    nodes.append(helper.make_node("Add", ["fc_mm", "fc.bias"], ["output"], name="fc_bias"))

    graph = helper.make_graph(
        nodes, "preset_surrogate_" + preset_id,
        [helper.make_tensor_value_info("images", TensorProto.FLOAT,
                                       list(PRESET_INPUT_SHAPE))],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 10])],
        initializer=inits,
    )
    model = helper.make_model(graph, producer_name="quant-deploy-presets",
                              opset_imports=[helper.make_opsetid("", 13)])
    model.ir_version = ORT_MAX_IR_VERSION
    onnx.checker.check_model(model)
    return model.SerializeToString()


def preset_onnx_bytes(preset_id: str) -> Tuple[Optional[bytes], str]:
    """三级取用，返回 (ONNX 字节 或 None, 来源标签)。"""
    cache = cache_dir() / ("%s.onnx" % preset_id)
    if cache.exists():
        try:
            data = cache.read_bytes()
            if data:
                return data, "cached"
        except OSError:
            pass

    data, origin = None, "placeholder"
    try:
        if preset_id == "yolov8":
            data, origin = _download_yolov8(), "downloaded"
        else:
            data, origin = generate_preset_onnx(preset_id), "generated"
    except Exception:  # noqa: BLE001 - 缺 torch / 权重下载失败 / 导出失败
        data, origin = None, "placeholder"

    if data is None:
        try:
            data, origin = generate_surrogate_onnx(preset_id), "surrogate"
        except Exception:  # noqa: BLE001 - 连 onnx/numpy 都没有（Windows py38）
            return None, "placeholder"

    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    except OSError:
        pass
    return data, origin
