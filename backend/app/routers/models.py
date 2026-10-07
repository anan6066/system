"""模型路由：ONNX 上传/下载/删除 + 预设模型 + 层信息。

对应前端 QuantizationPage：
* 上传自定义 ONNX        -> POST   /api/models (multipart, 字段名 file)
* 预设模型下拉            -> GET    /api/models/presets
* 选中预设后创建模型记录  -> POST   /api/models/preset
* 层配置预览 / 已量化层   -> GET    /api/models/{id}/layers
* 下载量化后模型(.om)     -> 见 jobs 路由 /api/quantization/jobs/{id}/om/download
"""
import json
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select

from .. import layers as layers_mod
from .. import presets as presets_mod
from ..config import CONFIG, uploads_dir
from ..db import get_session
from ..models import Deployment, JobLog, Model, QuantizationJob, Scheme, now_iso
from ..schemas import (ModelFromPresetIn, ModelOut, OkOut, PresetModelOut,
                       QuantizationLayerOut)

router = APIRouter(prefix="/api/models", tags=["models"])


def _to_out(model: Model, session: Session,
            quantization_layers: Optional[List[QuantizationLayerOut]] = None) -> ModelOut:
    latest_job = session.exec(
        select(QuantizationJob).where(QuantizationJob.modelId == model.id)
        .order_by(QuantizationJob.createdAt.desc())).first()
    if quantization_layers is None:
        quantization_layers = _resolution_layers(model, session, latest_job)
    return ModelOut(
        id=model.id, name=model.name, type=model.type, preset=model.preset,
        fileSize=model.fileSize, targetNPU=model.targetNPU, status=model.status,
        baseAccuracy=model.baseAccuracy, layerCount=model.layerCount,
        quantizationLayers=quantization_layers,
        latestJobId=latest_job.id if latest_job else None,
        createdAt=model.createdAt, updatedAt=model.updatedAt,
    )


def _resolution_layers(model: Model, session: Session,
                       latest_job: Optional[QuantizationJob]) -> List[QuantizationLayerOut]:
    """已量化模型返回选定方案的真实层位宽；未量化时返回全 FP32 的层结构。"""
    if latest_job is not None:
        scheme = None
        if latest_job.selectedSchemeIndex is not None:
            scheme = session.exec(select(Scheme).where(
                Scheme.jobId == latest_job.id,
                Scheme.index == latest_job.selectedSchemeIndex)).first()
        if scheme is None:
            scheme = session.exec(select(Scheme).where(Scheme.jobId == latest_job.id)
                                  .order_by(Scheme.index)).first()
        if scheme is not None and scheme.layersJson:
            try:
                rows = json.loads(scheme.layersJson)
            except ValueError:
                rows = []
            if rows:
                return [QuantizationLayerOut(**row) for row in rows]

    template = layers_mod.model_layers(model)
    return [QuantizationLayerOut(name=item["name"], type="FP32",
                                 originalSize=int(item.get("sizeKb", 0)),
                                 quantizedSize=int(item.get("sizeKb", 0)))
            for item in template]


@router.get("", response_model=List[ModelOut])
def list_models(session: Session = Depends(get_session)):
    models = session.exec(select(Model).order_by(Model.createdAt.desc())).all()
    return [_to_out(model, session) for model in models]


@router.post("", response_model=ModelOut)
async def upload_model(
    file: UploadFile = File(...),
    targetNPU: str = Form("ascend"),
    baseAccuracy: float = Form(72.0),
    session: Session = Depends(get_session),
):
    """上传 ONNX 模型（前端 QuantizationPage 的"自定义上传"）。"""
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".onnx"):
        raise HTTPException(status_code=400, detail="仅支持 .onnx 模型文件")

    max_mb = float(CONFIG.get("max_upload_mb", 500) or 500)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail="模型超过 %sMB 限制" % max_mb)

    # 装了 onnx 就顺手验一下，让非法文件在入口就被拦下，
    # 而不是拖到量化阶段才以"敏感度分析失败"的面目出现。
    # （Windows 的 tools/py38 没有 onnx，静默跳过校验）
    try:
        import io

        import onnx
    except ImportError:
        onnx = None
    if onnx is not None:
        try:
            onnx.checker.check_model(onnx.load(io.BytesIO(content),
                                               load_external_data=False))
        except Exception:  # noqa: BLE001 - 任何解析/校验失败都算非法
            raise HTTPException(status_code=400, detail="不是合法的 ONNX 模型文件")

    stored = uploads_dir() / ("%s.onnx" % uuid4().hex)
    stored.write_bytes(content)

    stamp = now_iso()
    model = Model(
        name=filename, type="custom", preset=None, filePath=str(stored),
        fileSize=len(content), targetNPU=(targetNPU or "ascend").lower(),
        status="idle", baseAccuracy=float(baseAccuracy or 72.0),
        createdAt=stamp, updatedAt=stamp,
    )
    model.layerCount = len(layers_mod.model_layers(model))
    session.add(model)
    session.commit()
    session.refresh(model)
    return _to_out(model, session)


