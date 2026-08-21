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


# ---------------- 提案闭环（复用 db_proposal） ----------------

class ProposalAction(BaseModel):
    action: str = Field(..., pattern="^(audit|confirm|decide|execute|resolve|feedback|reopen|close|take_down)$")
    approve: bool = Field(default=True)
    opinion: str = Field(default="")
    is_public: int = Field(default=1)
    reason: str = Field(default="")
    dept: str = Field(default="")
    result: str = Field(default="")
    satisfied: bool = Field(default=True)
    close: bool = Field(default=False)


@app.post("/api/web/proposals/{pid}/action")
def web_proposal_action(pid: int, req: ProposalAction, request: Request):
    from data.db_proposal import (
        audit_proposal, confirm_visibility, decide_execute, start_execute,
        resolve_proposal, feedback_proposal, handle_reopen, close_proposal,
        take_down_proposal,
    )
    actor = _user(request).get("name") or "负责人"
    a = req.action
    try:
        if a == "audit":
            ok_, msg = audit_proposal(pid, req.approve, opinion=req.opinion, actor=actor)
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
            ok_, msg = close_proposal(pid, actor=actor)
        elif a == "take_down":
            ok_, msg = take_down_proposal(pid, req.reason, actor=actor)
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
    from data.db_notice import create_notice
    actor = _user(request).get("name") or "负责人"
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
    from data.db_policy import transfer_to_human
    u = _user(request)
    try:
        ok_ = transfer_to_human(qid) if qid > 0 else transfer_to_human(
            user_id=u.get("uid"), question=req.question, source="居民端")
        return ok({"question_id": qid}, "已转人工")
    except Exception as e:  # noqa: BLE001
        return fail(2001, f"转人工失败：{e}")


@app.get("/api/web/qa/questions")
def web_qa_questions(request: Request, status: str = "", limit: int = 50):
    from data.db_policy import get_questions
    u = _user(request)
    if u.get("role") == "grid":
        rows = get_questions(status=status or None, limit=limit)
    else:
        rows = get_questions(user_id=u.get("uid"), limit=limit)
    return ok([dict(r) for r in rows])


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
    } for k in rows])


@app.get("/api/web/qa/high-freq")
def web_qa_high_freq(request: Request, limit: int = 10):
    from data.db_policy import get_common_questions
    return ok(get_common_questions(limit=limit))




# ---------------- 天气（复用 db_weather / tools.query_weather） ----------------

@app.get("/api/web/weather/current")
def web_weather_current(request: Request):
    from data.db_weather import get_weather_for_display
    from config import COMMUNITY_CITY, COMMUNITY_DISTRICT
    w = get_weather_for_display("")
    days = w.get("days") or []
    today = days[0] if days else {}
    return ok({
        "location": COMMUNITY_CITY + COMMUNITY_DISTRICT,
        "temp_high": today.get("temp_high"), "temp_low": today.get("temp_low"),
        "condition": today.get("condition"), "emoji": today.get("emoji"),
        "wind": today.get("wind"), "rain_prob": today.get("rain_prob"),
        "humidity": today.get("humidity"), "aqi": today.get("aqi"), "uv": today.get("uv"),
        "advice": today.get("advice"),
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
    rows = list_check_tasks(status=status or None, limit=200)
    return ok([dict(r) for r in rows])


# ---------------- 健康（复用 db_health_content） ----------------

@app.get("/api/web/health/articles")
def web_health_articles(request: Request, status: str = ""):
    from data.db_health_content import list_contents
    u = _user(request)
    if u.get("role") == "grid":
        rows = list_contents(status=status or None, limit=100)
    else:
        rows = list_contents(status="已发布", limit=50)
    return ok([{
        "id": c.get("id"), "title": c.get("title"), "content_type": c.get("content_type"),
        "summary": c.get("summary"), "status": c.get("status"),
        "pinned_at": c.get("pinned_at"), "created_at": c.get("created_at"),
    } for c in rows])


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
    from data.db_health_content import submit_consult
    from ui.cache import invalidate_health
    u = _user(request)
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
def web_consult_list(request: Request, status: str = ""):
    from data.db_health_content import get_my_consults, list_consults
    u = _user(request)
    if u.get("role") == "grid":
        rows = list_consults(status=status or None, limit=100)
    else:
        rows = get_my_consults(u.get("uid"), limit=50)
    return ok([dict(r) for r in rows])


class ConsultReply(BaseModel):
    reply: str = Field(..., min_length=1)
    doctor_guide: str = Field(default="")
    need_offline: bool = Field(default=False)
    offline_confirmed: bool = Field(default=False)


@app.post("/api/web/health/consults/{cid}/reply")
def web_consult_reply(cid: int, req: ConsultReply, request: Request):
    from data.db_health_content import reply_consult
    from ui.cache import invalidate_health
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
    uid = u.get("uid")
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
    })


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
    profile = {}
    try:
        from data.db_user import get_user_by_id
        profile = get_user_by_id(u.get("uid")) or {}
    except Exception:
        pass
    category, urgency = _llm_classify(req.text, "")
    loc = extract_location(req.text) or profile.get("community") or "社区"
    iid, hint = submit_issue(
        title=req.text[:80], category=category, issue_type=req.issue_type,
        location=loc, description=req.text, urgency=req.urgency or urgency or "一般",
        reporter_name=profile.get("name") or "老人",
        reporter_phone=profile.get("phone") or "13800000000",
        reporter_id=u.get("uid"),
    )
    if iid <= 0:
        return fail(2001, hint or "上报失败")
    return ok({"issue_id": iid, "category": category}, "上报成功")


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
    times = [t.strip() for t in req.times.replace("，", ",").split(",") if t.strip()]
    mid, msg = add_medication_reminder(
        u.get("uid"), u.get("name") or "老人", req.drug_name, req.dosage, times,
        repeat_rule=req.repeat_rule, start_date=req.start_date, end_date=req.end_date,
        note=req.note, setter_id=u.get("uid"), actor=u.get("name") or "老人",
    )
    if mid <= 0:
        return fail(2001, msg)
    return ok({"reminder_id": mid}, "已提交，待审核")


@app.get("/api/web/elderly/medications")
def web_medication_list(request: Request):
    from data.db_elderly_care import list_medication_reminders
    u = _user(request)
    return ok([dict(r) for r in list_medication_reminders(u.get("uid"))])


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
    return ok(get_latest_sos(u.get("uid")))


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
