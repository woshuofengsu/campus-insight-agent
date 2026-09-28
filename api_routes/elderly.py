# api_routes/elderly.py
"""老年端本体 + 老年关怀管理路由模块（从 api_web.py 拆出，P2-04）。

- router（prefix=/api/web/elderly）：老年端本体端点（含免登录 elder_id 解析）。
- manage_router（prefix=/api/web/elderly/manage）：负责人端老年关怀管理端点。
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _resolve_elder_uid, _tenant, _same_tenant
from api_routes.guards import write_route

import logging
_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/elderly", tags=["elderly"])
manage_router = APIRouter(prefix="/api/web/elderly/manage", tags=["elderly"])


def _touch(uid) -> None:
    """记一次**真实互动**（P3 安全闭环的输入：久未互动检测靠它）。

    ⚠️ 2026-09-24 修：`touch_active` 过去只被 Streamlit 备线调用（`ui/pages_elderly/home.py`），
    Vue 主路径从不写 `elderly_profile.last_active_at`（库里值停在 2026-08-21）
    → 主线上"久未互动"检测等于失效。现在在老年端真实交互处统一上报。

    失败只 warning，**绝不影响主流程**：记活跃不是业务前置条件，不能因为它坏了就让老人用不了。
    """
    if not uid:
        return
    try:
        from data.db_elderly import touch_active
        touch_active(uid)
    except Exception:  # noqa: BLE001
        _log.warning("记录老人活跃失败 uid=%s", uid, exc_info=True)


class MedicationAudit(BaseModel):
    approve: bool = Field(default=True)
    opinion: str = Field(default="")


class ContactAudit(BaseModel):
    approve: bool = Field(default=True)
    opinion: str = Field(default="")


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    phone: str = Field(..., min_length=11, max_length=20)
    relation: str = Field(default="家属")


class SosAction(BaseModel):
    action: str = Field(..., pattern="^(respond|close)$")
    handle_note: str = Field(default="")


class MedicationToggle(BaseModel):
    action: str = Field(..., pattern="^(pause|resume|taken|snooze)$")


class ContactCall(BaseModel):
    """联系家属/社区 —— **诚实呼叫**第一步（只到"准备拨打"为止）。

    ⚠️ **不再接受前端传姓名与号码**（v3 复核 §6-I8）：原来是 `target_name`/`target_phone`，
    等于"前端说打过谁就留痕谁"——号码可以随便传，留痕与真实行为无关。
    现在只接受**服务端能自己解析**的目标：
      · `contact_id`：紧急联系人 id（必须是本人或本人绑定老人名下的联系人）；
      · `community=True`：拨社区服务中心（号码取服务端配置）。
    """
    contact_id: int | None = None
    community: bool = False


class CallOutcome(BaseModel):
    """诚实呼叫第二步：把**手机上真实发生的事**报回来（卡 §6-B2）。

    允许的取值（与前端按钮一一对应）：
      · `dialer_opened` —— 已调起系统拨号盘（**只是打开拨号，不代表已接通**）；
      · `cancelled`     —— 老人在确认框/拨号盘上取消了；
      · `failed`        —— 没拨出去（设备不支持、权限被拒等）。
    ⚠️ **没有 `connected`（已接通）**：网页拿不到通话结果，任何"已接通/已通话"都只能是编的。
    真要证明接通，得接系统电话 API 或可信呼叫服务——本项目明确不做（也不宣称）。
    """
    stage: str = Field(..., pattern="^(dialer_opened|cancelled|failed)$")


class VoiceReport(BaseModel):
    text: str = Field(..., min_length=2, max_length=500)
    urgency: str = Field(default="一般")
    issue_type: str = Field(default="室内")


class ReportDraftIn(BaseModel):
    """报修草稿输入（v3 卡1）：只收**原话**，字段由服务端解析（不接受前端直接给"已确认字段"）。"""
    text: str = Field(..., min_length=2, max_length=500)


class ReportSubmitIn(BaseModel):
    """报修提交输入（v3 卡1 + 卡8）：原话 + **老人确认/补充**的值 + 幂等键。

    为什么原话要一起传：`location`/`scope` 是"老人说的"或"老人确认的"，
    而 title/description 永远是**原话**——分开保存才能做到
    「原始话语 / 系统建议 / 用户确认值 / 最终入库值」四者可区分（v3 复核 §6-I7）。

    `client_token`（卡8 / §6-I5）：前端**每次准备提交时生成一次**，网络重试/连点沿用同一个。
    服务端据此认出重复请求并返回**上一次的结果**（而不是再建一张工单）。
    """
    text: str = Field(..., min_length=2, max_length=500)
    location: str = Field(default="", max_length=80)
    scope: str = Field(default="", max_length=8)      # 室内 / 室外 / 空=按原话推断
    urgency: str = Field(default="", max_length=8)    # 一般 / 中等 / 紧急 / 空=按原话推断
    client_token: str = Field(default="", max_length=64)


class MedicationCreate(BaseModel):
    drug_name: str = Field(..., min_length=1, max_length=50)
    dosage: str = Field(default="")
    times: str = Field(default="08:00")
    repeat_rule: str = Field(default="每天")
    start_date: str = Field(default="")
    end_date: str = Field(default="")
    note: str = Field(default="")


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


# ---------------- 老年端本体 ----------------

@router.get("/home")
def web_elderly_home(request: Request):
    """老年端首页聚合：未读通知 / 天气摘要 / 用药状态 / 最近求助 + 人情味字段（M1）。"""
    from data.db_elderly_care import COMMUNITY_PHONE as _COMMUNITY_PHONE
    from data.db_elderly import get_profile
    from data.db_notice import get_notice_unread_count
    from data.db_elderly_care import get_latest_sos
    from data.db_weather import get_simplified_weather
    from api_routes.deps import _region
    from datetime import datetime
    from agent import tone
    u = _user(request)
    # 属地化（WS4）：老年端也必须带属地，否则与居民端口径不一致（演示一切屏就露馅）
    r = _region(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    _touch(uid)                       # 打开首页 = 一次真实互动（久未互动检测的输入）
    elderly = get_profile(uid) or {}
    health = elderly.get("health_info", {})
    due = 0
    try:
        from data.db_elderly_care import get_due_medications
        due = len(get_due_medications(uid))
    except Exception:
        pass
    weather = get_simplified_weather(r.district or r.city, r.city_id, region_label=r.label())
    # M1：称呼（优先 preferences.display_name，再退回 name）；语速（preferences.speech_rate）
    prefs = {}
    try:
        from data.db_user import get_user_by_id
        up = get_user_by_id(uid) or {}
        raw = up.get("preferences")
        if isinstance(raw, str) and raw.strip():
            import json
            prefs = json.loads(raw)
    except Exception:
        prefs = {}
    display_name = (prefs or {}).get("display_name") or u.get("name") or "大爷/阿姨"
    speech_rate = float((prefs or {}).get("speech_rate") or 0.9)
    # M1：今日一句关怀（天气 > 用药 > 久未活跃；久未活跃由最近活动时间推算，不新增列）
    days_inactive = 0
    try:
        from data.db_core import get_db
        with get_db() as conn:
            last = conn.execute(
                "SELECT MAX(created_at) m FROM ("
                "SELECT created_at FROM agent_dialogs WHERE user_id=? "
                "UNION ALL SELECT created_at FROM community_issues WHERE reporter_id=?)",
                (uid, uid)).fetchone()["m"]
            if last:
                days_inactive = (datetime.now() - datetime.fromisoformat(str(last).replace(" ", "T"))).days
    except Exception:
        days_inactive = 0
    care_line = tone.care_line(weather=weather, due_meds=due, days_inactive=days_inactive)
    # 最近联系（第七轮复审 P3-B）：前端 Home.vue 有 `v-if="home.latest_contact"` 的展示块，
    # 但此前 payload 里一直没有这个字段 → 那块永远不显示（前后端字段没对齐的典型）。
    # 后端本就有 get_latest_contact_call()，这里补上人文文案（拿不到给 None，前端自然不显示）。
    latest_contact = None
    try:
        from data.db_elderly_care import get_latest_contact_call
        rec = get_latest_contact_call(uid) if uid else None
        if rec:
            who = rec.get("target_name") or "家人"
            when = str(rec.get("created_at") or "")[:16].replace("T", " ")
            status = rec.get("status") or ""
            latest_contact = f"{who}（{status}）" if status else who
            if when:
                latest_contact = f"{latest_contact} · {when}"
    except Exception:
        latest_contact = None
    return _ok({
        "name": display_name,
        "greeting": tone.greeting(datetime.now().hour),
        "care_line": care_line,
        "speech_rate": speech_rate,
        "unread_notices": get_notice_unread_count("elderly", uid),
        "due_medications": due,
        "latest_sos": get_latest_sos(uid) if uid else None,
        "latest_contact": latest_contact,
        "bp": (health.get("blood_pressure") or [{}])[-1] if health.get("blood_pressure") else {},
        "weather": weather,
        "community_phone": _COMMUNITY_PHONE,
    })


def _elderly_profile(uid) -> dict:
    """老人资料 + **解密后的手机号**。

    `get_user_by_id` 返回的 `phone` 明文列按约定是空的（密文在 `phone_enc`），
    所以这里额外用 `get_user_phone()` 补上真实号码；拿不到就是空串，
    调用方必须据此**如实提示补号**，绝不写占位假号。
    """
    try:
        from data.db_user import get_user_by_id, get_user_phone
        prof = get_user_by_id(uid) or {}
        prof["phone"] = get_user_phone(uid)
        return prof
    except Exception as e:  # noqa: BLE001
        _log.warning("读取老人资料失败 uid=%s：%s", uid, e)
        return {}


def _report_draft_payload(text: str, profile: dict) -> dict:
    """生成报修确认摘要（v3 卡1）：结构化字段 + 缺失项 + 追问话术 + **每个字段的来源**。"""
    from utils.elderly_report import extract_report_fields
    r = extract_report_fields(text, profile)
    cleaned = _correct_report_text(text)
    return {
        "original_text": text,
        "fields": r["fields"],
        "sources": r["sources"],
        "suggestion": {
            **r["suggestion"],
            # 系统对措辞的建议（如去掉重复标点）——**只作提示**，入库的仍是老人确认过的原话
            "title_hint": cleaned if cleaned != text else "",
        },
        "missing": r["missing"],
        "ask": r["ask"],
        "need_more": bool(r["missing"]),
        "can_submit": not r["missing"],
        "note": r["note"],
        # 联系方式不要求老人填：用资料里的；没有就如实说"缺手机号"，**绝不写假号**
        "reporter_phone_ready": bool(str(profile.get("phone") or "").strip()),
    }


@router.get("/orders")
def web_elderly_orders(request: Request, limit: int = 10):
    """老人端「我的报修」：**带老人看得懂的进度**（v3 复核 §6-I9）。

    只返回**本人**（或已绑定家属名下的老人）报的工单，并按社区过滤；
    每条都附一段纯函数算出来的进度块：现在到哪一步 / 下一步谁做 / 按社区规定还要多久 /
    **是否已经超时**（超时就明说，不让老人干等）。
    """
    from data.db_repair import get_issues
    from utils.issue_progress import elderly_progress
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    if not uid:
        return _fail(1001, "请先登录")
    rows = get_issues(reporter_id=uid, limit=max(1, min(int(limit or 10), 50)))
    out = []
    for r in rows:
        d = dict(r)
        d["progress"] = elderly_progress(d)
        # 老人端不需要看到完整手机号等敏感字段
        for k in ("reporter_phone", "agent_phone", "reporter_phone_enc", "agent_phone_enc"):
            d.pop(k, None)
        out.append(d)
    return _ok(out)


@router.post("/report/draft")
def web_elderly_report_draft(req: ReportDraftIn, request: Request):
    """老人报修 · 第一步：把原话变成**可确认的结构化摘要**（不写库、不建单）。

    解决的是 v3 复核 §6-B1/§6-I6：原来老人说一句"楼道灯坏了"，后端就把位置回落成"社区"直接建单
    ——库里真的留下了 `location='社区'` 的**无法派单工单**。现在缺位置/责任范围时返回
    `need_more=true` + `ask`（一句能听懂的话），**绝不建单**。
    """
    uid = _resolve_elder_uid(request) or _user(request).get("uid")
    profile = _elderly_profile(uid)
    out = _report_draft_payload(req.text, profile)
    if not out["reporter_phone_ready"]:
        out["phone_hint"] = "您的资料里还没有手机号，网格员联系不上您；请让网格员帮您补一个。"
    return _ok(out, "请确认信息" if not out["need_more"] else out["ask"])


@router.post("/report/submit")
def web_elderly_report_submit(req: ReportSubmitIn, request: Request):
    """老人报修 · 第二步：**校验必填 + 提交**（v3 卡1 的闸门）。

    返回体明确分开四段值（v3 复核 §6-I7）：
      `original_text`（老人原话）/ `suggestion`（系统建议）/ `confirmed`（最终入库值）/ `sources`（每个字段来源）。
    缺必填 → 返回 2002 + 追问话术，**不建单**；资料里没手机号 → 明确拒绝，**不写 13800000000 这种假号**。
    """
    from data.db_idempotency import recall, remember
    from data.db_repair import submit_issue
    from tools.action_report_issue import _llm_classify
    from utils.elderly_report import build_report_confirm_payload
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    _touch(uid)

    # 幂等（卡8 / §6-I5）：同一个 token 重复提交 → 直接返回**上一次的结果**。
    # 这一步在"校验必填"之前：重试的请求本来就带着完整的已确认字段，
    # 但即便字段被前端改动了，也不该凭同一个 token 建第二张单（老人的意图只有一次）。
    if req.client_token:
        prev = recall("elderly_report", req.client_token, uid)
        if prev is not None:
            _log.info("老人报修重复提交（幂等命中）：uid=%s token=%s → 工单 #%s",
                      uid, req.client_token, prev.get("issue_id"))
            return _ok({**prev, "duplicate": True},
                       f"这条报修已经提交过了，工单号 {prev.get('issue_id')}")

    profile = _elderly_profile(uid)

    ok_, r, ask = build_report_confirm_payload(
        req.text, profile, confirmed_location=req.location,
        confirmed_scope=req.scope, confirmed_urgency=req.urgency)
    if not ok_:
        return _fail(2002, ask or "信息还不完整，请补充后再提交")

    phone = str(profile.get("phone") or "").strip()
    if not phone:
        # 诚实：没有手机号就不建单（假号会让网格员打不通，还可能被当成真实数据引用）
        return _fail(2002, "您的资料里还没有手机号，网格员联系不上您；请让网格员帮您补一个手机号再报修。")

    fields = r["fields"]
    category, urgency_llm = _llm_classify(req.text, "")
    urgency = fields["urgency"] or urgency_llm or "一般"
    iid, hint = submit_issue(
        title=fields["title"], category=category, issue_type=fields["issue_type"],
        location=fields["location"], description=fields["description"],
        urgency=urgency, reporter_name=profile.get("name") or u.get("name") or "老人",
        reporter_phone=phone, reporter_id=uid,
    )
    if iid <= 0:
        if hint == "safety":
            payload = {"issue_id": 0, "safety": True, "confirmed": fields,
                       "original_text": req.text, "suggestion": r["suggestion"],
                       "sources": r["sources"]}
            if req.client_token:
                remember("elderly_report", req.client_token, uid, payload)
            return _ok(payload, "已记为安全提醒（这类情况不生成工单，负责人会看到）")
        return _fail(2001, hint or "上报失败")
    payload = {
        "issue_id": iid,
        "original_text": req.text,
        "suggestion": r["suggestion"],
        "confirmed": fields,
        "sources": r["sources"],
        "category": category,
        "client_token": req.client_token,
    }
    if req.client_token:
        remember("elderly_report", req.client_token, uid, payload)
    return _ok(payload, f"上报成功，工单号 {iid}，请等待审核")


@router.get("/report/status")
def web_elderly_report_status(request: Request, token: str = ""):
    """「我刚才到底提交成功了吗？」—— 按幂等 token 查询（v3 复核 §6-I5）。

    **为什么必须有这个接口**：老人点了上报之后如果断网/超时，页面只知道"没收到回应"，
    既不知道成没成、也拿不到工单号。这时候**不能诱导老人再点一次**（会重复建单），
    正确做法是给出一个"结果未知 → 正在核对"的出口，由服务端按 token 查真实结果：
      · `submitted=True` → 带工单号（页面可以放心告诉老人"已经报上了"）；
      · `submitted=False` → 明确"这次没有提交成功"，可以重试（token 仍可复用）。

    这不是"伪造一个成功状态"，而是**把不确定如实展示**并把真实结果查出来。
    """
    from data.db_idempotency import recall, valid_key
    uid = _resolve_elder_uid(request) or _user(request).get("uid")
    if not valid_key(token):
        return _fail(1003, "缺少有效的提交编号")
    prev = recall("elderly_report", token, uid)
    if prev is None:
        return _ok({"submitted": False, "issue_id": 0, "known": False},
                   "这次没有查到已提交的记录，可以重新提交")
    return _ok({"submitted": True, "known": True, **prev},
               f"已经提交过了，工单号 {prev.get('issue_id')}")


@router.post("/voice-report")
def web_elderly_voice_report(req: VoiceReport, request: Request):
    """老年端语音报修（**严格版**：缺位置/责任范围就不建单）。

    ⚠️ 这是给旧版前端留的兼容入口；新版走「草稿 → 确认 → 提交」两步
    （`/report/draft`、`/report/submit`）。两者共用同一套必填契约，
    所以**不会再出现** `location='社区'` 那种无法派单的工单。
    """
    uid = _resolve_elder_uid(request) or _user(request).get("uid")
    profile = _elderly_profile(uid)
    from utils.elderly_report import build_report_confirm_payload
    ok_, r, ask = build_report_confirm_payload(
        req.text, profile, confirmed_urgency=req.urgency or "")
    if not ok_:
        return _fail(2002, ask or "请补充位置或说明是家里还是公共地方")
    body = ReportSubmitIn(text=req.text, location=r["fields"]["location"],
                          scope=r["fields"]["issue_type"], urgency=r["fields"]["urgency"])
    return web_elderly_report_submit(body, request)


@router.post("/medications")
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
        return _fail(2001, msg)
    return _ok({"reminder_id": mid}, "已提交，待审核")


# 老年端资源的归属列（授权矩阵 §三：同社区 ≠ 有权操作这个人）
_RESOURCE_OWNER_COL = {
    "emergency_contacts": "user_id",
    "medication_reminders": "user_id",
    "emergency_calls": "user_id",
}


def _resource_owner_uid(table: str, row_id: int) -> int:
    """取资源归属人 uid；查不到/异常返回 0（fail-closed，绝不放行）。"""
    from data.db_core import get_db
    if table not in _RESOURCE_OWNER_COL:
        _log.warning("未登记的老年端资源表：%s（按无权处理）", table)
        return 0
    col = _RESOURCE_OWNER_COL[table]
    try:
        with get_db() as conn:
            row = conn.execute(f"SELECT {col} FROM {table} WHERE id=?", (row_id,)).fetchone()
    except Exception as e:  # noqa: BLE001 — 查不动绝不放行
        _log.warning("查资源归属失败 table=%s id=%s：%s", table, row_id, e)
        return 0
    if not row:
        return 0
    try:
        return int(row[col] or 0)
    except (TypeError, ValueError):
        return 0


def _owns_resource(request: Request, table: str, row_id: int, *,
                   allow_family: bool = True) -> bool:
    """授权矩阵落点：**这道校验解决"有权操作这个人"**（`_same_tenant` 只解决"同社区"）。

    - `allow_family=True`（默认）：本人，或**已绑定家属**代本人操作
      （绑定关系由 `_resolve_elder_uid` 校验：`?elder_id=X` 且当前用户是 X 的绑定家属）；
    - `allow_family=False`：**只有本人**——用于"打卡"这类只能老人自己做的事（矩阵 D1/D4）。
    """
    u = _user(request)
    acting = None
    if allow_family:
        acting = _resolve_elder_uid(request)
    acting = acting or u.get("uid")
    owner = _resource_owner_uid(table, row_id)
    if not owner or not acting:
        return False
    return int(owner) == int(acting)


@router.post("/medications/{rid}/modify")
@write_route(table="medication_reminders", id_param="rid", owner_column="user_id",
             allow_family=True,
             note="改用药：本人或已绑定家属；租户闸门 + 所有权由装饰器统一执行")
def web_medication_modify(rid: int, req: MedicationCreate, request: Request):
    """修改用药提醒 → 重新审核（审核期间原规则继续播报）。

    授权（矩阵 D1）：**本人或已绑定家属**可改；网格员不代改（只审核）。
    """
    from data.db_elderly_care import modify_medication
    u = _user(request)
    times = [t.strip() for t in req.times.replace("，", ",").split(",") if t.strip()]
    ok_, msg = modify_medication(
        rid, u.get("name") or "老人", req.drug_name, req.dosage, times,
        repeat_rule=req.repeat_rule, start_date=req.start_date, end_date=req.end_date,
        note=req.note, actor=u.get("name") or "老人",
    )
    if not ok_:
        return _fail(2001, msg)
    return _ok({"reminder_id": rid}, "已提交修改，待重新审核")


@router.get("/medications")
def web_medication_list(request: Request):
    from data.db_elderly_care import list_medication_reminders
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    return _ok([dict(r) for r in list_medication_reminders(uid)])


@router.post("/emergency")
def web_emergency_trigger(request: Request):
    """紧急求助触发（家属代操作模式由前端隐藏按钮，后端校验）。"""
    from data.db_elderly_care import trigger_sos
    from data.db_user import get_user_by_id, get_bound_elderly
    u = _user(request)
    _touch(_resolve_elder_uid(request) or u.get("uid"))
    profile = get_user_by_id(u.get("uid")) or {}
    # 家属绑定模式：禁止家属代替老人触发
    try:
        bound = get_bound_elderly(u.get("uid"))
        if bound and bound.get("id") != u.get("uid"):
            return _fail(1003, "家属不能代替老人触发紧急求助")
    except Exception:
        pass
    cid, msg = trigger_sos(u.get("uid"), actor=profile.get("name") or "老人")
    if cid <= 0:
        return _fail(2001, msg or "触发失败")
    return _ok({"call_id": cid}, "已触发紧急求助")


@router.get("/emergency/status")
def web_emergency_status(request: Request):
    from data.db_elderly_care import get_latest_sos
    u = _user(request)
    uid = _resolve_elder_uid(request) or u.get("uid")
    return _ok(get_latest_sos(uid))


@router.get("/emergency-contacts")
def web_contacts_list(request: Request):
    from data.db_elderly_care import list_emergency_contacts
    u = _user(request)
    out = []
    for r in list_emergency_contacts(u.get("uid")):
        d = dict(r)
        if not d.get("phone") and d.get("phone_enc"):
            try:
                from utils.crypto import get_crypto
                d["phone"] = get_crypto().decrypt(d["phone_enc"])
            except Exception:
                d["phone"] = ""
        out.append(d)
    return _ok(out)


@router.post("/emergency-contacts")
def web_contacts_create(req: ContactCreate, request: Request):
    from data.db_elderly_care import add_emergency_contact
    u = _user(request)
    cid, msg = add_emergency_contact(u.get("uid"), req.name, req.phone, req.relation,
                                     actor=u.get("name") or "老人")
    if cid <= 0:
        return _fail(2001, msg)
    return _ok({"contact_id": cid}, "已提交，待审核")


@router.post("/emergency-contacts/{cid}/delete")
@write_route(table="emergency_contacts", id_param="cid", owner_column="user_id",
             allow_family=True,
             note="删联系人：本人或已绑定家属；网格员不代改（只审核）")
def web_contacts_delete(cid: int, request: Request):
    """删除紧急联系人。

    授权（矩阵 D1）：**本人或已绑定家属**；网格员不代改（只审核）。
    原来只有 `_same_tenant` → 同社区任何居民都能删别人家老人的联系人（Codex 评审 F2）。
    """
    from data.db_elderly_care import delete_emergency_contact
    u = _user(request)
    ok_, msg = delete_emergency_contact(cid, actor=u.get("name") or "老人")
    if not ok_:
        return _fail(2001, msg)
    return _ok({"contact_id": cid}, "已删除")


@router.post("/emergency/{call_id}/action")
@write_route(roles=("grid",), table="emergency_calls", id_param="call_id",
             note="SOS 处置：只有本社区网格员，且必须过租户闸门")
def web_sos_action(call_id: int, req: SosAction, request: Request):
    """SOS 响应/结束（处置）。

    授权（矩阵）：**只有本社区网格员能处置**——原来只查同社区，
    于是同社区普通居民也能"处置"别人家老人的求助（Codex 评审 F2）。
    现在角色 + 租户闸门由 `@write_route` 统一执行（见 `api_routes/guards.py`）。
    """
    from data.db_elderly_care import respond_sos, end_sos
    actor = _user(request).get("name") or "负责人"
    if req.action == "respond":
        ok_, msg = respond_sos(call_id, actor=actor)
    else:
        ok_, msg = end_sos(call_id, req.handle_note, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"call_id": call_id}, "操作成功")


@router.post("/medications/{rid}/toggle")
@write_route(table="medication_reminders", id_param="rid", owner_column="user_id",
             allow_family=False,
             note="打卡/暂停/恢复：**只能老人本人**（家属代打卡等于伪造服药记录）")
def web_medication_toggle(rid: int, req: MedicationToggle, request: Request):
    """用药：打卡（taken/snooze）与暂停/恢复。

    授权（矩阵 D1/§二）：**只能老人本人**（`allow_family=False`）——
    家属替老人打卡等于伪造服药记录；家属要停就走去审核的修改流程。
    租户闸门 + 所有权由 `@write_route` 统一执行（原来这两类检查是手写的）。
    """
    from data.db_elderly_care import pause_medication, resume_medication, mark_intake
    from agent.tone import human_status  # noqa: F401
    actor = _user(request).get("name") or "老人"
    uid = _user(request).get("uid")          # 打卡/暂停只能本人，不用 elder_id 代操作
    _touch(uid)
    if req.action == "taken" or req.action == "snooze":
        ok_, msg, streak = mark_intake(uid, rid, action=req.action)
        encourage = f"连续 {streak} 天按时吃药，真棒！" if streak >= 3 else msg
        if not ok_:
            return _ok({"reminder_id": rid, "streak": streak, "already": True}, msg)  # 重复打卡幂等
        return _ok({"reminder_id": rid, "streak": streak}, encourage)
    if req.action == "pause":
        ok_, msg = pause_medication(rid, actor=actor)
    else:
        ok_, msg = resume_medication(rid, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"reminder_id": rid}, "操作成功")


@router.post("/contact")
def web_elderly_contact(req: ContactCall, request: Request):
    """联系家属/社区（诚实呼叫 · 第一步：准备拨打）。

    **为什么改成两步**（v3 复核 §6-B2）：原来后端只写一条"已结束"的记录，前端却显示
    "正在呼叫 XXX" —— 页面在**替手机撒谎**。真实的 H5 只能做一件事：调起系统拨号盘
    （`tel:`），**拨出/接通/挂断都由手机掌控，网页看不到**。所以：
      第一步（本接口）：服务端解析号码 → 落一条「准备拨打」的记录 → 返回号码供 `tel:` 导航；
      第二步（`/contact/{call_id}/outcome`）：前端按**实际发生的事**回填
      「已打开拨号盘 / 已取消 / 拨打失败」。
    留痕里**不会出现"已接通"**，因为网页没有任何证据能支撑它。
    """
    from data.db_elderly_care import get_emergency_contact, log_emergency_call
    u = _user(request)
    uid = u.get("uid")
    actor = u.get("name") or "老人"
    # 记录归属：**老人本人**（家属代操作时归到被绑定的老人名下，与老年关怀模块其它数据一致）
    subject_uid = _resolve_elder_uid(request) or uid

    name, phone = "", ""
    if req.community:
        # 社区服务中心号码由**服务端配置**解析（不接受前端传值）
        try:
            from data.db_elderly import get_profile
            prof = get_profile(subject_uid) or {}
            phone = str(prof.get("community_phone") or "").strip()
        except Exception as e:  # noqa: BLE001
            _log.warning("读取社区电话失败：%s", e)
        name = "社区服务中心"
        if not phone:
            return _fail(2001, "暂无社区服务电话，请联系网格员补充")
    else:
        if not req.contact_id:
            return _fail(1003, "请选择要联系的紧急联系人")
        row = get_emergency_contact(req.contact_id)
        if not row:
            return _fail(1004, "联系人不存在")
        # ⚠️ 号码是**加密列**：`get_emergency_contact` 返回原始行（`phone` 明文列为空），
        # 必须解密后再用——旧代码之所以没踩到这个坑，是因为它**根本没用库里的号码**，
        # 而是直接用前端传来的 target_phone（这正是 §6-I8 的问题所在）。
        from data.db_elderly_care import _dec_contact
        row = _dec_contact(row)
        # 授权（矩阵 D2/D3）：只能拨**本人或已绑定家属名下**的联系人
        # ——与联系人删除/修改同一口径，避免"知道 id 就能拨别人家老人的家属"
        if not _owns_resource(request, "emergency_contacts", req.contact_id, allow_family=True):
            return _fail(1003, "无权限联系该联系人（不是您名下的联系人）")
        if (row.get("status") or "") != "审核通过":
            return _fail(2001, "该联系人还在审核中，暂时不能呼叫")
        name = row.get("name") or ""
        phone = (row.get("phone") or "").strip()
        if not phone:
            return _fail(2001, "该联系人号码不可用，请联系网格员")

    try:
        call_id = log_emergency_call(subject_uid, "contact", name, phone,
                                     "准备拨打", status="待确认", actor=actor)
    except Exception as e:  # noqa: BLE001
        _log.warning("拨打记录异常：%s", e)
        return _fail(2001, "拨打记录失败，请稍后再试")
    return _ok({
        "call_id": call_id,
        "name": name,
        "phone": phone,          # 号码由服务端给出，前端只用于 `tel:` 导航
        "tel": f"tel:{phone}",
        "stage": "准备拨打",
        "hint": "已准备好拨打，请在手机上完成呼叫（网页无法知道是否接通）",
    }, "准备拨打")


@router.post("/contact/{call_id}/outcome")
def web_elderly_contact_outcome(call_id: int, req: CallOutcome, request: Request):
    """诚实呼叫 · 第二步：回填**手机上真实发生的事**（打开拨号盘 / 取消 / 失败）。

    只允许改**自己**刚才那条「准备拨打」记录，且只能改一次语义明确的终态；
    「已接通」在数据层被显式排除（网页拿不到通话结果，不许编）。
    """
    from data.db_core import get_db as _gdb
    if not _same_tenant(request, "emergency_calls", call_id):
        return _fail(1003, "无权限更新该拨打记录（非本社区）")
    # 所有权：记录归**老人本人**名下，所以"本人或已绑定家属"都可以回填结果
    if not _owns_resource(request, "emergency_calls", call_id, allow_family=True):
        return _fail(1003, "无权限更新他人的拨打记录")
    with _gdb() as conn:
        row = conn.execute(
            "SELECT user_id, call_type, result FROM emergency_calls WHERE id=?", (call_id,)
        ).fetchone()
        if not row:
            return _fail(1004, "拨打记录不存在")
        if row["call_type"] != "contact":
            return _fail(2001, "该记录不是联系拨打记录")
        result_map = {
            "dialer_opened": ("已打开拨号盘（是否接通以手机通话记录为准）", "已结束"),
            "cancelled": ("已取消", "已结束"),
            "failed": ("拨打失败", "已结束"),
        }
        new_result, new_status = result_map[req.stage]
        conn.execute("UPDATE emergency_calls SET result=?, status=? WHERE id=?",
                     (new_result, new_status, call_id))
        conn.commit()
    from data.db_elderly_care import MODULE as CARE_MODULE
    from data.db_notifications import log_activity
    log_activity(_user(request).get("name") or "老人", "联系拨打结果", "emergency_call",
                 call_id, "", module=CARE_MODULE, after_value=new_result,
                 detail=f"前端回填阶段：{req.stage}（网页最多只能记录到「已打开拨号盘」）")
    return _ok({"call_id": call_id, "stage": req.stage, "result": new_result}, new_result)


# ---------------- 负责人端老年关怀管理 ----------------

@manage_router.get("/medications")
def web_manage_medications(request: Request, status: str = ""):
    """负责人端用药提醒列表（全部老人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import list_medication_reminders
    rows = list_medication_reminders(status=status or None, tenant=_tenant(request))
    return _ok([dict(r) for r in rows])