@router.get("/presets", response_model=List[PresetModelOut])
def list_presets():
    """预设模型列表（前端下拉直接用）。"""
    return [PresetModelOut(**item) for item in presets_mod.list_presets()]


@router.post("/preset", response_model=ModelOut)
def create_from_preset(payload: ModelFromPresetIn, session: Session = Depends(get_session)):
    """把预设模型实例化成一条模型记录，之后可正常走量化流水线。

    模型文件按三级取用（缓存 → torch 导出/下载 → 结构替身），都不行时
    退回占位字节，保证 Windows 演示链路仍能建出模型记录。
    fileSize 记实际字节数（真实模型可达十几 MB），前端的"名义体积"展示
    仍走 presets 列表里的 size 字段。
    """
    preset = presets_mod.get_preset(payload.preset)
    if preset is None:
        raise HTTPException(status_code=400, detail="预设模型不存在: %s" % payload.preset)

    data, _origin = presets_mod.preset_onnx_bytes(preset["id"])
    if data is None:
        data = ("PLACEHOLDER-ONNX:%s:%d\n" % (preset["id"], preset["fileSize"])).encode("utf-8")

    stored = uploads_dir() / ("%s.onnx" % uuid4().hex)
    stored.write_bytes(data)

    stamp = now_iso()
    model = Model(
        name=payload.name or preset["name"], type="preset", preset=preset["id"],
        filePath=str(stored), fileSize=len(data),
        targetNPU=(payload.targetNPU or presets_mod.TARGET_NPU).lower(),
        status="idle", baseAccuracy=float(preset["baseAccuracy"]),
        layerCount=len(preset["layers"]), createdAt=stamp, updatedAt=stamp,
    )
    session.add(model)
    session.commit()
    session.refresh(model)
    return _to_out(model, session)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: str, session: Session = Depends(get_session)):
    model = session.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    return _to_out(model, session)


@router.get("/{model_id}/layers", response_model=List[QuantizationLayerOut])
def model_layers(model_id: str, session: Session = Depends(get_session)):
    model = session.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    return _to_out(model, session).quantizationLayers


@router.get("/{model_id}/download")
def download_model(model_id: str, session: Session = Depends(get_session)):
    model = session.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    path = Path(model.filePath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="模型文件已丢失，请重新上传")
    return FileResponse(str(path), filename=model.name,
                        media_type="application/octet-stream")


@router.delete("/{model_id}", response_model=OkOut)
def delete_model(model_id: str, session: Session = Depends(get_session)):
    """删除模型：连同其量化任务/方案/日志/部署记录一起清理，避免悬挂外键。"""
    model = session.get(Model, model_id)
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    job_ids = [row.id for row in session.exec(
        select(QuantizationJob).where(QuantizationJob.modelId == model_id)).all()]
    for job_id in job_ids:
        for scheme in session.exec(select(Scheme).where(Scheme.jobId == job_id)).all():
            session.delete(scheme)
        for log in session.exec(select(JobLog).where(JobLog.jobId == job_id)).all():
            session.delete(log)
        for dep in session.exec(select(Deployment).where(Deployment.jobId == job_id)).all():
            session.delete(dep)
    for job in session.exec(select(QuantizationJob).where(
            QuantizationJob.modelId == model_id)).all():
        session.delete(job)

    path = Path(model.filePath)
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    session.delete(model)
    session.commit()
    return OkOut(detail="模型及其量化任务已删除")
