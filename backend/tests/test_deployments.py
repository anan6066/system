import time

import pytest

from app import ssh_client
from app.routers import deployments as deployments_router
from tests.conftest import requires_atc
from tests.helpers import prepare_om_ready_job, wait_deployment

# 部署推送的是真 .om，而要产出 .om 就得有昇腾 CANN 的 atc。
# 没有 CANN 的环境（Windows py38）会整组跳过。
pytestmark = requires_atc


def _device(client, name="昇腾板-01", ip="192.168.1.101"):
    resp = client.post("/api/devices", json={"name": name, "ip": ip, "username": "root",
                                             "password": "secret", "npuType": "ascend"})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _fake_push(container):
    def push(device, local_path, remote_dir):
        with open(local_path, "rb") as handle:
            container["content"] = handle.read()
        container["remote_dir"] = remote_dir
        container["device_ip"] = device.ip
        return "%s/model.om" % remote_dir.rstrip("/")
    return push


def test_create_deployment_validations(client):
    device = _device(client)
    assert client.post("/api/deployments", json={"deviceId": device["id"]}).status_code == 400
    assert client.post("/api/deployments", json={"deviceId": "nope",
                                                 "modelId": "nope"}).status_code == 400
    assert client.post("/api/deployments", json={"deviceId": device["id"],
                                                 "modelId": "nope"}).status_code == 400

    model, _ = prepare_om_ready_job(client)
    assert client.post("/api/deployments", json={"deviceId": "nope",
                                                 "modelId": model["id"]}).status_code == 400

    # 有模型但还没 .om
    from tests.helpers import create_from_preset

    fresh = create_from_preset(client, "resnet18")
    resp = client.post("/api/deployments", json={"deviceId": device["id"],
                                                 "modelId": fresh["id"]})
    assert resp.status_code == 400
    assert ".om" in resp.json()["detail"]


def test_push_success_with_estimated_metrics(client, monkeypatch):
    device = _device(client)
    model, job = prepare_om_ready_job(client)
    pushed = {}
    monkeypatch.setattr(ssh_client, "push_file", _fake_push(pushed))

    resp = client.post("/api/deployments", json={"modelId": model["id"],
                                                 "deviceId": device["id"]})
    assert resp.status_code == 200
    created = resp.json()
    assert created["status"] == "pending"
    assert created["targetDir"] == "/data/models"        # 未指定 -> 用 config 默认目录
    assert created["logs"][0]["message"] == "开始部署任务"
    assert created["modelName"] == model["name"]
    assert created["deviceName"] == device["name"]

    dep = wait_deployment(client, created["id"])
    assert dep["status"] == "success"
    assert dep["metricsSource"] == "estimated"
    assert dep["metrics"]["inferenceSpeed"] > 0
    assert dep["metrics"]["memoryUsage"] > 0
    assert 0 < dep["metrics"]["top1Accuracy"] <= 100
    assert dep["endTime"] is not None
    assert dep["remoteFile"] == "/data/models/model.om"

    assert pushed["remote_dir"] == "/data/models"
    assert pushed["content"][:4] == b"IMOD"      # 推的是真 .om（昇腾离线模型魔数）
    assert len(pushed["content"]) > 1024
    assert pushed["device_ip"] == "192.168.1.101"

    messages = [item["message"] for item in dep["logs"]]
    assert messages[0] == "开始部署任务"
    assert any("正在上传量化模型文件" in item for item in messages)
    assert any("模型文件上传完成" in item for item in messages)
    assert any("正在初始化 NPU 环境" in item for item in messages)
    assert any("开始推理速度测试" in item for item in messages)
    assert messages[-1] == "部署成功"
    for item in dep["logs"]:
        assert set(item) == {"id", "timestamp", "message", "type"}
        assert item["type"] in ("info", "success", "warning", "error")
    assert any(item["type"] == "warning" for item in dep["logs"])   # 未配置 bench 的提示
    assert any(item["type"] == "success" for item in dep["logs"])

    # 设备部署中置 busy、结束后回到 online；任务状态推进到 deployed
    assert client.get("/api/devices/%s" % device["id"]).json()["status"] == "online"
    assert client.get("/api/quantization/jobs/%s" % job["id"]).json()["status"] == "deployed"


