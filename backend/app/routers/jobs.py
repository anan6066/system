"""量化任务路由（8 态状态机 + 帕累托前沿 + .om 下载）。

对应前端 QuantizationPage / DeploymentPage：
* 生成量化方案（① HAWQ + ② NSGA-II）-> POST /api/quantization/jobs
* 轮询进度                          -> GET  /api/quantization/jobs/{id}（1~2s 一次）
* 展示帕累托前沿让用户选方案         -> GET  /api/quantization/jobs/{id}/schemes
* 开始量化（④ AMCT + ⑤ ATC）         -> POST /api/quantization/jobs/{id}/select
* 导出/下载量化后模型 .om            -> GET  /api/quantization/jobs/{id}/om/download
"""
import json
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from ..db import get_session
from ..models import (Deployment, JobLog, Model, QuantizationJob, Scheme, now_iso)
from ..pipeline import (RUNNING_STATUSES, job_dir, log_event,
                        recommended_scheme_index, run_first_phase,
                        run_second_phase, set_model_status, prepare_workspace)
from ..scheduler import scheduler
from ..schemas import JobCreate, JobLogOut, JobOut, OkOut, QuantizationLayerOut, SchemeOut, SelectSchemeIn

router = APIRouter(prefix="/api/quantization/jobs", tags=["jobs"])

OM_READY_STATUSES = ("om_ready", "deploying", "deployed")
# 可取消的状态：正在跑的阶段 + 停在 scheme_ready 等用户选择的状态
CANCELABLE_STATUSES = tuple(RUNNING_STATUSES) + ("scheme_ready",)


# --------------------------------------------------------------------------- #
# 序列化
# --------------------------------------------------------------------------- #
def _to_out(job: QuantizationJob, session: Session) -> JobOut:
    model = session.get(Model, job.modelId)
    return JobOut(
        id=job.id, modelId=job.modelId, modelName=model.name if model else None,
        status=job.status, progress=int(job.progress or 0), message=job.message or "",
        stage=job.stage or "", targetNPU=job.targetNPU,
        selectedSchemeIndex=job.selectedSchemeIndex, schemeCount=int(job.schemeCount or 0),
        hasOm=bool(job.omPath and Path(job.omPath).exists()),
        omPath=job.omPath, error=job.error,
        createdAt=job.createdAt, updatedAt=job.updatedAt,
        startedAt=job.startedAt, finishedAt=job.finishedAt,
    )


