"""端到端：上传 ONNX → scheme_ready → 选方案 → om_ready → 下载 .om。

阶段二（量化 + ATC 转换）在没有昇腾 CANN 的环境里必然失败 —— 那不是 bug，
所以「跑通全链路」的用例挂 requires_atc，「如实失败」的用例反而在任何环境都跑。
"""
import time

from tests.conftest import requires_atc
from tests.helpers import (create_from_preset, create_job, prepare_om_ready_job,
                           select_scheme, upload_model, wait_status)


@requires_atc
def test_full_flow_upload_to_om(client):
    model = upload_model(client, name="mobilenetv2.onnx")
    assert model["fileSize"] > 1024          # 真实 ONNX，不再是一行占位文本
    job = create_job(client, model["id"])
    ready = wait_status(client, job["id"], "scheme_ready")
    assert ready["progress"] == 100
    assert ready["schemeCount"] == 6

    schemes = client.get("/api/quantization/jobs/%s/schemes" % job["id"]).json()
    assert len(schemes) == 6
    assert all(any(bit in item["layerConfig"].values() for bit in ("INT8", "FP16", "FP32"))
               for item in schemes)

    selected = select_scheme(client, job["id"], 2)
    assert selected["selectedSchemeIndex"] == 2
    finished = wait_status(client, job["id"], "om_ready")
    assert finished["selectedSchemeIndex"] == 2
    assert finished["progress"] == 100

    resp = client.get("/api/quantization/jobs/%s/om/download" % job["id"])
    assert resp.status_code == 200
    content = resp.content
    # 真 .om 是昇腾离线模型：带 IMOD 魔数，不是源 ONNX 的字节副本，也不是占位文本
    assert content[:4] == b"IMOD"
    assert len(content) > 1024
    assert "attachment" in resp.headers["content-disposition"]


@requires_atc
def test_full_flow_with_preset_model(client):
    model = create_from_preset(client, "yolov8")
    assert model["type"] == "preset"
    _, job = prepare_om_ready_job(client, "yolov8")
    assert job["hasOm"] is True

    layers = client.get("/api/quantization/jobs/%s/layers" % job["id"]).json()
    assert len(layers) == 10
    # 层名来自预设模板（不是泛化的 conv1..conv5）
    assert layers[0]["name"] == "backbone.stem"


def test_conversion_without_atc_fails_clearly(client, monkeypatch):
    """没有 atc 时阶段二必须如实失败，并把原因写进 error（而不是伪造 .om）。"""
    from app import pipeline

    original_env = pipeline.algo_env

    def fake_env(name):
        env = original_env(name)
        if name == "atc_script":
            env = dict(env, QUANT_ATC_BIN="/nonexistent/atc")
        return env

    monkeypatch.setattr(pipeline, "algo_env", fake_env)

    model = create_from_preset(client, "mobilenetv2")
    job = create_job(client, model["id"])
    wait_status(client, job["id"], "scheme_ready")
    select_scheme(client, job["id"])
    failed = wait_status(client, job["id"], "failed")
    assert "ATC" in (failed["error"] or "") or "atc" in (failed["error"] or "")
    assert client.get("/api/quantization/jobs/%s/om/download" % job["id"]).status_code == 404


def test_job_failure_surfaces_error(client, monkeypatch):
    from pathlib import Path

    from app import pipeline
    from app.config import workspace_root

    model = upload_model(client)
    monkeypatch.setattr(pipeline, "algo_path",
                        lambda name: Path(workspace_root()) / "missing_algo.py")
    job = create_job(client, model["id"])
    failed = wait_status(client, job["id"], "failed")
    assert "不存在" in failed["error"]
    assert client.get("/api/quantization/jobs/%s/om/download" % job["id"]).status_code == 404
    assert client.get("/api/models/%s" % model["id"]).json()["status"] == "failed"


def test_progress_is_monotonic_per_stage(client):
    """轮询进度时状态机必须按 pending -> sensitivity_analysis -> scheme_search -> scheme_ready 推进。"""
    model = create_from_preset(client, "efficientnet-b0")
    job = create_job(client, model["id"])
    observed = []

    deadline = time.time() + 90
    body = None
    while time.time() < deadline:
        body = client.get("/api/quantization/jobs/%s" % job["id"]).json()
        if not observed or observed[-1] != body["status"]:
            observed.append(body["status"])
        if body["status"] in ("scheme_ready", "failed"):
            break
        time.sleep(0.05)

    assert observed[0] in ("pending", "sensitivity_analysis")
    assert "sensitivity_analysis" in observed
    assert "scheme_search" in observed
    assert observed[-1] == "scheme_ready"
    assert 0 <= body["progress"] <= 100
    assert body["message"]
