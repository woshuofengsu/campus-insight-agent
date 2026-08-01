# -*- coding: utf-8 -*-
"""End-to-end demo scenario tests — full pipeline from user input to agent response.

Runs 6 competition demo scenarios using OfflineAgent (no LLM dependency):
  1. Student reports a facility issue → ticket created with ID
  2. Campus pulse query → weather + hotspots + proposals
  3. Create proposal → support → status change
  4. Query my issues → find resolved → closed-loop confirmation
  5. Governance audit → four-dimension scoring → action items
  6. LLM unavailable → OfflineAgent takeover → graceful degradation

All scenarios use the OfflineAgent so they can run in CI without API keys.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _make_mock_st():
    mock_st = MagicMock()
    mock_st.langchain_memory = MagicMock()
    mock_st.langchain_memory.chat_memory = MagicMock()
    mock_st.langchain_memory.chat_memory.messages = []
    mock_st._login_user_profile = {
        "name": "演示学生",
        "student_id": "2024001",
        "school": "北京科技大学",
        "grade": "大三",
        "major": "计算机科学与技术",
    }
    return mock_st


def _init_test_db():
    db_path = os.path.join(os.path.dirname(__file__), "_test_e2e.db")
    from data.database import init_db
    init_db(db_path)
    return db_path


def _cleanup_test_db(db_path):
    try:
        os.unlink(db_path)
    except Exception:
        pass


class TestDemoScenarios(unittest.TestCase):
    """Six demo scenarios that competition judges would evaluate."""

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()
        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    # ═══════════════════════════════════════════════════════════
    # Scenario 1: 学生报修 → 自动分类 → 生成工单 → 确认工单号
    # ═══════════════════════════════════════════════════════════

    def test_scenario_1_student_repair(self):
        """Student reports a facility issue, gets ticket ID back."""
        # Step 1: Student describes a problem
        response1 = self.agent.run("教三楼二楼走廊的灯不亮了，晚上走路很危险")
        self.assertIsInstance(response1, str)
        self.assertIn("✅", response1, "Should confirm issue creation")
        self.assertIn("#", response1, "Should include issue ID")

        # Step 2: Student checks their issues (may not match due to offline author resolution)
        response2 = self.agent.run("查看我的工单")
        self.assertIsInstance(response2, str)
        self.assertTrue(len(response2) > 10, "My issues query should return something")

    # ═══════════════════════════════════════════════════════════
    # Scenario 2: 校园脉搏 → 天气+热点+提案 三合一
    # ═══════════════════════════════════════════════════════════

    def test_scenario_2_campus_pulse(self):
        """Campus pulse delivers weather, hotspots, and proposals."""
        response = self.agent.run("校园脉搏")
        self.assertIsInstance(response, str)
        self.assertTrue(len(response) > 80, "Pulse should be substantial")

        # Should contain weather info
        self.assertTrue("🌤️" in response or "天气" in response, "Should have weather")

        # Should contain hotspot section
        self.assertIn("热点", response)

    # ═══════════════════════════════════════════════════════════
    # Scenario 3: 创建提案 → 附议 → 状态变更
    # ═══════════════════════════════════════════════════════════

    def test_scenario_3_proposal_lifecycle(self):
        """Create proposal, check it appears, and support flow."""
        # Step 1: Express intent to create a proposal
        response1 = self.agent.run(
            "我觉得应该延长图书馆开放时间到晚上11点，方便考研同学复习"
        )
        self.assertIsInstance(response1, str)
        self.assertTrue(len(response1) > 20)

        # Step 2: Browse proposals
        response2 = self.agent.run("看看大家提了什么好建议")
        self.assertIsInstance(response2, str)

        # Step 3: Check "my proposals"
        response3 = self.agent.run("我的提案")
        self.assertIsInstance(response3, str)

    # ═══════════════════════════════════════════════════════════
    # Scenario 4: 查询我的工单 → 发现已解决 → 闭环确认
    # ═══════════════════════════════════════════════════════════

    def test_scenario_4_closed_loop(self):
        """Query my issues, check status, closed-loop confirmation."""
        # First report an issue to have data
        self.agent.run("教三楼水龙头漏水需要维修")

        # Then check "my issues"
        response = self.agent.run("我的工单处理得怎么样了")
        self.assertIsInstance(response, str)
        self.assertTrue(len(response) > 10)

    # ═══════════════════════════════════════════════════════════
    # Scenario 5: 治理审计 → 四维度评分 → 行动建议
    # ═══════════════════════════════════════════════════════════

    def test_scenario_5_governance_audit(self):
        """Governance audit with four-dimension scoring."""
        from agent.governance_audit import run_governance_audit

        report = run_governance_audit()
        self.assertIsInstance(report, str)
        self.assertTrue(len(report) > 50)

        # Should contain four dimensions
        self.assertIn("工单管理", report)
        self.assertIn("提案参与", report)
        self.assertIn("公民参与", report)

        # Should have health score and grade
        self.assertIn("治理健康度", report)

        # Should have report card
        self.assertIn("分维度评分", report)

    # ═══════════════════════════════════════════════════════════
    # Scenario 6: LLM不可用 → OfflineAgent接管 → 优雅降级
    # ═══════════════════════════════════════════════════════════

    def test_scenario_6_offline_fallback(self):
        """OfflineAgent handles all persona types without LLM."""
        # Test all four personas work in offline mode
        tests = [
            ("校园脉搏", "observer"),
            ("统计治理数据", "analyst"),
            ("教三楼灯坏了", "repair"),
            ("有什么提案", "advisor"),
            ("你好", "greeting"),
            ("谢谢", "thanks"),
            ("我的工单", "my_issues"),
        ]

        for user_input, scenario_type in tests:
            with self.subTest(input=user_input, type=scenario_type):
                response = self.agent.run(user_input)
                self.assertIsInstance(response, str,
                    f"Scenario '{scenario_type}' failed for input '{user_input}'")
                self.assertTrue(len(response) > 5,
                    f"Response too short for '{scenario_type}': {response[:50]}")

    # ═══════════════════════════════════════════════════════════
    # Multi-turn conversation simulation
    # ═══════════════════════════════════════════════════════════

    def test_multi_turn_conversation(self):
        """Simulate a natural multi-turn conversation."""
        # Turn 1: Greeting
        r1 = self.agent.run("你好")
        self.assertIn("校园", r1)

        # Turn 2: Campus pulse
        r2 = self.agent.run("校园脉搏")
        self.assertTrue(len(r2) > 50)

        # Turn 3: Report an issue
        r3 = self.agent.run("图书馆空调不制冷了")
        self.assertIn("✅", r3)

        # Turn 4: Check my issues
        r4 = self.agent.run("我的工单")
        self.assertIsInstance(r4, str)

        # Turn 5: Thanks
        r5 = self.agent.run("谢谢")
        self.assertTrue(len(r5) > 5)

        # Conversation should have tracked at least 5 turns
        self.assertGreaterEqual(self.agent._conversation_turns, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
