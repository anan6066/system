"""API Key 鉴权。

默认**关闭**：`config.yaml` 的 `server.api_key` 留空、环境变量也没设时，
中间件直接放行 —— 本机开发不用管它。

对外部署**务必**打开，否则任何人只要能访问到端口，就能建设备、传模型、
删数据，甚至让你的服务器去 SSH 别人的机器。两种开启方式（环境变量优先）：

    export QUANT_DEPLOY_API_KEY='一串足够长的随机字符串'
    # 或写进 config.yaml:  server.api_key: "..."

前端在 web/.env.production 里配 VITE_API_KEY 为同一个值。
"""
import hmac
import os
from typing import Set

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .config import get

# 免鉴权路径：健康检查与契约速查（给探活用），以及接口文档
PUBLIC_PATHS: Set[str] = {"/api/health", "/api/meta"}
PUBLIC_PREFIXES = ("/docs", "/redoc", "/openapi.json")


def configured_key() -> str:
    """环境变量优先，其次 config.yaml；都为空 = 关闭鉴权。"""
    return (os.environ.get("QUANT_DEPLOY_API_KEY")
            or get("server.api_key")
            or "").strip()


def _extract_key(request: Request) -> str:
    """支持 X-API-Key 头，或 Authorization: Bearer <key>。"""
    value = request.headers.get("x-api-key")
    if value:
        return value.strip()
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return ""


class ApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        key = configured_key()
        if not key:
            return await call_next(request)

        # 预检请求（OPTIONS）不带自定义头，放行交给 CORS 中间件
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        # 单端口交付时挂在根路径的前端静态资源也不拦
        if not path.startswith("/api/"):
            return await call_next(request)

        provided = _extract_key(request)
        # 定长比较，避免按字符逐位试探
        if not provided or not hmac.compare_digest(provided, key):
            return JSONResponse(status_code=401,
                                content={"detail": "缺少或错误的 API Key"})
        return await call_next(request)
