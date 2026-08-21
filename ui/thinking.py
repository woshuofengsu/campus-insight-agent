# ui/thinking.py
"""Agent 推理链可视化 — 渲染 OODA 步骤和关联发现。

聊天页（home.py）每次 agent 跑完一轮后调用。数据有两种形态：
结构化（list[dict] 的 steps + associations）或兜底（DeepSeek <think>
标签里的原始 thinking_text）。

渲染全部走内联 CSS 和 ui.components 的 TOKEN 设计系统。
"""

import html as _html
import json
import streamlit as st
from ui.components import TOKEN
import logging
_log = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """转义用户输入，防止注入和渲染被搞坏。"""
    if not text:
        return ""
    return _html.escape(str(text), quote=False)


PHASE_COLORS = {
    "observe": TOKEN["accent"],
    "act":     TOKEN["warning"],
    "reflect": TOKEN["success"],
    "decide":  TOKEN["accent"],
    "orient":  TOKEN["text_sec"],
}


# 结构化推理链

def render_reasoning_chain(
    steps: list[dict] | None,
    associations: dict | None = None,
) -> None:
    """把 agent 的推理链渲染成一个可展开的组件。

    step 字典字段：phase, icon, tool_name, tool_input, tool_output, summary。
    associations 字典字段：spatial, temporal, recurrence, has_insight, insight_text。
    """
    if not steps:
        return

    n = len(steps)

    # 折叠面板标题用第一步的摘要，太长了截断
    first_summary = _esc(steps[0].get("summary", "")) if steps else ""
    label_summary = first_summary[:28] + ("…" if len(first_summary) > 28 else "")
    with st.expander(
        f"🧠 处理流程 · {n} 步 · {label_summary}",
        expanded=False,
    ):
        for s in steps:
            phase = s.get("phase", "")
            border = PHASE_COLORS.get(phase, TOKEN["border"])
            icon = s.get("icon", "🔹")

            # 工具入参转 JSON 后截断，最多 80 字符
            try:
                inp = json.dumps(s.get("tool_input", {}), ensure_ascii=False)
            except Exception:
                _log.debug("非致命错误", exc_info=True)
                inp = str(s.get("tool_input", ""))
            inp = (inp[:77] + "...") if len(inp) > 80 else inp

            tool_name = _esc(s.get("tool_name", ""))
            tool_output = _esc(s.get("tool_output", ""))
            summary_safe = _esc(s.get("summary", ""))

            # 拼详情行：工具名 · 入参 · 输出
            _tmu = TOKEN["text_muted"]
            _tsec = TOKEN["text_sec"]
            detail_parts = []
            if tool_name:
                detail_parts.append(f'<code style="font-size:0.76em;">{tool_name}</code>')
            if inp and inp != "{}":
                detail_parts.append(f'<span style="color:{_tmu};font-size:0.75em;">📥 {inp}</span>')
            if tool_output:
                out_short = tool_output[:100]
                detail_parts.append(f'<span style="color:{_tsec};font-size:0.75em;">→ {out_short}</span>')

            details = ""
            if detail_parts:
                details = f'<div style="margin-top:3px;">{" &nbsp;".join(detail_parts)}</div>'

            st.markdown(
                f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
                f'border-left:3px solid {border};border-radius:{TOKEN["radius_card"]};'
                f'padding:10px 14px;margin:5px 0;box-shadow:{TOKEN["shadow_sm"]};'
                f'font-size:0.85em;line-height:1.5;transition:background 0.15s ease;"'
                f'onmouseover="this.style.background=\'{TOKEN["page_bg"]}\'" '
                f'onmouseout="this.style.background=\'{TOKEN["card_bg"]}\'">'
                f'<strong style="color:{TOKEN["text"]};font-size:0.85em;">'
                f'{icon} {summary_safe}</strong>'
                f'{details}</div>',
                unsafe_allow_html=True,
            )

        if associations and associations.get("has_insight"):
            insight_text = associations.get("insight_text", "")
            spatial = associations.get("spatial")
            anomalies = associations.get("anomalies", [])
            linked_proposals = associations.get("linked_proposals", [])
            correlations = associations.get("correlations", [])

            anomaly_html = ""
            if anomalies:
                for a in anomalies[:3]:
                    anomaly_html += (
                        f'<span style="display:inline-block;background:{TOKEN["danger_bg"]};'
                        f'border:1px solid {TOKEN["danger_border"]};'
                        f'border-radius:{TOKEN["radius_card"]};padding:5px 10px;'
                        f'margin:3px 4px 3px 0;font-size:0.78em;'
                        f'color:{TOKEN["danger"]};">'
                        f'⚠️ {_esc(a.get("category",""))} 激增 +{a.get("spike","")}'
                        f'</span>'
                    )

            cards_html = ""
            if spatial:
                for item in spatial[:8]:
                    issue_id = item.get("id", "?")
                    title = (item.get("title") or "")[:20]
                    status = item.get("status", "")
                    cards_html += (
                        f'<span style="display:inline-block;background:{TOKEN["card_bg"]};'
                        f'border:1px solid {TOKEN["accent_border"]};'
                        f'border-radius:{TOKEN["radius_card"]};padding:5px 10px;'
                        f'margin:3px 4px 3px 0;font-size:0.78em;'
                        f'color:{TOKEN["text_sec"]};">'
                        f'<strong style="color:{TOKEN["accent"]};">#{issue_id}</strong> '
                        f'{_esc(title)} · <span style="color:{TOKEN["text_muted"]};">{_esc(status)}</span></span>'
                    )

            proposal_html = ""
            if linked_proposals:
                for p in linked_proposals[:3]:
                    proposal_html += (
                        f'<span style="display:inline-block;background:{TOKEN["success_bg"]};'
                        f'border:1px solid {TOKEN["success_border"]};'
                        f'border-radius:{TOKEN["radius_card"]};padding:5px 10px;'
                        f'margin:3px 4px 3px 0;font-size:0.78em;'
                        f'color:{TOKEN["success"]};">'
                        f'💡 #{p.get("id","?")} {_esc((p.get("title") or "")[:22])} '
                        f'· 👍{p.get("supporter_count",0)}'
                        f'</span>'
                    )

            corr_html = ""
            if correlations:
                for c in correlations[:3]:
                    corr_html += (
                        f'<span style="display:inline-block;background:{TOKEN["warning_bg"]};'
                        f'border:1px solid {TOKEN["warning_border"]};'
                        f'border-radius:{TOKEN["radius_card"]};padding:5px 10px;'
                        f'margin:3px 4px 3px 0;font-size:0.78em;'
                        f'color:{TOKEN["warning"]};">'
                        f'🔗 {_esc(c.get("cat_a",""))} ↔ {_esc(c.get("cat_b",""))}'
                        f'</span>'
                    )

            panel_sections = []
            if anomaly_html:
                panel_sections.append(
                    f'<div style="margin-bottom:6px;">'
                    f'<span style="font-size:0.75em;color:{TOKEN["danger"]};font-weight:600;">⚠ 异常检测</span><br>'
                    f'{anomaly_html}</div>'
                )
            if cards_html:
                panel_sections.append(
                    f'<div style="margin-bottom:6px;">'
                    f'<span style="font-size:0.75em;color:{TOKEN["accent"]};font-weight:600;">📍 空间关联</span><br>'
                    f'{cards_html}</div>'
                )
            if corr_html:
                panel_sections.append(
                    f'<div style="margin-bottom:6px;">'
                    f'<span style="font-size:0.75em;color:{TOKEN["warning"]};font-weight:600;">🔗 类别关联</span><br>'
                    f'{corr_html}</div>'
                )
            if proposal_html:
                panel_sections.append(
                    f'<div>'
                    f'<span style="font-size:0.75em;color:{TOKEN["success"]};font-weight:600;">💡 相关提案</span><br>'
                    f'{proposal_html}</div>'
                )

            if panel_sections:
                st.markdown(
                    f'<div style="background:{TOKEN["accent_bg"]};'
                    f'border:1px solid {TOKEN["accent_border"]};'
                    f'border-radius:{TOKEN["radius_card"]};padding:14px 16px 10px;'
                    f'margin:10px 0 4px;box-shadow:{TOKEN["shadow_sm"]};">'
                    f'<div style="font-weight:700;color:{TOKEN["accent"]};'
                    f'font-size:0.9em;margin-bottom:8px;">💡 关联发现</div>'
                    f'{"".join(panel_sections)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # 关联结论单独渲染，好走 markdown
            if insight_text:
                st.markdown(insight_text)

            _render_proactive_suggestions(associations, steps)


# 主动建议引擎

def _render_proactive_suggestions(associations: dict, steps: list[dict]) -> None:
    """根据关联数据生成「你可能想…」的可操作建议。

    看空间聚集、异常、关联提案和工具调用情况，给用户推具体能做的事。
    """
    suggestions: list[dict] = []  # {icon, text, action_hint}

    spatial = associations.get("spatial", [])
    anomalies = associations.get("anomalies", [])
    linked = associations.get("linked_proposals", [])
    recurrence = associations.get("recurrence", [])
    efficiency = associations.get("resolution_efficiency", [])

    # 1. 空间聚集 → 建议去查相关工单
    if len(spatial) >= 2:
        locations = sorted({(r.get("location") or r.get("title", ""))[:12] for r in spatial})
        loc_str = "、".join(locations[:2])
        suggestions.append({
            "icon": "📍", "text": f"{loc_str}附近有 {len(spatial)} 个待处理问题",
            "action_hint": '输入「查看该区域详情」了解更多',
        })

    # 2. 某类激增 → 建议上报或关注
    if anomalies:
        top_anomaly = anomalies[0]
        suggestions.append({
            "icon": "⚠️", "text": f"「{top_anomaly['category']}」问题激增，本周 {top_anomaly['recent']} 件",
            "action_hint": "你可以上报类似问题或查看相关提案",
        })

    # 3. 关联提案 → 建议去附议
    if linked:
        top_prop = linked[0]
        suggestions.append({
            "icon": "👍", "text": f"提案 #{top_prop['id']}「{top_prop['title'][:20]}」正在解决同类问题",
            "action_hint": f'输入「附议提案 {top_prop["id"]}」来支持',
        })

    # 4. 反复出现 → 建议深挖根因
    if recurrence:
        suggestions.append({
            "icon": "🔄", "text": f"发现 {len(recurrence)} 个复发问题，根本原因可能未解决",
            "action_hint": '输入「查看复发问题详情」了解更多',
        })

    # 5. 解决太慢 → 建议推动
    if efficiency:
        worst = efficiency[0]
        if worst.get("avg_days", 0) >= 5:
            suggestions.append({
                "icon": "⏱️", "text": f"「{worst['category']}」平均 {worst['avg_days']} 天解决，效率最低",
                "action_hint": '输入「我想提建议」来推动改善',
            })

    # 6. 看这轮用了哪些工具，给场景化建议
    tool_names = [s.get("tool_name", "") for s in (steps or [])]
    if "report_issue" in tool_names:
        suggestions.append({
            "icon": "📋", "text": "工单已上报，你可以在「我的」页面追踪进度",
            "action_hint": "切到「👤 我的」页面查看",
        })
    if "get_community_pulse" in tool_names:
        suggestions.append({
            "icon": "🔧", "text": "看到社区动态后，有想上报的问题吗？",
            "action_hint": "直接描述问题，我会帮你上报",
        })

    if not suggestions:
        return

    # 渲染成一条干净的建议栏
    items_html = ""
    for sug in suggestions[:4]:
        items_html += (
            f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
            f'border-radius:{TOKEN["radius_card"]};padding:8px 12px;margin:4px 0;'
            f'font-size:0.82em;line-height:1.5;box-shadow:{TOKEN["shadow_sm"]};">'
            f'<span style="font-weight:600;color:{TOKEN["text"]};">'
            f'{sug["icon"]} {sug["text"]}</span>'
            f'<br><span style="color:{TOKEN["text_muted"]};font-size:0.9em;">'
            f'💬 {sug["action_hint"]}</span></div>'
        )

    st.markdown(
        f'<div style="margin:12px 0 4px;">'
        f'<div style="font-size:0.78em;font-weight:700;color:{TOKEN["text_sec"]};'
        f'margin-bottom:4px;">💡 你可能还想...</div>'
        f'{items_html}</div>',
        unsafe_allow_html=True,
    )


# 工具调用进度条（实时）

TOOL_ICONS = {
    "report_issue": "🔧", "query_issues": "🔍", "get_community_pulse": "🌊",
    "get_governance_stats": "📊", "get_weather": "🌤️", "create_proposal": "💡",
    "support_proposal": "👍", "get_proposals": "📋", "get_topics": "🗣️",
    "get_topic_detail": "📖", "express_opinion": "💬", "collect_feedback": "📥",
}

TOOL_LABELS = {
    "report_issue": "上报问题", "query_issues": "查询工单", "get_community_pulse": "社区脉搏",
    "get_governance_stats": "治理统计", "get_weather": "天气查询", "create_proposal": "创建提案",
    "support_proposal": "附议提案", "get_proposals": "查询提案", "get_topics": "查询议题",
    "get_topic_detail": "议题详情", "express_opinion": "发表意见", "collect_feedback": "收集反馈",
}


def render_tool_progress(events: list[dict] | None) -> None:
    """渲染一个紧凑的实时工具执行进度条。

    读 StreamingCallback 的事件流，展示：
      - 正在执行的工具（带转圈动画）
      - 已完成（打勾 + 耗时）
      - 失败（错误图标）

    Args:
        events: StreamingCallback.events 里的事件列表
    """
    if not events:
        return

    # 从事件里整理出每个工具的时间线
    tool_events: dict[str, dict] = {}  # tool_name → {start, end, elapsed_ms, error}
    for ev in events:
        if ev["type"] == "tool_start":
            tool_events[ev["tool"]] = {"start": ev["timestamp"], "status": "running"}
        elif ev["type"] == "tool_end":
            if ev["tool"] in tool_events:
                tool_events[ev["tool"]].update({
                    "status": "done",
                    "elapsed_ms": ev.get("elapsed_ms", 0),
                })
        elif ev["type"] == "tool_error":
            if ev["tool"] in tool_events:
                tool_events[ev["tool"]].update({
                    "status": "error",
                    "error": (ev.get("error") or "")[:60],
                })

    if not tool_events:
        return

    # 每个工具拼一个小徽章
    chips: list[str] = []
    for tool_name, info in tool_events.items():
        icon = TOOL_ICONS.get(tool_name, "⚙️")
        label = TOOL_LABELS.get(tool_name, tool_name)
        status = info.get("status", "running")

        if status == "running":
            chips.append(
                f'<span style="display:inline-flex;align-items:center;gap:4px;'
                f'background:{TOKEN["accent_bg"]};border:1px solid {TOKEN["accent_border"]};'
                f'border-radius:99px;padding:3px 10px;font-size:0.78em;'
                f'color:{TOKEN["accent"]};margin:2px 4px 2px 0;">'
                f'{icon} {label} '
                f'<span style="display:inline-block;width:8px;height:8px;'
                f'border-radius:50%;background:{TOKEN["accent"]};'
                f'animation:pulse-warning 1.5s infinite;"></span>'
                f'</span>'
            )
        elif status == "done":
            ms = info.get("elapsed_ms", 0)
            time_str = f"{ms:.0f}ms" if ms < 1000 else f"{ms/1000:.1f}s"
            chips.append(
                f'<span style="display:inline-flex;align-items:center;gap:4px;'
                f'background:{TOKEN["success_bg"]};border:1px solid {TOKEN["success_border"]};'
                f'border-radius:99px;padding:3px 10px;font-size:0.78em;'
                f'color:{TOKEN["success"]};margin:2px 4px 2px 0;">'
                f'{icon} {label} ✅ {time_str}'
                f'</span>'
            )
        elif status == "error":
            chips.append(
                f'<span style="display:inline-flex;align-items:center;gap:4px;'
                f'background:{TOKEN["danger_bg"]};border:1px solid {TOKEN["danger_border"]};'
                f'border-radius:99px;padding:3px 10px;font-size:0.78em;'
                f'color:{TOKEN["danger"]};margin:2px 4px 2px 0;">'
                f'{icon} {label} ❌'
                f'</span>'
            )

    st.markdown(
        f'<div style="margin:8px 0;">'
        f'<span style="font-size:0.75em;color:{TOKEN["text_muted"]};font-weight:500;">'
        f'⚡ 工具执行</span><br>'
        f'{"".join(chips)}'
        f'</div>',
        unsafe_allow_html=True,
    )


# 兜底：原始思考文本

def render_thinking_fallback(thinking_text: str | None) -> None:
    """没有结构化步骤时，直接展示 DeepSeek <think> 原始文本。"""
    if not thinking_text or not thinking_text.strip():
        return

    display = thinking_text[:500]
    if len(thinking_text) > 500:
        display += "\n\n*（内容较长，仅展示前 500 字）*"

    st.markdown(
        f'<div style="background:{TOKEN["page_bg"]};'
        f'border:1px solid {TOKEN["border"]};'
        f'border-left:3px solid {TOKEN["accent"]};'
        f'border-radius:{TOKEN["radius_card"]};padding:12px 16px;'
        f'margin:10px 0;box-shadow:{TOKEN["shadow_sm"]};'
        f'font-size:0.82em;line-height:1.6;color:{TOKEN["text_sec"]};'
        f'white-space:pre-wrap;font-family:system-ui,-apple-system,sans-serif;">'
        f'<div style="font-weight:700;color:{TOKEN["accent"]};'
        f'font-size:0.88em;margin-bottom:6px;">🧠 分析过程</div>'
        f'{display}</div>',
        unsafe_allow_html=True,
    )
