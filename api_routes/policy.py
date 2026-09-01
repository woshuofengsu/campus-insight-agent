# api_routes/policy.py
"""政策问答 / 知识库路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _fail, _ok, _require_role, _user

import logging
_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/qa", tags=["policy"])
knowledge_router = APIRouter(prefix="/api/web/knowledge", tags=["policy"])


# ---------------- 政策问答（复用 db_policy） ----------------

class AskQuestion(BaseModel):
    question: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="")
    source: str = Field(default="居民端")


@router.post("/ask")
def web_qa_ask(req: AskQuestion, request: Request):
    from data.db_policy import ask_question
    u = _user(request)
    r = ask_question(u.get("uid"), req.question, source=req.source, category=req.category or None)
    if r.get("matched"):
        return _ok({
            "matched": True, "question_id": r.get("question_id"),
            "answer": r.get("auto_answer"), "score": r.get("score"),
            "title": (r.get("knowledge") or {}).get("title"),
            "rag": r.get("rag", False),
        }, "已自动回答")
    # 未匹配/敏感/医疗 → 转人工提示
    return _ok({
        "matched": False, "reason": r.get("reason"),
        "manual_text": r.get("manual_text", "暂未找到答案，可转人工。"),
        "expired_hint": r.get("expired_hint", ""),
    }, "未自动回答")


class TransferHuman(BaseModel):
    question: str = Field(default="")


@router.post("/{qid}/transfer")
def web_qa_transfer(qid: int, req: TransferHuman, request: Request):
    from data.db_policy import get_question, transfer_to_human
    u = _user(request)
    if qid > 0:
        q = get_question(qid)
        if not q:
            return _fail(1004, "提问不存在")
        if u.get("role") != "grid" and q.get("user_id") != u.get("uid"):
            return _fail(1003, "无权限操作该提问")
    try:
        transfer_to_human(qid) if qid > 0 else transfer_to_human(
            user_id=u.get("uid"), question=req.question, source="居民端")
        return _ok({"question_id": qid}, "已转人工")
    except Exception as e:
        _log.warning("转人工异常：%s", e)
        return _fail(2001, "转人工失败，请稍后再试")


@router.delete("/questions/{qid}")
def web_qa_question_delete(qid: int, request: Request):
    """居民删除自己的提问记录（处理中拦截由数据层校验）。"""
    from data.db_policy import delete_question, get_question
    u = _user(request)
    q = get_question(qid)
    if not q:
        return _fail(1004, "提问不存在")
    if u.get("role") != "grid" and q.get("user_id") != u.get("uid"):
        return _fail(1003, "无权限删除该提问")
    ok_, msg = delete_question(qid, u.get("uid"))
    if not ok_:
        return _fail(2001, msg or "删除失败")
    return _ok({"question_id": qid}, "已删除")


@router.get("/questions")
def web_qa_questions(request: Request, status: str = "", limit: int = 50):
    limit = min(limit, 500)
    from data.db_policy import get_question_deadline_info, get_questions
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
    return _ok(out)


@knowledge_router.get("")
def web_knowledge_list(request: Request, category: str = "", limit: int = 50):
    limit = min(limit, 500)
    from data.db_policy import get_knowledge_list
    u = _user(request)
    status = None if u.get("role") == "grid" else "已发布"
    rows = get_knowledge_list(status=status, category=category or None, limit=limit)
    return _ok([{
        "id": k.get("id"), "title": k.get("title"), "category": k.get("category"),
        "plain_interpretation": k.get("plain_interpretation"), "summary": k.get("summary"),
        "status": k.get("audit_status"), "updated_at": k.get("updated_at") or k.get("created_at"),
        "attachment": k.get("attachment"),
        "audit_opinion": k.get("audit_opinion") or "",
        "auditor": k.get("auditor") or "",
        "version": k.get("version") or 1,
    } for k in rows])


@router.get("/high-freq")
def web_qa_high_freq(request: Request, limit: int = 10):
    from data.db_policy import get_common_questions
    return _ok(get_common_questions(limit=limit))


# ---- 政策知识库管理（创建/审核/下架） ----

class KnowledgeCreate(BaseModel):
    title: str = Field(..., min_length=2)
    category: str = Field(default="社保医保")
    plain_interpretation: str = Field(..., min_length=2, max_length=2000)
    content: str = Field(default="")
    summary: str = Field(default="")
    source: str = Field(default="社区整理")
    keywords: str = Field(default="")
    effective_date: str = Field(default="")
    expire_date: str = Field(default="")
    policy_number: str = Field(default="")
    attachment: str = Field(default="")


@knowledge_router.post("")
def web_knowledge_create(req: KnowledgeCreate, request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import create_knowledge, submit_review
    from utils.cache import invalidate_knowledge
    actor = _user(request).get("name") or "负责人"
    kid, err = create_knowledge(
        title=req.title, category=req.category, plain_interpretation=req.plain_interpretation,
        content=req.content, summary=req.summary, source=req.source,
        keywords=req.keywords, effective_date=req.effective_date,
        expire_date=req.expire_date, policy_number=req.policy_number,
        attachment=req.attachment, actor=actor,
    )
    if kid <= 0:
        return _fail(2001, err or "创建失败")
    submit_review(kid, auditor="社区审核组", actor=actor)
    invalidate_knowledge()
    return _ok({"knowledge_id": kid}, "已创建并提交审核")


class KnowledgeAction(BaseModel):
    action: str = Field(..., pattern="^(audit|offline|withdraw|delete)$")
    approve: bool = Field(default=True)
    opinion: str = Field(default="")
    reason: str = Field(default="")


@knowledge_router.post("/{kid}/action")
def web_knowledge_action(kid: int, req: KnowledgeAction, request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import audit_knowledge, delete_knowledge, take_down_knowledge, withdraw_review
    from utils.cache import invalidate_knowledge
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
        return _fail(1001, "不支持的操作")
    if not ok_:
        return _fail(2001, msg)
    invalidate_knowledge()
    return _ok({"knowledge_id": kid}, "操作成功")


@knowledge_router.get("/{kid}/versions")
def web_knowledge_versions(kid: int, request: Request):
    """版本历史（负责人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import get_version_history
    return _ok(get_version_history(kid))


