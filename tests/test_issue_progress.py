# -*- coding: utf-8 -*-
"""老人可理解的工单进度（v3 复核 §6-I9）。

**要守住的口径**：
  · 每一步都要说清「现在到哪 / 下一步谁做」（老人不用猜该等谁）；
  · 时限来自**社区规定**且要如实报"还剩多久"；
  · **超时就明说超时**并说明已提醒负责人（不许假装一切正常）；
  · 轮到老人自己确认时**不算超时**（时限是约束社区的，不是催老人的）。
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.issue_progress import STEPS, elderly_progress  # noqa: E402

NOW = datetime(2026, 9, 28, 12, 0, 0)


def test_every_step_says_who_is_next():
    """所有已知状态都必须给出"下一步谁做"（不能留空白让老人猜）。"""
    for status in ("待审核", "已审核待派单", "已派单", "处理中", "待居民反馈",
                   "处理结束", "待协商", "已转出", "退回补充信息"):
        p = elderly_progress({"status": status, "urgency": "一般",
                              "approved_at": "2026-09-28 10:00:00"}, NOW)
        assert p["now_line"] and p["next_line"] and p["who"], f"{status} 缺字段：{p}"
        assert p["steps"] == STEPS


def test_no_system_status_names_leak():
    """老人看得懂：进度文案里不出现"已审核待派单"这类系统状态名。"""
    p = elderly_progress({"status": "已审核待派单", "urgency": "一般",
                          "approved_at": "2026-09-28 10:00:00"}, NOW)
    assert "已审核待派单" not in p["now_line"]
    assert "正在安排维修人员" in p["now_line"]


def test_remaining_time_is_reported():
    """时限按社区规定给，并算出还剩多少小时。"""
    p = elderly_progress({"status": "待审核", "urgency": "一般",
                          "approved_at": "2026-09-28 10:00:00"}, NOW)
    assert "24 小时" in p["eta_line"] and "还剩" in p["eta_line"]
    assert p["overdue"] is False


def test_overdue_is_stated_plainly():
    """**超时如实说**：明说超了多久 + 已提醒负责人，而不是含糊过去。"""
    p = elderly_progress({"status": "处理中", "urgency": "一般",
                          "approved_at": "2026-09-27 10:00:00"}, NOW)
    assert p["overdue"] is True
    assert "超过" in p["eta_line"] and "已提醒负责人" in p["eta_line"]


def test_waiting_on_elder_is_not_overdue():
    """等老人确认时不算超时（不能拿维修时限去催老人）。"""
    p = elderly_progress({"status": "待居民反馈", "urgency": "一般",
                          "approved_at": "2026-09-26 10:00:00",
                          "resolved_at": "2026-09-27 10:00:00"}, NOW)
    assert p["overdue"] is False
    assert "等您确认" in p["eta_line"]
    assert "超过" not in p["eta_line"]


def test_finished_shows_completion_time():
    p = elderly_progress({"status": "处理结束", "urgency": "一般",
                          "approved_at": "2026-09-26 10:00:00",
                          "resolved_at": "2026-09-26 15:30:00"}, NOW)
    assert p["overdue"] is False and "已完成" in p["eta_line"] and "09月26日" in p["eta_line"]


def test_unknown_status_is_honest():
    """没见过的状态也要如实显示，并给出兜底的一句"负责人会跟进"。"""
    p = elderly_progress({"status": "某个新状态", "urgency": "一般"}, NOW)
    assert "某个新状态" in p["now_line"] and p["who"]


def test_missing_timestamps_do_not_crash():
    p = elderly_progress({"status": "待审核", "urgency": "紧急"}, NOW)
    assert "1 小时" in p["eta_line"] and p["overdue"] is False


def test_urgent_has_shorter_window():
    """紧急工单窗口更短（1 小时）—— 这条口径来自社区时限表。"""
    p = elderly_progress({"status": "待审核", "urgency": "紧急",
                          "approved_at": "2026-09-28 11:30:00"}, NOW)
    assert "1 小时" in p["eta_line"]
    assert p["overdue"] is False
