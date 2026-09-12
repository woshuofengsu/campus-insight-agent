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
    """建测试库；**先清理同名残留**，保证重复运行/中断后可重入（幂等）。"""
    db_path = os.path.join(os.path.dirname(__file__), f"_test_elderly_{name}.db")
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + suffix)
        except OSError:
            pass
    init_db(db_path)
    return db_path


def _cleanup(db_path: str):
    for suffix in ("", "-wal", "-shm"):
        try:
            os.unlink(db_path + suffix)
        except OSError:
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


class TestElderlyWeatherPayload(unittest.TestCase):
    """老年端简化天气的**键名契约**（外部评审 B1 回归）。

    B1 现象：老年端首页显示 "晴 17°~°"、语音播报漏最高温。
    根因：`get_simplified_weather()` 只返回 `temp`/`temp_low`，而前端模板与语音播报都读 `temp_high`
    → 取不到就渲染成空串。结构类检查（溢出/对比度）天然查不出这种「接口字段对不上」的 bug，
    所以这里把键名契约钉死：temp_high 与 temp_low 必须同时存在且非空。
    """

    @classmethod
    def setUpClass(cls):
        cls._db_path = _init_test_db("weather")

    @classmethod
    def tearDownClass(cls):
        _cleanup(cls._db_path)

    def test_simplified_weather_has_both_temp_keys(self):
        from data.db_weather import get_simplified_weather
        w = get_simplified_weather("海淀小区")
        self.assertIn("temp_high", w, "缺 temp_high → 老年端会渲染成 '17°~°'")
        self.assertIn("temp_low", w, "缺 temp_low → 老年端会渲染成 '°~27°'")
        self.assertIsNotNone(w["temp_high"], "temp_high 不能为 None（前端会渲染成空）")
        self.assertIsNotNone(w["temp_low"], "temp_low 不能为 None（前端会渲染成空）")
        # 兼容旧引用：temp 仍等于最高温
        self.assertEqual(w["temp"], w["temp_high"])

    def test_elderly_home_weather_has_no_residue(self):
        """端到端：老年端首页接口返回的天气字段能拼出完整温度串（不出现 '°~°'）。"""
        from data.db_weather import get_simplified_weather
        w = get_simplified_weather("海淀小区")
        shown = f"{w['temp_low']}°~{w['temp_high']}°"
        self.assertNotIn("°~°", shown, f"渲染残缺：{shown}")
        self.assertNotIn("None", shown, f"渲染残缺：{shown}")
        # 数值可比较（最高温 ≥ 最低温）
        self.assertGreaterEqual(int(w["temp_high"]), int(w["temp_low"]))


if __name__ == "__main__":
    unittest.main()
