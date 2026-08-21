# tools/action_report_issue.py
"""社区报修上报工具 — 报修模块工具层。

居民提交报修工单，Agent 使用 LLM 自动分类（诉求类别）、评估紧急程度（四档：
紧急/中等/一般/普通）、识别特殊情况（安全隐患/违规搭建/第三方施工），
LLM 调用失败时自动降级为关键词匹配。
数据落库统一走 data/db_repair.submit_issue（完整状态机：待审核 → … → 处理结束）。
"""
import json
import logging
import re

from langchain.tools import tool
from data.db_repair import submit_issue

_log = logging.getLogger(__name__)

# LLM 分类结果缓存（同一个会话里别重复调接口）
_classify_cache: dict[str, tuple[str, str]] = {}
_MAX_CACHE_SIZE = 200

# 紧急程度四档（文档《01-报修.md》）：紧急/中等/一般/普通
_URGENCY_LEVELS = ("紧急", "中等", "一般", "普通")
# 旧三档（极急/紧急/普通）→ 新四档的映射，兼容 LLM 偶尔吐旧档位
_LEGACY_URGENCY_MAP = {"极急": "紧急", "紧急": "中等", "普通": "一般"}

# 室内/室外分类关键词：描述里出现这些词默认「室内」，否则「室外」
_INDOOR_KEYWORDS = [
    "家里", "室内", "我家", "卧室", "厨房", "卫生间", "客厅", "阳台",
    "书房", "厕所", "浴室", "洗澡", "餐厅", "玄关",
]


def _detect_issue_type(title: str, description: str) -> str:
    """根据标题+描述判断报修分类（室内/室外）。默认室外。"""
    text = f"{title or ''} {description or ''}"
    if any(kw in text for kw in _INDOOR_KEYWORDS):
        return "室内"
    return "室外"


def _normalize_urgency(urgency: str) -> str:
    """把任意来源的紧急程度归一化到四档（紧急/中等/一般/普通）。"""
    if urgency in _URGENCY_LEVELS:
        return urgency
    if urgency in _LEGACY_URGENCY_MAP:
        return _LEGACY_URGENCY_MAP[urgency]
    return "一般"


def _resolve_reporter_id() -> int | None:
    """解析当前用户 ID（记录上报人，用于闭环通知）。"""
    try:
        from data.db_governance import _resolve_reporter_id
        return _resolve_reporter_id()
    except Exception:
        _log.debug("解析 reporter_id 失败，按无用户处理", exc_info=True)
        return None


