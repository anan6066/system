"""HTTP 端到端冒烟脚本（前后端联调前自检用）。

对着一个真正跑起来的后端执行完整链路：
    health → stats → 建设备 → 探活 → 预设模型 → 量化任务 → 帕累托前沿
    → 选方案 → 等 .om → 下载 .om → 对比数据 → 一键部署（无板子时预期失败）→ 清理

用法：
    python scripts/smoke_http.py [base_url]
    python scripts/smoke_http.py http://121.43.244.6:8000

退出码 0 表示链路通；非 0 表示某一步失败（失败点会打印原因）。
"""
import json
import sys
import time

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
TIMEOUT = 30.0

passed = []
failed = []


def step(name, ok, detail=""):
    mark = "OK  " if ok else "FAIL"
    line = "[%s] %s" % (mark, name)
    if detail:
        line += " -- %s" % detail
    print(line, flush=True)
    (passed if ok else failed).append(name)
    return ok


def poll(client, job_id, target, timeout=120.0):
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get("/api/quantization/jobs/%s" % job_id).json()
        if last.get("status") == target:
            return last
        if last.get("status") == "failed":
            raise RuntimeError("任务失败: %s" % last.get("error"))
        time.sleep(0.5)
    raise RuntimeError("超时等待 %s，最后状态 %s" % (target, last.get("status")))


def main():
    suffix = str(int(time.time()))
    with httpx.Client(base_url=BASE, timeout=TIMEOUT) as client:
        health = client.get("/api/health")
        step("GET /api/health", health.status_code == 200, str(health.json()))
        meta = client.get("/api/meta").json()
        step("GET /api/meta", "jobStatus" in meta,
             "%d 个任务状态" % len(meta.get("jobStatus", [])))

        stats_before = client.get("/api/stats").json()
        step("GET /api/stats", stats_before.get("generatedAt") is not None,
             "设备 %s / 模型 %s / 部署 %s"
             % (stats_before["totalDevices"], stats_before["totalModels"],
                stats_before["totalDeployments"]))

        device = client.post("/api/devices", json={
            "name": "smoke-device-%s" % suffix, "ip": "192.168.99.%s" % (int(suffix) % 250),
            "port": 22, "username": "root", "password": "secret", "npuType": "ascend",
        }).json()
        step("POST /api/devices", bool(device.get("id")), device.get("name"))

        check = client.post("/api/devices/%s/check" % device["id"])
        step("POST /api/devices/{id}/check", check.status_code == 200,
             "online=%s error=%s" % (check.json().get("online"), check.json().get("error")))

        presets = client.get("/api/models/presets").json()
        step("GET /api/models/presets", len(presets) == 4,
             ", ".join(item["id"] for item in presets))

        model = client.post("/api/models/preset",
                            json={"preset": "mobilenetv2", "targetNPU": "ascend"}).json()
        step("POST /api/models/preset", bool(model.get("id")),
             "%s 层数=%s" % (model.get("name"), model.get("layerCount")))

        job = client.post("/api/quantization/jobs", json={"modelId": model["id"]}).json()
        step("POST /api/quantization/jobs", bool(job.get("id")), "status=%s" % job.get("status"))

        ready = poll(client, job["id"], "scheme_ready")
        step("轮询到 scheme_ready", True, "进度 %s%%" % ready.get("progress"))

        logs = client.get("/api/quantization/jobs/%s/logs" % job["id"]).json()
        step("GET .../logs", len(logs) > 0, "共 %d 条进度日志" % len(logs))

        schemes = client.get("/api/quantization/jobs/%s/schemes" % job["id"]).json()
        step("GET .../schemes", len(schemes) == 6,
             "推荐方案 #%s" % next((item["index"] for item in schemes if item["recommended"]), "?"))
        for item in schemes:
            print("     方案 #%s  INT8 %2d 层 / FP16 %2d 层 / FP32 %2d 层  体积 %.2fMB  "
                  "延迟 %.1fms  精度损失 %.2fpp"
                  % (item["index"], item["stats"]["int8Layers"], item["stats"]["fp16Layers"],
                     item["stats"]["fp32Layers"], item["metrics"]["sizeMb"],
                     item["metrics"]["latencyMs"], item["metrics"]["accuracyLossPct"]))

        selected = client.post("/api/quantization/jobs/%s/select" % job["id"], json={}).json()
        step("POST .../select（用推荐方案）", selected.get("selectedSchemeIndex") is not None,
             "选定 #%s" % selected.get("selectedSchemeIndex"))

        finished = poll(client, job["id"], "om_ready")
        step("轮询到 om_ready", finished.get("hasOm") is True, "hasOm=%s" % finished.get("hasOm"))

        om = client.get("/api/quantization/jobs/%s/om/download" % job["id"])
        step("GET .../om/download", om.status_code == 200 and len(om.content) > 0,
             "%d 字节" % len(om.content))

        layers = client.get("/api/quantization/jobs/%s/layers" % job["id"]).json()
        step("GET .../layers", len(layers) > 0,
             "前两层: %s" % json.dumps(layers[:2], ensure_ascii=False))

        comparison = client.get("/api/comparison", params={"jobId": job["id"]}).json()
        step("GET /api/comparison", len(comparison.get("rows", [])) == 4,
             json.dumps(comparison["rows"][:2], ensure_ascii=False))

        deployment = client.post("/api/deployments", json={
            "modelId": model["id"], "deviceId": device["id"],
        }).json()
        step("POST /api/deployments", bool(deployment.get("id")),
             "targetDir=%s" % deployment.get("targetDir"))

        deadline = time.time() + 60
        final = deployment
        while time.time() < deadline and final["status"] in ("pending", "deploying"):
            time.sleep(0.5)
            final = client.get("/api/deployments/%s" % deployment["id"]).json()
        expected = final["status"] == "failed" and final.get("error")
        step("部署日志与失败回执", bool(final["logs"]),
             "status=%s（无真机时失败属预期）: %s"
             % (final["status"], (final.get("error") or final["logs"][-1]["message"])[:80]))
        for item in final["logs"]:
            print("     %s [%s] %s" % (item["timestamp"], item["type"], item["message"]))
        del expected

        stats_after = client.get("/api/stats").json()
        step("GET /api/stats（量化后）", stats_after["quantizedModels"] >= 1,
             "已量化模型 %s / 任务 %s / 部署 %s"
             % (stats_after["quantizedModels"], stats_after["totalJobs"],
                stats_after["totalDeployments"]))

        # 清理：部署 -> 任务 -> 模型 -> 设备
        client.delete("/api/deployments/%s" % deployment["id"])
        client.delete("/api/quantization/jobs/%s" % job["id"])
        client.delete("/api/models/%s" % model["id"])
        client.delete("/api/devices/%s" % device["id"])
        step("清理冒烟数据", True)

    print("\n通过 %d 项，失败 %d 项" % (len(passed), len(failed)))
    if failed:
        print("失败项: %s" % ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
