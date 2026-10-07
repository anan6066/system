"""四个算法脚本的冒烟测试：验证 JSONL 协议与产物格式。

脚本用当前解释器拉起，不依赖 app 包（脚本与 Web 隔离）。

真实算法落地后这里有两类用例：
  * 协议类 —— 进度行、产物文件名、结构化字段。任何环境都能跑。
  * 算法类 —— 真的解析 ONNX / 真的量化。需要 numpy/onnx/pymoo/onnxruntime，
    Windows 的 tools/py38 没有，自动 skip（那条链路走脚本内置的降级路径，
    由 test_pipeline 覆盖）。
"""
import json
from pathlib import Path

import onnx
import pytest

from app.executor import run_script
from tests.conftest import requires_atc, requires_toolchain
from tests.fixtures import (TINY_LAYER_NAMES, build_tiny_onnx,
                            tiny_onnx_layers_json)

REPO = Path(__file__).resolve().parents[1]
ALGO = REPO / "algorithms"
# 标定样本给个最小值就够验证链路，省时间
FAST_ENV = {"CALIBRATION_SAMPLES": "4"}


def _write_tiny(workdir, layers=True):
    (workdir / "model.onnx").write_bytes(build_tiny_onnx())
    if layers:
        (workdir / "layers.json").write_text(tiny_onnx_layers_json(), encoding="utf-8")


# --------------------------------------------------------------------------- #
# ① 敏感度分析
# --------------------------------------------------------------------------- #
@requires_toolchain
def test_hawq_script(tmp_path):
    _write_tiny(tmp_path)
    progress = []
    code, tail = run_script(ALGO / "hawq_sensitivity.py", tmp_path,
                            lambda s, p, m: progress.append((s, p, m)))
    assert code == 0, tail
    assert progress[-1] == ("sensitivity_analysis", 100, "敏感度分析完成")
    assert [item[0] for item in progress] == ["sensitivity_analysis"] * len(progress)

    doc = json.loads((tmp_path / "sensitivity.json").read_text(encoding="utf-8"))
    assert set(doc["layers"]) == set(TINY_LAYER_NAMES)
    assert all(0.0 <= value <= 1.0 for value in doc["layers"].values())
    # 谱范数是实数计算，不该出现"每个层都一个样"的退化结果
    assert len(set(doc["layers"].values())) > 1

    # 同一份模型两次跑出的敏感度必须一致（否则方案会随机漂移）
    again = run_script(ALGO / "hawq_sensitivity.py", tmp_path, lambda *args: None)
    assert again[0] == 0
    doc2 = json.loads((tmp_path / "sensitivity.json").read_text(encoding="utf-8"))
    assert doc2["layers"] == doc["layers"]


def test_hawq_script_without_layers_file_uses_defaults(tmp_path):
    """没有 model.onnx 也没有 layers.json —— 降级路径仍要产出可用结果。"""
    code, tail = run_script(ALGO / "hawq_sensitivity.py", tmp_path, lambda *args: None)
    assert code == 0, tail
    doc = json.loads((tmp_path / "sensitivity.json").read_text(encoding="utf-8"))
    assert set(doc["layers"]) == {"conv1", "conv2", "conv3", "conv4", "conv5", "fc1", "fc2"}


@requires_toolchain
def test_hawq_rejects_invalid_onnx(tmp_path):
    """模型文件存在但不是 ONNX —— 必须非零退出，不能伪造产物。"""
    (tmp_path / "model.onnx").write_bytes(b"NOT-AN-ONNX-FILE")
    (tmp_path / "layers.json").write_text(tiny_onnx_layers_json(), encoding="utf-8")
    code, tail = run_script(ALGO / "hawq_sensitivity.py", tmp_path, lambda *args: None)
    assert code != 0
    assert not (tmp_path / "sensitivity.json").exists()


