# agent/planner.py
"""Plan-and-Execute 规划器（轻量）——为复杂多意图查询生成步骤计划。

不替换 LangChain AgentExecutor（三层回退保底层不变），而是在 ORIENT 阶段注入
「建议步骤」，引导主 Agent 按计划逐步调用工具；LLM 不可用时回退规则模板。
"""
import logging

_log = logging.getLogger(__name__)

# 常见复合查询的规则步骤模板（LLM 兜底）
_RULE_PLANS: list[tuple[tuple[str, ...], list[str]]] = [
    (("统计", "提案"), ["查询治理统计", "查询提案列表", "对比并给出结论"]),
    (("社区脉搏", "天气"), ["查询社区脉搏", "查询天气", "汇总本周动态与天气建议"]),
    (("上报", "同类"), ["上报诉求", "查询同类工单", "告知相似工单与进展"]),
    (("提案", "工单"), ["查询相关提案", "查询同类别工单", "对照提案与诉求"]),
]


def _count_intents(text: str) -> int:
    """Estimate how many distinct tool intents a single message carries."""
    from agent.router import _TOOL_KEYWORDS
    hits = set()
    for tool, kws in _TOOL_KEYWORDS.items():
        if any(kw in text for kw in kws):
            hits.add(tool)
    return len(hits)


def _llm_plan(text: str) -> list[str] | None:
    """LLM 生成步骤计划（best-effort）。"""
    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        if not DEEPSEEK_API_KEY:
            return None
        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL, temperature=0, max_tokens=120, timeout=4, max_retries=0,
        )
        prompt = (
            "把用户这条社区治理请求拆成 2-4 个执行步骤（调用工具的顺序）。"
            "每行一个步骤，不要编号、不要解释，每步以动词开头。\n"
            f"用户请求：{text[:160]}\n"
        )
        resp = llm.invoke(prompt)
        lines = [ln.strip().lstrip("0123456789.-•·) ").strip()
                 for ln in (getattr(resp, "content", "") or "").splitlines()]
        steps = [ln for ln in lines if ln]
        return steps[:4] if steps else None
    except Exception:
        _log.debug("LLM planning failed, falling back", exc_info=True)
        return None


def plan_steps(text: str) -> list[str] | None:
    """Return an ordered step plan for a complex query; None if single-intent.

    Deterministic rule templates fire first (fast + testable); LLM planning
    kicks in for multi-intent messages not covered by a template.
    """
    for kws, steps in _RULE_PLANS:
        if all(kw in text for kw in kws):
            return steps

    if _count_intents(text) >= 2:
        return _llm_plan(text) or ["先查询相关数据", "再调用对应工具", "最后汇总结论"]

    return None
