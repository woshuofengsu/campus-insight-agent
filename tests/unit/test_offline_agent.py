# -*- coding: utf-8 -*-
"""Unit tests for OfflineAgent — routing, response generation, and edge cases.

Covers all persona routing paths, _handle_general branches, _my_issues,
_my_proposals, and helper methods. Uses a temp SQLite DB for DB-dependent paths.
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


def _make_mock_st():
    """Create a mock streamlit session_state with required attributes."""
    mock_st = MagicMock()
    mock_st.langchain_memory = MagicMock()
    mock_st.langchain_memory.chat_memory = MagicMock()
    mock_st.langchain_memory.chat_memory.messages = []
    mock_st._login_user_profile = {
        "name": "测试用户",
        "student_id": "2024001",
        "school": "测试大学",
        "grade": "大三",
        "major": "计算机",
    }
    return mock_st


# ═══════════════════════════════════════════════════════════════
# 1. OfflineAgent._route — Persona Dispatch
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentRoute(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_route.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_route_observer_to_pulse(self):
        persona = {"role": "🌊 校园观察员", "focus_hint": "test", "confidence": "high"}
        result = self.agent._route(persona, "校园脉搏")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 50)

    def test_route_analyst_to_stats(self):
        persona = {"role": "📊 数据分析师", "focus_hint": "test", "confidence": "high"}
        result = self.agent._route(persona, "统计治理数据")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_route_repair_to_report(self):
        persona = {"role": "🔧 报修助手", "focus_hint": "test", "confidence": "high"}
        result = self.agent._route(persona, "教三楼灯坏了")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_route_advisor_to_proposal(self):
        persona = {"role": "🗳️ 议事顾问", "focus_hint": "test", "confidence": "high"}
        result = self.agent._route(persona, "有什么提案")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_route_none_persona(self):
        result = self.agent._route(None, "whatever")
        self.assertIsNone(result)

    def test_route_empty_role(self):
        persona = {"role": "", "focus_hint": "test"}
        result = self.agent._route(persona, "whatever")
        self.assertIsNone(result)

    def test_route_unknown_role(self):
        persona = {"role": "🎭 未知角色", "focus_hint": "test"}
        result = self.agent._route(persona, "whatever")
        self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════
# 2. OfflineAgent._handle_general — Fallback Branches
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentGeneral(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_general.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_greeting_response(self):
        result = self.agent._handle_general("你好")
        self.assertIsNotNone(result)
        self.assertIn("校园", result)

    def test_hi_response(self):
        result = self.agent._handle_general("在吗")
        self.assertIsNotNone(result)
        self.assertIn("校园", result)

    def test_intro_question(self):
        result = self.agent._handle_general("你是谁")
        self.assertIsNotNone(result)
        self.assertIn("校园先知", result)

    def test_help_question(self):
        result = self.agent._handle_general("怎么用")
        self.assertIsNotNone(result)
        self.assertTrue(len(result) > 20)

    def test_thanks_response(self):
        result = self.agent._handle_general("谢谢")
        self.assertIsNotNone(result)
        self.assertTrue(len(result) > 5)

    def test_great_response(self):
        result = self.agent._handle_general("太好了")
        self.assertIsNotNone(result)
        self.assertTrue(len(result) > 5)

    def test_awesome_response(self):
        result = self.agent._handle_general("很棒")
        self.assertIsNotNone(result)
        self.assertTrue(len(result) > 5)

    def test_my_issues_intent(self):
        result = self.agent._handle_general("我的工单")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_my_reports_intent(self):
        result = self.agent._handle_general("我上报的")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_check_issue_intent(self):
        result = self.agent._handle_general("查看工单")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_my_proposals_intent(self):
        result = self.agent._handle_general("我的提案")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, str)

    def test_true_fallback(self):
        result = self.agent._handle_general("xyz123完全不匹配的内容")
        self.assertIsNotNone(result)
        self.assertIn("🤔", result)


# ═══════════════════════════════════════════════════════════════
# 3. OfflineAgent._respond_pulse
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentPulse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_pulse.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_pulse_returns_string(self):
        result = self.agent._respond_pulse()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 50)

    def test_pulse_has_weather_section(self):
        result = self.agent._respond_pulse()
        self.assertIn("🌤️", result)

    def test_pulse_has_hotspot_section(self):
        result = self.agent._respond_pulse()
        self.assertIn("热点", result)

    def test_pulse_has_encouragement(self):
        result = self.agent._respond_pulse()
        self.assertTrue("💡" in result or "🌟" in result or "🙌" in result)


# ═══════════════════════════════════════════════════════════════
# 4. OfflineAgent._respond_stats
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentStats(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_stats.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_stats_returns_string(self):
        result = self.agent._respond_stats("统计治理数据")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 30)

    def test_stats_has_report_header(self):
        result = self.agent._respond_stats("统计数据")
        self.assertIn("治理", result)

    def test_stats_with_facility_filter(self):
        result = self.agent._respond_stats("设施维修统计")
        self.assertIsInstance(result, str)

    def test_stats_with_canteen_filter(self):
        result = self.agent._respond_stats("餐饮问题有多少")
        self.assertIsInstance(result, str)


# ═══════════════════════════════════════════════════════════════
# 5. OfflineAgent._respond_report
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentReport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_report.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_report_returns_success(self):
        result = self.agent._respond_report("教三楼走廊灯坏了")
        self.assertIsInstance(result, str)
        self.assertIn("✅", result)

    def test_report_contains_issue_id(self):
        result = self.agent._respond_report("教三楼灯不亮了")
        self.assertIn("#", result)

    def test_report_extracts_location(self):
        result = self.agent._respond_report("图书馆空调不制冷了")
        self.assertIsInstance(result, str)
        self.assertIn("✅", result)

    def test_report_with_urgent_keywords(self):
        result = self.agent._respond_report("大面积停电需要紧急处理")
        self.assertIsInstance(result, str)

    def test_report_with_encouragement(self):
        result = self.agent._respond_report("教三楼水龙头漏水")
        self.assertTrue("🌟" in result or "🙌" in result or "✨" in result)


# ═══════════════════════════════════════════════════════════════
# 6. OfflineAgent._respond_proposal
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentProposal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_proposal.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_proposal_returns_string(self):
        result = self.agent._respond_proposal("有什么提案")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 20)

    def test_proposal_with_topic_intent(self):
        result = self.agent._respond_proposal("看看有什么议题讨论")
        self.assertIsInstance(result, str)

    def test_proposal_creation_intent(self):
        result = self.agent._respond_proposal("我想创建一个提案")
        self.assertIsInstance(result, str)
        self.assertIn("标题", result)

    def test_proposal_has_encouragement(self):
        result = self.agent._respond_proposal("看看提案")
        self.assertTrue("🙌" in result or "💪" in result or "🗳️" in result)


# ═══════════════════════════════════════════════════════════════
# 7. OfflineAgent.run — Full Pipeline
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentRun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_run.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_run_pulse_returns_response(self):
        result = self.agent.run("校园脉搏")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 50)

    def test_run_repair_returns_response(self):
        result = self.agent.run("教三楼灯坏了")
        self.assertIsInstance(result, str)
        self.assertIn("✅", result)

    def test_run_greeting_returns_response(self):
        result = self.agent.run("你好")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 10)

    def test_run_stats_returns_response(self):
        result = self.agent.run("统计治理数据")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 20)

    def test_run_proposal_returns_response(self):
        result = self.agent.run("有什么提案")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 20)

    def test_conversation_turns_increment(self):
        initial = self.agent._conversation_turns
        self.agent.run("你好")
        self.assertEqual(self.agent._conversation_turns, initial + 1)

    def test_get_last_chain(self):
        chain = self.agent.get_last_chain()
        # Chain may be None for offline agent (no LLM chain)
        self.assertTrue(chain is None or isinstance(chain, dict))


# ═══════════════════════════════════════════════════════════════
# 8. OfflineAgent — Helper Methods
# ═══════════════════════════════════════════════════════════════

class TestOfflineAgentHelpers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = os.path.join(
            os.path.dirname(__file__), "_test_offline_helpers.db"
        )
        from data.database import init_db
        init_db(cls._db_path)

        from agent.offline_agent import OfflineAgent
        cls.agent = OfflineAgent(_make_mock_st())

    @classmethod
    def tearDownClass(cls):
        try:
            os.unlink(cls._db_path)
        except Exception:
            pass

    def test_get_name(self):
        name = self.agent._get_name()
        # May be empty outside Streamlit context — graceful degradation
        self.assertIsInstance(name, str)

    def test_get_author_identifier(self):
        author = self.agent._get_author_identifier()
        # May be None outside Streamlit context — graceful degradation
        self.assertTrue(author is None or isinstance(author, str))

    def test_extract_location(self):
        loc = self.agent._extract_location("教三楼灯坏了")
        self.assertEqual(loc, "教三楼")

    def test_extract_weather_line(self):
        text = "📌 今天 周一 ☀️ 晴天\n    气温：15°C ~ 25°C"
        result = self.agent._extract_weather_line(text)
        self.assertTrue(len(result) > 5)

    def test_extract_weather_line_no_match(self):
        result = self.agent._extract_weather_line("no weather data here")
        self.assertTrue(len(result) > 0)

    def test_reformat_stats(self):
        raw = "📊 校园治理数据总览\n\n  📝 问题总数：10\n  ⏳ 待处理：5\n  ✅ 已解决：5"
        result = self.agent._reformat_stats(raw)
        self.assertIsInstance(result, str)

    def test_reformat_issue_list(self):
        raw = "  #1 🔧 设施维修 ⏳ 待处理\n     📝 灯坏了"
        result = self.agent._reformat_issue_list(raw)
        self.assertIsInstance(result, str)

    def test_build_stats_from_db(self):
        stats = {
            "total": 50,
            "by_status": {"待处理": 10, "处理中": 5, "已解决": 35},
            "by_category": {"设施维修": 20, "环境卫生": 15},
        }
        result = self.agent._build_stats_from_db(stats)
        self.assertIn("50", result)
        self.assertIn("设施维修", result)

    def test_build_stats_from_db_empty(self):
        stats = {"total": 0, "by_status": {}, "by_category": {}}
        result = self.agent._build_stats_from_db(stats)
        self.assertIsInstance(result, str)

    def test_random_encouragement(self):
        result = self.agent._random_encouragement("pulse")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
