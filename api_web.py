# api_web.py — 前后端分离 Web API（Vue3 前端用）
"""社区先知 CommunityInsight — FastAPI + Vue3 前端专用后端。

与 api.py（扣子插件用，API-key 鉴权）独立运行：
  uvicorn api_web:app --host 0.0.0.0 --port 8000

特点：
  - JWT 用户鉴权（stdlib HMAC-SHA256 实现 HS256，零第三方依赖）
  - /api/web/* 端点复用现有 data/ 层函数与 SQLite schema（零数据层改动）
  - 统一响应 {success, data, error, code, message}
  - 单进程同时服务 API + Vue3 构建产物（dist/）
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_log = logging.getLogger(__name__)

# ---------------- JWT（stdlib HMAC HS256） ----------------

_SECRET = os.getenv("WEB_JWT_SECRET", "community-insight-web-jwt-2026")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(user_id: int, role: str, name: str, expires_hours: int = 12) -> str:
    """签发 JWT（HS256）。"""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "uid": user_id, "role": role, "name": name,
        "exp": int(time.time()) + expires_hours * 3600,
    }, ensure_ascii=False).encode())
    sig = _b64(hmac.new(_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_token(token: str) -> dict | None:
    """校验 JWT，返回 payload；失败返回 None。"""
    try:
        header, payload, sig = token.split(".")
        expect = _b64(hmac.new(_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expect, sig):
            return None
        data = json.loads(_b64d(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


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


# 公开路径：登录 + 文档 + 前端静态
_PUBLIC_PATHS = {"/api/web/auth/login", "/api/web/auth/demo", "/web/docs", "/web/redoc",
                 "/web/openapi.json", "/", "/index.html", "/favicon.ico"}


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


# ---------------- 认证 ----------------

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(default="")


class DemoLoginRequest(BaseModel):
    role: str = Field(..., pattern="^(resident|grid|elderly)$")


@app.post("/api/web/auth/login")
def web_login(req: LoginRequest):
    """居民/负责人/老人登录。"""
    from data.db_user import authenticate, get_user_by_username
    user = authenticate(req.username, req.password)
    if user is None:
        return fail(1002, "用户名或密码错误")
    token = make_token(user["id"], user["role"], user.get("name") or user.get("username") or "")
    return ok({
        "token": token,
        "role": user["role"],
        "user_id": user["id"],
        "name": user.get("name") or user.get("username"),
        "community": user.get("community") or "",
        "building": user.get("building") or "",
        "unit": user.get("unit") or "",
        "phone": user.get("phone") or "",
    })


@app.post("/api/web/auth/demo")
def web_demo_login(req: DemoLoginRequest):
    """演示快速登录：直接取该角色第一个演示账号。"""
    from data.db_user import list_users
    for u in list_users(role=req.role):
        token = make_token(u["id"], u["role"], u.get("name") or u.get("username") or "")
        return ok({
            "token": token, "role": u["role"], "user_id": u["id"],
            "name": u.get("name") or u.get("username"),
            "community": u.get("community") or "", "building": u.get("building") or "",
            "unit": u.get("unit") or "", "phone": u.get("phone") or "",
        })
    return fail(1004, "没有可用的演示账号")


@app.get("/api/web/auth/me")
def web_me(request: Request):
    """当前用户信息。"""
    u = _user(request)
    from data.db_user import get_user_by_id
    row = get_user_by_id(u.get("uid"))
    if not row:
        return fail(1004, "用户不存在")
    return ok({
        "user_id": row["id"], "role": row["role"],
        "name": row.get("name") or row.get("username"),
        "community": row.get("community") or "", "building": row.get("building") or "",
        "unit": row.get("unit") or "", "phone": row.get("phone") or "",
        "resident_id": row.get("resident_id") or "",
    })


# ---------------- 附件上传 ----------------

class UploadResult(BaseModel):
    path: str


@app.post("/api/web/upload")
async def web_upload(request: Request, folder: str = "web"):
    """上传附件（图片/PDF，≤5MB）。multipart/form-data，字段名 files。"""
    from utils.uploads import save_uploaded_files
    try:
        form = await request.form()
        files = form.getlist("files")
        objs = []
        for f in files:
            data = await f.read()
            objs.append(_FakeUploadFile(f.filename or "x.jpg", len(data), data))
        if not objs:
            return fail(1001, "未选择文件")
        saved, errs = save_uploaded_files(objs, folder=folder, max_count=5)
        if errs:
            return fail(2001, "；".join(errs))
        return ok({"paths": saved}, "上传成功")
    except Exception as e:  # noqa: BLE001
        return fail(1001, f"上传失败：{e}")


class _FakeUploadFile:
    """把 multipart 上传对象适配成 utils/uploads 需要的接口（name/size/getbuffer）。"""

    def __init__(self, name, size, data):
        self.name = name
        self.size = size
        self._data = data

    def getbuffer(self):
        import io
        return io.BytesIO(self._data)


# ---------------- 报修模块（复用 db_repair） ----------------

class IssueCreate(BaseModel):
    title: str = Field(..., min_length=2)
    category: str = Field(default="公共设施")
    issue_type: str = Field(default="室内", pattern="^(室内|室外)$")
    location: str = Field(default="")
    description: str = Field(default="")
    urgency: str = Field(default="一般")
    reporter_name: str = Field(default="")
    reporter_phone: str = Field(default="")
    photo_before: str = Field(default="[]")


@app.post("/api/web/issues")
def web_issue_create(req: IssueCreate, request: Request):
    u = _user(request)
    iid, hint = _db_submit_issue(
        title=req.title, category=req.category, issue_type=req.issue_type,
        location=req.location, description=req.description or req.title,
        urgency=req.urgency, reporter_name=req.reporter_name or u.get("name") or "居民",
        reporter_phone=req.reporter_phone, reporter_id=u.get("uid"),
        photo_before=req.photo_before,
    )
    if iid <= 0:
        return fail(2001, hint or "提交失败")
    return ok({"issue_id": iid, "hint": hint}, "提交成功")


def _db_submit_issue(**kw):
    from data.db_repair import submit_issue
    return submit_issue(**kw)


@app.get("/api/web/issues")
def web_issue_list(request: Request, status: str = "", limit: int = 200):
    from data.db_repair import get_issues
    u = _user(request)
    if u.get("role") == "grid":
        rows = get_issues(status=status or None, limit=limit)
    else:
        rows = get_issues(reporter_id=u.get("uid"), limit=limit)
    return ok([_issue_view(r) for r in rows])


@app.get("/api/web/issues/{issue_id}")
def web_issue_detail(issue_id: int, request: Request):
    from data.db_repair import get_issues, get_issue_timeline
    rows = get_issues(limit=1000)
    row = next((r for r in rows if r["id"] == issue_id), None)
    if not row:
        return fail(1004, "工单不存在")
    detail = _issue_view(row)
    detail["timeline"] = [dict(t) for t in get_issue_timeline(issue_id)]
    return ok(detail)


def _issue_view(r: dict) -> dict:
    return {
        "id": r.get("id"), "title": r.get("title"), "category": r.get("category"),
        "issue_type": r.get("issue_type"), "location": r.get("location"),
        "description": r.get("description"), "urgency": r.get("urgency"),
        "status": r.get("status"), "reporter_name": r.get("reporter_name"),
        "reporter_phone": r.get("reporter_phone"), "assignee_name": r.get("assignee_name"),
        "created_at": r.get("reported_at"), "approved_at": r.get("approved_at"),
        "resolve_note": r.get("resolve_note"), "supplement_pending": r.get("supplement_pending"),
    }


class IssueAction(BaseModel):
    action: str = Field(..., pattern="^(audit|dispatch|start|resolve|feedback|withdraw|close|transfer|negotiate|supplement|confirm_supplement|update_category)$")
    opinion: str = Field(default="")
    approve: bool = Field(default=True)
    assignee_name: str = Field(default="")
    assignee_phone: str = Field(default="")
    reason: str = Field(default="")
    satisfied: bool = Field(default=True)
    affects_timing: bool = Field(default=False)
    category: str = Field(default="")
    note: str = Field(default="")


@app.post("/api/web/issues/{issue_id}/action")
def web_issue_action(issue_id: int, req: IssueAction, request: Request):
    from data.db_repair import (
        audit_issue, dispatch_issue, start_process, resolve_issue, feedback_issue,
        withdraw_issue, close_issue, transfer_issue, negotiate_issue,
        supplement_issue, confirm_supplement, update_issue_category,
    )
    actor = _user(request).get("name") or "负责人"
    a = req.action
    try:
        if a == "audit":
            ok_, msg = audit_issue(issue_id, req.approve, opinion=req.opinion, actor=actor)
        elif a == "dispatch":
            ok_, msg = dispatch_issue(issue_id, req.assignee_name, req.assignee_phone, actor=actor)
        elif a == "start":
            ok_, msg = start_process(issue_id, actor=actor)
        elif a == "resolve":
            ok_, msg = resolve_issue(issue_id, req.note, no_photo_reason=req.reason, actor=actor)
        elif a == "feedback":
            ok_, msg = feedback_issue(issue_id, req.satisfied, reason=req.reason, actor=actor)
        elif a == "withdraw":
            ok_, msg = withdraw_issue(issue_id, actor=actor)
        elif a == "close":
            ok_, msg = close_issue(issue_id, req.reason, actor=actor)
        elif a == "transfer":
            ok_, msg = transfer_issue(issue_id, actor=actor)
        elif a == "negotiate":
            ok_, msg = negotiate_issue(issue_id, req.reason, actor=actor)
        elif a == "supplement":
            ok_, msg = supplement_issue(issue_id, req.opinion, actor=actor)
        elif a == "confirm_supplement":
            ok_, msg = confirm_supplement(issue_id, affects_timing=req.affects_timing, actor=actor)
        elif a == "update_category":
            ok_, msg = update_issue_category(issue_id, req.category, actor=actor)
        else:
            return fail(1001, "不支持的操作")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"操作失败：{e}")
    if not ok_:
        return fail(2001, msg or "操作被拒绝")
    return ok({"issue_id": issue_id}, msg or "操作成功")


# ---------------- 提案模块（复用 db_proposal） ----------------

class ProposalCreate(BaseModel):
    title: str = Field(..., min_length=2)
    description: str = Field(..., min_length=5)
    category: str = Field(default="其他")
    is_public: int = Field(default=1)
    reporter_name: str = Field(default="")
    reporter_phone: str = Field(default="")


@app.post("/api/web/proposals")
def web_proposal_create(req: ProposalCreate, request: Request):
    from data.db_proposal import submit_proposal
    u = _user(request)
    pid, msg = submit_proposal(
        title=req.title, description=req.description, category=req.category,
        reporter_name=req.reporter_name or u.get("name") or "居民",
        reporter_phone=req.reporter_phone, is_public=req.is_public,
        reporter_id=u.get("uid"),
    )
    if pid <= 0:
        return fail(2001, msg or "提交失败")
    return ok({"proposal_id": pid}, "提交成功")


@app.get("/api/web/proposals")
def web_proposal_list(request: Request, status: str = "", limit: int = 300):
    from data.db_proposal import get_proposals
    u = _user(request)
    rows = get_proposals(status=status or None, limit=limit)
    out = []
    for p in rows:
        out.append({
            "id": p.get("id"), "title": p.get("title"), "category": p.get("category"),
            "status": p.get("status"), "is_public": p.get("is_public"),
            "reporter_name": p.get("reporter_name"), "created_at": p.get("created_at"),
            "reopen_count": p.get("reopen_count") or 0,
        })
    return ok(out)


class ProposalVote(BaseModel):
    score: int = Field(..., ge=1, le=5)


@app.post("/api/web/proposals/{pid}/vote")
def web_proposal_vote(pid: int, req: ProposalVote, request: Request):
    from data.db_proposal import vote_proposal
    u = _user(request)
    ok_, msg = vote_proposal(pid, u.get("uid"), req.score, actor="匿名居民")
    if not ok_:
        return fail(2001, msg or "投票失败")
    return ok({"proposal_id": pid}, "投票成功")


# ---------------- 静态托管（Vue3 dist，P2 后启用） ----------------

_DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist")


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
