import json

from sqlmodel import Session

from app.db import engine
from app.models import Model, QuantizationJob
from tests.conftest import requires_atc
from tests.fixtures import TINY_LAYER_NAMES
from tests.helpers import (create_job, prepare_scheme_ready_job, select_scheme,
                           upload_model, wait_status)


def _seed_bare_job(status="pending", with_om=False):
    with Session(engine) as session:
        model = Model(name="x.onnx", filePath="/tmp/x.onnx", fileSize=1, status="idle")
        session.add(model)
        session.commit()
        job = QuantizationJob(modelId=model.id, status=status,
                              omPath="/tmp/x.om" if with_om else None)
        session.add(job)
        session.commit()
        return job.id


def test_missing_job_404(client):
    assert client.get("/api/quantization/jobs/nonexistent").status_code == 404
    assert client.get("/api/quantization/jobs/nonexistent/schemes").status_code == 404
    assert client.get("/api/quantization/jobs/nonexistent/layers").status_code == 404
    assert client.get("/api/quantization/jobs/nonexistent/logs").status_code == 404
    assert client.get("/api/quantization/jobs/nonexistent/sensitivity").status_code == 404
    assert client.post("/api/quantization/jobs/nonexistent/select",
                       json={"schemeIndex": 0}).status_code == 404
    assert client.post("/api/quantization/jobs/nonexistent/cancel").status_code == 404
    assert client.delete("/api/quantization/jobs/nonexistent").status_code == 404


