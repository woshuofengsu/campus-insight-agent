# agent/reflector/_parser.py
"""Step parsing, text-action fallback parsing, and trivial-input gating.

Extracted from the monolithic reflector.py — these are the "shape" utilities
that convert raw LangChain intermediate_steps (or raw text when no formal
tool calls fired) into structured reasoning steps.
"""
import re

# ── Constants ──

_STOP_WORDS: set[str] = {
    "了", "的", "是", "我", "要", "有", "在", "不", "和", "都",
    "一", "个", "上", "也", "很", "到", "说", "去", "你", "会",
    "着", "没有", "看", "好", "自己", "这",
}

_PHASE_ICONS = {
    "observe": "🔍", "orient": "⚡", "decide": "🗳️", "act": "🔧", "reflect": "🌤️",
}

# Token that stops at spaces, Chinese punctuation, and line breaks
_TK = r"[^\s，。；！？\n]+"

_TEXT_ACTION_PATTERNS: list[tuple[str, str, str]] = [
    # (regex pattern, icon, phase)
    # Order matters: more specific patterns first to prevent sub-pattern shadowing
    (rf"已(为你|为你)?生成工单\s*[#＃]?\s*{_TK}", "⚡", "act"),
    (rf"工单\s*[#＃]\s*{_TK}", "⚡", "act"),
    (r"(上报|报修|创建).{0,10}(工单|问题)", "⚡", "act"),
    (r"(已上报|已报修|已提交)", "⚡", "act"),
    (r"(查询|正在查|检索).{0,10}(工单|问题|数据|提案|议题|报修)", "🔍", "observe"),
    (r"校园脉搏", "🌊", "observe"),
    (r"治理(统计|数据|快照|健康)", "📊", "observe"),
    (r"天气", "🌤️", "observe"),
    (r"(创建|发起).{0,10}(提案|议题)", "🗳️", "act"),
    (r"(附议|支持).{0,10}提案", "🗳️", "act"),
    (r"(\d+)人附议", "🗳️", "observe"),
    (r"已采纳|已实施|已回应", "✅", "act"),
]

# Messages that don't warrant 10+ SQL queries for association analysis
_TRIVIAL_PATTERNS: set[str] = {
    "你好", "您好", "hi", "hello", "嗨", "早", "早上好", "下午好", "晚上好",
    "谢谢", "感谢", "thanks", "thank you", "3q",
    "好的", "嗯", "哦", "行", "可以", "ok", "okay", "好滴", "好",
    "哈哈", "嘿嘿", "呵呵", "嘻嘻", "lol",
    "再见", "拜拜", "bye", "88", "回头见", "改天聊",
    "在吗", "在不在", "有人吗", "在不",
    "没事", "没什么", "没啥", "随便看看", "逛逛",
    "你是谁", "你叫什么", "介绍一下", "介绍一下你自己",
}


# -- 1. Step normalisation

def normalize_tool_input(tool_input) -> dict:
    """Normalize tool_input to a dict. Accepts str, int, None — safe for .get()."""
    if tool_input is None:
        return {}
    if isinstance(tool_input, dict):
        return tool_input
    if isinstance(tool_input, str):
        return {"input": tool_input}
    # Number, list, or other — wrap for safe display
    return {"value": tool_input}


# -- 2. Step summarisation

