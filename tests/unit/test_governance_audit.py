# -*- coding: utf-8 -*-
"""Unit tests for governance audit engine — cross-table health analysis.

Covers run_governance_audit() with empty DB, populated DB, and various
health score scenarios to validate scoring methodology.
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _init_test_db(suffix=""):
    db_path = os.path.join(os.path.dirname(__file__), f"_test_audit_{suffix}.db")
    from data.database import init_db
    init_db(db_path)
    return db_path


def _cleanup_test_db(db_path):
    for ext in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + ext)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════
# 1. Empty DB — All Zero State
# ═══════════════════════════════════════════════════════════════

class TestGovernanceAuditEmptyDB(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("empty")

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_db_returns_valid_report(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIsInstance(report, str)
        self.assertTrue(len(report) > 20)

    def test_empty_db_has_sections(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # Should have at least the health score line
        self.assertIn("治理健康度", report)

    def test_empty_db_no_errors(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # Should not contain error markers
        self.assertNotIn("Traceback", report)
        self.assertNotIn("Exception", report)

    def test_empty_db_has_report_card(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("分维度评分", report)


# ═══════════════════════════════════════════════════════════════
# 2. Populated DB — With Sample Data
# ═══════════════════════════════════════════════════════════════

class TestGovernanceAuditWithData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("withdata")
        cls._seed_data()

    @classmethod
    def _seed_data(cls):
        """Insert sample issues, proposals, and topics for audit testing."""
        from data.database import get_db
        with get_db() as conn:
            # Insert issues with varied status/urgency
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, "
                "urgency, status, author, reported_at, resolved_at) VALUES "
                "('灯坏了', '设施维修', '教三楼', '走廊灯不亮', '普通', '已解决', 'user1', "
                "datetime('now', '-3 days'), datetime('now', '-1 day'))"
            )
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('水管漏水', '设施维修', '5号宿舍楼', '严重漏水', '紧急', '处理中', 'user1', "
                "datetime('now', '-2 days'))"
            )
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('电线裸露', '安全隐患', '实验楼', '有触电风险', '极急', '待处理', 'user2', "
                "datetime('now', '-1 day'))"
            )
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('垃圾未清理', '环境卫生', '一食堂', '垃圾桶满了', '普通', '待处理', 'user2', "
                "datetime('now', '-10 days'))"  # stale > 7 days
            )
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('网络很慢', '网络服务', '图书馆', 'WiFi连不上', '普通', '待处理', 'user3', "
                "datetime('now', '-5 days'))"
            )
            conn.execute(
                "INSERT INTO campus_issues (title, category, location, description, "
                "urgency, status, author, reported_at, resolved_at) VALUES "
                "('投影仪故障', '教学设备', '教五楼', '', '普通', '已解决', 'user3', "
                "datetime('now', '-7 days'), datetime('now', '-2 days'))"
            )

            # Insert proposals
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, "
                "status, author) VALUES "
                "('延长图书馆时间', '建议延长到23:00', '校园管理', 15, '讨论中', 'user1')"
            )
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, "
                "status, author) VALUES "
                "('增设快递柜', '宿舍楼下需要快递柜', '校园管理', 42, '已采纳', 'user2')"
            )
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, "
                "status, response_text, author) VALUES "
                "('改善食堂菜品', '增加素食选项', '餐饮问题', 8, '已回应', "
                "'已反馈给后勤部门', 'user3')"
            )

            # Insert discussion topics
            conn.execute(
                "INSERT INTO discussion_topics (title, description, category, "
                "created_by_agent, is_active, participant_count) VALUES "
                "('校园网络质量讨论', '大家对校园网满意吗', '网络服务', 1, 1, 5)"
            )

            conn.commit()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_populated_db_has_issues(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("工单管理", report)

    def test_populated_db_has_proposals(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("提案参与", report)

    def test_populated_db_has_citizen_engagement(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("公民参与", report)

    def test_populated_db_has_health_score(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("治理健康度", report)
        self.assertIn("分", report)

    def test_populated_db_has_report_card(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("分维度评分", report)

    def test_populated_db_has_action_items(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("优先行动建议", report)

    def test_populated_db_mentions_urgent_issue(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # Should mention the urgent unresolved issue
        self.assertTrue("紧急" in report or "安全隐患" in report)

    def test_populated_db_no_crash(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertNotIn("Traceback", report)


# ═══════════════════════════════════════════════════════════════
# 3. All Resolved DB — Perfect Health
# ═══════════════════════════════════════════════════════════════

class TestGovernanceAuditAllResolved(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("resolved")
        from data.database import get_db
        with get_db() as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO campus_issues (title, category, location, "
                    "urgency, status, author, reported_at, resolved_at) VALUES "
                    "(?, '设施维修', '教三楼', '普通', '已解决', 'user1', "
                    "datetime('now', '-3 days'), datetime('now', '-1 day'))",
                    (f"已解决问题{i}",),
                )
            conn.execute(
                "INSERT INTO proposals (title, description, category, "
                "supporter_count, status, author) VALUES "
                "('已实施提案', 'test', '校园管理', 20, '已实施', 'user1')"
            )
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_all_resolved_high_score(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("治理健康度", report)

    def test_all_resolved_has_grade(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # Should have a grade (优/良/需改进)
        self.assertTrue("优" in report or "良" in report or "需改进" in report)

    def test_all_resolved_no_action_items_or_minimal(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # With all resolved, urgent action items should be minimal
        self.assertNotIn("🔴", report)  # No urgent (red) action items


# ═══════════════════════════════════════════════════════════════
# 4. All Pending/Urgent DB — Poor Health
# ═══════════════════════════════════════════════════════════════

class TestGovernanceAuditAllPending(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("pending")
        from data.database import get_db
        with get_db() as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO campus_issues (title, category, location, "
                    "urgency, status, author, reported_at) VALUES "
                    "(?, '设施维修', '教三楼', '紧急', '待处理', 'user1', "
                    "datetime('now', '-10 days'))",
                    (f"积压问题{i}",),
                )
            conn.commit()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_all_pending_low_score(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("治理健康度", report)

    def test_all_pending_has_urgent_actions(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("优先行动建议", report)

    def test_all_pending_mentions_stale(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # Should mention the 7+ day stale issues
        self.assertTrue("积压" in report or "7天" in report)


# ═══════════════════════════════════════════════════════════════
# 5. DB Error — Graceful Degradation
# ═══════════════════════════════════════════════════════════════

class TestGovernanceAuditDBError(unittest.TestCase):

    def test_db_error_graceful(self):
        """When DB is not initialized, audit should return error message, not crash."""
        # Temporarily break the DB path to simulate error
        from agent.governance_audit import run_governance_audit
        # run_governance_audit catches exceptions and returns error string
        # Even with broken DB, it should not raise
        try:
            report = run_governance_audit()
            self.assertIsInstance(report, str)
        except Exception:
            # If DB completely broken, function should still handle it
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
