# -*- coding: utf-8 -*-
"""语义兜底测试 — 关键业务口径的回归保护。

覆盖 4 个易错语义（防止未来重构时口径回退）：
  1. SLA 时区：julianday('now') 与 UTC 存储同源，新工单不误判超时（回归 +8h bug）
  2. 分级边界：极急 6h / 紧急 24h / 普通 72h 的临界判定
  3. 满意度闭环：不满意重开 + 重新解决后评价与原因重置
  4. 匿名：匿名上报存稳定伪名（哈希），不泄露真实身份，且后台保留 reporter_id
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _init_test_db(name: str) -> str:
    db_path = os.path.join(os.path.dirname(__file__), f"_test_semantics_{name}.db")
    from data.database import init_db
    init_db(db_path)
    return db_path


def _cleanup_test_db(db_path: str):
    try:
        os.unlink(db_path)
    except Exception:
        pass


def _utc_hours_ago(hours: float) -> str:
    """返回 hours 小时前的 UTC 时间，格式跟 SQLite CURRENT_TIMESTAMP 一致。"""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")


def _insert_issue(conn, title: str, category: str = "设施维修", urgency: str = "普通",
                  status: str = "待处理", reported_at: str | None = None) -> int:
    if reported_at is None:
        reported_at = _utc_hours_ago(0)
    cur = conn.execute(
        "INSERT INTO community_issues (title, category, urgency, status, reported_at) "
        "VALUES (?,?,?,?,?)",
        (title, category, urgency, status, reported_at),
    )
    conn.commit()
    return cur.lastrowid


# 1. SLA 时区

class TestSLATimezone(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("tz")
        from data.database import get_db
        with get_db() as conn:
            cls._fresh_id = _insert_issue(
                conn, "刚报的电梯困人", "安全隐患", "极急", "待处理", _utc_hours_ago(0.5)
            )

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_fresh_urgent_issue_not_flagged_as_breached(self):
        from data.db_sla import get_sla_breaches
        ids = [b["id"] for b in get_sla_breaches()]
        self.assertNotIn(self._fresh_id, ids)


# 2. 分级边界

class TestSLABoundaries(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("bound")
        from data.database import get_db
        with get_db() as conn:
            cls.urgent_ok = _insert_issue(conn, "极急5小时", "安全隐患", "极急", "待处理", _utc_hours_ago(5))
            cls.urgent_over = _insert_issue(conn, "极急7小时", "安全隐患", "极急", "待处理", _utc_hours_ago(7))
            cls.normal_ok = _insert_issue(conn, "普通71小时", "设施维修", "普通", "待处理", _utc_hours_ago(71))
            cls.normal_over = _insert_issue(conn, "普通73小时", "设施维修", "普通", "待处理", _utc_hours_ago(73))

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_grading_boundaries(self):
        from data.db_sla import get_sla_breaches
        breaches = {b["id"]: b for b in get_sla_breaches()}
        self.assertNotIn(self.urgent_ok, breaches)    # 5h < 6h 极急 SLA
        self.assertIn(self.urgent_over, breaches)     # 7h > 6h
        self.assertNotIn(self.normal_ok, breaches)    # 71h < 72h 普通 SLA
        self.assertIn(self.normal_over, breaches)     # 73h > 72h
        self.assertEqual(breaches[self.urgent_over]["level"], "critical")
        self.assertEqual(breaches[self.normal_over]["level"], "overdue")


# 3. 满意度闭环

class TestSatisfactionClosedLoop(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("sat")

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_dissatisfied_goes_to_review_then_reopen_resets(self):
        from data.database import get_db, update_issue_status, set_satisfaction, review_dissatisfaction
        with get_db() as conn:
            iid = _insert_issue(conn, "满意度复核测试", "设施维修", "普通", "待处理")

        update_issue_status(iid, "已解决", actor="网格员")

        # 不满意 → 待复核（不直接重开，堵住居民单方面刷单）
        final = set_satisfaction(iid, "不满意", reason="处理不彻底，仍在漏水")
        self.assertEqual(final, "待复核")
        with get_db() as conn:
            row = conn.execute(
                "SELECT status, satisfaction, satisfaction_reason FROM community_issues WHERE id = ?",
                (iid,),
            ).fetchone()
        self.assertEqual(row["status"], "待复核")
        self.assertEqual(row["satisfaction"], "不满意")
        self.assertEqual(row["satisfaction_reason"], "处理不彻底，仍在漏水")

        # 网格员确认重开
        final2 = review_dissatisfaction(iid, reopen=True)
        self.assertEqual(final2, "待处理")

        # 再次解决 → 评价与原因重置，居民可再次评价
        update_issue_status(iid, "已解决", actor="网格员")
        with get_db() as conn:
            row = conn.execute(
                "SELECT satisfaction, satisfaction_reason FROM community_issues WHERE id = ?",
                (iid,),
            ).fetchone()
        self.assertEqual(row["satisfaction"], "")
        self.assertEqual(row["satisfaction_reason"], "")

    def test_dissatisfied_can_be_dismissed(self):
        from data.database import get_db, update_issue_status, set_satisfaction, review_dissatisfaction
        with get_db() as conn:
            iid = _insert_issue(conn, "满意度驳回测试", "设施维修", "普通", "待处理")

        update_issue_status(iid, "已解决", actor="网格员")
        set_satisfaction(iid, "不满意", reason="误点")

        # 网格员驳回 → 维持已解决，评价保留但不重开
        final = review_dissatisfaction(iid, reopen=False)
        self.assertEqual(final, "已解决")
        with get_db() as conn:
            row = conn.execute(
                "SELECT status, satisfaction FROM community_issues WHERE id = ?", (iid,)
            ).fetchone()
        self.assertEqual(row["status"], "已解决")
        self.assertEqual(row["satisfaction"], "不满意")


# 4. 匿名

class TestAnonymousReporting(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("anon")

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_anonymized_author_stable_and_distinct(self):
        from data.db_governance import anonymized_author
        a1 = anonymized_author("user:1")
        a2 = anonymized_author("user:1")
        a3 = anonymized_author("user:2")
        self.assertEqual(a1, a2)                    # 稳定
        self.assertNotEqual(a1, a3)                 # 不同身份不同伪名
        self.assertTrue(a1.startswith("匿名居民#"))  # 伪名前缀，不暴露真实身份
        self.assertEqual(anonymized_author(""), "匿名居民")

    def test_anonymous_report_hides_real_identity(self):
        from data.database import get_db, report_issue
        from data.db_governance import anonymized_author

        iid = report_issue(
            "匿名诉求", "设施维修", urgency="普通",
            author="王阿姨", reporter_id=42, anonymous=True,
        )
        with get_db() as conn:
            row = conn.execute(
                "SELECT author, reporter_id FROM community_issues WHERE id = ?", (iid,)
            ).fetchone()
        self.assertEqual(row["author"], anonymized_author("user:42"))
        self.assertNotIn("王阿姨", row["author"])
        self.assertEqual(row["reporter_id"], 42)  # 后台仍保留 reporter_id 供闭环通知


if __name__ == "__main__":
    unittest.main()