@knowledge_router.post("/{kid}/new-version")
def web_knowledge_new_version(kid: int, req: KnowledgeCreate, request: Request):
    """已发布条目创建新版本（提交审核，审核通过自动替换旧版）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import create_new_version, submit_review
    from utils.cache import invalidate_knowledge
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
        return _fail(2001, err or "创建版本失败")
    submit_review(nid, auditor="社区审核组", actor=actor)
    invalidate_knowledge()
    return _ok({"knowledge_id": nid}, "新版本已创建并提交审核")


# ---- 提问人工回复 / 居民反馈 ----

class QaReply(BaseModel):
    reply: str = Field(..., min_length=1, max_length=2000)


@router.post("/questions/{qid}/reply")
def web_qa_reply(qid: int, req: QaReply, request: Request):
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import reply_question
    actor = _user(request).get("name") or "负责人"
    ok_, msg, _ = reply_question(qid, req.reply, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"question_id": qid}, "已回复")


class QaFeedback(BaseModel):
    satisfied: bool = Field(default=True)
    reason: str = Field(default="")


@router.post("/questions/{qid}/feedback")
def web_qa_feedback(qid: int, req: QaFeedback, request: Request):
    from data.db_policy import feedback_question, get_question
    u = _user(request)
    q = get_question(qid)
    if not q:
        return _fail(1004, "提问不存在")
    if u.get("role") != "grid" and q.get("user_id") != u.get("uid"):
        return _fail(1003, "无权限反馈该提问")
    ok_, msg, _ = feedback_question(qid, req.satisfied, reason=req.reason, actor=u.get("name") or "居民")
    if not ok_:
        return _fail(2001, msg)
    return _ok({"question_id": qid}, "反馈已提交")


# ---------------- 政策统计 / 匹配阈值 ----------------

@router.get("/stats")
def web_qa_stats(request: Request, days: int = 0):
    """负责人端高频统计（匹配失败/无帮助分类）；days=0 全部，7 近 7 天，30 近 30 天。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import get_frequency_stats
    return _ok(get_frequency_stats(days=days or None))


class ThresholdSet(BaseModel):
    threshold: float = Field(..., ge=0.1, le=5.0)


@router.get("/threshold")
def web_qa_threshold_get(request: Request):
    from data.db_policy import get_match_threshold
    return _ok({"threshold": get_match_threshold()})


@router.post("/threshold")
def web_qa_threshold_set(req: ThresholdSet, request: Request):
    """匹配阈值配置（仅负责人，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import set_match_threshold
    set_match_threshold(req.threshold, actor=_user(request).get("name") or "负责人")
    return _ok({"threshold": req.threshold}, "阈值已更新")
