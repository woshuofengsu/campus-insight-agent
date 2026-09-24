# api_routes/issues.py
"""报修工单路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _tenant, _same_tenant

import logging
from utils.timeutil import utcnow
_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/issues", tags=["issues"])


class IssueCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
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


class IssueDraft(BaseModel):
    title: str = Field(default="")
    location: str = Field(default="")
    description: str = Field(default="")
    urgency: str = Field(default="一般")
    issue_type: str = Field(default="室内")


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


def _db_submit_issue(**kw):
    from data.db_repair import submit_issue
    return submit_issue(**kw)


def _issue_deadline(r: dict) -> dict:
    """按紧急程度计算时限（审核通过后计时：紧急1h/中等4h/一般24h/普通48h）。"""
    hours = {"紧急": 1, "中等": 4, "一般": 24, "普通": 48}.get(r.get("urgency"), 24)
    approved = r.get("approved_at")
    remaining, overdue = None, False
    if approved:
        try:
            from datetime import datetime
            t0 = datetime.strptime(str(approved)[:19], "%Y-%m-%d %H:%M:%S")
            remaining = round(hours - (utcnow() - t0).total_seconds() / 3600.0, 2)
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


def _mask_phone(v: dict) -> dict:
    if v.get("reporter_phone"):
        v["reporter_phone"] = v["reporter_phone"][:3] + "****" + v["reporter_phone"][-4:]
    return v


@router.post("")
def issue_create(req: IssueCreate, request: Request):
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
        return _fail(2001, hint or "提交失败")
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
        return _ok({"issue_id": iid, "merged": True, "original_id": dup["id"],
                    "hint": hint}, "已提交，检测到重复上报已合并处理")
    return _ok({"issue_id": iid, "merged": False, "hint": hint}, "提交成功")


@router.get("")
def issue_list(request: Request, status: str = "", category: str = "",
               urgency: str = "", issue_type: str = "", keyword: str = "",
               limit: int = 200):
    limit = min(limit, 500)
    from data.db_repair import get_issues
    u = _user(request)
    if u.get("role") == "grid":
        rows = get_issues(status=status or None, category=category or None,
                          urgency=urgency or None, issue_type=issue_type or None,
                          keyword=keyword or None, limit=limit, tenant=_tenant(request))
    else:
        rows = get_issues(reporter_id=u.get("uid"), status=status or None, limit=limit)
    # 非负责人：手机号脱敏；M2：状态人话化
    try:
        from agent.tone import human_status
    except Exception:
        human_status = lambda s: s
    out = []
    for r in rows:
        v = _issue_view(r)
        if u.get("role") != "grid":
            v = _mask_phone(v)
        v["status_human"] = human_status(v.get("status") or "")
        out.append(v)
    return _ok(out)


@router.get("/safety-reminders")
def issue_safety_reminders(request: Request, limit: int = 100):
    """负责人查看安全隐患提醒记录。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_repair import get_safety_reminders
    return _ok(get_safety_reminders(limit=limit))


# ---- 报修草稿（必须注册在 /{issue_id} 之前，避免被动态路由遮蔽） ----

@router.get("/drafts")
def issue_drafts(request: Request):
    """当前居民未完成的报修草稿。"""
    from data.db_repair import get_drafts
    u = _user(request)
    return _ok([dict(r) for r in get_drafts(u.get("uid"))])


@router.post("/drafts")
def issue_draft_save(req: IssueDraft, request: Request):
    """保存报修草稿（崩溃/超时自动生成，7 天内可恢复）。"""
    from data.db_repair import create_draft
    u = _user(request)
    if not req.title:
        return _fail(1001, "还差一点点：再跟我说说哪儿坏了，我好帮您找对人")
    create_draft(
        u.get("uid"), title=req.title, category="", issue_type=req.issue_type,
        location=req.location, description=req.description or req.title,
        urgency=req.urgency, reporter_name="", reporter_phone="",
    )
    return _ok({"saved": True}, "草稿已保存")


@router.delete("/drafts/{did}")
def issue_draft_delete(did: int, request: Request):
    """删除草稿（校验归属：居民只能删自己的）。"""
    from data.db_repair import get_draft, delete_draft
    u = _user(request)
    d = get_draft(did)
    if not d:
        return _fail(1004, "草稿不存在")
    if u.get("role") != "grid" and d.get("user_id") != u.get("uid"):
        return _fail(1003, "无权限删除该草稿")
    delete_draft(did)
    return _ok({"deleted": did}, "已删除")


@router.get("/{issue_id}")
def issue_detail(issue_id: int, request: Request):
    from data.db_repair import get_issue, get_issue_timeline
    u = _user(request)
    row = get_issue(issue_id)  # N9：直查单条，避免 limit=1000 内存找
    if not row:
        return _fail(1004, "工单不存在")
    # 权限：居民只能看自己的工单
    if u.get("role") != "grid" and row.get("reporter_id") != u.get("uid"):
        return _fail(1003, "无权限查看该工单")
    # 多租户（B6）：网格员按 id 直取也必须落在自己社区内，否则"列表看不见、换 id 就看见"
    if u.get("role") == "grid" and not _same_tenant(request, "community_issues", issue_id):
        return _fail(1003, "无权查看该工单")
    detail = _issue_view(row)
    if u.get("role") != "grid":
        detail = _mask_phone(detail)
    try:  # M2：工单状态人话化
        from agent.tone import human_status
        detail["status_human"] = human_status(detail.get("status") or "")
    except Exception:
        detail["status_human"] = detail.get("status", "")
    detail["timeline"] = [dict(t) for t in get_issue_timeline(issue_id)]
    return _ok(detail)


@router.post("/{issue_id}/action")
def issue_action(issue_id: int, req: IssueAction, request: Request):
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
        return _fail(1003, "无权限执行该操作（仅负责人可管理工单状态）")
    # 归属校验：居民只能操作自己提交的工单
    if role != "grid":
        from data.db_repair import get_issue
        issue = get_issue(issue_id)
        if not issue:
            return _fail(1004, "工单不存在")
        if issue.get("reporter_id") != u.get("uid"):
            return _fail(1003, "无权限操作该工单（非本人报修）")
    # 多租户（B6）：网格员按 id 直取只能操作本社区工单（否则可跨社区派单/结单）
    elif not _same_tenant(request, "community_issues", issue_id):
        return _fail(1003, "无权限操作该工单（非本社区）")
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
            return _fail(1001, "不支持的操作")
    except Exception as e:  # noqa: BLE001
        _log.warning("工单操作异常：%s", e)
        return _fail(2001, "操作失败，请稍后再试")
    if not ok_:
        return _fail(2001, msg or "操作被拒绝")
    return _ok({"issue_id": issue_id}, msg or "操作成功")
