# agent/reflection.py
"""反思层 v2 — LLM 事实核查（编号 + 数值 + 语义一致性）。

与 enforce_tool_call 互补：enforce 管「该调的工具调没调」，这里管「答得对不对」。
- 正则查 `#编号` 存在性 = 护栏（零成本、零延迟）；
- LLM 核查 = 主防线（仅当回复含数字/编号且有工具结果时触发，控制成本）。
"""
import logging
import re

from agent.verifier import verify_facts

_log = logging.getLogger(__name__)

_HAS_FACT_RE = re.compile(r"#\d+|\d+")


def reflect(response: str, intermediate_steps: list | None = None) -> str:
    """事实核查反思：编号存在性（护栏）+ 数值硬校验 + LLM 数值/语义一致性。"""
    if not response:
        return response

    # 1. 编号存在性（正则护栏）
    response = verify_facts(response)

    # 2. 数值硬校验（DB 计算对比）
    response = _verify_stats_numbers(response)

    # 3. LLM 事实核查
    return _llm_fact_check(response, intermediate_steps)


def _verify_stats_numbers(response: str) -> str:
    """硬校验：回复中「满意率/解决率 X%」与 DB 实际值对比，偏差 >20% 追加提示。"""
    m = re.search(r"(满意率|解决率)[^\d]{0,6}(\d+(?:\.\d+)?)\s*%", response)
    if not m:
        return response
    try:
        claimed = float(m.group(2))
        from data.db_governance import get_satisfaction_stats
        actual = get_satisfaction_stats().get("rate")
        if actual is None:
            return response
        if abs(claimed - actual) > 20:
            note = (
                f"\n\n⚠️ *核对提示：您提到的{m.group(1)}为 {claimed}%，"
                f"系统实际统计为 {actual}%，两者有出入，请以系统数据为准。*"
            )
            return response + note
    except (ValueError, TypeError):
        pass
    return response


def _llm_fact_check(response: str, intermediate_steps: list | None) -> str:
    """LLM 对「回复 vs 工具结果」做一致性核查；不一致则修正。"""
    if not intermediate_steps or not _HAS_FACT_RE.search(response):
        return response

    observations = []
    for step in intermediate_steps:
        if len(step) >= 2:
            obs = str(step[1])
            observations.append(obs[:400] if len(obs) > 400 else obs)
    if not observations:
        return response

    try:
        from langchain_openai import ChatOpenAI
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
        if not DEEPSEEK_API_KEY:
            return response
        llm = ChatOpenAI(
            api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL,
            model=DEEPSEEK_MODEL, temperature=0, max_tokens=400, timeout=6, max_retries=0,
        )
        facts = "\n".join(f"- {o}" for o in observations)
        prompt = (
            "你是社区治理助手的事实核查员。下面是工具返回的真实数据，和助手据此生成的回复。\n"
            "判断助手回复中的数字、编号、结论是否与真实数据一致。\n"
            "若有不一致或编造，输出修正后的完整回复；若一致，原样输出回复。\n"
            "只输出最终回复文本，不要解释、不要加任何前缀。\n\n"
            f"真实数据：\n{facts}\n\n"
            f"助手回复：\n{response}\n"
        )
        resp = llm.invoke(prompt)
        content = (getattr(resp, "content", "") or "").strip()
        if content:
            _log.info("reflection: LLM fact-check returned %d chars", len(content))
            return content
    except Exception:
        _log.debug("LLM fact-check failed, returning original", exc_info=True)
    return response
