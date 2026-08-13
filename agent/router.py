# agent/router.py
"""意图 → 工具 语义路由（规则关键词 + LLM 语义兜底 + 置信度阈值）。

把「用户该调哪个工具」从提示词里的穷举触发词，升级为可扩展的语义路由：
常见意图走规则（零延迟），未见表述走 LLM 语义（覆盖长尾），失败回退关键词/不干预。
结果注入 ORIENT 阶段作为「本轮建议工具」，帮助主 Agent 更准地调用工具。
"""
import logging

_log = logging.getLogger(__name__)

# 可被路由的工具（与 tools/ 实际注册名一致）
VALID_TOOLS = {
    "report_issue", "get_community_pulse", "get_weather", "get_governance_stats",
    "query_issues", "query_my_issues", "get_proposals", "create_proposal",
    "get_topics", "get_topic_detail", "express_opinion", "collect_feedback",
    "support_proposal", "query_knowledge",
}

# 规则关键词表（覆盖常见说法；未见表述交给 LLM 语义层）。
# 顺序即优先级：强动作意图在前，report_issue（最宽泛）放最后做兜底，
# 避免「充电桩」这种词把「我建议加装充电桩」误判成上报。
_TOOL_KEYWORDS: dict[str, list[str]] = {
    "get_weather": ["天气", "温度", "下雨", "刮风", "空气质量", "冷不冷", "热不热"],
    "get_community_pulse": ["社区脉搏", "最近发生", "动态", "热点", "大事", "情况怎么样", "有什么新", "新鲜事", "有啥事"],
    "query_my_issues": ["我的工单", "我上报", "我的报修", "进展", "处理好了吗", "修好了吗", "我的诉求"],
    "create_proposal": ["我建议", "我想提", "能不能", "希望", "加装", "增设", "推行", "建一个", "建议修", "提议"],
    "query_issues": ["工单", "报修列表", "诉求列表", "有哪些问题", "设施维修类", "哪类", "清单"],
    "get_proposals": ["提案列表", "大家提了什么", "有哪些提案", "看看提案"],
    "get_topics": ["议题", "讨论", "大家怎么想", "议事"],
    "get_governance_stats": ["统计", "数据", "解决率", "占比", "多少件", "治理看板"],
    "query_knowledge": ["政策", "指南", "电话", "流程", "怎么办理", "咨询"],
    "report_issue": [
        "坏了", "漏水", "故障", "不亮", "停水", "停电", "电梯", "堵塞", "异味",
        "扰民", "堆物", "损坏", "失灵", "异响", "滴水", "飞线", "路灯",
        "门禁", "监控", "报修", "漏电", "年检", "塌", "反味", "天花板", "墙面",
        "忽闪", "忽明忽暗", "坑", "凹陷", "渗水", "脱皮", "鼓包", "地锁",
        "井盖", "一直叫", "吵", "拧不紧", "水龙头", "装修", "松动", "吱吱响",
    ],
}


def _keyword_route(text: str) -> tuple[str | None, str]:
    """规则关键词路由。返回 (tool, confidence)。按表顺序匹配（强意图优先）。"""
    for tool, kws in _TOOL_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return tool, "high"
    return None, "low"


def _llm_route(text: str) -> str | None:
    """LLM 语义路由（best-effort，仅在规则低置信度时调用）。"""
    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        if not DEEPSEEK_API_KEY:
            return None
        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL, temperature=0, max_tokens=20, timeout=4, max_retries=0,
        )
        tool_list = "、".join(sorted(VALID_TOOLS))
        prompt = (
            "你是社区治理助手的意图路由器。判断用户这句话最可能调用哪个工具。\n"
            f"可选工具：{tool_list}\n"
            f"用户：{text[:120]}\n"
            "只返回一个工具名，不要解释；若都不匹配返回 none。"
        )
        resp = llm.invoke(prompt)
        tool = (getattr(resp, "content", "") or "").strip().lower()
        if tool in VALID_TOOLS:
            return tool
    except Exception:
        _log.debug("LLM semantic routing failed, falling back to none", exc_info=True)
    return None


def route_intent(text: str) -> dict:
    """路由用户意图到建议工具。

    Returns {"tool": str|None, "confidence": high/medium/low, "method": keyword/llm/none}
    """
    tool, conf = _keyword_route(text)
    if tool:
        return {"tool": tool, "confidence": conf, "method": "keyword"}

    llm_tool = _llm_route(text)
    if llm_tool:
        return {"tool": llm_tool, "confidence": "medium", "method": "llm"}

    return {"tool": None, "confidence": "low", "method": "none"}
