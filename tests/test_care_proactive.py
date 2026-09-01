# -*- coding: utf-8 -*-
"""M4：主动关怀（办结回访 + 久未活跃）测试。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="proactive_")
config.DB_PATH = os.path.join(_tmp, "proactive.db")

from data.db_core import init_db  # noqa: E402
init_db(config.DB_PATH)

from data import db_care_proactive as cp  # noqa: E402
from data.db_core import get_db  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402


def _seed(uid, title, status, days_ago):
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active) "
                     "VALUES (?, ?, 'resident', '测试居民', 1)", (uid, f"u{uid}"))
        ts = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO community_issues (title, status, reporter_id, reported_at, resolved_at) "
            "VALUES (?,?,?,?,?)",
            (title, status, uid, ts, ts if status == "已完成" else None))
        conn.commit()


def test_followup_creates_notification():
    """昨日办结的工单 → 回访通知。今日重复运行幂等。"""
    _seed(91001, "自来水管道维修", "已完成", 1)
    n1 = cp.run_followup(now=datetime.now())
    assert n1 >= 1
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM notifications WHERE user_id=91001 AND type='followup'").fetchone()
        assert row["c"] >= 1
    # 幂等：再跑一次，不重复创建（今日已回访）
    n2 = cp.run_followup(now=datetime.now())
    assert n2 == 0


def test_followup_not_on_pending():
    """未办结/非昨日的不产生回访。"""
    _seed(91002, "还在处理", "处理中", 1)
    before = cp.run_followup(now=datetime.now())
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM notifications WHERE user_id=91002").fetchone()
        assert row["c"] == 0


def test_inactive_elderly_lists_old_users():
    """久未活跃（无活动记录）→ 被列出。"""
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active) "
                     "VALUES (92001, 'inactive_elder1', 'elderly', '李阿姨', 1)")
        conn.execute("INSERT OR REPLACE INTO elderly_profile (user_id) VALUES (92001)")
        conn.commit()
    lst = cp.list_inactive_elderly(days=5, limit=20)
    assert any(x["user_id"] == 92001 for x in lst)
