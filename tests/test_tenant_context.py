# -*- coding: utf-8 -*-
"""多租户最后两条边界（B7 尾巴）：升级名单按社区 + Agent 工具的租户上下文。

① **更高级负责人名单**（`settings.senior_manager_ids`）此前是全局一份：
   定时任务的"超时升级第 2 层"通知对象对两个社区是同一批人。现在给了 `tenant` 就按
   **任务自己所属的社区**取名单；
② **Agent 工具**（`tools/*.py`）此前用 `default_community()` 兜底（"永远看成默认社区"）：
   朝阳用户问"有哪些提案"会看到海淀的提案——这是**对话文本里的跨租户泄漏**，页面审计抓不到。
   现在工具按**请求级租户上下文**（`utils.tenant.tenant_context`）取，取不到就明确说
   "无法确定社区"，绝不拿别的社区的数据充数。

隔离写法同 `tests/test_tenant_isolation.py`（临时库 + teardown 还原 + 清租户缓存）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
UID_A = 96401
UID_B = 96402
GRID_A = 96411
GRID_B = 96412


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="tenant_ctx_")
    path = os.path.join(tmp, "ctx.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, com in ((UID_A, "resident", "A居民", A),
                                     (UID_B, "resident", "B居民", B),
                                     (GRID_A, "grid", "A网格", A),
                                     (GRID_B, "grid", "B网格", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


# ---------------- ① 更高级负责人名单按社区 ----------------

def test_senior_manager_ids_isolated_per_community():
    from data.db_weather import get_senior_manager_ids, set_senior_manager_ids
    assert get_senior_manager_ids() == [], "干净库里应为空（升级走'无法升级'分支）"
    set_senior_manager_ids([GRID_A], actor="A网格", tenant=A)
    assert get_senior_manager_ids(tenant=A) == [GRID_A]
    assert get_senior_manager_ids(tenant=B) == [], \
        "B 社区不该拿到 A 的升级名单（升级给谁是社区自己的配置）"
    assert get_senior_manager_ids() == [], "社区级写入不该污染全局键"


def test_senior_manager_ids_global_fallback():
    from data.db_weather import get_senior_manager_ids, set_senior_manager_ids
    set_senior_manager_ids([GRID_B], actor="系统", tenant=None)   # 写全局
    assert get_senior_manager_ids(tenant=B) == [GRID_B], "未单独配置的社区回落全局名单"
    assert get_senior_manager_ids(tenant=A) == [GRID_A], "已单独配置的社区不受全局影响"


def test_escalate_uses_task_community(monkeypatch):
    """升级按**任务自己的社区**取名单：A 社区的任务升给 A 名单，B 的升给 B 名单。"""
    from data import db_weather
    from data.db_core import get_db

    with get_db() as conn:
        for tid, tenant in ((9001, A), (9002, B)):
            conn.execute(
                "INSERT INTO weather_check_tasks (id, alert_id, alert_type, level, "
                "checklist_json, status, tenant_id) VALUES (?, ?, '高温', '橙色', '[]', "
                "'超时未确认', ?)", (tid, f"alert-{tid}", tenant))
        conn.commit()

    notified: list = []
    monkeypatch.setattr(db_weather, "_notify_managers",
                        lambda title, content, related_id=None, online_user_ids=None:
                        notified.append((related_id, list(online_user_ids or []))) or 1)
    monkeypatch.setattr(db_weather, "_last_escalation_log", lambda tid: None)
    monkeypatch.setattr(db_weather, "log_activity", lambda *a, **k: None)

    out = db_weather.escalate_overdue_tasks()
    senior_map = {tid: ids for tid, ids in notified}
    assert senior_map.get(9001) == [GRID_A], f"A 任务应升给 A 名单，实际 {notified}"
    assert senior_map.get(9002) == [GRID_B], f"B 任务应升给 B 名单，实际 {notified}"
    assert out["senior_notified"] >= 2


def test_escalate_explicit_list_still_wins(monkeypatch):
    """显式传名单时按传入值处理（老调用方/测试兼容）。

    注意 `_notify_managers` 会被调两次：第 1 层（在线负责人，online_user_ids=None）
    与第 2 层（更高级负责人）；这里只断言第 2 层用的是显式名单。
    """
    from data import db_weather
    notified: list = []
    monkeypatch.setattr(db_weather, "_notify_managers",
                        lambda title, content, related_id=None, online_user_ids=None:
                        notified.append(list(online_user_ids or [])) or 1)
    monkeypatch.setattr(db_weather, "_last_escalation_log", lambda tid: None)
    monkeypatch.setattr(db_weather, "log_activity", lambda *a, **k: None)
    db_weather.escalate_overdue_tasks(senior_user_ids=[GRID_B])
    assert [GRID_B] in notified, f"显式名单应被用于升级层，实际通知记录 {notified}"


# ---------------- ② Agent 工具的租户上下文 ----------------

def test_context_defaults_to_empty_and_restores():
    from utils.tenant import ctx_tenant, tenant_context
    assert ctx_tenant() == "", "没有声明上下文时必须返回空串（不猜社区）"
    with tenant_context(A):
        assert ctx_tenant() == A
        with tenant_context(B):
            assert ctx_tenant() == B
        assert ctx_tenant() == A, "退出内层要还原外层"
    assert ctx_tenant() == ""


def test_context_normalizes_legacy_value():
    from utils.tenant import ctx_tenant, tenant_context
    with tenant_context("海淀区"):     # 历史行政区值 = 无效租户
        assert ctx_tenant() == ""


def test_tool_tenant_fail_closed_without_context():
    """工具拿不到上下文时返回空串——由工具自己给出"无法确定社区"的提示。"""
    import tools._ctx as ctx
    assert ctx.tool_tenant() == ""


def test_tool_tenant_reads_context():
    import tools._ctx as ctx
    from utils.tenant import tenant_context
    with tenant_context(B):
        assert ctx.tool_tenant() == B


def _tool_fn(t):
    """取 LangChain 工具底层的普通函数（拿不到就跳过，避免绑死框架版本）。"""
    return getattr(t, "func", None) or getattr(t, "_run", None)


def test_proposals_tool_is_scoped_and_fails_closed():
    """提案工具：按上下文只出自己的社区；没有上下文时明确提示而不是给默认社区的数据。"""
    import data.db_proposal as dp
    from data.db_core import get_db
    from utils.tenant import tenant_context
    # 工具只展示"公开可见状态"的提案，新建的提案默认是"待审核"（不在可见集合里），
    # 所以要造两条**公示中**的提案才算真样本。
    a_pid, _ = dp.submit_proposal(title="甲社区加装电梯的提案", description="这是一段足够长的提案描述内容",
                                  category="公共设施", reporter_name="A居民",
                                  reporter_phone="13800000031", is_public=1, reporter_id=UID_A)
    b_pid, _ = dp.submit_proposal(title="乙社区增设快递柜的提案", description="这是一段足够长的提案描述内容",
                                  category="公共设施", reporter_name="B居民",
                                  reporter_phone="13800000032", is_public=1, reporter_id=UID_B)
    with get_db() as conn:
        conn.execute("UPDATE proposals SET status='公示中' WHERE id IN (?, ?)", (a_pid, b_pid))
        conn.commit()

    from tools.query_proposals import get_proposals
    fn = _tool_fn(get_proposals)
    if fn is None:                                     # pragma: no cover
        pytest.skip("LangChain 工具未暴露 .func，跳过行为级断言")

    with tenant_context(A):
        out_a = fn()
    with tenant_context(B):
        out_b = fn()
    assert "甲社区加装电梯的提案" in out_a and "乙社区增设快递柜的提案" not in out_a, \
        "A 社区上下文下不该看到 B 社区提案"
    assert "乙社区增设快递柜的提案" in out_b and "甲社区加装电梯的提案" not in out_b

    out_none = fn()
    assert "无法确定您所在的社区" in out_none, \
        "没有租户上下文时必须明确提示，而不是拿默认社区的数据充数"
    assert "甲社区加装电梯的提案" not in out_none and "乙社区增设快递柜的提案" not in out_none


def test_create_proposal_duplicate_check_is_scoped():
    """查重也只在本社区内找：A 的标题不该被 B 的会话当成重复。"""
    from tools.action_create_proposal import _check_duplicate
    from utils.tenant import tenant_context
    with tenant_context(A):
        dup_a = [p["title"] for p in _check_duplicate("甲社区加装电梯的提案")]
    with tenant_context(B):
        dup_b = [p["title"] for p in _check_duplicate("甲社区加装电梯的提案")]
    assert dup_a == ["甲社区加装电梯的提案"]
    assert dup_b == [], "B 社区里没有这条提案，不该被判重复"
