# tools/action_report_issue.py
"""社区诉求上报工具 — 接诉即办核心功能。

居民随手提交社区诉求（设施损坏、卫生状况、安全隐患等），
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

# LLM 分类结果缓存（同一个会话里别重复调接口）
_classify_cache: dict[str, tuple[str, str]] = {}
_MAX_CACHE_SIZE = 200


def _llm_classify(title: str, description: str) -> tuple[str, str]:
    """用 LLM（DeepSeek）判断诉求类别 + 评估紧急度。

    返回 (category, urgency) 元组。
    接口超时、限流等任何报错都退回关键词匹配。
    结果按（标题+描述）缓存，避免重复调接口。
    """
    cache_key = f"{title}|{description or ''}"
    if cache_key in _classify_cache:
        return _classify_cache[cache_key]

    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL

        if not DEEPSEEK_API_KEY:
            raise ValueError("未配置 API key")

        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL,
            temperature=0,
            max_tokens=80,
            timeout=5,        # 超时短一点，分类本来就快
            max_retries=0,    # 不重试，失败直接走关键词
        )

        prompt = (
            "你是社区诉求分类助手。根据标题和描述，判断类别和紧急程度。\n\n"
            "类别选项：设施维修, 环境卫生, 安全隐患, 停车管理, 噪音扰民, 物业服务, 邻里矛盾, 社区事务\n"
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

        # 从返回里抠 JSON（偶尔会被 markdown 包一层）
        match = re.search(r'\{[^{}]*"category"[^{}]*"urgency"[^{}]*\}', text, re.DOTALL)
        if not match:
            match = re.search(r'\{[^}]+\}', text)
        if match:
            result = json.loads(match.group())
            category = result.get("category", "其他")
            urgency = result.get("urgency", "普通")

            valid_cats = {
                "设施维修", "环境卫生", "安全隐患", "停车管理",
                "噪音扰民", "物业服务", "邻里矛盾", "社区事务",
            }
            valid_urg = {"普通", "紧急", "极急"}
            if category not in valid_cats:
                category = "其他"
            if urgency not in valid_urg:
                urgency = "普通"

            # 缓存结果，超了先挤掉最旧的
            if len(_classify_cache) >= _MAX_CACHE_SIZE:
                _classify_cache.pop(next(iter(_classify_cache)))
            _classify_cache[cache_key] = (category, urgency)

            return category, urgency

    except (Exception,):
        # 只抓 Exception，别碰 BaseException（KeyboardInterrupt、SystemExit）
        _log.debug("LLM 分类失败，退回关键词分类")

    # 关键词兜底
    cat = _keyword_classify(title, description)
    urg = _keyword_urgency(title, description)
    return cat, urg


# 位置校验：楼栋/单元类诉求必须带位置

_ROOM_REQUIRED_KEYWORDS = [
    "楼", "单元", "楼道", "电梯", "天台", "屋面", "车库", "地下室",
]
_ROOM_EXEMPT_KEYWORDS = [
    "广场", "花园", "草坪", "道路", "步道", "大门", "东门", "西门",
    "南门", "北门", "围墙", "车棚", "快递柜", "全小区", "垃圾桶",
    "垃圾点", "绿化带", "健身器材",
]
# 只要有个像样的位置就算过：楼栋+楼层、单元号、楼名都行
_ROOM_NUMBER_PATTERN = re.compile(
    r"(\d{3,}|[号楼栋幢层Ff]\s*\d+|"
    r"[A-Za-z]\d{2,}|\d+[层Ff楼]|"
    r"[一二三四五六七八九十]+[层Ff楼]|"
    r"\d+号(?:楼|单元)?)"
)


def validate_location(title: str, location: str) -> str | None:
    """楼栋/单元类诉求至少要填到楼栋级别的位置。

    只有楼栋/单元类问题且位置完全为空时才报错。
    只要填了任何位置（楼名、楼层、单元）都算过——
    有点位置信息总比把上报卡死强。
    """
    text = f"{title} {location}"
    needs_room = any(kw in text for kw in _ROOM_REQUIRED_KEYWORDS)
    is_exempt = any(kw in text for kw in _ROOM_EXEMPT_KEYWORDS)

    if needs_room and not is_exempt:
        if not location.strip():
            return "⚠️ 楼栋/单元类诉求请填写位置（如：3号楼2单元、7号楼前空地、中心花园）"
        # 只要非空就接受 — 有半截信息也比没上报强
    return None

# 自动分类用的关键词表
_CATEGORIES = {
    "安全隐患": ["火灾", "漏电", "触电", "煤气", "爆炸", "消防", "通道堵塞", "玻璃碎裂",
                 "瓷砖脱落", "外墙", "年检", "飞线", "电动车", "电线裸露", "塌", "困人"],
    "停车管理": ["停车", "车位", "地锁", "占位", "乱停", "违停", "车库", "占道"],
    "噪音扰民": ["噪音", "扰民", "广场舞", "装修", "施工", "喇叭", "犬吠", "狗叫", "吵闹", "分贝"],
    "物业服务": ["物业", "报修", "保洁", "保安", "安保", "门禁", "监控", "服务态度"],
    "邻里矛盾": ["邻里", "纠纷", "矛盾", "空调滴水", "占用公共"],
    "环境卫生": ["垃圾", "异味", "蟑螂", "老鼠", "蚊虫", "灰尘", "脏", "清洁", "消毒",
                 "绿化", "杂草", "粪便", "堆物", "清运", "满溢"],
    "设施维修": ["灯", "水龙头", "空调", "电梯", "门", "窗", "管道", "漏水", "停电", "停水",
                 "暖气", "扶手", "天花板", "地板", "墙面", "瓷砖", "快递柜", "健身器材",
                 "滑梯", "声控灯", "路灯", "坡道", "屋面", "渗水", "反味", "下水道", "器材"],
    "社区事务": ["助餐", "活动", "独居", "老人", "僵尸车", "政策", "咨询", "议事",
                 "充电桩", "加装电梯", "自行车棚"],
}


def _keyword_classify(title: str, description: str) -> str:
    """关键词兜底分类器 — LLM 不可用时用。"""
    text = f"{title} {description}"
    for cat, keywords in _CATEGORIES.items():
        for kw in keywords:
            if kw in text:
                return cat
    return "其他"


def _keyword_urgency(title: str, description: str) -> str:
    """关键词兜底紧急度判断 — LLM 不可用时用。"""
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


# 表单用的 AI 分类（LLM + 关键词兜底）
def _auto_classify(title: str, description: str = "") -> str:
    """AI 语义分类 — 由 DeepSeek 判断类别，失败时自动降级为关键词匹配。"""
    return _llm_classify(title, description)[0]


def _auto_urgency(title: str, description: str = "") -> str:
    """AI 紧急度评估 — 由 DeepSeek 判断紧急程度，失败时自动降级为关键词匹配。"""
    return _llm_classify(title, description)[1]


@tool
def report_issue(title: str, category: str = "", location: str = "",
                 description: str = "", urgency: str = "") -> str:
    """上报社区诉求 — 发现设施损坏、环境卫生、安全隐患等问题时使用。

    居民可以快速提交小区中发现的各类诉求。Agent 使用 DeepSeek 自动分析和分类，
    根据语义理解（而非关键词匹配）判断诉求类别和紧急程度。LLM 不可用时自动降级为
    关键词匹配。
    参数：
    - title: 诉求标题（如"3号楼2单元电梯困人"）
    - category: 可选，诉求分类。留空则自动分类
    - location: 诉求地点
    - description: 诉求详细描述
    - urgency: 可选，紧急程度。与 category 同时提供时跳过 LLM 分类（快速路径）
    """
    if not title.strip():
        return "❌ 请至少提供诉求标题，例如：'3号楼2单元电梯困人了'"

    # 楼栋/单元类诉求先校验位置
    loc_err = validate_location(title, location)
    if loc_err:
        return loc_err

    # 分类：category 和 urgency 都给了（比如安全网传的）就走快路径，
    #     否则用 LLM 分类，准确率高一点
    if category.strip() and urgency.strip():
        # 快路径：跳过 LLM，直接用传进来的值（下面会校验）
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
        author="",  # 空着，让 _resolve_author() 从用户资料自动补
        suggested_category=category,  # 把 AI 分类存下来，网格员审核时能对照
    )

    # 清网格员那边的缓存，新工单立刻能看见
    try:
        from ui.cache import invalidate_issues
        invalidate_issues()
    except Exception:
        pass

    # 顺手取一下统计数据，回复里好带上
    stats = _db_get_stats()

    urgency_emoji = {"普通": "🔵", "紧急": "🟠", "极急": "🔴"}
    ue = urgency_emoji.get(urgency, "🔵")

    lines = [
        "✅ 诉求已上报成功！",
        f"",
        f"  📋 工单编号：#{issue_id}",
        f"  📂 分类：{category}",
        f"  {ue} 紧急程度：{urgency}",
        f"  📍 地点：{location or '未指定'}",
        f"",
        f"📊 社区治理数据：当前共有 {stats['total']} 个上报诉求，"
        f"其中 {stats['by_status'].get('待处理', 0)} 个待处理。",
    ]

    if urgency in ("紧急", "极急"):
        lines.append(
            f"\n⚠️ 该诉求已被标记为 **{urgency}**，建议同步电话通知网格员/物业。"
        )
    else:
        lines.append(
            "\n网格员/物业将尽快处理，进度可在「接诉即办」中追踪。"
        )

    return "\n".join(lines)
