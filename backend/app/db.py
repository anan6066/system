"""SQLite 引擎与会话。

注意：engine 在模块导入时按 config.db_path()（可被 QUANT_DEPLOY_DB 覆盖）创建，
因此测试环境的 conftest 必须在 import app.* 之前设置好环境变量。
"""
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import db_path

engine = create_engine(
    "sqlite:///" + db_path(),
    connect_args={"check_same_thread": False, "timeout": 30},
)


def init_db() -> None:
    """建表（幂等）。调用前需确保 app.models 已被导入，否则表不会注册。"""
    from . import models  # noqa: F401  确保所有表模型注册进 metadata

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
