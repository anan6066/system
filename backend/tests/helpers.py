"""测试公共工具：把"上传 → 量化 → 部署"的链路封装成可复用函数。"""
import time

# 真实算法比占位实现慢：①+② 要解析 ONNX、跑 NSGA-II，给足余量
DEFAULT_TIMEOUT = 90.0
# 阶段二含真实 ATC 转换（大模型可到几分钟）
OM_TIMEOUT = 300.0


def default_upload_bytes():
    """上传用的模型字节：优先真实 tiny ONNX，没有 onnx 包时退回假字节。

    上传接口会在装了 onnx 的环境里做合法性校验，所以只有在同样没有 onnx
    的环境（Windows py38）才用假字节 —— 两边都不会被拦。
    """
    try:
        from tests.fixtures import build_tiny_onnx

        return build_tiny_onnx()
    except ImportError:
        return b"FAKE-ONNX"


def upload_model(client, name="mobilenetv2.onnx", content=None):
    if content is None:
        content = default_upload_bytes()
    resp = client.post("/api/models",
                       files={"file": (name, content, "application/octet-stream")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_from_preset(client, preset="mobilenetv2"):
    resp = client.post("/api/models/preset", json={"preset": preset})
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_job(client, model_id, **extra):
    payload = {"modelId": model_id}
    payload.update(extra)
    resp = client.post("/api/quantization/jobs", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def wait_status(client, job_id, target, timeout=DEFAULT_TIMEOUT):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get("/api/quantization/jobs/%s" % job_id)
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] == target:
            return last
        if last["status"] == "failed":
            raise AssertionError("任务失败: %s" % last.get("error"))
        time.sleep(0.1)
    raise AssertionError("超时等待 %s，最后状态 %s" % (target, last and last.get("status")))


def prepare_scheme_ready_job(client, preset="mobilenetv2"):
    model = create_from_preset(client, preset)
    job = create_job(client, model["id"])
    ready = wait_status(client, job["id"], "scheme_ready")
    return model, ready


def select_scheme(client, job_id, scheme_index=None):
    payload = {} if scheme_index is None else {"schemeIndex": scheme_index}
    resp = client.post("/api/quantization/jobs/%s/select" % job_id, json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def prepare_om_ready_job(client, preset="mobilenetv2", scheme_index=None):
    model, _ = prepare_scheme_ready_job(client, preset)
    job_id = client.get("/api/quantization/jobs?modelId=%s" % model["id"]).json()[0]["id"]
    select_scheme(client, job_id, scheme_index)
    job = wait_status(client, job_id, "om_ready", timeout=OM_TIMEOUT)
    return model, job


def wait_deployment(client, deployment_id, timeout=30.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get("/api/deployments/%s" % deployment_id)
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] in ("success", "failed"):
            return last
        time.sleep(0.1)
    raise AssertionError("超时等待部署结束，最后状态 %s" % (last and last.get("status")))
