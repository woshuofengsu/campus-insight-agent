# tools/action_report_issue.py
"""校园问题上报工具 — 基层治理核心功能。

学生随手提交校园问题（设施损坏、卫生状况、安全隐患等），
Agent 使用 LLM 自动分类、评估紧急程度、生成工单记录。
LLM 调用失败时自动降级为关键词匹配。
"""
import json
import logging

_log = logging.getLogger(__name__)
import re
from langchain.tools import tool
from data.database import report_issue as _db_report_issue
from data.database import get_issues_stats as _db_get_stats

# ── Cache for LLM classify results (avoids duplicate API calls within session) ──
_classify_cache: dict[str, tuple[str, str]] = {}
_MAX_CACHE_SIZE = 200


def _llm_classify(title: str, description: str) -> tuple[str, str]:
    """Use LLM (DeepSeek) to classify issue category + assess urgency.

    Returns (category, urgency) tuple.
    Falls back to keyword matching on any error (API timeout, rate limit, etc.).
    Results are cached by (title+description) to avoid duplicate API calls.
    """
    cache_key = f"{title}|{description or ''}"
    if cache_key in _classify_cache:
        return _classify_cache[cache_key]

    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

        if not DEEPSEEK_API_KEY:
            raise ValueError("No API key configured")

        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
            temperature=0,
            max_tokens=80,
            timeout=5,        # short timeout — classification is fast
            max_retries=0,    # no retry — fall back to keywords on failure
        )

        prompt = (
            "你是校园问题分类助手。根据标题和描述，判断类别和紧急程度。\n\n"
            "类别选项：设施维修, 环境卫生, 安全隐患, 教学设备, 网络服务, 餐饮问题, 校园管理, 其他\n"
            "紧急程度：普通（一般问题）, 紧急（影响较大需尽快处理）, 极急（涉及人身安全或大面积影响）\n\n"
            "甄别标准：\n"
            "- 极急：火灾、漏电、大面积停电停水、电梯困人、严重漏水、人员受伤、煤气泄漏\n"
            "- 紧急：停电、停水、玻璃碎裂、线路裸露、消防通道堵塞、电梯故障\n"
            "- 普通：其他一般问题\n\n"
            f"标题：{title}\n"
            f"描述：{description or '无'}\n\n"
            "只返回JSON，不要任何解释："
            '{"category": "分类结果", "urgency": "紧急程度"}'
        )

        response = llm.invoke(prompt)
        text = response.content if hasattr(response, 'content') else str(response)

        # Extract JSON from response (handles occasional markdown wrapping)
        match = re.search(r'\{[^{}]*"category"[^{}]*"urgency"[^{}]*\}', text, re.DOTALL)
        if not match:
            match = re.search(r'\{[^}]+\}', text)
        if match:
            result = json.loads(match.group())
            category = result.get("category", "其他")
            urgency = result.get("urgency", "普通")

            valid_cats = {
                "设施维修", "环境卫生", "安全隐患", "教学设备",
                "网络服务", "餐饮问题", "校园管理", "其他",
            }
            valid_urg = {"普通", "紧急", "极急"}
            if category not in valid_cats:
                category = "其他"
            if urgency not in valid_urg:
                urgency = "普通"

            # Cache result (with size limit)
            if len(_classify_cache) >= _MAX_CACHE_SIZE:
                _classify_cache.pop(next(iter(_classify_cache)))
            _classify_cache[cache_key] = (category, urgency)

            return category, urgency

    except (Exception,):
        # Catch all but don't catch BaseException (KeyboardInterrupt, SystemExit)
        _log.debug("LLM classification failed, falling back to keyword-based classification")

    # ── Keyword fallback ──
    cat = _keyword_classify(title, description)
    urg = _keyword_urgency(title, description)
    return cat, urg


# ── Location validation: dorm/classroom should have location info ──

_ROOM_REQUIRED_KEYWORDS = [
    "宿舍", "寝室", "教室", "多媒体", "机房", "实验室", "自习室",
    "办公室", "会议室", "活动室", "琴房", "画室", "舞蹈室",
]
_ROOM_EXEMPT_KEYWORDS = [
    "厕所", "洗手间", "卫生间", "走廊", "楼梯", "电梯", "大厅",
    "操场", "食堂", "图书馆", "校门", "道路", "停车场", "车棚",
    "快递", "围墙", "花园", "草坪",
]
# Accept any reasonable location: building+floor, room number, or building name
_ROOM_NUMBER_PATTERN = re.compile(
    r"(\d{3,}|[号楼栋幢层Ff]\s*\d+|"
    r"[A-Za-z]\d{2,}|\d+[层Ff楼]|"
    r"[一二三四五六七八九十]+[层Ff楼]|"
    r"\d+号(?:宿舍|学生)?楼)"
)


def validate_location(title: str, location: str) -> str | None:
    """Check dorm/classroom issues have at least building-level location.

    Returns error only when location is completely empty for dorm/classroom
    issues. Any non-empty location (building name, floor, room) is accepted —
    having some location info is always more actionable than blocking the report.
    """
    text = f"{title} {location}"
    needs_room = any(kw in text for kw in _ROOM_REQUIRED_KEYWORDS)
    is_exempt = any(kw in text for kw in _ROOM_EXEMPT_KEYWORDS)

    if needs_room and not is_exempt:
        if not location.strip():
            return "⚠️ 宿舍/教室类问题请填写位置（如：5号楼302、教三楼205、宿舍楼2楼）"
        # Any non-empty location is accepted — partial info > no report
    return None

