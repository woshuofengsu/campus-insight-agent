# agent/enforce.py
"""Anti-hallucination safety net — guarantee report_issue is called for repair intents.

Extracted from CampusAgent._enforce_tool_call(). When the LLM fails to call
report_issue (or calls it but it fails), this module forces a real tool call
using fast keyword-based classification.  The user never sees a hallucinated
"工单 #42" that doesn't actually exist in the database.
"""
import logging

_log = logging.getLogger(__name__)


def enforce_tool_call(response: str, user_input: str,
                      intermediate_steps: list | None = None) -> str:
    """Safety net: guarantee report_issue is called AND succeeds for repair intents.

    Handles TWO failure modes:
    1. LLM didn't call report_issue at all (hallucinated a fake response)
    2. LLM called report_issue but it returned an error (e.g. validate_location
       blocked it) — the LLM may still respond as if it succeeded

    In both cases we force a real, successful tool call.

    Args:
        response: The LLM's raw text response.
        user_input: The original user message.
        intermediate_steps: List of (AgentAction, observation) tuples from the
            LangChain agent executor, or None.

    Returns:
        The original response if everything is fine, or a replacement response
        with the real report_issue result.
    """
    if not intermediate_steps:
        intermediate_steps = []

    # ── Check if report_issue was called AND succeeded ──
    report_called = False
    report_succeeded = False
    for step in intermediate_steps:
        if len(step) >= 2:
            tool = step[0]  # (AgentAction, observation) tuple
            tool_name = getattr(tool, 'tool', '')
            if tool_name == "report_issue":
                report_called = True
                observation = step[1]  # tool return value
                # Check if the tool returned an error
                if not any(observation.startswith(p) for p in ("⚠️", "❌")):
                    report_succeeded = True
                break

    if report_succeeded:
        return response  # Tool was called and succeeded — nothing to do

    # ── Check if user input looks like a problem report ──
    from agent.prompt import detect_persona
    persona = detect_persona(user_input)
    is_repair_intent = bool(persona and "报修助手" in persona.get("role", ""))

    if not is_repair_intent:
        return response

    # ── Force the real tool call ──
    if report_called:
        _log.warning(
            "Safety net: report_issue was called but FAILED. Retrying. "
            "user_input=%r", user_input[:80]
        )
    else:
        _log.warning(
            "Safety net: report_issue NOT called for repair intent. "
            "Enforcing real tool call. user_input=%r, response_preview=%r",
            user_input[:80], response[:80]
        )

    try:
        from tools.action_report_issue import report_issue, _keyword_classify, _keyword_urgency
        from agent.helpers import extract_location

        # Strip prefetch context from title
        clean_input = user_input.split("\n\n[📊")[0].strip()
        title = clean_input[:80]
        location = extract_location(clean_input)

        # Pre-compute category + urgency with fast keyword methods
        # (no LLM API call — instant, and good enough for safety net)
        cat = _keyword_classify(title, clean_input)
        urg = _keyword_urgency(title, clean_input)

        # If location is still empty, try extracting from full user_input
        if not location:
            location = extract_location(user_input)

        result = report_issue.invoke({
            "title": title,
            "category": cat,
            "location": location,
            "description": clean_input,
            "urgency": urg,       # fast path: skips _llm_classify
        })

        # If result is STILL an error, validate_location blocked us.
        # Retry with the full input as location fallback.
        if result.startswith("⚠️") or result.startswith("❌"):
            _log.warning(
                "Safety net retry also blocked by validation. "
                "Falling back with full-input location. error=%r", str(result)[:80]
            )
            result = report_issue.invoke({
                "title": title,
                "category": cat,
                "location": location or clean_input[:60],
                "description": clean_input,
                "urgency": urg,
            })

        _log.info("Safety net: report_issue result=%r", str(result)[:120])
        return str(result)
    except Exception as e:
        _log.error("Safety net report_issue also failed: %s", e)
        # DON'T return the LLM's hallucinated response with a fake ticket number.
        # Give the user an honest error message instead.
        return (
            "很抱歉，自动上报没有成功 😥\n\n"
            "你可以试试页面顶部的「⚡ 快速报修」——它不走 AI，直接写入数据库，"
            "不会出现这种问题。\n\n"
            f"（错误信息：{str(e)[:100]}）"
        )
