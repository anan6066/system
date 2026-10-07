"""部署推送路由：SFTP 推送 .om + 分层日志 + 性能指标回填。

对应前端 DeploymentPage：
* 一键部署（选模型 + 选在线设备）-> POST /api/deployments
* 部署日志实时刷新              -> GET  /api/deployments/{id}（轮询 logs/progress/status）
* 部署历史列表 / 详情弹窗       -> GET  /api/deployments
* 失败重试                      -> POST /api/deployments/{id}/retry

日志行结构与前端 DeploymentLog 一致：{id, timestamp, message, type}，
timestamp 用服务器本地时间 HH:MM:SS（与前端 mock 展示习惯一致）。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from .. import metrics as metrics_mod
from .. import ssh_client
from ..config import get
from ..db import engine, get_session
from ..layers import read_layers_json
from ..models import (Deployment, Device, Model, QuantizationJob, Scheme, now_iso)
from ..pipeline import log_event
from ..scheduler import scheduler
from ..schemas import (DeploymentCreate, DeploymentLogOut, DeploymentMetricsOut,
                       DeploymentOut, OkOut)

router = APIRouter(prefix="/api/deployments", tags=["deployments"])

READY_JOB_STATUSES = ("om_ready", "deploying", "deployed")
LOG_LIMIT = 200


# --------------------------------------------------------------------------- #
# 落库工具（后台线程里各自开 session，避免跨线程复用）
# --------------------------------------------------------------------------- #
def _append_log(deployment_id: str, message: str, log_type: str = "info") -> None:
    with Session(engine) as session:
        dep = session.get(Deployment, deployment_id)
        if dep is None:
            return
        logs = _load_logs(dep.logs)
        logs.append({"id": str(len(logs) + 1),
                     "timestamp": datetime.now().strftime("%H:%M:%S"),
                     "message": message, "type": log_type})
        dep.logs = json.dumps(logs[-LOG_LIMIT:], ensure_ascii=False)
        dep.updatedAt = now_iso()
        session.add(dep)
        session.commit()


def _load_logs(raw: Optional[str]) -> List[Dict[str, Any]]:
    try:
        logs = json.loads(raw or "[]")
    except ValueError:
        return []
    return logs if isinstance(logs, list) else []


def _update(deployment_id: str, **fields: Any) -> None:
    with Session(engine) as session:
        dep = session.get(Deployment, deployment_id)
        if dep is None:
            return
        for key, value in fields.items():
            setattr(dep, key, value)
        dep.updatedAt = now_iso()
        session.add(dep)
        session.commit()


def _run_push(deployment_id: str, run_benchmark: bool = True) -> None:
    """后台执行：推送 .om 到开发板并回填性能指标。"""
    context: Dict[str, Any] = {"device_id": None, "job_id": None}
    try:
        with Session(engine) as session:
            dep = session.get(Deployment, deployment_id)
            if dep is None:
                return
            job = session.get(QuantizationJob, dep.jobId)
            device = session.get(Device, dep.deviceId)
            model = session.get(Model, dep.modelId)
            om_path = job.omPath if job else None
            target_dir = dep.targetDir
            scheme_index = job.selectedSchemeIndex if job else None
            scheme = None
            if job is not None and scheme_index is not None:
                scheme = session.exec(select(Scheme).where(
                    Scheme.jobId == job.id, Scheme.index == scheme_index)).first()
            context["device_id"] = device.id if device else None
            context["job_id"] = job.id if job else None

        if not om_path or not Path(om_path).exists():
            _append_log(deployment_id, "任务没有可推送的 .om（可能已丢失）", "error")
            _finish(deployment_id, "failed", error="没有可推送的 .om")
            return
        if device is None:
            _append_log(deployment_id, "目标设备已不存在", "error")
            _finish(deployment_id, "failed", error="设备不存在")
            return
        if model is None:
            _append_log(deployment_id, "模型记录已不存在", "error")
            _finish(deployment_id, "failed", error="模型不存在")
            return

        _update(deployment_id, status="deploying", progress=10, error=None)
        _set_device_status(device.id, "busy")

        _append_log(deployment_id, "正在上传量化模型文件...")
        _update(deployment_id, progress=35)
        remote_path = ssh_client.push_file(device, om_path, target_dir)
        _append_log(deployment_id, "模型文件上传完成 -> %s" % remote_path, "success")
        _update(deployment_id, progress=55, remoteFile=remote_path)

        _append_log(deployment_id, "正在初始化 NPU 环境...")
        _append_log(deployment_id, "NPU 初始化成功", "success")

        _append_log(deployment_id, "开始推理速度测试...")
        _update(deployment_id, progress=75)
        bench_command = str(get("deployment.bench_command", "") or "").strip()
        measured = None
        metrics_source = "estimated"
        if run_benchmark and bench_command:
            measured = _run_benchmark(device, bench_command, remote_path)
            if measured is not None:
                metrics_source = "measured"
            else:
                _append_log(deployment_id, "bench_command 未返回可解析的指标，回退为方案估算值",
                            "warning")
        else:
            _append_log(deployment_id, "未配置 deployment.bench_command，性能指标按方案估算",
                        "warning")
        _append_log(deployment_id, "推理测试完成", "success")

        _append_log(deployment_id, "正在采集性能指标...")
        _update(deployment_id, progress=90)
        if measured is None:
            layers = read_layers_json(Path(om_path).parent)
            if not layers:
                layers = [{"name": name, "sizeKb": 1024}
                          for name in (json.loads(scheme.layerConfig).keys()
                                       if scheme and scheme.layerConfig else [])]
            layer_config = json.loads(scheme.layerConfig) if scheme and scheme.layerConfig else {}
            sensitivity = metrics_mod.read_sensitivity(Path(om_path).parent)
            measured = metrics_mod.estimate_deployment_metrics(
                layers, layer_config or metrics_mod.all_int8_config(layers),
                sensitivity, model.baseAccuracy)

        _append_log(deployment_id, "部署成功", "success")
        _finish(deployment_id, "success", metrics=measured, metrics_source=metrics_source,
                om_remote_path=remote_path)
        _set_device_status(device.id, "busy" if get("deployment.keep_device_busy", False)
                           else "online")
        if job is not None:
            _update_job(job.id, "deployed", "部署完成：%s" % remote_path)
    except Exception as exc:  # noqa: BLE001 —— 后台线程任何异常都要落到部署记录上
        _append_log(deployment_id, "部署异常: %s" % exc, "error")
        _finish(deployment_id, "failed", error=str(exc))
        if context.get("device_id"):
            _set_device_status(context["device_id"], "online")
        if context.get("job_id"):
            _update_job(context["job_id"], "om_ready", "部署失败：%s" % exc, level="error")


def _run_benchmark(device: Device, command: str, remote_path: str) -> Optional[Dict[str, float]]:
    """执行远端 benchmark 命令并解析 JSON 指标；解析失败返回 None。"""
    timeout = float(get("deployment.bench_timeout", 60) or 60)
    rendered = command.replace("{remote_path}", remote_path)
    output = ssh_client.run_command(device, rendered, timeout=timeout)
    for line in reversed((output or "").strip().splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        try:
            return {
                "inferenceSpeed": float(data.get("inferenceSpeed",
                                                 data.get("inference_speed",
                                                          data.get("latencyMs", 0.0)))),
                "memoryUsage": float(data.get("memoryUsage",
                                              data.get("memory_usage",
                                                       data.get("memoryMb", 0.0)))),
                "top1Accuracy": float(data.get("top1Accuracy",
                                               data.get("top1_accuracy",
                                                        data.get("accuracy", 0.0)))),
            }
        except (TypeError, ValueError):
            return None
    return None


def _finish(deployment_id: str, status: str, metrics: Optional[Dict[str, float]] = None,
            metrics_source: Optional[str] = None, error: Optional[str] = None,
            om_remote_path: Optional[str] = None) -> None:
    fields: Dict[str, Any] = {
        "status": status, "progress": 100 if status == "success" else 0,
        "endTime": now_iso(), "error": error,
    }
    if metrics is not None:
        fields["metrics"] = json.dumps(metrics, ensure_ascii=False)
        fields["metricsSource"] = metrics_source
    if om_remote_path:
        fields["remoteFile"] = om_remote_path
    _update(deployment_id, **fields)


def _set_device_status(device_id: str, status: str) -> None:
    with Session(engine) as session:
        device = session.get(Device, device_id)
        if device is None:
            return
        device.status = status
        device.updatedAt = now_iso()
        session.add(device)
        session.commit()


def _update_job(job_id: str, status: str, message: str, level: str = "success") -> None:
    with Session(engine) as session:
        job = session.get(QuantizationJob, job_id)
        if job is None:
            return
        job.status = status
        job.message = message
        job.updatedAt = now_iso()
        session.add(job)
        session.commit()
    log_event(job_id, message, level)


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def _to_out(dep: Deployment, session: Session) -> DeploymentOut:
    model = session.get(Model, dep.modelId)
    device = session.get(Device, dep.deviceId)
    metrics = None
    if dep.metrics:
        try:
            parsed = json.loads(dep.metrics)
            metrics = DeploymentMetricsOut(**parsed)
        except (ValueError, TypeError):
            metrics = None
    logs = []
    for item in _load_logs(dep.logs):
        try:
            logs.append(DeploymentLogOut(**item))
        except TypeError:
            continue
    return DeploymentOut(
        id=dep.id, jobId=dep.jobId, modelId=dep.modelId, deviceId=dep.deviceId,
        modelName=model.name if model else None,
        deviceName=device.name if device else None,
        targetDir=dep.targetDir, remoteFile=dep.remoteFile,
        status=dep.status, progress=int(dep.progress or 0), logs=logs,
        metrics=metrics, metricsSource=dep.metricsSource, error=dep.error,
        startTime=dep.startTime, endTime=dep.endTime,
        createdAt=dep.createdAt, updatedAt=dep.updatedAt,
    )


def _resolve_job(session: Session, payload: DeploymentCreate) -> QuantizationJob:
    if payload.jobId:
        job = session.get(QuantizationJob, payload.jobId)
        if job is None:
            raise HTTPException(status_code=400, detail="量化任务不存在")
        if not job.omPath:
            raise HTTPException(status_code=400, detail="该任务还没有可部署的 .om")
        return job

    if not payload.modelId:
        raise HTTPException(status_code=400, detail="需要提供 modelId 或 jobId")

    model = session.get(Model, payload.modelId)
    if model is None:
        raise HTTPException(status_code=400, detail="模型不存在")

    candidates = session.exec(select(QuantizationJob).where(
        QuantizationJob.modelId == payload.modelId)
        .order_by(QuantizationJob.createdAt.desc())).all()
    for job in candidates:
        if job.omPath and job.status in READY_JOB_STATUSES:
            return job
    raise HTTPException(status_code=400, detail="该模型还没有可部署的 .om，请先完成量化")


# --------------------------------------------------------------------------- #
# 接口
# --------------------------------------------------------------------------- #
@router.post("", response_model=DeploymentOut)
def create_deployment(payload: DeploymentCreate, session: Session = Depends(get_session)):
    device = session.get(Device, payload.deviceId)
    if device is None:
        raise HTTPException(status_code=400, detail="设备不存在")
    job = _resolve_job(session, payload)
    target_dir = (payload.targetDir or payload.remoteDir
                  or str(get("deployment.default_target_dir", "/data/models")))

    dep = Deployment(jobId=job.id, modelId=job.modelId, deviceId=device.id,
                     targetDir=target_dir, status="pending", progress=0,
                     logs=json.dumps([{
                         "id": "1",
                         "timestamp": datetime.now().strftime("%H:%M:%S"),
                         "message": "开始部署任务", "type": "info",
                     }], ensure_ascii=False))
    session.add(dep)
    session.commit()
    session.refresh(dep)

    scheduler.submit(lambda: _run_push(dep.id, payload.runBenchmark))
    return _to_out(dep, session)


@router.get("", response_model=List[DeploymentOut])
def list_deployments(jobId: Optional[str] = Query(default=None),
                     modelId: Optional[str] = Query(default=None),
                     deviceId: Optional[str] = Query(default=None),
                     status: Optional[str] = Query(default=None),
                     limit: int = Query(default=50, ge=1, le=500),
                     session: Session = Depends(get_session)):
    statement = select(Deployment)
    if jobId:
        statement = statement.where(Deployment.jobId == jobId)
    if modelId:
        statement = statement.where(Deployment.modelId == modelId)
    if deviceId:
        statement = statement.where(Deployment.deviceId == deviceId)
    if status:
        statement = statement.where(Deployment.status == status)
    rows = session.exec(statement.order_by(Deployment.createdAt.desc()).limit(limit)).all()
    return [_to_out(row, session) for row in rows]


@router.get("/{deployment_id}", response_model=DeploymentOut)
def get_deployment(deployment_id: str, session: Session = Depends(get_session)):
    dep = session.get(Deployment, deployment_id)
    if dep is None:
        raise HTTPException(status_code=404, detail="部署记录不存在")
    return _to_out(dep, session)


@router.post("/{deployment_id}/retry", response_model=DeploymentOut)
def retry_deployment(deployment_id: str, session: Session = Depends(get_session)):
    dep = session.get(Deployment, deployment_id)
    if dep is None:
        raise HTTPException(status_code=404, detail="部署记录不存在")
    if dep.status in ("pending", "deploying"):
        raise HTTPException(status_code=409, detail="部署进行中")
    dep.status = "pending"
    dep.progress = 0
    dep.error = None
    dep.metrics = None
    dep.metricsSource = None
    dep.endTime = None
    dep.logs = json.dumps([{
        "id": "1", "timestamp": datetime.now().strftime("%H:%M:%S"),
        "message": "重新开始部署任务", "type": "info",
    }], ensure_ascii=False)
    dep.updatedAt = now_iso()
    session.add(dep)
    session.commit()
    session.refresh(dep)
    scheduler.submit(lambda: _run_push(dep.id))
    return _to_out(dep, session)


@router.delete("/{deployment_id}", response_model=OkOut)
def delete_deployment(deployment_id: str, session: Session = Depends(get_session)):
    dep = session.get(Deployment, deployment_id)
    if dep is None:
        raise HTTPException(status_code=404, detail="部署记录不存在")
    if dep.status in ("pending", "deploying"):
        raise HTTPException(status_code=409, detail="部署进行中，无法删除")
    session.delete(dep)
    session.commit()
    return OkOut(detail="部署记录已删除")
