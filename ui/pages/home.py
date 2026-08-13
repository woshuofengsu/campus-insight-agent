# ui/pages/home.py
"""Chat — community governance assistant."""
import time
import logging
import streamlit as st
from config import PERCEPTION_IDLE_SECONDS
from ui.components import TOKEN, time_ago, reminder, ooda_nav, resolve_author, page_header
from ui.session_state import SS, session
from utils.text import split_thinking
from ui.thinking import render_reasoning_chain, render_thinking_fallback, render_tool_progress
from ui.prefetch import try_prefetch as _try_prefetch
from ui.cache import invalidate_issues, cached_issues_stats
from tools.action_report_issue import _auto_classify, _auto_urgency, validate_location
from data.database import report_issue as db_report_issue

_log = logging.getLogger(__name__)

agent = st.session_state.get("agent")
memory = st.session_state.get("memory")

# ── Perception check (idle-based) ──
now = time.time()
last_check = st.session_state.get("last_check_time") or 0
last_interaction = st.session_state.get("last_interaction") or 0
threshold = PERCEPTION_IDLE_SECONDS

if last_interaction and (now - last_interaction) > threshold and (now - last_check) > threshold:
    st.session_state.last_check_time = now
    alerts = agent.run_perception_check()
    for alert in alerts:
        alert_msg = f"**{alert['title']}**\n\n{alert['message']}"
        memory.add_message("assistant", alert_msg)
        reminder(alert["title"], alert["message"])

# ── Header (对话 Agent 主角) ──
page_header("对话", "用自然语言上报问题、查看社区动态、参与提案讨论。", "社区助手")
ooda_nav("home")

# ── Quick Report — 一句话快捷上报（无需等待 AI 对话）──
profile = memory.get_user_profile()
_author = resolve_author(profile)

def _do_quick_report():
    title = st.session_state.home_quick_title.strip()
    loc = st.session_state.home_quick_loc.strip()
    if not title:
        st.session_state._home_report_error = "请填写问题描述"
        return
    loc_err = validate_location(title, loc)
    if loc_err:
        st.session_state._home_report_error = loc_err
        return
    cat = _auto_classify(title, "")
    urgency = _auto_urgency(title, "")
    try:
        issue_id = db_report_issue(
            title=title, category=cat, location=loc,
            description="", urgency=urgency, author=_author,
        )
        st.session_state._home_report_ok = f"工单 #{issue_id} 已创建 · {cat} · {urgency}"
        st.session_state._home_report_error = ""
        st.session_state.home_quick_title = ""
        st.session_state.home_quick_loc = ""
        invalidate_issues()
        st.toast(f"已提交 #{issue_id}")
    except Exception as e:
        _log.debug("non-critical failure", exc_info=True)
        st.session_state._home_report_error = f"上报失败：{e}"
        st.session_state._home_report_ok = ""

st.markdown(
    f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
    f'border-radius:14px;padding:14px 20px;margin-bottom:14px;'
    f'box-shadow:{TOKEN["shadow"]};">'
    f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:10px;">'
    f'<div style="font-size:1.15em;">⚡</div>'
    f'<div style="font-weight:800;font-size:1.05em;color:{TOKEN["text"]};">快速上报</div>'
    f'<div style="font-size:0.78em;color:{TOKEN["text_muted"]};">一句话描述，AI 自动分类定级 · 3 秒生成工单</div>'
    f'</div></div>',
    unsafe_allow_html=True,
)
qc1, qc2, qc3 = st.columns([3, 2, 1])
with qc1:
    st.text_input("问题描述", placeholder="如：5号楼302空调坏了、小区广场地面有坑…", key="home_quick_title", label_visibility="collapsed")
with qc2:
    st.text_input("地点", placeholder="楼栋/单元/门牌号（可选）", key="home_quick_loc", label_visibility="collapsed")
with qc3:
    st.button("立即上报", type="primary", width="stretch", key="home_quick_btn", on_click=_do_quick_report)

if st.session_state.get("_home_report_error"):
    st.error(st.session_state.pop("_home_report_error"))
if st.session_state.get("_home_report_ok"):
    st.success(st.session_state.pop("_home_report_ok"))

# ── Split layout: chat (left 3) + panel (right 1) ──
chat_col, panel_col = st.columns([3, 1])

