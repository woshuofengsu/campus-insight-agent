# -*- coding: utf-8 -*-
"""授权矩阵落地测试（v2 升级方案任务卡 3：封同社区所有权）。

**背景**：多租户只解决了"跨社区不可见"，没有解决"**同社区 ≠ 有权操作这个人**"。
Codex 评审 F2 实测：同社区普通居民能删别人家老人的紧急联系人、暂停别人家老人的用药，
甚至"处置"别人家老人的 SOS——因为那几条路由只查了 `_same_tenant`。

本文件按 `docs/spec/升级方案/授权矩阵.md` 的矩阵逐格验证：
**本人允许 / 绑定家属按矩阵允许或拒绝 / 同社区他人一律拒绝 / 网格员只做审核与处置**。
反向断言同样重要：合法的老人本人与绑定家属不能被误伤。
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
ELDER_A = 96621        # A 社区老人（有资源）
FAMILY_A = 96601       # A 社区：ELDER_A 的绑定家属
OTHER_A = 96602        # A 社区：无关居民（同社区但非本人/非家属）
GRID_A = 96611
GRID_B = 96612
ELDER_B = 96622        # B 社区老人


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="authz_matrix_")
    path = os.path.join(tmp, "az.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, com in ((ELDER_A, "elderly", "A老人", A),
                                     (ELDER_B, "elderly", "B老人", B),
                                     (FAMILY_A, "resident", "A家属", A),
                                     (OTHER_A, "resident", "A他人", A),
                                     (GRID_A, "grid", "A网格", A),
                                     (GRID_B, "grid", "B网格", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        # 绑定家属关系：FAMILY_A → ELDER_A
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
    """取错误文案（失败走 `_fail` → JSONResponse）。"""
    if isinstance(res, dict):
        return res.get("error") or ""
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


def _fixtures():
    """造一条 A 老人资源：联系人 + 用药提醒 + SOS 求助。

    直接用数据层创建（路由带业务校验，测授权不该被业务校验挡住）。
    """
    from api_routes.elderly import ContactCreate, web_contacts_create
    from data.db_elderly_care import (add_medication_reminder, audit_emergency_contact,
                                      log_emergency_call)
    req = _req(ELDER_A, "elderly", A)
    r1 = web_contacts_create(ContactCreate(name="A家属甲", phone="13800003001", relation="子女"), req)
    cid = (r1.get("data") or {}).get("contact_id") if isinstance(r1, dict) else None
    audit_emergency_contact(cid, True, actor="A网格")
    rid, _msg = add_medication_reminder(ELDER_A, patient_name="A老人", drug_name="降压药",
                                        dosage="1片", times=["08:00"], setter_id=ELDER_A,
                                        start_date="2026-01-01")
    call_id = log_emergency_call(ELDER_A, call_type="sos", target_name="A家属甲",
                                 target_phone="13800003001", status="求助中")
    return cid, rid, call_id


CID, RID, CALL_ID = None, None, None


def test_setup_fixtures():
    global CID, RID, CALL_ID
    CID, RID, CALL_ID = _fixtures()
    assert CID and RID and CALL_ID, f"夹具创建失败：{CID} {RID} {CALL_ID}"


# ---------------- 紧急联系人：删除 ----------------

def test_contact_delete_by_owner_allowed():
    """本人可以删（反向断言：别把合法路径误伤）。"""
    from api_routes.elderly import ContactCreate, web_contacts_create, web_contacts_delete
    req = _req(ELDER_A, "elderly", A)
    cid = (web_contacts_create(ContactCreate(name="临时联系人", phone="13800003002",
                                             relation="邻居"), req).get("data") or {}).get("contact_id")
    assert not _denied(web_contacts_delete(cid, req)), "本人应能删除自己的联系人"


def test_contact_delete_by_same_community_other_resident_denied():
    """同社区**无关居民**不能删别人家老人的联系人（Codex 评审 F2 的核心）。"""
    from api_routes.elderly import web_contacts_delete
    assert _denied(web_contacts_delete(CID, _req(OTHER_A, "resident", A))), \
        "同社区他人不该能删（只查 _same_tenant 的旧行为会放行）"


def test_contact_delete_by_bound_family_allowed():
    """已绑定家属可代操作（矩阵 D1）。"""
    from api_routes.elderly import ContactCreate, web_contacts_create, web_contacts_delete
    elder_req = _req(ELDER_A, "elderly", A)
    cid = (web_contacts_create(ContactCreate(name="家属代删用", phone="13800003003",
                                             relation="邻居"), elder_req).get("data")
           or {}).get("contact_id")
    fam_req = _req(FAMILY_A, "resident", A, elder_id=ELDER_A)
    assert not _denied(web_contacts_delete(cid, fam_req)), "已绑定家属应可代删"


def test_contact_delete_cross_community_denied():
    from api_routes.elderly import web_contacts_delete
    assert _denied(web_contacts_delete(CID, _req(GRID_B, "grid", B))), "跨社区必须拒绝"


# ---------------- 用药：暂停/恢复 与 打卡 ----------------

def test_medication_pause_by_other_resident_denied():
    from api_routes.elderly import MedicationToggle, web_medication_toggle
    res = web_medication_toggle(RID, MedicationToggle(action="pause"),
                               _req(OTHER_A, "resident", A))
    assert _denied(res), "同社区他人不该能暂停别人家老人的用药"


def test_medication_pause_by_family_denied():
    """矩阵 D1：暂停/恢复只限本人（家属要停就走审核的修改流程）。"""
    from api_routes.elderly import MedicationToggle, web_medication_toggle
    res = web_medication_toggle(RID, MedicationToggle(action="pause"),
                               _req(FAMILY_A, "resident", A, elder_id=ELDER_A))
    assert _denied(res), "家属不该能暂停（打卡/暂停都只能本人）"


def test_medication_taken_by_family_denied_by_owner_allowed():
    """打卡只能老人本人——家属替打卡等于伪造服药记录。"""
    from api_routes.elderly import MedicationToggle, web_medication_toggle
    fam = web_medication_toggle(RID, MedicationToggle(action="taken"),
                               _req(FAMILY_A, "resident", A, elder_id=ELDER_A))
    assert _denied(fam), "家属不该能替老人打卡"
    own = web_medication_toggle(RID, MedicationToggle(action="taken"),
                               _req(ELDER_A, "elderly", A))
    assert not _denied(own), "本人打卡必须可用（别误伤）"


def test_medication_modify_by_family_allowed_other_denied():
    """同社区他人被拒；**绑定家属**不该被**授权层**拒（业务态拒绝另算，例如"待审核中不能改"）。"""
    from api_routes.elderly import MedicationCreate, web_medication_modify
    body = MedicationCreate(drug_name="降压药", dosage="1片", times="09:00")
    assert _denied(web_medication_modify(RID, body, _req(OTHER_A, "resident", A))), \
        "同社区他人不该能改别人家老人的用药"
    fam = web_medication_modify(RID, body, _req(FAMILY_A, "resident", A, elder_id=ELDER_A))
    assert "无权限" not in _err(fam), f"绑定家属被授权层拒绝（不该）：{_err(fam)!r}"


# ---------------- SOS 处置：仅网格员 ----------------

def test_sos_action_requires_grid_role():
    """原来同社区任何居民都能"处置"别人家老人的求助。"""
    from api_routes.elderly import SosAction, web_sos_action
    for req in (_req(OTHER_A, "resident", A), _req(FAMILY_A, "resident", A, elder_id=ELDER_A),
                _req(ELDER_A, "elderly", A)):
        res = web_sos_action(CALL_ID, SosAction(action="close", handle_note="测试"), req)
        assert _denied(res), f"{req.state.user['role']} 不该能处置 SOS（仅网格员）"
    grid = web_sos_action(CALL_ID, SosAction(action="close", handle_note="网格员处置"),
                          _req(GRID_A, "grid", A))
    assert not _denied(grid), "本社区网格员应能处置（别误伤）"


# ---------------- 健康记录录入：仅本人 ----------------

def test_vital_create_family_denied_owner_allowed():
    """矩阵 D4：家属不得代录（避免替老人造健康数据）。"""
    from api_routes.elderly import VitalCreate, web_vital_create
    body = VitalCreate(kind="bp", sys=135, dia=85)
    assert _denied(web_vital_create(body, _req(FAMILY_A, "resident", A, elder_id=ELDER_A))), \
        "家属不该能代录健康记录"
    assert not _denied(web_vital_create(body, _req(ELDER_A, "elderly", A))), \
        "老人本人录入必须可用（别误伤）"
