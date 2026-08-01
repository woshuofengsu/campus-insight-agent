# -*- coding: utf-8 -*-
"""Unit tests for agent helpers — extract_location, random_encouragement,
get_author_identifier, get_user_name.

Covers all location patterns, edge cases, and encouragement contexts.
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ═══════════════════════════════════════════════════════════════
# 1. extract_location — Known Buildings
# ═══════════════════════════════════════════════════════════════

class TestExtractLocationBuildings(unittest.TestCase):

    def test_jiao_building(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("教三楼灯坏了"), "教三楼")

    def test_jiao_building_chinese_number(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("教五楼电梯故障"), "教五楼")

    def test_dorm_with_room(self):
        from agent.helpers import extract_location
        result = extract_location("5号宿舍楼302空调坏了")
        self.assertIn("5号宿舍楼", result)

    def test_dorm_building_only(self):
        from agent.helpers import extract_location
        result = extract_location("3号宿舍楼停水了")
        self.assertIn("3号宿舍楼", result)

    def test_canteen_first(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("一食堂麻辣烫涨价"), "一食堂")

    def test_canteen_second(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("二食堂饭菜有问题"), "二食堂")

    def test_canteen_east(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("东食堂门口积水"), "东食堂")

    def test_library(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("图书馆自习区插座不足"), "图书馆")

    def test_playground(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("操场看台座椅锈蚀"), "操场")

    def test_lab_building(self):
        from agent.helpers import extract_location
        result = extract_location("实验楼漏水需要维修")
        self.assertIn("实验楼", result)

    def test_admin_building(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("行政楼电梯坏了"), "行政楼")

    def test_classroom(self):
        from agent.helpers import extract_location
        result = extract_location("教室投影仪坏了")
        self.assertIn("教室", result)


# ═══════════════════════════════════════════════════════════════
# 2. extract_location — Edge Cases
# ═══════════════════════════════════════════════════════════════

class TestExtractLocationEdges(unittest.TestCase):

    def test_no_location(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("今天天气不错"), "")

    def test_empty_input(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location(""), "")

    def test_short_is_location(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("教三楼"), "教三楼")

    def test_only_problem_no_location(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("灯坏了需要修"), "")

    def test_location_in_middle(self):
        from agent.helpers import extract_location
        result = extract_location("我发现图书馆的空调不制冷")
        self.assertIn("图书馆", result)

    def test_multiple_locations_returns_first(self):
        from agent.helpers import extract_location
        result = extract_location("教三楼和图书馆都漏水")
        # Should find at least one location
        self.assertTrue(len(result) > 0)

    def test_dorm_student_building(self):
        from agent.helpers import extract_location
        result = extract_location("2号学生宿舍楼网络很差")
        # May match "2号学生楼" (first pattern) or "宿舍楼" (general pattern)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_gate(self):
        from agent.helpers import extract_location
        result = extract_location("校门口道路破损")
        self.assertIn("校门口", result)

    def test_express_station(self):
        from agent.helpers import extract_location
        result = extract_location("快递站排队太长")
        self.assertIn("快递站", result)

    def test_main_road(self):
        from agent.helpers import extract_location
        result = extract_location("主干道路灯不亮")
        self.assertIn("主干道", result)


# ═══════════════════════════════════════════════════════════════
# 3. random_encouragement — All Contexts
# ═══════════════════════════════════════════════════════════════

class TestRandomEncouragement(unittest.TestCase):

    def test_pulse_context(self):
        from agent.helpers import random_encouragement
        for _ in range(10):
            result = random_encouragement("pulse")
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 5)

    def test_stats_context(self):
        from agent.helpers import random_encouragement
        for _ in range(10):
            result = random_encouragement("stats")
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 5)

    def test_report_context(self):
        from agent.helpers import random_encouragement
        for _ in range(10):
            result = random_encouragement("report")
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 5)

    def test_proposal_context(self):
        from agent.helpers import random_encouragement
        for _ in range(10):
            result = random_encouragement("proposal")
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 5)

    def test_empty_context_fallback(self):
        from agent.helpers import random_encouragement
        for _ in range(10):
            result = random_encouragement("")
            self.assertIsInstance(result, str)
            self.assertTrue(len(result) > 5)

    def test_unknown_context_fallback(self):
        from agent.helpers import random_encouragement
        result = random_encouragement("nonexistent_context")
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 5)

    def test_returns_different_values(self):
        """random_encouragement should return variety (not always the same)."""
        from agent.helpers import random_encouragement
        results = {random_encouragement("pulse") for _ in range(30)}
        # Should have at least 2 unique results (pool has 3 for pulse)
        self.assertGreaterEqual(len(results), 2)


# ═══════════════════════════════════════════════════════════════
# 4. get_author_identifier — delegates to _resolve_author
# ═══════════════════════════════════════════════════════════════

class TestGetAuthorIdentifier(unittest.TestCase):

    def test_returns_student_id_first(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "student_id": "2024001", "name": "张三",
                "school": "测试大学", "grade": "大三",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "2024001")

    def test_falls_back_to_school_grade(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "student_id": "", "school": "测试大学", "grade": "大三",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "测试大学大三")

    def test_falls_back_to_school_only(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "student_id": "", "school": "测试大学", "grade": "",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "测试大学")

    def test_falls_back_to_name(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "student_id": "", "school": "", "grade": "", "name": "李四",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "李四")

    def test_falls_back_to_user_id(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "student_id": "", "school": "", "grade": "", "name": "", "id": 42,
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "user_42")

    def test_profile_exception_graceful(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.side_effect = Exception("DB error")
            # Should not raise; _resolve_author catches and returns "匿名"
            # which get_author_identifier maps to None
            result = get_author_identifier(MagicMock())
            self.assertIsNone(result)


# ═══════════════════════════════════════════════════════════════
# 5. get_user_name
# ═══════════════════════════════════════════════════════════════

class TestGetUserName(unittest.TestCase):

    def test_returns_name(self):
        from agent.helpers import get_user_name
        mock_memory = MagicMock()
        mock_memory.get_user_profile.return_value = {
            "name": "王五",
            "student_id": "2024002",
        }
        result = get_user_name(mock_memory)
        self.assertEqual(result, "王五")

    def test_falls_back_to_student_id(self):
        from agent.helpers import get_user_name
        mock_memory = MagicMock()
        mock_memory.get_user_profile.return_value = {
            "name": "",
            "student_id": "2024003",
        }
        result = get_user_name(mock_memory)
        self.assertEqual(result, "2024003")

    def test_empty_profile(self):
        from agent.helpers import get_user_name
        mock_memory = MagicMock()
        mock_memory.get_user_profile.return_value = {}
        result = get_user_name(mock_memory)
        self.assertEqual(result, "")

    def test_profile_exception_graceful(self):
        from agent.helpers import get_user_name
        mock_memory = MagicMock()
        mock_memory.get_user_profile.side_effect = Exception("DB error")
        result = get_user_name(mock_memory)
        self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
