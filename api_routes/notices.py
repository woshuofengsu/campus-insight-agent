# api_routes/notices.py
"""通知路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _tenant, _same_tenant

import logging
_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/notices", tags=["notices"])


class NoticeCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=50)
    notice_type: str = Field(..., pattern="^(社区公告|活动通知|停水停电通知|政策通知|温馨提示|紧急通知|其他)$")
    publish_scope: str = Field(default="全体居民", pattern="^(全体居民|指定小区|指定楼栋|仅老年端)$")
    body: str = Field(..., min_length=1, max_length=3000)
    elderly_summary: str = Field(default="")
    is_urgent: int = Field(default=0)
    is_pinned: int = Field(default=0)
    expire_at: str = Field(default="")
    scheduled_at: str = Field(default="")
    attachment_json: str = Field(default="[]")
    scope_target_json: str = Field(default="[]")
    # 幂等键（卡8 推广）：前端每次"点发布"生成一次，网络重试沿用同一个。
    # 不带也能用（老客户端），但带上就能保证"连点两下只发一条通知"。
    client_token: str = Field(default="", max_length=64)


@router.post("")
def web_notice_create(req: NoticeCreate, request: Request):
    from data.db_notice import create_notice, can_publish_urgent
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    actor = _user(request).get("name") or "负责人"
    uid = _user(request).get("uid") or 0
    # 幂等（卡8 推广到通知链路）：通知是**一对多**的写操作（发一次 = 全社区收一条），
    # 重复执行不只是"多一条记录"，而是**所有居民/老人各多收一条**，所以这条链路最该有幂等。
    scope = "notice_create"
    reserved = False
    if req.client_token:
        from data.db_idempotency import begin, valid_key, wait_result
        if not valid_key(req.client_token):
            # 编号格式不合规（服务端要求 8–64 位 [A-Za-z0-9_-]）→ **不能静默当没带**：
            # 静默的后果是"以为有幂等、其实没有"。这里如实告警，并继续按无编号处理（旧客户端不受影响）。
            _log.warning("通知创建的幂等编号格式不合规（%s 位），本次按无编号处理：%s",
                         len(req.client_token), req.client_token[:12])
            req.client_token = ""
    if req.client_token:
        state, prev = begin(scope, req.client_token, uid)
        if state == "done":
            _log.info("通知重复创建（幂等命中）：uid=%s token=%s", uid, req.client_token)
            return _ok({**(prev or {}), "duplicate": True}, "这条通知已经创建过了")
        if state == "pending":
            prev = wait_result(scope, req.client_token, uid, timeout=8)
            if prev is not None:
                return _ok({**(prev or {}), "duplicate": True}, "这条通知已经创建过了")
            return _fail(2003, "这条通知正在创建中，请稍等几秒后再看结果。")
        if state == "unknown":
            # 占位没做成 → fail-closed：通知发出去就收不回来（居民端已经收到推送），
            # 无法确认"是不是已经发过了"时宁可让负责人刷新列表确认。
            return _fail(2003, "创建状态暂时无法确认（系统繁忙），请刷新通知列表确认是否已发布，不要重复点。")
        reserved = True
    # 紧急通知权限白名单（方案权限矩阵：仅紧急通知发布人）
    if req.is_urgent and not can_publish_urgent(_user(request).get("uid")):
        if reserved:
            from data.db_idempotency import release
            release(scope, req.client_token, uid)
        return _fail(1003, "您无权发布紧急通知（仅指定负责人）")
    nid = create_notice(
        title=req.title, notice_type=req.notice_type, publish_scope=req.publish_scope,
        body=req.body, elderly_summary=req.elderly_summary, publisher=actor,
        is_pinned=req.is_pinned, is_urgent=req.is_urgent, expire_at=req.expire_at,
        attachment_json=req.attachment_json, scope_target_json=req.scope_target_json,
        actor=actor, publisher_id=_user(request).get("uid"),
    )
    if nid <= 0:
        if reserved:
            from data.db_idempotency import release
            release(scope, req.client_token, uid)
        return _fail(2001, "通知类型或敏感词校验不通过")
    # 定时 / 立即发布
    if req.scheduled_at:
        from data.db_notice import schedule_notice
        ok_, msg = schedule_notice(nid, req.scheduled_at, _user(request).get("uid"), actor,
                                   confirm_urgent=bool(req.is_urgent))
        if not ok_:
            if reserved:
                from data.db_idempotency import release
                release(scope, req.client_token, uid)
            return _fail(2001, msg)
    elif req.notice_type != "紧急通知":
        from data.db_notice import publish_notice
        ok_, msg = publish_notice(nid, _user(request).get("uid"), actor)
        if not ok_:
            if reserved:
                from data.db_idempotency import release
                release(scope, req.client_token, uid)
            return _fail(2001, msg)
    if reserved:
        from data.db_idempotency import remember
        remember(scope, req.client_token, uid, {"notice_id": nid})
    return _ok({"notice_id": nid}, "通知已创建")


@router.get("")
def web_notice_list(request: Request, limit: int = 100):
    limit = min(limit, 500)
    from data.db_notice import get_visible_notices
    u = _user(request)
    role = u.get("role")
    client_type = "elderly" if role == "elderly" else "resident"
    rows = get_visible_notices(client_type, u.get("uid"), limit=limit, tenant=_tenant(request))
    out = [{
        "id": n.get("id"), "title": n.get("title"), "notice_type": n.get("notice_type"),
        "body": n.get("body"), "is_urgent": n.get("is_urgent"), "is_pinned": n.get("is_pinned"),
        "published_at": n.get("published_at"), "elderly_summary": n.get("elderly_summary"),
        "is_read": n.get("is_read", 0),
    } for n in rows]
    return _ok(out)


@router.get("/manage")
def web_notice_manage(request: Request, status: str = "", limit: int = 200):
    limit = min(limit, 500)
    """负责人端通知管理列表（含已读统计）。"""
    from utils.cache import cached_notices_with_stats
    _r = _require_role(request, "grid")
    if _r:
        return _r
    rows = cached_notices_with_stats(status=status or None, limit=limit, tenant=_tenant(request))
    return _ok(rows)


class NoticeAction(BaseModel):
    action: str = Field(..., pattern="^(publish|schedule|withdraw|take_down|pin|unpin|mark_read|delete)$")
    scheduled_at: str = Field(default="")
    reason: str = Field(default="")
    confirm_urgent: bool = Field(default=False)
    # 幂等键（卡8 推广）：同一次"点发布/撤回/下架"重试沿用同一个 token
    client_token: str = Field(default="", max_length=64)


@router.post("/{nid}/action")
def web_notice_action(nid: int, req: NoticeAction, request: Request):
    from data.db_notice import (
        publish_notice, schedule_notice, withdraw_notice, take_down_notice,
        set_pinned, mark_notice_read, delete_notice,
    )
    from utils.cache import invalidate_notices
    u = _user(request)
    # 管理动作仅负责人；mark_read 允许居民/老年
    if req.action != "mark_read" and u.get("role") != "grid":
        return _fail(1003, "无权限执行该操作（仅负责人可管理通知）")
    # 多租户（B6）：通知按 id 直取只能动本社区的（否则可跨社区发布/撤回/删除/置顶，
    # 或把别的社区的通知标成已读）
    if not _same_tenant(request, "notices", nid):
        return _fail(1003, "无权限操作该通知（非本社区）")
    actor = u.get("name") or "负责人"
    uid = u.get("uid") or 0
    a = req.action
    # 幂等（卡8 推广）：**发布类**动作连点两下会让全社区各收两条；
    # 撤回/下架/置顶这类"改状态"的动作重复执行不会多出东西，但同样按 token 挡一层，
    # 免得"以为失败了又点一次"之后状态被反复翻转。
    scope = f"notice_{a}"
    reserved = False
    if req.client_token and a != "mark_read":
        from data.db_idempotency import begin, valid_key, wait_result
        if not valid_key(req.client_token):
            _log.warning("通知操作的幂等编号格式不合规（%s 位），本次按无编号处理：%s",
                         len(req.client_token), req.client_token[:12])
        else:
            state, prev = begin(scope, req.client_token, uid)
            if state == "done":
                _log.info("通知重复操作（幂等命中）：uid=%s token=%s action=%s", uid, req.client_token, a)
                return _ok({**(prev or {}), "duplicate": True}, f"这个操作已经做过了：{a}")
            if state == "pending":
                prev = wait_result(scope, req.client_token, uid, timeout=8)
                if prev is not None:
                    return _ok({**(prev or {}), "duplicate": True}, f"这个操作已经做过了：{a}")
                return _fail(2003, "这个操作正在处理中，请稍等几秒后再看结果。")
            if state == "unknown":
                return _fail(2003, "操作状态暂时无法确认（系统繁忙），请刷新后确认结果，不要重复点。")
            reserved = True

    def _drop():
        if reserved:
            from data.db_idempotency import release
            release(scope, req.client_token, uid)

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
            return _ok({"notice_id": nid}, "已标记已读")
        elif a == "delete":
            delete_notice(nid, actor)
            invalidate_notices()
            if reserved:
                from data.db_idempotency import remember
                remember(scope, req.client_token, uid, {"notice_id": nid})
            return _ok({"notice_id": nid}, "已删除")
        else:
            _drop()
            return _fail(1001, "不支持的操作")
    except Exception as e:  # noqa: BLE001
        _log.warning("通知操作异常：%s", e)
        _drop()
        return _fail(2001, "操作失败，请稍后再试")
    if not ok_:
        # 没做成 → 放掉占位，让同一次点击可以重试
        _drop()
        return _fail(2001, msg or "操作被拒绝")
    if reserved:
        from data.db_idempotency import remember
        remember(scope, req.client_token, uid, {"notice_id": nid, "action": a})
    invalidate_notices()
    return _ok({"notice_id": nid}, msg or "操作成功")


@router.get("/{nid}")
def web_notice_detail(nid: int, request: Request):
    from data.db_notice import get_notice, get_notice_read_stats
    u = _user(request)
    n = get_notice(nid)
    if not n:
        return _fail(1004, "通知不存在")
    # 多租户（B6）：网格员按 id 直取也必须落在本社区（居民/老年下面按可见集合过滤）
    if u.get("role") == "grid" and not _same_tenant(request, "notices", nid):
        return _fail(1003, "无权限查看该通知（非本社区）")
    # 范围过滤：居民/老年只能看本端可见通知（N8：授权判断 fail-closed，校验异常即拒绝，不静默放行）
    if u.get("role") != "grid":
        try:
            from data.db_notice import get_visible_notices
            visible = get_visible_notices("elderly" if u.get("role") == "elderly" else "resident",
                                          u.get("uid"), limit=500, tenant=_tenant(request))
        except Exception:
            return _fail(1003, "无权查看该通知")  # fail-closed：校验失败 → 拒绝
        if not any(v.get("id") == nid for v in visible):
            return _fail(1003, "无权限查看该通知")
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
    return _ok(out)
