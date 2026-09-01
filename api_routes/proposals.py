# api_routes/proposals.py
"""提案路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role

import logging
_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/proposals", tags=["proposals"])


class ProposalCreate(BaseModel):
    title: str = Field(..., min_length=2)
    description: str = Field(..., min_length=5, max_length=5000)
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


class ProposalDraft(BaseModel):
    title: str = Field(default="")
    description: str = Field(default="")
    category: str = Field(default="其他")
    is_public: int = Field(default=1)
    reporter_name: str = Field(default="")
    reporter_phone: str = Field(default="")
    attachment_public: int = Field(default=0)


class ProposalVote(BaseModel):
    score: int = Field(..., ge=1, le=5)


class ProposalCommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


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


@router.post("")
def proposal_create(req: ProposalCreate, request: Request):
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
        return _fail(2001, msg or "提交失败")
    return _ok({"proposal_id": pid}, "提交成功")


# 提案草稿（崩溃/超时留草稿，7 天有效）

@router.get("/drafts")
def proposal_drafts(request: Request):
    from data.db_proposal import get_drafts
    u = _user(request)
    return _ok(get_drafts(u.get("uid")))


@router.post("/drafts")
def proposal_draft_save(req: ProposalDraft, request: Request):
    from data.db_proposal import save_draft
    u = _user(request)
    did = save_draft(
        u.get("uid"), title=req.title, description=req.description,
        category=req.category, is_public=req.is_public,
        reporter_name=req.reporter_name, reporter_phone=req.reporter_phone,
        attachment_public=req.attachment_public,
    )
    return _ok({"draft_id": did}, "草稿已保存")


@router.delete("/drafts/{did}")
def proposal_draft_delete(did: int, request: Request):
    from data.db_proposal import get_draft, delete_draft
    u = _user(request)
    d = get_draft(did, u.get("uid"))
    if not d:
        return _fail(1004, "草稿不存在")
    delete_draft(did)
    return _ok({"deleted": did}, "草稿已删除")


@router.get("")
def proposal_list(request: Request, status: str = "", limit: int = 300):
    limit = min(limit, 500)
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
    return _ok(out)


@router.get("/{pid}")
def proposal_detail(pid: int, request: Request):
    from data.db_proposal import get_proposal, get_proposal_vote_stats, get_proposal_timeline
    u = _user(request)
    p = get_proposal(pid)
    if not p:
        return _fail(1004, "提案不存在")
    # 居民：只能看自己提交的（含私有/待审核）+ 公开公示链上的提案，隐藏敏感字段
    if u.get("role") != "grid":
        mine = p.get("reporter_id") == u.get("uid")
        if not mine:
            if not p.get("is_public") or p.get("status") not in (
                "公示中", "待执行", "执行中", "待提案人反馈", "重新执行", "已完成"
            ):
                return _fail(1003, "无权限查看该提案")
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
    return _ok(out)


@router.post("/{pid}/vote")
def proposal_vote(pid: int, req: ProposalVote, request: Request):
    from data.db_proposal import vote_proposal
    u = _user(request)
    ok_, msg = vote_proposal(pid, u.get("uid"), req.score, actor="匿名居民")
    if not ok_:
        return _fail(2001, msg or "投票失败")
    return _ok({"proposal_id": pid}, "投票成功")


# ---------------- 提案议论（公示期匿名讨论） ----------------

@router.get("/{pid}/comments")
def proposal_comments(pid: int, request: Request, limit: int = 100):
    """公示提案的匿名议论列表（作者为匿名伪名，匿名可见）。"""
    from data.db_proposal import get_proposal_comments, get_proposal
    p = get_proposal(pid)
    if not p:
        return _fail(1004, "提案不存在")
    u = _user(request)
    if u.get("role") != "grid" and (not p.get("is_public") or p.get("status") not in
                                    ("公示中", "待执行", "执行中", "待提案人反馈", "重新执行")):
        return _fail(1003, "该提案暂不支持议论")
    return _ok(get_proposal_comments(pid, limit=limit))


@router.post("/{pid}/comments")
def proposal_comment_add(pid: int, req: ProposalCommentCreate, request: Request):
    """匿名发表议论（自己能看到、别人能看到，均不显示真实身份）。"""
    from data.db_proposal import add_proposal_comment
    u = _user(request)
    ok_, msg = add_proposal_comment(pid, u.get("uid"), req.content)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"proposal_id": pid}, "议论已发布（匿名）")


@router.post("/{pid}/action")
def proposal_action(pid: int, req: ProposalAction, request: Request):
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
        return _fail(1003, "无权限执行该操作（仅负责人可管理提案）")
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
                return _fail(1004, "提案不存在")
            return _ok({"phone": phone}, "已留痕查看完整手机号")
        elif a == "remind":
            ok_, msg = remind_confirm(pid, actor=actor)
        elif a == "extend_voting":
            ok_, msg = extend_voting(pid, req.minutes, actor=actor)
        else:
            return _fail(1001, "不支持的操作")
    except Exception as e:  # noqa: BLE001
        _log.warning("提案操作异常：%s", e)
        return _fail(2001, "操作失败，请稍后再试")
    if not ok_:
        return _fail(2001, msg or "操作被拒绝")
    return _ok({"proposal_id": pid}, msg or "操作成功")
