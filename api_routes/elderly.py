# api_routes/elderly.py
"""老年端本体 + 老年关怀管理路由模块（从 api_web.py 拆出，P2-04）。

- router（prefix=/api/web/elderly）：老年端本体端点（含免登录 elder_id 解析）。
- manage_router（prefix=/api/web/elderly/manage）：负责人端老年关怀管理端点。
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _resolve_elder_uid

router = APIRouter(prefix="/api/web/elderly", tags=["elderly"])
manage_router = APIRouter(prefix="/api/web/elderly/manage", tags=["elderly"])


class MedicationAudit(BaseModel):
    approve: bool = Field(default=True)
    opinion: str = Field(default="")


class ContactAudit(BaseModel):
    approve: bool = Field(default=True)
    opinion: str = Field(default="")


class ContactCreate(BaseModel):
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=11)
    relation: str = Field(default="家属")


class SosAction(BaseModel):
    action: str = Field(..., pattern="^(respond|close)$")
    handle_note: str = Field(default="")


class MedicationToggle(BaseModel):
    action: str = Field(..., pattern="^(pause|resume)$")


class ContactCall(BaseModel):
    target_name: str = Field(default="")
    target_phone: str = Field(default="")


class VoiceReport(BaseModel):
    text: str = Field(..., min_length=2)
    urgency: str = Field(default="一般")
    issue_type: str = Field(default="室内")


class MedicationCreate(BaseModel):
    drug_name: str = Field(..., min_length=1)
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
    """老年端首页聚合：未读通知 / 天气摘要 / 用药状态 / 最近求助。"""
    from data.db_elderly_care import COMMUNITY_PHONE as _COMMUNITY_PHONE
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
    return _ok({
        "name": u.get("name") or "大爷/阿姨",
        "unread_notices": get_notice_unread_count("elderly", uid),
        "due_medications": due,
        "latest_sos": get_latest_sos(uid) if uid else None,
        "bp": (health.get("blood_pressure") or [{}])[-1] if health.get("blood_pressure") else {},
        "weather": get_simplified_weather(""),
        "community_phone": _COMMUNITY_PHONE,
    })


@router.post("/voice-report")
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
        return _fail(2001, hint or "上报失败")
    return _ok({"issue_id": iid, "category": category, "corrected": corrected,
                "original": req.text}, "上报成功")


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


@router.post("/medications/{rid}/modify")
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
                from utils.crypto import Crypto
                d["phone"] = Crypto().decrypt(d["phone_enc"])
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
def web_contacts_delete(cid: int, request: Request):
    from data.db_elderly_care import delete_emergency_contact
    u = _user(request)
    ok_, msg = delete_emergency_contact(cid, actor=u.get("name") or "老人")
    if not ok_:
        return _fail(2001, msg)
    return _ok({"contact_id": cid}, "已删除")


@router.post("/emergency/{call_id}/action")
def web_sos_action(call_id: int, req: SosAction, request: Request):
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
def web_medication_toggle(rid: int, req: MedicationToggle, request: Request):
    from data.db_elderly_care import pause_medication, resume_medication
    actor = _user(request).get("name") or "老人"
    if req.action == "pause":
        ok_, msg = pause_medication(rid, actor=actor)
    else:
        ok_, msg = resume_medication(rid, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"reminder_id": rid}, "操作成功")


@router.post("/contact")
def web_elderly_contact(req: ContactCall, request: Request):
    """联系家属/社区（拨号留痕）。"""
    from data.db_elderly_care import log_emergency_call
    u = _user(request)
    try:
        log_emergency_call(u.get("uid"), "contact", req.target_name, req.target_phone,
                           "拨出", status="已结束", actor=u.get("name") or "老人")
        return _ok({"dialed": req.target_name or req.target_phone}, "已记录拨打")
    except Exception as e:  # noqa: BLE001
        return _fail(2001, f"拨打记录失败：{e}")


# ---------------- 负责人端老年关怀管理 ----------------

@manage_router.get("/medications")
def web_manage_medications(request: Request, status: str = ""):
    """负责人端用药提醒列表（全部老人）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import list_medication_reminders
    rows = list_medication_reminders(status=status or None)
    return _ok([dict(r) for r in rows])


@manage_router.post("/medications/{rid}/audit")
def web_manage_medication_audit(rid: int, req: MedicationAudit, request: Request):
    """负责人审核用药提醒。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
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
    rows = list_emergency_contacts()
    out = [dict(r) for r in rows]
    if status:
        out = [c for c in out if c.get("status") == status]
    return _ok(out)


@manage_router.post("/contacts/{cid}/audit")
def web_manage_contact_audit(cid: int, req: ContactAudit, request: Request):
    """负责人审核紧急联系人。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import audit_emergency_contact
    actor = _user(request).get("name") or "负责人"
    ok_, msg = audit_emergency_contact(cid, req.approve, opinion=req.opinion, actor=actor)
    if not ok_:
        return _fail(2001, msg)
    return _ok({"contact_id": cid}, "审核完成")


@manage_router.get("/sos")
def web_manage_sos(request: Request, status: str = ""):
    """负责人端紧急求助列表。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_elderly_care import get_sos_calls
    rows = get_sos_calls(status=status or None, limit=50)
    return _ok([dict(r) for r in rows])