# Issue categories for auto-classification
_CATEGORIES = {
    "设施维修": ["灯", "水龙头", "空调", "电梯", "门", "窗", "桌椅", "投影仪", "黑板", "电源",
                 "水管", "暖气", "锁", "扶手", "天花板", "地板", "漏水", "停电", "停水"],
    "环境卫生": ["垃圾", "厕所", "异味", "蟑螂", "老鼠", "灰尘", "脏", "清洁", "消毒", "卫生纸",
                 "洗手液", "下水道", "污水"],
    "安全隐患": ["火灾", "电线", "裸露", "玻璃", "裂", "塌", "摔倒", "漏电", "煤气", "消防",
                 "通道堵塞", "电梯故障", "围栏"],
    "教学设备": ["电脑", "网络", "WiFi", "音响", "麦克风", "屏幕", "机房", "多媒体", "话筒"],
    "网络服务": ["网速", "断网", "VPN", "校园网", "登录不了", "系统", "网站", "APP"],
    "餐饮问题": ["食堂", "饭菜", "价格", "食品", "卫生许可证", "食材", "变质", "排队"],
    "其他": [],
}


def _keyword_classify(title: str, description: str) -> str:
    """Keyword-based fallback classifier — used when LLM is unavailable."""
    text = f"{title} {description}"
    for cat, keywords in _CATEGORIES.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "其他"


def _keyword_urgency(title: str, description: str) -> str:
    """Keyword-based fallback urgency assessment — used when LLM is unavailable."""
    urgent_keywords = ["火灾", "漏电", "触电", "塌", "爆炸", "大面积停电", "电梯困人",
                       "受伤", "流血", "煤气", "中毒", "严重漏水"]
    high_keywords = ["停电", "停水", "电梯故障", "玻璃碎裂", "线路裸露", "消防",
                     "通道堵塞", "大面积", "严重"]

    text = f"{title} {description}"
    for kw in urgent_keywords:
        if kw in text:
            return "极急"
    for kw in high_keywords:
        if kw in text:
            return "紧急"
    return "普通"


# Backward-compatible aliases (used by other modules)
_auto_classify = _keyword_classify
_auto_urgency = _keyword_urgency


@tool
def report_issue(title: str, category: str = "", location: str = "",
                 description: str = "", urgency: str = "") -> str:
    """上报校园问题 — 发现设施损坏、环境卫生、安全隐患等问题时使用。

    学生可以快速提交校园中发现的各类问题。Agent 使用 AI（DeepSeek）自动分析和分类，
    根据语义理解（而非关键词匹配）判断问题类别和紧急程度。LLM 不可用时自动降级为
    关键词匹配。
    参数：
    - title: 问题标题（如"三教二楼男厕水龙头漏水"）
    - category: 可选，问题分类。留空则 AI 自动分类
    - location: 问题地点
    - description: 问题详细描述
    - urgency: 可选，紧急程度。与 category 同时提供时跳过 LLM 分类（快速路径）
    """
    if not title.strip():
        return "❌ 请至少提供问题标题，例如：'三教二楼走廊灯不亮了'"

    # Validate location for dorm/classroom issues
    loc_err = validate_location(title, location)
    if loc_err:
        return loc_err

    # ── Classification: use fast keyword path when category+urgency are both
    #     provided (e.g. from safety net), otherwise use LLM for better accuracy ──
    if category.strip() and urgency.strip():
        # Fast path: skip LLM, use provided values (validated below)
        pass
    elif not category.strip():
        category, urgency = _llm_classify(title, description)
    else:
        _, urgency = _llm_classify(title, description)

    issue_id = _db_report_issue(
        title=title.strip(),
        category=category,
        location=location.strip(),
        description=description.strip(),
        urgency=urgency,
        author="",  # Let _resolve_author() auto-fill from user profile
    )

    # Get current stats for context
    stats = _db_get_stats()

    urgency_emoji = {"普通": "🔵", "紧急": "🟠", "极急": "🔴"}
    ue = urgency_emoji.get(urgency, "🔵")

    lines = [
        "✅ 问题已上报成功！",
        f"",
        f"  📋 工单编号：#{issue_id}",
        f"  📂 分类：{category}",
        f"  {ue} 紧急程度：{urgency}",
        f"  📍 地点：{location or '未指定'}",
        f"",
        f"📊 校园治理数据：当前共有 {stats['total']} 个上报问题，"
        f"其中 {stats['by_status'].get('待处理', 0)} 个待处理。",
    ]

    if urgency in ("紧急", "极急"):
        lines.append(
            f"\n⚠️ 该问题已被标记为 **{urgency}**，建议同步电话通知相关部门。"
        )
    else:
        lines.append(
            "\n💡 感谢你的反馈！维修/保洁人员将尽快处理。"
        )

    return "\n".join(lines)
