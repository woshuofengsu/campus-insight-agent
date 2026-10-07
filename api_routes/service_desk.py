# api_routes/service_desk.py
"""服务台模式（阶段 2）：**共享平板 / 工作人员代录**的独立入口。

## 为什么单独一个模块、单独一个入口

真实社区里老人不会都用手机：**服务站平板、家属代办、网格员代录、电话人工**都会发生。
这些场景有两个共同点，决定了它们不能塞进老年端页面：

1. **操作人不是当事人**。张大爷是 `reporter`，社区工作人员王老师是 `operator`。
   只记一个身份，"老人首次完成率"就会把**工作人员代操作算成老人完成了**（试点核心指标当场变假）。
2. **设备是共享的**。同一台平板一天要接待十几位老人，所以
   "上一个人的信息绝不留给下一个人"是**功能需求**，不是洁癖。

所以：`/service-desk` **独立入口**，不进老年端导航（老人用不到的按钮，放上去就是干扰）。

## 三条安全红线（都有测试守着）

① **只有本社区的负责人能用**（`_require_role(request, "grid")`），居民/老人一律拒绝；
② **被代录的人必须在操作人所在社区**——否则等于"帮隔壁社区建单"，
   而且读取侧是 fail-closed，建出来的单**自己社区反而看不见**（B6 那个老坑的翻版）；
③ **代录必须有授权依据**（`consent_status` 非空）：站点/家属代录场景里，
   "老人是否知情同意"不是可选项。没记录就不给提交（fail-closed）。

## 走查用户（没有账号的老人）怎么处理

社区里必然有没建过账号的老人。这时 `reporter_id=0`，但租户**必须按操作人的社区盖章**——
`submit_issue` 是按 `reporter_id` 盖章的，`reporter_id=0` 会盖成空租户，
于是这张单在网格端列表里**谁都看不见**。这里显式补章（`stamp_tenant_value`），并有测试守着。
"""
import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _fail, _ok, _require_role, _tenant, _user

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/service-desk", tags=["service-desk"])

#: 服务台可选的**办理方式**（与 `data.db_issue_code.CHANNELS` 同源，这里只列服务台会用的）
SERVICE_DESK_CHANNELS = ("service_desk_tablet", "family_assisted",
                         "grid_recorded", "phone_manual")
#: 这些方式下"操作人 ≠ 当事人"，所以必须有授权依据
ASSISTED = set(SERVICE_DESK_CHANNELS)
#: 授权依据的可选值（写成枚举，避免自由文本导致"表里都是字、其实没法统计"）
CONSENT_VALUES = ("口头同意", "书面同意", "家属知情", "电话确认", "本人未到场·家属代述")


def _operator(request: Request) -> dict:
    u = _user(request) or {}
    return {"uid": u.get("uid") or 0, "name": u.get("name") or "", "role": u.get("role") or ""}


@router.get("/context")
def service_desk_context(request: Request):
    """服务台初始上下文：**当前社区 / 操作人 / 可选办理方式 / 本社区可代录的人**。

    社区一律来自**服务端身份**（`_tenant`，源自 JWT），不接受前端传参——
    否则"选择办理哪个社区"就变成了越权入口。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    tenant = _tenant(request)
    op = _operator(request)
    from data.db_issue_code import CHANNELS
    people = []
    try:
        from data.db_user import managers_of  # 仅用于确认同社区读取可用（失败不阻断）
        managers_of(tenant)
        from data.db_core import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, name, role, community FROM user_profile "
                "WHERE COALESCE(community,'')=? AND role IN ('elderly','resident','grid') "
                "ORDER BY role, id LIMIT 200", (tenant,)).fetchall()
        people = [{"id": r["id"], "name": r["name"] or "", "role": r["role"]} for r in rows]
    except Exception as e:  # noqa: BLE001 — 读不到人不阻断服务台（可以走查用户手工录入）
        _log.warning("服务台读本社区人员失败（tenant=%s）：%s", tenant, e)
    return _ok({
        "community": tenant,
        "operator": op,
        "channels": [{"value": c, "label": CHANNELS.get(c, c)} for c in SERVICE_DESK_CHANNELS],
        "consent_values": list(CONSENT_VALUES),
        "people": people,
        "note": "社区取自您的登录身份，不能改。被代录的人必须在同一社区。",
    })


class DeskVoice(BaseModel):
    """系统帮我抽取"（把工作人员听到的原话转成结构化字段，供其确认）。"""
    text: str = Field(..., min_length=2, max_length=500)


