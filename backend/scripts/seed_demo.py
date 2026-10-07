"""给前端手工走查灌一套演示数据（不依赖开发板）。

用法（先把后端起起来：scripts\\local.cmd serve）：

    python scripts/seed_demo.py                       # 建 2 台设备 + 2 个已量化模型
    python scripts/seed_demo.py --with-deployment     # 额外发起一次部署（无真机会失败，但能看到日志面板）
    python scripts/seed_demo.py --fake-online         # 把设备状态直接改成 online（仅本机界面走查用）

    # 有 SSH 可达的机器（ECS / WSL / 开发板）时，接成"真机"，监控与部署都是真实数据：
    python scripts/seed_demo.py --real-device 121.43.244.6 ecs-user 密码
    python scripts/seed_demo.py --real-device 121.43.244.6 ecs-user --key ~/.ssh/id_rsa

说明：
* 幂等——同名设备/同预设模型已存在时跳过，可重复执行；
* --fake-online 直接改 SQLite 的 device.status（绕过真实探活），
  只为了让"监控"面板和"部署"下拉框有东西可选，真实状态请以设备页"检测"为准。
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx

BACKEND_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "http://127.0.0.1:8000"
DEPLOY_DIR = "/data/models"
SAMPLE_DEVICES = [
    {"name": "演示板-01", "ip": "192.168.10.11", "port": 22, "username": "root",
     "password": "demo", "npuType": "ascend"},
    {"name": "演示板-02", "ip": "192.168.10.12", "port": 22, "username": "root",
     "password": "demo", "npuType": "ascend"},
]
SAMPLE_PRESETS = ["mobilenetv2", "resnet18"]


def step(text):
    print("[seed] %s" % text, flush=True)


def fail(text):
    print("[seed] 失败: %s" % text, flush=True)
    sys.exit(1)


def call(method, client, path, payload=None, expect=200):
    """发请求并把后端的错误体原样报出来，避免出现莫名的 KeyError。"""
    response = client.request(method, path, json=payload)
    if response.status_code != expect:
        fail("%s %s -> HTTP %s: %s" % (method, path, response.status_code, response.text[:400]))
    return response.json()


def wait_job(client, job_id, target, timeout=180.0):
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = call("GET", client, "/api/quantization/jobs/%s" % job_id)
        if last.get("status") == target:
            return last
        if last.get("status") == "failed":
            fail("量化任务失败: %s" % last.get("error"))
        time.sleep(0.3)
    fail("等待 %s 超时，最后状态 %s" % (target, last.get("status")))


def ensure_device(client, payload):
    existing = [d for d in call("GET", client, "/api/devices") if d["name"] == payload["name"]]
    if existing:
        step("设备已存在，跳过：%s" % payload["name"])
        return existing[0]
    device = call("POST", client, "/api/devices", payload)
    step("创建设备：%s (%s)" % (device["name"], device["ip"]))
    return device


def ensure_quantized_model(client, preset):
    models = call("GET", client, "/api/models")
    done = [m for m in models if m.get("preset") == preset and m["status"] == "completed"]
    if done:
        step("已量化模型已存在，跳过：%s" % done[0]["name"])
        return done[0]

    model = next((m for m in models if m.get("preset") == preset), None)
    if model is None:
        model = call("POST", client, "/api/models/preset", {"preset": preset})
        step("创建模型：%s（%d 层）" % (model["name"], model["layerCount"]))

    step("跑量化任务：%s（HAWQ → NSGA-II → AMCT → ATC）" % model["name"])
    job = call("POST", client, "/api/quantization/jobs", {"modelId": model["id"]})
    ready = wait_job(client, job["id"], "scheme_ready")
    schemes = call("GET", client, "/api/quantization/jobs/%s/schemes" % job["id"])
    index = next((s["index"] for s in schemes if s["recommended"]), schemes[0]["index"])
    chosen = next(s for s in schemes if s["index"] == index)
    step("  方案就绪：%d 个候选，选推荐方案 #%s（体积 %.2fMB / 延迟 %.1fms / 精度损失 %.2fpp）"
         % (len(schemes), index, chosen["metrics"]["sizeMb"],
            chosen["metrics"]["latencyMs"], chosen["metrics"]["accuracyLossPct"]))
    call("POST", client, "/api/quantization/jobs/%s/select" % job["id"], {"schemeIndex": index})
    finished = wait_job(client, job["id"], "om_ready")
    step("  量化完成：job=%s hasOm=%s schemes=%s"
         % (finished["id"][:8], finished["hasOm"], ready["schemeCount"]))
    return call("GET", client, "/api/models/%s" % model["id"])


def fake_online(device_id, db_path):
    """仅本机界面走查用：直接把设备状态改成 online。"""
    if not Path(db_path).exists():
        step("--fake-online 跳过：找不到数据库 %s" % db_path)
        return
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("UPDATE device SET status = 'online' WHERE id = ?", (device_id,))
        conn.commit()
    step("已把设备 %s 的状态直接改为 online（绕过真实探活，仅用于界面走查）" % device_id[:8])


def fake_success_deployment(client, model, device, db_path):
    """仅本机界面走查用：直接往库里写一条"部署成功"记录（含指标与日志）。

    真实部署必须 SSH 到开发板；没有板子时用这条假数据才能走查"效果对比"页。
    """
    if not Path(db_path).exists():
        step("--fake-deployment 跳过：找不到数据库 %s" % db_path)
        return None
    jobs = call("GET", client, "/api/quantization/jobs?modelId=%s" % model["id"])
    job = next((j for j in jobs if j["status"] in ("om_ready", "deployed")), None)
    if job is None:
        step("--fake-deployment 跳过：%s 还没有可部署的任务" % model["name"])
        return None

    schemes = call("GET", client, "/api/quantization/jobs/%s/schemes" % job["id"])
    scheme = next((s for s in schemes if s.get("isSelected")), schemes[0])
    metrics = {
        "inferenceSpeed": round(scheme["metrics"]["latencyMs"], 2),
        "memoryUsage": round(scheme["metrics"]["sizeMb"] * 18.0 + 120.0, 1),
        "top1Accuracy": round(model.get("baseAccuracy", 72.0) - scheme["metrics"]["accuracyLossPct"], 1),
    }
    now = datetime.utcnow().replace(microsecond=0)
    start = now - timedelta(seconds=42)
    stamp = lambda t: t.isoformat() + "Z"  # noqa: E731
    clock = lambda t: t.strftime("%H:%M:%S")  # noqa: E731
    messages = [
        (start, "info", "开始部署任务"),
        (start, "info", "正在上传量化模型文件..."),
        (start + timedelta(seconds=6), "success", "模型文件上传完成 -> %s/model.om" % DEPLOY_DIR),
        (start + timedelta(seconds=8), "info", "正在初始化 NPU 环境..."),
        (start + timedelta(seconds=11), "success", "NPU 初始化成功"),
        (start + timedelta(seconds=12), "info", "开始推理速度测试..."),
        (start + timedelta(seconds=30), "success", "推理测试完成"),
        (start + timedelta(seconds=31), "info", "正在采集性能指标..."),
        (now, "success", "部署成功"),
    ]
    logs = [{"id": str(i + 1), "timestamp": clock(t), "message": m, "type": k}
            for i, (t, k, m) in enumerate(messages)]

    deployment_id = uuid4().hex
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            "INSERT INTO deployment (id, jobId, modelId, deviceId, targetDir, remoteFile, status,"
            " progress, logs, metrics, metricsSource, error, startTime, endTime, createdAt, updatedAt)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (deployment_id, job["id"], model["id"], device["id"], DEPLOY_DIR,
             "%s/%s_%s.om" % (DEPLOY_DIR, model["name"], job["id"][:8]), "success", 100,
             json.dumps(logs, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False),
             "estimated", None, stamp(start), stamp(now), stamp(start), stamp(now)))
        conn.commit()
    step("已写入一条【演示用】成功部署记录 %s（指标：%.1fms / %.0fMB / %.1f%%）"
         % (deployment_id[:8], metrics["inferenceSpeed"], metrics["memoryUsage"],
            metrics["top1Accuracy"]))
    step("  注意：这条不是真实推送结果，只为在没有开发板时走查「效果对比」页")
    return deployment_id


def create_deployment(client, model, device):
    step("发起部署：%s → %s" % (model["name"], device["name"]))
    created = call("POST", client, "/api/deployments", {
        "modelId": model["id"], "deviceId": device["id"]})
    deadline = time.time() + 90
    dep = created
    while time.time() < deadline and dep["status"] in ("pending", "deploying"):
        time.sleep(0.5)
        dep = call("GET", client, "/api/deployments/%s" % dep["id"])
    step("  部署结束：status=%s metricsSource=%s" % (dep["status"], dep.get("metricsSource")))
    for item in dep["logs"]:
        print("      %s [%s] %s" % (item["timestamp"], item["type"], item["message"]))
    return dep


def main():
    parser = argparse.ArgumentParser(description="给前端走查灌演示数据")
    parser.add_argument("base_url", nargs="?", default=DEFAULT_BASE)
    parser.add_argument("--with-deployment", action="store_true",
                        help="额外发起一次部署（无真机时会失败，用于查看日志面板与重试）")
    parser.add_argument("--fake-online", action="store_true",
                        help="把第一台设备状态直接改成 online（仅本机界面走查用）")
    parser.add_argument("--fake-deployment", action="store_true",
                        help="写一条【演示用】成功部署记录，让「效果对比」页有数据（仅本机走查用）")
    parser.add_argument("--real-device", nargs="+", metavar="ARG",
                        help="接入真实 SSH 设备：--real-device HOST USER [PASSWORD] [--key KEYPATH]")
    parser.add_argument("--key", help="配合 --real-device 使用的私钥路径（密钥登录）")
    parser.add_argument("--db", default=str(BACKEND_ROOT / "app.db"),
                        help="--fake-online 使用的 SQLite 路径（默认 backend/app.db）")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0) as client:
        try:
            health = client.get("/api/health").json()
        except Exception as exc:  # noqa: BLE001
            fail("连不上后端 %s（%s）。请先执行 scripts\\local.cmd serve" % (args.base_url, exc))
        step("后端在线：%s" % health)

        real_device = None
        if args.real_device:
            parts = args.real_device
            if len(parts) < 2:
                fail("--real-device 至少需要 HOST 和 USER")
            host, user = parts[0], parts[1]
            payload = {"name": "真机-%s" % host, "ip": host, "port": 22, "username": user,
                       "npuType": "ascend"}
            if args.key:
                payload["authType"] = "key"
                payload["keyPath"] = os.path.expanduser(args.key)
            elif len(parts) >= 3:
                payload["password"] = parts[2]
            else:
                fail("密码登录请带上密码，或使用 --key 指定私钥")
            real_device = ensure_device(client, payload)
            checked = call("POST", client, "/api/devices/%s/check" % real_device["id"])
            step("真实探活：online=%s latency=%sms error=%s"
                 % (checked["online"], checked["latencyMs"], checked["error"]))
            if checked["online"]:
                metrics = call("GET", client, "/api/devices/%s/metrics" % real_device["id"])
                step("真实指标：CPU %.1f%% / 内存 %.1f%%" % (metrics["cpuUsage"], metrics["memoryUsage"]))

        devices = [real_device] if real_device else [ensure_device(client, item) for item in SAMPLE_DEVICES]
        models = [ensure_quantized_model(client, preset) for preset in SAMPLE_PRESETS]

        if args.fake_online and not real_device:
            fake_online(devices[0]["id"], args.db)

        if args.with_deployment:
            target = real_device or devices[0]
            create_deployment(client, models[0], target)

        if args.fake_deployment and not args.with_deployment:
            fake_success_deployment(client, models[0], devices[0], args.db)

        stats = call("GET", client, "/api/stats")
        step("当前数据：设备 %d（在线 %d）/ 模型 %d（已量化 %d）/ 任务 %d / 部署 %d"
             % (stats["totalDevices"], stats["activeDevices"], stats["totalModels"],
                stats["quantizedModels"], stats["totalJobs"], stats["totalDeployments"]))

    print("""
[seed] 完成。打开前端 http://localhost:5173 可以看：
  首页       —— 活跃设备 / 已量化模型 / 部署次数 / 平均延迟（真实聚合）
  设备管理   —— 设备卡片、检测按钮、监控面板（真机时才有真实曲线）
  模型量化   —— 预设下拉已有模型；重新走一遍「生成方案 → 选方案 → 开始量化 → 导出 .om」
  一键部署   —— 模型下拉已过滤出已量化模型
  效果对比   —— 有成功部署后会自动选中最近一条并出图
""")


if __name__ == "__main__":
    main()
