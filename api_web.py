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

from data.db_elderly_care import COMMUNITY_PHONE as _COMMUNITY_PHONE

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


# ---------------- 系统 ----------------

@app.get("/api/web/health")
def web_health():
    """健康检查（Docker HEALTHCHECK 用）。"""
    return ok({"service": "CommunityInsight Web", "status": "ok"})


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
    if not row.get("is_active"):
        return fail(1003, "账号已注销")
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
    is_agent_report: int = Field(default=0)
    agent_name: str = Field(default="")
    agent_phone: str = Field(default="")
    agent_relation: str = Field(default="")


@app.post("/api/web/issues")
def web_issue_create(req: IssueCreate, request: Request):
    u = _user(request)
    iid, hint = _db_submit_issue(
        title=req.title, category=req.category, issue_type=req.issue_type,
        location=req.location, description=req.description or req.title,
        urgency=req.urgency, reporter_name=req.reporter_name or u.get("name") or "居民",
        reporter_phone=req.reporter_phone, reporter_id=u.get("uid"),
        photo_before=req.photo_before,
        is_agent_report=req.is_agent_report, agent_name=req.agent_name,
        agent_phone=req.agent_phone, agent_relation=req.agent_relation,
    )
    if iid <= 0:
        return fail(2001, hint or "提交失败")
    # 重复上报检测（P2-02）：7 天内同楼栋同类问题 → 合并提示 + 通知双方（原工单不动）
    dup = None
    try:
        from data.db_repair import find_duplicate_issue
        dup = find_duplicate_issue(req.location, req.description, exclude_id=iid)
    except Exception:
        dup = None
    if dup:
        try:
            from data.db_notifications import create_notification
            if dup.get("reporter_id"):
                create_notification(dup["reporter_id"], "issue",
                                    f"工单 #{dup['id']} 有新的居民上报了相同问题",
                                    f"您报修的「{(dup.get('title') or '')[:20]}」又有居民上报，我们正在一并处理。")
            if u.get("uid"):
                create_notification(u.get("uid"), "issue",
                                    f"您上报的问题已合并处理",
                                    f"您报修的问题与工单 #{dup['id']} 相同，已合并处理，可在「我的报修」查看进度。")
        except Exception:
            pass
        return ok({"issue_id": iid, "merged": True, "original_id": dup["id"],
                   "hint": hint}, "已提交，检测到重复上报已合并处理")
    return ok({"issue_id": iid, "merged": False, "hint": hint}, "提交成功")


def _db_submit_issue(**kw):
    from data.db_repair import submit_issue
    return submit_issue(**kw)


@app.get("/api/web/issues")
def web_issue_list(request: Request, status: str = "", category: str = "",
                   urgency: str = "", issue_type: str = "", keyword: str = "",
                   limit: int = 200):
    from data.db_repair import get_issues
    u = _user(request)
    if u.get("role") == "grid":
        rows = get_issues(status=status or None, category=category or None,
                          urgency=urgency or None, issue_type=issue_type or None,
                          keyword=keyword or None, limit=limit)
    else:
        rows = get_issues(reporter_id=u.get("uid"), status=status or None, limit=limit)
    # 非负责人：手机号脱敏
    out = []
    for r in rows:
        v = _issue_view(r)
        if u.get("role") != "grid" and v.get("reporter_phone"):
            v["reporter_phone"] = v["reporter_phone"][:3] + "****" + v["reporter_phone"][-4:]
        out.append(v)
    return ok(out)


