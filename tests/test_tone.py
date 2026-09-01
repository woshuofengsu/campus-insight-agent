# -*- coding: utf-8 -*-
"""M1：关怀内核（agent/tone.py）纯函数测试。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import tone  # noqa: E402


def test_greeting_buckets():
    assert tone.greeting(3) == "夜深了，还没休息呀，注意身体"
    assert tone.greeting(8) == "早上好"
    assert tone.greeting(12) == "中午好，记得吃饭"
    assert tone.greeting(15) == "下午好"
    assert tone.greeting(21) == "晚上好"


def test_detect_emotion_hit_and_miss():
    tag, comfort = tone.detect_emotion("家里漏了一地水，急死了")
    assert tag == "着急" and comfort
    tag2, c2 = tone.detect_emotion("我今天散步去了")
    assert tag2 is None and c2 == ""


def test_pick_dedup():
    used = set()
    picked = []
    for _ in range(4):
        picked.append(tone.pick("repair_ok", used))
    # 语料池 3 句，第 4 次应因 used 用尽而回退到已有（不抛错）
    assert len(picked) == 4
    assert all(p for p in picked)


def test_human_status():
    assert tone.human_status("处理中") == "师傅已经在处理啦，您在家等就好"
    assert tone.human_status("未知态") == "未知态"


def test_care_line_priority():
    # 天气预警最高
    assert tone.care_line(weather={"alert_tags": [{"type": "暴雨"}], "temp": 30}) == \
        "今天天气不太好，尽量少出门，出门一定慢一点"
    # 高温其次
    assert tone.care_line(weather={"alert_tags": [], "temp": 36}) == \
        "今天高温，多喝水、避开正午出门"
    # 用药
    assert tone.care_line(due_meds=2) == "今天有 2 次药要吃，我会到点提醒您"
    # 久未活跃
    assert tone.care_line(days_inactive=6) == "好几天没见您啦，一切都好吧？有事随时长按找我"
    # 都不满足 → 空
    assert tone.care_line() == ""
