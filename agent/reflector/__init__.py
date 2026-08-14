# agent/reflector/__init__.py
"""回复后的关联推理引擎（"反射器"）。

从原来 1024 行的单文件拆出来的包：
  __init__.py      — 对外 API + 兼容旧名的再导出
  _parser.py       — 步骤解析、文本动作兜底、闲聊输入闸门
  _associations.py — 重 SQL 的关联计算、主动洞察
  _insight.py      — LLM 生成自然语言的洞察
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

# 兼容旧名字的别名（老代码用的带下划线的名字）
_normalize_tool_input = normalize_tool_input
_summarize_step = summarize_step
_parse_text_actions = parse_text_actions


# 1. 回复增强

def enrich_response(raw_response: str, associations: dict) -> str:
    """有意义的关联洞察就追加到 Agent 回复后面。

    回复里已经带我们的洞察标题就跳过（防止重复处理时加两遍）。
    """
    if not associations.get("has_insight"):
        return raw_response or ""
    insight = associations.get("insight_text", "")
    if not insight:
        return raw_response or ""
    if "关联分析" in (raw_response or ""):
        return raw_response or ""
    return (
        f"{raw_response}\n\n---\n\n"
        f"💡 **关联分析**：\n\n{insight}"
    )


# 2. 主入口

def build_reasoning_chain(
    intermediate_steps: list, raw_response: str, user_input: str,
) -> dict:
    """主入口：解析步骤、算关联、增强回复。

    策略：
    1. 先试 LangChain 的 intermediate_steps（正式工具调用）。
    2. 为空就退回文本动作解析（在回复里做模式匹配）。
    3. 最后补一个"反思"步骤放 Agent 的文字回答。
    4. 输入是闲聊的话跳过重的 SQL。
    """
    raw, ui = raw_response or "", user_input or ""
    steps = parse_intermediate_steps(intermediate_steps)

    # 兜底：没抓到正式工具调用，就从文本回复里解析
    if not steps and raw.strip():
        steps = parse_text_actions(raw)

    # 补最后一步：Agent 的文字回复（"反思"阶段）
    if raw.strip():
        steps.append({
            "phase": "reflect",
            "icon": "💬",
            "tool_name": "",
            "tool_input": {},
            "tool_output": raw[:200] + ("..." if len(raw) > 200 else ""),
            "summary": f"生成回复（{len(raw)} 字）",
        })

    # 闲聊闸门：小打小闹的输入不跑重的关联分析
    if is_trivial_input(ui) and not intermediate_steps:
        return {
            "steps": steps,
            "associations": {"has_insight": False},
            "raw_response": raw,
            "enriched_response": raw,
        }

    assoc = compute_associations(ui, steps, DB_PATH)
    # 关联算完再填 insight_text
    if assoc.get("has_insight"):
        assoc["insight_text"] = build_insight_text(assoc, user_input=ui)

    return {
        "steps": steps,
        "associations": assoc,
        "raw_response": raw,
        "enriched_response": enrich_response(raw, assoc),
    }
