# agent/helpers.py
"""Shared helpers used by both CommunityAgent (LLM-driven) and OfflineAgent (rule-driven).

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
        return profile.get("name", "") or profile.get("resident_id", "") or ""
    except Exception:  # ok to fail
        _log.debug("Failed to get user name from profile", exc_info=True)
        return ""


def extract_location(text: str) -> str:
    """Extract a clean community location from user input text.

    Matches known community location names (buildings, units, facilities) and returns
    just the location portion — problem descriptions like "灯坏了" are excluded.
    """
    # ── Known location patterns (ordered by specificity, longest first) ──
    _LOCATION_PATTERNS = [
        # Specific buildings with numbers: "3号楼", "2单元501", "7号楼前"
        r'(?:[一二三四五六七八九\d]+号(?:楼|栋|单元)\d*)',
        # Building + unit combos
        r'(?:[一二三四五六七八九\d]+号楼[一二三四五六七八九\d]+单元)',
        # General facility names (longer patterns first for greedy match)
        r'(?:小区|车库|楼道|天台|电梯间|活动室|助餐点|快递柜|垃圾站|充电桩'
        r'|门禁|健身器材|滑梯|坡道|自行车棚|广场|花园|绿地'
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
        "查看「📊 社区治理看板」获取更详细的数据。",
        "深入了解某类诉求？输入「设施维修类有哪些」。",
        "发现小区问题？直接描述即可上报。",
    ],
    "stats": [
        "查看某类诉求？输入「设施维修有哪些」。",
        "需要图表？在「📊 社区治理看板」页面查看。",
        "数据每小时更新一次。",
    ],
    "report": [
        "已上报。输入「查看我的工单」追踪进度。",
        "已记录。输入「查看我的工单」追踪。",
        "已上报。网格员/物业会尽快处理。",
    ],
    "proposal": [
        "提案已创建。附议越多越容易被社区/物业关注。",
        "分享给邻居，让更多人附议你的提案。",
        "提案已提交。查看「邻里议事」页面关注进展。",
    ],
}


def random_encouragement(context: str = "") -> str:
    """Return a random encouragement phrase for the given context.

    Shared by both agents to keep response tone consistent.
    """
    options = _ENCOURAGEMENT_POOL.get(context, [
        "还有其他需要吗？",
        "有社区相关问题可以问我。",
    ])
    return random.choice(options)
