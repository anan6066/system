"""pytest 公共 fixture。

关键点：环境变量必须在任何 app.* 导入之前设置 —— conftest 的模块级代码
先于测试模块收集执行；单文件跑（pytest tests/test_x.py）也成立。

环境门控（真实算法落地后新增）：
  HAS_TOOLCHAIN  numpy/onnx/pymoo/onnxruntime 是否可导入。
                 Windows 的 tools/py38 没有这些，算法脚本用例会自动跳过，
                 流水线走脚本内置的降级路径。
  HAS_ATC        是否有昇腾 CANN（atc）。没有时真转换用例跳过。
  QUANT_E2E=1    才跑真实 torchvision 导出 + 真实 ATC 转换（慢，默认关）。
"""
import importlib
import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="quant_deploy_test_")
os.environ["QUANT_DEPLOY_DB"] = os.path.join(_TMP, "test.db")
os.environ["QUANT_DEPLOY_WORKSPACE"] = os.path.join(_TMP, "workspace")
# 预设 ONNX 缓存也指向临时目录，免得测试生成的 tiny 模型污染 backend/presets_cache
os.environ["QUANT_DEPLOY_PRESET_CACHE"] = os.path.join(_TMP, "presets_cache")

IDLE_TIMEOUT = 120.0
RUN_E2E = os.environ.get("QUANT_E2E") == "1"


def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
    except ImportError:
        return False
    return True


HAS_TOOLCHAIN = all(_importable(mod) for mod in ("numpy", "onnx", "pymoo", "onnxruntime"))
HAS_ATC = bool(shutil.which("atc")) or Path("/usr/local/Ascend").exists()

requires_toolchain = pytest.mark.skipif(
    not HAS_TOOLCHAIN, reason="需要 numpy/onnx/pymoo/onnxruntime")
requires_atc = pytest.mark.skipif(not HAS_ATC, reason="需要昇腾 CANN 工具链（atc）")


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "e2e: 需要 QUANT_E2E=1 的真实链路用例（torch 导出 / ATC 转换）")


def pytest_collection_modifyitems(config, items):
    if RUN_E2E:
        return
    skip = pytest.mark.skip(reason="需要 QUANT_E2E=1（真实 torch 导出 / ATC 转换）")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fast_presets(monkeypatch):
    """非 E2E 时把预设 ONNX 生成换成 tiny 模型。

    真导出 MobileNetV2 要 10~40s，而绝大多数用例只关心"流水线能不能跑通"，
    不关心模型是不是真的 MobileNetV2。E2E 档才走真实导出。
    """
    if RUN_E2E or not HAS_TOOLCHAIN:
        yield False
        return

    from app import presets as presets_mod
    from tests.fixtures import build_tiny_onnx

    payload = build_tiny_onnx()
    monkeypatch.setattr(presets_mod, "generate_preset_onnx", lambda preset_id: payload)
    monkeypatch.setattr(presets_mod, "generate_surrogate_onnx", lambda preset_id: payload)
    monkeypatch.setattr(presets_mod, "_download_yolov8", lambda: payload)
    yield True


@pytest.fixture(autouse=True)
def reset_db():
    """每个用例前：等后台任务排空 → 重建表 → 清空设备指标缓存。"""
    from sqlmodel import SQLModel

    import app.models  # noqa: F401  确保建表前所有表模型已注册
    from app.db import engine
    from app.routers import devices as devices_router
    from app.scheduler import scheduler

    scheduler.wait_idle(IDLE_TIMEOUT)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with devices_router._history_lock:
        devices_router._history.clear()
    yield
    scheduler.wait_idle(IDLE_TIMEOUT)


@pytest.fixture()
def db_session():
    """直接操作数据库的测试用 session。"""
    from sqlmodel import Session

    from app.db import engine

    with Session(engine) as session:
        yield session