def test_push_measured_metrics(client, monkeypatch):
    device = _device(client)
    model, _ = prepare_om_ready_job(client)
    monkeypatch.setattr(ssh_client, "push_file", _fake_push({}))
    monkeypatch.setattr(ssh_client, "run_command",
                        lambda dev, cmd, timeout=None:
                            'npu bench ok\n{"inferenceSpeed": 9.9, "memoryUsage": 210, '
                            '"top1Accuracy": 66.6}')

    def fake_get(path, default=None):
        if path == "deployment.bench_command":
            return "bench {remote_path}"
        from app.config import get as real_get

        return real_get(path, default)

    monkeypatch.setattr(deployments_router, "get", fake_get)

    created = client.post("/api/deployments", json={"modelId": model["id"],
                                                    "deviceId": device["id"]}).json()
    dep = wait_deployment(client, created["id"])
    assert dep["status"] == "success"
    assert dep["metricsSource"] == "measured"
    assert dep["metrics"] == {"inferenceSpeed": 9.9, "memoryUsage": 210.0,
                              "top1Accuracy": 66.6}
    assert not any(item["type"] == "warning" for item in dep["logs"])


def test_push_failure_marks_failed(client, monkeypatch):
    device = _device(client)
    model, job = prepare_om_ready_job(client)

    def boom(dev, local_path, remote_dir):
        raise RuntimeError("连接超时: 认证失败")

    monkeypatch.setattr(ssh_client, "push_file", boom)
    created = client.post("/api/deployments", json={"modelId": model["id"],
                                                    "deviceId": device["id"]}).json()
    dep = wait_deployment(client, created["id"])
    assert dep["status"] == "failed"
    assert "连接超时" in dep["error"]
    assert dep["metrics"] is None
    assert dep["logs"][-1]["type"] == "error"
    # 设备不该卡在 busy，任务回到 om_ready 以便重试
    assert client.get("/api/devices/%s" % device["id"]).json()["status"] == "online"
    assert client.get("/api/quantization/jobs/%s" % job["id"]).json()["status"] == "om_ready"


def test_retry_after_failure(client, monkeypatch):
    device = _device(client)
    model, _ = prepare_om_ready_job(client)
    calls = {"count": 0}

    def flaky(dev, local_path, remote_dir):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("首次失败")
        return "%s/model.om" % remote_dir

    monkeypatch.setattr(ssh_client, "push_file", flaky)
    created = client.post("/api/deployments", json={"modelId": model["id"],
                                                    "deviceId": device["id"]}).json()
    assert wait_deployment(client, created["id"])["status"] == "failed"

    resp = client.post("/api/deployments/%s/retry" % created["id"])
    assert resp.status_code == 200
    dep = wait_deployment(client, created["id"])
    assert dep["status"] == "success"
    assert dep["logs"][0]["message"] == "重新开始部署任务"


def test_list_detail_and_delete(client, monkeypatch):
    device = _device(client)
    model, _ = prepare_om_ready_job(client)
    monkeypatch.setattr(ssh_client, "push_file", _fake_push({}))

    created = client.post("/api/deployments", json={"modelId": model["id"],
                                                    "deviceId": device["id"],
                                                    "targetDir": "/opt/models"}).json()
    dep = wait_deployment(client, created["id"])
    assert dep["targetDir"] == "/opt/models"

    listed = client.get("/api/deployments").json()
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]
    assert len(client.get("/api/deployments?modelId=%s" % model["id"]).json()) == 1
    assert len(client.get("/api/deployments?deviceId=%s" % device["id"]).json()) == 1
    assert client.get("/api/deployments?status=failed").json() == []
    assert client.get("/api/deployments/nonexistent").status_code == 404

    assert client.delete("/api/deployments/%s" % created["id"]).status_code == 200
    assert client.get("/api/deployments").json() == []
    assert client.get("/api/deployments/%s" % created["id"]).status_code == 404


def test_deployment_by_job_id_and_duplicate_delete_running(client, monkeypatch):
    device = _device(client)
    model, job = prepare_om_ready_job(client)

    def slow_push(dev, local_path, remote_dir):
        time.sleep(0.6)
        return "%s/model.om" % remote_dir

    monkeypatch.setattr(ssh_client, "push_file", slow_push)
    created = client.post("/api/deployments", json={"jobId": job["id"],
                                                    "deviceId": device["id"]}).json()
    assert created["jobId"] == job["id"]
    assert created["modelId"] == model["id"]

    # 部署中不允许删除；重试也返回 409
    assert client.delete("/api/deployments/%s" % created["id"]).status_code == 409
    assert client.post("/api/deployments/%s/retry" % created["id"]).status_code == 409

    assert wait_deployment(client, created["id"])["status"] == "success"
