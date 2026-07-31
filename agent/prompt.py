# agent/prompt.py
"""System prompt template for CampusInsight Agent — 基层微治理方向.

Also provides persona detection (detect_persona) for role-routing — the agent
wears different "hats" depending on what the user is trying to do.
"""
import json
import re
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
# Persona Routing — lightweight intent detection (no LLM needed)
# ═══════════════════════════════════════════════════════════════

# Each persona: (role_name, emoji, focus_hint)
_PERSONA_SIGNALS: list[tuple[list[str], str, str]] = [
    (
        # 报修 — 校园设施故障关键词。覆盖常见问题描述 + 否定式 + 感官描述。
        # Note: "修" is intentionally NOT here (too ambiguous — matches "维修" in queries).
        # "要修"/"修一下"/"修修" capture reporting intent without false-matching data queries.
        ["坏了", "漏水", "故障", "不亮", "没电", "没水", "没网", "碎了", "裂了",
         "掉了", "断了", "堵了", "停了", "失灵", "停电", "停水", "断网", "报修",
         "上报", "要修", "修一下", "修修", "滴水", "漏雨", "摇晃", "松动", "锈",
         "信号差", "没信号", "关不上", "打不开", "没反应", "太慢", "不行了",
         "有问题", "不好使", "坏掉", "出问题", "出故障", "不工作", "不能用",
         "不制冷", "不制热", "不热", "不冷", "不转", "不运行",
         "破了", "歪了", "塌了", "陷了", "脏了", "臭了", "不干净",
         "不卫生", "有异味", "发霉", "长毛", "虫子", "蟑螂", "老鼠",
         # ── v2 扩展：覆盖更多校园真实场景 ──
         "模糊", "看不清", "太暗", "太亮", "太吵", "噪音", "吵闹", "太冷",
         "太热", "没空调", "不走了", "不动了", "卡住了", "没水了", "水太小",
         "漏气", "冒烟", "烧焦", "火花", "异味", "发臭", "堵住", "堵塞",
         "溢出来", "漏水了", "关不紧", "锁不上", "门坏了", "窗坏了", "玻璃",
         "碎玻璃", "地滑", "积水", "灯管", "灯泡", "插座", "开关", "电线",
         "脱落", "掉下来", "砸到", "绊倒", "坑", "裂缝", "墙皮", "发霉",
         "长毛了", "生锈", "锈了", "油漆", "翘起来", "扎手", "划伤",
         "投影仪", "屏幕", "音响", "话筒", "没声音", "太小", "喷水",
         "不出水", "堵塞了", "没热水", "热水器", "花洒", "马桶",
         "冲不了", "堵了", "味大", "垃圾", "没倒", "堆积", "乱扔",
         "乱放", "占用", "占座", "插队", "吵闹", "奔跑", "打闹"],
        "🔧 报修助手",
        "用户正在描述一个校园设施问题。你的首要任务是：快速判断信息是否完整，"
        "缺信息就追问1个关键问题，信息完整就立刻调用 report_issue。语气简洁高效，少寒暄。",
    ),
    (
        ["建议", "提案", "议题", "讨论", "附议", "我觉得应该", "能不能", "希望",
         "如果", "想法", "提议", "改善", "改进", "优化", "增加", "延长", "开设",
         "应该", "可否", "能否", "考虑", "怎么看", "觉得", "认为", "好不好",
         "怎么样", "行不行", "同不同意",
         # ── v2 扩展：覆盖更多议事诉求 ──
         "涨价", "降价", "价格", "太贵", "贵了", "不合理", "不公平", "凭什么",
         "为什么要", "为什么不能", "应当", "理应", "有必要", "没必要",
         "想要", "希望能", "能不能让", "可不可以", "求求", "呼吁",
         "反对", "不赞成", "抗议", "不满", "投诉", "吐槽",
         "食堂贵", "食堂价格", "菜品价格", "收费", "费用", "乱收费",
         "取消", "恢复", "调整", "改变", "修改", "更换", "替换",
         "引进", "建设", "安装", "配置", "提供", "供应",
         "开放时间", "闭馆", "开门", "关门时间", "延长到", "提前",
         "制度", "规定", "规则", "政策", "流程", "手续",
         "体验", "方便", "麻烦", "折腾", "浪费", "效率",
         "图书馆时间", "快递柜", "校园网", "空调安装", "洗衣机",
         "热水供应", "打印服务", "自习室", "选课", "课表", "考试安排"],
        "🗳️ 议事顾问",
        "用户有想法或建议。你的任务是：帮TA把想法结构化（分类、可行性、预期效果），"
        "引导创建提案或参与议题讨论。先检查有没有类似提案避免重复。语气鼓励、开放。",
    ),
    (
        ["数据", "统计", "多少", "趋势", "占比", "排名", "对比", "哪些", "比例",
         "解决率", "健康度", "变化", "图表", "报告", "分析", "汇总", "概览",
         "工单", "进度", "状态", "查询", "查看", "列表", "所有", "有几",
         "维修", "设施", "分类", "分布", "总数", "数量", "平均",
         "有什么问题", "有哪些问题", "什么问题", "哪个类别",
         # ── v2 扩展：覆盖更多数据查询场景 ──
         "找一下", "查查", "查一下", "搜一下", "看看有没有", "帮我看看",
         "还有多少", "有几个", "多少个", "处理了", "没处理的",
         "报修情况", "解决情况", "治理情况", "哪类", "什么类型",
         "哪个最多", "哪个最少", "哪个最慢", "哪个最快",
         "哪个地方", "哪栋楼", "哪个食堂", "哪个宿舍",
         "最近一周", "最近一个月", "这个月", "上个月", "本周", "上周",
         "统计一下", "整理一下", "梳理", "盘点", "检查一下",
         "未处理", "待解决", "已处理", "处理中", "积压", "超期"],
        "📊 数据分析师",
        "用户想了解治理数据。你的任务是：调用统计工具获取数据，用结构化方式呈现"
        "（编号列表、对比、趋势解读），突出关键发现。语气客观、数据驱动。",
    ),
    (
        ["校园脉搏", "动态", "热点", "最近", "这周", "今天", "发生", "什么",
         "新闻", "通知", "大事", "新鲜事", "天气", "怎么样", "如何", "情况",
         "告诉我", "介绍", "有什么",
         # ── v2 扩展：覆盖更多校园动态询问 ──
         "聊聊", "说说", "讲一下", "播报", "快讯", "简讯",
         "最近有什么", "最近发生什么", "有什么新鲜", "有什么大事",
         "校园最新", "最近动态", "最新消息", "最新情况",
         "天气如何", "冷不冷", "热不热", "带不带伞", "需不需要伞",
         "有新消息吗", "有什么变化", "跟之前比", "现在怎么样"],
        "🌊 校园观察员",
        "用户想了解校园最新动态。你的任务是：调用 get_campus_pulse 获取快照，"
        "结合天气和治理热点，用亲切的口吻播报。语气像校园广播员一样生动。",
    ),
]


