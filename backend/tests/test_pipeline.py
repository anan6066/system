import json
from pathlib import Path

from sqlmodel import Session, select

from app.config import workspace_root
from app.db import engine
from app.layers import read_layers_json
from app.models import JobLog, Model, QuantizationJob, Scheme
from app.pipeline import job_dir, recommended_scheme_index, run_first_phase, run_second_phase
from tests.conftest import requires_atc


def _seed_model(preset=None, file_size=4096):
    from tests.helpers import default_upload_bytes

    source = workspace_root() / "uploads" / "t.onnx"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(default_upload_bytes())
    with Session(engine) as session:
        model = Model(name="t.onnx", filePath=str(source), fileSize=file_size,
                      preset=preset, baseAccuracy=70.0)
        session.add(model)
        session.commit()
        return model.id


def _seed_job(model_id, status="pending"):
    with Session(engine) as session:
        job = QuantizationJob(modelId=model_id, status=status)
        session.add(job)
        session.commit()
        return job.id


def test_first_phase_reaches_scheme_ready(client):
    model_id = _seed_model(preset="mobilenetv2")
    job_id = _seed_job(model_id)

    run_first_phase(job_id)

    with Session(engine) as session:
        job = session.get(QuantizationJob, job_id)
        assert job.status == "scheme_ready"
        assert job.progress == 100
        assert job.schemeCount == 6
        assert job.error is None
        assert job.sensitivityFile and job.sensitivityFile.endswith("sensitivity.json")
        assert job.schemesFile and job.schemesFile.endswith("schemes.json")

        schemes = session.exec(select(Scheme).where(Scheme.jobId == job_id)
                              .order_by(Scheme.index)).all()
        assert len(schemes) == 6
        layer_config = json.loads(schemes[0].layerConfig)
        assert set(layer_config) == {"conv1", "conv2_1", "conv2_2", "conv3_1",
                                     "conv3_2", "conv4_1", "conv4_2", "fc"}
        assert schemes[0].int8Layers + schemes[0].fp16Layers + schemes[0].fp32Layers == 8
        assert schemes[0].quantizedSizeKb < schemes[0].sizeKb
        assert 0 < schemes[0].compressionRatio < 1
        assert json.loads(schemes[0].metrics)["latencyMs"] > 0

        logs = session.exec(select(JobLog).where(JobLog.jobId == job_id)).all()
        assert any("帕累托前沿" in row.message for row in logs)

        model = session.get(Model, model_id)
        assert model.status == "processing"

    # 工作目录产物
    workdir = job_dir(job_id)
    for name in ("model.onnx", "layers.json", "sensitivity.json", "schemes.json"):
        assert (workdir / name).exists(), name

    layers = read_layers_json(workdir)
    assert [item["name"] for item in layers] == ["conv1", "conv2_1", "conv2_2", "conv3_1",
                                                 "conv3_2", "conv4_1", "conv4_2", "fc"]


@requires_atc
def test_second_phase_produces_om(client):
    model_id = _seed_model(preset="resnet18")
    job_id = _seed_job(model_id)
    run_first_phase(job_id)

    run_second_phase(job_id, 2)

    with Session(engine) as session:
        job = session.get(QuantizationJob, job_id)
        assert job.status == "om_ready"
        assert job.selectedSchemeIndex == 2
        assert job.omPath and Path(job.omPath).exists()
        assert job.quantizedFile and Path(job.quantizedFile).exists()
        assert job.progress == 100
        selected = session.exec(select(Scheme).where(
            Scheme.jobId == job_id, Scheme.index == 2)).first()
        assert selected.isSelected is True
        model = session.get(Model, model_id)
        assert model.status == "completed"


def test_phase_guards_prevent_rerun(client):
    model_id = _seed_model()
    job_id = _seed_job(model_id, status="nonexistent-state")

    run_first_phase(job_id)                       # 非 pending 态：拒绝启动
    with Session(engine) as session:
        assert session.get(QuantizationJob, job_id).status == "nonexistent-state"

    run_second_phase(job_id, 0)                   # 非 scheme_ready 态：拒绝启动
    with Session(engine) as session:
        assert session.get(QuantizationJob, job_id).status == "nonexistent-state"


def test_failure_marks_job_and_model(client, monkeypatch):
    from app import pipeline

    model_id = _seed_model()
    job_id = _seed_job(model_id)
    monkeypatch.setattr(pipeline, "algo_path",
                        lambda name: Path(workspace_root()) / "missing_script.py")

    run_first_phase(job_id)

    with Session(engine) as session:
        job = session.get(QuantizationJob, job_id)
        assert job.status == "failed"
        assert "不存在" in job.error
        assert session.get(Model, model_id).status == "failed"


def test_recommended_index(client):
    model_id = _seed_model()
    job_id = _seed_job(model_id)
    run_first_phase(job_id)
    with Session(engine) as session:
        schemes = session.exec(select(Scheme).where(Scheme.jobId == job_id)).all()
        index = recommended_scheme_index(list(schemes))
        assert index in [row.index for row in schemes]