# --------------------------------------------------------------------------- #
# ② NSGA-II 方案搜索
# --------------------------------------------------------------------------- #
def test_nsga2_script(tmp_path):
    """协议 + 前沿形状。降级路径（无 pymoo）也要满足同样的形状约束。"""
    (tmp_path / "sensitivity.json").write_text(
        json.dumps({"layers": {"conv1": 0.9, "fc1": 0.2}}), encoding="utf-8")
    (tmp_path / "layers.json").write_text(
        json.dumps([{"name": "conv1", "sizeKb": 1024},
                    {"name": "fc1", "sizeKb": 2048, "kind": "fc"}]), encoding="utf-8")
    progress = []
    code, tail = run_script(ALGO / "nsga2_search.py", tmp_path,
                            lambda s, p, m: progress.append((s, p, m)))
    assert code == 0, tail
    assert progress[-1][0] == "scheme_search" and progress[-1][1] == 100

    schemes = json.loads((tmp_path / "schemes.json").read_text(encoding="utf-8"))
    assert len(schemes) == 6
    assert [item["index"] for item in schemes] == list(range(6))
    first = schemes[0]
    assert {"index", "layer_config", "objectives", "metrics", "layers", "stats"} <= set(first)
    assert set(first["layer_config"]) == {"conv1", "fc1"}
    assert set(first["objectives"]) == {"size", "accuracy_loss", "latency"}
    assert set(first["layers"][0]) == {"name", "type", "originalSize", "quantizedSize"}

    # 前沿形状：方案按体积升序排，精度损失随之降序 —— 前端卡片就是这个取舍曲线
    losses = [item["objectives"]["accuracy_loss"] for item in schemes]
    sizes = [item["objectives"]["size"] for item in schemes]
    assert sizes == sorted(sizes)
    assert losses == sorted(losses, reverse=True)

    # 最保守的方案不能让高敏感层还留在 INT8
    assert schemes[-1]["layer_config"]["conv1"] in ("FP16", "FP32")


def test_nsga2_is_deterministic(tmp_path):
    (tmp_path / "sensitivity.json").write_text(
        json.dumps({"layers": {"conv1": 0.9, "conv2": 0.4, "fc1": 0.2}}), encoding="utf-8")
    (tmp_path / "layers.json").write_text(
        json.dumps([{"name": "conv1", "sizeKb": 1024},
                    {"name": "conv2", "sizeKb": 1024},
                    {"name": "fc1", "sizeKb": 2048, "kind": "fc"}]), encoding="utf-8")
    run_script(ALGO / "nsga2_search.py", tmp_path, lambda *args: None)
    first = (tmp_path / "schemes.json").read_text(encoding="utf-8")
    run_script(ALGO / "nsga2_search.py", tmp_path, lambda *args: None)
    assert (tmp_path / "schemes.json").read_text(encoding="utf-8") == first


# --------------------------------------------------------------------------- #
# ④ 量化
# --------------------------------------------------------------------------- #
@requires_toolchain
def test_amct_quantizes_real_onnx(tmp_path):
    _write_tiny(tmp_path)
    (tmp_path / "selected_scheme.json").write_text(json.dumps({
        "index": 1,
        "layer_config": {"conv1": "INT8", "conv2": "FP16", "fc1": "FP32"},
    }), encoding="utf-8")

    progress = []
    code, tail = run_script(ALGO / "amct_quantize.py", tmp_path,
                            lambda s, p, m: progress.append((s, p, m)),
                            extra_env=FAST_ENV)
    assert code == 0, tail
    assert progress[-1] == ("quantizing", 100, "量化完成")

    produced = onnx.load(str(tmp_path / "quantized.onnx"))
    onnx.checker.check_model(produced)
    ops = {node.op_type for node in produced.graph.node}
    # INT8 层插入了 QDQ 算子，FP16 层权重被转成 half
    assert "QuantizeLinear" in ops and "DequantizeLinear" in ops
    dtypes = {init.data_type for init in produced.graph.initializer}
    assert onnx.TensorProto.FLOAT16 in dtypes
    assert onnx.TensorProto.FLOAT in dtypes          # fc1 被挡住，保持 FP32
    # 产物不再是原模型的字节副本
    assert (tmp_path / "quantized.onnx").read_bytes() != build_tiny_onnx()


@requires_toolchain
def test_amct_all_fp32_scheme_passes_through(tmp_path):
    _write_tiny(tmp_path)
    (tmp_path / "selected_scheme.json").write_text(json.dumps({
        "index": 5,
        "layer_config": {"conv1": "FP32", "conv2": "FP32", "fc1": "FP32"},
    }), encoding="utf-8")
    code, tail = run_script(ALGO / "amct_quantize.py", tmp_path, lambda *args: None,
                            extra_env=FAST_ENV)
    assert code == 0, tail
    produced = onnx.load(str(tmp_path / "quantized.onnx"))
    onnx.checker.check_model(produced)
    assert not any(node.op_type == "QuantizeLinear" for node in produced.graph.node)