@manage_router.post("/medications/{rid}/audit")
@write_route(roles=("grid",), table="medication_reminders", id_param="rid",
             note="负责人审核用药提醒：本社区 + 网格员角色")
def web_manage_medication_audit(rid: int, req: MedicationAudit, request: Request):
    """负责人审核用药提醒（角色与租户闸门由 `@write_route` 统一执行）。"""
    from data.db_elderly_care import audit_medication
    actor = _user(request).get("name") or "负责人"
    ok_, msg = audit_medication(rid, req.approve, opinion=req.opinion, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"reminder_id": rid}, "审核完成")


@manage_router.get("/contacts")
def web_manage_contacts(request: Request, status: str = ""):
    """负责人端紧急联系人列表（全部老人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import list_emergency_contacts
    rows = list_emergency_contacts(tenant=_tenant(request))
    out = [dict(r) for r in rows]
    if status:
        out = [c for c in out if c.get("status") == status]
    return _ok(out)


@manage_router.post("/contacts/{cid}/audit")
@write_route(roles=("grid",), table="emergency_contacts", id_param="cid",
             note="负责人审核紧急联系人：本社区 + 网格员角色")
def web_manage_contact_audit(cid: int, req: ContactAudit, request: Request):
    """负责人审核紧急联系人（角色与租户闸门由 `@write_route` 统一执行）。"""
    from data.db_elderly_care import audit_emergency_contact
    actor = _user(request).get("name") or "负责人"
    ok_, msg = audit_emergency_contact(cid, req.approve, opinion=req.opinion, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"contact_id": cid}, "审核完成")


@manage_router.get("/inactive")
def web_manage_inactive(request: Request, days: int = 5, limit: int = 20):
    """负责人端：久未活跃老人（M4 关怀提示，给网格员抓手）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    try:
        from data.db_care_proactive import list_inactive_elderly
        return _ok(list_inactive_elderly(days=days, limit=limit, tenant=_tenant(request)))
    except Exception as e:  # noqa: BLE001
        return _fail(2001, "查询失败，请重试")


