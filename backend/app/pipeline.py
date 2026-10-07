"""量化流水线编排（两阶段，scheme_ready 处挂起等用户选方案）。

阶段一：① HAWQ 敏感度分析 → ② NSGA-II 方案搜索 → 状态置 scheme_ready 并落库帕累托前沿
阶段二：用户选方案后 → ④ AMCT 量化 → ⑤ ATC 转 .om → 状态置 om_ready

所有进度都通过 JobLog + QuantizationJob(status/progress/message) 落库，
前端只需轮询 GET /api/quantization/jobs/{id}。
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select
from sqlalchemy import update

from . import layers as layers_mod
from .config import algo_path, get as config_get, workspace_root
from .db import engine
from .executor import run_script
from .models import JobLog, Model, QuantizationJob, Scheme, now_iso
from .scheduler import scheduler

# 终态：进入后不再接受进度覆盖
TERMINAL_STATUSES = ("failed", "canceled")
RUNNING_STATUSES = ("pending", "sensitivity_analysis", "scheme_search",
                    "quantizing", "converting", "deploying")


def job_dir(job_id: str) -> Path:
    path = workspace_root() / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def algo_env(name: str) -> Dict[str, str]:
    """按脚本注入配置。

    算法脚本的 cwd 是任务工作目录而不是仓库根，读不到 config.yaml，所以
    配置得从这里透传。只给真正需要的脚本注入，保持其它脚本"不读配置"的契约。
    """
    if name == "amct_script":
        samples = config_get("algorithms.calibration_samples", 32) or 32
        return {"CALIBRATION_SAMPLES": str(samples)}
    if name == "atc_script":
        soc = config_get("algorithms.soc_version", "Ascend310B4") or "Ascend310B4"
        return {"SOC_VERSION": str(soc)}
    return {}


# --------------------------------------------------------------------------- #
# 落库工具
# --------------------------------------------------------------------------- #
def update_job(job_id: str, **fields: Any) -> None:
    try:
        with Session(engine) as session:
            job = session.get(QuantizationJob, job_id)
            if job is None:
                return
            for key, value in fields.items():
                setattr(job, key, value)
            job.updatedAt = now_iso()
            session.add(job)
            session.commit()
    except Exception:  # noqa: BLE001
        # 进度落库属于"尽力而为"的记账，绝不能让它把编排线程打挂
        pass


def update_job_if_active(job_id: str, **fields: Any) -> bool:
    """进度写库：任务进入终态（failed/canceled）后不再被覆盖。

    用一条带 WHERE 的原子 UPDATE（而不是"读-改-写"ORM 对象），
    否则取消请求与进度回调并发时，回调会把 failed 覆盖回运行态。
    """
    try:
        with Session(engine) as session:
            statement = (
                update(QuantizationJob)
                .where(QuantizationJob.id == job_id,
                       ~QuantizationJob.status.in_(TERMINAL_STATUSES))
                .values(updatedAt=now_iso(), **fields)
            )
            result = session.execute(statement)
            session.commit()
            return bool(result.rowcount)
    except Exception:  # noqa: BLE001
        return False


def set_model_status(model_id: Optional[str], status: str) -> None:
    if not model_id:
        return
    with Session(engine) as session:
        model = session.get(Model, model_id)
        if model is None:
            return
        model.status = status
        model.updatedAt = now_iso()
        session.add(model)
        session.commit()


def log_event(job_id: str, message: str, level: str = "info",
              stage: str = "", percent: Optional[int] = None) -> None:
    try:
        with Session(engine) as session:
            if percent is None:
                job = session.get(QuantizationJob, job_id)
                percent = job.progress if job else 0
            session.add(JobLog(jobId=job_id, stage=stage or "", percent=int(percent or 0),
                               message=message, level=level, timestamp=now_iso()))
            session.commit()
    except Exception:  # noqa: BLE001 —— 同 update_job：日志失败不影响任务
        pass


def _progress_callback(job_id: str):
    def callback(stage: str, percent: int, message: str) -> None:
        try:
            if scheduler.is_canceled(job_id):
                return
            if not update_job_if_active(job_id, status=stage or "pending",
                                        stage=stage, progress=int(percent),
                                        message=message):
                return
            log_event(job_id, message, "info", stage=stage, percent=percent)
        except Exception:  # noqa: BLE001
            pass

    return callback


def _fail(job_id: str, tail: str) -> None:
    try:
        canceled = scheduler.is_canceled(job_id)
        error = "任务已取消" if canceled else (tail or "算法脚本执行失败")
        update_job(job_id, status="failed", error=error[:2000],
                   message=error.splitlines()[-1][:200] if error else "任务失败",
                   finishedAt=now_iso())
        with Session(engine) as session:
            job = session.get(QuantizationJob, job_id)
            model_id = job.modelId if job else None
        set_model_status(model_id, "failed")
        log_event(job_id, error[:500], "error", percent=None)
    except Exception:  # noqa: BLE001 —— 失败处理本身也不能抛出去
        pass


# --------------------------------------------------------------------------- #
# 工作目录准备
# --------------------------------------------------------------------------- #
def prepare_workspace(job: QuantizationJob, model: Model) -> Path:
    """创建任务工作目录：拷入 model.onnx，并写出 layers.json 供算法脚本使用。"""
    workdir = job_dir(job.id)
    source = Path(model.filePath) if model.filePath else None
    target = workdir / "model.onnx"
    if source is not None and source.exists():
        target.write_bytes(source.read_bytes())
    elif not target.exists():
        target.write_bytes(b"PLACEHOLDER-ONNX")
    layer_list = layers_mod.model_layers(model)
    layers_mod.write_layers_json(workdir, layer_list)
    return workdir


# --------------------------------------------------------------------------- #
# 阶段一
# --------------------------------------------------------------------------- #
def run_first_phase(job_id: str) -> None:
    cancel = scheduler.new_cancel_event(job_id)
    try:
        with Session(engine) as session:
            job = session.get(QuantizationJob, job_id)
            if job is None:
                return
            if job.status not in ("pending",):
                # 防重入：只有 pending 态才允许启动阶段一
                return
            model = session.get(Model, job.modelId)
            if model is None:
                _fail(job_id, "模型不存在")
                return
            workdir = prepare_workspace(job, model)
            set_model_status(model.id, "processing")

        if not update_job_if_active(job_id, status="sensitivity_analysis", progress=0,
                                    message="开始 HAWQ 敏感度分析", stage="sensitivity_analysis",
                                    startedAt=now_iso(), error=None):
            return                      # 已被取消/删除，不再继续
        log_event(job_id, "开始量化任务：① HAWQ 敏感度分析", "info",
                  stage="sensitivity_analysis", percent=0)

        code, tail = run_script(algo_path("hawq_script"), workdir,
                                _progress_callback(job_id), cancel,
                                extra_env=algo_env("hawq_script"))
        if code != 0:
            return _fail(job_id, tail)

        sensitivity_file = workdir / "sensitivity.json"
        if not sensitivity_file.exists():
            return _fail(job_id, "敏感度分析未产出 sensitivity.json")
        update_job_if_active(job_id, sensitivityFile=str(sensitivity_file),
                             status="scheme_search", progress=0,
                             message="开始 NSGA-II 位宽方案搜索", stage="scheme_search")
        log_event(job_id, "① 完成，进入 ② NSGA-II 位宽方案搜索", "info",
                  stage="scheme_search", percent=0)

        code, tail = run_script(algo_path("nsga2_script"), workdir,
                                _progress_callback(job_id), cancel,
                                extra_env=algo_env("nsga2_script"))
        if code != 0:
            return _fail(job_id, tail)

        schemes_file = workdir / "schemes.json"
        if not schemes_file.exists():
            return _fail(job_id, "方案搜索未产出 schemes.json")
        with open(str(schemes_file), encoding="utf-8") as handle:
            schemes = json.load(handle)
        if not isinstance(schemes, list) or not schemes:
            return _fail(job_id, "schemes.json 内容为空")

        _persist_schemes(job_id, schemes)
        if not update_job_if_active(job_id, schemesFile=str(schemes_file),
                                    status="scheme_ready", progress=100,
                                    schemeCount=len(schemes),
                                    message="已生成 %d 个帕累托方案，请选择" % len(schemes),
                                    stage="scheme_ready"):
            return                      # 期间被取消：保持 failed，不复活任务
        log_event(job_id, "② 完成，帕累托前沿已生成（%d 个方案），等待选择"
                  % len(schemes), "success", stage="scheme_ready", percent=100)
    except Exception as exc:  # noqa: BLE001 —— 流水线内任何异常都转为任务失败
        _fail(job_id, "流水线异常: %s" % exc)
    finally:
        scheduler.release(job_id)


def _persist_schemes(job_id: str, schemes: List[Dict[str, Any]]) -> None:
    workdir = job_dir(job_id)
    all_layers = layers_mod.read_layers_json(workdir)
    with Session(engine) as session:
        for row in session.exec(select(Scheme).where(Scheme.jobId == job_id)).all():
            session.delete(row)
        session.commit()

        for item in schemes:
            layer_config = item.get("layer_config", {}) or {}
            layer_view = item.get("layers")
            if not isinstance(layer_view, list) or not layer_view:
                layer_view = layers_mod.scheme_layer_view(all_layers, layer_config)
            summary = item.get("stats") if isinstance(item.get("stats"), dict) else None
            if not summary:
                summary = layers_mod.scheme_summary(layer_view)
            metrics = item.get("metrics") if isinstance(item.get("metrics"), dict) else {}
            session.add(Scheme(
                jobId=job_id,
                index=int(item.get("index", 0)),
                layerConfig=json.dumps(layer_config, ensure_ascii=False),
                objectives=json.dumps(item.get("objectives", {}), ensure_ascii=False),
                metrics=json.dumps(metrics, ensure_ascii=False),
                layersJson=json.dumps(layer_view, ensure_ascii=False),
                sizeKb=float(summary.get("originalSizeKb", 0) or 0),
                quantizedSizeKb=float(summary.get("quantizedSizeKb", 0) or 0),
                compressionRatio=float(summary.get("compressionRatio", 0) or 0),
                int8Layers=int(summary.get("int8Layers", 0) or 0),
                fp16Layers=int(summary.get("fp16Layers", 0) or 0),
                fp32Layers=int(summary.get("fp32Layers", 0) or 0),
            ))
        session.commit()


# --------------------------------------------------------------------------- #
# 阶段二
# --------------------------------------------------------------------------- #
def run_second_phase(job_id: str, scheme_index: int) -> None:
    cancel = scheduler.new_cancel_event(job_id)
    try:
        with Session(engine) as session:
            job = session.get(QuantizationJob, job_id)
            if job is None or job.status not in ("scheme_ready", "quantizing"):
                # 状态守卫：只有"方案已就绪"（或选方案接口刚置为 quantizing）才允许启动阶段二
                return
            scheme = session.exec(select(Scheme).where(
                Scheme.jobId == job_id, Scheme.index == scheme_index)).first()
            if scheme is None:
                _fail(job_id, "方案序号 %s 不存在" % scheme_index)
                return
            model = session.get(Model, job.modelId)
            workdir = job_dir(job_id)
            selected = {
                "index": scheme_index,
                "layer_config": json.loads(scheme.layerConfig or "{}"),
                "objectives": json.loads(scheme.objectives or "{}"),
                "metrics": json.loads(scheme.metrics or "{}"),
            }

        (workdir / "selected_scheme.json").write_text(
            json.dumps(selected, ensure_ascii=False, indent=2), encoding="utf-8")

        update_job(job_id, selectedSchemeIndex=scheme_index, status="quantizing",
                   progress=0, message="开始 AMCT 量化", stage="quantizing")
        log_event(job_id, "已选定方案 #%d，开始 ④ AMCT 量化" % scheme_index, "info",
                  stage="quantizing", percent=0)
        if model is not None:
            set_model_status(model.id, "processing")

        code, tail = run_script(algo_path("amct_script"), workdir,
                                _progress_callback(job_id), cancel,
                                extra_env=algo_env("amct_script"))
        if code != 0:
            return _fail(job_id, tail)

        update_job_if_active(job_id, status="converting", progress=0,
                             message="开始 ATC 转换 .om", stage="converting")
        log_event(job_id, "④ 完成，进入 ⑤ ATC 转换 .om", "info",
                  stage="converting", percent=0)
        code, tail = run_script(algo_path("atc_script"), workdir,
                                _progress_callback(job_id), cancel,
                                extra_env=algo_env("atc_script"))
        if code != 0:
            return _fail(job_id, tail)

        om_path = workdir / "model.om"
        if not om_path.exists():
            return _fail(job_id, "ATC 未产出 model.om")
        quantized = workdir / "quantized.onnx"

        with Session(engine) as session:
            scheme = session.exec(select(Scheme).where(
                Scheme.jobId == job_id, Scheme.index == scheme_index)).first()
            if scheme is not None:
                scheme.isSelected = True
                session.add(scheme)
            for row in session.exec(select(Scheme).where(Scheme.jobId == job_id)).all():
                if row.index != scheme_index and row.isSelected:
                    row.isSelected = False
                    session.add(row)
            session.commit()

        if not update_job_if_active(job_id, status="om_ready", progress=100,
                                    stage="om_ready",
                                    message=".om 已生成，可下载或部署",
                                    omPath=str(om_path),
                                    quantizedFile=str(quantized) if quantized.exists() else None,
                                    finishedAt=now_iso()):
            return                      # 期间被取消：不把任务复活成 om_ready
        log_event(job_id, "⑤ 完成，.om 已生成，可下载或一键部署", "success",
                  stage="om_ready", percent=100)
        if model is not None:
            set_model_status(model.id, "completed")
    except Exception as exc:  # noqa: BLE001
        _fail(job_id, "流水线异常: %s" % exc)
    finally:
        scheduler.release(job_id)


# --------------------------------------------------------------------------- #
# 方案推荐（前端未指定方案时的默认选择）
# --------------------------------------------------------------------------- #
def recommended_scheme_index(schemes: List[Scheme]) -> Optional[int]:
    """帕累托前沿的膝点：归一化 (体积, 精度损失) 平面上离首尾连线最远的点。

    前端 "使用推荐方案" 用它；数据退化（只有 1~2 个方案、体积或损失完全相同）时，
    回退到精度损失最小的方案。
    """
    if not schemes:
        return None
    rows = []
    for row in schemes:
        try:
            objectives = json.loads(row.objectives or "{}")
        except ValueError:
            objectives = {}
        try:
            size = float(objectives.get("size", 0) or 0)
        except (TypeError, ValueError):
            size = 0.0
        try:
            loss = float(objectives.get("accuracy_loss", 0) or 0)
        except (TypeError, ValueError):
            loss = 0.0
        rows.append((row.index, size, loss))

    if len(rows) < 3:
        return min(rows, key=lambda item: item[2])[0]

    sizes = [item[1] for item in rows]
    losses = [item[2] for item in rows]
    size_low, size_high = min(sizes), max(sizes)
    loss_low, loss_high = min(losses), max(losses)
    if size_high - size_low <= 1e-9 or loss_high - loss_low <= 1e-9:
        return min(rows, key=lambda item: item[2])[0]

    points = [((size - size_low) / (size_high - size_low),
               (loss - loss_low) / (loss_high - loss_low), index)
              for index, size, loss in rows]
    points.sort()
    ax, ay, _ = points[0]
    bx, by, _ = points[-1]
    denominator = ((by - ay) ** 2 + (bx - ax) ** 2) ** 0.5 or 1.0

    best_index = points[0][2]
    best_distance = -1.0
    for x, y, index in points:
        distance = abs((by - ay) * x - (bx - ax) * y + bx * ay - by * ax) / denominator
        if distance > best_distance:
            best_distance = distance
            best_index = index
    return best_index
