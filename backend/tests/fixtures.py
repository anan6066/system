"""测试夹具：手工搭一个确定性的 tiny ONNX 模型。

手工构建（onnx.helper + numpy）而不是用 torch 导出，原因：
  - 没有 torch 依赖，生成耗时 < 0.1s（torch 导出要 2~10s）
  - 权重由固定种子生成，跨运行逐字节一致
  - 层名刻意取 conv1/conv2/fc1，与预设层模板的"前缀直配"映射规则吻合

结构：Conv → Relu → Conv → Relu → GlobalAveragePool → Flatten → MatMul(+bias)
输入 (1,3,32,32)，输出 (1,10)，opset 13，约 6KB。
"""
from __future__ import annotations

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

TINY_INPUT = "images"
TINY_SHAPE = (1, 3, 32, 32)
TINY_SEED = 20240916
# 三个可被 layers.json 直配的节点名
TINY_LAYER_NAMES = ["conv1", "conv2", "fc1"]
# onnxruntime 1.23 支持的最高 IR 版本；onnx>=1.19 默认写更高的值
ORT_MAX_IR_VERSION = 10


def _conv_weight(rng, shape) -> np.ndarray:
    fan_in = shape[1] * shape[2] * shape[3]
    return (rng.standard_normal(shape) * np.sqrt(2.0 / fan_in)).astype(np.float32)


def build_tiny_onnx() -> bytes:
    """返回一个合法 tiny ONNX 模型的字节串（确定性）。"""
    rng = np.random.default_rng(TINY_SEED)

    conv1_w = _conv_weight(rng, (8, 3, 3, 3))
    conv2_w = _conv_weight(rng, (16, 8, 3, 3))
    fc1_w = (rng.standard_normal((16, 10)) * 0.1).astype(np.float32)

    initializers = [
        numpy_helper.from_array(conv1_w, "conv1.weight"),
        numpy_helper.from_array(np.zeros((8,), dtype=np.float32), "conv1.bias"),
        numpy_helper.from_array(conv2_w, "conv2.weight"),
        numpy_helper.from_array(np.zeros((16,), dtype=np.float32), "conv2.bias"),
        numpy_helper.from_array(fc1_w, "fc1.weight"),
        numpy_helper.from_array(np.zeros((10,), dtype=np.float32), "fc1.bias"),
    ]

    nodes = [
        helper.make_node("Conv", [TINY_INPUT, "conv1.weight", "conv1.bias"],
                         ["conv1_out"], name="conv1",
                         kernel_shape=[3, 3], pads=[1, 1, 1, 1], strides=[1, 1]),
        helper.make_node("Relu", ["conv1_out"], ["conv1_relu"], name="conv1_relu"),
        helper.make_node("Conv", ["conv1_relu", "conv2.weight", "conv2.bias"],
                         ["conv2_out"], name="conv2",
                         kernel_shape=[3, 3], pads=[1, 1, 1, 1], strides=[1, 1]),
        helper.make_node("Relu", ["conv2_out"], ["conv2_relu"], name="conv2_relu"),
        helper.make_node("GlobalAveragePool", ["conv2_relu"], ["gap_out"], name="gap"),
        helper.make_node("Flatten", ["gap_out"], ["flat_out"], name="flatten", axis=1),
        helper.make_node("MatMul", ["flat_out", "fc1.weight"], ["fc1_mm"], name="fc1"),
        helper.make_node("Add", ["fc1_mm", "fc1.bias"], ["output"], name="fc1_bias"),
    ]

    graph = helper.make_graph(
        nodes,
        "tiny_cnn",
        [helper.make_tensor_value_info(TINY_INPUT, TensorProto.FLOAT, list(TINY_SHAPE))],
        [helper.make_tensor_value_info("output", TensorProto.FLOAT, [1, 10])],
        initializer=initializers,
    )
    model = helper.make_model(
        graph,
        producer_name="quant-deploy-tests",
        opset_imports=[helper.make_opsetid("", 13)],
    )
    # onnx>=1.19 默认写 IR 13，而 onnxruntime 最高只认 IR 11 —— 不压回去
    # quantize_static 会在建标定 session 时报 "Unsupported model IR version"
    model.ir_version = ORT_MAX_IR_VERSION
    onnx.checker.check_model(model)
    return model.SerializeToString()


def write_tiny_onnx(path) -> str:
    """把 tiny ONNX 写到指定路径，返回路径字符串。"""
    data = build_tiny_onnx()
    with open(path, "wb") as handle:
        handle.write(data)
    return str(path)


def tiny_onnx_layers_json(layer_names=None) -> str:
    """与 tiny 模型配套的 layers.json 内容。"""
    import json

    names = layer_names or TINY_LAYER_NAMES
    return json.dumps(
        [{"name": name, "sizeKb": 1024, "kind": "fc" if name.startswith("fc") else "conv"}
         for name in names],
        ensure_ascii=False)