@manage_router.get("/sos")
def web_manage_sos(request: Request, status: str = ""):
    """负责人端紧急求助列表。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import get_sos_calls
    rows = get_sos_calls(status=status or None, limit=50, tenant=_tenant(request))
    return _ok([dict(r) for r in rows])


# ---------------- P4：老年健康记录（血压 / 血糖）----------------

class VitalCreate(BaseModel):
    """录入一条健康记录：血压给 sys/dia，血糖给 glucose。"""
    kind: str = Field(..., pattern="^(bp|glucose)$")
    sys: int | None = Field(default=None)
    dia: int | None = Field(default=None)
    glucose: float | None = Field(default=None)
    measure_when: str = Field(default="random")   # fasting / postprandial / random
    measured_at: str = Field(default="")          # 留空=现在
    note: str = Field(default="", max_length=200)


@router.post("/vitals")
def web_vital_create(req: VitalCreate, request: Request):
    """老年端录一条血压/血糖，返回分级与固定提示语（不诊断）。

    授权（矩阵 D4）：**只能本人录入**——家属"代录"等于替老人造健康数据，
    展示与告警都会失真，所以不开放；家属仍可**查看**（走 `manage/vitals` 且限本社区、需绑定）。
    """
    from data.db_vitals import add_vital, notify_abnormal_vital
    u = _user(request)
    if _resolve_elder_uid(request) and _resolve_elder_uid(request) != u.get("uid"):
        return _fail(1003, "健康记录只能老人本人录入（家属可查看，不可代录）")
    uid = u.get("uid")
    _touch(uid)
    vid, level, meta = add_vital(uid, req.kind, req.sys, req.dia, req.glucose,
                                 req.measure_when, req.measured_at,
                                 recorder_id=u.get("uid"), source="self", note=req.note)
    if vid <= 0:
        return _fail(1003, meta.get("error") or "录入失败")
    value_text = (f"{req.sys}/{req.dia} mmHg" if req.kind == "bp" and req.sys
                  else f"{req.glucose} mmol/L")
    notified = notify_abnormal_vital(uid, req.kind, level, meta.get("hint", ""), value_text)
    return _ok({"id": vid, "level": level, "hint": meta.get("hint", ""), "notified": notified})


@router.get("/vitals")
def web_vitals_list(request: Request, kind: str = "", limit: int = 14):
    """老年端：自己的健康记录（按测量时间倒序，带分级与提示语）。"""
    from data.db_vitals import list_vitals
    uid = _resolve_elder_uid(request) or _user(request).get("uid")
    return _ok(list_vitals(uid, kind, limit=limit))


@router.get("/vitals/summary")
def web_vitals_summary(request: Request, limit: int = 7):
    """老年端首页摘要：最新血压/血糖 + 各自趋势一句话。"""
    from data.db_vitals import vitals_summary
    uid = _resolve_elder_uid(request) or _user(request).get("uid")
    return _ok(vitals_summary(uid, limit=limit))


@manage_router.get("/vitals")
def web_manage_vitals(request: Request, uid: int = 0, kind: str = "", limit: int = 14):
    """负责人端：看某位老人的健康记录（网格员关怀页用）。

    多租户（Codex 评审 F1 修复）：**先按社区授权，再取数据**。
    原实现只校验 grid 角色就按传入 uid 取值 → A 社区网格员可读到 B 社区老人的健康记录。
    现先确认目标老人在请求者本社区；不在则一律 1003，不区分"不存在"与"非本社区"
    （否则可用错误码探测其他社区有哪些老人）。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    if not uid:
        return _fail(1003, "请指定老人")
    if not _elder_in_tenant(request, uid):
        return _fail(1003, "无权限查看该老人（非本社区）")
    from data.db_vitals import list_vitals, vitals_summary
    return _ok({"records": list_vitals(uid, kind, limit=limit),
                "summary": vitals_summary(uid)})


