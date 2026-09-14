# -*- coding: utf-8 -*-
"""主动派单测试 — 多网格员按部门分发 + assignee_id 不串单。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data.db_core import init_db
from data.db_user import create_user

# 全局 DB 路径的"上一个值"：本文件会 init_db(临时库) 并在 teardown 删库，
# **必须把全局还原**，否则后续测试文件里的 get_db() 会打到"已删除的路径"上
# （sqlite 会新建一个空库 → `no such table: user_profile`）。
# 实测：`pytest tests/test_agent.py tests/test_dispatch.py tests/test_api_web.py` 三连跑必现，
# 而两两组合/单跑都过 —— 典型的"跑子集出假失败"陷阱。
_orig_db_path: str | None = None


def _init_test_db(name: str) -> str:
    """建测试库：**先清残留**（db + -wal + -shm），保证重复运行/中断后可重入。

    踩坑记录：原先只 `init_db()` 不清理，残留库会让 `create_user` 抛
    `Username 'grid_mgmt' already taken` → 单独跑通过、全量跑 error 的偶发失败。
    """
    global _orig_db_path
    import config
    from data import db_core
    if _orig_db_path is None:
        _orig_db_path = db_core._DB_PATH or config.DB_PATH
    db_path = os.path.join(os.path.dirname(__file__), f"_test_dispatch_{name}.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + suffix)
        except OSError:
            pass
    init_db(db_path)
    return db_path


def _cleanup(db_path: str, retries: int = 5):
    """清理临时库（含 -wal/-shm），并把全局 DB 路径**还原**回进入本文件前的值。"""
    import time

    for suffix in ("", "-wal", "-shm"):
        for i in range(retries):
            try:
                os.unlink(db_path + suffix)
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.2 * (i + 1))
    global _orig_db_path
    if _orig_db_path:
        import config
        from data import db_core
        db_core._DB_PATH = _orig_db_path
        config.DB_PATH = _orig_db_path


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
