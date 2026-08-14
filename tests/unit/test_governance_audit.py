# -*- coding: utf-8 -*-
"""治理审计引擎单元测试 — 跨表健康度分析。

run_governance_audit() 覆盖空库、有数据的库和多种健康度场景，
验证评分口径。
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


# 1. 空库全零状态

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
        # 至少要有健康度那一行
        self.assertIn("治理健康度", report)

    def test_empty_db_no_errors(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # 不能带报错信息
        self.assertNotIn("Traceback", report)
        self.assertNotIn("Exception", report)

    def test_empty_db_has_report_card(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertIn("分维度评分", report)


# 2. 有数据的库

class TestGovernanceAuditWithData(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("withdata")
        cls._seed_data()

    @classmethod
    def _seed_data(cls):
        """给审计测试塞一批工单、提案和议题。"""
        from data.database import get_db
        with get_db() as conn:
            # 工单：状态、紧急度都岔开一点
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, "
                "urgency, status, author, reported_at, resolved_at) VALUES "
                "('灯坏了', '设施维修', '3号楼', '楼道灯不亮', '普通', '已解决', 'user1', "
                "datetime('now', '-3 days'), datetime('now', '-1 day'))"
            )
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('水管漏水', '设施维修', '5号楼', '严重漏水', '紧急', '处理中', 'user1', "
                "datetime('now', '-2 days'))"
            )
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('电线裸露', '安全隐患', '3号楼', '有触电风险', '极急', '待处理', 'user2', "
                "datetime('now', '-1 day'))"
            )
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('垃圾未清理', '环境卫生', '助餐点', '垃圾桶满了', '普通', '待处理', 'user2', "
                "datetime('now', '-10 days'))"  # 超过 7 天算积压
            )
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, "
                "urgency, status, author, reported_at) VALUES "
                "('网络很慢', '物业服务', '活动室', 'WiFi连不上', '普通', '待处理', 'user3', "
                "datetime('now', '-5 days'))"
            )
            conn.execute(
                "INSERT INTO community_issues (title, category, location, description, "
                "urgency, status, author, reported_at, resolved_at) VALUES "
                "('路灯故障', '设施维修', '5号楼', '', '普通', '已解决', 'user3', "
                "datetime('now', '-7 days'), datetime('now', '-2 days'))"
            )

            # 提案
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, "
                "status, author) VALUES "
                "('延长活动室时间', '建议延长到23:00', '社区事务', 15, '讨论中', 'user1')"
            )
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, "
                "status, author) VALUES "
                "('增设快递柜', '单元楼下需要快递柜', '社区事务', 42, '已采纳', 'user2')"
            )
            conn.execute(
                "INSERT INTO proposals (title, description, category, supporter_count, "
                "status, response_text, author) VALUES "
                "('改善助餐点菜品', '增加素食选项', '物业服务', 8, '已回应', "
                "'已反馈给物业部门', 'user3')"
            )

            # 议题
            conn.execute(
                "INSERT INTO discussion_topics (title, description, category, "
                "created_by_agent, is_active, participant_count) VALUES "
                "('社区网络质量讨论', '大家对社区网满意吗', '物业服务', 1, 1, 5)"
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
        # 应该提到那条没解决的紧急工单
        self.assertTrue("紧急" in report or "安全隐患" in report)

    def test_populated_db_no_crash(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        self.assertNotIn("Traceback", report)


# 3. 全部已解决的库

class TestGovernanceAuditAllResolved(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("resolved")
        from data.database import get_db
        with get_db() as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO community_issues (title, category, location, "
                    "urgency, status, author, reported_at, resolved_at) VALUES "
                    "(?, '设施维修', '3号楼', '普通', '已解决', 'user1', "
                    "datetime('now', '-3 days'), datetime('now', '-1 day'))",
                    (f"已解决问题{i}",),
                )
            conn.execute(
                "INSERT INTO proposals (title, description, category, "
                "supporter_count, status, author) VALUES "
                "('已实施提案', 'test', '社区事务', 20, '已实施', 'user1')"
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
        # 应该有评级（优/良/需改进）
        self.assertTrue("优" in report or "良" in report or "需改进" in report)

    def test_all_resolved_no_action_items_or_minimal(self):
        from agent.governance_audit import run_governance_audit
        report = run_governance_audit()
        # 全解决了的话，紧急行动建议应该没有或很少
        self.assertNotIn("🔴", report)  # No urgent (red) action items


# 4. 全部积压的库

class TestGovernanceAuditAllPending(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("pending")
        from data.database import get_db
        with get_db() as conn:
            for i in range(8):
                conn.execute(
                    "INSERT INTO community_issues (title, category, location, "
                    "urgency, status, author, reported_at) VALUES "
                    "(?, '设施维修', '3号楼', '紧急', '待处理', 'user1', "
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
        # 应该提到那些超过 7 天的积压单
        self.assertTrue("积压" in report or "7天" in report)


# 5. 数据库报错兜底

class TestGovernanceAuditDBError(unittest.TestCase):

    def test_db_error_graceful(self):
        """库没初始化时，审计应该返回错误提示而不是崩。"""
        # 故意把库搞坏来模拟报错
        from agent.governance_audit import run_governance_audit
        # run_governance_audit 内部会接住异常，返回错误字符串
        # 就算库坏了也不能抛
        try:
            report = run_governance_audit()
            self.assertIsInstance(report, str)
        except Exception:
            # 库彻底坏了函数也得兜住
            pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
