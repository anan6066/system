from app.models import Device, Model, QuantizationJob


def test_tables_created(client):
    from sqlmodel import SQLModel

    from app.db import engine
    from app import models  # noqa: F401

    assert {"device", "model", "quantizationjob", "scheme", "joblog",
            "deployment"} <= set(SQLModel.metadata.tables.keys())
    del engine


def test_insert_device(db_session):
    device = Device(name="测试板", ip="192.168.1.10", username="root")
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    assert device.id and len(device.id) == 32
    assert device.status == "offline"
    assert device.createdAt.endswith("Z")
    assert device.cpuUsage == 0.0


def test_job_and_model_roundtrip(db_session):
    model = Model(name="m.onnx", filePath="/tmp/m.onnx", fileSize=10, status="idle")
    db_session.add(model)
    db_session.commit()
    job = QuantizationJob(modelId=model.id)
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    assert job.status == "pending"
    assert job.progress == 0
    assert job.schemeCount == 0