def summarize_step(tool_name: str, tool_input: dict) -> str:
    """Generate a one-line human-readable Chinese summary of a tool call.

    Uses a dispatch table keyed by exact tool name for robustness.
    The 16 known tools are the ones auto-discovered from tools/.
    """
    ti = tool_input or {}

    handlers = {
        # 报 — issue reporting
        "report_issue": lambda: f"上报问题：{str(ti.get('title',''))[:30]} → {ti.get('category','')}",
        "query_issues": lambda: f"查询工单：{ti.get('category','') or '全部'} {ti.get('status','') or '全部'}",
        "query_my_issues": lambda: "查询我的工单",
        "query_my_proposals": lambda: "查询我的提案",
        # 知 — observation
        "get_campus_pulse": lambda: "获取校园脉搏快照",
        "get_governance_stats": lambda: "查询治理统计数据",
        "get_weather": lambda: "查询天气信息",
        "query_knowledge": lambda: f"语义搜索校园百科：{str(ti.get('query',''))[:30]}",
        "get_school_policy": lambda: f"检索校规政策：{str(ti.get('topic',''))[:30]}",
        # 议 — proposals & discussion
        "create_proposal": lambda: f"创建提案：{str(ti.get('title',''))[:30]}",
        "support_proposal": lambda: f"附议提案 #{ti.get('proposal_id','?')}",
        "get_proposals": lambda: "查询提案列表",
        "get_topics": lambda: "查询讨论议题",
        "get_topic_detail": lambda: f"查看议题 #{ti.get('topic_id','?')} 详情",
        "express_opinion": lambda: "发表议题意见",
        "collect_feedback": lambda: "收集校园意见",
    }

    handler = handlers.get(tool_name)
    if handler:
        return handler()
    return f"调用 {tool_name}"


# -- 3. Step parsing

def parse_intermediate_steps(intermediate_steps: list) -> list[dict]:
    """Convert LangChain intermediate_steps (list[tuple[AgentAction, str]]) to structured steps."""
    if not intermediate_steps:
        return []
    steps: list[dict] = []
    for action, observation in intermediate_steps:
        tool_name = getattr(action, "tool", "unknown")
        tool_input = normalize_tool_input(getattr(action, "tool_input", None))
        obs_raw = str(observation) if observation else ""
        obs_str = obs_raw[:200] + ("..." if len(obs_raw) > 200 else "")
        t = tool_name.lower()
        phase = "observe" if any(k in t for k in ("query", "get_", "pulse", "weather")) else "act"
        steps.append({
            "phase": phase,
            "icon": _PHASE_ICONS.get(phase, "🔧"),
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": obs_str,
            "summary": summarize_step(tool_name, tool_input),
        })
    return steps


# -- 4. Text-action parsing (fallback)

def parse_text_actions(raw_response: str) -> list[dict]:
    """Extract pseudo-steps from the agent's text response.

    When DeepSeek generates action descriptions inline (e.g. "已为你生成工单 #42")
    instead of formally calling tools via LangChain, this parser recovers those
    actions so the reasoning chain isn't empty.

    Returns a list of step dicts compatible with parse_intermediate_steps output.
    """
    steps: list[dict] = []
    covered_ranges: list[tuple[int, int]] = []  # for overlap dedup

    def _has_overlap(start: int, end: int) -> bool:
        for cs, ce in covered_ranges:
            if start < ce and end > cs:  # intervals overlap
                return True
        return False

    for pattern, icon, phase in _TEXT_ACTION_PATTERNS:
        for m in re.finditer(pattern, raw_response):
            start, end = m.start(), m.end()
            if _has_overlap(start, end):
                continue  # skip — already covered by a higher-priority pattern
            covered_ranges.append((start, end))
            match_text = m.group(0)[:60]
            steps.append({
                "phase": phase,
                "icon": icon,
                "tool_name": "",
                "tool_input": {},
                "tool_output": match_text,
                "summary": f"AI 执行：{match_text}",
            })

    # Sort by position in text (natural reading order)
    steps.sort(key=lambda s: raw_response.find(s["tool_output"]))
    return steps


# -- 5. Trivial-input gate

def is_trivial_input(user_input: str) -> bool:
    """Return True if the input is generic small-talk that shouldn't trigger
    the heavy association analysis pipeline."""
    cleaned = user_input.strip().lower().rstrip("。！？!?.,，")
    if len(cleaned) <= 2:
        return True
    if cleaned in _TRIVIAL_PATTERNS:
        return True
    # Greeting-only pattern: "你好呀", "嗨~", etc.
    if re.match(
        r"^(你好|您好|hi|hello|嗨|早|谢谢|感谢|thanks|bye|再见|拜拜)[!！~～呀啊哦呢嘛啦喔]*$",
        cleaned,
    ):
        return True
    return False
