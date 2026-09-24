# api_routes/health.py
"""健康内容 / 健康咨询 / 天气联动路由模块（从 api_web.py 拆出，P2-04）。"""
import json

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _tenant, _same_tenant

router = APIRouter(prefix="/api/web/health", tags=["health"])


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


@router.post("/articles")
def web_health_article_create(req: HealthArticleCreate, request: Request):
    from data.db_health_content import create_content, submit_for_review
    from utils.cache import invalidate_health
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
        return _fail(2001, err or "创建失败")
    # 发布人不能同时是审核人，用「社区审核组」作为默认审核人
    submit_for_review(cid, auditor="社区审核组", actor=actor)
    invalidate_health()
    return _ok({"content_id": cid}, "已创建并提交审核")


class HealthArticleAction(BaseModel):
    action: str = Field(..., pattern="^(audit|offline|withdraw|delete|pin|unpin)$")
    approve: bool = Field(default=True)
    opinion: str = Field(default="")
    reason: str = Field(default="")


@router.post("/articles/{cid}/action")
def web_health_article_action(cid: int, req: HealthArticleAction, request: Request):
    from data.db_health_content import (
        review_content, take_down_content, withdraw_submission, delete_draft,
        set_pinned, is_disease_prevention_manager,
    )
    from utils.cache import invalidate_health
    # 权限：内容审核仅疾病预防负责人（方案权限矩阵）
    if not is_disease_prevention_manager(_user(request)):
        return _fail(1003, "无权限：仅疾病预防负责人可管理健康内容")
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
        return _fail(1001, "不支持的操作")
    if not ok_:
        return _fail(2001, msg)
    invalidate_health()
    return _ok({"content_id": cid}, "操作成功")


# ---- 健康咨询：未读徽标 / 天气联动 / 阈值配置 ----

@router.get("/unread-reply-count")
def web_health_unread(request: Request):
    """我的咨询未读回复数量（居民端徽标）。"""
    from data.db_health_content import get_unread_reply_count
    u = _user(request)
    return _ok({"count": get_unread_reply_count(u.get("uid"))})


@router.get("/linkage/records")
def web_health_linkage_records(request: Request, limit: int = 50):
    """天气联动触发记录（负责人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import get_linkage_records
    return _ok(get_linkage_records(limit=limit))


@router.get("/linkage/active")
def web_health_linkage_active(request: Request, limit: int = 3):
    """居民端当前生效的天气联动提醒（当天触发，最多 3 条，其余折叠）。

    多租户（B7）：只返回**本社区**触发的联动（留痕带 `[社区]` 归属标签；
    不带标签的历史行视为全局触发，仍可见，避免升级后这一段突然空白）。
    """
    from data.db_core import get_db
    from data.db_health_content import linkage_scope_of
    scope = _tenant(request) or "全局"
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE module='疾病预防' AND target_type='weather_linkage' "
            "AND action='联动提醒触发' AND date(created_at, 'localtime')=date('now','localtime') "
            "ORDER BY id DESC LIMIT ?", (limit * 5,),
        ).fetchall()
    out = [{
        "content_id": r["target_id"], "title": r["target_title"] or "",
        "detail": (r["detail"] or "").replace(f"[{scope}]", ""), "created_at": r["created_at"],
    } for r in rows if linkage_scope_of(r["detail"]) in (scope, "")]
    return _ok(out[:limit])


@router.get("/linkage/thresholds")
def web_health_linkage_thresholds_get(request: Request):
    """本社区生效的联动阈值（多租户 B7：社区专属 → 全局 → 代码默认）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import get_linkage_thresholds
    tenant = _tenant(request)
    return _ok({**get_linkage_thresholds(tenant=tenant), "scope": tenant or "全局"})


class LinkageThresholdsSet(BaseModel):
    high_temp: int | None = Field(default=None)
    low_temp: int | None = Field(default=None)
    temp_drop: int | None = Field(default=None)