def test_amct_without_model_degrades(tmp_path):
    """没有 model.onnx 时走降级路径，仍产出占位文件（Windows 演示链路）。"""
    code, tail = run_script(ALGO / "amct_quantize.py", tmp_path, lambda *args: None)
    assert code == 0, tail
    assert (tmp_path / "quantized.onnx").exists()


@requires_toolchain
def test_amct_all_int8_produces_compressed_fallback(tmp_path):
    """全 INT8 方案也得留一份**真压缩过**的兜底模型。

    ATC 不接受 QDQ(INT8) 图，转 .om 时必然降级。若兜底是未量化的原模型，
    用户拿到的 .om 体积就跟方案承诺的压缩率完全对不上（曾经就是这样）。
    这里锁住：兜底必须是 FP16，且不等于原模型。
    """
    _write_tiny(tmp_path)
    (tmp_path / "selected_scheme.json").write_text(json.dumps({
        "index": 0,
        "layer_config": {"conv1": "INT8", "conv2": "INT8", "fc1": "INT8"},
    }), encoding="utf-8")

    code, tail = run_script(ALGO / "amct_quantize.py", tmp_path, lambda *args: None,
                            extra_env=FAST_ENV)
    assert code == 0, tail

    quantized = tmp_path / "quantized.onnx"
    fallback = tmp_path / "quantized_fallback.onnx"
    assert quantized.exists(), "INT8 主产物缺失"
    assert fallback.exists(), "全 INT8 方案没有产出兜底模型"

    produced = onnx.load(str(quantized))
    assert any(node.op_type == "QuantizeLinear" for node in produced.graph.node)

    backup = onnx.load(str(fallback))
    dtypes = {init.data_type for init in backup.graph.initializer}
    assert onnx.TensorProto.FLOAT16 in dtypes, "兜底模型没被压成 FP16"
    assert fallback.read_bytes() != build_tiny_onnx(), "兜底模型是原模型副本，等于没压"


# --------------------------------------------------------------------------- #
# ⑤ ATC 转换
# --------------------------------------------------------------------------- #
def test_atc_reports_missing_toolchain(tmp_path):
    """atc 不可用必须非零退出 —— .om 是二进制私有格式，伪造的板子加载不了。"""
    (tmp_path / "quantized.onnx").write_bytes(build_tiny_onnx())
    code, tail = run_script(ALGO / "atc_convert.py", tmp_path, lambda *args: None,
                            extra_env={"QUANT_ATC_BIN": "/nonexistent/atc"})
    assert code != 0
    assert "atc" in tail.lower() or "ATC" in tail
    assert not (tmp_path / "model.om").exists()


def test_atc_requires_quantized_input(tmp_path):
    code, _ = run_script(ALGO / "atc_convert.py", tmp_path, lambda *args: None)
    assert code != 0
    assert not (tmp_path / "model.om").exists()


@requires_atc
@pytest.mark.e2e
def test_atc_converts_to_om(tmp_path):
    """真实 ATC 转换（慢，只在 QUANT_E2E=1 时跑）。"""
    from tests.conftest import HAS_TOOLCHAIN

    if not HAS_TOOLCHAIN:
        pytest.skip("需要工具链先产出 quantized.onnx")

    _write_tiny(tmp_path)
    (tmp_path / "selected_scheme.json").write_text(json.dumps({
        "index": 1,
        "layer_config": {"conv1": "INT8", "conv2": "FP16", "fc1": "FP32"},
    }), encoding="utf-8")
    code, tail = run_script(ALGO / "amct_quantize.py", tmp_path, lambda *args: None,
                            extra_env=FAST_ENV)
    assert code == 0, tail

    progress = []
    code, tail = run_script(ALGO / "atc_convert.py", tmp_path,
                            lambda s, p, m: progress.append((s, p, m)))
    assert code == 0, tail
    assert progress[-1] == ("converting", 100, ".om 生成完成")

    om = tmp_path / "model.om"
    assert om.exists() and om.stat().st_size > 1024
    # 昇腾离线模型的魔数
    assert om.read_bytes()[:4] == b"IMOD"
    # 产物不再是 quantized.onnx 的字节副本
    assert om.read_bytes() != (tmp_path / "quantized.onnx").read_bytes()
