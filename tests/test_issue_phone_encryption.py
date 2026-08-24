# -*- coding: utf-8 -*-
"""P0-2：工单手机号落库加密测试（schema v38 + 写入加密 + 读取解密 + 迁移幂等）。

隔离说明：本测试不使用 module 级写 config.DB_PATH（那会污染同进程其他测试文件），
而是每个用例在 fixture 内建临时库并设置 db_core._DB_PATH，teardown 恢复原始值。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """每个用例在临时库上运行；teardown 恢复 db_core 全局路径（不与 config.DB_PATH 全局冲突）。"""
    _orig_db_path = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="issue_phone_enc_")
    _path = os.path.join(_tmp, "issue_phone_enc.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    yield
    db_core._DB_PATH = _orig_db_path  # 恢复，而非置空


def _submit(phone="13800001111", agent_phone="13900002222"):
    from data.db_repair import submit_issue
    iid, msg = submit_issue(
        title="楼道灯坏", category="公共设施", issue_type="室外",
        location="幸福小区3号楼", description="楼道灯不亮了影响出行",
        urgency="一般", reporter_name="张三", reporter_phone=phone,
        reporter_id=1, is_agent_report=1, agent_name="李四", agent_phone=agent_phone,
        agent_relation="邻居",
    )
    return iid


def _audit(iid, approve=True):
    from data.db_repair import audit_issue
    ok, msg = audit_issue(iid, approve, opinion="通过" if approve else "", actor="负责人")
    assert ok, msg
    return msg


def _dispatch(iid, name="王维修", phone="13700003333"):
    from data.db_repair import dispatch_issue
    ok, msg = dispatch_issue(iid, name, phone, actor="负责人")
    assert ok, msg
    return msg


def test_schema_v38_columns_exist():
    from data.database import get_db
    with get_db() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(community_issues)")}
    assert {"reporter_phone_enc", "agent_phone_enc", "assignee_phone_enc"} <= cols


def test_submit_encrypts_and_clears_plaintext():
    iid = _submit()
    assert iid > 0
    from data.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT reporter_phone, reporter_phone_enc, agent_phone, agent_phone_enc "
            "FROM community_issues WHERE id=?", (iid,)).fetchone()
    assert row["reporter_phone"] == ""      # reporter 明文置空
    assert row["reporter_phone_enc"] != ""  # reporter 密文非空
    assert "13800001111" not in row["reporter_phone_enc"]
    assert row["agent_phone"] == ""          # agent 明文置空
    assert row["agent_phone_enc"] != ""      # agent 密文非空
    assert "13900002222" not in row["agent_phone_enc"]


def test_read_decrypts_back_for_display():
    iid = _submit()
    from data.db_repair import get_issue
    issue = get_issue(iid)
    assert issue["reporter_phone"] == "13800001111"   # 读取层还原，路由层再脱敏
    assert issue["agent_phone"] == "13900002222"
    assert issue["reporter_phone_enc"] != ""          # 密文列仍保留


def test_dispatch_encrypts_assignee_phone():
    iid = _submit()
    _audit(iid)
    _dispatch(iid)
    from data.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT assignee_phone, assignee_phone_enc FROM community_issues WHERE id=?",
            (iid,)).fetchone()
    assert row["assignee_phone"] == ""
    assert row["assignee_phone_enc"] != ""
    assert "13700003333" not in row["assignee_phone_enc"]
    # 读取层还原 assignee 明文
    from data.db_repair import get_issue
    assert get_issue(iid)["assignee_phone"] == "13700003333"


def test_issues_list_decrypts_reporter_phone():
    iid = _submit()
    from data.db_repair import get_issues
    rows = get_issues(limit=10)
    hit = next(r for r in rows if r["id"] == iid)
    assert hit["reporter_phone"] == "13800001111"


def _insert_legacy_plaintext_issue(phone="13800001234"):
    """模拟 v37 之前的存量明文工单：绕过 submit_issue（写入即加密），直接裸插明文行。"""
    from data.database import get_db
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO community_issues (title, category, issue_type, location, "
            "description, urgency, status, reporter_name, reporter_phone) "
            "VALUES ('历史工单', '公共设施', '室内', '老小区1号楼', '历史遗留的明文问题', "
            "'一般', '待审核', '历史居民', ?)",
            (phone,),
        )
        conn.commit()
        return cur.lastrowid


def test_migration_idempotent_and_clears_plaintext():
    lid = _insert_legacy_plaintext_issue()
    from scripts.migrate_issue_phone_encryption import migrate
    n1 = migrate()
    n2 = migrate()
    assert n1 >= 1
    assert n2 == 0  # 幂等：第二次无可迁移明文
    from data.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT reporter_phone, reporter_phone_enc FROM community_issues WHERE id=?",
            (lid,)).fetchone()
    assert row["reporter_phone"] == ""        # 明文已搬走
    assert row["reporter_phone_enc"] != ""    # 密文已生效
    assert "13800001234" not in row["reporter_phone_enc"]


def test_rollback_roundtrip():
    lid = _insert_legacy_plaintext_issue()
    from scripts.migrate_issue_phone_encryption import migrate, rollback
    migrate()
    n = rollback()
    assert n >= 1
    from data.database import get_db
    with get_db() as conn:
        row = conn.execute(
            "SELECT reporter_phone FROM community_issues WHERE id=?", (lid,)).fetchone()
    assert row["reporter_phone"] == "13800001234"