def test_create_job_with_missing_model_400(client):
    resp = client.post("/api/quantization/jobs", json={"modelId": "nonexistent"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "模型不存在"


def test_create_job_with_missing_file_400(client, db_session):
    model = Model(name="x.onnx", filePath="/tmp/definitely-missing.onnx", fileSize=1)
    db_session.add(model)
    db_session.commit()
    resp = client.post("/api/quantization/jobs", json={"modelId": model.id})
    assert resp.status_code == 400
    assert "丢失" in resp.json()["detail"]


def test_select_scheme_wrong_state_409(client):
    job_id = _seed_bare_job(status="pending")
    resp = client.post("/api/quantization/jobs/%s/select" % job_id, json={"schemeIndex": 0})
    assert resp.status_code == 409
    assert "不可选择" in resp.json()["detail"]


def test_download_om_before_ready_404(client):
    job_id = _seed_bare_job(status="pending")
    assert client.get("/api/quantization/jobs/%s/om/download" % job_id).status_code == 404


def test_cancel_finished_job_409(client):
    job_id = _seed_bare_job(status="om_ready", with_om=True)
    assert client.post("/api/quantization/jobs/%s/cancel" % job_id).status_code == 409


def test_duplicate_running_job_409(client):
    model = client.post("/api/models/preset", json={"preset": "mobilenetv2"}).json()
    create_job(client, model["id"])
    resp = client.post("/api/quantization/jobs", json={"modelId": model["id"]})
    assert resp.status_code == 409
    assert "进行中" in resp.json()["detail"]


@requires_atc
def test_full_job_api_flow(
    client):
    model = upload_model(client)
    job = create_job(client, model["id"])
    assert job["status"] in ("pending", "sensitivity_analysis")
    assert job["modelName"] == "mobilenetv2.onnx"
    assert job["hasOm"] is False

    ready = wait_status(client, job["id"], "scheme_ready")
    assert ready["progress"] == 100
    assert ready["schemeCount"] == 6

    # 进度日志
    logs = client.get("/api/quantization/jobs/%s/logs" % job["id"]).json()
    assert len(logs) >= 5
    assert {"id", "timestamp", "stage", "percent", "message", "level"} == set(logs[0])
    assert logs[-1]["level"] in ("info", "success")

    # 敏感度
    sensitivity = client.get("/api/quantization/jobs/%s/sensitivity" % job["id"]).json()
    assert sensitivity and all(isinstance(v, float) for v in sensitivity.values())

    # 帕累托前沿
    schemes = client.get("/api/quantization/jobs/%s/schemes" % job["id"]).json()
    assert len(schemes) == 6
    assert sum(1 for item in schemes if item["recommended"]) == 1
    first = schemes[0]
    assert set(first) >= {"index", "layerConfig", "objectives", "metrics", "layers",
                          "stats", "isSelected", "recommended"}
    assert set(first["metrics"]) >= {"sizeMb", "latencyMs", "accuracyLossPct"}
    # 自定义上传的层结构来自 ONNX 里真实的权重张量（偏置不算层）
    assert len(first["layers"]) == len(TINY_LAYER_NAMES)
    assert set(first["layers"][0]) == {"name", "type", "originalSize", "quantizedSize"}
    assert first["stats"]["int8Layers"] + first["stats"]["fp16Layers"] \
        + first["stats"]["fp32Layers"] == len(TINY_LAYER_NAMES)
    assert 0 < first["stats"]["compressionRatio"] < 1

    # 选方案（省略 index -> 用推荐方案）
    selected = select_scheme(client, job["id"])
    assert selected["selectedSchemeIndex"] is not None
    chosen = selected["selectedSchemeIndex"]

    finished = wait_status(client, job["id"], "om_ready")
    assert finished["selectedSchemeIndex"] == chosen
    assert finished["hasOm"] is True

    # 层信息与选中方案一致
    layers = client.get("/api/quantization/jobs/%s/layers" % job["id"]).json()
    scheme = [item for item in schemes if item["index"] == chosen][0]
    assert layers == scheme["layers"]

    # 下载 .om
    resp = client.get("/api/quantization/jobs/%s/om/download" % job["id"])
    assert resp.status_code == 200
    assert resp.content[:4] == b"IMOD"                    # 真 .om（昇腾离线模型魔数）
    assert len(resp.content) > 1024

    # 列表与筛选
    assert len(client.get("/api/quantization/jobs").json()) == 1
    assert len(client.get("/api/quantization/jobs?modelId=%s" % model["id"]).json()) == 1
    assert len(client.get("/api/quantization/jobs?status=om_ready").json()) == 1
    assert client.get("/api/quantization/jobs?status=pending").json() == []

    # 模型状态同步为已完成，且层位宽跟随方案
    model_out = client.get("/api/models/%s" % model["id"]).json()
    assert model_out["status"] == "completed"
    assert model_out["quantizationLayers"] == scheme["layers"]
    assert model_out["latestJobId"] == job["id"]

    # .om 就绪后不可再选方案
    assert client.post("/api/quantization/jobs/%s/select" % job["id"],
                       json={"schemeIndex": 0}).status_code == 409

    # 删除任务
    assert client.delete("/api/quantization/jobs/%s" % job["id"]).status_code == 200
    assert client.get("/api/quantization/jobs").json() == []


def test_select_unknown_scheme_400(client):
    _, ready = prepare_scheme_ready_job(client)
    resp = client.post("/api/quantization/jobs/%s/select" % ready["id"],
                       json={"schemeIndex": 99})
    assert resp.status_code == 400
    assert "方案序号" in resp.json()["detail"]


def test_cancel_job_at_scheme_ready(client):
    _, ready = prepare_scheme_ready_job(client)
    resp = client.post("/api/quantization/jobs/%s/cancel" % ready["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error"] == "任务已取消"

    model_id = body["modelId"]
    assert client.get("/api/models/%s" % model_id).json()["status"] == "failed"

    logs = client.get("/api/quantization/jobs/%s/logs" % ready["id"]).json()
    assert any(row["level"] == "warning" for row in logs)


def test_cancel_running_job(client):
    model = client.post("/api/models/preset", json={"preset": "resnet18"}).json()
    job = create_job(client, model["id"])
    resp = client.post("/api/quantization/jobs/%s/cancel" % job["id"])
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"

    # 取消后任务不会再被推进（脚本被 kill，状态保持 failed）
    import time

    time.sleep(1.0)
    again = client.get("/api/quantization/jobs/%s" % job["id"]).json()
    assert again["status"] == "failed"
    assert again["error"] == "任务已取消"


def test_delete_running_job_409(client):
    model = client.post("/api/models/preset", json={"preset": "yolov8"}).json()
    job = create_job(client, model["id"])
    assert client.delete("/api/quantization/jobs/%s" % job["id"]).status_code == 409
    client.post("/api/quantization/jobs/%s/cancel" % job["id"])


def test_schemes_payload_matches_frontend_shape(client):
    _, ready = prepare_scheme_ready_job(client, preset="efficientnet-b0")
    schemes = client.get("/api/quantization/jobs/%s/schemes" % ready["id"]).json()
    for item in schemes:
        assert isinstance(item["layerConfig"], dict)
        assert set(item["objectives"]) == {"size", "accuracy_loss", "latency"}
        assert all(value in ("INT8", "FP16", "FP32")
                   for value in item["layerConfig"].values())
        assert item["stats"]["quantizedSizeKb"] < item["stats"]["originalSizeKb"]
        # 层明细可直接喂给前端 QuantizationLayer[]
        for layer in item["layers"]:
            assert layer["type"] in ("INT8", "FP16", "FP32")
            assert layer["quantizedSize"] <= layer["originalSize"]
    text = json.dumps(schemes)
    assert "conv1" in text
