# agent/enforce.py
"""Safety net: enforce report_issue tool call when LLM hallucinates a response.

When the LLM describes taking an action (e.g. "已生成工单 #42") without
actually calling the tool, this module forces a real report_issue call using
keyword-based classification so the database stays consistent.
"""
import logging

_log = logging.getLogger(__name__)


# ── 幻觉工单检测：LLM 回复是否声称"已生成/已上报"工单 ──
_CLAIMED_REPORT_MARKERS = (
    "已上报", "已生成工单", "已创建工单", "已为你生成", "已帮你上报",
    "上报成功", "工单编号",
)


def _claimed_report(response: str) -> bool:
    """检测 LLM 回复是否声称创建了工单（幻觉工单号）。"""
    return any(m in response for m in _CLAIMED_REPORT_MARKERS)


def enforce_tool_call(response: str, user_input: str,
                      intermediate_steps: list | None = None) -> str:
    """Force a real report_issue call when LLM hallucinates or the tool fails.

    Covers two failure modes: LLM skipped the tool entirely (hallucinated
    reply), or called it but the call failed (e.g. location validation).
    Returns original response if all checks pass, or a replacement response
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

    # ── 修复"假工单"：只在两种情况下兜底 ──
    # 1. report_issue 被调用但失败（report_called=True）→ 重试
    # 2. LLM 声称已上报但没调工具（幻觉工单号）→ 补真实上报
    # 之前仅凭 detect_persona 判"用户输入像上报"就兜底，会把 LLM 的正常追问
    # （"哪栋楼？"）和咨询（"充电桩怎么收费？"）误判成幻觉，强制生成假工单。
    if not report_called and not _claimed_report(response):
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
