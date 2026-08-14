# agent/helpers.py
"""两个 Agent 共用的辅助函数（LLM 版 CommunityAgent 和规则版 OfflineAgent 都用）。

抽出来是为了去掉两个实现里重复的代码。
"""
import logging
import random
import re

_log = logging.getLogger(__name__)


def get_author_identifier(memory) -> str | None:
    """拿到当前用户的作者标识，匿名就返回 None。"""
    from data.db_governance import _resolve_author
    author = _resolve_author("")
    return author if author != "匿名" else None


def get_user_name(memory) -> str:
    """从用户资料里取显示名。"""
    try:
        profile = memory.get_user_profile()
        return profile.get("name", "") or profile.get("resident_id", "") or ""
    except Exception:  # 挂了也没关系
        _log.debug("从 profile 获取用户名失败", exc_info=True)
        return ""


def extract_location(text: str) -> str:
    """从用户输入里抠出干净的小区位置。

    匹配已知的地点词（楼栋、单元、设施），只返回位置部分——
    "灯坏了"这类问题描述不会被带进来。
    """
    # 已知位置模式（按具体程度排序，长的在前）
    _LOCATION_PATTERNS = [
        # 带数字的具体楼栋："3号楼"、"2单元501"、"7号楼前"
        r'(?:[一二三四五六七八九\d]+号(?:楼|栋|单元)\d*)',
        # 楼栋 + 单元组合
        r'(?:[一二三四五六七八九\d]+号楼[一二三四五六七八九\d]+单元)',
        # 通用设施名（长的放前面，贪心匹配）
        r'(?:小区|车库|楼道|天台|电梯间|活动室|助餐点|快递柜|垃圾站|充电桩'
        r'|门禁|健身器材|滑梯|坡道|自行车棚|广场|花园|绿地'
        r')',
    ]
    _LOCATION_RE = re.compile(
        r'(?:' + r'|'.join(_LOCATION_PATTERNS) + r')'
        r'(?:[一-鿿\d]{0,6}(?:楼|[层Ff]|层))?'  # 可选的楼层/房间后缀
    )

    match = _LOCATION_RE.search(text)
    if match:
        loc = match.group(0)
        # 去掉末尾的标点和空白
        loc = re.sub(r'[。，,、！!？?\s]+$', '', loc).strip()
        # 别把整句话当位置返回（除非输入本身很短）
        if len(loc) < len(text) * 0.85 or len(text) <= 6:
            return loc
        # 输入很短时整句就是位置，保留
        if len(text) <= 12:
            return loc

    return ""


# 鼓励语

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
    """按上下文随机返回一句鼓励语。

    两个 Agent 共用，保证回复语气一致。
    """
    options = _ENCOURAGEMENT_POOL.get(context, [
        "还有其他需要吗？",
        "有社区相关问题可以问我。",
    ])
    return random.choice(options)
