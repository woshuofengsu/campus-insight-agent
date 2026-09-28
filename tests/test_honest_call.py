# -*- coding: utf-8 -*-
"""「诚实呼叫」口径测试（v3 复核 §6 B2 + I8）。

**背景（B2）**：`api_routes/elderly.py:449` 原来只写一条"已结束"的拨打记录就返回，
前端 `Contacts.vue` 却显示"正在呼叫 XXX" —— 页面在**替手机撒谎**：H5 能做的只有
`tel:` 调起系统拨号盘，**拨出/接通/挂断都由手机掌控，网页看不到**。

**背景（I8）**：原接口签名 `ContactCall{target_name, target_phone}` 是**前端传什么就记什么**，
"打了给谁"完全可以伪造（留痕与事实脱钩）。

本文件守住三件事：
  1. 号码/姓名**只能由服务端解析**（前端传的号码一律不采信）；
  2. 记录状态分期：准备拨打 → 已打开拨号盘 / 已取消 / 拨打失败；
  3. **不存在"已接通"** —— 网页没有证据，接口也不接受这个取值（schema 层就拒）。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
ELDER_A = 97721
FAMILY_A = 97701
OTHER_A = 97702
ELDER_B = 97722
GRID_A = 97711

REAL_PHONE = "13800007777"


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="honest_call_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "hc.db"))
    with db_core.get_db() as conn:
        for uid, role, name, com in ((ELDER_A, "elderly", "A老人", A),
                                     (ELDER_B, "elderly", "B老人", B),
                                     (FAMILY_A, "resident", "A家属", A),
                                     (OTHER_A, "resident", "A他人", A),
                                     (GRID_A, "grid", "A网格", A)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(user_profile)")]
        if "bound_elderly_id" in cols:
            conn.execute("UPDATE user_profile SET bound_elderly_id=? WHERE id=?", (ELDER_A, FAMILY_A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def _req(uid, role, community, elder_id=None):
    qp = {"elder_id": str(elder_id)} if elder_id else {}
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"{community}{role}", "community": community,
    }), query_params=qp, client=SimpleNamespace(host="127.0.0.1"))


def _denied(res) -> bool:
    if isinstance(res, dict):
        return not res.get("success")
    import json as _json
    return not _json.loads(bytes(res.body).decode("utf-8")).get("success")


def _err(res) -> str:
    if isinstance(res, dict):
        return res.get("error") or ""
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


CID = None


def test_setup_contact():
    """造一个已审核通过的联系人（真实号码 REAL_PHONE）。"""
    global CID
    from api_routes.elderly import ContactCreate, web_contacts_create
    from data.db_elderly_care import audit_emergency_contact
    r = web_contacts_create(ContactCreate(name="A家属甲", phone=REAL_PHONE, relation="子女"),
                            _req(ELDER_A, "elderly", A))
    CID = (r.get("data") or {}).get("contact_id")
    assert CID, f"夹具创建失败：{r}"
    audit_emergency_contact(CID, True, actor="A网格")


def _last_call():
    from data.db_core import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_calls WHERE call_type='contact' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- 第一步：准备拨打

def test_prepare_call_resolves_target_server_side():
    """本人发起 → 服务端解析号码 → 记录停在「准备拨打」，返回 tel: 供前端导航。"""
    from api_routes.elderly import ContactCall, web_elderly_contact
    res = web_elderly_contact(ContactCall(contact_id=CID), _req(ELDER_A, "elderly", A))
    assert not _denied(res), _err(res)
    data = res["data"]
    assert data["phone"] == REAL_PHONE
    assert data["tel"] == f"tel:{REAL_PHONE}"
    assert data["stage"] == "准备拨打"
    row = _last_call()
    assert row["result"] == "准备拨打" and row["status"] == "待确认"
    assert row["user_id"] == ELDER_A


def test_frontend_supplied_phone_is_ignored():
    """I8：前端传 target_phone **不被采信** —— 留痕里的号码必须来自联系人本身。

    原来是 `target_name/target_phone` 直传直记，等于"想留痕成打过谁就打给谁"。
    """
    from api_routes.elderly import ContactCall, web_elderly_contact
    forged = ContactCall(contact_id=CID, target_phone="13900000000", target_name="假名字")
    res = web_elderly_contact(forged, _req(ELDER_A, "elderly", A))
    assert not _denied(res), _err(res)
    assert res["data"]["phone"] == REAL_PHONE, "前端传的号码不得影响实际拨出对象"
    from data.db_elderly_care import _dec_phone
    row = _last_call()
    assert _dec_phone(row["target_phone_enc"], row["target_phone"]) == REAL_PHONE
    assert "13900000000" not in str(row.get("target_phone") or "")


def test_prepare_call_denies_other_resident_same_community():
    """同社区他人不能拨别人家老人的联系人（授权矩阵：同社区 ≠ 有权操作这个人）。"""
    from api_routes.elderly import ContactCall, web_elderly_contact
    res = web_elderly_contact(ContactCall(contact_id=CID), _req(OTHER_A, "resident", A))
    assert _denied(res), "同社区无关居民不该能拨别人家老人的紧急联系人"


def test_prepare_call_denies_other_community():
    """跨社区一律拒绝（多租户）。"""
    from api_routes.elderly import ContactCall, web_elderly_contact
    res = web_elderly_contact(ContactCall(contact_id=CID), _req(ELDER_B, "elderly", B))
    assert _denied(res), "别的社区不该能拨本社区老人的联系人"


def test_prepare_call_allows_bound_family():
    """反向断言：绑定家属代操作必须可用（别误伤），且记录归到老人名下。"""
    from api_routes.elderly import ContactCall, web_elderly_contact
    res = web_elderly_contact(ContactCall(contact_id=CID),
                              _req(FAMILY_A, "resident", A, elder_id=ELDER_A))
    assert not _denied(res), _err(res)
    assert _last_call()["user_id"] == ELDER_A, "家属代打的记录应归到老人名下（老年关怀模块口径一致）"


# ---------------------------------------------------------------- 第二步：回填真实结果

def test_outcome_dialer_opened_never_claims_connected():
    """打开拨号盘 → 只记「已打开拨号盘」，**不许出现"已接通/已通话"**。"""
    from api_routes.elderly import CallOutcome, ContactCall, web_elderly_contact, \
        web_elderly_contact_outcome
    prep = web_elderly_contact(ContactCall(contact_id=CID), _req(ELDER_A, "elderly", A))
    call_id = prep["data"]["call_id"]
    res = web_elderly_contact_outcome(call_id, CallOutcome(stage="dialer_opened"),
                                      _req(ELDER_A, "elderly", A))
    assert not _denied(res), _err(res)
    row = _last_call()
    assert "已打开拨号盘" in row["result"]
    assert "接通" not in row["result"].replace("是否接通以手机通话记录为准", ""), \
        f"不得宣称已接通：{row['result']}"
    assert row["status"] == "已结束"


@pytest.mark.parametrize("stage,expect", [("cancelled", "已取消"), ("failed", "拨打失败")])
def test_outcome_cancelled_and_failed(stage, expect):
    from api_routes.elderly import CallOutcome, ContactCall, web_elderly_contact, \
        web_elderly_contact_outcome
    prep = web_elderly_contact(ContactCall(contact_id=CID), _req(ELDER_A, "elderly", A))
    call_id = prep["data"]["call_id"]
    res = web_elderly_contact_outcome(call_id, CallOutcome(stage=stage),
                                      _req(ELDER_A, "elderly", A))
    assert not _denied(res), _err(res)
    assert _last_call()["result"] == expect


def test_connected_stage_is_rejected_by_schema():
    """**网页没有通话结果**：接口在 schema 层就拒绝 `connected`（不许编一个"已接通"）。"""
    from pydantic import ValidationError
    from api_routes.elderly import CallOutcome
    with pytest.raises(ValidationError):
        CallOutcome(stage="connected")


def test_outcome_denies_others():
    """别人不能改我的拨打记录（同社区他人 / 跨社区都不行）。"""
    from api_routes.elderly import CallOutcome, ContactCall, web_elderly_contact, \
        web_elderly_contact_outcome
    prep = web_elderly_contact(ContactCall(contact_id=CID), _req(ELDER_A, "elderly", A))
    call_id = prep["data"]["call_id"]
    for req in (_req(OTHER_A, "resident", A), _req(ELDER_B, "elderly", B)):
        res = web_elderly_contact_outcome(call_id, CallOutcome(stage="cancelled"), req)
        assert _denied(res), "不该能改他人/他社区的拨打记录"


def test_outcome_rejects_non_contact_record():
    """SOS 事件行不能被"联系拨打结果"接口改（两类记录语义不同）。"""
    from api_routes.elderly import CallOutcome, web_elderly_contact_outcome
    from data.db_elderly_care import log_emergency_call
    sos_id = log_emergency_call(ELDER_A, call_type="sos", target_name="A家属甲",
                                target_phone=REAL_PHONE, status="求助中")
    res = web_elderly_contact_outcome(sos_id, CallOutcome(stage="cancelled"),
                                      _req(ELDER_A, "elderly", A))
    assert _denied(res)


def test_prepare_call_requires_audited_contact():
    """没审核通过的联系人不能拨（业务态：待审核不生效）。"""
    from api_routes.elderly import ContactCall, ContactCreate, web_contacts_create, \
        web_elderly_contact
    r = web_contacts_create(ContactCreate(name="待审核联系人", phone="13800008888", relation="邻居"),
                            _req(ELDER_A, "elderly", A))
    pending = (r.get("data") or {}).get("contact_id")
    res = web_elderly_contact(ContactCall(contact_id=pending), _req(ELDER_A, "elderly", A))
    assert _denied(res)


# ---------------------------------------------------------------- 留痕合规

def test_sos_dial_trace_has_no_full_phone():
    """拨号留痕（activity_log.detail）不得含完整手机号（项目硬约定）。"""
    from data.db_core import get_db
    from data.db_elderly_care import log_sos_dial
    log_sos_dial(1, "A家属甲", REAL_PHONE, "已打开拨号盘", actor="A老人")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT detail FROM activity_log WHERE action='紧急求助拨号' ORDER BY id DESC LIMIT 1"
        ).fetchall()
    assert rows, "应留下拨号留痕"
    assert REAL_PHONE not in (rows[0]["detail"] or ""), f"留痕含完整手机号：{rows[0]['detail']}"


def test_unfilled_call_becomes_unknown_not_assumed_dialed():
    """没回填结果的记录 → 超时后标「结果未知」，**绝不假设成"已拨打"**（诚实口径）。"""
    from api_routes.elderly import ContactCall, web_elderly_contact
    from data.db_core import get_db
    from data.db_elderly_care import resolve_stale_contact_calls

    prep = web_elderly_contact(ContactCall(contact_id=CID), _req(ELDER_A, "elderly", A))
    call_id = prep["data"]["call_id"]
    assert resolve_stale_contact_calls(minutes=5) == 0, "刚创建的记录不该被立刻判为未知"
    with get_db() as conn:
        # ⚠️ created_at 是 **UTC**（CURRENT_TIMESTAMP），所以回拨时间也要用 UTC 口径
        conn.execute("UPDATE emergency_calls SET created_at=datetime('now','-30 minutes') "
                     "WHERE id=?", (call_id,))
        conn.commit()
    assert resolve_stale_contact_calls(minutes=5) >= 1
    with get_db() as conn:
        row = conn.execute("SELECT result, status FROM emergency_calls WHERE id=?", (call_id,)).fetchone()
    assert "结果未知" in row["result"], f"应如实标注结果未知：{row['result']}"
    assert "已拨打" not in row["result"] and "已打开拨号盘" not in row["result"], \
        "没有证据时不得假设成已拨打/已打开拨号盘"
    assert row["status"] == "已结束"
