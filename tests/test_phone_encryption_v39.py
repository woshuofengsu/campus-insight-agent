# -*- coding: utf-8 -*-
"""P0 收口：手机号加密遗漏面测试（health_consults / emergency_contacts / emergency_calls / 派单留痕 / seed 防回滚）。

隔离说明：与 test_issue_phone_encryption 相同，fixture 内建临时库，teardown 恢复 db_core._DB_PATH。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """每个用例在临时库上运行；teardown 恢复 db_core 全局路径。"""
    _orig_db_path = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="enc_v39_")
    _path = os.path.join(_tmp, "enc_v39.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    yield
    db_core._DB_PATH = _orig_db_path


def test_health_consult_phone_encrypted():
    """submit_consult 落库：phone 明文置空 + phone_enc 非空；读取自动解密还原。"""
    from data.db_health_content import get_consult, submit_consult
    cid, code, _ = submit_consult(1, "王阿姨", "13800001234", "疾病症状",
                                  "高血压平时怎么管理", is_agent_report=1,
                                  agent_name="李奶奶", agent_phone="13900005678", agent_relation="邻居")
    assert cid > 0 and code
    with db_core.get_db() as conn:
        row = conn.execute("SELECT phone, phone_enc, agent_phone, agent_phone_enc "
                           "FROM health_consults WHERE id=?", (cid,)).fetchone()
    assert row["phone"] == "" and row["phone_enc"] != ""      # 明文清空、密文落库
    assert row["agent_phone"] == "" and row["agent_phone_enc"] != ""
    d = get_consult(cid)
    assert d["phone"] == "13800001234"                        # 读取自动解密
    assert d["agent_phone"] == "13900005678"


def test_emergency_contact_encrypted():
    """add_emergency_contact 落库：phone 明文置空 + phone_enc 非空；列表读取解密。"""
    from data.db_elderly_care import add_emergency_contact, list_emergency_contacts
    cid, msg = add_emergency_contact(1, "张小明", "13900001111", "儿子", setter_id=1)
    assert cid > 0 and not msg
    with db_core.get_db() as conn:
        row = conn.execute("SELECT phone, phone_enc FROM emergency_contacts WHERE id=?",
                           (cid,)).fetchone()
    assert row["phone"] == "" and row["phone_enc"] != ""
    lst = [c for c in list_emergency_contacts(1) if c["id"] == cid]
    assert lst and lst[0]["phone"] == "13900001111"


def test_dispatch_issue_detail_masked():
    """dispatch_issue 的 activity_log.detail 不落完整手机号。"""
    from data.db_repair import dispatch_issue, submit_issue
    iid, _ = submit_issue(
        title="楼道灯坏", category="公共设施", issue_type="室外", location="幸福小区",
        description="楼道灯不亮", urgency="一般", reporter_name="张三",
        reporter_phone="13800138000", reporter_id=1)
    # 先审核通过
    from data.db_repair import audit_issue
    audit_issue(iid, True, opinion="通过", actor="负责人")
    ok, msg = dispatch_issue(iid, "李师傅", "13911112222", actor="负责人")
    assert ok, msg
    with db_core.get_db() as conn:
        row = conn.execute(
            "SELECT detail FROM activity_log WHERE target_type='issue' AND target_id=? AND action='分派维修人员'",
            (iid,)).fetchone()
    assert row is not None
    assert "13911112222" not in (row["detail"] or "")        # 留痕无完整手机号
    assert "139" not in (row["detail"] or "") or "****" in row["detail"]


def test_seed_does_not_rollback_plaintext():
    """_seed_users 首次 & 二次执行后 user_profile.phone 均为空、phone_enc 非空（防回滚）。"""
    from data.seed import _seed_users
    # 首次（fixture 临时库为空 → 走 INSERT 分支）
    _seed_users()
    with db_core.get_db() as conn:
        row = conn.execute("SELECT phone, phone_enc FROM user_profile WHERE username='demo_resident'").fetchone()
    assert row is not None
    assert row["phone"] == "" and row["phone_enc"] != ""
    # 二次（库已有该用户 → 走 UPDATE 分支，不应回滚明文）
    _seed_users()
    with db_core.get_db() as conn:
        row2 = conn.execute("SELECT phone, phone_enc FROM user_profile WHERE username='demo_resident'").fetchone()
    assert row2["phone"] == "" and row2["phone_enc"] == row["phone_enc"]


def test_emergency_call_target_phone_encrypted():
    """发起 SOS 后 emergency_calls.target_phone 明文置空为非空。(间接验证两处 INSERT)"""
    from data.db_elderly_care import add_emergency_contact, audit_emergency_contact, trigger_sos
    cid, _ = add_emergency_contact(3, "张小明", "13900001111", "儿子", setter_id=3)
    audit_emergency_contact(cid, True, opinion="通过", actor="负责人")
    cid2, msg = trigger_sos(3, actor="测试")
    assert cid2 > 0 and not msg
    with db_core.get_db() as conn:
        row = conn.execute("SELECT target_phone, target_phone_enc FROM emergency_calls WHERE id=?",
                           (cid2,)).fetchone()
    assert row["target_phone"] == "" and row["target_phone_enc"] != ""
