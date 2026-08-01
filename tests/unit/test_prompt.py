# -*- coding: utf-8 -*-
"""Unit tests for persona detection and system prompt building.

Covers detect_persona() with exhaustive keyword/edge/semantic cases
and get_system_prompt() with profile injection validation.
"""
import sys
import os
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ═══════════════════════════════════════════════════════════════
# 1. detect_persona — Repair Persona (报修助手)
# ═══════════════════════════════════════════════════════════════

class TestPersonaRepair(unittest.TestCase):
    """Tests for 报修助手 persona detection."""

    def test_broken_keyword_high_confidence(self):
        from agent.prompt import detect_persona
        r = detect_persona("教三楼灯坏了漏水故障不亮了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])
        self.assertEqual(r["confidence"], "high")

    def test_single_broken_keyword(self):
        from agent.prompt import detect_persona
        r = detect_persona("水龙头漏水了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_not_working_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("空调不工作了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_no_power_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("教室没电了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_stopped_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("电梯停了不动了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_broken_window_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("窗户玻璃碎了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_v2_extended_keyword_blurry(self):
        from agent.prompt import detect_persona
        r = detect_persona("投影仪模糊看不清")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_v2_extended_keyword_too_loud(self):
        from agent.prompt import detect_persona
        r = detect_persona("教室太吵了噪音大")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_v2_extended_keyword_stuck(self):
        from agent.prompt import detect_persona
        r = detect_persona("门卡住了关不上")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_v2_toilet_keyword(self):
        from agent.prompt import detect_persona
        r = detect_persona("马桶堵了冲不了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_v2_smell_keyword(self):
        from agent.prompt import detect_persona
        r = detect_persona("厕所味大臭了")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])


# ═══════════════════════════════════════════════════════════════
# 2. detect_persona — Observer Persona (校园观察员)
# ═══════════════════════════════════════════════════════════════

class TestPersonaObserver(unittest.TestCase):

    def test_campus_pulse_direct(self):
        from agent.prompt import detect_persona
        r = detect_persona("校园脉搏")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])

    def test_whats_happening(self):
        from agent.prompt import detect_persona
        r = detect_persona("最近校园发生了什么")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])

    def test_weather_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("今天天气怎么样")
        self.assertIsNotNone(r)
        # Weather keyword matches observer persona
        self.assertIn("观察员", r["role"])

    def test_recent_dynamics(self):
        from agent.prompt import detect_persona
        r = detect_persona("最近有什么新鲜事")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])

    def test_news_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("校园最新消息")
        self.assertIsNotNone(r)
        self.assertIn("观察员", r["role"])


# ═══════════════════════════════════════════════════════════════
# 3. detect_persona — Analyst Persona (数据分析师)
# ═══════════════════════════════════════════════════════════════

class TestPersonaAnalyst(unittest.TestCase):

    def test_stats_direct(self):
        from agent.prompt import detect_persona
        r = detect_persona("统计最近报修数量")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_data_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("校园治理数据")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_count_query(self):
        from agent.prompt import detect_persona
        r = detect_persona("有多少待处理的工单")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_category_question(self):
        from agent.prompt import detect_persona
        r = detect_persona("食堂有什么问题")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_check_progress(self):
        from agent.prompt import detect_persona
        r = detect_persona("查查工单处理进度")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_report_stats_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("报修统计数据")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_category_count_overrides_repair(self):
        """'统计设施维修数量' should route to analyst, not repair."""
        from agent.prompt import detect_persona
        r = detect_persona("统计设施维修数量")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])


# ═══════════════════════════════════════════════════════════════
# 4. detect_persona — Advisor Persona (议事顾问)
# ═══════════════════════════════════════════════════════════════

class TestPersonaAdvisor(unittest.TestCase):

    def test_create_proposal_intent(self):
        from agent.prompt import detect_persona
        r = detect_persona("我想创建提案")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_suggestion_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("我觉得应该延长图书馆时间")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_price_complaint(self):
        from agent.prompt import detect_persona
        r = detect_persona("食堂涨价太贵了不合理")
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
        r = detect_persona("呼吁学校建设快递柜")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])

    def test_oppose_pattern(self):
        from agent.prompt import detect_persona
        r = detect_persona("我反对这个规定")
        self.assertIsNotNone(r)
        self.assertIn("议事顾问", r["role"])


# ═══════════════════════════════════════════════════════════════
# 5. detect_persona — Edge Cases & Boundaries
# ═══════════════════════════════════════════════════════════════

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
        r = detect_persona("d")  # len < 2
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
        """Very long inputs should still work (no truncation)."""
        from agent.prompt import detect_persona
        long_text = "教三楼" + "的灯" * 200 + "坏了"
        r = detect_persona(long_text)
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_mixed_chinese_english(self):
        from agent.prompt import detect_persona
        r = detect_persona("wifi坏了教室")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_pure_english_no_match(self):
        from agent.prompt import detect_persona
        r = detect_persona("hello world")
        self.assertIsNone(r)

    def test_short_ambiguous_low_confidence(self):
        from agent.prompt import detect_persona
        r = detect_persona("灯")
        if r is not None:
            self.assertEqual(r.get("confidence"), "low")


