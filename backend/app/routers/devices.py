"""设备路由：CRUD + SSH 探活 + 板载指标（含监控折线历史）。

对应前端 DevicesPage：
* 卡片列表 / 新增 / 编辑 / 删除        -> GET/POST/PUT/DELETE /api/devices
* "检测"按钮                          -> POST /api/devices/{id}/check
* "监控"折线图（CPU/内存 2s 轮询）     -> GET  /api/devices/{id}/metrics[/history]
"""
import threading
import time
from collections import deque
from typing import Deque, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import ssh_client
from ..db import get_session
from ..models import Device, now_iso
from ..schemas import (CheckAllOut, CheckOut, DeviceCreate, DeviceOut,
                       DeviceUpdate, MetricSampleOut, MetricsHistoryOut,
                       MetricsOut, OkOut)

router = APIRouter(prefix="/api/devices", tags=["devices"])

# 设备指标环形缓冲：前端监控面板初始化时直接拿到历史曲线（无需等 20 个采样点）
_HISTORY_MAX = 60
_history: Dict[str, Deque[Dict[str, float]]] = {}
_history_lock = threading.Lock()


def _to_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id, name=device.name, ip=device.ip, port=device.port,
        username=device.username, authType=device.authType, npuType=device.npuType,
        status=device.status, cpuUsage=round(float(device.cpuUsage or 0), 1),
        memoryUsage=round(float(device.memoryUsage or 0), 1),
        npuUsage=device.npuUsage, note=device.note,
        lastConnected=device.lastConnected, lastChecked=device.lastChecked,
        lastError=device.lastError, createdAt=device.createdAt, updatedAt=device.updatedAt,
    )


def _get_or_404(session: Session, device_id: str) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


def _record_history(device_id: str, cpu: float, memory: float) -> None:
    sample = {"timestamp": int(time.time() * 1000), "cpu": float(cpu), "memory": float(memory)}
    with _history_lock:
        bucket = _history.setdefault(device_id, deque(maxlen=_HISTORY_MAX))
        bucket.append(sample)


def _read_history(device_id: str, limit: int) -> List[Dict[str, float]]:
    with _history_lock:
        bucket = _history.get(device_id)
        samples = list(bucket) if bucket else []
    return samples[-limit:] if limit > 0 else samples


@router.get("", response_model=List[DeviceOut])
def list_devices(session: Session = Depends(get_session)):
    devices = session.exec(select(Device).order_by(Device.createdAt)).all()
    return [_to_out(device) for device in devices]


@router.post("", response_model=DeviceOut)
def create_device(payload: DeviceCreate, session: Session = Depends(get_session)):
    if not payload.ip.strip():
        raise HTTPException(status_code=400, detail="设备 IP 不能为空")
    if not payload.username.strip():
        raise HTTPException(status_code=400, detail="登录账号不能为空")
    if payload.authType == "key" and not payload.keyPath:
        raise HTTPException(status_code=400, detail="密钥登录必须提供 keyPath")
    if not 1 <= int(payload.port) <= 65535:
        raise HTTPException(status_code=400, detail="端口需在 1~65535 之间")

    stamp = now_iso()
    device = Device(
        name=payload.name.strip() or payload.ip.strip(),
        ip=payload.ip.strip(), port=int(payload.port), username=payload.username.strip(),
        authType=payload.authType if payload.authType in ("pwd", "key") else "pwd",
        password=payload.password, keyPath=payload.keyPath,
        npuType=(payload.npuType or "ascend").lower(), note=payload.note,
        status="offline", lastConnected=stamp, createdAt=stamp, updatedAt=stamp,
    )
    session.add(device)
    session.commit()
    session.refresh(device)
    return _to_out(device)


@router.post("/check-all", response_model=CheckAllOut)
def check_all_devices(session: Session = Depends(get_session)):
    """批量探活：设备页/首页刷新时一次把所有设备状态刷成真实值。"""
    devices = session.exec(select(Device)).all()
    results = []
    online_count = 0
    for device in devices:
        online, latency, error = ssh_client.measure_latency(device)
        if online:
            online_count += 1
            device.status = "online"
            device.lastConnected = now_iso()
            device.lastError = None
        elif device.status != "busy":
            device.status = "offline"
            device.lastError = error
        device.lastChecked = now_iso()
        device.updatedAt = now_iso()
        session.add(device)
        results.append({"id": device.id, "name": device.name, "online": online,
                        "status": device.status, "latencyMs": latency, "error": error})
    session.commit()
    return CheckAllOut(total=len(devices), online=online_count,
                       offline=len(devices) - online_count, results=results)


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: str, session: Session = Depends(get_session)):
    return _to_out(_get_or_404(session, device_id))


