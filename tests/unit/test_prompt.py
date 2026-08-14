# -*- coding: utf-8 -*-
"""角色识别和系统提示词构建的单元测试。

detect_persona() 覆盖关键词、边界、语义的穷举用例，
get_system_prompt() 验证画像注入是否正常。
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# 1. detect_persona 报修角色（接诉助手）

class TestPersonaRepair(unittest.TestCase):
    """接诉助手角色的识别测试。"""

    def test_broken_keyword_high_confidence(self):
        from agent.prompt import detect_persona
        r = detect_persona("3号楼灯坏了漏水故障不亮了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])
        self.assertEqual(r["confidence"], "high")

    def test_single_broken_keyword(self):
        from agent.prompt import detect_persona
        r = detect_persona("水龙头漏水了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_not_working_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("空调不工作了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_no_power_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("楼道没电了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_stopped_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("电梯停了不动了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_broken_window_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("窗户玻璃碎了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_v2_extended_keyword_blurry(self):
        from agent.prompt import detect_persona
        r = detect_persona("路灯模糊看不清")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_v2_extended_keyword_too_loud(self):
        from agent.prompt import detect_persona
        r = detect_persona("楼道太吵了噪音大")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_v2_extended_keyword_stuck(self):
        from agent.prompt import detect_persona
        r = detect_persona("门卡住了关不上")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_v2_toilet_keyword(self):
        from agent.prompt import detect_persona
        r = detect_persona("马桶堵了冲不了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_v2_smell_keyword(self):
        from agent.prompt import detect_persona
        r = detect_persona("楼道味大臭了")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])


# 2. detect_persona 观察角色（社区观察员）

class TestPersonaObserver(unittest.TestCase):

    def test_community_pulse_direct(self):
        from agent.prompt import detect_persona
        r = detect_persona("社区脉搏")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])

    def test_whats_happening(self):
        from agent.prompt import detect_persona
        r = detect_persona("最近社区发生了什么")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])

    def test_weather_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("今天天气怎么样")
        self.assertIsNotNone(r)
        # 天气关键词也归观察员
        self.assertIn("观察员", r["role"])

    def test_recent_dynamics(self):
        from agent.prompt import detect_persona
        r = detect_persona("最近有什么新鲜事")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])

    def test_news_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("社区最新消息")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])


# 3. detect_persona 分析角色（数据分析师）

class TestPersonaAnalyst(unittest.TestCase):

    def test_stats_direct(self):
        from agent.prompt import detect_persona
        r = detect_persona("统计最近报修数量")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_data_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("社区治理数据")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_count_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("有多少待处理的工单")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_category_question(self):
        from agent.prompt import detect_persona
        r = detect_persona("停车有什么问题")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_check_progress(self):
        from agent.prompt import detect_persona
        r = detect_persona("查查工单处理进度")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_report_stats_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("工单统计数据")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_category_count_overrides_repair(self):
        """'统计设施维修数量' 应该归分析师，不是报修。"""
        from agent.prompt import detect_persona
        r = detect_persona("统计设施维修数量")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])


# 4. detect_persona 顾问角色（议事顾问）

class TestPersonaAdvisor(unittest.TestCase):

    def test_create_proposal_intent(self):
        from agent.prompt import detect_persona
        r = detect_persona("我想创建提案")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_suggestion_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("我觉得应该延长活动室时间")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_price_complaint(self):
        from agent.prompt import detect_persona
        r = detect_persona("物业费涨价太贵了不合理")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_opinion_question(self):
        from agent.prompt import detect_persona
        r = detect_persona("你觉得这个想法怎么样")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_view_proposals_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("看看大家提了什么好建议")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_v2_appeal_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("呼吁降低物业费")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_oppose_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("我反对这个规定")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])


# 5. detect_persona 边界情况

class TestPersonaEdgeCases(unittest.TestCase):

    def test_empty_input(self):
        from agent.prompt import detect_persona
        r = detect_persona("")
        self.assertIsNone(r)

    def test_none_input(self):
        from agent.prompt import detect_persona
        r = detect_persona(None)
        self.assertIsNone(r)

    def test_single_char(self):
        from agent.prompt import detect_persona
        r = detect_persona("d")  # 长度小于 2
        self.assertIsNone(r)

    def test_greeting_no_match(self):
        from agent.prompt import detect_persona
        r = detect_persona("你好")
        self.assertIsNone(r)

    def test_thanks_no_match(self):
        from agent.prompt import detect_persona
        r = detect_persona("谢谢")
        self.assertIsNone(r)

    def test_very_long_input(self):
        """超长输入也要能正常识别（不做截断）。"""
        from agent.prompt import detect_persona
        long_text = "3号楼" + "的灯" * 200 + "坏了"
        r = detect_persona(long_text)
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_mixed_chinese_english(self):
        from agent.prompt import detect_persona
        r = detect_persona("wifi坏了楼道")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_pure_english_no_match(self):
        from agent.prompt import detect_persona
        r = detect_persona("hello world")
        self.assertIsNone(r)

    def test_short_ambiguous_low_confidence(self):
        from agent.prompt import detect_persona
        r = detect_persona("灯")
        if r is not None:
            self.assertEqual(r.get("confidence"), "low")


# 6. detect_persona 状态查询覆盖

class TestStatusQueryOverride(unittest.TestCase):

    def test_fixed_yet_redirects_to_analyst(self):
        """'我上报的水龙头修好了吗' 应该走分析师，不是报修。"""
        from agent.prompt import detect_persona
        r = detect_persona("我上报的水龙头修好了吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])
        self.assertTrue(r.get("status_query_override"))

    def test_solved_yet_redirects_to_analyst(self):
        from agent.prompt import detect_persona
        r = detect_persona("3号楼的灯坏了解决了吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_progress_check_redirects(self):
        from agent.prompt import detect_persona
        r = detect_persona("我的工单有进展吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_my_item_status_check(self):
        from agent.prompt import detect_persona
        r = detect_persona("我之前上报的处理了吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_short_ownership_check(self):
        """短的所有权+查询组合：'我的工单' """
        from agent.prompt import detect_persona
        r = detect_persona("我的工单")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_reply_status_check(self):
        """'回复了吗' 这种状态查询加上所有权信号就归分析师。"""
        from agent.prompt import detect_persona
        r = detect_persona("我上报的工单回复了吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])


# 7. detect_persona 语义兜底

class TestSemanticFallback(unittest.TestCase):

    def test_regex_fallback_repair(self):
        """带地点+问题但关键词表里没有 — 语义正则要能接住。"""
        from agent.prompt import detect_persona
        # "饮水机"在设施正则里、"无法"在问题正则里，
        # 但都不在关键词表里，所以必须走语义兜底
        r = detect_persona("饮水机突然无法出水")
        self.assertIsNotNone(r)
        self.assertIn("接诉", r["role"])

    def test_regex_fallback_projector(self):
        from agent.prompt import detect_persona
        r = detect_persona("路灯模糊看不清")
        # 这条有"看不清"+"路灯"关键词，应该直接命中
        self.assertIsNotNone(r)

    def test_regex_fallback_suggestion(self):
        from agent.prompt import detect_persona
        r = detect_persona("能不能延长闭馆时间")
        self.assertIsNotNone(r)
        # 要么命中顾问关键词，要么走语义兜底，总得有结果

    def test_no_semantic_fallback_for_irrelevant(self):
        from agent.prompt import detect_persona
        r = detect_persona("窗外阳光明媚适合读书")
        self.assertIsNone(r)


# 8. get_system_prompt 系统提示词构建

class TestSystemPrompt(unittest.TestCase):

    def test_builds_with_basic_profile(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({
            "community": "测试大学",
            "building": "大三",
            "unit": "计算机科学",
        })
        self.assertIsInstance(prompt, str)
        self.assertIn("测试大学", prompt)
        self.assertIn("大三", prompt)
        self.assertIn("计算机科学", prompt)

    def test_builds_minimal_length(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({})
        self.assertGreater(len(prompt), 2000)

    def test_contains_tool_names(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({"community": "测试"})
        # 提示词里应该提到关键工具名
        self.assertIn("report_issue", prompt)

    def test_contains_forbidden_behavior(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({"community": "测试"})
        self.assertIn("绝对不能", prompt)

    def test_contains_four_characters(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({"community": "测试"})
        self.assertIn("知", prompt)
        self.assertIn("报", prompt)
        self.assertIn("议", prompt)
        self.assertIn("督", prompt)

    def test_injects_environment_context(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt(
            {"community": "测试"},
            environment_context="⚠️ 当前有3条紧急告警",
        )
        self.assertIn("紧急告警", prompt)
        self.assertIn("实时环境感知", prompt)

    def test_handles_empty_profile(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({})
        self.assertIn("未设置", prompt)

    def test_handles_preferences_json(self):
        from agent.prompt import get_system_prompt
        # 画像会解析，但进不进提示词要看模板怎么拼
        prompt = get_system_prompt({
            "community": "测试",
            "building": "大三",
            "unit": "计算机",
            "preferences": '["篮球", "编程"]',
        })
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 2000)
        self.assertIn("测试", prompt)

    def test_handles_invalid_preferences_json(self):
        from agent.prompt import get_system_prompt
        # 非法 JSON 不能崩
        prompt = get_system_prompt({
            "community": "测试",
            "preferences": "not valid json",
        })
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 1000)


# 9. 辅助函数 _detect_status_query

class TestDetectStatusQuery(unittest.TestCase):

    def test_fixed_yet(self):
        from agent.prompt import _detect_status_query
        self.assertTrue(_detect_status_query("修好了吗"))

    def test_solved_yet(self):
        from agent.prompt import _detect_status_query
        self.assertTrue(_detect_status_query("解决了吗"))

    def test_progress_check(self):
        from agent.prompt import _detect_status_query
        self.assertTrue(_detect_status_query("有进展吗"))

    def test_short_ownership(self):
        from agent.prompt import _detect_status_query
        self.assertTrue(_detect_status_query("我的工单"))

    def test_long_ownership_not_alone(self):
        from agent.prompt import _detect_status_query
        # 文本很长（>20字）但带所有权前缀、描述的是新问题 → 不算状态查询
        self.assertFalse(_detect_status_query(
            "我的教三楼灯坏了需要尽快派人来维修更换灯管"))

    def test_normal_report(self):
        from agent.prompt import _detect_status_query
        self.assertFalse(_detect_status_query("教三楼灯坏了"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
