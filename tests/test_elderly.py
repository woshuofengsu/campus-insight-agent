# -*- coding: utf-8 -*-
"""老年关怀版测试 — 档案 CRUD / 用药触发 / 平安打卡 / SOS 闭环。"""
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from data.db_core import init_db
from data.db_user import create_user


def _init_test_db(name: str) -> str:
    db_path = os.path.join(os.path.dirname(__file__), f"_test_elderly_{name}.db")
    init_db(db_path)
    return db_path


def _cleanup(db_path: str):
    try:
        os.unlink(db_path)
    except Exception:
        pass


class TestElderlyProfile(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("profile")
        cls.uid = create_user("elder1", "", "elderly", community="海淀小区", name="张大爷")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._db_path)

    def test_profile_crud(self):
        from data.db_elderly import get_profile, set_health_info, set_medication_reminders, set_emergency_contact
        set_health_info(self.uid, {"chronic": ["高血压"], "blood_type": "A型"})
        set_medication_reminders(self.uid, [{"name": "降压药", "dosage": "1片", "times": ["08:00"]}])
        set_emergency_contact(self.uid, [{"name": "张小明", "relation": "儿子", "phone": "139"}])
        p = get_profile(self.uid)
        self.assertEqual(p["health_info"]["chronic"], ["高血压"])
        self.assertEqual(p["medication_reminders"][0]["name"], "降压药")
        self.assertEqual(p["emergency_contact"][0]["relation"], "儿子")

    def test_due_reminders_window(self):
        from data.db_elderly import set_medication_reminders, due_reminders
        set_medication_reminders(self.uid, [{"name": "降压药", "dosage": "1片", "times": ["08:00"]}])
        due = due_reminders(self.uid, datetime(2026, 8, 13, 8, 10, 0))  # 8:10 在 ±30min 内
        self.assertTrue(any(d["name"] == "降压药" for d in due))
        due2 = due_reminders(self.uid, datetime(2026, 8, 13, 12, 0, 0))  # 12:00 不在窗口
        self.assertFalse(any(d["name"] == "降压药" for d in due2))


class TestElderlySafety(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("safety")
        cls.uid = create_user("elder2", "", "elderly", community="海淀小区", name="李大爷")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._db_path)

    def test_touch_active_clears_inactive(self):
        from data.db_elderly import touch_active, get_inactive_elders
        touch_active(self.uid)
        inactive = get_inactive_elders(24)
        self.assertFalse(any(e["user_id"] == self.uid for e in inactive))

    def test_sos_flow(self):
        from data.db_elderly import sos_request, get_pending_sos, mark_sos_done
        sid = sos_request(self.uid)
        pending = get_pending_sos()
        self.assertTrue(any(s["id"] == sid for s in pending))
        mark_sos_done(sid)
        pending2 = get_pending_sos()
        self.assertFalse(any(s["id"] == sid for s in pending2))


if __name__ == "__main__":
    unittest.main()
