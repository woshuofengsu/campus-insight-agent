# -*- coding: utf-8 -*-
"""agent.helpers 单元测试 — extract_location、random_encouragement、
get_author_identifier、get_user_name。

覆盖各种地点写法、边界情况和鼓励话术的各个场景。
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# 1. extract_location 已知地点

class TestExtractLocationBuildings(unittest.TestCase):

    def test_jiao_building(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("3号楼灯坏了"), "3号楼")

    def test_jiao_building_chinese_number(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("五号楼电梯故障"), "五号楼")

    def test_dorm_with_room(self):
        from agent.helpers import extract_location
        result = extract_location("5号楼302空调坏了")
        self.assertIn("5号楼", result)

    def test_dorm_building_only(self):
        from agent.helpers import extract_location
        result = extract_location("3号楼停水了")
        self.assertIn("3号楼", result)

    def test_canteen_first(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("助餐点麻辣烫涨价"), "助餐点")

    def test_canteen_second(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("助餐点饭菜有问题"), "助餐点")

    def test_canteen_east(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("助餐点门口积水"), "助餐点")

    def test_library(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("活动室自习区插座不足"), "活动室")

    def test_playground(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("广场看台座椅锈蚀"), "广场")

    def test_lab_building(self):
        from agent.helpers import extract_location
        result = extract_location("3号楼漏水需要维修")
        self.assertIn("3号楼", result)

    def test_admin_building(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("4号楼电梯坏了"), "4号楼")

    def test_classroom(self):
        from agent.helpers import extract_location
        result = extract_location("楼道投影仪坏了")
        self.assertIn("楼道", result)


# 2. extract_location 边界情况

class TestExtractLocationEdges(unittest.TestCase):

    def test_no_location(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("今天天气不错"), "")

    def test_empty_input(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location(""), "")

    def test_short_is_location(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("3号楼"), "3号楼")

    def test_only_problem_no_location(self):
        from agent.helpers import extract_location
        self.assertEqual(extract_location("灯坏了需要修"), "")

    def test_location_in_middle(self):
        from agent.helpers import extract_location
        result = extract_location("我发现活动室的空调不制冷")
        self.assertIn("活动室", result)

    def test_multiple_locations_returns_first(self):
        from agent.helpers import extract_location
        result = extract_location("3号楼和活动室都漏水")
        # 至少要能找出一个地点
        self.assertTrue(len(result) > 0)

    def test_dorm_resident_building(self):
        from agent.helpers import extract_location
        result = extract_location("2号楼网络很差")
        # 命中"2号楼"的楼栋模式
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_gate(self):
        from agent.helpers import extract_location
        result = extract_location("小区门口道路破损")
        self.assertIn("小区", result)

    def test_express_station(self):
        from agent.helpers import extract_location
        result = extract_location("快递柜排队太长")
        self.assertIn("快递柜", result)

    def test_main_road(self):
        from agent.helpers import extract_location
        result = extract_location("小区主干道路灯不亮")
        self.assertIn("小区", result)


# 3. random_encouragement 各场景

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
        """鼓励话术应该有变化，不能老返回同一句。"""
        from agent.helpers import random_encouragement
        results = {random_encouragement("pulse") for _ in range(30)}
        # 至少要有 2 种不同结果（pulse 的话术池里有 3 句）
        self.assertGreaterEqual(len(results), 2)


# 4. get_author_identifier 委托给 _resolve_author

class TestGetAuthorIdentifier(unittest.TestCase):

    def test_returns_resident_id_first(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "resident_id": "2024001", "name": "张三",
                "community": "测试大学", "building": "大三",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "2024001")

    def test_falls_back_to_community_building(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "resident_id": "", "community": "测试大学", "building": "大三",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "测试大学大三")

    def test_falls_back_to_community_only(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "resident_id": "", "community": "测试大学", "building": "",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "测试大学")

    def test_falls_back_to_name(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "resident_id": "", "community": "", "building": "", "name": "李四",
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "李四")

    def test_falls_back_to_user_id(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.return_value = {
                "resident_id": "", "community": "", "building": "", "name": "", "id": 42,
            }
            result = get_author_identifier(MagicMock())
            self.assertEqual(result, "user_42")

    def test_profile_exception_graceful(self):
        from agent.helpers import get_author_identifier
        with patch("data.db_user.get_current_user") as mock_user:
            mock_user.side_effect = Exception("DB error")
            # 不该抛异常；_resolve_author 内部接住并返回"匿名"
            # get_author_identifier 再把它映射成 None
            result = get_author_identifier(MagicMock())
            self.assertIsNone(result)


# 5. get_user_name

class TestGetUserName(unittest.TestCase):

    def test_returns_name(self):
        from agent.helpers import get_user_name
        mock_memory = MagicMock()
        mock_memory.get_user_profile.return_value = {
            "name": "王五",
            "resident_id": "2024002",
        }
        result = get_user_name(mock_memory)
        self.assertEqual(result, "王五")

    def test_falls_back_to_resident_id(self):
        from agent.helpers import get_user_name
        mock_memory = MagicMock()
        mock_memory.get_user_profile.return_value = {
            "name": "",
            "resident_id": "2024003",
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