@app.get("/api/web/issues/safety-reminders")
def web_issue_safety_reminders(request: Request, limit: int = 100):
    """负责人查看安全隐患提醒记录。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_repair import get_safety_reminders
    return ok(get_safety_reminders(limit=limit))


# ---- 报修草稿（必须注册在 /issues/{issue_id} 之前，避免被动态路由遮蔽） ----

class IssueDraft(BaseModel):
    title: str = Field(default="")
    location: str = Field(default="")
    description: str = Field(default="")
    urgency: str = Field(default="一般")
    issue_type: str = Field(default="室内")


@app.get("/api/web/issues/drafts")
def web_issue_drafts(request: Request):
    """当前居民未完成的报修草稿。"""
    from data.db_repair import get_drafts
    u = _user(request)
    return ok([dict(r) for r in get_drafts(u.get("uid"))])


@app.post("/api/web/issues/drafts")
def web_issue_draft_save(req: IssueDraft, request: Request):
    """保存报修草稿（崩溃/超时自动生成，7 天内可恢复）。"""
    from data.db_repair import create_draft
    u = _user(request)
    if not req.title:
        return fail(1001, "请至少填写问题描述")
    create_draft(
        u.get("uid"), title=req.title, category="", issue_type=req.issue_type,
        location=req.location, description=req.description or req.title,
        urgency=req.urgency, reporter_name="", reporter_phone="",
    )
    return ok({"saved": True}, "草稿已保存")


@app.delete("/api/web/issues/drafts/{did}")
def web_issue_draft_delete(did: int, request: Request):
    """删除草稿（校验归属：居民只能删自己的）。"""
    from data.db_repair import get_draft, delete_draft
    u = _user(request)
    d = get_draft(did)
    if not d:
        return fail(1004, "草稿不存在")
    if u.get("role") != "grid" and d.get("user_id") != u.get("uid"):
        return fail(1003, "无权限删除该草稿")
    delete_draft(did)
    return ok({"deleted": did}, "已删除")


@app.get("/api/web/issues/{issue_id}")
def web_issue_detail(issue_id: int, request: Request):
    from data.db_repair import get_issues, get_issue_timeline
    u = _user(request)
    rows = get_issues(limit=1000)
    row = next((r for r in rows if r["id"] == issue_id), None)
    if not row:
        return fail(1004, "工单不存在")
    # 权限：居民只能看自己的工单
    if u.get("role") != "grid" and row.get("reporter_id") != u.get("uid"):
        return fail(1003, "无权限查看该工单")
    detail = _issue_view(row)
    if u.get("role") != "grid" and detail.get("reporter_phone"):
        detail["reporter_phone"] = detail["reporter_phone"][:3] + "****" + detail["reporter_phone"][-4:]
    detail["timeline"] = [dict(t) for t in get_issue_timeline(issue_id)]
    return ok(detail)


def _issue_deadline(r: dict) -> dict:
    """按紧急程度计算时限（审核通过后计时：紧急1h/中等4h/一般24h/普通48h）。"""
    hours = {"紧急": 1, "中等": 4, "一般": 24, "普通": 48}.get(r.get("urgency"), 24)
    approved = r.get("approved_at")
    remaining, overdue = None, False
    if approved:
        try:
            from datetime import datetime
            t0 = datetime.strptime(str(approved)[:19], "%Y-%m-%d %H:%M:%S")
            remaining = round(hours - (datetime.utcnow() - t0).total_seconds() / 3600.0, 2)
            overdue = remaining < 0
        except (ValueError, TypeError):
            pass
    return {"deadline_hours": hours, "remaining_hours": remaining, "overdue": overdue}


def _issue_view(r: dict) -> dict:
    v = {
        "id": r.get("id"), "title": r.get("title"), "category": r.get("category"),
        "issue_type": r.get("issue_type"), "location": r.get("location"),
        "description": r.get("description"), "urgency": r.get("urgency"),
        "status": r.get("status"), "reporter_name": r.get("reporter_name"),
        "reporter_phone": r.get("reporter_phone"), "assignee_name": r.get("assignee_name"),
        "created_at": r.get("reported_at"), "approved_at": r.get("approved_at"),
        "resolve_note": r.get("resolve_note"), "supplement_pending": r.get("supplement_pending"),
        "is_violation": r.get("is_violation") or 0,
        "non_community_responsibility": r.get("non_community_responsibility") or 0,
        "photo_before": r.get("photo_before") or "[]",
        "is_agent_report": r.get("is_agent_report") or 0,
        "agent_name": r.get("agent_name") or "",
        "agent_relation": r.get("agent_relation") or "",
    }
    v.update(_issue_deadline(r))
    return v


class IssueAction(BaseModel):
    action: str = Field(..., pattern="^(audit|dispatch|start|resolve|feedback|withdraw|close|transfer|negotiate|supplement|confirm_supplement|update_category|reopen|resubmit|edit)$")
    opinion: str = Field(default="")
    approve: bool = Field(default=True)
    assignee_name: str = Field(default="")
    assignee_phone: str = Field(default="")
    reason: str = Field(default="")
    satisfied: bool = Field(default=True)
    affects_timing: bool = Field(default=False)
    category: str = Field(default="")
    note: str = Field(default="")
    title: str = Field(default="")
    location: str = Field(default="")
    description: str = Field(default="")
    urgency: str = Field(default="")


@app.post("/api/web/issues/{issue_id}/action")
def web_issue_action(issue_id: int, req: IssueAction, request: Request):
    from data.db_repair import (
        audit_issue, dispatch_issue, start_process, resolve_issue, feedback_issue,
        withdraw_issue, close_issue, transfer_issue, negotiate_issue,
        supplement_issue, confirm_supplement, update_issue_category,
        reopen_issue, resubmit_issue, edit_issue,
    )
    u = _user(request)
    role = u.get("role")
    # 权限（spec 六）：状态管理类操作仅负责人；居民可 反馈/撤回/补充/重新打开/重新提交/修改一次
    resident_actions = {"feedback", "withdraw", "supplement", "reopen", "resubmit", "edit"}
    if role != "grid" and req.action not in resident_actions:
        return fail(1003, "无权限执行该操作（仅负责人可管理工单状态）")
    # 归属校验：居民只能操作自己提交的工单
    if role != "grid":
        from data.db_repair import get_issue
        issue = get_issue(issue_id)
        if not issue:
            return fail(1004, "工单不存在")
        if issue.get("reporter_id") != u.get("uid"):
            return fail(1003, "无权限操作该工单（非本人报修）")
    actor = u.get("name") or "负责人"
    a = req.action
    try:
        if a == "audit":
            ok_, msg = audit_issue(issue_id, req.approve, opinion=req.opinion, actor=actor)
        elif a == "dispatch":
            ok_, msg = dispatch_issue(issue_id, req.assignee_name, req.assignee_phone, actor=actor)
        elif a == "start":
            ok_, msg = start_process(issue_id, actor=actor)
        elif a == "resolve":
            ok_, msg = resolve_issue(issue_id, req.note,
                                     no_photo_reason=req.reason or "现场未拍照", actor=actor)
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
        elif a == "reopen":
            ok_, msg = reopen_issue(issue_id, actor=actor)
        elif a == "resubmit":
            ok_, msg = resubmit_issue(issue_id, actor=actor)
        elif a == "edit":
            ok_, msg = edit_issue(issue_id, actor=actor, title=req.title,
                                  location=req.location, description=req.description,
                                  urgency=req.urgency)
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
    community_building: str = Field(default="")
    attachment_public: int = Field(default=0)
    attachment: str = Field(default="[]")
    is_agent_report: int = Field(default=0)
    agent_name: str = Field(default="")
    agent_phone: str = Field(default="")
    agent_relation: str = Field(default="")


@app.post("/api/web/proposals")
def web_proposal_create(req: ProposalCreate, request: Request):
    from data.db_proposal import submit_proposal
    u = _user(request)
    pid, msg = submit_proposal(
        title=req.title, description=req.description, category=req.category,
        reporter_name=req.reporter_name or u.get("name") or "居民",
        reporter_phone=req.reporter_phone, is_public=req.is_public,
        reporter_id=u.get("uid"),
        community_building=req.community_building,
        attachment_public=req.attachment_public, attachment=req.attachment,
        is_agent_report=req.is_agent_report, agent_name=req.agent_name,
        agent_phone=req.agent_phone, agent_relation=req.agent_relation,
    )
    if pid <= 0:
        return fail(2001, msg or "提交失败")
    return ok({"proposal_id": pid}, "提交成功")


# 提案草稿（崩溃/超时留草稿，7 天有效）

class ProposalDraft(BaseModel):
    title: str = Field(default="")
    description: str = Field(default="")
    category: str = Field(default="其他")
    is_public: int = Field(default=1)
    reporter_name: str = Field(default="")
    reporter_phone: str = Field(default="")
    attachment_public: int = Field(default=0)


@app.get("/api/web/proposals/drafts")
def web_proposal_drafts(request: Request):
    from data.db_proposal import get_drafts
    u = _user(request)
    return ok(get_drafts(u.get("uid")))


@app.post("/api/web/proposals/drafts")
def web_proposal_draft_save(req: ProposalDraft, request: Request):
    from data.db_proposal import save_draft
    u = _user(request)
    did = save_draft(
        u.get("uid"), title=req.title, description=req.description,
        category=req.category, is_public=req.is_public,
        reporter_name=req.reporter_name, reporter_phone=req.reporter_phone,
        attachment_public=req.attachment_public,
    )
    return ok({"draft_id": did}, "草稿已保存")


@app.delete("/api/web/proposals/drafts/{did}")
def web_proposal_draft_delete(did: int, request: Request):
    from data.db_proposal import get_draft, delete_draft
    u = _user(request)
    d = get_draft(did, u.get("uid"))
    if not d:
        return fail(1004, "草稿不存在")
    delete_draft(did)
    return ok({"deleted": did}, "草稿已删除")


@app.get("/api/web/proposals")
def web_proposal_list(request: Request, status: str = "", limit: int = 300):
    from data.db_proposal import get_proposals, get_proposal_vote_stats, has_voted
    u = _user(request)
    rows = get_proposals(status=status or None, limit=limit)
    out = []
    for p in rows:
        # 居民：只看自己提交的（含私有/待审核等）+ 公开公示链上的，且他人姓名脱敏
        if u.get("role") != "grid":
            mine = p.get("reporter_id") == u.get("uid")
            if not mine:
                if p.get("status") not in ("公示中", "待执行", "执行中", "待提案人反馈", "重新执行", "已完成"):
                    continue
                if not p.get("is_public"):
                    continue
        stats = {}
        remaining = None
        try:
            stats = get_proposal_vote_stats(p.get("id")) or {}
        except Exception:
            stats = {}
        if p.get("status") == "公示中" and p.get("voting_ended_at"):
            try:
                from datetime import datetime
                end = datetime.strptime(str(p["voting_ended_at"])[:19], "%Y-%m-%d %H:%M:%S")
                remaining = max(0, (end - datetime.utcnow()).days + 1)
            except (ValueError, TypeError):
                remaining = None
        out.append({
            "id": p.get("id"), "title": p.get("title"), "category": p.get("category"),
            "status": p.get("status"), "is_public": p.get("is_public"),
            "reporter_name": p.get("reporter_name") if u.get("role") == "grid"
            else ((p.get("reporter_name") or "")[:1] + "**" if p.get("reporter_name") else "—"),
            "created_at": p.get("created_at"),
            "reopen_count": p.get("reopen_count") or 0,
            "mine": u.get("role") != "grid" and p.get("reporter_id") == u.get("uid"),
            "proposal_no": p.get("id"),
            "vote_count": stats.get("vote_count") or 0,
            "avg_score": stats.get("avg_score"),
            "rank": stats.get("rank"),
            "remaining_days": remaining,
            "executor_dept": p.get("executor_dept") or "",
            "execution_result": p.get("execution_result") or "",
            "attachment_public": p.get("attachment_public") or 0,
            "has_voted": bool(has_voted(p.get("id"), u.get("uid"))),
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


# ---------------- 提案议论（公示期匿名讨论） ----------------

class ProposalCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


@app.get("/api/web/proposals/{pid}/comments")
def web_proposal_comments(pid: int, request: Request, limit: int = 100):
    """公示提案的匿名议论列表（作者为匿名伪名，匿名可见）。"""
    from data.db_proposal import get_proposal_comments, get_proposal
    p = get_proposal(pid)
    if not p:
        return fail(1004, "提案不存在")
    u = _user(request)
    if u.get("role") != "grid" and (not p.get("is_public") or p.get("status") not in
                                    ("公示中", "待执行", "执行中", "待提案人反馈", "重新执行")):
        return fail(1003, "该提案暂不支持议论")
    return ok(get_proposal_comments(pid, limit=limit))


@app.post("/api/web/proposals/{pid}/comments")
def web_proposal_comment_add(pid: int, req: ProposalCommentCreate, request: Request):
    """匿名发表议论（自己能看到、别人能看到，均不显示真实身份）。"""
    from data.db_proposal import add_proposal_comment
    u = _user(request)
    ok_, msg = add_proposal_comment(pid, u.get("uid"), req.content)
    if not ok_:
        return fail(2001, msg)
    return ok({"proposal_id": pid}, "议论已发布（匿名）")




class ProposalAction(BaseModel):
    action: str = Field(..., pattern="^(audit|confirm|decide|execute|resolve|feedback|reopen|close|take_down|resubmit|withdraw|reopen_mine|change_visibility|update_category|view_phone|remind|extend_voting)$")
    approve: bool = Field(default=True)
    opinion: str = Field(default="")
    is_public: int = Field(default=1)
    reason: str = Field(default="")
    dept: str = Field(default="")
    result: str = Field(default="")
    satisfied: bool = Field(default=True)
    close: bool = Field(default=False)
    category: str = Field(default="")
    minutes: int = Field(default=1440)
    attachment_public_ok: bool | None = Field(default=None)


@app.post("/api/web/proposals/{pid}/action")
def web_proposal_action(pid: int, req: ProposalAction, request: Request):
    from data.db_proposal import (
        audit_proposal, confirm_visibility, decide_execute, start_execute,
        resolve_proposal, feedback_proposal, handle_reopen, close_proposal,
        take_down_proposal, resubmit_proposal, withdraw_proposal,
        reopen_proposal, change_visibility, update_category, view_full_phone,
        remind_confirm, extend_voting,
    )
    u = _user(request)
    role = u.get("role")
    # 权限：管理动作仅负责人；居民可确认公开/私有、反馈、撤回、重新提交、重新打开、改公开方式
    resident_actions = {"confirm", "feedback", "resubmit", "withdraw", "reopen_mine", "change_visibility"}
    if role != "grid" and req.action not in resident_actions:
        return fail(1003, "无权限执行该操作（仅负责人可管理提案）")
    actor = u.get("name") or "负责人"
    a = req.action
    try:
        if a == "audit":
            ok_, msg = audit_proposal(pid, req.approve, opinion=req.opinion,
                                      attachment_public_ok=req.attachment_public_ok, actor=actor)
        elif a == "confirm":
            ok_, msg = confirm_visibility(pid, req.is_public, actor=actor)
        elif a == "decide":
            ok_, msg = decide_execute(pid, req.approve, reason=req.reason, actor=actor)
        elif a == "execute":
            ok_, msg = start_execute(pid, req.dept, actor=actor)
        elif a == "resolve":
            ok_, msg = resolve_proposal(pid, req.result, actor=actor)
        elif a == "feedback":
            ok_, msg = feedback_proposal(pid, req.satisfied, reason=req.reason, actor=actor)
        elif a == "reopen":
            ok_, msg = handle_reopen(pid, close=req.close, reason=req.reason, actor=actor)
        elif a == "close":
            ok_, msg = close_proposal(pid, req.reason, actor=actor)
        elif a == "take_down":
            ok_, msg = take_down_proposal(pid, req.reason, actor=actor)
        elif a == "resubmit":
            ok_, msg = resubmit_proposal(pid, title=req.opinion, description=req.result,
                                         category=req.category, actor=actor)
        elif a == "withdraw":
            ok_, msg = withdraw_proposal(pid, actor=actor)
        elif a == "reopen_mine":
            ok_, msg = reopen_proposal(pid, actor=actor)
        elif a == "change_visibility":
            ok_, msg = change_visibility(pid, req.is_public, actor=actor)
        elif a == "update_category":
            ok_, msg = update_category(pid, req.category, actor=actor)
        elif a == "view_phone":
            phone = view_full_phone(pid, actor)
            if not phone:
                return fail(1004, "提案不存在")
            return ok({"phone": phone}, "已留痕查看完整手机号")
        elif a == "remind":
            ok_, msg = remind_confirm(pid, actor=actor)
        elif a == "extend_voting":
            ok_, msg = extend_voting(pid, req.minutes, actor=actor)
        else:
            return fail(1001, "不支持的操作")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"操作失败：{e}")
    if not ok_:
        return fail(2001, msg or "操作被拒绝")
    return ok({"proposal_id": pid}, msg or "操作成功")


# ---------------- 通知模块（复用 db_notice） ----------------

class NoticeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=50)
    notice_type: str = Field(..., pattern="^(社区公告|活动通知|停水停电通知|政策通知|温馨提示|紧急通知|其他)$")
    publish_scope: str = Field(default="全体居民", pattern="^(全体居民|指定小区|指定楼栋|仅老年端)$")
    body: str = Field(..., min_length=1)
    elderly_summary: str = Field(default="")
    is_urgent: int = Field(default=0)
    is_pinned: int = Field(default=0)
    expire_at: str = Field(default="")
    scheduled_at: str = Field(default="")
    attachment_json: str = Field(default="[]")
    scope_target_json: str = Field(default="[]")


@app.post("/api/web/notices")
def web_notice_create(req: NoticeCreate, request: Request):
    from data.db_notice import create_notice, can_publish_urgent
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    actor = _user(request).get("name") or "负责人"
    # 紧急通知权限白名单（方案权限矩阵：仅紧急通知发布人）
    if req.is_urgent and not can_publish_urgent(_user(request).get("uid")):
        return fail(1003, "您无权发布紧急通知（仅指定负责人）")
    nid = create_notice(
        title=req.title, notice_type=req.notice_type, publish_scope=req.publish_scope,
        body=req.body, elderly_summary=req.elderly_summary, publisher=actor,
        is_pinned=req.is_pinned, is_urgent=req.is_urgent, expire_at=req.expire_at,
        attachment_json=req.attachment_json, scope_target_json=req.scope_target_json,
        actor=actor,
    )
    if nid <= 0:
        return fail(2001, "通知类型或敏感词校验不通过")
    # 定时 / 立即发布
    if req.scheduled_at:
        from data.db_notice import schedule_notice
        ok_, msg = schedule_notice(nid, req.scheduled_at, _user(request).get("uid"), actor,
                                   confirm_urgent=bool(req.is_urgent))
        if not ok_:
            return fail(2001, msg)
    elif req.notice_type != "紧急通知":
        from data.db_notice import publish_notice
        ok_, msg = publish_notice(nid, _user(request).get("uid"), actor)
        if not ok_:
            return fail(2001, msg)
    return ok({"notice_id": nid}, "通知已创建")


@app.get("/api/web/notices")
def web_notice_list(request: Request, limit: int = 100):
    from data.db_notice import get_visible_notices
    u = _user(request)
    role = u.get("role")
    client_type = "elderly" if role == "elderly" else "resident"
    rows = get_visible_notices(client_type, u.get("uid"), limit=limit)
    out = [{
        "id": n.get("id"), "title": n.get("title"), "notice_type": n.get("notice_type"),
        "body": n.get("body"), "is_urgent": n.get("is_urgent"), "is_pinned": n.get("is_pinned"),
        "published_at": n.get("published_at"), "elderly_summary": n.get("elderly_summary"),
        "is_read": n.get("is_read", 0),
    } for n in rows]
    return ok(out)


@app.get("/api/web/notices/manage")
def web_notice_manage(request: Request, status: str = "", limit: int = 200):
    """负责人端通知管理列表（含已读统计）。"""
    from ui.cache import cached_notices_with_stats
    _r = _require_role(request, "grid")
    if _r:
        return _r
    rows = cached_notices_with_stats(status=status or None, limit=limit)
    return ok(rows)


class NoticeAction(BaseModel):
    action: str = Field(..., pattern="^(publish|schedule|withdraw|take_down|pin|unpin|mark_read|delete)$")
    scheduled_at: str = Field(default="")
    reason: str = Field(default="")
    confirm_urgent: bool = Field(default=False)


@app.post("/api/web/notices/{nid}/action")
def web_notice_action(nid: int, req: NoticeAction, request: Request):
    from data.db_notice import (
        publish_notice, schedule_notice, withdraw_notice, take_down_notice,
        set_pinned, mark_notice_read, delete_notice,
    )
    from ui.cache import invalidate_notices
    u = _user(request)
    # 管理动作仅负责人；mark_read 允许居民/老年
    if req.action != "mark_read" and u.get("role") != "grid":
        return fail(1003, "无权限执行该操作（仅负责人可管理通知）")
    actor = u.get("name") or "负责人"
    a = req.action
    try:
        if a == "publish":
            ok_, msg = publish_notice(nid, u.get("uid"), actor, confirm_urgent=req.confirm_urgent)
        elif a == "schedule":
            ok_, msg = schedule_notice(nid, req.scheduled_at, u.get("uid"), actor,
                                       confirm_urgent=req.confirm_urgent)
        elif a == "withdraw":
            ok_, msg = withdraw_notice(nid, actor)
        elif a == "take_down":
            ok_, msg = take_down_notice(nid, req.reason, actor)
        elif a == "pin":
            ok_, msg = set_pinned(nid, True, actor)
        elif a == "unpin":
            ok_, msg = set_pinned(nid, False, actor)
        elif a == "mark_read":
            mark_notice_read(nid, "elderly" if u.get("role") == "elderly" else "resident", u.get("uid"))
            return ok({"notice_id": nid}, "已标记已读")
        elif a == "delete":
            delete_notice(nid, actor)
            invalidate_notices()
            return ok({"notice_id": nid}, "已删除")
        else:
            return fail(1001, "不支持的操作")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"操作失败：{e}")
    if not ok_:
        return fail(2001, msg or "操作被拒绝")
    invalidate_notices()
    return ok({"notice_id": nid}, msg or "操作成功")


# ---------------- 政策问答（复用 db_policy） ----------------

class AskQuestion(BaseModel):
    question: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="")
    source: str = Field(default="居民端")


@app.post("/api/web/qa/ask")
def web_qa_ask(req: AskQuestion, request: Request):
    from data.db_policy import ask_question
    u = _user(request)
    r = ask_question(u.get("uid"), req.question, source=req.source, category=req.category or None)
    if r.get("matched"):
        return ok({
            "matched": True, "question_id": r.get("question_id"),
            "answer": r.get("auto_answer"), "score": r.get("score"),
            "title": (r.get("knowledge") or {}).get("title"),
        }, "已自动回答")
    # 未匹配/敏感/医疗 → 转人工提示
    return ok({
        "matched": False, "reason": r.get("reason"),
        "manual_text": r.get("manual_text", "暂未找到答案，可转人工。"),
        "expired_hint": r.get("expired_hint", ""),
    }, "未自动回答")


class TransferHuman(BaseModel):
    question: str = Field(default="")


@app.post("/api/web/qa/{qid}/transfer")
def web_qa_transfer(qid: int, req: TransferHuman, request: Request):
    from data.db_policy import transfer_to_human, get_question
    u = _user(request)
    if qid > 0:
        q = get_question(qid)
        if not q:
            return fail(1004, "提问不存在")
        if u.get("role") != "grid" and q.get("user_id") != u.get("uid"):
            return fail(1003, "无权限操作该提问")
    try:
        ok_ = transfer_to_human(qid) if qid > 0 else transfer_to_human(
            user_id=u.get("uid"), question=req.question, source="居民端")
        return ok({"question_id": qid}, "已转人工")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"转人工失败：{e}")


@app.delete("/api/web/qa/questions/{qid}")
def web_qa_question_delete(qid: int, request: Request):
    """居民删除自己的提问记录（处理中拦截由数据层校验）。"""
    from data.db_policy import delete_question, get_question
    u = _user(request)
    q = get_question(qid)
    if not q:
        return fail(1004, "提问不存在")
    if u.get("role") != "grid" and q.get("user_id") != u.get("uid"):
        return fail(1003, "无权限删除该提问")
    ok_, msg = delete_question(qid, u.get("uid"))
    if not ok_:
        return fail(2001, msg or "删除失败")
    return ok({"question_id": qid}, "已删除")


@app.get("/api/web/qa/questions")
def web_qa_questions(request: Request, status: str = "", limit: int = 50):
    from data.db_policy import get_questions, get_question_deadline_info
    u = _user(request)
    if u.get("role") == "grid":
        rows = get_questions(status=status or None, limit=limit)
    else:
        rows = get_questions(user_id=u.get("uid"), limit=limit)
    out = []
    for r in rows:
        v = dict(r)
        # 脱敏昵称（居民+后4位 / 老人+后4位）
        if u.get("role") == "grid":
            try:
                from data.db_policy import masked_nickname
                v["nickname_masked"] = masked_nickname(v.get("user_id") or 0, "老人" if v.get("source") == "老年端" else "居民")
            except Exception:
                v["nickname_masked"] = v.get("nickname") or ""
        if u.get("role") == "grid" and v.get("status") in ("待人工回复", "处理中", "已转人工", "超时未回复"):
            try:
                deadline = get_question_deadline_info(r["id"])
                v.update(deadline or {})
            except Exception:
                pass
        out.append(v)
    return ok(out)


@app.get("/api/web/knowledge")
def web_knowledge_list(request: Request, category: str = "", limit: int = 50):
    from data.db_policy import get_knowledge_list
    u = _user(request)
    status = None if u.get("role") == "grid" else "已发布"
    rows = get_knowledge_list(status=status, category=category or None, limit=limit)
    return ok([{
        "id": k.get("id"), "title": k.get("title"), "category": k.get("category"),
        "plain_interpretation": k.get("plain_interpretation"), "summary": k.get("summary"),
        "status": k.get("audit_status"), "updated_at": k.get("updated_at") or k.get("created_at"),
        "attachment": k.get("attachment"),
        "audit_opinion": k.get("audit_opinion") or "",
        "auditor": k.get("auditor") or "",
        "version": k.get("version") or 1,
    } for k in rows])


@app.get("/api/web/qa/high-freq")
def web_qa_high_freq(request: Request, limit: int = 10):
    from data.db_policy import get_common_questions
    return ok(get_common_questions(limit=limit))




# ---------------- 补充端点：详情 / 内容 CRUD / 提问回复 / 老年端闭环 ----------------

@app.get("/api/web/proposals/{pid}")
def web_proposal_detail(pid: int, request: Request):
    from data.db_proposal import get_proposal, get_proposal_vote_stats, get_proposal_timeline
    u = _user(request)
    p = get_proposal(pid)
    if not p:
        return fail(1004, "提案不存在")
    # 居民：只能看自己提交的（含私有/待审核）+ 公开公示链上的提案，隐藏敏感字段
    if u.get("role") != "grid":
        mine = p.get("reporter_id") == u.get("uid")
        if not mine:
            if not p.get("is_public") or p.get("status") not in (
                "公示中", "待执行", "执行中", "待提案人反馈", "重新执行", "已完成"
            ):
                return fail(1003, "无权限查看该提案")
    stats = get_proposal_vote_stats(pid) or {}
    out = dict(p)
    # 当前用户是否已投票（居民/负责人匿名一票制）
    try:
        from data.db_proposal import has_voted
        out["has_voted"] = bool(has_voted(pid, u.get("uid")))
    except Exception:
        out["has_voted"] = False
    if u.get("role") != "grid":
        mine = p.get("reporter_id") == u.get("uid")
        out["mine"] = bool(mine)
        if not mine:
            out.pop("reporter_phone", None)
            out["reporter_name"] = ((p.get("reporter_name") or "")[:1] + "**") if p.get("reporter_name") else "—"
            # 附件公开且审核通过（公示链）→ 其他居民公示期可见
            if p.get("attachment_public") and p.get("status") in (
                "公示中", "待执行", "执行中", "待提案人反馈", "重新执行", "已完成"
            ):
                pass
            else:
                out.pop("attachment", None)
    out["vote_stats"] = stats
    try:
        out["timeline"] = get_proposal_timeline(pid, limit=20)
    except Exception:
        out["timeline"] = []
    return ok(out)


@app.get("/api/web/notices/{nid}")
def web_notice_detail(nid: int, request: Request):
    from data.db_notice import get_notice, get_notice_read_stats
    u = _user(request)
    n = get_notice(nid)
    if not n:
        return fail(1004, "通知不存在")
    # 范围过滤：居民/老年只能看本端可见通知
    if u.get("role") != "grid":
        try:
            from data.db_notice import get_visible_notices
            visible = get_visible_notices("elderly" if u.get("role") == "elderly" else "resident",
                                          u.get("uid"), limit=500)
            if not any(v.get("id") == nid for v in visible):
                return fail(1003, "无权限查看该通知")
        except Exception:
            pass
        n.pop("publisher", None)
        n.pop("scope_target_json", None)
    out = dict(n)
    if u.get("role") == "grid":
        out["read_stats"] = get_notice_read_stats(nid)
        try:
            from data.db_notice import get_notice_timeline
            out["timeline"] = get_notice_timeline(nid)
        except Exception:
            out["timeline"] = []
    return ok(out)


# ---- 健康内容管理（创建/审核/下架） ----

class HealthArticleCreate(BaseModel):
    title: str = Field(..., min_length=2)
    content_type: str = Field(default="健康知识")
    body: str = Field(default="")
    summary: str = Field(default="")
    source: str = Field(default="社区整理")
    is_pinned: int = Field(default=0)
    expire_at: str = Field(default="")
    info_updated_at: str = Field(default="")
    weather_link_json: str = Field(default="[]")
    elderly_reminder_text: str = Field(default="")


@app.post("/api/web/health/articles")
def web_health_article_create(req: HealthArticleCreate, request: Request):
    from data.db_health_content import create_content, submit_for_review
    from ui.cache import invalidate_health
    actor = _user(request).get("name") or "负责人"
    try:
        weather_links = json.loads(req.weather_link_json or "[]") if req.weather_link_json else []
    except (ValueError, TypeError):
        weather_links = []
    cid, err = create_content(
        title=req.title, content_type=req.content_type, body=req.body,
        source=req.source, publisher=actor, is_pinned=req.is_pinned,
        expire_at=req.expire_at, info_updated_at=req.info_updated_at,
        weather_link=weather_links,
        elderly_reminder_text=req.elderly_reminder_text,
    )
    if cid <= 0:
        return fail(2001, err or "创建失败")
    # 发布人不能同时是审核人，用「社区审核组」作为默认审核人
    submit_for_review(cid, auditor="社区审核组", actor=actor)
    invalidate_health()
    return ok({"content_id": cid}, "已创建并提交审核")


class HealthArticleAction(BaseModel):
    action: str = Field(..., pattern="^(audit|offline|withdraw|delete|pin|unpin)$")
    approve: bool = Field(default=True)
    opinion: str = Field(default="")
    reason: str = Field(default="")


@app.post("/api/web/health/articles/{cid}/action")
def web_health_article_action(cid: int, req: HealthArticleAction, request: Request):
    from data.db_health_content import (
        review_content, take_down_content, withdraw_submission, delete_draft,
        set_pinned, is_disease_prevention_manager,
    )
    from ui.cache import invalidate_health
    # 权限：内容审核仅疾病预防负责人（方案权限矩阵）
    if not is_disease_prevention_manager(_user(request)):
        return fail(1003, "无权限：仅疾病预防负责人可管理健康内容")
    actor = _user(request).get("name") or "负责人"
    if req.action == "audit":
        # 提交时审核人为「社区审核组」，审核必须同名（单负责人演示环境统一用该标识）
        ok_, msg = review_content(cid, req.approve, opinion=req.opinion, actor="社区审核组")
    elif req.action == "offline":
        ok_, msg = take_down_content(cid, req.reason, confirm=True, actor=actor)
    elif req.action == "withdraw":
        ok_, msg = withdraw_submission(cid, actor=actor)
    elif req.action == "delete":
        ok_, msg = delete_draft(cid, actor=actor)
    elif req.action == "pin":
        ok_, msg = set_pinned(cid, True, actor=actor)
    elif req.action == "unpin":
        ok_, msg = set_pinned(cid, False, actor=actor)
    else:
        return fail(1001, "不支持的操作")
    if not ok_:
        return fail(2001, msg)
    invalidate_health()
    return ok({"content_id": cid}, "操作成功")


# ---- 健康咨询：未读徽标 / 天气联动 / 阈值配置 ----

@app.get("/api/web/health/unread-reply-count")
def web_health_unread(request: Request):
    """我的咨询未读回复数量（居民端徽标）。"""
    from data.db_health_content import get_unread_reply_count
    u = _user(request)
    return ok({"count": get_unread_reply_count(u.get("uid"))})


@app.get("/api/web/health/linkage/records")
def web_health_linkage_records(request: Request, limit: int = 50):
    """天气联动触发记录（负责人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import get_linkage_records
    return ok(get_linkage_records(limit=limit))


