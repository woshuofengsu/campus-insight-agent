# -*- coding: utf-8 -*-
"""通知收件人按社区收口（v2 升级方案任务卡 4 前半：通知）。

**问题**（Codex 评审 I2）：转人工通知与健康异常提醒都遍历 `list_users(role="grid")`——
即**所有社区**的网格员。消息中心虽然只让本人看到自己的消息，但**敏感内容已经投递给错误收件人**：
A 社区老人的姓名与血压读数会出现在 B 社区网格员的消息里。

**做法**：新增结构化收件人入口 `data.db_user.managers_of(tenant)`（收件人选择统一从这里走），
并把带敏感内容的通知改为按**主体所属社区**选择收件人；社区取不到时不投递给网格员（fail-closed）。
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
ELDER_A = 96721
GUARDIAN_A = 96701
GRID_A = 96711
GRID_B = 96712
RES_A = 96702


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="notify_scope_")
    path = os.path.join(tmp, "ns.db")
    db_core._DB_PATH = ""
    if os.path.exists(path):
        os.unlink(path)
    db_core.init_db(path)
    with db_core.get_db() as conn:
        for uid, role, name, com in ((ELDER_A, "elderly", "A老人", A),
                                     (GUARDIAN_A, "resident", "A家属", A),
                                     (RES_A, "resident", "A居民", A),
                                     (GRID_A, "grid", "A网格", A),
                                     (GRID_B, "grid", "B网格", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, name, com))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(user_profile)")]
        if "bound_elderly_id" in cols:
            conn.execute("UPDATE user_profile SET bound_elderly_id=? WHERE id=?", (ELDER_A, GUARDIAN_A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = _orig
    clear_cache()


def _notifs(uid):
    with db_core.get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM notifications WHERE user_id=?", (uid,)).fetchall()]


# ---------------- 结构化收件人入口 ----------------

def test_managers_of_filters_by_community():
    from data.db_user import list_users, managers_of
    assert [u["id"] for u in managers_of(A)] == [GRID_A], "只应返回本社区网格员"
    assert [u["id"] for u in managers_of(B)] == [GRID_B]
    assert managers_of("") == [], "社区为空 → 空表（fail-closed，绝不返回全部）"
    # 向后兼容：不传 community 仍是"全部"（老调用方行为不变）
    assert {u["id"] for u in list_users(role="grid")} == {GRID_A, GRID_B}


def test_managers_of_ignores_legacy_district_value():
    from data.db_user import managers_of
    assert managers_of("海淀区") == [], "历史行政区值不是合法租户"


# ---------------- 健康异常提醒 ----------------

def test_abnormal_vital_notifies_only_own_community():
    """A 社区老人的血压异常，只通知 A 社区网格员 + 家属；**B 社区网格员不该收到**。"""
    from data.db_vitals import add_vital, notify_abnormal_vital
    vid, level, meta = add_vital(ELDER_A, "bp", sys_=185, dia=115, note="测试")
    assert vid > 0 and level != "normal", f"夹具应产生异常分级，实际 {level}"
    notify_abnormal_vital(ELDER_A, "bp", level, meta.get("hint", ""), "185/115 mmHg")

    a_msgs = _notifs(GRID_A)
    b_msgs = _notifs(GRID_B)
    g_msgs = _notifs(GUARDIAN_A)
    assert any(m["type"] == "elderly_health" for m in a_msgs), "本社区网格员应收到健康提醒"
    assert all(m["type"] != "elderly_health" for m in b_msgs), \
        "**跨社区不该收到**（Codex 评审 I2：敏感内容投递给错误收件人）"
    assert any(m["type"] == "elderly_health" for m in g_msgs), "绑定家属应收到"


def test_vital_notification_body_not_leaked_to_other_community():
    """再确认一次：B 社区网格员的消息正文里不该出现 A 老人的姓名与读数。"""
    text = " ".join((m.get("title") or "") + (m.get("content") or "") for m in _notifs(GRID_B))
    assert "A老人" not in text and "185/115" not in text


# ---------------- 转人工通知 ----------------

def test_handoff_notifies_only_own_community(monkeypatch):
    """转人工（含 AI 整理的上下文）只通知**用户所属社区**的网格员。"""
    import data.db_agent as dba
    from agent.orchestrator import Orchestrator

    monkeypatch.setattr(dba, "create_handoff", lambda *a, **k: 5150)
    o = Orchestrator(session_id="test-notify-scope")
    ctx = {"uid": RES_A, "name": "A居民", "role": "resident", "user_input": "我要找人处理"}
    out = type(o)._transfer_to_human(o, ctx, {"reply": "好的。", "intent": "其他", "status": "转人工"},
                                     "需要人工")
    assert out["handoff_id"] == 5150
    assert any(m["type"] == "agent_handoff" for m in _notifs(GRID_A)), \
        "本社区网格员应收到转人工通知"
    assert all(m["type"] != "agent_handoff" for m in _notifs(GRID_B)), \
        "跨社区网格员不该收到（原来 list_users(role='grid') 会投给所有社区）"