with panel_col:
    # ── Quick Actions ──
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:6px;">'
        f'<div style="width:3px;height:14px;border-radius:2px;'
        f'background:{TOKEN["brand_gradient"]};flex-shrink:0;"></div>'
        f'<div style="font-size:0.75em;font-weight:700;color:{TOKEN["text_sec"]};'
        f'letter-spacing:0.03em;">快捷操作</div></div>',
        unsafe_allow_html=True,
    )
    _quick_actions = [
        ("社区脉搏", "qp_pulse", "社区脉搏"),
        ("我要上报", "qp_report", "我要上报一个问题，帮我上报"),
        ("我有个建议", "qp_proposals", "我有个建议想提给社区"),
        ("治理数据", "qp_transparency", "帮我看看最近的社区治理数据怎么样"),
    ]
    for label, key, prompt in _quick_actions:
        if st.button(label, key=key, width="stretch"):
            st.session_state.last_interaction = time.time()
            memory.add_message("user", prompt)
            agent.run(prompt)
            invalidate_issues()
            st.session_state["_home_last_chain"] = agent.get_last_chain()
            st.rerun()

    st.markdown("---")

    # ── System Status ──
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:7px;margin-bottom:6px;">'
        f'<div style="width:3px;height:14px;border-radius:2px;'
        f'background:{TOKEN["brand_gradient"]};flex-shrink:0;"></div>'
        f'<div style="font-size:0.75em;font-weight:700;color:{TOKEN["text_sec"]};'
        f'letter-spacing:0.03em;">系统状态</div></div>',
        unsafe_allow_html=True,
    )
    try:
        stats = cached_issues_stats()
        pending = stats["by_status"].get("待处理", 0)
        resolved = stats["by_status"].get("已解决", 0)
        total = stats["total"]
        st.markdown(
            f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_sec"]};">'
            f'<div>工单总数：{total}</div>'
            f'<div style="color:{TOKEN["warning"]};">待处理：{pending}</div>'
            f'<div style="color:{TOKEN["success"]};">已解决：{resolved}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    except Exception:
        _log.warning("Failed to load stats for system status panel", exc_info=True)

    # ── Notification badge ──
    try:
        user_id = session.login_user_id
        from data.db_notifications import get_unread_count, get_notifications, mark_all_read
        unread = get_unread_count(user_id) if user_id else 0
        if unread > 0:
            recent = get_notifications(user_id, unread_only=True, limit=3)
            st.markdown(
                f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["accent"]};'
                f'font-weight:600;margin-top:8px;">{unread} 条未读</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        _log.warning("Failed to load notification badge", exc_info=True)

with chat_col:
    # ── Chat messages ──
    chat_container = st.container(height=440, border=False)

    with chat_container:
        messages = memory.get_working_memory()
        if not messages:
            st.info(
                "欢迎。我是你的社区治理助手。\n\n"
                "你可以这样使用我：\n"
                "- 输入「社区脉搏」查看本周热点\n"
                "- 描述问题：「3号楼二楼水龙头漏水」\n"
                "- 「我有个建议」提交提案\n"
                "- 「治理数据」查看透明统计"
            )
        else:
            for i, msg in enumerate(messages[-40:]):
                role = msg["role"]
                content = msg["content"]
                ts = msg.get("timestamp", "")
                ago = time_ago(ts) if ts else ""
                is_last = (i == len(messages[-40:]) - 1)

                with st.chat_message(role):
                    if role == "assistant":
                        chain = None
                        if is_last:
                            chain = agent.get_last_chain() or st.session_state.get("_home_last_chain")

                        if chain and chain.get("steps"):
                            render_reasoning_chain(chain["steps"], chain.get("associations"))
                            clean, _ = split_thinking(content)
                            st.markdown(clean)
                        else:
                            clean, thinking = split_thinking(content)
                            render_thinking_fallback(thinking)
                            st.markdown(clean)
                    else:
                        st.markdown(content)
                    if ago:
                        st.caption(ago)

    # ── Chat input ──
    user_input = st.chat_input("输入你的问题，如「社区脉搏」、「3号楼灯坏了」...")

    if user_input:
        st.session_state.last_interaction = time.time()
        prefetch_context = _try_prefetch(user_input)
        augmented_input = user_input
        if prefetch_context:
            augmented_input = (
                user_input + "\n\n"
                f"[Pre-fetched data for reference. Call tools for more detail.]\n\n"
                f"{prefetch_context}"
            )

        with st.status("思考中...", expanded=True) as status:
            st.write("分析意图...")
            st.session_state["_stream_events"] = []
            st.session_state["_stream_current_tool"] = ""
            result = agent.run(augmented_input)
            invalidate_issues()

            stream_events = st.session_state.get("_stream_events", [])
            if stream_events:
                from ui.thinking import render_tool_progress
                render_tool_progress(stream_events)
            else:
                st.write("调用工具...")

            chain = agent.get_last_chain()
            if chain:
                st.session_state["_home_last_chain"] = chain
                st.write("分析关联数据...")
            else:
                st.session_state["_home_last_chain"] = None

            status.update(label="完成", state="complete", expanded=False)
        st.rerun()