@app.get("/api/web/health/linkage/active")
def web_health_linkage_active(request: Request, limit: int = 3):
    """居民端当前生效的天气联动提醒（当天触发，最多 3 条，其余折叠）。"""
    from data.db_core import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE module='疾病预防' AND target_type='weather_linkage' "
            "AND action='联动提醒触发' AND date(created_at, 'localtime')=date('now','localtime') "
            "ORDER BY id DESC LIMIT ?", (limit,),
        ).fetchall()
        return ok([{
            "content_id": r["target_id"], "title": r["target_title"] or "",
            "detail": r["detail"] or "", "created_at": r["created_at"],
        } for r in rows])


@app.get("/api/web/health/linkage/thresholds")
def web_health_linkage_thresholds_get(request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import get_linkage_thresholds
    return ok(get_linkage_thresholds())


class LinkageThresholdsSet(BaseModel):
    high_temp: int | None = Field(default=None)
    low_temp: int | None = Field(default=None)
    temp_drop: int | None = Field(default=None)


@app.post("/api/web/health/linkage/thresholds")
def web_health_linkage_thresholds_set(req: LinkageThresholdsSet, request: Request):
    """天气联动阈值配置（仅疾病预防负责人，立即生效留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import set_linkage_thresholds
    actor = _user(request).get("name") or "负责人"
    r = set_linkage_thresholds(high_temp=req.high_temp, low_temp=req.low_temp,
                               temp_drop=req.temp_drop, actor=actor)
    return ok(r, "阈值已更新")


class LinkageAction(BaseModel):
    action: str = Field(..., pattern="^(close|reopen)$")
    reason: str = Field(default="")


@app.post("/api/web/health/linkage/{link_key}/action")
def web_health_linkage_action(link_key: str, req: LinkageAction, request: Request):
    """联动关闭/重新开启（二次确认留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import close_linkage, reopen_linkage
    actor = _user(request).get("name") or "负责人"
    if req.action == "close":
        ok_, msg = close_linkage(link_key, req.reason or "演示关闭", actor=actor, confirm=True)
    elif req.action == "reopen":
        ok_, msg = reopen_linkage(link_key, actor=actor, confirm=True)
    else:
        return fail(1001, "不支持的操作")
    if not ok_:
        return fail(2001, msg)
    return ok({"link_key": link_key}, "操作成功")


# ---- 咨询详情 / 居民反馈 ----

@app.get("/api/web/health/consults/{cid}")
def web_consult_detail(cid: int, request: Request):
    from data.db_health_content import get_consult
    u = _user(request)
    c = get_consult(cid)
    if not c:
        return fail(1004, "咨询不存在")
    # 权限：居民只能看自己的咨询；负责人可看全部
    if u.get("role") != "grid" and c.get("user_id") != u.get("uid"):
        return fail(1003, "无权限查看该咨询")
    out = dict(c)
    if u.get("role") != "grid" and out.get("phone"):
        out["phone"] = out["phone"][:3] + "****" + out["phone"][-4:]
    return ok(out)


class ConsultFeedback(BaseModel):
    solved: bool = Field(default=True)
    reason: str = Field(default="")


@app.post("/api/web/health/consults/{cid}/feedback")
def web_consult_feedback(cid: int, req: ConsultFeedback, request: Request):
    from data.db_health_content import feedback_consult
    from ui.cache import invalidate_health
    u = _user(request)
    ok_, msg = feedback_consult(cid, u.get("uid"), req.solved, reason=req.reason)
    if not ok_:
        return fail(2001, msg)
    invalidate_health()
    return ok({"consult_id": cid}, "反馈已提交")


class ConsultToggle(BaseModel):
    action: str = Field(..., pattern="^(withdraw|reopen|close)$")
    content: str = Field(default="")


@app.post("/api/web/health/consults/{cid}/toggle")
def web_consult_toggle(cid: int, req: ConsultToggle, request: Request):
    """咨询撤回/重新打开/关闭（居民本人）。"""
    from data.db_health_content import withdraw_consult, reopen_consult, close_consult
    from ui.cache import invalidate_health
    u = _user(request)
    uid = u.get("uid")
    if req.action == "withdraw":
        ok_, msg = withdraw_consult(cid, uid)
    elif req.action == "reopen":
        ok_, msg = reopen_consult(cid, uid, content=req.content)
    else:
        ok_, msg = close_consult(cid, uid)
    if not ok_:
        return fail(2001, msg)
    invalidate_health()
    return ok({"consult_id": cid}, "操作成功")


# ---- 站内消息中心（通知/工单/提案等系统消息） ----

@app.get("/api/web/messages")
def web_messages(request: Request, limit: int = 50):
    """当前用户站内消息（type=notification/issue/sos/policy 等）。"""
    from data.db_core import get_db
    u = _user(request)
    uid = u.get("uid")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, ntype, title, content, is_read, related_id, created_at "
            "FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
    return ok([dict(r) for r in rows])


@app.post("/api/web/messages/{mid}/read")
def web_message_read(mid: int, request: Request):
    """标记消息已读。"""
    from data.db_core import get_db
    u = _user(request)
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (mid, u.get("uid")))
        conn.commit()
    return ok({"message_id": mid}, "已读")


