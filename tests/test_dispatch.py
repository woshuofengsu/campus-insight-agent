# -*- coding: utf-8 -*-
"""主动派单测试 — 多网格员按部门分发 + assignee_id 不串单。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data.db_core import init_db
from data.db_user import create_user


def _init_test_db(name: str) -> str:
    db_path = os.path.join(os.path.dirname(__file__), f"_test_dispatch_{name}.db")
    init_db(db_path)
    return db_path


def _cleanup(db_path: str):
    try:
        os.unlink(db_path)
    except Exception:
        pass


class TestDispatchByDepartment(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("dept")
        cls.grid_mgmt = create_user("grid_mgmt", "pw", "grid", community="测试小区", building="网格办", name="刘网格员")
        cls.grid_prop = create_user("grid_prop", "pw", "grid", community="测试小区", building="物业", name="王物业")
        cls.resident = create_user("res1", "", "resident", community="测试小区", name="居民甲")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._db_path)

    def test_facility_to_property(self):
        from data.database import report_issue
        from data.db_dispatch import auto_dispatch
        iid = report_issue("楼道灯坏了", "设施维修", reporter_id=self.resident)
        result = auto_dispatch(iid)
        self.assertEqual(result["assignee_id"], self.grid_prop)

    def test_neighbor_dispute_fallback_to_mgmt(self):
        from data.database import report_issue
        from data.db_dispatch import auto_dispatch
        iid = report_issue("邻里纠纷", "邻里矛盾", reporter_id=self.resident)
        result = auto_dispatch(iid)
        # 居委会部门没有网格员 → 退回网格办 → grid_mgmt
        self.assertEqual(result["assignee_id"], self.grid_mgmt)


class TestSameNameDispatch(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("samename")
        cls.grid_mgmt = create_user("g1", "pw", "grid", community="测试小区", building="网格办", name="刘网格员")
        cls.grid_comm = create_user("g2", "pw", "grid", community="测试小区", building="居委会", name="刘网格员")
        cls.resident = create_user("r1", "", "resident", community="测试小区", name="居民乙")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._db_path)

    def test_same_name_distinguished_by_id(self):
        from data.database import report_issue
        from data.db_dispatch import auto_dispatch
        # 噪音扰民 → 居委会 → 同名但 id 不同的 grid_comm（不是 grid_mgmt）
        iid = report_issue("广场舞扰民", "噪音扰民", reporter_id=self.resident)
        result = auto_dispatch(iid)
        self.assertEqual(result["assignee_id"], self.grid_comm)
        self.assertNotEqual(result["assignee_id"], self.grid_mgmt)


if __name__ == "__main__":
    unittest.main()
