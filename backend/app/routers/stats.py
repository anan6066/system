"""首页统计：活跃设备 / 已量化模型 / 任务状态分布 / 部署次数 / 平均性能。"""
import json
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session, func, select

from ..db import get_session
from ..models import Deployment, Device, Model, QuantizationJob, now_iso
from ..schemas import StatsOut

router = APIRouter(prefix="/api/stats", tags=["stats"])

RUNNING_STATUSES = ("pending", "sensitivity_analysis", "scheme_search",
                    "quantizing", "converting", "deploying")


def _count(session: Session, model, *conditions) -> int:
    statement = select(func.count()).select_from(model)
    for condition in conditions:
        statement = statement.where(condition)
    return int(session.exec(statement).one() or 0)


def _successful_metrics(session: Session) -> List[dict]:
    rows = session.exec(select(Deployment).where(Deployment.status == "success")).all()
    parsed = []
    for row in rows:
        if not row.metrics:
            continue
        try:
            data = json.loads(row.metrics)
        except ValueError:
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def _average(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


@router.get("", response_model=StatsOut)
def get_stats(session: Session = Depends(get_session)):
    """首页四个统计卡 + 任务/部署分布（真实聚合，不是 mock）。"""
    online = _count(session, Device, Device.status == "online")
    busy = _count(session, Device, Device.status == "busy")
    running = _count(session, QuantizationJob,
                     QuantizationJob.status.in_(RUNNING_STATUSES))
    failed_jobs = _count(session, QuantizationJob, QuantizationJob.status == "failed")
    metrics_rows = _successful_metrics(session)

    speeds = [float(item.get("inferenceSpeed", 0) or 0) for item in metrics_rows]
    accuracies = [float(item.get("top1Accuracy", 0) or 0) for item in metrics_rows
                  if item.get("top1Accuracy")]

    return StatsOut(
        activeDevices=online,
        onlineDevices=online,
        busyDevices=busy,
        totalDevices=_count(session, Device),
        totalModels=_count(session, Model),
        quantizedModels=_count(session, Model, Model.status == "completed"),
        totalJobs=_count(session, QuantizationJob),
        runningJobs=running,
        readyJobs=_count(session, QuantizationJob, QuantizationJob.status == "om_ready"),
        failedJobs=failed_jobs,
        totalDeployments=_count(session, Deployment),
        successfulDeployments=_count(session, Deployment, Deployment.status == "success"),
        avgInferenceSpeed=_average(speeds),
        avgLatencyMs=_average(speeds),
        avgTop1Accuracy=_average(accuracies),
        generatedAt=now_iso(),
    )
