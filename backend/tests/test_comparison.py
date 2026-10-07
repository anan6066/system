from app import ssh_client
from tests.conftest import requires_atc
from tests.helpers import prepare_om_ready_job, wait_deployment


def _device(client):
    return client.post("/api/devices", json={"name": "板", "ip": "10.0.0.9",
                                             "username": "root", "password": "x"}).json()


def test_comparison_needs_a_selector(client):
    assert client.get("/api/comparison").status_code == 400
    assert client.get("/api/comparison?jobId=nonexistent").status_code == 404
    assert client.get("/api/comparison?modelId=nonexistent").status_code == 404


def test_comparison_requires_scheme(client):
    from tests.helpers import create_from_preset

    model = create_from_preset(client, "mobilenetv2")
    # 任务还在跑，尚未生成方案
    job = client.post("/api/quantization/jobs", json={"modelId": model["id"]}).json()
    resp = client.get("/api/comparison?jobId=%s" % job["id"])
    assert resp.status_code in (404, 409)
    client.post("/api/quantization/jobs/%s/cancel" % job["id"])


@requires_atc
def test_comparison_by_job(
    client):
    model, job = prepare_om_ready_job(client)
    body = client.get("/api/comparison?jobId=%s" % job["id"]).json()

    assert body["jobId"] == job["id"]
    assert body["modelId"] == model["id"]
    assert body["mode"] == "job"
    assert len(body["rows"]) == 4
    metrics = [row["metric"] for row in body["rows"]]
    assert "Top-1 准确率 (%)" in metrics
    assert "推理延迟 (ms)" in metrics
    for row in body["rows"]:
        assert {"metric", "traditionalINT8", "mixedPrecision", "unit"} == set(row)

    accuracy = [row for row in body["rows"] if row["metric"].startswith("Top-1")][0]
    latency = [row for row in body["rows"] if row["metric"].startswith("推理延迟")][0]
    size = [row for row in body["rows"] if row["metric"].startswith("模型大小")][0]
    # 基线是"全 INT8"，所以混合精度一定不会更差：精度不降，代价是体积/延迟略增
    assert accuracy["mixedPrecision"] >= accuracy["traditionalINT8"]
    assert latency["mixedPrecision"] >= latency["traditionalINT8"] * 0.99
    assert size["mixedPrecision"] >= size["traditionalINT8"] * 0.99

    assert [item["metric"] for item in body["radar"]] == ["精度", "速度", "效率", "内存", "功耗"]
    for item in body["radar"]:
        assert 0 <= item["traditional"] <= 100
        assert 0 <= item["mixedPrecision"] <= 100
    assert body["traditionalLayers"] == 8
    assert body["mixedPrecisionLayers"] >= 0


@requires_atc
def test_comparison_by_model_uses_latest_job(
    client):
    model, job = prepare_om_ready_job(client)
    body = client.get("/api/comparison?modelId=%s" % model["id"]).json()
    assert body["mode"] == "model"
    assert body["jobId"] == job["id"]


@requires_atc
def test_comparison_by_deployment(
    client, monkeypatch):
    device = _device(client)
    model, job = prepare_om_ready_job(client)
    monkeypatch.setattr(ssh_client, "push_file",
                        lambda dev, local, remote: "%s/model.om" % remote)
    created = client.post("/api/deployments", json={"modelId": model["id"],
                                                    "deviceId": device["id"]}).json()
    dep = wait_deployment(client, created["id"])
    assert dep["status"] == "success"

    body = client.get("/api/comparison?deploymentId=%s" % created["id"]).json()
    assert body["mode"] == "deployment"
    assert body["deploymentId"] == created["id"]
    assert len(body["rows"]) == 4

    assert client.get("/api/comparison?deploymentId=nonexistent").status_code == 404