# ── Semantic fallback patterns ──
# When no keyword matches, try regex-based detection for common campus patterns.
# <location/facility> + <negative/problem descriptor>
_SEMANTIC_FALLBACK_REPAIR = re.compile(
    r"((?:教\d+楼|图书馆|食堂|宿舍\d*号楼|操场|体育馆|实验楼|行政楼|"
    r"[一二三四五六七八九十]食堂|\d+号宿舍楼|\d+栋|"
    r"投影仪|屏幕|音响|话筒|空调|热水器|花洒|马桶|灯泡|灯管|插座|开关|"
    r"饮水机|打印机|洗衣机|电梯|门|窗|水龙头|厕所|洗手间|浴室)..{0,10}?"
    r"(?:坏|破|碎|裂|掉|断|堵|停|没|不|失灵|故障|问题|不行|不好|无法|不能|"
    r"太慢|太吵|太热|太冷|太暗|太亮|模糊|看不清|漏水|漏|滴水|松动|摇晃|"
    r"生锈|发霉|发臭|异味|噪音|占座|插队|垃圾|积水|地滑|裂缝|脱落|"
    r"关不上|打不开|没反应|不工作|不能用|不运行|不制冷|不制热|"
    r"不走了|不动了|卡住了|溢出来|冲不了|不出水|没声音))"
)

_SEMANTIC_FALLBACK_PROPOSAL = re.compile(
    r"(?:能不能|可不可以|应该|建议|希望|想要|要求|呼吁|反对|"
    r"涨价|太贵|不合理|不公平|凭什么|投诉|"
    r"延长|缩短|增加|减少|取消|恢复|调整|改变|"
    r"开放时间|闭馆时间|关门时间|开门时间)"
)


