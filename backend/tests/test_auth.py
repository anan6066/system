"""API Key 鉴权。

默认关闭（不配 key 时全部放行）；配了 key 之后：
  - /api/health、/api/meta、接口文档 仍然免鉴权（探活与联调用）
  - 其余 /api/* 必须带 X-API-Key 头或 Authorization: Bearer
"""
import pytest
from fastapi.testclient import TestClient

KEY = "test-key-0123456789"


@pytest.fixture()
def keyed_client(monkeypatch):
    """开启鉴权的 client（key 走环境变量，优先级高于 config.yaml）。"""
    monkeypatch.setenv("QUANT_DEPLOY_API_KEY", KEY)
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_disabled_when_no_key_configured(client):
    """没配 key = 不鉴权，本机开发不受影响。"""
    assert client.get("/api/devices").status_code == 200


def test_public_endpoints_stay_open(keyed_client):
    assert keyed_client.get("/api/health").status_code == 200
    assert keyed_client.get("/api/meta").status_code == 200


def test_api_requires_key(keyed_client):
    resp = keyed_client.get("/api/devices")
    assert resp.status_code == 401
    assert "API Key" in resp.json()["detail"] or "API" in resp.json()["detail"]


def test_write_endpoints_also_protected(keyed_client):
    resp = keyed_client.post("/api/devices", json={
        "name": "x", "ip": "10.0.0.1", "username": "root", "password": "p"})
    assert resp.status_code == 401


def test_accepts_x_api_key_header(keyed_client):
    assert keyed_client.get("/api/devices", headers={"X-API-Key": KEY}).status_code == 200


def test_accepts_bearer_token(keyed_client):
    resp = keyed_client.get("/api/devices", headers={"Authorization": "Bearer %s" % KEY})
    assert resp.status_code == 200


def test_rejects_wrong_key(keyed_client):
    assert keyed_client.get("/api/devices", headers={"X-API-Key": "wrong"}).status_code == 401
    assert keyed_client.get("/api/devices",
                            headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_preflight_not_blocked(keyed_client):
    """浏览器预检不带自定义头，不能被鉴权拦掉（否则 CORS 全废）。"""
    resp = keyed_client.options("/api/devices", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert resp.status_code < 400