@router.post("/linkage/thresholds")
def web_health_linkage_thresholds_set(req: LinkageThresholdsSet, request: Request):
    """天气联动阈值配置（仅疾病预防负责人，立即生效留痕）。

    多租户（B7）：只改**本社区**的阈值（`linkage_thresholds@社区`），其他社区不受影响。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import set_linkage_thresholds
    actor = _user(request).get("name") or "负责人"
    tenant = _tenant(request)
    r = set_linkage_thresholds(high_temp=req.high_temp, low_temp=req.low_temp,
                               temp_drop=req.temp_drop, actor=actor, tenant=tenant)
    return _ok({**r, "scope": tenant or "全局"}, "阈值已更新")


class LinkageAction(BaseModel):
    action: str = Field(..., pattern="^(close|reopen)$")
    reason: str = Field(default="")
    # 「永久关闭」此前**没有任何入口**（路由从不传 permanent）→ `reopen_linkage` 永远没有可开启的
    # 对象、`_linkage_perm_closed` 恒为 False，属"做了但没接上主路径"。这里补上开关。
    permanent: bool = Field(default=False)


@router.post("/linkage/{link_key}/action")
def web_health_linkage_action(link_key: str, req: LinkageAction, request: Request):
    """联动关闭/重新开启（二次确认留痕）。

    `permanent=true` = 永久关闭（需 reopen 才能再触发）；否则只做当天去重。

    多租户（B7）：关闭/重开只对本社区生效（留痕带 `[社区]` 归属标签）——
    耦合 `link_key` 的联动态（关闭状态、今日已触发）**不含社区信息**，
    所以归属必须由这里的服务端身份补上，否则 A 社区关闭会连带关掉 B 社区。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import close_linkage, reopen_linkage
    actor = _user(request).get("name") or "负责人"
    tenant = _tenant(request)
    if req.action == "close":
        ok_, msg = close_linkage(link_key, req.reason or "演示关闭", actor=actor,
                                 permanent=req.permanent, confirm=True, tenant=tenant)
    elif req.action == "reopen":
        ok_, msg = reopen_linkage(link_key, actor=actor, confirm=True, tenant=tenant)
    else:
        return _fail(1001, "不支持的操作")
    if not ok_:
        return _fail(2001, msg)
    return _ok({"link_key": link_key, "scope": tenant or "全局",
                "permanent": req.permanent if req.action == "close" else False},
               "已永久关闭" if (req.action == "close" and req.permanent) else "操作成功")


# ---- 咨询详情 / 居民反馈 ----

@router.get("/consults/{cid}")
def web_consult_detail(cid: int, request: Request):
    from data.db_health_content import get_consult
    u = _user(request)
    c = get_consult(cid)
    if not c:
        return _fail(1004, "咨询不存在")
    # 权限：居民只能看自己的咨询；负责人可看全部
    if u.get("role") != "grid" and c.get("user_id") != u.get("uid"):
        return _fail(1003, "无权限查看该咨询")
    # 多租户（B6）：负责人按 id 直取也必须落在本社区（否则跨社区读走居民健康咨询正文）
    if u.get("role") == "grid" and not _same_tenant(request, "health_consults", cid):
        return _fail(1003, "无权限查看该咨询（非本社区）")
    out = dict(c)
    if u.get("role") != "grid" and out.get("phone"):
        out["phone"] = out["phone"][:3] + "****" + out["phone"][-4:]
    return _ok(out)


class ConsultFeedback(BaseModel):
    solved: bool = Field(default=True)
    reason: str = Field(default="")


@router.post("/consults/{cid}/feedback")
def web_consult_feedback(cid: int, req: ConsultFeedback, request: Request):
    from data.db_health_content import feedback_consult
    from utils.cache import invalidate_health
    u = _user(request)
    ok_, msg = feedback_consult(cid, u.get("uid"), req.solved, reason=req.reason)
    if not ok_:
        return _fail(2001, msg)
    invalidate_health()
    return _ok({"consult_id": cid}, "反馈已提交")


class ConsultToggle(BaseModel):
    action: str = Field(..., pattern="^(withdraw|reopen|close)$")
    content: str = Field(default="")


@router.post("/consults/{cid}/toggle")
def web_consult_toggle(cid: int, req: ConsultToggle, request: Request):
    """咨询撤回/重新打开/关闭（居民本人）。"""
    from data.db_health_content import withdraw_consult, reopen_consult, close_consult
    from utils.cache import invalidate_health
    u = _user(request)
    uid = u.get("uid")
    if req.action == "withdraw":
        ok_, msg = withdraw_consult(cid, uid)
    elif req.action == "reopen":
        ok_, msg = reopen_consult(cid, uid, content=req.content)
    else:
        ok_, msg = close_consult(cid, uid)
    if not ok_:
        return _fail(2001, msg)
    invalidate_health()
    return _ok({"consult_id": cid}, "操作成功")


