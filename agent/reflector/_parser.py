# agent/reflector/_parser.py
"""步骤解析、文本动作兜底解析、闲聊输入闸门。

从单文件的 reflector.py 拆出来的——这些"整形"工具把
LangChain 的原始 intermediate_steps（或没正式调工具时的原始文本）
转成结构化的推理步骤。
"""
import re

# 常量

_STOP_WORDS: set[str] = {
    "了", "的", "是", "我", "要", "有", "在", "不", "和", "都",
    "一", "个", "上", "也", "很", "到", "说", "去", "你", "会",
    "着", "没有", "看", "好", "自己", "这",
}

_PHASE_ICONS = {
    "observe": "🔍", "orient": "⚡", "decide": "🗳️", "act": "🔧", "reflect": "🌤️",
}

# 遇空格、中文标点、换行就停的 token
_TK = r"[^\s，。；！？\n]+"

_TEXT_ACTION_PATTERNS: list[tuple[str, str, str]] = [
    # (正则, 图标, 阶段)
    # 顺序很重要：具体的模式放前面，防止被宽泛模式抢走
    (rf"已(为你|为你)?生成工单\s*[#＃]?\s*{_TK}", "⚡", "act"),
    (rf"工单\s*[#＃]\s*{_TK}", "⚡", "act"),
    (r"(上报|报修|创建).{0,10}(工单|问题)", "⚡", "act"),
    (r"(已上报|已报修|已提交)", "⚡", "act"),
    (r"(查询|正在查|检索).{0,10}(工单|问题|数据|提案|议题|报修)", "🔍", "observe"),
    (r"社区脉搏", "🌊", "observe"),
    (r"治理(统计|数据|快照|健康)", "📊", "observe"),
    (r"天气", "🌤️", "observe"),
    (r"(创建|发起).{0,10}(提案|议题)", "🗳️", "act"),
    (r"(附议|支持).{0,10}提案", "🗳️", "act"),
    (r"(\d+)人附议", "🗳️", "observe"),
    (r"已采纳|已实施|已回应", "✅", "act"),
]

# 这些消息不值得为关联分析跑 10 多条 SQL
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


# 1. 步骤入参归一化

def normalize_tool_input(tool_input) -> dict:
    """把 tool_input 归一成 dict。str、int、None 都行——.get() 用着安全。"""
    if tool_input is None:
        return {}
    if isinstance(tool_input, dict):
        return tool_input
    if isinstance(tool_input, str):
        return {"input": tool_input}
    # 数字、列表等其他类型——包一层好安全展示
    return {"value": tool_input}


# 2. 步骤摘要

def summarize_step(tool_name: str, tool_input: dict) -> str:
    """给一次工具调用生成一行人话中文摘要。

    用按工具名精确匹配的分发表，稳。
    16 个已知工具就是 tools/ 里自动发现的那些。
    """
    ti = tool_input or {}

    handlers = {
        # 报 — issue reporting
        "report_issue": lambda: f"上报诉求：{str(ti.get('title',''))[:30]} → {ti.get('category','')}",
        "query_issues": lambda: f"查询工单：{ti.get('category','') or '全部'} {ti.get('status','') or '全部'}",
        "query_my_issues": lambda: "查询我的工单",
        "query_my_proposals": lambda: "查询我的提案",
        # 知 — observation
        "get_community_pulse": lambda: "获取社区脉搏快照",
        "get_governance_stats": lambda: "查询治理统计数据",
        "get_weather": lambda: "查询天气信息",
        "query_knowledge": lambda: f"语义搜索社区知识：{str(ti.get('query',''))[:30]}",
        "get_community_policy": lambda: f"检索社区规章：{str(ti.get('topic',''))[:30]}",
        # 议 — 提案和讨论
        "create_proposal": lambda: f"创建提案：{str(ti.get('title',''))[:30]}",
        "support_proposal": lambda: f"附议提案 #{ti.get('proposal_id','?')}",
        "get_proposals": lambda: "查询提案列表",
        "get_topics": lambda: "查询讨论议题",
        "get_topic_detail": lambda: f"查看议题 #{ti.get('topic_id','?')} 详情",
        "express_opinion": lambda: "发表议题意见",
        "collect_feedback": lambda: "收集社区意见",
    }

    handler = handlers.get(tool_name)
    if handler:
        return handler()
    return f"调用 {tool_name}"


# 3. 步骤解析

def parse_intermediate_steps(intermediate_steps: list) -> list[dict]:
    """把 LangChain 的 intermediate_steps（list[tuple[AgentAction, str]]）转成结构化步骤。"""
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


# 4. 文本动作解析（兜底）

def parse_text_actions(raw_response: str) -> list[dict]:
    """从 Agent 的文本回复里抠出伪步骤。

    DeepSeek 直接在文字里描述动作（比如"已为你生成工单 #42"）
    而不是正经调 LangChain 工具时，这个解析器把动作捞回来，
    推理链才不会空着。

    返回的步骤字典和 parse_intermediate_steps 输出兼容。
    """
    steps: list[dict] = []
    covered_ranges: list[tuple[int, int]] = []  # 记已覆盖的范围，去重用

    def _has_overlap(start: int, end: int) -> bool:
        for cs, ce in covered_ranges:
            if start < ce and end > cs:  # 区间重叠
                return True
        return False

    for pattern, icon, phase in _TEXT_ACTION_PATTERNS:
        for m in re.finditer(pattern, raw_response):
            start, end = m.start(), m.end()
            if _has_overlap(start, end):
                continue  # 跳过——更高优先级的模式已经盖过了
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

    # 按在文本里的位置排（符合阅读顺序）
    steps.sort(key=lambda s: raw_response.find(s["tool_output"]))
    return steps


# 5. 闲聊输入闸门

def is_trivial_input(user_input: str) -> bool:
    """输入是普通寒暄就返回 True，别触发重的关联分析流程。"""
    cleaned = user_input.strip().lower().rstrip("。！？!?.,，")
    if len(cleaned) <= 2:
        return True
    if cleaned in _TRIVIAL_PATTERNS:
        return True
    # 纯问候句式："你好呀"、"嗨~" 等
    if re.match(
        r"^(你好|您好|hi|hello|嗨|早|谢谢|感谢|thanks|bye|再见|拜拜)[!！~～呀啊哦呢嘛啦喔]*$",
        cleaned,
    ):
        return True
    return False
