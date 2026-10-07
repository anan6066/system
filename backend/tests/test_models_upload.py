from pathlib import Path

from tests.helpers import default_upload_bytes, upload_model


def test_upload_and_list(client):
    body = upload_model(client)
    assert body["name"] == "mobilenetv2.onnx"
    assert body["fileSize"] == len(default_upload_bytes())
    assert body["type"] == "custom"
    assert body["status"] == "idle"
    assert body["targetNPU"] == "ascend"
    assert body["quantizationLayers"], "上传后应能给出层结构（占位推导）"
    assert body["layerCount"] == len(body["quantizationLayers"])

    listed = client.get("/api/models").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_upload_rejects_wrong_suffix(client):
    resp = client.post("/api/models",
                       files={"file": ("model.txt", b"x", "application/octet-stream")})
    assert resp.status_code == 400
    assert "onnx" in resp.json()["detail"]


def test_upload_rejects_empty_file(client):
    resp = client.post("/api/models",
                       files={"file": ("model.onnx", b"", "application/octet-stream")})
    assert resp.status_code == 400


def test_download(client):
    model_id = upload_model(client)["id"]
    resp = client.get("/api/models/%s/download" % model_id)
    assert resp.status_code == 200
    assert resp.content == default_upload_bytes()


def test_delete_removes_file(client, db_session):
    model = upload_model(client)
    from app.models import Model

    row = db_session.get(Model, model["id"])
    stored = Path(row.filePath)
    assert stored.exists()

    assert client.delete("/api/models/%s" % model["id"]).status_code == 200
    assert client.get("/api/models").json() == []
    assert not stored.exists()


def test_get_missing_model_404(client):
    assert client.get("/api/models/nonexistent").status_code == 404
    assert client.delete("/api/models/nonexistent").status_code == 404
    assert client.get("/api/models/nonexistent/download").status_code == 404


def test_presets_endpoint(client):
    presets = client.get("/api/models/presets").json()
    ids = [item["id"] for item in presets]
    assert ids == ["mobilenetv2", "resnet18", "yolov8", "efficientnet-b0"]
    for item in presets:
        assert item["name"] and item["description"] and item["size"]
        assert item["layerCount"] > 0


def test_create_model_from_preset(client):
    model = client.post("/api/models/preset", json={"preset": "mobilenetv2"}).json()
    assert model["type"] == "preset"
    assert model["preset"] == "mobilenetv2"
    assert model["layerCount"] == 8
    assert model["baseAccuracy"] > 60

    layers = client.get("/api/models/%s/layers" % model["id"]).json()
    assert len(layers) == 8
    assert layers[0]["name"] == "conv1"
    assert all(item["type"] == "FP32" for item in layers)      # 未量化：全精度
    assert all(item["originalSize"] > 0 for item in layers)


def test_create_model_from_unknown_preset_400(client):
    resp = client.post("/api/models/preset", json={"preset": "nope"})
    assert resp.status_code == 400