def _elder_in_tenant(request: Request, uid: int) -> bool:
    """目标用户是否属于请求者所在社区（fail-closed：租户为空/查不到/跨社区一律 False）。"""
    tenant = _tenant(request)
    if not tenant:
        return False
    from data.db_core import get_db
    from utils.tenant import normalize_tenant
    try:
        with get_db() as conn:
            row = conn.execute("SELECT community FROM user_profile WHERE id=?", (uid,)).fetchone()
    except Exception as e:  # noqa: BLE001 — 查不动绝不放行
        _log.warning("校验老人归属失败 uid=%s：%s", uid, e)
        return False
    return bool(row) and normalize_tenant(row["community"]) == tenant


@manage_router.get("/elders")
def web_manage_elders(request: Request):
    """负责人端：老人下拉列表（网格员选对象用，避免手输用户 ID）。

    多租户（Codex 评审 F1 修复）：**只列本社区老人**——原实现只筛 role/is_active，
    会把全平台老人（含姓名与社区）返回给任意社区的网格员。租户为空时返回空列表。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    tenant = _tenant(request)
    if not tenant:
        return _ok([])
    from data.db_core import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, community FROM user_profile "
            "WHERE role='elderly' AND is_active=1 AND community=? ORDER BY id",
            (tenant,)).fetchall()
    return _ok([dict(r) for r in rows])