# ═══════════════════════════════════════════════════════════════
# 6. detect_persona — Status Query Override
# ═══════════════════════════════════════════════════════════════

class TestStatusQueryOverride(unittest.TestCase):

    def test_fixed_yet_redirects_to_analyst(self):
        """'我上报的水龙头修好了吗' should go to analyst, not repair."""
        from agent.prompt import detect_persona
        r = detect_persona("我上报的水龙头修好了吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])
        self.assertTrue(r.get("status_query_override"))

    def test_solved_yet_redirects_to_analyst(self):
        from agent.prompt import detect_persona
        r = detect_persona("教三楼的灯坏了解决了吗")
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
        """Short ownership + query combo: '我的工单' """
        from agent.prompt import detect_persona
        r = detect_persona("我的工单")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])

    def test_reply_status_check(self):
        """Status query '回复了吗' with ownership signals triggers analyst."""
        from agent.prompt import detect_persona
        r = detect_persona("我上报的工单回复了吗")
        self.assertIsNotNone(r)
        self.assertIn("数据分析师", r["role"])


# ═══════════════════════════════════════════════════════════════
# 7. detect_persona — Semantic Fallback
# ═══════════════════════════════════════════════════════════════

class TestSemanticFallback(unittest.TestCase):

    def test_regex_fallback_repair(self):
        """Input with location+problem not in keyword list — semantic regex catches it."""
        from agent.prompt import detect_persona
        # "教3楼饮水机无法出水" — "饮水机" in facility regex, "无法" in problem regex
        # but neither is in the keyword list, so it must go through semantic fallback
        r = detect_persona("教3楼饮水机无法出水")
        self.assertIsNotNone(r)
        self.assertIn("报修", r["role"])

    def test_regex_fallback_projector(self):
        from agent.prompt import detect_persona
        r = detect_persona("投影仪模糊看不清")
        # This one has keyword "看不清" + "投影仪" → direct match likely
        self.assertIsNotNone(r)

    def test_regex_fallback_suggestion(self):
        from agent.prompt import detect_persona
        r = detect_persona("能不能延长闭馆时间")
        self.assertIsNotNone(r)
        # Should match either advisor keywords or semantic fallback

    def test_no_semantic_fallback_for_irrelevant(self):
        from agent.prompt import detect_persona
        r = detect_persona("窗外阳光明媚适合读书")
        self.assertIsNone(r)


# ═══════════════════════════════════════════════════════════════
# 8. get_system_prompt — System Prompt Building
# ═══════════════════════════════════════════════════════════════

class TestSystemPrompt(unittest.TestCase):

    def test_builds_with_basic_profile(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({
            "school": "测试大学",
            "grade": "大三",
            "major": "计算机科学",
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
        prompt = get_system_prompt({"school": "测试"})
        # Should mention key tool names
        self.assertIn("report_issue", prompt)

    def test_contains_forbidden_behavior(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({"school": "测试"})
        self.assertIn("绝对不能", prompt)

    def test_contains_four_characters(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt({"school": "测试"})
        self.assertIn("知", prompt)
        self.assertIn("报", prompt)
        self.assertIn("议", prompt)
        self.assertIn("督", prompt)

    def test_injects_environment_context(self):
        from agent.prompt import get_system_prompt
        prompt = get_system_prompt(
            {"school": "测试"},
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
        # Preferences are parsed but may or may not appear in prompt depending on template
        prompt = get_system_prompt({
            "school": "测试",
            "grade": "大三",
            "major": "计算机",
            "preferences": '["篮球", "编程"]',
        })
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 2000)
        self.assertIn("测试", prompt)

    def test_handles_invalid_preferences_json(self):
        from agent.prompt import get_system_prompt
        # Invalid JSON should not crash
        prompt = get_system_prompt({
            "school": "测试",
            "preferences": "not valid json",
        })
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 1000)


# ═══════════════════════════════════════════════════════════════
# 9. Helper: _detect_status_query
# ═══════════════════════════════════════════════════════════════

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
        # Long text (>20 chars) with ownership prefix but describing a new problem → not status query
        self.assertFalse(_detect_status_query(
            "我的教三楼灯坏了需要尽快派人来维修更换灯管"))

    def test_normal_report(self):
        from agent.prompt import _detect_status_query
        self.assertFalse(_detect_status_query("教三楼灯坏了"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
