"""配置加载：config.yaml + 环境变量覆盖。

环境变量：
    QUANT_DEPLOY_CONFIG     覆盖 config.yaml 路径
    QUANT_DEPLOY_WORKSPACE  覆盖 workspace_dir（测试用）
    QUANT_DEPLOY_DB         覆盖 db_path（测试用）
"""
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent


def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    cfg_path = Path(path or os.environ.get("QUANT_DEPLOY_CONFIG", str(BASE_DIR / "config.yaml")))
    with open(cfg_path, encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


CONFIG: Dict[str, Any] = load_config()


def get(dotted: str, default: Any = None) -> Any:
    """按 'scheduler.max_concurrent_jobs' 形式取配置，缺失返回 default。"""
    node: Any = CONFIG
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def workspace_root() -> Path:
    """任务工作目录根，可用环境变量 QUANT_DEPLOY_WORKSPACE 覆盖（测试用）。"""
    root = Path(os.environ.get("QUANT_DEPLOY_WORKSPACE")
                or str(BASE_DIR / CONFIG.get("workspace_dir", "workspace")))
    root.mkdir(parents=True, exist_ok=True)
    return root


def uploads_dir() -> Path:
    """上传模型存放目录。"""
    path = workspace_root() / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def algo_path(name: str) -> Path:
    """算法脚本绝对路径，name 为 config.yaml 中 algorithms 下的键。"""
    raw = CONFIG["algorithms"][name]
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def db_path() -> str:
    """SQLite 路径，可用环境变量 QUANT_DEPLOY_DB 覆盖（测试用）。"""
    return os.environ.get("QUANT_DEPLOY_DB") or str(BASE_DIR / CONFIG.get("db_path", "app.db"))