def _get_or_404(session: Session, job_id: str) -> QuantizationJob:
    job = session.get(QuantizationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


def _scheme_out(row: Scheme, recommended: bool = False) -> SchemeOut:
    def _load(raw: str, fallback):
        try:
            value = json.loads(raw or "")
        except ValueError:
            return fallback
        return value if isinstance(value, type(fallback)) else fallback

    layers = _load(row.layersJson, [])
    stats = {
        "int8Layers": row.int8Layers, "fp16Layers": row.fp16Layers,
        "fp32Layers": row.fp32Layers, "originalSizeKb": row.sizeKb,
        "quantizedSizeKb": row.quantizedSizeKb, "compressionRatio": row.compressionRatio,
    }
    return SchemeOut(
        index=row.index,
        layerConfig=_load(row.layerConfig, {}),
        objectives=_load(row.objectives, {}),
        metrics=_load(row.metrics, {}),
        layers=[QuantizationLayerOut(**item) for item in layers],
        stats=stats, isSelected=bool(row.isSelected), recommended=recommended,
    )


def _selected_layers(job: QuantizationJob, session: Session) -> List[QuantizationLayerOut]:
    scheme = None
    if job.selectedSchemeIndex is not None:
        scheme = session.exec(select(Scheme).where(
            Scheme.jobId == job.id, Scheme.index == job.selectedSchemeIndex)).first()
    if scheme is None:
        scheme = session.exec(select(Scheme).where(Scheme.jobId == job.id)
                              .order_by(Scheme.index)).first()
    if scheme is None:
        return []
    return _scheme_out(scheme).layers


# --------------------------------------------------------------------------- #
# 任务创建与查询
# --------------------------------------------------------------------------- #
@router.post("", response_model=JobOut)
def create_job(payload: JobCreate, session: Session = Depends(get_session)):
    """创建量化任务：拷贝模型到任务工作目录并异步入队阶段一。"""
    model = session.get(Model, payload.modelId)
    if model is None:
        raise HTTPException(status_code=400, detail="模型不存在")
    source = Path(model.filePath)
    if not model.filePath or not source.exists():
        raise HTTPException(status_code=400, detail="模型文件已丢失，请重新上传")

    running = session.exec(select(QuantizationJob).where(
        QuantizationJob.modelId == model.id)).all()
    for row in running:
        if row.status in RUNNING_STATUSES:
            raise HTTPException(status_code=409,
                                detail="该模型已有进行中的量化任务（%s）" % row.id)

    job = QuantizationJob(modelId=model.id, status="pending",
                          targetNPU=payload.targetNPU or model.targetNPU)
    session.add(job)
    session.commit()
    session.refresh(job)

    prepare_workspace(job, model)
    set_model_status(model.id, "processing")
    log_event(job.id, "任务已创建，排队等待算法执行", "info")
    scheduler.submit(lambda: run_first_phase(job.id))
    return _to_out(job, session)


@router.get("", response_model=List[JobOut])
def list_jobs(modelId: Optional[str] = Query(default=None),
              status: Optional[str] = Query(default=None),
              limit: int = Query(default=50, ge=1, le=500),
              session: Session = Depends(get_session)):
    statement = select(QuantizationJob)
    if modelId:
        statement = statement.where(QuantizationJob.modelId == modelId)
    if status:
        statement = statement.where(QuantizationJob.status == status)
    rows = session.exec(statement.order_by(
        QuantizationJob.createdAt.desc()).limit(limit)).all()
    return [_to_out(row, session) for row in rows]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: str, session: Session = Depends(get_session)):
    return _to_out(_get_or_404(session, job_id), session)


@router.get("/{job_id}/logs", response_model=List[JobLogOut])
def get_job_logs(job_id: str, limit: int = Query(default=200, ge=1, le=2000),
                 session: Session = Depends(get_session)):
    _get_or_404(session, job_id)
    rows = session.exec(select(JobLog).where(JobLog.jobId == job_id)
                        .order_by(JobLog.id.desc()).limit(limit)).all()
    rows = list(reversed(rows))
    return [JobLogOut(id=row.id, timestamp=row.timestamp, stage=row.stage,
                      percent=row.percent, message=row.message, level=row.level)
            for row in rows]


@router.get("/{job_id}/schemes", response_model=List[SchemeOut])
def list_schemes(job_id: str, session: Session = Depends(get_session)):
    """帕累托前沿：每个方案的层位宽、目标值、层明细与压缩率。"""
    _get_or_404(session, job_id)
    rows = session.exec(select(Scheme).where(Scheme.jobId == job_id)
                        .order_by(Scheme.index)).all()
    best = recommended_scheme_index(list(rows))
    return [_scheme_out(row, recommended=(row.index == best)) for row in rows]


@router.get("/{job_id}/layers", response_model=List[QuantizationLayerOut])
def job_layers(job_id: str, session: Session = Depends(get_session)):
    """量化完成后的层信息（前端"层信息"面板）。未选方案时返回首个方案。"""
    job = _get_or_404(session, job_id)
    return _selected_layers(job, session)