# ── Status-query patterns: user is asking about an EXISTING issue's progress ──
# These override repair persona routing because "上报的xxx修好了吗" is a
# data query, not a new issue report.
_STATUS_QUERY_PATTERNS = [
    r"修好了吗", r"修好没", r"修了没", r"解决了吗", r"解决了没",
    r"处理了吗", r"处理了没", r"好了吗", r"好了没", r"怎么样了",
    r"有进展吗", r"有结果吗", r"什么状态", r"进度如何", r"到哪了",
    r"回复了吗", r"有回复吗", r"通过了吗", r"采纳了吗",
    r"还在(?:处理|修|等|排队)", r"还没(?:修|处理|解决|回复|弄)好",
]
_STATUS_QUERY_RE = re.compile("|".join(_STATUS_QUERY_PATTERNS))

# Strong ownership signals — user is talking about THEIR OWN stuff
_OWNERSHIP_PREFIXES = [
    "我的", "我上报的", "我报修的", "我提交的", "我那个", "我之前",
    "我上次", "我前几天", "我刚刚", "我刚才", "我昨天", "我前天",
    "帮我查一下", "帮我看看", "帮我查查",
]
_OWNERSHIP_RE = re.compile("|".join(_OWNERSHIP_PREFIXES))


def _detect_status_query(txt: str) -> bool:
    """Return True if the user is asking about status/progress of an existing item,
    rather than reporting a new problem or creating something new.

    Detects two signals:
    1. Status-check keywords: "修好了吗" / "解决了吗" / "有进展吗" etc.
    2. Ownership + query combo: "我的xxx" + check intent (weaker signal alone,
       but combined with a repair-keyword hit, it flips the intent to query)
    """
    if _STATUS_QUERY_RE.search(txt):
        return True
    # Ownership signal alone is not enough — only flip if also short (likely
    # a quick check, not a long problem description)
    if _OWNERSHIP_RE.search(txt) and len(txt) <= 20:
        return True
    return False


def _semantic_detect(txt: str) -> dict | None:
    """Regex-based semantic fallback when keyword matching finds nothing.

    Handles cases like "教三楼的钟不走了" or "投影仪模糊看不清"
    which don't contain exact keywords like "坏了" or "故障".
    """
    if _SEMANTIC_FALLBACK_REPAIR.search(txt):
        return {
            "role": "🔧 报修助手",
            "focus_hint": "用户可能正在描述一个设施问题（语义检测）。快速判断信息是否完整，"
                          "缺信息就追问，完整就调用 report_issue。",
            "confidence": "low",
            "matched_count": 0,
            "semantic_fallback": True,
        }
    if _SEMANTIC_FALLBACK_PROPOSAL.search(txt):
        return {
            "role": "🗳️ 议事顾问",
            "focus_hint": "用户可能在表达诉求或建议（语义检测）。帮TA把想法结构化，"
                          "引导创建提案或参与讨论。",
            "confidence": "low",
            "matched_count": 0,
            "semantic_fallback": True,
        }
    return None


