# app.py
"""校园先知 CampusInsight Agent — Streamlit 多页面入口."""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
from ui.session_state import SS
import altair as alt
from config import DEEPSEEK_API_KEY, OFFLINE_MODE

# ── Global Altair theme ──
# Provides sensible defaults; individual charts override via configure_altair().
@alt.theme.register("campus", enable=True)
def _alt_theme():
    return alt.theme.ThemeConfig({
        "background": "transparent",
        "view": {"stroke": "transparent"},
        "axis": {
            "gridColor": "rgba(0,0,0,0.06)", "domainColor": "rgba(0,0,0,0.10)",
            "tickColor": "rgba(0,0,0,0.10)", "labelColor": "#64748b",
            "titleColor": "#475569", "labelFontSize": 11, "titleFontSize": 12,
        },
        "bar": {"color": "#4f46e5"},
        "line": {"strokeWidth": 2, "color": "#4f46e5"},
        "point": {"filled": True, "size": 50, "color": "#4f46e5"},
})
from ui.session import init_session
from ui.onboarding import render_onboarding
from ui.login import render_login
from ui.theme import inject_theme_css, apply_theme_at_startup, apply_native_theme
from ui.notify import check_and_notify
from agent.rag import build_index


def main():
    # ── Set native theme BEFORE set_page_config (critical for baseweb) ──
    apply_theme_at_startup()

    # ── Page Config — sidebar expanded only when logged in ──
    # apply_native_theme() called immediately after to preserve dark-mode
    # overrides that st.set_page_config() would otherwise reset to config.toml.
    st.set_page_config(
        page_title="校园先知 · CampusInsight",
        page_icon="🏛️",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ── Native theme override — must follow EVERY set_page_config call ──
    apply_native_theme()

    # ── Global CSS ──
    from ui.css import inject_global_css, inject_sidebar_force_css
    inject_global_css()
    inject_theme_css()
    inject_sidebar_force_css()

    # ── Validate .env (skip in offline demo mode) ──
    is_offline = OFFLINE_MODE
    try:
        qp = st.query_params.get("offline")
        if qp and str(qp).lower() in ("1", "true", "yes"):
            is_offline = True
    except Exception:
        pass  # query_params access may fail in some Streamlit versions — non-critical

    if not DEEPSEEK_API_KEY and not is_offline:
        st.warning(
            "⚠️ 未检测到 DeepSeek API Key，已自动切换到**离线演示模式**。\n\n"
            "部分 AI 功能（智能分类、反思分析）将使用规则引擎替代。"
        )
        st.caption("复制 `.env.example` 为 `.env` 并填入 API Key 即可启用完整 AI 能力。")
        is_offline = True
        st.session_state._force_offline = True

    # ── Init Session (DB + Agent + Memory) ──
    try:
        agent, memory = init_session()
    except Exception as e:
        st.error(f"😅 系统初始化失败：{e}\n请检查 .env 中的 API Key 是否正确。")
        st.stop()

    # ── Build RAG index (non-blocking, skips if already indexed) ──
    try:
        build_index(force=False)
    except Exception:
        pass  # RAG is optional — don't block startup

    # ── Login Gate ──
    if SS.login_user_id not in st.session_state:
        render_login()
        return

    # ── Onboarding Gate (new users only) ──
    if not memory.is_onboarding_done():
        render_onboarding(memory)
        return

    # ── Real-time notification check (toasts) ──
    check_and_notify()

    # ── Multi-Page Navigation ──
    profile = memory.get_user_profile()
    if profile is None:
        profile = {}
    role = profile.get("role", "student")

    if role == "teacher":
        nav = st.navigation([
            st.Page("ui/pages_teacher/dashboard.py", title="工作台", icon=":material/dashboard:", default=True),
            st.Page("ui/pages_teacher/issues_mgmt.py", title="工单管理", icon=":material/assignment:"),
            st.Page("ui/pages_teacher/proposals_mgmt.py", title="提案管理", icon=":material/lightbulb:"),
            st.Page("ui/pages_teacher/content_mgmt.py", title="内容发布", icon=":material/campaign:"),
            st.Page("ui/pages_teacher/insights.py", title="数据洞察", icon=":material/insights:"),
            st.Page("ui/pages_teacher/health_mgmt.py", title="健康管理", icon=":material/health_and_safety:"),
        ])
    else:
        nav = st.navigation([
            st.Page("ui/pages/home.py", title="对话", icon=":material/chat:", default=True),
            st.Page("ui/pages/pulse.py", title="校园脉搏", icon=":material/waves:"),
            st.Page("ui/pages/issues.py", title="随手报修", icon=":material/build:"),
            st.Page("ui/pages/voice.py", title="有话说", icon=":material/forum:"),
            st.Page("ui/pages/transparency.py", title="治理透明窗", icon=":material/bar_chart:"),
            st.Page("ui/pages/health.py", title="健康防护", icon=":material/health_and_safety:"),
            st.Page("ui/pages/notifications.py", title="消息", icon=":material/notifications:"),
            st.Page("ui/pages/mine.py", title="我的", icon=":material/person:"),
            st.Page("ui/pages/bigscreen.py", title="治理大屏", icon=":material/tv:"),
        ])

    # ── Sidebar ──
    with st.sidebar:
        from ui.sidebar import render_sidebar
        render_sidebar(profile, role)

    nav.run()


if __name__ == "__main__":
    main()
