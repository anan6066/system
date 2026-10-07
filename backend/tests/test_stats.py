from tests.conftest import requires_atc
from tests.helpers import prepare_om_ready_job, upload_model


def test_stats_empty(client):
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["activeDevices"] == 0
    assert body["totalModels"] == 0
    assert body["totalJobs"] == 0
    assert body["totalDeployments"] == 0
    assert body["quantizedModels"] == 0
    assert body["avgInferenceSpeed"] is None


def test_stats_counts(client, monkeypatch):
    from app import ssh_client

    first = client.post("/api/devices", json={"name": "板1", "ip": "10.0.0.1",
                                              "username": "root", "password": "x"}).json()
    client.post("/api/devices", json={"name": "板2", "ip": "10.0.0.2",
                                      "username": "root", "password": "x"})
    monkeypatch.setattr(ssh_client, "probe", lambda device: (device.ip == "10.0.0.1", ""))
    client.post("/api/devices/%s/check" % first["id"])

    upload_model(client)

    body = client.get("/api/stats").json()
    assert body["activeDevices"] == 1
    assert body["onlineDevices"] == 1
    assert body["totalDevices"] == 2
    assert body["totalModels"] == 1
    assert body["quantizedModels"] == 0


@requires_atc
def test_stats_after_quantization(
    client):
    model, job = prepare_om_ready_job(client)
    body = client.get("/api/stats").json()
    assert body["totalModels"] == 1
    assert body["quantizedModels"] == 1            # 首页"已量化模型"
    assert body["totalJobs"] == 1
    assert body["readyJobs"] == 1
    assert body["runningJobs"] == 0
    assert body["failedJobs"] == 0
    assert body["generatedAt"].endswith("Z")


@requires_atc
def test_stats_average_latency_from_deployments(
    client, monkeypatch):
    from app import ssh_client

    device = client.post("/api/devices", json={"name": "板1", "ip": "10.0.0.9",
                                               "username": "root", "password": "x"}).json()
    model, job = prepare_om_ready_job(client)
    monkeypatch.setattr(ssh_client, "push_file",
                        lambda device_obj, local, remote: "%s/model.om" % remote)
    resp = client.post("/api/deployments", json={"modelId": model["id"],
                                                 "deviceId": device["id"]})
    assert resp.status_code == 200

    from tests.helpers import wait_deployment

    dep = wait_deployment(client, resp.json()["id"])
    assert dep["status"] == "success"

    body = client.get("/api/stats").json()
    assert body["totalDeployments"] == 1
    assert body["successfulDeployments"] == 1
    assert body["avgLatencyMs"] == dep["metrics"]["inferenceSpeed"]
    assert body["avgTop1Accuracy"] == dep["metrics"]["top1Accuracy"]
    assert job["status"] == "om_ready"