# ---- 政策知识库管理（创建/审核/下架） ----

class KnowledgeCreate(BaseModel):
    title: str = Field(..., min_length=2)
    category: str = Field(default="社保医保")
    plain_interpretation: str = Field(..., min_length=2)
    content: str = Field(default="")
    summary: str = Field(default="")
    source: str = Field(default="社区整理")
    keywords: str = Field(default="")
    effective_date: str = Field(default="")
    expire_date: str = Field(default="")
    policy_number: str = Field(default="")
    attachment: str = Field(default="")


@app.post("/api/web/knowledge")
def web_knowledge_create(req: KnowledgeCreate, request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import create_knowledge, submit_review
    from ui.cache import invalidate_knowledge
    actor = _user(request).get("name") or "负责人"
    kid, err = create_knowledge(
        title=req.title, category=req.category, plain_interpretation=req.plain_interpretation,
        content=req.content, summary=req.summary, source=req.source,
        keywords=req.keywords, effective_date=req.effective_date,
        expire_date=req.expire_date, policy_number=req.policy_number,
        attachment=req.attachment, actor=actor,
    )
    if kid <= 0:
        return fail(2001, err or "创建失败")
    submit_review(kid, auditor="社区审核组", actor=actor)
    invalidate_knowledge()
    return ok({"knowledge_id": kid}, "已创建并提交审核")


class KnowledgeAction(BaseModel):
    action: str = Field(..., pattern="^(audit|offline|withdraw|delete)$")
    approve: bool = Field(default=True)
    opinion: str = Field(default="")
    reason: str = Field(default="")


@app.post("/api/web/knowledge/{kid}/action")
def web_knowledge_action(kid: int, req: KnowledgeAction, request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import audit_knowledge, take_down_knowledge, withdraw_review, delete_knowledge
    from ui.cache import invalidate_knowledge
    actor = _user(request).get("name") or "负责人"
    if req.action == "audit":
        # 发布人不能审核自己发布的内容，审核统一走「社区审核组」身份
        ok_, msg = audit_knowledge(kid, req.approve, opinion=req.opinion, actor="社区审核组")
    elif req.action == "offline":
        ok_, msg = take_down_knowledge(kid, req.reason, actor=actor)
    elif req.action == "withdraw":
        ok_, msg = withdraw_review(kid, actor=actor)
    elif req.action == "delete":
        ok_, msg = delete_knowledge(kid, actor=actor)
    else:
        return fail(1001, "不支持的操作")
    if not ok_:
        return fail(2001, msg)
    invalidate_knowledge()
    return ok({"knowledge_id": kid}, "操作成功")


@app.get("/api/web/knowledge/{kid}/versions")
def web_knowledge_versions(kid: int, request: Request):
    """版本历史（负责人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import get_version_history
    return ok(get_version_history(kid))


@app.post("/api/web/knowledge/{kid}/new-version")
def web_knowledge_new_version(kid: int, req: KnowledgeCreate, request: Request):
    """已发布条目创建新版本（提交审核，审核通过自动替换旧版）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import create_new_version, submit_review
    from ui.cache import invalidate_knowledge
    actor = _user(request).get("name") or "负责人"
    nid, err = create_new_version(
        kid, title=req.title, category=req.category,
        plain_interpretation=req.plain_interpretation, source=req.source,
        keywords=req.keywords, effective_date=req.effective_date,
        content=req.content, summary=req.summary, expire_date=req.expire_date,
        policy_number=req.policy_number, attachment=req.attachment,
        actor=actor, auditor="社区审核组",
    )
    if nid <= 0:
        return fail(2001, err or "创建版本失败")
    submit_review(nid, auditor="社区审核组", actor=actor)
    invalidate_knowledge()
    return ok({"knowledge_id": nid}, "新版本已创建并提交审核")


# ---- 提问人工回复 / 居民反馈 ----

class QaReply(BaseModel):
    reply: str = Field(..., min_length=1)


@app.post("/api/web/qa/questions/{qid}/reply")
def web_qa_reply(qid: int, req: QaReply, request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import reply_question
    actor = _user(request).get("name") or "负责人"
    ok_, msg, _ = reply_question(qid, req.reply, actor=actor)
    if not ok_:
        return fail(2001, msg)
    return ok({"question_id": qid}, "已回复")


class QaFeedback(BaseModel):
    satisfied: bool = Field(default=True)
    reason: str = Field(default="")


@app.post("/api/web/qa/questions/{qid}/feedback")
def web_qa_feedback(qid: int, req: QaFeedback, request: Request):
    from data.db_policy import feedback_question, get_question
    u = _user(request)
    q = get_question(qid)
    if not q:
        return fail(1004, "提问不存在")
    if u.get("role") != "grid" and q.get("user_id") != u.get("uid"):
        return fail(1003, "无权限反馈该提问")
    ok_, msg, _ = feedback_question(qid, req.satisfied, reason=req.reason, actor=u.get("name") or "居民")
    if not ok_:
        return fail(2001, msg)
    return ok({"question_id": qid}, "反馈已提交")


# ---------------- 导出（复用数据层导出函数，统一 CSV） ----------------

@app.get("/api/web/export/issues")
def web_export_issues(request: Request):
    """导出报修工单 CSV（负责人，脱敏，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_repair import get_issues
    import csv
    from io import StringIO
    rows = get_issues(limit=1000)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["编号", "标题", "分类", "类型", "紧急度", "状态", "地址", "报修人", "电话", "维修人员", "提交时间"])
    for r in rows:
        p = r.get("reporter_phone") or ""
        w.writerow([r.get("id"), r.get("title"), r.get("category"), r.get("issue_type"),
                    r.get("urgency"), r.get("status"), r.get("location"),
                    r.get("reporter_name"), (p[:3] + "****" + p[-4:]) if len(p) == 11 else "****",
                    r.get("assignee_name") or "", (r.get("reported_at") or "")[:16]])
    from data.db_notifications import log_activity
    log_activity(_user(request).get("name") or "负责人", "导出工单数据", module="报修",
                 detail=f"导出 {len(rows)} 条（脱敏，不含照片附件）")
    from fastapi.responses import Response
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=issues.csv"})


@app.get("/api/web/export/proposals")
def web_export_proposals(request: Request):
    """导出提案 CSV（负责人，含排名/脱敏，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_proposal import get_export_rows, log_export
    rows = get_export_rows()
    import csv
    from io import StringIO
    buf = StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    log_export(actor=_user(request).get("name") or "负责人")
    from fastapi.responses import Response
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=proposals.csv"})


@app.get("/api/web/export/notices")
def web_export_notices(request: Request):
    """导出通知列表 + 已读统计（负责人，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_notice import export_notices_csv
    from fastapi.responses import Response
    content, fname = export_notices_csv(actor=_user(request).get("name") or "负责人")
    return Response(content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/api/web/export/knowledge")
def web_export_knowledge(request: Request):
    """导出政策知识库 CSV（负责人，脱敏留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import get_knowledge_list
    import csv
    from io import StringIO
    rows = get_knowledge_list(limit=1000)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "标题", "分类", "状态", "版本", "有效期", "引用次数", "更新时间"])
    for k in rows:
        w.writerow([k.get("id"), (k.get("title") or "")[:40], k.get("category"),
                    k.get("audit_status"), k.get("version") or 1,
                    f"{k.get('effective_date') or ''}~{k.get('expire_date') or ''}",
                    k.get("cite_count") or 0, (k.get("updated_at") or k.get("created_at") or "")[:16]])
    from data.db_notifications import log_activity
    log_activity(_user(request).get("name") or "负责人", "导出知识库", module="政策问答",
                 detail=f"导出 {len(rows)} 条（不含正文全文与审核意见）")
    from fastapi.responses import Response
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=knowledge.csv"})


@app.get("/api/web/export/health-contents")
def web_export_health_contents(request: Request):
    """导出健康内容 CSV（负责人，脱敏留痕，不含附件与内部备注）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import export_contents_csv
    from fastapi.responses import Response
    content, fname = export_contents_csv(actor=_user(request).get("name") or "负责人")
    return Response(content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/api/web/export/health-consults")
def web_export_health_consults(request: Request):
    """导出健康咨询 CSV（负责人，电话脱敏留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import export_consults_csv
    from fastapi.responses import Response
    content, fname = export_consults_csv(actor=_user(request).get("name") or "负责人")
    return Response(content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@app.get("/api/web/export/weather-tasks")
def web_export_weather_tasks(request: Request):
    """导出天气检查任务记录 CSV（负责人，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_weather import list_check_tasks
    from data.db_notifications import log_activity
    import csv
    from io import StringIO
    rows = list_check_tasks(limit=1000)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["编号", "预警类型", "等级", "状态", "确认人", "备注", "检查时间", "创建时间"])
    for r in rows:
        w.writerow([r.get("id"), r.get("alert_type"), r.get("level"), r.get("status"),
                    r.get("checker") or "", r.get("note") or "",
                    (r.get("checked_at") or "")[:16], (r.get("created_at") or "")[:16]])
    log_activity(_user(request).get("name") or "负责人", "导出天气检查任务",
                 module="天气", detail=f"导出 {len(rows)} 条检查任务记录")
    from fastapi.responses import Response
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=weather-tasks.csv"})


# ---------------- 老年关怀管理（负责人端：用药审核 / 联系人审核 / SOS 响应） ----------------

@app.get("/api/web/elderly/manage/medications")
def web_manage_medications(request: Request, status: str = ""):
    """负责人端用药提醒列表（全部老人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import list_medication_reminders
    rows = list_medication_reminders(status=status or None)
    return ok([dict(r) for r in rows])


class MedicationAudit(BaseModel):
    approve: bool = Field(default=True)
    opinion: str = Field(default="")


@app.post("/api/web/elderly/manage/medications/{rid}/audit")
def web_manage_medication_audit(rid: int, req: MedicationAudit, request: Request):
    """负责人审核用药提醒。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import audit_medication
    actor = _user(request).get("name") or "负责人"
    ok_, msg = audit_medication(rid, req.approve, opinion=req.opinion, actor=actor)
    if not ok_:
        return fail(2001, msg)
    return ok({"reminder_id": rid}, "审核完成")


@app.get("/api/web/elderly/manage/contacts")
def web_manage_contacts(request: Request, status: str = ""):
    """负责人端紧急联系人列表（全部老人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import list_emergency_contacts
    rows = list_emergency_contacts()
    out = [dict(r) for r in rows]
    if status:
        out = [c for c in out if c.get("status") == status]
    return ok(out)


class ContactAudit(BaseModel):
    approve: bool = Field(default=True)
    opinion: str = Field(default="")


@app.post("/api/web/elderly/manage/contacts/{cid}/audit")
def web_manage_contact_audit(cid: int, req: ContactAudit, request: Request):
    """负责人审核紧急联系人。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import audit_emergency_contact
    actor = _user(request).get("name") or "负责人"
    ok_, msg = audit_emergency_contact(cid, req.approve, opinion=req.opinion, actor=actor)
    if not ok_:
        return fail(2001, msg)
    return ok({"contact_id": cid}, "审核完成")


@app.get("/api/web/elderly/manage/sos")
def web_manage_sos(request: Request, status: str = ""):
    """负责人端紧急求助列表。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import get_sos_calls
    rows = get_sos_calls(status=status or None, limit=50)
    return ok([dict(r) for r in rows])


# ---------------- 天气历史 / 社区概况 ----------------

@app.get("/api/web/weather/history")
def web_weather_history(request: Request, status: str = "", limit: int = 200):
    """负责人端天气检查任务历史。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_weather import get_check_task_history
    rows = get_check_task_history(status=status or None, limit=limit)
    return ok([dict(r) for r in rows])


@app.get("/api/web/weather/overview")
def web_weather_overview(request: Request, limit: int = 50):
    """负责人端所有社区天气概况。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_weather import get_community_weather_overview
    return ok(get_community_weather_overview(limit=limit))


@app.get("/api/web/weather/exception-logs")
def web_weather_exception_logs(request: Request, limit: int = 100):
    """负责人端异常日志（天气等系统异常单独记录 7 天）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_core import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, created_at, module, error, detail FROM exception_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return ok([dict(r) for r in rows])


# ---------------- 政策统计 / 匹配阈值 ----------------

@app.get("/api/web/qa/stats")
def web_qa_stats(request: Request, days: int = 0):
    """负责人端高频统计（匹配失败/无帮助分类）；days=0 全部，7 近 7 天，30 近 30 天。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import get_frequency_stats
    return ok(get_frequency_stats(days=days or None))


class ThresholdSet(BaseModel):
    threshold: float = Field(..., ge=0.1, le=5.0)


@app.get("/api/web/qa/threshold")
def web_qa_threshold_get(request: Request):
    from data.db_policy import get_match_threshold
    return ok({"threshold": get_match_threshold()})


@app.post("/api/web/qa/threshold")
def web_qa_threshold_set(req: ThresholdSet, request: Request):
    """匹配阈值配置（仅负责人，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import set_match_threshold
    set_match_threshold(req.threshold, actor=_user(request).get("name") or "负责人")
    return ok({"threshold": req.threshold}, "阈值已更新")


# ---- 老年端补充：联系人 / SOS 响应结束 / 用药暂停恢复 / 联系拨打 ----

class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=11)
    relation: str = Field(default="家属")


@app.get("/api/web/elderly/emergency-contacts")
def web_contacts_list(request: Request):
    from data.db_elderly_care import list_emergency_contacts
    u = _user(request)
    return ok([dict(r) for r in list_emergency_contacts(u.get("uid"))])


@app.post("/api/web/elderly/emergency-contacts")
def web_contacts_create(req: ContactCreate, request: Request):
    from data.db_elderly_care import add_emergency_contact
    u = _user(request)
    cid, msg = add_emergency_contact(u.get("uid"), req.name, req.phone, req.relation,
                                     actor=u.get("name") or "老人")
    if cid <= 0:
        return fail(2001, msg)
    return ok({"contact_id": cid}, "已提交，待审核")


@app.post("/api/web/elderly/emergency-contacts/{cid}/delete")
def web_contacts_delete(cid: int, request: Request):
    from data.db_elderly_care import delete_emergency_contact
    u = _user(request)
    ok_, msg = delete_emergency_contact(cid, actor=u.get("name") or "老人")
    if not ok_:
        return fail(2001, msg)
    return ok({"contact_id": cid}, "已删除")


class SosAction(BaseModel):
    action: str = Field(..., pattern="^(respond|close)$")
    handle_note: str = Field(default="")


@app.post("/api/web/elderly/emergency/{call_id}/action")
def web_sos_action(call_id: int, req: SosAction, request: Request):
    from data.db_elderly_care import respond_sos, end_sos
    actor = _user(request).get("name") or "负责人"
    if req.action == "respond":
        ok_, msg = respond_sos(call_id, actor=actor)
    else:
        ok_, msg = end_sos(call_id, req.handle_note, actor=actor)
    if not ok_:
        return fail(2001, msg)
    return ok({"call_id": call_id}, "操作成功")


class MedicationToggle(BaseModel):
    action: str = Field(..., pattern="^(pause|resume)$")


@app.post("/api/web/elderly/medications/{rid}/toggle")
def web_medication_toggle(rid: int, req: MedicationToggle, request: Request):
    from data.db_elderly_care import pause_medication, resume_medication
    actor = _user(request).get("name") or "老人"
    if req.action == "pause":
        ok_, msg = pause_medication(rid, actor=actor)
    else:
        ok_, msg = resume_medication(rid, actor=actor)
    if not ok_:
        return fail(2001, msg)
    return ok({"reminder_id": rid}, "操作成功")


class ContactCall(BaseModel):
    target_name: str = Field(default="")
    target_phone: str = Field(default="")


@app.post("/api/web/elderly/contact")
def web_elderly_contact(req: ContactCall, request: Request):
    """联系家属/社区（拨号留痕）。"""
    from data.db_elderly_care import log_emergency_call
    u = _user(request)
    try:
        log_emergency_call(u.get("uid"), "contact", req.target_name, req.target_phone,
                           "拨出", status="已结束", actor=u.get("name") or "老人")
        return ok({"dialed": req.target_name or req.target_phone}, "已记录拨打")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"拨打记录失败：{e}")


# ---- 天气预报独立端点 ----

@app.get("/api/web/weather/forecast")
def web_weather_forecast(request: Request, days: int = 3):
    from data.db_weather import get_weather_for_display
    w = get_weather_for_display("")
    return ok({"forecast": (w.get("days") or [])[:days], "is_degraded": w.get("is_degraded")})


# ---------------- 老年端免登录（elder_id 参数 + 绑定校验） ----------------
# 使用方式：token 为绑定家属的居民，请求 /api/web/elderly/*?elder_id=X 时以老人身份操作。
# 在 JWT 中间件中处理：见下方 hook —— 由端点内的 _resolve_elder_uid 使用。

def _resolve_elder_uid(request: Request) -> int | None:
    """老年端免登录：?elder_id=X 且当前 token 用户是该老人的绑定家属 → 返回老人 uid。"""
    u = _user(request)
    uid = u.get("uid")
    elder_id = request.query_params.get("elder_id")
    if not elder_id or not str(elder_id).isdigit():
        return None
    elder_id = int(elder_id)
    if u.get("role") == "elderly" and elder_id == uid:
        return uid
    try:
        from data.db_user import get_bound_elderly
        bound = get_bound_elderly(uid)
        if bound and bound.get("id") == elder_id:
            return elder_id
    except Exception:
        pass
    return None




@app.get("/api/web/weather/current")
def web_weather_current(request: Request):
    from data.db_weather import get_weather_for_display, get_daily_advice
    from config import COMMUNITY_CITY, COMMUNITY_DISTRICT
    w = get_weather_for_display("")
    days = w.get("days") or []
    today = days[0] if days else {}
    advice = {}
    try:
        advice = get_daily_advice(city="") or {}
    except Exception:
        pass
    return ok({
        "location": COMMUNITY_CITY + COMMUNITY_DISTRICT,
        "temp_high": today.get("temp_high"), "temp_low": today.get("temp_low"),
        "condition": today.get("condition"), "emoji": today.get("emoji"),
        "wind": today.get("wind"), "rain_prob": today.get("rain_prob"),
        "humidity": today.get("humidity"), "aqi": today.get("aqi"), "uv": today.get("uv"),
        "advice": today.get("advice"),
        "dress": advice.get("dress", ""), "travel": advice.get("travel", ""),
        "updated_at": w.get("data_updated_at") or "",
        "forecast": days[1:4],
        "is_degraded": w.get("is_degraded"), "note": w.get("note", ""),
    })


@app.get("/api/web/weather/alerts")
def web_weather_alerts(request: Request):
    from ui.cache import cached_active_alerts
    return ok(cached_active_alerts())


class CheckTaskConfirm(BaseModel):
    checker: str = Field(default="")
    items: list = Field(default_factory=list)
    note: str = Field(default="")


@app.post("/api/web/weather/check-task/{task_id}/confirm")
def web_check_task_confirm(task_id: int, req: CheckTaskConfirm, request: Request):
    from data.db_weather import confirm_check_task, fill_overdue_task
    from data.db_weather import list_check_tasks
    from ui.cache import invalidate_weather
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    actor = _user(request).get("name") or "负责人"
    rows = list_check_tasks(limit=1000)
    row = next((t for t in rows if t["id"] == task_id), None)
    if not row:
        return fail(1004, "检查任务不存在")
    if row["status"] == "待检查":
        ok_, msg = confirm_check_task(task_id, req.checker or actor, req.items, req.note, actor=actor)
    elif row["status"] == "超时未确认":
        ok_, msg = fill_overdue_task(task_id, req.checker or actor, req.items, req.note, actor=actor)
    else:
        return fail(2001, f"当前状态「{row['status']}」不支持确认")
    if not ok_:
        return fail(2001, msg)
    invalidate_weather()
    return ok({"task_id": task_id}, "已确认")


@app.get("/api/web/weather/tasks")
def web_weather_tasks(request: Request, status: str = ""):
    from data.db_weather import list_check_tasks
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    rows = list_check_tasks(status=status or None, limit=200)
    return ok([dict(r) for r in rows])


# ---------------- 健康（复用 db_health_content） ----------------

@app.get("/api/web/health/articles")
def web_health_articles(request: Request, status: str = "", content_type: str = "", keyword: str = ""):
    from data.db_health_content import list_contents, get_published_contents
    u = _user(request)
    if u.get("role") == "grid":
        rows = list_contents(status=status or None, content_type=content_type or None,
                             keyword=keyword or None, limit=100)
    else:
        rows = get_published_contents(content_type=content_type or None, limit=50)
    return ok([{
        "id": c.get("id"), "title": c.get("title"), "content_type": c.get("content_type"),
        "summary": c.get("summary"), "status": c.get("status"),
        "source": c.get("source"), "expire_at": c.get("expire_at"),
        "is_pinned": c.get("is_pinned") or 0,
        "pinned_at": c.get("pinned_at"), "created_at": c.get("created_at"),
        "published_at": c.get("published_at"), "updated_at": c.get("updated_at"),
        "info_updated_at": c.get("info_updated_at") or "",
    } for c in rows])


@app.get("/api/web/health/articles/{cid}")
def web_health_article_detail(cid: int, request: Request):
    """健康内容详情（居民仅已发布；负责人全量含审核意见）。"""
    from data.db_health_content import get_content
    u = _user(request)
    c = get_content(cid)
    if not c:
        return fail(1004, "内容不存在")
    if u.get("role") != "grid" and c.get("status") != "已发布":
        return fail(1003, "无权限查看该内容")
    return ok(dict(c))


class ConsultCreate(BaseModel):
    name: str = Field(default="")
    phone: str = Field(default="")
    consult_type: str = Field(default="健康知识")
    content: str = Field(..., min_length=5)
    building: str = Field(default="")
    attachment_json: str = Field(default="[]")
    is_agent_report: int = Field(default=0)
    agent_name: str = Field(default="")
    agent_phone: str = Field(default="")
    agent_relation: str = Field(default="")


@app.post("/api/web/health/consults")
def web_consult_create(req: ConsultCreate, request: Request):
    from data.db_health_content import submit_consult, log_emergency_hint_shown
    from ui.cache import invalidate_health
    u = _user(request)
    # 提交前紧急提示已展示（120 急救提示，留痕）
    try:
        log_emergency_hint_shown(u.get("uid"))
    except Exception:
        pass
    cid, msg, code = submit_consult(
        u.get("uid"), req.name or u.get("name") or "居民", req.phone,
        req.consult_type, req.content, building=req.building,
        attachment_json=req.attachment_json,
        is_agent_report=req.is_agent_report, agent_name=req.agent_name,
        agent_phone=req.agent_phone, agent_relation=req.agent_relation,
    )
    if cid <= 0:
        return fail(2001, msg or "提交失败")
    invalidate_health()
    return ok({"consult_id": cid, "code": code}, "提交成功")


@app.get("/api/web/health/consults")
def web_consult_list(request: Request, status: str = "", consult_type: str = "", keyword: str = ""):
    from data.db_health_content import get_my_consults, list_consults
    u = _user(request)
    if u.get("role") == "grid":
        rows = list_consults(status=status or None, consult_type=consult_type or None,
                             keyword=keyword or None, limit=100)
    else:
        rows = get_my_consults(u.get("uid"), limit=50)
    out = []
    for r in rows:
        v = dict(r)
        if u.get("role") == "grid":
            # 负责人列表：电话脱敏展示
            v["phone"] = v.get("phone_masked") or v.get("phone", "")
        out.append(v)
    return ok(out)


class ConsultReply(BaseModel):
    reply: str = Field(..., min_length=1)
    doctor_guide: str = Field(default="")
    need_offline: bool = Field(default=False)
    offline_confirmed: bool = Field(default=False)


@app.post("/api/web/health/consults/{cid}/reply")
def web_consult_reply(cid: int, req: ConsultReply, request: Request):
    from data.db_health_content import reply_consult, is_disease_prevention_manager
    from ui.cache import invalidate_health
    # 权限：咨询处理人（疾病预防负责人自动成为处理人）
    if not is_disease_prevention_manager(_user(request)):
        return fail(1003, "无权限：仅咨询处理人可回复")
    actor = _user(request).get("name") or "负责人"
    ok_, msg = reply_consult(cid, req.reply, actor=actor, doctor_guide=req.doctor_guide,
                             need_offline=req.need_offline, offline_confirmed=req.offline_confirmed)
    if not ok_:
        return fail(2001, msg)
    invalidate_health()
    return ok({"consult_id": cid}, "已回复")


# ---------------- 老年端（复用 db_elderly_care / db_elderly） ----------------

@app.get("/api/web/elderly/home")
def web_elderly_home(request: Request):
    """老年端首页聚合：未读通知 / 天气摘要 / 用药状态 / 最近求助。"""
    from data.db_elderly import get_profile
    from data.db_notice import get_notice_unread_count
    from data.db_elderly_care import get_latest_sos
    from data.db_weather import get_simplified_weather
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    elderly = get_profile(uid) or {}
    health = elderly.get("health_info", {})
    due = 0
    try:
        from data.db_elderly_care import get_due_medications
        due = len(get_due_medications(uid))
    except Exception:
        pass
    return ok({
        "name": u.get("name") or "大爷/阿姨",
        "unread_notices": get_notice_unread_count("elderly", uid),
        "due_medications": due,
        "latest_sos": get_latest_sos(uid) if uid else None,
        "bp": (health.get("blood_pressure") or [{}])[-1] if health.get("blood_pressure") else {},
        "weather": get_simplified_weather(""),
        "community_phone": _COMMUNITY_PHONE,
    })


def _correct_report_text(text: str) -> str:
    """简单纠错（演示级规则）：压缩空格、合并重复标点、常见错别字替换。"""
    import re
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"([。！？!?，,\.])\1+", r"\1", t)
    t = re.sub(r"([。！？!?，,\.])(?=[^。！？!?，,\.]+[。！？!?，,\.])", r"\1", t)  # noqa: E501
    fixes = {"的的": "的", "在在": "在", "了了": "了", "楼楼": "楼", "电梯梯": "电梯",
             "报修修": "报修", "没没有": "没有", "一一起": "一起", "门门": "门", "灯灯": "灯"}
    for k, v in fixes.items():
        t = t.replace(k, v)
    return t


class VoiceReport(BaseModel):
    text: str = Field(..., min_length=2)
    urgency: str = Field(default="一般")
    issue_type: str = Field(default="室内")


@app.post("/api/web/elderly/voice-report")
def web_elderly_voice_report(req: VoiceReport, request: Request):
    """老年端语音报修（转写文本已确认，走报修状态机）。"""
    from data.db_repair import submit_issue
    from agent.helpers import extract_location
    from tools.action_report_issue import _llm_classify
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    profile = {}
    try:
        from data.db_user import get_user_by_id
        profile = get_user_by_id(uid) or {}
    except Exception:
        pass
    category, urgency = _llm_classify(req.text, "")
    loc = extract_location(req.text) or profile.get("community") or "社区"
    corrected = _correct_report_text(req.text)
    iid, hint = submit_issue(
        title=req.text[:80], category=category, issue_type=req.issue_type,
        location=loc, description=req.text, urgency=req.urgency or urgency or "一般",
        reporter_name=profile.get("name") or "老人",
        reporter_phone=profile.get("phone") or "13800000000",
        reporter_id=uid,
    )
    if iid <= 0:
        return fail(2001, hint or "上报失败")
    return ok({"issue_id": iid, "category": category, "corrected": corrected,
               "original": req.text}, "上报成功")


class MedicationCreate(BaseModel):
    drug_name: str = Field(..., min_length=1)
    dosage: str = Field(default="")
    times: str = Field(default="08:00")
    repeat_rule: str = Field(default="每天")
    start_date: str = Field(default="")
    end_date: str = Field(default="")
    note: str = Field(default="")


@app.post("/api/web/elderly/medications")
def web_medication_create(req: MedicationCreate, request: Request):
    from data.db_elderly_care import add_medication_reminder
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    times = [t.strip() for t in req.times.replace("，", ",").split(",") if t.strip()]
    mid, msg = add_medication_reminder(
        uid, u.get("name") or "老人", req.drug_name, req.dosage, times,
        repeat_rule=req.repeat_rule, start_date=req.start_date, end_date=req.end_date,
        note=req.note, setter_id=u.get("uid"), actor=u.get("name") or "老人",
    )
    if mid <= 0:
        return fail(2001, msg)
    return ok({"reminder_id": mid}, "已提交，待审核")


@app.post("/api/web/elderly/medications/{rid}/modify")
def web_medication_modify(rid: int, req: MedicationCreate, request: Request):
    """修改用药提醒 → 重新审核（审核期间原规则继续播报）。"""
    from data.db_elderly_care import modify_medication
    u = _user(request)
    times = [t.strip() for t in req.times.replace("，", ",").split(",") if t.strip()]
    ok_, msg = modify_medication(
        rid, u.get("name") or "老人", req.drug_name, req.dosage, times,
        repeat_rule=req.repeat_rule, start_date=req.start_date, end_date=req.end_date,
        note=req.note, actor=u.get("name") or "老人",
    )
    if not ok_:
        return fail(2001, msg)
    return ok({"reminder_id": rid}, "已提交修改，待重新审核")


@app.get("/api/web/elderly/medications")
def web_medication_list(request: Request):
    from data.db_elderly_care import list_medication_reminders
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    return ok([dict(r) for r in list_medication_reminders(uid)])


@app.post("/api/web/elderly/emergency")
def web_emergency_trigger(request: Request):
    """紧急求助触发（家属代操作模式由前端隐藏按钮，后端校验）。"""
    from data.db_elderly_care import trigger_sos
    from data.db_user import get_user_by_id, get_bound_elderly
    u = _user(request)
    profile = get_user_by_id(u.get("uid")) or {}
    # 家属绑定模式：禁止家属代替老人触发
    try:
        bound = get_bound_elderly(u.get("uid"))
        if bound and bound.get("id") != u.get("uid"):
            return fail(1003, "家属不能代替老人触发紧急求助")
    except Exception:
        pass
    cid, msg = trigger_sos(u.get("uid"), actor=profile.get("name") or "老人")
    if cid <= 0:
        return fail(2001, msg or "触发失败")
    return ok({"call_id": cid}, "已触发紧急求助")


@app.get("/api/web/elderly/emergency/status")
def web_emergency_status(request: Request):
    from data.db_elderly_care import get_latest_sos
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    return ok(get_latest_sos(uid))


# ---------------- Agent 统一入口模块（识别意图 → 引导补全 → 路由执行 → 返回） ----------------

class AgentChat(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)


# ---- PIPL 合规：修改密码 / 个人数据导出 / 账号注销（数据安全 v3.0） ----

class ChangePassword(BaseModel):
    old_password: str = Field(default="")
    new_password: str = Field(..., min_length=8)


@app.post("/api/web/auth/change-password")
def web_change_password(req: ChangePassword, request: Request):
    """修改密码（校验强度；演示账号居民/老人为空密码时免旧密码）。"""
    from data.db_core import get_db, _hash_password, _verify_password
    from utils.password import validate_password
    u = _user(request)
    uid = u.get("uid")
    okp, msg = validate_password(req.new_password)
    if not okp:
        return fail(2001, msg)
    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM user_profile WHERE id=?", (uid,)).fetchone()
        if row is None:
            return fail(1004, "用户不存在")
        stored = row["password_hash"] or ""
        if stored and not _verify_password(req.old_password, stored):
            return fail(1001, "原密码不正确")
        conn.execute("UPDATE user_profile SET password_hash=? WHERE id=?",
                     (_hash_password(req.new_password), uid))
        conn.commit()
    from data.db_notifications import log_activity
    log_activity(u.get("name") or "用户", "修改密码", module="安全",
                 detail=f"用户 #{uid} 修改登录密码（留痕，不含明文）")
    return ok({}, "密码已修改")


@app.get("/api/web/me/export")
def web_me_export(request: Request):
    """PIPL：导出本人数据（JSON，脱敏——不含完整手机号）。"""
    from data.db_core import get_db
    import json
    from io import StringIO
    u = _user(request)
    uid = u.get("uid")
    out = {"user_id": uid, "name": u.get("name") or "", "role": u.get("role") or ""}
    with get_db() as conn:
        for table, cols in (("community_issues", "reported_at"), ("proposals", "created_at"),
                            ("health_consults", "created_at"), ("agent_dialogs", "created_at")):
            try:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE user_id=? ORDER BY {cols} DESC LIMIT 50",
                    (uid,)).fetchall()
            except Exception:
                continue
            out[table] = [dict(r) for r in rows]
    # 脱敏：手机号打码
    def mask(obj):
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                if k == "phone" or k.endswith("_phone"):
                    v = str(obj[k] or "")
                    obj[k] = (v[:3] + "****" + v[-4:]) if len(v) == 11 else v
                elif isinstance(obj[k], (dict, list)):
                    mask(obj[k])
        elif isinstance(obj, list):
            for i in obj:
                mask(i)
    mask(out)
    from data.db_notifications import log_activity
    log_activity(u.get("name") or "用户", "导出本人数据", module="安全",
                 detail=f"用户 #{uid} 导出个人数据（脱敏）")
    from fastapi.responses import Response
    return Response(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"),
                    media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=my-data.json"})


@app.post("/api/web/me/delete")
def web_me_delete(request: Request):
    """PIPL：注销账号（匿名化个人字段 + 停用；保留必要日志）。"""
    from data.db_core import get_db
    from data.db_notifications import log_activity
    u = _user(request)
    uid = u.get("uid")
    with get_db() as conn:
        conn.execute(
            "UPDATE user_profile SET is_active=0, username='已注销用户' || id, "
            "phone='', community='', building='' WHERE id=? AND role != 'grid'",
            (uid,))
        conn.commit()
    log_activity(u.get("name") or "用户", "注销账号", module="安全",
                 detail=f"用户 #{uid} 注销（匿名化个人字段，保留日志）")
    return ok({}, "账号已注销（个人数据已匿名化，日志按法规保留）")


@app.post("/api/web/agent/chat")
def web_agent_chat(req: AgentChat, request: Request):
    """居民端 / 负责人端 Agent 对话（多 Agent 编排：接待员→业务Agent→合规审计→执行链）。"""
    from agent.orchestrator import Orchestrator
    u = _user(request)
    role = u.get("role")
    if role not in ("resident", "grid"):
        return fail(1003, "当前角色暂不支持 Agent 对话")
    try:
        # 每用户独立 Orchestrator（黑板带 session_id）
        orch = getattr(request.app.state, "_agent_orchs", None)
        if orch is None:
            orch = request.app.state._agent_orchs = {}
        key = f"{role}:{u.get('uid')}"
        if key not in orch:
            orch[key] = Orchestrator()
        out = orch[key].run(role, u.get("uid"), u.get("name") or "居民", req.text)
        return ok(out, "ok")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"服务暂时不可用，请稍后再试（{e}）")


@app.post("/api/web/agent/elderly/chat")
def web_agent_elderly_chat(req: AgentChat, request: Request):
    """老年端 Agent 对话（语音转写文本或文字输入，多 Agent 编排）。"""
    from agent.orchestrator import Orchestrator
    u = _user(request)
    role = u.get("role")
    if role not in ("elderly", "resident"):
        return fail(1003, "无权限")
    uid = _resolve_elder_uid(request) or u.get("uid")
    try:
        orch = getattr(request.app.state, "_agent_orchs", None)
        if orch is None:
            orch = request.app.state._agent_orchs = {}
        key = f"elderly:{uid}"
        if key not in orch:
            orch[key] = Orchestrator()
        out = orch[key].run("elderly", uid, u.get("name") or "老人", req.text, elder_uid=uid)
        return ok(out, "ok")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"服务暂时不可用，请稍后再试（{e}）")


@app.get("/api/web/agent/history")
def web_agent_history(request: Request):
    """居民端最近 5 条对话（可查看详情，可删除）。"""
    from data.db_agent import get_dialogs
    u = _user(request)
    return ok(get_dialogs(u.get("uid"), u.get("role") or "resident", limit=5))


@app.delete("/api/web/agent/history/{did}")
def web_agent_history_delete(did: int, request: Request):
    """居民删除自己的对话（归属校验）。"""
    from data.db_agent import delete_dialog
    u = _user(request)
    if not delete_dialog(did, u.get("uid")):
        return fail(1003, "无权限删除该记录")
    return ok({"deleted": did}, "已删除")


@app.delete("/api/web/agent/history")
def web_agent_history_clear(request: Request):
    """居民清空自己的历史对话。"""
    from data.db_agent import clear_dialogs
    u = _user(request)
    n = clear_dialogs(u.get("uid"), u.get("role") or "resident")
    return ok({"cleared": n}, "已清空")


@app.get("/api/web/agent/logs")
def web_agent_logs(request: Request, role: str = "", intent: str = "",
                   status: str = "", keyword: str = "", limit: int = 200):
    """负责人查 Agent 留痕（模块来源=Agent，可按角色/意图/状态/关键词筛选）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_agent_logs
    return ok(get_agent_logs(role=role, intent=intent, status=status,
                             keyword=keyword, limit=limit))


@app.get("/api/web/agent/handoffs")
def web_agent_handoffs(request: Request, status: str = "", limit: int = 50):
    """负责人端人工处理包列表（无缝转人工：AI 已整理上下文，可直接处理）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import list_handoffs
    return ok(list_handoffs(status=status, limit=limit))


@app.post("/api/web/agent/handoffs/{hid}/resolve")
def web_agent_handoff_resolve(hid: int, request: Request):
    """负责人处理完成（关闭人工处理包）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import resolve_handoff
    if not resolve_handoff(hid, _user(request).get("name") or "负责人"):
        return fail(2001, "处理包不存在或已处理")
    return ok({"handoff_id": hid}, "已处理完成")


@app.get("/api/web/agent/llm-usage")
def web_agent_llm_usage(request: Request, days: int = 7):
    """LLM 用量统计（P2-05：调用/token/费用/缓存命中，规则优先可验证）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_llm_usage import get_usage_summary, get_usage_trend
    return ok({
        "summary": get_usage_summary(days=days),
        "trend": get_usage_trend(days=days),
    })


@app.get("/api/web/export/agent-logs")
def web_export_agent_logs(request: Request):
    """导出 Agent 留痕 CSV（负责人，脱敏——不含完整手机号，导出本身留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_agent_logs
    from data.db_notifications import log_activity
    import csv
    from io import StringIO
    rows = get_agent_logs(limit=1000)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "角色", "用户输入", "纠正后", "识别意图", "路由结果", "状态", "异常", "关联编号", "时间"])
    for r in rows:
        w.writerow([r.get("id"), r.get("role"), (r.get("user_input") or "")[:80],
                    (r.get("corrected") or "")[:80], r.get("intent"), r.get("routed"),
                    r.get("status"), (r.get("error") or "")[:80], r.get("related_id"),
                    (r.get("created_at") or "")[:16]])
    log_activity(_user(request).get("name") or "负责人", "导出Agent留痕",
                 module="Agent", detail=f"导出 {len(rows)} 条（脱敏）")
    from fastapi.responses import Response
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=agent-logs.csv"})


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
