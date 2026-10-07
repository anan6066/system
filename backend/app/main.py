"""FastAPI 入口：路由挂载 + CORS + 建表 + 契约元信息。

启动（服务器）：
    ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
前端联调：
    vite.config.ts 里把 /api 代理到 http://localhost:8000（或直接跨域，见 config.server.cors_origins）
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import __version__
from .auth import ApiKeyMiddleware
from .config import BASE_DIR, get
from .db import init_db
from .models import now_iso
from .routers import comparison, deployments, devices, jobs
from .routers import models as models_router
from .routers import stats

# 导入即建表（幂等）：避免 TestClient/uvicorn 未走 lifespan 时表缺失
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="智能模型量化部署一体化平台", version=__version__, lifespan=lifespan)

# 注意顺序：后 add 的在外层。先加鉴权、后加 CORS，
# 这样 CORS 在最外层，浏览器预检（OPTIONS）才不会被鉴权拦掉。
app.add_middleware(ApiKeyMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get("server.cors_origins", ["*"]) or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

app.include_router(devices.router)
app.include_router(models_router.router)
app.include_router(jobs.router)
app.include_router(deployments.router)
app.include_router(stats.router)
app.include_router(comparison.router)


@app.get("/api/health", tags=["meta"])
def health() -> Dict[str, str]:
    return {"status": "ok", "version": __version__, "time": now_iso()}


@app.get("/api/meta", tags=["meta"])
def meta() -> Dict[str, Any]:
    """联调用的契约速查：状态机枚举、设备状态、错误格式、约定。"""
    return {
        "version": __version__,
        "time": now_iso(),
        "conventions": {
            "fieldCase": "camelCase（与前端 types 一致）",
            "idFormat": "32 位 hex 字符串（Scheme/JobLog 为自增整数）",
            "timeFormat": "ISO8601 UTC，带 Z 后缀，可直接 new Date()",
            "errorFormat": {"detail": "错误说明"},
            "progressPolling": "GET /api/quantization/jobs/{id}（建议 1~2s 一次）",
        },
        "deviceStatus": ["online", "offline", "busy"],
        "modelStatus": ["idle", "processing", "completed", "failed"],
        "jobStatus": ["pending", "sensitivity_analysis", "scheme_search", "scheme_ready",
                      "quantizing", "converting", "om_ready", "deploying", "deployed",
                      "failed"],
        "jobTerminalStatus": ["om_ready", "deployed", "failed"],
        "deploymentStatus": ["pending", "deploying", "success", "failed"],
        "logType": ["info", "success", "warning", "error"],
        "bitWidths": ["INT8", "FP16", "FP32"],
        "npuType": {"default": "ascend", "accepted": ["ascend", "kirin", "rockchip", "other"]},
        "metricsSource": ["measured", "estimated"],
    }


def _mount_frontend() -> None:
    """可选：把已构建的前端（web/dist）挂在根路径，实现单 URL 交付。"""
    from fastapi.staticfiles import StaticFiles

    candidates: List[Path] = []
    env_dir = os.environ.get("QUANT_DEPLOY_STATIC_DIR")
    if env_dir:
        candidates.append(Path(env_dir))
    candidates.append(BASE_DIR.parent / "web" / "dist")
    for candidate in candidates:
        if candidate.is_dir() and (candidate / "index.html").exists():
            app.mount("/", StaticFiles(directory=str(candidate), html=True), name="frontend")
            return


_mount_frontend()


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):  # pragma: no cover - 兜底日志
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误: %s" % exc})