@router.get("/{job_id}/sensitivity", response_model=Dict[str, float])
def job_sensitivity(job_id: str, session: Session = Depends(get_session)):
    """HAWQ 敏感度结果 {层名: 敏感度}（可选展示）。"""
    job = _get_or_404(session, job_id)
    if not job.sensitivityFile or not Path(job.sensitivityFile).exists():
        raise HTTPException(status_code=404, detail="敏感度结果尚未生成")
    try:
        data = json.loads(Path(job.sensitivityFile).read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=500, detail="敏感度文件解析失败: %s" % exc)
    layers = data.get("layers", {}) if isinstance(data, dict) else {}
    return {str(key): float(value) for key, value in layers.items()}


# --------------------------------------------------------------------------- #
# 选方案 / 下载 / 取消 / 删除
# --------------------------------------------------------------------------- #
@router.post("/{job_id}/select", response_model=JobOut)
def select_scheme(job_id: str, payload: SelectSchemeIn,
                  session: Session = Depends(get_session)):
    """选定方案并启动阶段二；schemeIndex 省略时用推荐（膝点）方案。"""
    job = _get_or_404(session, job_id)
    if job.status != "scheme_ready":
        raise HTTPException(status_code=409,
                            detail="当前状态 %s 不可选择方案" % job.status)

    rows = session.exec(select(Scheme).where(Scheme.jobId == job_id)
                        .order_by(Scheme.index)).all()
    if not rows:
        raise HTTPException(status_code=400, detail="该任务还没有可用方案")

    index = payload.schemeIndex
    if index is None:
        index = recommended_scheme_index(list(rows))
    if not any(row.index == index for row in rows):
        raise HTTPException(status_code=400, detail="方案序号不存在: %s" % index)

    job.selectedSchemeIndex = index
    job.status = "quantizing"
    job.progress = 0
    job.message = "方案 #%s 已选定，开始量化" % index
    job.stage = "quantizing"
    job.updatedAt = now_iso()
    session.add(job)
    session.commit()
    session.refresh(job)

    scheduler.submit(lambda: run_second_phase(job.id, index))
    return _to_out(job, session)


@router.get("/{job_id}/om/download")
def download_om(job_id: str, session: Session = Depends(get_session)):
    job = _get_or_404(session, job_id)
    if job.status not in OM_READY_STATUSES or not job.omPath:
        raise HTTPException(status_code=404, detail=".om 尚未生成")
    path = Path(job.omPath)
    if not path.exists():
        raise HTTPException(status_code=404, detail=".om 文件已丢失")
    model = session.get(Model, job.modelId)
    stem = Path(model.name).stem if model else job.id
    return FileResponse(str(path), filename="%s_%s.om" % (stem, job.id[:8]),
                        media_type="application/octet-stream")


@router.post("/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, session: Session = Depends(get_session)):
    job = _get_or_404(session, job_id)
    if job.status not in CANCELABLE_STATUSES:
        raise HTTPException(status_code=409, detail="任务已结束，无需取消")
    scheduler.cancel(job_id)
    job.status = "failed"
    job.error = "任务已取消"
    job.message = "任务已取消"
    job.finishedAt = now_iso()
    job.updatedAt = now_iso()
    session.add(job)
    session.commit()
    set_model_status(job.modelId, "failed")
    log_event(job_id, "任务已取消", "warning")
    session.refresh(job)
    return _to_out(job, session)


@router.delete("/{job_id}", response_model=OkOut)
def delete_job(job_id: str, session: Session = Depends(get_session)):
    job = _get_or_404(session, job_id)
    if job.status in RUNNING_STATUSES:
        raise HTTPException(status_code=409, detail="任务进行中，请先取消再删除")
    for row in session.exec(select(Scheme).where(Scheme.jobId == job_id)).all():
        session.delete(row)
    for row in session.exec(select(JobLog).where(JobLog.jobId == job_id)).all():
        session.delete(row)
    for row in session.exec(select(Deployment).where(Deployment.jobId == job_id)).all():
        session.delete(row)
    workspace = job_dir(job_id)
    session.delete(job)
    session.commit()
    shutil.rmtree(str(workspace), ignore_errors=True)
    return OkOut(detail="任务已删除")
