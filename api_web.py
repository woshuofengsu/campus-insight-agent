# api_web.py — 前后端分离 Web API（Vue3 前端用）
"""社区先知 CommunityInsight — FastAPI + Vue3 前端专用后端。

与 api.py（扣子插件用，API-key 鉴权）独立运行：
  uvicorn api_web:app --host 0.0.0.0 --port 8000

特点：
  - JWT 用户鉴权（stdlib HMAC-SHA256 实现 HS256，零第三方依赖）
  - /api/web/* 端点复用现有 data/ 层函数与 SQLite schema（零数据层改动）
  - 统一响应 {success, data, error, code, message}
  - 单进程同时服务 API + Vue3 构建产物（dist/）

P2-04 / P1-F2-01（api_web 单体拆分）：业务端点已全部迁入 api_routes/ 包，
本文件仅保留：App 装配 + JWT 鉴权中间件 + 健康检查 + 路由挂载 + SPA 托管。
"""
import logging
import os
import sys

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_log = logging.getLogger(__name__)

# ---------------- JWT（stdlib HMAC HS256） ----------------
# 已随路由拆分（P2-04 / P1-F2-01）移入 api_routes/deps.py，此处仅向后兼容引用。

from api_routes.deps import make_token, verify_token  # noqa: F401  (供本模块端点/中间件使用)


# ---------------- 统一响应 ----------------

def ok(data=None, message="ok") -> dict:
    return {"success": True, "data": data, "error": None, "code": 0, "message": message}


def fail(code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={
        "success": False, "data": None, "error": message, "code": code, "message": message,
    })


# ---------------- App ----------------

app = FastAPI(title="CommunityInsight Web API", version="3.0.0",
              docs_url="/web/docs", redoc_url="/web/redoc", openapi_url="/web/openapi.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_db_ready = False


def _ensure_db():
    global _db_ready
    if _db_ready:
        return
    from config import DB_PATH
    from data.db_core import init_db
    from data.seed import seed_all
    init_db(DB_PATH)
    seed_all(DB_PATH)
    _db_ready = True


_scheduler_started = False


def _ensure_scheduler():
    """启动后台调度器（守护线程）：定时发布/超时升级/自动分派/预警检测/到期清理等
    A 类自动任务（spec 九）。幂等：进程内只启动一次。"""
    global _scheduler_started
    if _scheduler_started:
        return
    try:
        from scripts.scheduler import ensure_scheduler_started
        ensure_scheduler_started(interval=60)
        _scheduler_started = True
        _log.info("Web 服务调度器已启动（自动任务每 60 秒轮询）")
    except Exception as e:  # noqa: BLE001
        _log.warning("调度器启动失败（不影响 API）：%s", e)


from contextlib import asynccontextmanager


@asynccontextmanager
async def _lifespan(app):
    _ensure_db()
    _ensure_scheduler()
    yield


app = FastAPI(title="CommunityInsight Web API", version="3.0.0",
              docs_url="/web/docs", redoc_url="/web/redoc", openapi_url="/web/openapi.json",
              lifespan=_lifespan)


# 公开路径：登录 + 健康检查 + 文档 + 前端静态
_PUBLIC_PATHS = {"/api/web/auth/login", "/api/web/auth/demo", "/api/web/health",
                 "/web/docs", "/web/redoc", "/web/openapi.json",
                 "/", "/index.html", "/favicon.ico"}


@app.middleware("http")
async def _web_auth_middleware(request: Request, call_next):
    """JWT 鉴权：/api/web/* 除公开路径外必须带 Bearer token。"""
    _ensure_db()
    path = request.url.path
    if not path.startswith("/api/web/") or path in _PUBLIC_PATHS or path.startswith("/web/"):
        return await call_next(request)
    auth = request.headers.get("Authorization", "")
    payload = None
    if auth.startswith("Bearer "):
        payload = verify_token(auth[7:])
    if payload is None:
        return JSONResponse(status_code=401, content={
            "success": False, "data": None, "error": "未登录或登录已过期", "code": 1002, "message": "未登录",
        })
    request.state.user = payload
    return await call_next(request)


def _user(request: Request) -> dict:
    return getattr(request.state, "user", {})


def _require_role(request: Request, role: str):
    u = _user(request)
    if u.get("role") != role:
        return fail(1003, "无权限")
    return None


# ---------------- 系统 ----------------

@app.get("/api/web/health")
def web_health():
    """健康检查（Docker HEALTHCHECK 用）。"""
    return ok({"service": "CommunityInsight Web", "status": "ok"})


# ---------------- 路由模块挂载（P2-04 / P1-F2-01：api_web 单体拆分） ----------------
# 必须在 SPA catch-all（/{full_path:path}）之前挂载，否则会被兜底路由吞掉。
# 业务端点分布在 api_routes/ 包内（每文件 <300 行，端点列表见各模块 docstring）。

from api_routes import agent as _agent_routes
from api_routes import auth as _auth_routes
from api_routes import elderly as _elderly_routes
from api_routes import export as _export_routes
from api_routes import health as _health_routes
from api_routes import issues as _issues_routes
from api_routes import messages as _messages_routes
from api_routes import notices as _notices_routes
from api_routes import opinions as _opinions_routes
from api_routes import policy as _policy_routes
from api_routes import proposals as _proposals_routes
from api_routes import upload as _upload_routes
from api_routes import weather as _weather_routes

app.include_router(_agent_routes.router)
app.include_router(_auth_routes.router)
app.include_router(_elderly_routes.router)
app.include_router(_elderly_routes.manage_router)
app.include_router(_export_routes.router)
app.include_router(_health_routes.router)
app.include_router(_issues_routes.router)
app.include_router(_messages_routes.router)
app.include_router(_notices_routes.router)
app.include_router(_opinions_routes.router)
app.include_router(_policy_routes.router)
app.include_router(_policy_routes.knowledge_router)
app.include_router(_proposals_routes.router)
app.include_router(_upload_routes.router)
app.include_router(_weather_routes.router)


_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web", "dist")


@app.get("/{full_path:path}")
def _spa(full_path: str):
    """前端静态托管 + history fallback（dist 存在且含 index.html 时启用）。"""
    index = os.path.join(_DIST, "index.html")
    if not os.path.isfile(index):
        return JSONResponse(status_code=200, content={
            "service": "CommunityInsight Web API", "status": "ok",
            "note": "Vue3 前端尚未构建（P2 阶段），请访问 /web/docs 查看接口文档",
        })
    candidate = os.path.normpath(os.path.join(_DIST, full_path))
    if os.path.isfile(candidate) and candidate.startswith(os.path.normpath(_DIST)):
        return FileResponse(candidate)
    return FileResponse(index)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
