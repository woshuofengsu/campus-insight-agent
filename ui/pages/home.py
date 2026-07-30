# ui/pages/home.py
"""💬 对话 — AI 校园治理伙伴，自然语言交互."""
import time
import streamlit as st
from config import PERCEPTION_IDLE_SECONDS
from ui.components import time_ago, TOKEN, reminder, ooda_nav, resolve_author
from utils.text import split_thinking
from ui.thinking import render_reasoning_chain, render_thinking_fallback, render_tool_progress
from ui.prefetch import try_prefetch as _try_prefetch
from ui.cache import invalidate_issues
from tools.action_report_issue import _auto_classify, _auto_urgency, validate_location
from data.database import report_issue as db_report_issue

# ═══════════════════════════════════════════
# Page render
# ═══════════════════════════════════════════

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
        alert_msg = f"**{alert['emoji']} {alert['title']}**\n\n{alert['message']}"
        memory.add_message("assistant", alert_msg)
        reminder(alert["title"], alert["message"], alert["emoji"])

# ── Brand header ──
st.markdown(
    f'<div style="margin-bottom:2px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">💬 校园先知</span>'
    f'<span style="font-size:0.78em;color:{TOKEN["text_muted"]};margin-left:10px;">'
    f'知校园事 · 报校园修 · 议校园政 · 督校园治</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption("用自然语言上报问题、提建议、参与讨论 —— AI 会自动分类、去重、追踪。")

ooda_nav("home")

# ── Quick report — TOP of page, bypasses AI ──
profile = memory.get_user_profile()
_author = resolve_author(profile)



def _do_quick_report():
    """Callback for quick report button — runs BEFORE page rerender."""
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
        st.session_state._home_report_ok = f"✅ 工单 #{issue_id} 已生成！分类：{cat} · {urgency} · 👉 切到「👤 我的」页面查看"
        st.session_state._home_report_error = ""
        st.session_state.home_quick_title = ""
        st.session_state.home_quick_loc = ""
        invalidate_issues()  # ensure "我的" page shows fresh data
        st.toast(f"Submitted #{issue_id}", icon="✅")
    except Exception as e:
        st.session_state._home_report_error = f"上报失败：{e}"
        st.session_state._home_report_ok = ""
        import traceback
        from utils.logger import get_logger
        get_logger(__name__).error(f"Quick report failed:\n{traceback.format_exc()}")


st.markdown(
    f'<div style="font-size:0.82em;font-weight:700;color:{TOKEN["text"]};margin:8px 0 4px;">'
    f'⚡ 快速报修（直接写入，无需 AI）</div>',
    unsafe_allow_html=True,
)
c_f1, c_f2, c_f3 = st.columns([3, 2, 1])
with c_f1:
    st.text_input("问题描述", placeholder="比如：5号宿舍楼302空调坏了", key="home_quick_title", label_visibility="collapsed")
with c_f2:
    st.text_input("地点", placeholder="宿舍/教室需填房间号", key="home_quick_loc", label_visibility="collapsed")
with c_f3:
    st.button("🚀 上报", type="primary", width="stretch", key="home_quick_btn", on_click=_do_quick_report)

# Show result/error from callback (survives rerun)
if st.session_state.get("_home_report_error"):
    st.error(st.session_state.pop("_home_report_error"))
if st.session_state.get("_home_report_ok"):
    st.success(st.session_state.pop("_home_report_ok"))

st.markdown("---")

# ── Quick action chips ──
st.markdown(
    f'<div style="margin:10px 0 4px;font-size:0.78em;color:{TOKEN["text_muted"]};">'
    f'💡 一键体验 AI 能力（点击自动调用真实数据）：</div>',
    unsafe_allow_html=True,
)
c1, c2, c3, c4 = st.columns(4)

_quick_actions = [
    ("🌊 校园脉搏", "qp_pulse", "校园脉搏", "🤖 AI 正在感知校园动态..."),
    ("🔧 我要报修", "qp_report", "我要报修一个问题，帮我上报", "🤖 AI 正在分析..."),
    ("🗳️ 我有个建议", "qp_proposals", "我有个建议想提给学校", "🤖 AI 正在思考..."),
    ("📊 治理数据", "qp_transparency", "帮我看看最近的校园治理数据怎么样", "🤖 AI 正在查询..."),
]
for i, (label, key, prompt, spinner_text) in enumerate(_quick_actions):
    col = [c1, c2, c3, c4][i]
    with col:
        if st.button(label, key=key, width="stretch"):
            st.session_state.last_interaction = time.time()
            memory.add_message("user", prompt)
            with st.spinner(spinner_text):
                agent.run(prompt)
            invalidate_issues()  # ensure "我的" page shows fresh data
            st.session_state["_home_last_chain"] = agent.get_last_chain()
            st.rerun()

st.markdown("---")

# ── Chat messages ──
chat_container = st.container(height=460, border=False)

with chat_container:
    messages = memory.get_working_memory()
    if not messages:
        profile = memory.get_user_profile()
        st.info(
            "👋 欢迎回来！我是校园先知——你的校园治理 AI 伙伴。\n\n"
            "你可以这样使用我：\n"
            "🌊 **知** · 输入'校园脉搏'看本周热点\n"
            "🔧 **报** · 直接描述问题，比如'教三楼厕所水龙头漏水'\n"
            "🗳️ **议** · '我有个建议'或'看看大家在讨论什么'\n"
            "📊 **督** · 点击顶部导航查看治理看板"
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
                    # ── Reasoning chain visualization ──
                    # For the last assistant message, try structured chain first,
                    # then fall back to raw <think> text.
                    chain = None
                    if is_last:
                        chain = agent.get_last_chain() or st.session_state.get("_home_last_chain")

                    if chain and chain.get("steps"):
                        # Structured: show OODA reasoning steps + association insights
                        render_reasoning_chain(
                            chain["steps"],
                            chain.get("associations"),
                        )
                        # Clean content (no thinking tags needed — already stripped)
                        clean, _ = split_thinking(content)
                        st.markdown(clean)
                    else:
                        # Fallback: raw thinking text or plain content
                        clean, thinking = split_thinking(content)
                        render_thinking_fallback(thinking)
                        st.markdown(clean)
                else:
                    st.markdown(content)
                if ago:
                    st.caption(ago)

# ── Chat input ──
user_input = st.chat_input("输入你的问题，比如'校园脉搏'、'三教二楼灯坏了'、'我有个建议'...")

if user_input:
    st.session_state.last_interaction = time.time()

    # ── Pre-fetch context data as a helpful starting point ──
    # The agent is ENCOURAGED (not forced) to use this data.
    # It should STILL call tools whenever it needs more detail or fresher data.
    prefetch_context = _try_prefetch(user_input)

    augmented_input = user_input

    if prefetch_context:
        augmented_input = (
            user_input + "\n\n"
            f"[📊 系统已预取以下数据作为参考。你可以直接使用这些数据快速回复，"
            f"如需更详细或更新的信息，请调用相应工具获取。]\n\n"
            f"{prefetch_context}"
        )

    # Show thinking indicator with real-time tool tracking
    with st.status("🤖 校园先知正在思考...", expanded=True) as status:
        st.write("🔍 感知校园环境...")
        st.write("🧭 分析你的意图...")

        # Reset callback events before running
        st.session_state["_stream_events"] = []
        st.session_state["_stream_current_tool"] = ""

        result = agent.run(augmented_input)

        # ── Invalidate caches so "我的" page shows fresh data ──
        invalidate_issues()

        # ── Show tool calls from streaming callback ──
        stream_events = st.session_state.get("_stream_events", [])
        if stream_events:
            from ui.thinking import render_tool_progress
            render_tool_progress(stream_events)
        else:
            st.write("🔧 调用工具执行操作...")

        # ── Capture reasoning chain for UI visualization ──
        chain = agent.get_last_chain()
        if chain:
            st.session_state["_home_last_chain"] = chain
            st.write("💡 正在分析关联数据...")
        else:
            st.session_state["_home_last_chain"] = None

        status.update(label="✅ 处理完成！", state="complete", expanded=False)
    st.rerun()
