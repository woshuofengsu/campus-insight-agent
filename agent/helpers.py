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
        "查看「📊 治理透明窗」获取更详细的数据。",
        "深入了解某类问题？输入「设施维修类有哪些」。",
        "发现校园问题？直接描述即可上报。",
    ],
    "stats": [
        "查看某类问题？输入「设施维修有哪些」。",
        "需要图表？在「📊 治理透明窗」页面查看。",
        "数据每小时更新一次。",
    ],
    "report": [
        "已上报。输入「查看我的工单」追踪进度。",
        "已记录。输入「查看我的工单」追踪。",
        "已上报。维修人员会尽快处理。",
    ],
    "proposal": [
        "提案已创建。附议越多越容易被校方关注。",
        "分享给同学，让更多人附议你的提案。",
        "提案已提交。查看「有话说」页面关注进展。",
    ],
}


def random_encouragement(context: str = "") -> str:
    """Return a random encouragement phrase for the given context.

    Shared by both agents to keep response tone consistent.
    """
    options = _ENCOURAGEMENT_POOL.get(context, [
        "还有其他需要吗？",
        "有校园相关问题可以问我。",
    ])
    return random.choice(options)
