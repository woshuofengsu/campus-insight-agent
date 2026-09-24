# -*- coding: utf-8 -*-
"""多租户真隔离（B5）测试 —— **这是隔离的契约**，实现方必须让它全绿。

租户键 = **社区名**（`user_profile.community`）。三条硬规则：
1. **写入侧必须落租户**（v41 的教训：只回填不写入 → 隔离静默失效）；
2. **读取侧 fail-closed**：空租户 → **空集**，绝不回落成"查全部"；
3. **绝不能"没有范围"就能查全量**：跨用户列表查询必须显式给 `tenant=`，
   什么都不给要**大声报错**（ValueError），而不是悄悄返回全库。

隔离说明：每个用例在临时库上跑，teardown 恢复 `db_core._DB_PATH`（同
`tests/test_issue_phone_encryption.py` 的写法）。租户缓存也要清，避免跨用例串味。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"        # 租户 A
B = "朝阳试点社区"    # 租户 B
UID_A = 96101
UID_B = 96102
UID_A2 = 96103       # A 社区第二个居民
GRID_A = 96111
GRID_B = 96112


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="tenant_iso_")
    _path = os.path.join(_tmp, "tenant.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    from data.db_core import get_db
    with get_db() as conn:
        for uid, role, name, community in (
                (UID_A, "resident", "A居民", A), (UID_A2, "resident", "A居民2", A),
                (UID_B, "resident", "B居民", B),
                (GRID_A, "grid", "A网格", A), (GRID_B, "grid", "B网格", B)):
            conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                         "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, community))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def _tenant_cols():
    from data.db_core import get_db
    with get_db() as conn:
        return {t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
                for t in ("community_issues", "proposals", "notices", "health_consults",
                          "policy_questions", "medication_reminders", "emergency_contacts",
                          "emergency_calls", "agent_logs", "agent_dialogs", "care_event_log",
                          "weather_check_tasks")}


# ---------------- 1. 基础：租户解析 ----------------

def test_normalize_rejects_legacy_district():
    from utils.tenant import normalize_tenant
    assert normalize_tenant(" 海淀小区 ") == "海淀小区"
    assert normalize_tenant("海淀区") == "", "行政区是 v41 的历史口径，必须视为无效"
    assert normalize_tenant("") == ""
    assert normalize_tenant(None) == ""


def test_tenant_of_user_reads_community():
    from utils.tenant import clear_cache, tenant_of_user
    clear_cache()
    assert tenant_of_user(UID_A) == A
    assert tenant_of_user(UID_B) == B
    assert tenant_of_user(999999) == "", "查不到用户 → 空租户（fail-closed）"


# ---------------- 2. 迁移：加列 / 归一化 / 回填 ----------------

def test_v48_columns_exist():
    cols = _tenant_cols()
    for table, cl in cols.items():
        assert "tenant_id" in cl, f"{table} 缺 tenant_id（v48 应加上）"


def test_v48_migration_is_idempotent():
    from data.db_core import init_db
    init_db(db_core._DB_PATH)          # 再跑一遍整条迁移链
    with db_core.get_db() as conn:
        v = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    assert v >= 48


def test_v48_normalizes_district_and_backfills_from_owner():
    """历史 '海淀区' 值 + 空值都要按归属人重算成社区名。"""
    from data.db_core import get_db, init_db
    from data.db_repair import submit_issue
    iid, _ = submit_issue(title="归一化用例", category="公共设施", issue_type="室内",
                          location="3号楼", description="测试用描述内容", urgency="一般",
                          reporter_name="A居民", reporter_phone="13800000001",
                          reporter_id=UID_A)
    with get_db() as conn:                       # 人为制造历史脏值
        conn.execute("UPDATE community_issues SET tenant_id='海淀区' WHERE id=?", (iid,))
        conn.commit()
    init_db(db_core._DB_PATH)                    # 重跑迁移
    with get_db() as conn:
        row = conn.execute("SELECT tenant_id FROM community_issues WHERE id=?", (iid,)).fetchone()
    assert row["tenant_id"] == A, f"行政区值应按归属人归一化为社区名，实际 {row['tenant_id']}"


# ---------------- 3. 写入侧：新行必须带租户 ----------------

def _make_issue(uid, title):
    from data.db_repair import submit_issue
    iid, _ = submit_issue(title=title, category="公共设施", issue_type="室内",
                          location="1号楼", description="描述内容够长了", urgency="一般",
                          reporter_name="居民", reporter_phone="13800000002", reporter_id=uid)
    return iid


def test_write_side_stamps_tenant():
    from data.db_core import get_db
    iid = _make_issue(UID_B, "B社区的工单")
    with get_db() as conn:
        row = conn.execute("SELECT tenant_id FROM community_issues WHERE id=?", (iid,)).fetchone()
    assert row["tenant_id"] == B, "写入侧必须按报修人的社区落租户（v41 的教训）"


# ---------------- 4. 读取侧：跨租户不可见 + fail-closed ----------------

def test_issue_list_isolated_by_tenant():
    from data.db_repair import get_issues
    a_title, b_title = "隔离A工单", "隔离B工单"
    _make_issue(UID_A, a_title)
    _make_issue(UID_B, b_title)

    a_rows = get_issues(tenant=A, limit=500)
    titles_a = [r["title"] for r in a_rows]
    assert a_title in titles_a
    assert b_title not in titles_a, "A 社区不应看到 B 社区的工单"

    b_rows = get_issues(tenant=B, limit=500)
    assert b_title in [r["title"] for r in b_rows]
    assert a_title not in [r["title"] for r in b_rows]


def test_issue_list_fail_closed_on_empty_tenant():
    from data.db_repair import get_issues
    assert get_issues(tenant="", limit=500) == [], "空租户必须返回空集，不得回落成查全部"


def test_issue_list_without_any_scope_raises():
    """既不给 tenant 也不给 reporter_id = 没有范围 → 必须大声报错，不能悄悄查全量。"""
    from data.db_repair import get_issues
    with pytest.raises(ValueError):
        get_issues(limit=500)


def test_resident_self_scope_unchanged():
    """居民看自己的数据不受租户影响（守住原有行为）。"""
    from data.db_repair import get_issues
    mine = "我的工单"
    _make_issue(UID_A2, mine)
    rows = get_issues(reporter_id=UID_A2, limit=100)
    assert mine in [r["title"] for r in rows]
    assert all(r["reporter_id"] == UID_A2 for r in rows)


def test_export_rows_isolated():
    """批量导出是最危险的泄漏口，必须带租户。"""
    from data.db_proposal import get_export_rows, submit_proposal
    submit_proposal(title="A社区提案", description="这是一段足够长的提案描述内容", category="公共设施",
                    reporter_name="A居民", reporter_phone="13800000003", is_public=1, reporter_id=UID_A)
    submit_proposal(title="B社区提案", description="这是一段足够长的提案描述内容", category="公共设施",
                    reporter_name="B居民", reporter_phone="13800000004", is_public=1, reporter_id=UID_B)
    rows = get_export_rows(tenant=A)
    titles = [r.get("标题") for r in rows]
    assert "A社区提案" in titles and "B社区提案" not in titles
    assert get_export_rows(tenant="") == []


def test_proposal_list_isolated():
    from data.db_proposal import get_proposals
    assert "B社区提案" not in [r.get("title") for r in get_proposals(tenant=A, limit=200)]
    assert get_proposals(tenant="") == []


def test_consults_and_policy_questions_isolated():
    from data.db_health_content import list_consults, submit_consult
    from data.db_policy import get_common_questions, get_questions
    submit_consult(user_id=UID_A, name="A居民", phone="13800000005", consult_type="健康知识",
                   content="A社区的健康咨询内容")
    submit_consult(user_id=UID_B, name="B居民", phone="13800000006", consult_type="健康知识",
                   content="B社区的健康咨询内容")
    a = [r.get("content", "") for r in list_consults(tenant=A, limit=100)]
    assert any("A社区的" in c for c in a) and not any("B社区的" in c for c in a)
    assert list_consults(tenant="", limit=100) == []
    assert get_common_questions(tenant="") == []
    assert get_questions(tenant="") == []


def test_elderly_manage_lists_isolated():
    from data.db_elderly_care import add_emergency_contact, add_medication_reminder, \
        list_emergency_contacts, list_medication_reminders
    add_medication_reminder(UID_A, patient_name="A老人", drug_name="A药", dosage="1片",
                            times=["08:00"], setter_id=UID_A, start_date="2026-01-01")
    add_medication_reminder(UID_B, patient_name="B老人", drug_name="B药", dosage="1片",
                            times=["08:00"], setter_id=UID_B, start_date="2026-01-01")
    add_emergency_contact(UID_A, name="A家属", phone="13800000007", relation="子女", setter_id=UID_A)
    add_emergency_contact(UID_B, name="B家属", phone="13800000008", relation="子女", setter_id=UID_B)

    meds_a = [r.get("patient_name") for r in list_medication_reminders(tenant=A)]
    assert "A老人" in meds_a and "B老人" not in meds_a, "用药提醒必须按租户隔离（老年敏感）"
    assert list_medication_reminders(tenant="") == []

    con_a = [r.get("name") for r in list_emergency_contacts(tenant=A)]
    assert "A家属" in con_a and "B家属" not in con_a
    assert list_emergency_contacts(tenant="") == []


def test_notices_visible_scope_is_community_scoped():
    """「全体居民」以前对任何社区都可见 —— 现在必须是"本社区全体居民"。"""
    from data.db_notice import get_visible_notices
    a = get_visible_notices("resident", UID_A, tenant=A)
    b = get_visible_notices("resident", UID_B, tenant=B)
    a_ids = {n.get("id") for n in a}
    b_ids = {n.get("id") for n in b}
    # 只要有数据，就必须互不可见（同一条通知不能同时出现在两个社区）
    assert not (a_ids & b_ids) or not a_ids, "通知不能跨社区同时可见"
    assert get_visible_notices("resident", UID_A, tenant="") == []


def test_sos_calls_isolated():
    from data.db_elderly_care import get_sos_calls, log_emergency_call
    log_emergency_call(UID_B, call_type="sos", target_name="B家属", target_phone="13800000009")
    rows = get_sos_calls(tenant=A, limit=50)
    assert all(r.get("user_id") != UID_B for r in rows), "SOS 列表必须按租户隔离"
    assert get_sos_calls(tenant="", limit=50) == []
