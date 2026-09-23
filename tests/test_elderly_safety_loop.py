# -*- coding: utf-8 -*-
"""P3 安全闭环回归：打卡 → 久未互动 → 通知网格员（含子女联系方式）+ 接线守卫。

背景（2026-09-24 侦察）：这条链路"代码都在、但没人调"——
`touch_active` 只被 Streamlit 备线调用（Vue 主路径从不写 `last_active_at`，库里值停在 2026-08-21），
`notify_inactive_elders` 没进调度（只在 Agent 聊天观察阶段顺带跑）。
所以这个文件除了行为测试，还有**接线守卫**：把那两处接线写死的断言，删掉就会红。
"""
import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    _orig = db_core._DB_PATH
    _tmp = tempfile.mkdtemp(prefix="elderly_safety_")
    _path = os.path.join(_tmp, "safety.db")
    db_core._DB_PATH = ""
    if os.path.exists(_path):
        os.unlink(_path)
    db_core.init_db(_path)
    yield
    db_core._DB_PATH = _orig


ELDER_UID = 93001
GRID_UID = 93002


def _seed(elder_active_hours_ago=30, alone=1):
    """一个老人（30h 没互动、独居、有子女联系方式）+ 一个网格员。"""
    from data.db_core import get_db

    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                     "VALUES (?, 'elder93001', 'elderly', '张奶奶', 1, '海淀小区')", (ELDER_UID,))
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                     "VALUES (?, 'grid93002', 'grid', '王网格', 1, '海淀小区')", (GRID_UID,))
        conn.execute(
            "INSERT OR REPLACE INTO elderly_profile (user_id, is_living_alone, last_active_at, health_info, "
            "medication_reminders, emergency_contact, updated_at) "
            "VALUES (?, ?, datetime('now', ?), '{}', '[]', ?, CURRENT_TIMESTAMP)",
            (ELDER_UID, alone, f"-{elder_active_hours_ago} hours",
             '[{"name": "小张", "phone": "13800138000", "relation": "子女"}]'))
        conn.commit()


def test_touch_active_marks_now():
    from data.db_core import get_db
    from data.db_elderly import touch_active

    _seed(elder_active_hours_ago=30)
    touch_active(ELDER_UID)
    with get_db() as conn:
        row = conn.execute("SELECT last_active_at FROM elderly_profile WHERE user_id=?",
                           (ELDER_UID,)).fetchone()
    assert row["last_active_at"] is not None
    # 刚打过卡 → 不在"久未互动"名单里
    from data.db_elderly import get_inactive_elders
    assert ELDER_UID not in [e["user_id"] for e in get_inactive_elders(hours=24)]


def test_inactive_threshold_is_hours_based():
    from data.db_elderly import get_inactive_elders

    _seed(elder_active_hours_ago=30)
    assert ELDER_UID in [e["user_id"] for e in get_inactive_elders(hours=24)]
    _seed(elder_active_hours_ago=10)
    assert ELDER_UID not in [e["user_id"] for e in get_inactive_elders(hours=24)]


def test_notify_inactive_elders_tells_grid_with_family_contact():
    from data.db_core import get_db
    from data.db_elderly import notify_inactive_elders

    _seed(elder_active_hours_ago=30)
    with get_db() as conn:                       # 清掉历史通知，保证可判定
        conn.execute("DELETE FROM notifications WHERE type='elderly_safety'")
        conn.commit()

    assert notify_inactive_elders(hours=24) >= 1
    with get_db() as conn:
        row = conn.execute(
            "SELECT title, content, related_id FROM notifications "
            "WHERE type='elderly_safety' AND user_id=? ORDER BY id DESC LIMIT 1", (GRID_UID,)).fetchone()
    assert row is not None, "网格员必须收到老人安全通知"
    assert "张奶奶" in row["title"]
    # 独居标记 + 子女联系方式（脱敏）——让网格员能直接联系家属
    assert "独居" in row["content"]
    assert "小张" in row["content"]
    assert "138****8000" in row["content"]
    assert "13800138000" not in row["content"], "通知正文不得含完整手机号"


def test_notify_inactive_elders_dedup_within_24h():
    from data.db_elderly import notify_inactive_elders

    _seed(elder_active_hours_ago=30)
    assert notify_inactive_elders(hours=24) == 0, "24h 内不应重复通知同一老人"


# ---------------- 接线守卫（这两条正是本轮回溯出的问题）----------------

def test_elderly_endpoints_record_activity():
    """Vue 主路径必须上报互动：老年端端点至少有 4 处 `_touch(` 调用。"""
    src = io.open(os.path.join(ROOT, "api_routes", "elderly.py"), encoding="utf-8").read()
    assert src.count("_touch(") >= 4, "老年端真实交互处必须调用 _touch（否则久未互动检测在主线上失效）"
    for marker in ("def _touch(", "from data.db_elderly import touch_active"):
        assert marker in src, f"缺少 {marker}"


def test_scheduler_runs_elderly_safety():
    """无人应答巡检必须进调度，而不是只在 Agent 聊天时顺带跑。"""
    src = io.open(os.path.join(ROOT, "scripts", "scheduler.py"), encoding="utf-8").read()
    assert '"elderly_safety"' in src, "run_all() 必须注册老人安全巡检任务"
    assert "notify_inactive_elders" in src, "巡检必须调用 notify_inactive_elders"
