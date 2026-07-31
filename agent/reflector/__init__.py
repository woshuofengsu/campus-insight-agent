# agent/reflector/__init__.py
"""Post-response association reasoning engine ("反射器").

Package structure (split from a 1024-line monolith):
  __init__.py      — Public API + backward-compat re-exports
  _parser.py       — Step parsing, text-action fallback, trivial-input gate
  _associations.py — SQL-heavy association computation, proactive insights
  _insight.py      — LLM-powered natural-language insight generation
"""
import logging

from agent.reflector._parser import (
    parse_intermediate_steps,
    normalize_tool_input,
    summarize_step,
    parse_text_actions,
    is_trivial_input,
    _TEXT_ACTION_PATTERNS,
)
from agent.reflector._associations import (
    compute_associations,
    get_proactive_insights,
    _cross_time_comparison,
    _z_score_anomalies,
    _detect_upgrade_paths,
)
from agent.reflector._insight import (
    build_insight_text,
    _build_insight_prompt,
    _generate_llm_insight,
)
from config import DB_PATH

_logger = logging.getLogger("agent.reflector")

# ── Backward-compat aliases (old code used underscore-prefixed names) ──
_normalize_tool_input = normalize_tool_input
_summarize_step = summarize_step
_parse_text_actions = parse_text_actions


# ═══════════════════════ 1. Response enrichment ═══════════════════════

def enrich_response(raw_response: str, associations: dict) -> str:
    """Append association insights to the agent's response if meaningful.

    Only skips when the response already contains our exact insight header
    (prevents double-appending on re-processing).
    """
    if not associations.get("has_insight"):
        return raw_response or ""
    insight = associations.get("insight_text", "")
    if not insight:
        return raw_response or ""
    if "智能关联分析" in (raw_response or ""):
        return raw_response or ""
    return (
        f"{raw_response}\n\n---\n\n"
        f"💡 **智能关联分析**（AI 自动发现）：\n\n{insight}"
    )


# ═══════════════════════ 2. Main entry point ═══════════════════════

def build_reasoning_chain(
    intermediate_steps: list, raw_response: str, user_input: str,
) -> dict:
    """Main entry point: parse steps, compute associations, enrich response.

    Strategy:
    1. Try LangChain intermediate_steps (formal tool calls) first.
    2. If empty, fall back to text-action parsing (pattern-matching in response).
    3. Append a final "reflect" step for the agent's text answer.
    4. Skip heavy SQL if input is trivial small-talk.
    """
    raw, ui = raw_response or "", user_input or ""
    steps = parse_intermediate_steps(intermediate_steps)

    # Fallback: if no formal tool calls captured, parse the text response
    if not steps and raw.strip():
        steps = parse_text_actions(raw)

    # Append a final step for the agent's text response (the "reflect" phase)
    if raw.strip():
        steps.append({
            "phase": "reflect",
            "icon": "💬",
            "tool_name": "",
            "tool_input": {},
            "tool_output": raw[:200] + ("..." if len(raw) > 200 else ""),
            "summary": f"生成回复（{len(raw)} 字）",
        })

    # ── Trivial-input gate: skip heavy association analysis for small-talk ──
    if is_trivial_input(ui) and not intermediate_steps:
        return {
            "steps": steps,
            "associations": {"has_insight": False},
            "raw_response": raw,
            "enriched_response": raw,
        }

    assoc = compute_associations(ui, steps, DB_PATH)
    # Populate insight_text after association computation
    if assoc.get("has_insight"):
        assoc["insight_text"] = build_insight_text(assoc, user_input=ui)

    return {
        "steps": steps,
        "associations": assoc,
        "raw_response": raw,
        "enriched_response": enrich_response(raw, assoc),
    }
