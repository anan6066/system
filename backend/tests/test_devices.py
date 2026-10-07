def _create(client, **overrides):
    payload = {"name": "昇腾开发板-01", "ip": "192.168.1.101", "port": 22,
               "username": "root", "authType": "pwd", "password": "secret",
               "npuType": "ascend"}
    payload.update(overrides)
    return client.post("/api/devices", json=payload)


def test_create_and_list(client):
    resp = _create(client)
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "昇腾开发板-01"
    assert body["npuType"] == "ascend"
    assert body["status"] == "offline"
    assert body["cpuUsage"] == 0
    assert body["memoryUsage"] == 0
    assert "password" not in body                     # 密码永不回传
    assert body["lastConnected"] is not None          # 前端直接 new Date() 不会拿到 null

    resp = client.get("/api/devices")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["id"] == body["id"]


def test_create_validates_input(client):
    assert _create(client, ip="   ").status_code == 400
    assert _create(client, username="").status_code == 400
    assert _create(client, port=99999).status_code == 400
    assert _create(client, authType="key", keyPath=None).status_code == 400


def test_update_device(client):
    device_id = _create(client).json()["id"]
    resp = client.put("/api/devices/%s" % device_id, json={"name": "改名后的板子",
                                                          "npuType": "KIRIN"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "改名后的板子"
    assert resp.json()["npuType"] == "kirin"          # 统一小写

    assert client.put("/api/devices/nonexistent", json={"name": "x"}).status_code == 404


def test_delete_device(client):
    device_id = _create(client).json()["id"]
    assert client.delete("/api/devices/%s" % device_id).status_code == 200
    assert client.get("/api/devices").json() == []


def test_delete_missing_returns_404(client):
    assert client.delete("/api/devices/nonexistent").status_code == 404


def test_check_online(client, monkeypatch):
    from app import ssh_client

    device_id = _create(client).json()["id"]

    def fake_probe(device):
        assert device.ip == "192.168.1.101"
        return (True, "")

    monkeypatch.setattr(ssh_client, "probe", fake_probe)
    resp = client.post("/api/devices/%s/check" % device_id)
    assert resp.status_code == 200
    body = resp.json()
    assert body["online"] is True
    assert body["status"] == "online"
    assert body["latencyMs"] is not None

    listed = client.get("/api/devices").json()[0]
    assert listed["status"] == "online"
    assert listed["lastConnected"] is not None


def test_check_offline(client, monkeypatch):
    from app import ssh_client

    device_id = _create(client).json()["id"]
    monkeypatch.setattr(ssh_client, "probe", lambda device: (False, "连接超时"))
    resp = client.post("/api/devices/%s/check" % device_id)
    assert resp.status_code == 200
    assert resp.json()["online"] is False
    listed = client.get("/api/devices").json()[0]
    assert listed["status"] == "offline"
    assert listed["lastError"] == "连接超时"


def test_check_all(client, monkeypatch):
    from app import ssh_client

    _create(client, name="板1", ip="10.0.0.1")
    _create(client, name="板2", ip="10.0.0.2")
    monkeypatch.setattr(ssh_client, "probe",
                        lambda device: (device.ip == "10.0.0.1", ""))
    body = client.post("/api/devices/check-all").json()
    assert body["total"] == 2
    assert body["online"] == 1
    assert body["offline"] == 1
    statuses = {item["ip"]: item["status"] for item in client.get("/api/devices").json()}
    assert statuses == {"10.0.0.1": "online", "10.0.0.2": "offline"}


def test_metrics_updates_device_and_history(client, monkeypatch):
    from app import ssh_client

    device_id = _create(client).json()["id"]
    monkeypatch.setattr(ssh_client, "get_metrics",
                        lambda device: {"cpuUsage": 42.5, "memoryUsage": 63.2,
                                        "npuUsage": 12.0, "collectedAt": "2026-01-01T00:00:00Z"})
    resp = client.get("/api/devices/%s/metrics" % device_id)
    assert resp.status_code == 200
    assert resp.json()["cpuUsage"] == 42.5
    assert resp.json()["memoryUsage"] == 63.2
    assert resp.json()["npuUsage"] == 12.0

    listed = client.get("/api/devices").json()[0]
    assert listed["cpuUsage"] == 42.5
    assert listed["status"] == "online"               # 采集成功即视为在线

    history = client.get("/api/devices/%s/metrics/history" % device_id).json()
    assert history["deviceId"] == device_id
    assert len(history["samples"]) == 1
    sample = history["samples"][0]
    assert set(sample.keys()) == {"timestamp", "cpu", "memory"}   # 对齐前端 DeviceMetrics
    assert sample["cpu"] == 42.5
    assert isinstance(sample["timestamp"], int)


def test_metrics_failure_returns_502(client, monkeypatch):
    from app import ssh_client

    device_id = _create(client).json()["id"]

    def boom(device):
        raise RuntimeError("认证失败")

    monkeypatch.setattr(ssh_client, "get_metrics", boom)
    resp = client.get("/api/devices/%s/metrics" % device_id)
    assert resp.status_code == 502
    assert "认证失败" in resp.json()["detail"]


def test_metrics_missing_device_404(client):
    assert client.get("/api/devices/nonexistent/metrics").status_code == 404
    assert client.get("/api/devices/nonexistent/metrics/history").status_code == 404