def _llm_classify(title: str, description: str) -> tuple[str, str]:
    """用 LLM（DeepSeek）判断诉求类别 + 评估紧急程度（四档）。

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
            "你是社区报修分类助手。根据标题和描述，判断类别和紧急程度。\n\n"
            "类别选项：设施维修, 环境卫生, 安全隐患, 停车管理, 噪音扰民, 物业服务, 邻里矛盾, 社区事务\n"
            "紧急程度（四档，从高到低）：紧急、中等、一般、普通\n"
            "- 紧急：涉及人身安全或大面积影响，需 1 小时内上门（火灾、漏电、大面积停水停电、电梯困人、严重漏水、人员受伤、燃气泄漏）\n"
            "- 中等：影响较大需尽快处理，4 小时内上门（停电、停水、玻璃碎裂、线路裸露、消防通道堵塞、电梯故障）\n"
            "- 一般：一般维修问题，24 小时内上门（如灯具损坏、门锁维修、下水道堵塞）\n"
            "- 普通：轻微问题不影响正常生活，48 小时内解决（如小磕碰、美观类、咨询建议）\n\n"
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
            urgency = result.get("urgency", "一般")

            valid_cats = {
                "设施维修", "环境卫生", "安全隐患", "停车管理",
                "噪音扰民", "物业服务", "邻里矛盾", "社区事务",
            }
            if category not in valid_cats:
                category = "其他"
            urgency = _normalize_urgency(urgency)

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
    """关键词兜底紧急度判断 — LLM 不可用时用（四档：紧急/中等/一般/普通）。"""
    urgent_keywords = ["火灾", "漏电", "触电", "塌", "爆炸", "大面积停电", "电梯困人",
                       "受伤", "流血", "煤气", "中毒", "严重漏水", "起火", "冒烟"]
    medium_keywords = ["停电", "停水", "电梯故障", "玻璃碎裂", "线路裸露", "消防",
                       "通道堵塞", "大面积", "严重", "渗水", "管道破裂", "堵塞"]
    low_keywords = ["小问题", "不影响", "轻微", "小事", "咨询", "建议", "美观", "顺手", "磕碰", "划痕", "掉漆"]

    text = f"{title} {description}"
    for kw in urgent_keywords:
        if kw in text:
            return "紧急"
    for kw in medium_keywords:
        if kw in text:
            return "中等"
    for kw in low_keywords:
        if kw in text:
            return "普通"
    return "一般"


# 表单用的 AI 分类（LLM + 关键词兜底）
def _auto_classify(title: str, description: str = "") -> str:
    """AI 语义分类 — 由 DeepSeek 判断类别，失败时自动降级为关键词匹配。"""
    return _llm_classify(title, description)[0]


def _auto_urgency(title: str, description: str = "") -> str:
    """AI 紧急度评估 — 由 DeepSeek 判断紧急程度（四档），失败时自动降级为关键词匹配。"""
    return _llm_classify(title, description)[1]


_URGENCY_EMOJI = {"紧急": "🔴", "中等": "🟠", "一般": "🟡", "普通": "🔵"}


def correct_typos(text: str) -> str:
    """LLM 纠正错别字/病句，失败或无明显差异时返回原文本（spec：纠正后交居民确认）。

    供报修/提案提交前的「纠错建议」用；不改变原文存储，只做提示。
    """
    if not text or len(text.strip()) < 3:
        return text
    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        if not DEEPSEEK_API_KEY:
            return text
        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL, temperature=0, max_tokens=120, timeout=5, max_retries=0,
        )
        prompt = (
            "你是中文校对助手。纠正下面这段话的错别字和病句，"
            "只输出纠正后的文本，不要任何解释。如果无需纠正，原样输出：\n"
            f"{text}"
        )
        resp = llm.invoke(prompt)
        out = (resp.content if hasattr(resp, "content") else str(resp)).strip().strip('"')
        return out if out and len(out) >= 3 else text
    except Exception:
        return text


@tool
def report_issue(title: str, category: str = "", location: str = "",
                 description: str = "", urgency: str = "",
                 reporter_name: str = "", reporter_phone: str = "") -> str:
    """上报社区诉求 / 提交报修工单 — 发现设施损坏、环境卫生、安全隐患等问题时使用。

    居民提交报修，Agent 使用 DeepSeek 自动分析和分类，判断诉求类别、紧急程度
    （四档：紧急/中等/一般/普通）、室内/室外分类并识别特殊情况。LLM 不可用时
    自动降级为关键词匹配。
    参数：
    - title: 问题描述（如"3号楼2单元电梯困人"）
    - category: 可选，诉求类别（设施维修等）。留空则自动分类
    - location: 报修地址（小区/院落名称 + 楼栋单元房号）
    - description: 可选，补充详细描述
    - urgency: 可选，紧急程度（紧急/中等/一般/普通）。与 category 同时提供时跳过 LLM 分类
    - reporter_name: 报修人姓名
    - reporter_phone: 报修人联系电话（手机号，系统自动校验格式）
    """
    if not title.strip():
        return "❌ 请至少提供问题描述，例如：'3号楼2单元电梯困人了'"

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

    category = (category or "其他").strip() or "其他"
    urgency = _normalize_urgency(urgency)
    issue_type = _detect_issue_type(title, description)

    issue_id, hint = submit_issue(
        title=title.strip(),
        category=category,
        issue_type=issue_type,
        location=location.strip(),
        description=description.strip(),
        urgency=urgency,
        reporter_name=reporter_name.strip(),
        reporter_phone=reporter_phone.strip(),
        reporter_id=_resolve_reporter_id(),
    )

    # 清网格员那边的缓存，新工单立刻能看见
    try:
        from ui.cache import invalidate_issues
        invalidate_issues()
    except Exception:
        pass

    # 特殊情况提示文案
    if hint == "safety":
        return (
            "⚠️ **已记录安全提醒，不生成维修工单**\n\n"
            "您描述的情况存在安全隐患，请先拨打紧急电话：\n"
            "- 🚒 消防：**119**\n"
            "- 🔥 燃气：**96777**\n\n"
            "系统已记录您的安全提醒，社区负责人会同步跟进。"
        )
    if hint == "third_party":
        return (
            "⚠️ 检测到该问题可能属于**第三方施工责任**，建议先联系施工方。\n\n"
            f"✅ 已按您的要求生成工单 **#{issue_id}** 并标记「非社区责任」，"
            "负责人会核实处理；如确认属第三方责任，将由负责人关闭工单并说明原因。"
        )
    if hint == "violation":
        return (
            f"⚠️ 工单 **#{issue_id}** 已生成并标记「**违规搭建**」。\n\n"
            "负责人审核通过后将按流程转出处理（转城管/社区治理），进度可在报修工单中查看。"
        )
    if issue_id <= 0:
        return f"❌ 提交失败：{hint}"

    # 正常成功
    ue = _URGENCY_EMOJI.get(urgency, "🔵")
    lines = [
        "✅ 报修工单已提交！",
        "",
        f"  📋 工单编号：#{issue_id}",
        f"  📂 分类：{category}（{issue_type}）",
        f"  {ue} 紧急程度：{urgency}",
        f"  📍 地点：{location or '未指定'}",
        f"  ⏳ 当前状态：待审核",
        "",
        "社区负责人会尽快电话核实，请保持电话畅通。",
    ]
    if urgency in ("紧急", "中等"):
        lines.append(f"\n⚠️ 该工单为 **{urgency}** 级别，已建议优先处理。")
    return "\n".join(lines)