# ---------------- 健康（复用 db_health_content） ----------------

@router.get("/articles")
def web_health_articles(request: Request, status: str = "", content_type: str = "", keyword: str = ""):
    from data.db_health_content import list_contents, get_published_contents
    u = _user(request)
    if u.get("role") == "grid":
        rows = list_contents(status=status or None, content_type=content_type or None,
                             keyword=keyword or None, limit=100)
    else:
        rows = get_published_contents(content_type=content_type or None, limit=50)
    return _ok([{
        "id": c.get("id"), "title": c.get("title"), "content_type": c.get("content_type"),
        "summary": c.get("summary"), "status": c.get("status"),
        "source": c.get("source"), "expire_at": c.get("expire_at"),
        "is_pinned": c.get("is_pinned") or 0,
        "pinned_at": c.get("pinned_at"), "created_at": c.get("created_at"),
        "published_at": c.get("published_at"), "updated_at": c.get("updated_at"),
        "info_updated_at": c.get("info_updated_at") or "",
    } for c in rows])


@router.get("/articles/{cid}")
def web_health_article_detail(cid: int, request: Request):
    """健康内容详情（居民仅已发布；负责人全量含审核意见）。"""
    from data.db_health_content import get_content
    u = _user(request)
    c = get_content(cid)
    if not c:
        return _fail(1004, "内容不存在")
    if u.get("role") != "grid" and c.get("status") != "已发布":
        return _fail(1003, "无权限查看该内容")
    return _ok(dict(c))


class ConsultCreate(BaseModel):
    name: str = Field(default="")
    phone: str = Field(default="")
    consult_type: str = Field(default="健康知识")
    content: str = Field(..., min_length=5, max_length=2000)
    building: str = Field(default="")
    attachment_json: str = Field(default="[]")
    is_agent_report: int = Field(default=0)
    agent_name: str = Field(default="")
    agent_phone: str = Field(default="")
    agent_relation: str = Field(default="")


@router.post("/consults")
def web_consult_create(req: ConsultCreate, request: Request):
    from data.db_health_content import submit_consult, log_emergency_hint_shown
    from utils.cache import invalidate_health
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
        return _fail(2001, msg or "提交失败")
    invalidate_health()
    return _ok({"consult_id": cid, "code": code}, "提交成功")


@router.get("/consults")
def web_consult_list(request: Request, status: str = "", consult_type: str = "", keyword: str = ""):
    from data.db_health_content import get_my_consults, list_consults
    u = _user(request)
    if u.get("role") == "grid":
        rows = list_consults(status=status or None, consult_type=consult_type or None,
                             keyword=keyword or None, limit=100, tenant=_tenant(request))
    else:
        rows = get_my_consults(u.get("uid"), limit=50)
    out = []
    for r in rows:
        v = dict(r)
        if u.get("role") == "grid":
            # 负责人列表：电话脱敏展示
            v["phone"] = v.get("phone_masked") or v.get("phone", "")
        out.append(v)
    return _ok(out)


class ConsultReply(BaseModel):
    reply: str = Field(..., min_length=1, max_length=2000)
    doctor_guide: str = Field(default="")
    need_offline: bool = Field(default=False)
    offline_confirmed: bool = Field(default=False)


@router.post("/consults/{cid}/reply")
def web_consult_reply(cid: int, req: ConsultReply, request: Request):
    from data.db_health_content import reply_consult, is_disease_prevention_manager
    from utils.cache import invalidate_health
    # 权限：咨询处理人（疾病预防负责人自动成为处理人）
    if not is_disease_prevention_manager(_user(request)):
        return _fail(1003, "无权限：仅咨询处理人可回复")
    # 多租户（B6）：只能回复本社区的健康咨询（咨询正文含居民健康信息）
    if not _same_tenant(request, "health_consults", cid):
        return _fail(1003, "无权限回复该咨询（非本社区）")
    actor = _user(request).get("name") or "负责人"
    ok_, msg = reply_consult(cid, req.reply, actor=actor, doctor_guide=req.doctor_guide,
                             need_offline=req.need_offline, offline_confirmed=req.offline_confirmed)
    if not ok_:
        return _fail(2001, msg)
    invalidate_health()
    return _ok({"consult_id": cid}, "已回复")
