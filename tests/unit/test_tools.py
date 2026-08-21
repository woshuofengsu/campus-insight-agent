# -*- coding: utf-8 -*-
"""工具函数单元测试 — 调用逻辑、边界情况、错误处理。

tools/ 里每个带 @tool 装饰器的函数都要覆盖到：
  - 正常输入 → 输出结构符合预期
  - 边界输入（空、非法、极端）→ 能优雅处理
  - 兜底路径（LLM 不可用、数据库为空）
"""
import sys
import os
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# 需要建临时库的测试共用一个初始化函数

def _init_test_db():
    """给工具测试建一个临时库。"""
    db_path = os.path.join(os.path.dirname(__file__), "_test_tools.db")
    from data.database import init_db
    init_db(db_path)
    return db_path


def _cleanup_test_db(db_path):
    try:
        os.unlink(db_path)
    except Exception:
        pass


# 1. report_issue 报修工具

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
        self.assertIn("问题描述", result)

    def test_whitespace_title_returns_error(self):
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({"title": "   ", "category": "", "location": "", "description": ""})
        self.assertIn("❌", result)

    def test_minimal_title_creates_issue(self):
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({
            "title": "3号楼灯坏了",
            "category": "设施维修",
            "location": "幸福小区3号楼",
            "description": "楼道灯不亮",
            "urgency": "普通",
            "reporter_name": "王阿姨",
            "reporter_phone": "13800138000",
        })
        self.assertIn("✅", result)
        self.assertIn("#", result)

    def test_fast_path_with_category_and_urgency(self):
        """分类和紧急度都给了就直接走，跳过 LLM 分类。"""
        from tools.action_report_issue import report_issue
        result = report_issue.invoke({
            "title": "楼道堆放杂物",
            "category": "物业服务",
            "location": "幸福小区3号楼2单元",
            "description": "楼道堆了很多杂物影响通行",
            "urgency": "紧急",
            "reporter_name": "王阿姨",
            "reporter_phone": "13800138000",
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
        self.assertEqual(_keyword_urgency("漏电了", ""), "紧急")
        self.assertEqual(_keyword_urgency("大面积停电", ""), "紧急")
        self.assertEqual(_keyword_urgency("电梯故障了", ""), "中等")
        self.assertEqual(_keyword_urgency("玻璃碎裂了", ""), "中等")
        self.assertEqual(_keyword_urgency("灯坏了", ""), "一般")
        self.assertEqual(_keyword_urgency("轻微划痕", ""), "普通")

    def test_validate_location_dorm_no_location(self):
        from tools.action_report_issue import validate_location
        err = validate_location("楼道灯坏了", "")
        self.assertIsNotNone(err)
        self.assertIn("楼栋", err)

    def test_validate_location_dorm_with_location(self):
        from tools.action_report_issue import validate_location
        err = validate_location("楼道灯坏了", "幸福小区3号楼2单元")
        self.assertIsNone(err)

    def test_validate_location_exempt(self):
        from tools.action_report_issue import validate_location
        # 户外/公共区域（广场、花园）不强制要地点
        err = validate_location("7号楼前广场积水", "")
        self.assertIsNone(err)

    def test_classify_cache_hit(self):
        """验证 LLM 分类的缓存能用。"""
        from tools.action_report_issue import _llm_classify, _classify_cache
        _classify_cache.clear()
        # 手动塞一条缓存
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
            "description": "测试上报的描述内容",
            "urgency": "普通",
            "reporter_name": "王阿姨",
            "reporter_phone": "13800138000",
        })
        self.assertIn("#", result)
        self.assertTrue(re.search(r'#\d+', result))


# 2. get_community_pulse 社区脉搏查询

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


# 3. query_issues 工单查询

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
        # 库里没数据，应该提示查不到
        self.assertTrue("暂无" in result or "安好" in result or "没有" in result)

    def test_with_category_filter(self):
        from tools.query_community_issues import query_issues
        result = query_issues.invoke({"category": "设施维修", "status": "", "limit": 5})
        self.assertIsInstance(result, str)

    def test_with_status_filter(self):
        from tools.query_community_issues import query_issues
        result = query_issues.invoke({"category": "", "status": "待处理", "limit": 5})
        self.assertIsInstance(result, str)


# 4. get_governance_stats 治理统计

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
        # 空库应该显示"暂无"或"良好"之类的零状态
        self.assertTrue(len(result) > 10)

    def test_after_reporting_shows_data(self):
        from tools.action_report_issue import report_issue
        from tools.query_community_issues import get_governance_stats
        report_issue.invoke({
            "title": "测试统计用",
            "category": "设施维修",
            "location": "测试",
            "description": "测试统计用的描述内容",
            "urgency": "普通",
            "reporter_name": "王阿姨",
            "reporter_phone": "13800138000",
        })
        result = get_governance_stats.invoke("")
        self.assertIn("总数", result)


# 5. get_weather 天气查询

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
        self.assertIsInstance(is_real, bool)  # 真数据还是 mock 看配置

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


# 6. get_proposals 提案列表

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


# 7. create_proposal 创建提案

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
        self.assertIn("五选一", result)

    def test_valid_proposal_creation(self):
        from tools.action_create_proposal import create_proposal
        result = create_proposal.invoke({
            "title": "这是一个独特标题用于测试",
            "description": "这是一个详细的提案描述",
            "category": "公共设施",
            "is_public": True,
            "reporter_name": "王阿姨",
            "reporter_phone": "13800138000",
        })
        self.assertIn("✅", result)
        self.assertIn("P", result)

    def test_duplicate_check_keyword_overlap(self):
        from tools.action_create_proposal import _check_duplicate
        # 库里没数据，重复检查应该返回空列表
        dups = _check_duplicate("独一无二的提案标题")
        self.assertEqual(len(dups), 0)


# 8. support_proposal 附议提案

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
        result = support_proposal.invoke({"proposal_id": 99999, "score": 5})
        self.assertIn("未找到", result)


# 9. express_opinion 发表意见

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


# 10. query_knowledge 知识库检索

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


# 11. get_topics 议题列表

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
        # 库里没数据，应该返回 None
        self.assertIsNone(result)


# 12. collect_feedback 意见收集

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


# 13. 工具发现

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
