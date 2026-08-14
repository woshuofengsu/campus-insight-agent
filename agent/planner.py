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

# 规则模板 → 具体工具调用序列（Plan-and-Execute 真循环用）
_RULE_TOOL_PLANS: list[tuple[tuple[str, ...], list[tuple[str, dict]]]] = [
    (("统计", "提案"), [("get_governance_stats", {}), ("get_proposals", {})]),
    (("社区脉搏", "天气"), [("get_community_pulse", {}), ("get_weather", {})]),
    (("提案", "工单"), [("get_proposals", {}), ("query_issues", {"limit": 10})]),
]


def _match_tool_plan(text: str) -> list[tuple[str, dict]] | None:
    """Return the tool-call plan for a rule-template-matched composite query."""
    for kws, plan in _RULE_TOOL_PLANS:
        if all(kw in text for kw in kws):
            return plan
    return None


def execute_plan_steps(text: str) -> list[dict] | None:
    """真正执行计划：对规则模板覆盖的复合查询，逐步调用真实工具并收集观察。

    返回 [{"tool": 工具名, "observation": 结果}, ...]；非模板查询返回 None。
    这是 Plan-and-Execute 的「执行」半环，结果交给 LLM 汇总。
    """
    plan = _match_tool_plan(text)
    if not plan:
        return None
    try:
        from tools import discover_tools
        tools = {t.name: t for t in discover_tools()}
    except Exception:
        _log.warning("discover_tools failed in execute_plan_steps", exc_info=True)
        return None

    results: list[dict] = []
    for tool_name, kwargs in plan:
        tool = tools.get(tool_name)
        if not tool:
            continue
        try:
            obs = tool.invoke(kwargs)
            results.append({"tool": tool_name, "observation": str(obs)})
        except Exception as e:
            _log.warning("plan step %s failed: %s", tool_name, e)
            results.append({"tool": tool_name, "observation": f"[{tool_name} 调用失败: {e}]"})
    return results or None


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
