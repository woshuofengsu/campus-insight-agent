# agent/router.py
"""意图 → 工具 语义路由（LLM 主决策 + 关键词快路径/兜底）。

V3 重构：把「用户该调哪个工具」的决策权交还给 LLM——
- 明确查询类（社区脉搏/天气/我的工单…）走关键词快路径，省一次 LLM 调用；
- 动作类/歧义类（上报/提案/长文本）走 LLM 结构化判断（含澄清机制）；
- LLM 不可用/超时时回退关键词表（护栏，不抢主决策）。
"""
import json
import logging
import re

_log = logging.getLogger(__name__)

# 可被路由的工具（与 tools/ 实际注册名一致）
VALID_TOOLS = {
    "report_issue", "get_community_pulse", "get_weather", "get_governance_stats",
    "query_issues", "query_my_issues", "get_proposals", "create_proposal",
    "get_topics", "get_topic_detail", "express_opinion", "collect_feedback",
    "support_proposal", "query_knowledge",
}

# 快路径工具：明确、几乎无歧义的查询类意图（命中即跳过 LLM，零延迟）
_FAST_PATH_TOOLS = {
    "get_community_pulse", "get_weather", "query_my_issues",
    "get_proposals", "get_topics", "get_governance_stats", "query_knowledge",
}

# 关键词兜底表（顺序即优先级：强意图在前，report_issue 最宽泛放最后）
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
    """关键词兜底路由。返回 (tool, confidence)。"""
    for tool, kws in _TOOL_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                return tool, "high"
    return None, "low"


def _llm_route_structured(text: str) -> dict | None:
    """LLM 结构化语义路由（主决策），输出 JSON 含澄清机制。"""
    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        if not DEEPSEEK_API_KEY:
            return None
        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL, temperature=0, max_tokens=160, timeout=5, max_retries=0,
        )
        tool_list = "、".join(sorted(VALID_TOOLS))
        prompt = (
            "你是社区治理助手的意图路由器。判断用户这句话的意图，输出 JSON。\n"
            f"可选工具：{tool_list}\n"
            "规则：\n"
            "1. tool 填最合适的工具名；实在无法判断填 null。\n"
            "2. confidence 填 0~1 的小数（你的把握）。\n"
            "3. 若信息不足、需要追问澄清，needs_clarification 填 true 并给出 question；否则 false。\n"
            "只输出 JSON，不要任何解释：\n"
            '{"tool": "...", "confidence": 0.9, "needs_clarification": false, "question": ""}\n'
            f"用户：{text[:160]}\n"
        )
        resp = llm.invoke(prompt)
        content = getattr(resp, "content", "") or ""
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        tool = data.get("tool")
        if tool and tool in VALID_TOOLS:
            try:
                conf_val = float(data.get("confidence", 0))
            except (TypeError, ValueError):
                conf_val = 0.5
            return {
                "tool": tool,
                "confidence": "high" if conf_val >= 0.7 else "medium",
                "method": "llm",
                "needs_clarification": bool(data.get("needs_clarification", False)),
                "question": (data.get("question") or "").strip(),
            }
    except Exception:
        _log.debug("LLM structured routing failed, falling back", exc_info=True)
    return None


def route_intent(text: str) -> dict:
    """路由用户意图到建议工具。

    Returns {"tool", "confidence", "method", "needs_clarification", "question"}
    """
    tool, conf = _keyword_route(text)

    # 快路径：明确查询类意图，跳过 LLM（零延迟）
    if tool in _FAST_PATH_TOOLS:
        return {"tool": tool, "confidence": "high", "method": "keyword_fast",
                "needs_clarification": False, "question": ""}

    # 主决策：LLM 语义路由
    llm_result = _llm_route_structured(text)
    if llm_result:
        return llm_result

    # 护栏：LLM 不可用/低置信 → 关键词兜底
    if tool:
        return {"tool": tool, "confidence": conf, "method": "keyword_fallback",
                "needs_clarification": False, "question": ""}

    return {"tool": None, "confidence": "low", "method": "none",
            "needs_clarification": True, "question": "能再具体说说是哪方面的问题吗？"}