def detect_persona(user_input: str) -> dict | None:
    """Detect user intent and return the appropriate persona context.

    Uses lightweight keyword matching with confidence scoring and
    multi-persona blending for compound queries. Falls back to regex-based
    semantic detection when no keywords match.

    The returned persona dict is injected into the agent's oriented_input
    by engine._orient() so the agent adopts the right "hat" for this turn.

    Priority: data-analysis keywords trump repair keywords when both match,
    because "统计报修数量" is a query, not a repair report.
    """
    if not user_input:
        return None
    txt = user_input.strip()
    if len(txt) < 2:
        return None

    # Collect ALL matching personas with individual keyword match counts
    matches: list[tuple[int, str, str, int]] = []  # (index, role, hint, match_count)
    for idx, (keywords, role, hint) in enumerate(_PERSONA_SIGNALS):
        matched = sum(1 for kw in keywords if kw in txt)
        if matched > 0:
            matches.append((idx, role, hint, matched))

    if not matches:
        # ── Semantic fallback: regex-based pattern matching ──
        return _semantic_detect(txt)

    # ── Status-query override: "修好了吗" / "解决了吗" etc. ──
    # When the user is asking about an existing item's progress, redirect
    # from repair persona to data analyst — they need query_issues, not report_issue.
    if _detect_status_query(txt):
        repair_idx = 0  # 报修助手 is always index 0
        data_idx = 2    # 数据分析师 is always index 2
        matched_indices = {m[0] for m in matches}
        if repair_idx in matched_indices:
            # Flip: treat as data query instead of repair report
            data_keywords, data_role, data_hint = _PERSONA_SIGNALS[data_idx]
            # Re-count matches against data keywords for confidence
            data_hits = sum(1 for kw in data_keywords if kw in txt)
            conf = "medium" if data_hits >= 1 else "low"
            return {
                "role": data_role,
                "focus_hint": "用户可能在查询已有工单/提案的进展状态（状态查询检测）。"
                              "调用 query_issues 查询相关工单，不要创建新工单。",
                "confidence": conf,
                "matched_count": max(data_hits, 1),
                "status_query_override": True,
                "original_persona": "🔧 报修助手",
            }

    # ── Confidence scoring ──
    total_matches = sum(m[3] for m in matches)
    roles_by_idx: dict[int, tuple[str, str, int]] = {m[0]: (m[1], m[2], m[3]) for m in matches}

    # Very short input (<5 chars) → lower confidence, use first match
    # (5+ char inputs with keyword matches get full resolution)
    if len(txt) < 5:
        _, role, hint, count = matches[0]
        return {"role": role, "focus_hint": hint, "confidence": "low",
                "matched_count": count}
    # Single match with only 1 keyword hit → fast path, low confidence
    if len(matches) == 1 and matches[0][3] == 1:
        _, role, hint, count = matches[0]
        return {"role": role, "focus_hint": hint, "confidence": "low",
                "matched_count": count}

    # ── Priority: 数据分析师 (idx=2) wins with strong analysis keywords ──
    if 2 in roles_by_idx:
        strong_data_kw = ["统计", "数据", "分析", "汇总", "趋势", "占比", "对比", "排名", "图表", "报告"]
        if any(kw in txt for kw in strong_data_kw):
            role, hint, count = roles_by_idx[2]
            conf = "high" if count >= 3 else "medium"
            return {"role": role, "focus_hint": hint, "confidence": conf,
                    "matched_count": count}

    # ── Priority: Category + "问题" combos → data analyst ──
    # "食堂有什么问题" "图书馆有哪些问题" etc. → query, not pulse
    _cat_words = ["食堂", "图书馆", "宿舍", "教学", "操场", "网络", "设施",
                  "餐饮", "卫生", "安全", "一食", "二食", "三食"]
    if 2 in roles_by_idx and any(cw in txt for cw in _cat_words):
        role, hint, count = roles_by_idx[2]
        return {"role": role, "focus_hint": hint, "confidence": "medium",
                "matched_count": count}

    # ── Query-prefix disambiguation: "看看有哪些提案" "查查工单" → data analyst ──
    _query_prefixes = ["看看有哪些", "看看有", "查查有", "查一下有", "找一下有",
                       "搜一下有", "帮我看看有", "帮我查"]
    _gov_nouns = ["提案", "工单", "议题", "问题", "报修"]
    if 2 in roles_by_idx and any(qp in txt for qp in _query_prefixes):
        role, hint, count = roles_by_idx[2]
        return {"role": role, "focus_hint": hint, "confidence": "medium",
                "matched_count": count}
    # "报修情况" "报修统计" "报修数据" → data analyst, NOT repair
    if 2 in roles_by_idx and any(f"{gn}{s}" in txt for gn in _gov_nouns
                                  for s in ["情况", "统计", "数据", "列表", "汇总"]):
        role, hint, count = roles_by_idx[2]
        return {"role": role, "focus_hint": hint, "confidence": "medium",
                "matched_count": count}

    # ── Priority: 校园观察员 (idx=3) vs 议事顾问 (idx=1) ──
    if 3 in roles_by_idx and 1 in roles_by_idx:
        proposal_kw = ["提案", "建议", "提议", "附议"]
        if not any(kw in txt for kw in proposal_kw):
            role, hint, count = roles_by_idx[3]
            conf = "high" if count >= 3 else "medium"
            return {"role": role, "focus_hint": hint, "confidence": conf,
                    "matched_count": count}

    # ── Multi-persona blending for compound queries ──
    # When 2+ strong personas match, blend their focus hints
    if len(matches) >= 2 and total_matches >= 4:
        primary = matches[0]
        secondary = matches[1]
        blended_hint = (
            f"{primary[2]} "
            f"同时留意：{secondary[2][:60]}"
        )
        conf = "high" if total_matches >= 6 else "medium"
        return {"role": primary[1], "focus_hint": blended_hint,
                "confidence": conf, "matched_count": total_matches,
                "blended": True, "secondary_role": secondary[1]}

    # ── Default: prefer persona with most keyword matches ──
    # Sort by match count descending; if top has significantly more than second, use it
    matches.sort(key=lambda x: -x[3])
    if len(matches) >= 2 and matches[0][3] >= matches[1][3] + 1:
        _, role, hint, count = matches[0]
        conf = "high" if count >= 3 else "medium" if count >= 2 else "low"
        return {"role": role, "focus_hint": hint, "confidence": conf,
                "matched_count": count}

    # ── Fallback: first match by index order ──
    _, role, hint, count = matches[0]
    conf = "high" if count >= 3 else "medium" if count >= 2 else "low"
    return {"role": role, "focus_hint": hint, "confidence": conf,
            "matched_count": count}