@router.post("/extract")
def service_desk_extract(req: DeskVoice, request: Request):
    """从原话里抽取 位置 / 责任范围 / 紧急程度（**只给建议，由工作人员确认**）。

    复用老人端同一套契约（`utils/elderly_report`）：一套规则、两个入口，
    避免"服务站抽出来的字段和老人在家抽出来的不一样"。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from utils.elderly_report import build_report_confirm_payload
    ok, r, ask = build_report_confirm_payload(req.text, {})
    return _ok({
        "ok": bool(ok),
        "fields": (r or {}).get("fields") or {},
        "suggestion": (r or {}).get("suggestion") or {},
        "sources": (r or {}).get("sources") or {},
        "ask": ask or "",
    }, "" if ok else (ask or "信息还不完整，请补充后再提交"))


class DeskSubmit(BaseModel):
    """服务台提交（代录）。"""
    channel: str = Field(..., min_length=4, max_length=32)
    consent_status: str = Field(default="", max_length=16)
    station_id: str = Field(default="", max_length=32)
    # 当事人：要么给 id（本社区已有账号），要么给姓名+手机（走查用户）
    reporter_id: int = Field(default=0)
    reporter_name: str = Field(default="", max_length=40)
    reporter_phone: str = Field(default="", max_length=20)
    # 事项字段
    title: str = Field(..., min_length=2, max_length=200)
    description: str = Field(..., min_length=5, max_length=2000)
    location: str = Field(..., min_length=1, max_length=120)
    scope: str = Field(default="室外", pattern="^(室内|室外)$")
    urgency: str = Field(default="一般", max_length=8)
    raw_text: str = Field(default="", max_length=500)
    client_token: str = Field(default="", max_length=64)


@router.post("/submit")
def service_desk_submit(req: DeskSubmit, request: Request):
    """服务台代录建单（**记录"谁在替谁办理"**）。

    与老人端提交的关键差别：这里同时落 `channel` / `operator_id` / `station_id` / `consent_status`，
    并在返回里给**对外事项编号**。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    tenant = _tenant(request)
    op = _operator(request)

    if req.channel not in SERVICE_DESK_CHANNELS:
        return _fail(1003, f"办理方式不在允许范围内：{req.channel}")
    # 红线③：代录必须有授权依据
    if not (req.consent_status or "").strip():
        return _fail(1003, "请先记录授权情况（老人是否知情同意）再提交——"
                           "代录必须留下授权依据。")
    if req.consent_status not in CONSENT_VALUES:
        return _fail(1003, f"授权情况取值不认识：{req.consent_status}")

    # 幂等（与老人端同一套原子占位）
    from data.db_idempotency import begin, release, remember, wait_result
    reserved = False
    if req.client_token:
        state, prev = begin("service_desk", req.client_token, op["uid"])
        if state == "done":
            return _ok({**(prev or {}), "duplicate": True}, "这条已经提交过了")
        if state == "pending":
            prev = wait_result("service_desk", req.client_token, op["uid"], timeout=8)
            if prev is not None:
                return _ok({**prev, "duplicate": True}, "这条已经提交过了")
            return _fail(2003, "正在提交中，请稍等几秒再核对结果。")
        if state == "unknown":
            # 与老人端同口径：占位失败 = 无法确认是否已被领走 → **不办**（fail-closed）
            return _fail(2003, "提交状态暂时无法确认（系统繁忙）。请不要重复点击，稍后核对。")
        reserved = True

    # 红线②：被代录的人必须在**操作人所在社区**
    rid = int(req.reporter_id or 0)
    walk_in = False
    if rid:
        # ⚠️ 这里不能用 `row_in_tenant("user_profile", …)`：**`user_profile` 不是租户表**
        # （人的社区记在它自己的 `community` 列里，租户表白名单里没有它，传进去会抛 ValueError）。
        # 正确做法是按人的社区比对，且**取不到社区一律拒绝**（fail-closed）。
        from utils.tenant import normalize_tenant, tenant_of_user
        person_tenant = normalize_tenant(tenant_of_user(rid))
        if not person_tenant or person_tenant != tenant:
            if reserved:
                release("service_desk", req.client_token, op["uid"])
            _log.warning("服务台代录被拒：被代录人 #%s 属于「%s」，操作人社区「%s」（操作人 %s）",
                         rid, person_tenant or "（无社区）", tenant, op["uid"])
            return _fail(1003, "被代录的人不在您所在社区，不能代他提交。")
    else:
        # 走查用户：必须有姓名与手机号（否则网格员联系不上，等于建了张废单）
        walk_in = True
        if not (req.reporter_name or "").strip() or not (req.reporter_phone or "").strip():
            if reserved:
                release("service_desk", req.client_token, op["uid"])
            return _fail(1003, "走查居民请填写姓名与手机号（网格员要能联系上他）。")

    from data.db_repair import submit_issue
    iid, hint = submit_issue(
        title=req.title, category="公共设施", issue_type=req.scope,
        location=req.location, description=req.description,
        urgency=req.urgency, reporter_name=req.reporter_name or "居民",
        reporter_phone=req.reporter_phone, reporter_id=rid or None,
        channel=req.channel, operator_id=op["uid"], operator_role=op["role"],
        station_id=req.station_id, consent_status=req.consent_status,
        allow_missing_phone=False,
    )
    if iid <= 0:
        if reserved:
            release("service_desk", req.client_token, op["uid"])
        if hint == "safety":
            return _ok({"issue_id": 0, "safety": True}, "已记为安全提醒（这类情况不生成工单）")
        return _fail(2001, hint or "提交失败")

    # ⚠️ 走查用户：`submit_issue` 按 `reporter_id` 盖章，`reporter_id=0` 会盖成**空租户** →
    # 这张单在网格端（读取侧 fail-closed）**谁都看不见**。所以显式按**操作人的社区**补章。
    if walk_in or rid == 0:
        try:
            from data.db_core import get_db
            from utils.tenant import stamp_tenant_value
            with get_db() as conn:
                stamp_tenant_value(conn, "community_issues", iid, tenant)
                conn.commit()
        except Exception as e:  # noqa: BLE001 — 补章失败要留痕，绝不静默
            _log.warning("走查工单 #%s 按操作人社区补章失败（tenant=%s）：%s", iid, tenant, e)

    from data.db_issue_code import ensure_issue_code
    code = ""
    try:
        from data.db_core import get_db
        with get_db() as conn:
            code = ensure_issue_code(conn, iid)
    except Exception as e:  # noqa: BLE001
        _log.warning("服务台读取事项编号失败（issue=%s）：%s", iid, e)

    payload = {"issue_id": iid, "issue_code": code, "channel": req.channel,
               "operator_id": op["uid"], "community": tenant,
               "walk_in": walk_in}
    if req.client_token:
        remember("service_desk", req.client_token, op["uid"], payload)
    return _ok(payload, f"已登记，事项编号 {code}" if code else "已登记")


