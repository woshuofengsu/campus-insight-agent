# -*- coding: utf-8 -*-
"""M3：用药打卡闭环（medication_intake_log / v42）测试。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402

_tmp = tempfile.mkdtemp(prefix="intake_")
config.DB_PATH = os.path.join(_tmp, "intake.db")

from data.db_core import init_db  # noqa: E402
init_db(config.DB_PATH)

from data import db_elderly_care as ec  # noqa: E402
from data.db_core import get_db  # noqa: E402


def _reminder(uid, rid):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO medication_reminders (id, user_id, patient_name, drug_name, "
            "status, setter_id) VALUES (?,?,?,?, '审核通过', ?)",
            (rid, uid, "测试老人", "降压药", uid))
        conn.commit()


def test_v42_table_exists():
    with get_db() as conn:
        t = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='medication_intake_log'").fetchone()
        assert t, "v42 表应存在"


def test_mark_intake_and_streak():
    _reminder(90001, 90011)
    ok, msg, s = ec.mark_intake(90001, 90011, action="taken")
    assert ok and s >= 1
    # 重复 taken 幂等（同日 UNIQUE 挡住）
    ok2, msg2, s2 = ec.mark_intake(90001, 90011, action="taken")
    assert not ok2 and s2 >= 1


def test_streak_across_days():
    # 直接插 3 天连续（含今天），验证连续计数
    from datetime import date, timedelta
    with get_db() as conn:
        for i in range(3):
            d = (date.today() - timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT INTO medication_intake_log (user_id, reminder_id, intake_date, action) "
                "VALUES (90002, 90012, ?, 'taken')", (d,))
        conn.commit()
    assert ec.get_intake_streak(90002) == 3


def test_toggle_invalid_action():
    ok, msg, s = ec.mark_intake(90003, 90013, action="weird")
    assert not ok
