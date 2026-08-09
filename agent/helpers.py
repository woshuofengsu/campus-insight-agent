# agent/helpers.py
"""Shared helpers used by both CampusAgent (LLM-driven) and OfflineAgent (rule-driven).

Extracted to eliminate duplication across the two agent implementations.
"""
import logging
import random
import re

_log = logging.getLogger(__name__)


def get_author_identifier(memory) -> str | None:
    """Resolve the current user's author identifier. Returns None if anonymous."""
    from data.db_governance import _resolve_author
    author = _resolve_author("")
    return author if author != "匿名" else None


def get_user_name(memory) -> str:
    """Get the user's display name from their profile."""
    try:
        profile = memory.get_user_profile()
        return profile.get("name", "") or profile.get("student_id", "") or ""
    except Exception:  # ok to fail
        _log.debug("Failed to get user name from profile", exc_info=True)
        return ""


def extract_location(text: str) -> str:
    """Extract a clean campus location from user input text.

    Matches known campus location names (buildings, facilities) and returns
    just the location portion — problem descriptions like "灯坏了" are excluded.
    """
    # ── Known location patterns (ordered by specificity, longest first) ──
    _LOCATION_PATTERNS = [
        # Specific buildings with numbers: "教三楼", "5号宿舍楼302", "一食堂"
        r'(?:教[一二三四五六七八九\d]+楼|[一二三四五六七八九\d]+号(?:宿舍|学生)?楼\d*)',
        # Specific canteens
        r'[一二三四五六七八九东西南北中]食堂',
        # General facility names (longer patterns first for greedy match)
        r'(?:教学楼|图书馆|宿舍楼|食堂|操场|实验楼|行政楼|校门口?|主干道|快递站'
        r'|多媒体|机房|实验室|自习室|宿舍|教室'
        r')',
    ]
    _LOCATION_RE = re.compile(
        r'(?:' + r'|'.join(_LOCATION_PATTERNS) + r')'
        r'(?:[一-鿿\d]{0,6}(?:楼|[层Ff]|层))?'  # optional floor/room suffix
    )

    match = _LOCATION_RE.search(text)
    if match:
        loc = match.group(0)
        # Trim trailing punctuation and whitespace
        loc = re.sub(r'[。，,、！!？?\s]+$', '', loc).strip()
        # Avoid returning the entire input as location (unless input is very short)
        if len(loc) < len(text) * 0.85 or len(text) <= 6:
            return loc
        # For short inputs, the entire text IS the location — keep it
        if len(text) <= 12:
            return loc

    return ""


# ── Encouragement phrases ──

_ENCOURAGEMENT_POOL: dict[str, list[str]] = {
    "pulse": [
        "💡 *试试点击上方「📊 治理透明窗」查看更详细的数据看板~*",
        "💡 *想深入了解某类问题？直接告诉我，比如「设施维修类有哪些」*",
        "💡 *发现校园问题？直接描述，我帮你秒速上报~*",
    ],
    "stats": [
        "💡 *想查看具体某类问题？输入「设施维修有哪些」试试~*",
        "💡 *需要导出报告？在「📊 治理透明窗」页面可以查看图表*",
        "💡 *数据每小时更新，随时回来看最新进展~*",
    ],
    "report": [
        "🌟 你的每一次上报，都在让校园变得更好！",
        "🙌 感谢你的参与！校园治理需要每一个人的力量~",
        "✨ 一个问题的发现，就是校园改善的开始~",
    ],
    "proposal": [
        "🙌 每一个提案都是校园进步的阶梯~",
        "💪 好的想法值得被更多人看到，继续加油！",
        "🗳️ 校园的每一点改变，都源于像你一样愿意发声的人~",
    ],
}


def random_encouragement(context: str = "") -> str:
    """Return a random encouragement phrase for the given context.

    Shared by both agents to keep response tone consistent.
    """
    options = _ENCOURAGEMENT_POOL.get(context, [
        "💡 *还有其他想了解的吗？*",
        "💡 *随时问我任何校园相关问题~*",
    ])
    return random.choice(options)
