"""量化效果对比：传统全 INT8 vs 混合精度。

前端 ComparisonPage 当前用自己的公式在本地算（基于部署记录的 metrics 字段）；
本接口把同一份对比放到后端，数据来源是同一任务的工作目录
（layers.json + sensitivity.json + 选定方案的 layer_config），
两列严格可比：基线 = 全部层 INT8，混合 = 用户实际选定的位宽组合。
"""
import json
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from .. import metrics as metrics_mod
from ..db import get_session
from ..layers import read_layers_json
from ..models import Deployment, Model, QuantizationJob, Scheme
from ..schemas import ComparisonOut, ComparisonRowOut, RadarItemOut

router = APIRouter(prefix="/api/comparison", tags=["comparison"])

MAX_LATENCY_MS = 50.0        # 雷达图速度轴归一化上限
MAX_MEMORY_MB = 500.0        # 雷达图内存轴归一化上限
READY_JOB_STATUSES = ("om_ready", "deploying", "deployed")


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return round(max(low, min(high, value)), 1)


def _radar_scores(summary: dict) -> dict:
    """把一项方案的三项指标折算成 0~100 的雷达图分数（占位归一化，口径固定）。"""
    latency = float(summary.get("inferenceSpeed", 0) or 0)
    memory = float(summary.get("memoryUsage", 0) or 0)
    accuracy = float(summary.get("top1Accuracy", 0) or 0)
    speed = _clamp(100 - latency / MAX_LATENCY_MS * 100, 20)
    return {
        "精度": _clamp(accuracy),
        "速度": speed,
        "效率": _clamp(speed * 0.7 + accuracy * 0.3, 20),
        "内存": _clamp(100 - memory / MAX_MEMORY_MB * 100, 30),
        "功耗": _clamp(100 - latency / MAX_LATENCY_MS * 80, 20),
    }


def _build_radar(baseline: dict, mixed: dict) -> List[RadarItemOut]:
    traditional = _radar_scores(baseline)
    mixed_precision = _radar_scores(mixed)
    return [RadarItemOut(metric=key, traditional=traditional[key],
                         mixedPrecision=mixed_precision[key])
            for key in ("精度", "速度", "效率", "内存", "功耗")]


def _resolve_job(session: Session, deployment_id: Optional[str], job_id: Optional[str],
                 model_id: Optional[str]):
    if deployment_id:
        dep = session.get(Deployment, deployment_id)
        if dep is None:
            raise HTTPException(status_code=404, detail="部署记录不存在")
        job = session.get(QuantizationJob, dep.jobId)
        if job is None:
            raise HTTPException(status_code=404, detail="部署对应的量化任务不存在")
        return (dep, job)
    if job_id:
        job = session.get(QuantizationJob, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="量化任务不存在")
        return (None, job)
    if model_id:
        model = session.get(Model, model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="模型不存在")
        candidates = session.exec(select(QuantizationJob).where(
            QuantizationJob.modelId == model_id)
            .order_by(QuantizationJob.createdAt.desc())).all()
        for job in candidates:
            if job.selectedSchemeIndex is not None or job.status in READY_JOB_STATUSES:
                return (None, job)
        if candidates:
            return (None, candidates[0])
        raise HTTPException(status_code=404, detail="该模型还没有量化任务")
    raise HTTPException(status_code=400,
                        detail="需要提供 deploymentId / jobId / modelId 之一")


@router.get("", response_model=ComparisonOut)
def get_comparison(deploymentId: Optional[str] = None, jobId: Optional[str] = None,
                   modelId: Optional[str] = None,
                   session: Session = Depends(get_session)):
    dep, job = _resolve_job(session, deploymentId, jobId, modelId)

    scheme = None
    if job.selectedSchemeIndex is not None:
        scheme = session.exec(select(Scheme).where(
            Scheme.jobId == job.id, Scheme.index == job.selectedSchemeIndex)).first()
    if scheme is None:
        scheme = session.exec(select(Scheme).where(Scheme.jobId == job.id)
                              .order_by(Scheme.index)).first()
    if scheme is None:
        raise HTTPException(status_code=404, detail="该任务还没有可用方案，无法对比")

    workdir = Path(job.omPath).parent if job.omPath else None
    layer_list = read_layers_json(workdir) if workdir else []
    if not layer_list:
        # 兜底：用方案自带的层明细还原层体积
        try:
            layer_list = [{"name": item["name"], "sizeKb": item["originalSize"]}
                          for item in json.loads(scheme.layersJson or "[]")]
        except (ValueError, KeyError, TypeError):
            layer_list = []
    if not layer_list:
        raise HTTPException(status_code=409, detail="缺少层信息，无法生成对比数据")

    try:
        layer_config = json.loads(scheme.layerConfig or "{}")
    except ValueError:
        layer_config = {}
    sensitivity = metrics_mod.read_sensitivity(workdir) if workdir else {}
    model = session.get(Model, job.modelId)
    base_accuracy = model.baseAccuracy if model else 72.0

    rows = metrics_mod.build_comparison_rows(layer_list, layer_config, sensitivity,
                                            base_accuracy)
    baseline = metrics_mod.estimate_deployment_metrics(
        layer_list, metrics_mod.all_int8_config(layer_list), sensitivity, base_accuracy)
    mixed = metrics_mod.estimate_deployment_metrics(
        layer_list, layer_config, sensitivity, base_accuracy)

    radar = _build_radar(baseline, mixed)

    return ComparisonOut(
        deploymentId=dep.id if dep else None,
        jobId=job.id,
        modelId=job.modelId,
        modelName=model.name if model else None,
        mode="deployment" if dep else ("job" if jobId else "model"),
        mixedPrecisionLayers=sum(1 for value in layer_config.values()
                                 if str(value).upper() == "INT8"),
        traditionalLayers=len(layer_list),
        rows=[ComparisonRowOut(**row) for row in rows],
        radar=radar,
    )
