# -*- coding: utf-8 -*-
"""时间口径回归：库内 UTC 与本地时间必须显式换算（2026-09-24 修的时区 bug）。

背景：`data/db_care_proactive.run_followup` 拿本地日期比库里的 UTC 日期做去重，
本地 0:00–8:00（UTC 还在前一天）时去重必然失效——该窗口与"21:00–8:00 静默"重叠，
所以生产上未暴露，但传假 `now` 的测试必然失败，且静默时段一改就会真发重复回访。
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from utils.timeutil import local_to_utc_naive, utc_stamp_of_local, utcnow, utcnow_str  # noqa: E402


def test_utcnow_is_naive_utc():
    now = utcnow()
    assert now.tzinfo is None, "库里存的是 naive 字符串，aware 时间会引发比较异常"
    # 与 UTC 直读之差应在几秒内
    from datetime import timezone as _tz
    delta = abs((datetime.now(_tz.utc).replace(tzinfo=None) - now).total_seconds())
    assert delta < 5


def test_utcnow_str_format_matches_sqlite():
    s = utcnow_str()
    assert len(s) == 19 and s[4] == "-" and s[10] == " " and s[13] == ":"


def test_local_to_utc_shifts_by_machine_offset():
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    local_dt = datetime(2026, 9, 24, 9, 0, 0)
    assert local_to_utc_naive(local_dt) == local_dt - offset
    # 换算后与 utcnow 同口径：取"本地此刻"换算回来应≈真实 UTC 此刻
    delta = abs((local_to_utc_naive(datetime.now()) - utcnow()).total_seconds())
    assert delta < 5


def test_utc_stamp_of_local_is_db_format():
    stamp = utc_stamp_of_local(datetime(2026, 9, 24, 10, 0, 0))
    assert len(stamp) == 19 and stamp.startswith("2026-09-24") or stamp.startswith("2026-09-23")


@pytest.fixture(scope="module")
def _followup_db():
    """复用主动关怀的临时库（同一套 harness，避免污染 config.DB_PATH 全局）。"""
    import config
    from data.db_core import init_db

    _orig = config.DB_PATH
    _tmp = tempfile.mkdtemp(prefix="timeconv_")
    config.DB_PATH = os.path.join(_tmp, "timeconv.db")
    init_db(config.DB_PATH)
    yield
    config.DB_PATH = _orig


def test_followup_writes_explicit_utc_stamp(_followup_db):
    """回归：去重靠 activity_log.created_at，必须**显式写入传入 now 的 UTC 换算值**，
    不能依赖 CURRENT_TIMESTAMP（否则与传入的假 now 对不上，去重永远失败）。"""
    from data.db_core import get_db
    from data.db_care_proactive import run_followup

    uid = 92001
    local_now = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    with get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active) "
                     "VALUES (?, 'u92001', 'resident', '时间口径测试', 1)", (uid,))
        ts = local_to_utc_naive(local_now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("INSERT INTO community_issues (title, status, reporter_id, reported_at, resolved_at) "
                     "VALUES ('时间口径测试工单', '已完成', ?, ?, ?)", (uid, ts, ts))
        conn.commit()

    assert run_followup(now=local_now) == 1
    with get_db() as conn:
        row = conn.execute(
            "SELECT created_at FROM activity_log WHERE module='主动关怀' AND action='办结回访' "
            "ORDER BY id DESC LIMIT 1").fetchone()
    expected = local_to_utc_naive(local_now).strftime("%Y-%m-%d %H:%M:%S")
    assert row["created_at"] == expected, f"时间戳应显式为 {expected}，实际 {row['created_at']}"
    # 幂等：同一天再跑不再发
    assert run_followup(now=local_now) == 0
