def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["time"].endswith("Z")


def test_meta_exposes_contract(client):
    body = client.get("/api/meta").json()
    assert "scheme_ready" in body["jobStatus"]
    assert "om_ready" in body["jobStatus"]
    assert body["deviceStatus"] == ["online", "offline", "busy"]
    assert body["bitWidths"] == ["INT8", "FP16", "FP32"]
    assert body["conventions"]["errorFormat"] == {"detail": "错误说明"}