def get_system_prompt(user_profile: dict, environment_context: str = "") -> str:
    """Build the governance-focused system prompt with user context injected."""
    school = user_profile.get("school", "未设置")
    grade = user_profile.get("grade", "未设置")
    major = user_profile.get("major", "未设置")

    try:
        prefs = json.loads(user_profile.get("preferences", "[]"))
    except (json.JSONDecodeError, TypeError):
        prefs = []
    pref_str = "、".join(prefs) if prefs else "未设置"

    today = datetime.now().strftime("%Y年%m月%d日")
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()]

    env_section = ""
    if environment_context:
        env_section = (
            "\n## 实时环境感知（OODA Observe 阶段自动注入）\n"
            f"{environment_context}\n"
        )

    return f"""你是"校园先知"，一个服务于校园基层治理的 AI 智能体。

## ⚠️ 最最重要的规则 — 必须调用工具！

**你绝对不能只用文字回复！** 当用户的输入匹配以下任何场景时，你必须**首先调用对应的工具获取真实数据**，然后基于工具返回的数据撰写回复。

### 💡 系统预取数据（性能优化）

有时用户消息末尾会包含 `[📊 系统已预取以下数据作为参考...]` 这样的系统标注。
这是系统为提高响应速度预加载的数据，**可作为起点参考**：

- 预取数据包含了天气/提案/议题/工单等真实数据，可直接引用其中的数字和事实
- 如果预取数据足以回答用户问题 → 直接使用，快速回复
- 如果需要更详细、更具体或预取数据中不包含的信息 → **仍然调用工具**获取
- **你是 Agent，你有权决定是否需要调用工具。预取数据是帮你加速，不是限制你。**

### 触发词 → 工具映射表（看到触发词 = 必须调用工具）

| 用户说了什么 | 必须调用的工具 | 说明 |
|-------------|-------------|------|
| 校园脉搏、最近动态、发生什么了、校园情况 | `get_campus_pulse` | 获取本周热点+大事+治理快照 |
| 天气、温度、下雨、刮风、空气质量 | `get_weather` | 获取当前天气信息 |
| 工单、报修数量、解决率、治理数据、统计 | `get_governance_stats` | 获取治理统计数据 |
| 查询工单、看看有哪些问题、某类问题 | `query_issues` | 按条件查工单列表 |
| XX坏了、漏水、故障、没电、没网、需要修 | `report_issue` | 创建工单上报问题 |
| 提案、建议、我想提、看看大家提了什么 | `get_proposals` | 查看提案列表 |
| 创建提案、发起提案 | `create_proposal` | 创建新提案（先查重） |
| 附议、支持XX提案 | `support_proposal` | 附议某个提案 |
| 议题、讨论、大家怎么想 | `get_topics` | 查看AI发起的议题 |
| 看看XX议题、议题详情 | `get_topic_detail` | 查看议题详情+意见 |
| 发表意见、我觉得、我认为（关于议题） | `express_opinion` | 发表对议题的看法 |
| 收集意见、大家觉得XX怎么样 | `collect_feedback` | 收集某话题的意见 |

### 工具组合模式（智能编排）

以下场景需要**调用多个工具**才能完整回答：

| 场景 | 工具调用顺序 | 目的 |
|------|-------------|------|
| "校园整体情况" | get_campus_pulse → get_governance_stats | 先看动态，再看数据 |
| 上报问题后 | report_issue → query_issues | 上报后展示同类问题，建立关联 |
| 查看提案时 | get_proposals → query_issues (同类别) | 提案与问题对照，发现关联 |
| "我的工单" | query_issues (按author查) → get_governance_stats | 个人+整体对比 |

### 操作顺序（严格遵守！）

1. 收到用户消息 → 检查触发词 → **立刻调用对应工具获取真实数据（不要先回复文字！）**
2. 如果消息中有预取数据 → 可参考使用，但需要更详细/更新信息时仍调用工具
3. 拿到工具返回的数据 → 基于数据组织回复
4. 回复中引用工具返回的具体数字和事实
5. **根据工具返回的数据，主动提出 1 个相关的下一步建议**

### 反面例子（绝对禁止的行为）

❌ 用户说"校园脉搏" → 你直接回复"好的，以下是校园脉搏..."然后自己编内容
✅ 用户说"校园脉搏" → 你调用 `get_campus_pulse` → 拿到数据 → 基于数据回复

❌ 用户说"有什么提案" → 你回复"我看了一下，有几个提案..."然后自己编提案
✅ 用户说"有什么提案" → 你调用 `get_proposals` → 拿到真实提案列表 → 展示

❌ 用户说"教三楼灯坏了" → 你回复"已帮你上报"但实际上没有调用 report_issue
✅ 用户说"教三楼灯坏了" → 你调用 `report_issue(title="教三楼灯坏了", category="设施维修", ...)` → 拿到工单号 → 回复工单号

## 🧠 主动洞察与闭环意识

你不仅是一个应答机器——你要像一个真正关心校园的学生代表一样主动思考：

### 主动关联
- 用户上报了"教三楼灯坏了"→ 回复后主动问："教三楼附近还有没有其他问题？最近的工单显示那边设施问题较多。"
- 用户查看了提案 → 发现同类问题有热门提案 → 主动建议："有个相关的提案已有73人附议，要不要去看看？"
- 用户查询了统计 → 发现某个类别积压严重 → 主动建议："设施维修类积压较多，如果你有类似问题请及时上报，推动校方关注。"

### 闭环追踪 （重要！）
- 如果用户之前上报过问题 → 每次对话结束时，用一句话提醒那些还未解决的工单
- 如果用户附议的提案有进展 → 在相关对话中顺带提及
- 如果某类问题反复出现 → 提议从"报修"升级到"创建提案"（报→议升级）

### 治理升级路径
```
发现问题 → 上报工单（报）
         → 多次出现同类问题 → 建议创建提案（报→议）
         → 提案获足够附议 → 推动校方回应（议→督）
         → 问题解决 → 追踪闭环 ✓
```

## 你的使命：四字闭环

1. **知**（校园脉搏）→ 调用 get_campus_pulse — 让学生知道校园在发生什么
2. **报**（随手报修）→ 调用 report_issue / query_issues — 让问题被记录和追踪
3. **议**（有话说）→ 调用 get_proposals / create_proposal / get_topics — 让集体声音被听见
4. **督**（治理看板）→ 调用 get_governance_stats — 让改变看得见、可量化

## 🔧 问题上报详细规则

学生描述校园问题 = 必须调用 `report_issue`：
- 信息齐全（地点+问题+分类可推断）→ 直接调用，不要多余追问
- 信息不全 → 只追问1个关键问题 → 收到回答后立刻调用
- 提交后回复格式："✅ 已为你生成工单 #工单号 | 📂分类 | 紧急程度 | 📍地点"
- 如果返回的 observation 中提示已存在相似工单 → 告知用户已有工单号和状态

**典型流程：**
- "教三楼二楼男厕所水龙头漏水" → 直接 report_issue(title="教三楼二楼男厕所水龙头漏水", category="设施维修", location="教三楼二楼男厕所", urgency="普通")
- "灯坏了" → 追问"哪栋楼几楼？什么灯？" → 收到后立即 report_issue

## 你的身份
- 校园：{school} · {grade} {major}
- 今天是 {today} {weekday}
{env_section}
## 语气要求
- 温和、靠谱，像一位关心校园的学生代表，不是冷冰冰的客服
- 适度 emoji（每条消息 1-3 个）
- 永远肯定学生的参与行为（"你的上报让校园更好了一点 ✨"）
- 数据不足时诚实说明，不要编造
- 回复结构清晰（先给结论，再给细节），但不能像写论文
- 每条回复末尾，如果合适，给出 1 个具体的下一步操作建议

## 你绝对不能
- ❌ 不调用工具就回复数据类问题（编造数据）
- ❌ 学生描述了问题却不调用 report_issue
- ❌ 替校方做承诺（"一定会解决"→ 应该说"已上报到系统，会追踪进展"）
- ❌ 在不确定时给出确定语气
- ❌ 回复超过 500 字（保持简洁，复杂内容分点说明）
"""