@router.get("/search")
def service_desk_search(request: Request, code: str = "", name: str = "",
                        phone_tail: str = "", building: str = "", date: str = "",
                        limit: int = 20):
    """工作人员查询（**编号 / 姓名 / 手机后四位 / 楼栋 / 提交日期** 五选一）。

    为什么服务台必须有它：老人**记不住编号**。让老人背编号是反适老设计；
    正确做法是工作人员用"姓名 / 楼栋 / 时间"任何一个都能查出来。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_issue_code import staff_search
    return _ok(staff_search(_tenant(request), code=code, name=name, phone_tail=phone_tail,
                            building=building, date=date, limit=limit))


class DeskReset(BaseModel):
    """结束本次办理（共享设备清理）。"""
    station_id: str = Field(default="", max_length=32)
    reporter_id: int = Field(default=0)


@router.post("/reset")
def service_desk_reset(req: DeskReset, request: Request):
    """**结束本次办理**：把服务端这一侧留下的临时痕迹清掉。

    诚实说明边界（很重要）：
      · 服务端能清的是**草稿**（`issue_drafts`，按当事人归属存的那份）；
      · **浏览器里的 sessionStorage / 页面状态由前端清**（见 `ServiceDesk.vue` 的
        `endSession()` —— token 放 sessionStorage 而不是 localStorage，关掉标签页即失效）；
      · **已建成的工单不清**（那是业务事实，不能说删就删）——返回里明确写清保留了哪些。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    tenant = _tenant(request)
    cleared = {"drafts": 0}
    if req.reporter_id:
        try:
            from data.db_core import get_db
            with get_db() as conn:
                cur = conn.execute("DELETE FROM issue_drafts WHERE user_id=?",
                                   (int(req.reporter_id),))
                cleared["drafts"] = int(cur.rowcount or 0)
                conn.commit()
        except Exception as e:  # noqa: BLE001 — 清不掉要报出来，不能假装清干净了
            _log.warning("服务台清理草稿失败（reporter=%s tenant=%s）：%s",
                         req.reporter_id, tenant, e)
            return _fail(2001, "本机临时数据未能清理干净，请让负责人检查后再交接")
    return _ok({**cleared, "station_id": req.station_id, "community": tenant,
                "kept": "已提交的工单不会被删除（那是业务记录）"},
               "本次办理已结束，可以接待下一位")
