# -*- coding: utf-8 -*-
"""Unit tests for tool functions — invoke logic, edge cases, error handling.

Covers every @tool-decorated function in tools/ with tests that validate:
  - Correct input → expected output structure
  - Boundary inputs (empty, invalid, edge) → graceful handling
  - Fallback paths (LLM unavailable, DB empty)
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# -- Helper: create a temp in-memory DB for tests that need one --

def _init_test_db():
    """Init a temporary DB for tool tests."""
    db_path = os.path.join(os.path.dirname(__file__), "_test_tools.db")
    from data.database import init_db
    init_db(db_path)
    return db_path


def _cleanup_test_db(db_path):
    try:
        os.unlink(db_path)
    except Exception:
        pass


# -- 1. report_issue — issue reporting tool --

class TestReportIssue(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_title_returns_error(self):
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({"title": "", "category": "", "location": "", "description": ""})
        self.assertIn("❌", result)
        self.assertIn("标题", result)

    def test_whitespace_title_returns_error(self):
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({"title": "   ", "category": "", "location": "", "description": ""})
        self.assertIn("❌", result)

    def test_minimal_title_creates_issue(self):
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({
            "title": "3号楼灯坏了",
            "category": "设施维修",
            "location": "3号楼",
            "description": "楼道灯不亮",
            "urgency": "普通",
        })
        self.assertIn("✅", result)
        self.assertIn("#", result)

    def test_fast_path_with_category_and_urgency(self):
        """When both category and urgency are provided, skip LLM classification."""
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({
            "title": "楼道堆放杂物",
            "category": "物业服务",
            "location": "3号楼2单元",
            "description": "",
            "urgency": "紧急",
        })
        self.assertIn("✅", result)
        self.assertIn("物业服务", result)
        self.assertIn("紧急", result)

    def test_keyword_classify_fallback(self):
        from tools.action_report_issue import _keyword_classify
        self.assertEqual(_keyword_classify("灯坏了", ""), "设施维修")
        self.assertEqual(_keyword_classify("垃圾没清理", ""), "环境卫生")
        self.assertEqual(_keyword_classify("电线裸露有火灾风险", ""), "安全隐患")
        self.assertEqual(_keyword_classify("停车位被占了", ""), "停车管理")
        self.assertEqual(_keyword_classify("广场舞噪音太大", ""), "噪音扰民")
        self.assertEqual(_keyword_classify("物业保洁不到位", ""), "物业服务")
        self.assertEqual(_keyword_classify("邻里纠纷", ""), "邻里矛盾")
        self.assertEqual(_keyword_classify("老人助餐服务", ""), "社区事务")
        self.assertEqual(_keyword_classify("完全不知道是什么类别", ""), "其他")

    def test_keyword_urgency_fallback(self):
        from tools.action_report_issue import _keyword_urgency
        self.assertEqual(_keyword_urgency("漏电了", ""), "极急")
        self.assertEqual(_keyword_urgency("大面积停电", ""), "极急")
        self.assertEqual(_keyword_urgency("电梯故障了", ""), "紧急")
        self.assertEqual(_keyword_urgency("玻璃碎裂了", ""), "紧急")
        self.assertEqual(_keyword_urgency("灯坏了", ""), "普通")

    def test_validate_location_dorm_no_location(self):
        from tools.action_report_issue import validate_location
        err = validate_location("楼道灯坏了", "")
        self.assertIsNotNone(err)
        self.assertIn("楼栋", err)

    def test_validate_location_dorm_with_location(self):
        from tools.action_report_issue import validate_location
        err = validate_location("楼道灯坏了", "3号楼2单元")
        self.assertIsNone(err)

    def test_validate_location_exempt(self):
        from tools.action_report_issue import validate_location
        # Outdoor/common areas (广场, 花园) are exempt from location requirement
        err = validate_location("7号楼前广场积水", "")
        self.assertIsNone(err)

    def test_classify_cache_hit(self):
        """Verify LLM classify cache works."""
        from tools.action_report_issue import _llm_classify, _classify_cache
        _classify_cache.clear()
        # Prime cache manually
        _classify_cache["test|desc"] = ("设施维修", "普通")
        cat, urg = _llm_classify("test", "desc")
        self.assertEqual(cat, "设施维修")
        self.assertEqual(urg, "普通")
        _classify_cache.clear()

    def test_report_issue_returns_issue_id(self):
        from tools.action_report_issue import report_issue
        import re
        result = report_issue.invoke({
            "title": "测试上报唯一标题xyz",
            "category": "社区事务",
            "location": "测试地点",
            "description": "测试",
            "urgency": "普通",
        })
        self.assertIn("#", result)
        self.assertTrue(re.search(r'#\d+', result))


# -- 2. get_community_pulse — community pulse query --

class TestCommunityPulse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_returns_non_empty_string(self):
        from tools.query_community_pulse import get_community_pulse
        result = get_community_pulse.invoke("")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 20)

    def test_contains_expected_sections(self):
        from tools.query_community_pulse import get_community_pulse
        result = get_community_pulse.invoke("")
        self.assertIn("社区", result)

    def test_generator_produces_valid_text(self):
        from tools.query_community_pulse import _generate_pulse_text
        text = _generate_pulse_text()
        self.assertIsInstance(text, str)
        self.assertTrue(len(text) > 50)


# -- 3. query_issues — issue querying --

class TestQueryIssues(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_db_returns_no_results_message(self):
        from tools.query_community_issues import query_issues
        result = query_issues.invoke({"category": "", "status": "", "limit": 5})
        self.assertIsInstance(result, str)
        # Should indicate no results (DB is empty)
        self.assertTrue("暂无" in result or "安好" in result or "没有" in result)

    def test_with_category_filter(self):
        from tools.query_community_issues import query_issues
        result = query_issues.invoke({"category": "设施维修", "status": "", "limit": 5})
        self.assertIsInstance(result, str)

    def test_with_status_filter(self):
        from tools.query_community_issues import query_issues
        result = query_issues.invoke({"category": "", "status": "待处理", "limit": 5})
        self.assertIsInstance(result, str)


# -- 4. get_governance_stats — governance statistics --

class TestGovernanceStats(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_db_shows_zero_state(self):
        from tools.query_community_issues import get_governance_stats
        result = get_governance_stats.invoke("")
        self.assertIsInstance(result, str)
        # Empty DB should show "暂无" or "良好"
        self.assertTrue(len(result) > 10)

    def test_after_reporting_shows_data(self):
        from tools.action_report_issue import report_issue
        from tools.query_community_issues import get_governance_stats
        report_issue.invoke({
            "title": "测试统计用",
            "category": "设施维修",
            "location": "测试",
            "description": "",
            "urgency": "普通",
        })
        result = get_governance_stats.invoke("")
        self.assertIn("总数", result)


# -- 5. get_weather — weather query --

class TestWeather(unittest.TestCase):

    def test_mock_weather_returns_three_days(self):
        from tools.query_weather import _mock_weather
        days = _mock_weather()
        self.assertEqual(len(days), 3)

    def test_mock_weather_has_required_fields(self):
        from tools.query_weather import _mock_weather
        days = _mock_weather()
        for d in days:
            for key in ["date", "weekday", "condition", "emoji", "temp_high",
                        "temp_low", "rain_prob", "wind", "advice"]:
                self.assertIn(key, d, f"Missing key: {key}")

    def test_get_weather_tool_returns_string(self):
        from tools.query_weather import get_weather
        result = get_weather.invoke("")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 30)

    def test_get_today_weather_returns_tuple(self):
        from tools.query_weather import get_today_weather
        days, loc, is_real = get_today_weather()
        self.assertIsNotNone(days)
        self.assertIsInstance(loc, str)
        self.assertIsInstance(is_real, bool)  # may be real or mock depending on config

    def test_make_advice_storm(self):
        from tools.query_weather import _make_advice
        self.assertIn("减少外出", _make_advice("暴雨", 90))

    def test_make_advice_rain(self):
        from tools.query_weather import _make_advice
        self.assertIn("带伞", _make_advice("小雨", 30))

    def test_make_advice_sunny(self):
        from tools.query_weather import _make_advice
        self.assertIn("防晒", _make_advice("晴", 0))

    def test_make_advice_haze(self):
        from tools.query_weather import _make_advice
        self.assertIn("口罩", _make_advice("霾", 50))

    def test_fallback_weather_returns_string(self):
        from tools.query_weather import _fallback_weather
        result = _fallback_weather("测试原因")
        self.assertIn("测试原因", result)
        self.assertIn("天气", result)


# -- 6. get_proposals — proposal listing --

class TestProposals(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_db_returns_no_results(self):
        from tools.query_proposals import get_proposals
        result = get_proposals.invoke({"category": "", "sort_by": "supporters", "limit": 5})
        self.assertIsInstance(result, str)
        self.assertIn("暂无", result)

    def test_sort_by_latest(self):
        from tools.query_proposals import get_proposals
        result = get_proposals.invoke({"category": "", "sort_by": "latest", "limit": 5})
        self.assertIsInstance(result, str)


# -- 7. create_proposal — proposal creation --

class TestCreateProposal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_title_and_description(self):
        from tools.action_create_proposal import create_proposal
        result = create_proposal.invoke({"title": "", "description": "", "category": "其他"})
        self.assertIn("⚠️", result)

    def test_invalid_category(self):
        from tools.action_create_proposal import create_proposal
        result = create_proposal.invoke({
            "title": "测试提案",
            "description": "详细描述",
            "category": "不存在的分类",
        })
        self.assertIn("无效", result)

    def test_valid_proposal_creation(self):
        from tools.action_create_proposal import create_proposal
        result = create_proposal.invoke({
            "title": "这是一个独特标题用于测试",
            "description": "这是一个详细的提案描述",
            "category": "社区事务",
        })
        self.assertIn("✅", result)
        self.assertIn("#", result)

    def test_duplicate_check_keyword_overlap(self):
        from tools.action_create_proposal import _check_duplicate
        # With empty DB, should return empty list
        dups = _check_duplicate("独一无二的提案标题")
        self.assertEqual(len(dups), 0)


# -- 8. support_proposal — proposal support --

class TestSupportProposal(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_invalid_id_zero(self):
        from tools.action_support_proposal import support_proposal
        result = support_proposal.invoke({"proposal_id": 0})
        self.assertIn("⚠️", result)

    def test_invalid_id_negative(self):
        from tools.action_support_proposal import support_proposal
        result = support_proposal.invoke({"proposal_id": -1})
        self.assertIn("⚠️", result)

    def test_nonexistent_proposal(self):
        from tools.action_support_proposal import support_proposal
        result = support_proposal.invoke({"proposal_id": 99999})
        self.assertIn("未找到", result)


# -- 9. express_opinion — opinion expression --

class TestExpressOpinion(unittest.TestCase):

    def test_invalid_topic_id(self):
        from tools.action_express_opinion import express_opinion
        result = express_opinion.invoke({"topic_id": 0, "content": "我的意见"})
        self.assertIn("⚠️", result)

    def test_empty_content(self):
        from tools.action_express_opinion import express_opinion
        result = express_opinion.invoke({"topic_id": 1, "content": ""})
        self.assertIn("⚠️", result)

    def test_short_content(self):
        from tools.action_express_opinion import express_opinion
        result = express_opinion.invoke({"topic_id": 1, "content": "a"})
        self.assertIn("⚠️", result)


# -- 10. query_knowledge — RAG knowledge search --

class TestQueryKnowledge(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_returns_string_for_query(self):
        from tools.query_knowledge import query_knowledge
        result = query_knowledge.invoke({"query": "助餐点营业时间"})
        self.assertIsInstance(result, str)

    def test_get_community_policy_returns_string(self):
        from tools.query_knowledge import get_community_policy
        result = get_community_policy.invoke({"topic": "居民公约"})
        self.assertIsInstance(result, str)


# -- 11. get_topics — topic listing --

class TestTopics(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_topics_returns_message(self):
        from tools.query_topics import get_topics
        result = get_topics.invoke("")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 10)

    def test_get_topic_detail_invalid_id(self):
        from tools.query_topics import get_topic_detail
        result = get_topic_detail.invoke({"topic_id": 0})
        self.assertIn("⚠️", result)

    def test_discover_hot_topic_empty_db(self):
        from tools.query_topics import _discover_hot_topic
        result = _discover_hot_topic()
        # With empty DB, should return None
        self.assertIsNone(result)


# -- 12. collect_feedback — opinion collection --

class TestCollectFeedback(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db()

    @classmethod
    def tearDownClass(cls):
        _cleanup_test_db(cls._db_path)

    def test_empty_topic_returns_error(self):
        from tools.query_community_issues import collect_feedback
        result = collect_feedback.invoke({"topic": ""})
        self.assertIn("❌", result)

    def test_demo_data_for_unknown_topic(self):
        from tools.query_community_issues import collect_feedback
        result = collect_feedback.invoke({"topic": "停车"})
        self.assertIn("演示数据", result)


# -- 13. Tool discovery --

class TestToolDiscovery(unittest.TestCase):

    def test_discover_tools_returns_list(self):
        from tools import discover_tools
        tool_list = discover_tools()
        self.assertIsInstance(tool_list, list)
        self.assertGreater(len(tool_list), 5, "Should discover at least 6 tools")

    def test_get_tool_names_returns_names(self):
        from tools import get_tool_names
        names = get_tool_names()
        self.assertIsInstance(names, list)
        self.assertGreater(len(names), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
