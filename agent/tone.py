# agent/tone.py
"""关怀内核（人情味优化 M1）：纯函数、零 IO、零 LLM。

单事实源：后端所有"暖心话"只在此 + 前端 web/src/utils/warm.js 镜像；禁止散落到各路由/组件。
规则驱动，稳定可测，与项目"规则为骨、LLM 为脑、LLM 默认关"一致。
"""
import random
from datetime import datetime

# 场景语料池（每类 3 句，随机轮换；pick 用 used 集合做会话级去重，避免复读机）
LINES: dict[str, list[str]] = {
    "repair_ok": ["收到啦，您别着急，我这就帮您安排人。",
                  "好的，已经记下了，马上帮您派师傅，您在家等消息就行。",
                  "您放心，单子我接住了，这就走流程。"],
    "wait": ["正在帮您处理，您稍坐一会儿。", "我盯着进度呢，有进展第一时间告诉您。"],
    "fail": ["刚刚没太听清，您慢慢再说一遍，不着急。",
             "这一步没成功，不是您的问题，我们再来一次。"],
    "sos": ["别慌，我们已经在联系了，您先找个安全的地方坐下。"],
    "done": ["已经帮您处理好啦，您看看还有没有问题？", "搞定！后续有任何情况随时找我。"],
}

# 情绪词 → 先安抚一句（规则命中即可，不调 LLM）；有序匹配，返回 (tag, comfort)
EMOTION: dict[str, tuple[tuple[str, ...], str]] = {
    "疼痛": (("疼", "痛", "摔", "磕", "出血", "扭了"), "您先别乱动，我优先帮您处理。"),
    "着急": (("急", "快点", "来不及", "漏了一地", "冒水", "泡"), "听着挺让人着急的，我给您加急。"),
    "害怕": (("怕", "害怕", "一个人", "不敢"), "您别担心，我在呢，这就帮您联系人。"),
    "抱怨": (("怎么还", "投诉", "没人管", "太慢"), "让您久等了，我这就帮您查清楚。"),
}

# 工单状态 → 一句人话
HUMAN_STATUS: dict[str, str] = {
    "待审核": "您的上报我们收到了，正在核对",
    "待派单": "已核对通过，正在为您安排负责人",
    "处理中": "师傅已经在处理啦，您在家等就好",
    "待反馈": "处理完了，就等您确认结果",
    "已完成": "这件事已经办结",
    "已驳回": "这条需要再补充点信息，不是不给您办",
}


def pick(scene: str, used: set[str] | None = None) -> str:
    """从场景语料池选一句，尽量不与 used 里重复（会话级去重）；无可用则返回空串。"""
    pool = LINES.get(scene) or []
    if used is not None:
        remaining = [s for s in pool if s not in used]
        if remaining:
            pool = remaining
        else:
            pool = [s for s in pool] or [""]
    if not pool:
        return ""
    s = random.choice(pool)
    if used is not None:
        used.add(s)
    return s


def detect_emotion(text: str) -> tuple[str | None, str]:
    """返回 (情绪tag, 安抚句)；未命中返回 (None, '')。按 EMOTION 顺序首个命中。"""
    for tag, (words, comfort) in EMOTION.items():
        if any(w in text for w in words):
            return tag, comfort
    return None, ""


def greeting(hour: int | None = None) -> str:
    """分时段问候。"""
    if hour is None:
        hour = datetime.now().hour
    if hour < 6:
        return "夜深了，还没休息呀，注意身体"
    if hour < 11:
        return "早上好"
    if hour < 13:
        return "中午好，记得吃饭"
    if hour < 18:
        return "下午好"
    return "晚上好"


def care_line(*, weather: dict | None = None, due_meds: int = 0, days_inactive: int = 0) -> str:
    """首页"今日一句关怀"：按 天气 > 用药 > 久未出现 优先级取一条；宁可不弹也不堆。

    weather: get_simplified_weather 返回体（含 alert_tags 列表、temp 高温、condition）。
    """
    if weather and weather.get("alert_tags"):
        return "今天天气不太好，尽量少出门，出门一定慢一点"
    if weather and isinstance(weather.get("temp"), (int, float)) and weather["temp"] >= 35:
        return "今天高温，多喝水、避开正午出门"
    if due_meds:
        return f"今天有 {due_meds} 次药要吃，我会到点提醒您"
    if days_inactive >= 5:
        return "好几天没见您啦，一切都好吧？有事随时长按找我"
    return ""


def human_status(status: str) -> str:
    return HUMAN_STATUS.get(status, status or "")