@router.put("/{device_id}", response_model=DeviceOut)
def update_device(device_id: str, payload: DeviceUpdate,
                  session: Session = Depends(get_session)):
    device = _get_or_404(session, device_id)
    updates = payload.model_dump(exclude_unset=True)
    if updates.get("authType") == "key" and not (updates.get("keyPath") or device.keyPath):
        raise HTTPException(status_code=400, detail="密钥登录必须提供 keyPath")
    if "port" in updates and updates["port"] is not None and not 1 <= int(updates["port"]) <= 65535:
        raise HTTPException(status_code=400, detail="端口需在 1~65535 之间")
    for key, value in updates.items():
        if key == "npuType" and value:
            value = str(value).lower()
        if value is not None:
            setattr(device, key, value)
    device.updatedAt = now_iso()
    session.add(device)
    session.commit()
    session.refresh(device)
    return _to_out(device)


@router.delete("/{device_id}", response_model=OkOut)
def delete_device(device_id: str, session: Session = Depends(get_session)):
    device = _get_or_404(session, device_id)
    session.delete(device)
    session.commit()
    with _history_lock:
        _history.pop(device_id, None)
    return OkOut(detail="设备已删除")


@router.post("/{device_id}/check", response_model=CheckOut)
def check_device(device_id: str, session: Session = Depends(get_session)):
    """真实 SSH 探活（替换前端的假检测）。"""
    device = _get_or_404(session, device_id)
    online, latency, error = ssh_client.measure_latency(device)
    if online:
        device.status = "online"
        device.lastConnected = now_iso()
        device.lastError = None
    elif device.status != "busy":
        device.status = "offline"
        device.lastError = error
    device.lastChecked = now_iso()
    device.updatedAt = now_iso()
    session.add(device)
    session.commit()
    return CheckOut(online=online, status=device.status, latencyMs=latency,
                    lastConnected=device.lastConnected, error=error or None)


@router.get("/{device_id}/metrics", response_model=MetricsOut)
def device_metrics(device_id: str, session: Session = Depends(get_session)):
    """SSH 采集板载 CPU/内存（前端监控面板的实时值）。"""
    device = _get_or_404(session, device_id)
    try:
        metrics = ssh_client.get_metrics(device)
    except Exception as exc:  # noqa: BLE001 —— 网络/认证/命令失败统一转 502
        device.status = "offline" if device.status != "busy" else device.status
        device.lastError = str(exc)
        device.lastChecked = now_iso()
        session.add(device)
        session.commit()
        raise HTTPException(status_code=502, detail="指标采集失败: %s" % exc)

    device.cpuUsage = float(metrics.get("cpuUsage", 0.0) or 0.0)
    device.memoryUsage = float(metrics.get("memoryUsage", 0.0) or 0.0)
    device.npuUsage = metrics.get("npuUsage")
    device.lastChecked = now_iso()
    if device.status == "offline":
        device.status = "online"
        device.lastConnected = now_iso()
    device.updatedAt = now_iso()
    session.add(device)
    session.commit()

    _record_history(device.id, device.cpuUsage, device.memoryUsage)
    return MetricsOut(cpuUsage=device.cpuUsage, memoryUsage=device.memoryUsage,
                      npuUsage=device.npuUsage,
                      collectedAt=metrics.get("collectedAt") or now_iso())


@router.get("/{device_id}/metrics/history", response_model=MetricsHistoryOut)
def device_metrics_history(device_id: str, limit: int = 30,
                           session: Session = Depends(get_session)):
    """监控折线图的历史采样点（timestamp 为 epoch 毫秒，对齐前端 DeviceMetrics）。"""
    _get_or_404(session, device_id)
    samples = _read_history(device_id, max(1, min(int(limit or 30), _HISTORY_MAX)))
    return MetricsHistoryOut(deviceId=device_id,
                             samples=[MetricSampleOut(**item) for item in samples])
