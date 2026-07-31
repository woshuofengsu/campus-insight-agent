# app.py
"""校园先知 CampusInsight Agent — Streamlit 多页面入口."""
import sys
import os

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(__file__))

import streamlit as st
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
        "bar": {"color": "#5c6cf0"},
        "line": {"strokeWidth": 2, "color": "#5c6cf0"},
        "point": {"filled": True, "size": 50, "color": "#5c6cf0"},
})
from ui.session import init_session
from ui.onboarding import render_onboarding
from ui.login import render_login
from ui.components import TOKEN
from ui.theme import inject_theme_css, apply_theme_at_startup, apply_native_theme, theme_toggle as render_theme_toggle, get_theme
from ui.notify import check_and_notify, render_sidebar_badge
from ui.cache import invalidate_all
from data.db_user import list_users, get_user_by_id
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
    st.markdown("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    /* Zero out browser defaults */
    html, body { margin: 0 !important; padding: 0 !important; overflow-x: hidden !important; }
    *, *::before, *::after { box-sizing: border-box; }

    /* Hide Streamlit branding */
    #MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
    .stDeployButton { display: none !important; }

    /* Eliminate Streamlit default padding */
    .stApp, .stApp > div, [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] > div,
    [data-testid="stAppViewContainer"] > div > div,
    [data-testid="stMain"], [data-testid="stMain"] > div {
        padding: 0 !important;
        background: inherit;
    }

    /* Typography */
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                     "Microsoft YaHei", "Helvetica Neue", sans-serif;
        -webkit-font-smoothing: antialiased;
    }

    /* Main content */
    .block-container {
        padding-top: 1.5rem !important;
        padding-bottom: 1rem !important;
        max-width: 100% !important;
        padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
    }

    /* Chat Bubbles */
    [data-testid="stChatMessage"] {
        background: var(--c-surface, #ffffff);
        border: 1px solid var(--c-border, #ebebeb);
        padding: 10px 14px;
        margin: 6px auto 6px 0;
        max-width: 92%;
        border-radius: 6px;
    }
    [data-testid="stChatMessage"][aria-label*="user"] {
        background: var(--c-accent-bg, #f0efff);
        border-color: var(--c-accent-border, #d2d0f8);
        border-radius: 6px;
        margin-left: auto;
        margin-right: 0;
        max-width: 85%;
    }
    [data-testid="stChatMessage"][aria-label*="assistant"] {
        background: var(--c-surface, #ffffff);
        border-color: var(--c-border, #ebebeb);
        border-radius: 6px;
    }
    [data-testid="stChatMessage"] img {
        width: 28px !important;
        height: 28px !important;
        border-radius: 4px;
    }
    [data-testid="stChatMessage"] [data-testid="stCaptionContainer"] {
        font-size: 0.72em;
        color: var(--c-text-muted, #a0a0a0);
        margin-top: 4px;
    }

    /* Buttons */
    .stButton > button {
        border-radius: 4px !important;
        font-weight: 500 !important;
        font-size: 0.8em !important;
        transition: all 0.15s ease !important;
        border: 1px solid var(--c-border-visible, #dcdcdc) !important;
        box-shadow: none !important;
        min-height: 32px !important;
    }
    .stButton > button:hover {
        border-color: var(--c-accent-border, #d2d0f8) !important;
        box-shadow: none !important;
    }
    .stButton > button[kind="primary"] {
        border-color: transparent !important;
        background: var(--c-accent, #4f46e5) !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: #4338ca !important;
        filter: none !important;
    }

    /* Radio buttons */
    .stRadio [role="radiogroup"] { gap: 6px; }
    .stRadio label {
        border: 1px solid var(--c-border, #ebebeb);
        border-radius: 6px;
        padding: 4px 12px;
        font-size: 0.82em;
        transition: all 0.15s ease;
    }
    .stRadio label:hover { border-color: var(--c-accent-border, #d2d0f8); background: var(--c-accent-bg, #f0efff); }

    /* Inputs */
    .stSelectbox > div > div,
    .stTextInput > div > div > input,
    .stTextArea textarea {
        border-radius: 4px !important;
        border-color: var(--c-border, #ebebeb) !important;
    }
    .stSelectbox > div > div:focus-within,
    .stTextInput > div > div > input:focus,
    .stTextArea textarea:focus {
        box-shadow: 0 0 0 1px rgba(79,70,229,0.15) !important;
        border-color: var(--c-accent-border, #d2d0f8) !important;
    }

    /* Expanders */
    .stExpander {
        border-radius: 6px !important;
        box-shadow: none !important;
        border: 1px solid var(--c-border, #ebebeb) !important;
    }

    /* Tabs */
    .stTabs [data-baseweb="tab"] {
        font-size: 0.84em !important;
        font-weight: 500 !important;
        padding: 8px 16px !important;
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: var(--c-accent, #4f46e5) !important;
    }

    /* Dividers */
    hr { border-color: var(--c-border, #ebebeb) !important; margin: 16px 0 !important; border-width: 0.5px !important; }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: var(--c-surface, #ffffff);
        border: 1px solid var(--c-border, #ebebeb);
        border-radius: 6px;
        padding: 12px 16px;
        box-shadow: var(--c-shadow-sm, 0 1px 2px rgba(0,0,0,0.04));
    }

    /* Container border */
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-radius: 6px !important;
        border-color: var(--c-border, #ebebeb) !important;
    }

    /* Toast */
    [data-testid="stToast"] {
        border-radius: 6px !important;
        font-size: 0.88em !important;
    }

    /* Status */
    [data-testid="stStatus"] {
        border-radius: 6px !important;
        border: 1px solid var(--c-border, #ebebeb) !important;
    }

    /* PC / Large Screen (>1024px) */
    @media (min-width: 1025px) {
        .block-container {
            max-width: 88rem !important;
            padding-left: 2.5rem !important;
            padding-right: 2.5rem !important;
        }
        [data-testid="stHorizontalBlock"] > div { gap: 1rem; }
        [data-testid="stSidebar"] { max-width: 300px !important; }
        [data-testid="stChatMessage"][aria-label*="user"] { max-width: 75%; }
        [data-testid="stChatMessage"][aria-label*="assistant"] { max-width: 88%; }
    }

    /* Tablet (769px-1024px) */
    @media (min-width: 769px) and (max-width: 1024px) {
        .block-container {
            max-width: 100% !important;
            padding: 1rem 1.2rem !important;
        }
        [data-testid="stHorizontalBlock"] > div { flex-wrap: wrap; }
        [data-testid="stHorizontalBlock"] > div > div {
            flex: 0 0 calc(50% - 0.5rem) !important;
            min-width: calc(50% - 0.5rem) !important;
        }
    }

    /* Mobile (<=768px) */
    @media (max-width: 768px) {
        .block-container {
            padding: 0.5rem 0.6rem !important;
            max-width: 100% !important;
        }
        [data-testid="stHorizontalBlock"] > div {
            flex-direction: column !important;
            gap: 0.5rem !important;
        }
        [data-testid="stHorizontalBlock"] > div > div {
            min-width: 100% !important;
            width: 100% !important;
        }
        .stButton > button {
            width: 100% !important;
            font-size: 0.92em !important;
            min-height: 44px !important;
        }
        .stRadio [role="radiogroup"] {
            flex-direction: column !important;
            flex-wrap: wrap;
        }
        .stRadio label { width: 100%; padding: 8px 12px; font-size: 0.88em; }
        [data-testid="stChatMessage"][aria-label*="user"],
        [data-testid="stChatMessage"][aria-label*="assistant"] {
            max-width: 98% !important;
        }
        .stSelectbox > div > div, .stTextInput > div > div > input {
            min-height: 40px !important;
        }
        .stCaption, caption, [data-testid="stCaptionContainer"] {
            font-size: 0.82em !important;
        }
        [data-testid="stSidebar"] {
            min-width: 0 !important;
            max-width: 0 !important;
            width: 0 !important;
            overflow: hidden !important;
        }
        [data-testid="stSidebar"][aria-expanded="true"] {
            min-width: 100vw !important;
            max-width: 100vw !important;
            width: 100vw !important;
            z-index: 9999 !important;
        }
    }

    /* Small phone (<480px) */
    @media (max-width: 480px) {
        .block-container { padding: 0.3rem 0.4rem !important; }
        [data-testid="stHorizontalBlock"] > div { gap: 0.3rem !important; }
        html { font-size: 15px; }
        .stButton > button { min-height: 46px !important; font-size: 0.95em !important; }
        .stat-card { padding: 10px 8px !important; }
        .stat-value { font-size: 1.3em !important; }
        .stat-label { font-size: 0.75em !important; }
    }

    /* Safe area for notched phones */
    @supports (padding-bottom: env(safe-area-inset-bottom)) {
        .block-container {
            padding-bottom: calc(1rem + env(safe-area-inset-bottom)) !important;
        }
    }

    /* Print */
    @media print {
        [data-testid="stSidebar"], .stButton, button, [data-testid="stHeader"] {
            display: none !important;
        }
        .block-container { max-width: 100% !important; padding: 0 !important; }
    }
</style>
""", unsafe_allow_html=True)

    inject_theme_css()

    # ── Force sidebar visibility (only on desktop/tablet, not mobile) ──
    # Must match BOTH [data-testid="stSidebar"] AND the collapsed variant
    # [data-testid="stSidebarCollapsed"] so that Streamlit's own CSS
    # (which injects higher-specificity rules when sidebar is collapsed
    # via set_page_config initial_sidebar_state) does not win.
    st.markdown("""
<style>
@media (min-width: 769px) {
    [data-testid="stSidebar"],
    [data-testid="stSidebar"][aria-expanded="false"],
    [data-testid="stSidebarCollapsed"] {
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        min-width: 240px !important;
        max-width: 300px !important;
        width: 280px !important;
        transform: none !important;
        position: relative !important;
        left: 0 !important;
    }
}
</style>
""", unsafe_allow_html=True)

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
    if "_login_user_id" not in st.session_state:
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

    # ── Sidebar brand + profile ──
    with st.sidebar:
        is_dark = get_theme() == "dark"
        tx = "#e8e8ed" if is_dark else "#1a1a1a"
        tx2 = "#9898a2" if is_dark else "#6e6e6e"
        tx3 = "#5e5e6a" if is_dark else "#a0a0a0"
        bd = "#25252e" if is_dark else "#ebebeb"
        card = "#18181f" if is_dark else "#ffffff"
        accent_bg = "rgba(109,107,245,0.10)" if is_dark else "#f0efff"
        accent_bd = "rgba(109,107,245,0.18)" if is_dark else "#d2d0f8"
        accent = "#6d6bf5" if is_dark else "#4f46e5"

        # ── Brand header ──
        st.markdown(
            f'<div style="padding:14px 0 8px;">'
            f'<div style="font-size:1.1em;font-weight:700;color:{tx};'
            f'letter-spacing:-0.01em;">CampusInsight</div>'
            f'<div style="font-size:0.7em;color:{tx3};margin-top:1px;">'
            f'{"校园治理平台" if role != "teacher" else "管理后台"}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── User profile card ──
        if profile:
            school = profile.get("school", "")
            grade = profile.get("grade", "")
            major = profile.get("major", "")
            student_id = profile.get("student_id", "")
            name = profile.get("name", "")
            role_label = "教师" if role == "teacher" else "学生"
            display_name = name or profile.get("username", "User")

            st.markdown(
                f'<div style="background:{accent_bg};'
                f'border:1px solid {accent_bd};'
                f'border-radius:6px;padding:10px 12px;margin:8px 0;">'
                f'<div style="font-size:0.84em;font-weight:600;color:{tx};">'
                f'{display_name}</div>'
                f'<div style="font-size:0.7em;color:{tx2};line-height:1.5;">'
                f'<span style="background:{accent}18;color:{accent};'
                f'padding:1px 6px;border-radius:99px;font-size:0.85em;">{role_label}</span>'
                f'{" &middot; " + school if school else ""}'
                f'{" &middot; " + grade if grade else ""}'
                f'{"<br>" + major if major and role != "teacher" else ""}'
                f'{"<br>" + student_id if student_id else ""}'
                f'</div></div>',
                unsafe_allow_html=True,
            )

        # ── Divider with label ──
        def _sidebar_divider(label: str = ""):
            if label:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;margin:12px 0 6px;">'
                    f'<span style="font-size:0.68em;font-weight:600;color:{tx3};'
                    f'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;">{label}</span>'
                    f'<div style="flex:1;height:1px;background:{bd};"></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown("---")

        # ── Sidebar stat grid helper ──
        _warn_bg = "rgba(251,191,36,0.08)" if is_dark else "#fffbeb"
        _dang_bg = "rgba(248,113,113,0.08)" if is_dark else "#fef2f2"
        _succ_bg = "rgba(52,211,153,0.08)" if is_dark else "#ecfdf5"
        _warn = "#fbbf24" if is_dark else "#d97706"
        _dang = "#f87171" if is_dark else "#dc2626"
        _succ = "#34d399" if is_dark else "#059669"

        def _sidebar_stat_grid(items: list[tuple[str, str, str, str]]):
            color_map = {
                "text": tx, "card_bg": card,
                "warning": _warn, "warning_bg": _warn_bg,
                "danger": _dang, "danger_bg": _dang_bg,
                "success": _succ, "success_bg": _succ_bg,
            }
            cells = []
            for label, value, bg_key, color_key in items:
                bg = color_map.get(bg_key, card)
                color = color_map.get(color_key, tx)
                cells.append(
                    f'<div style="background:{bg};padding:6px 8px;border-radius:4px;'
                    f'text-align:center;"><div style="color:{tx3};">{label}</div>'
                    f'<div style="font-weight:600;color:{color};">{value}</div></div>'
                )
            st.markdown(
                f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;'
                f'font-size:0.7em;">{"".join(cells)}</div>',
                unsafe_allow_html=True,
            )

        _sidebar_divider("概览")

        # Governance stats
        from ui.cache import cached_issues_stats, cached_proposals_stats, cached_knowledge_base
        i_stats = cached_issues_stats()
        p_stats = cached_proposals_stats()
        resolved = i_stats["by_status"].get("已解决", 0)
        pending = i_stats["by_status"].get("待处理", 0)
        in_progress = i_stats["by_status"].get("处理中", 0)

        if role == "teacher":
            from ui.cache import cached_issues
            urgent_issues = cached_issues(urgency="紧急", limit=100)
            urgent_count = len(urgent_issues)
            _sidebar_stat_grid([
                ("工单", str(i_stats["total"]), "card_bg", "text"),
                ("提案", str(p_stats["total"]), "card_bg", "text"),
                ("待处理", str(pending), "warning_bg", "warning"),
                ("紧急", str(urgent_count), "danger_bg", "danger"),
            ])
        else:
            _sidebar_stat_grid([
                ("上报", str(i_stats["total"]), "card_bg", "text"),
                ("提案", str(p_stats["total"]), "card_bg", "text"),
                ("已解决", str(resolved), "success_bg", "success"),
                ("待处理", str(pending), "warning_bg", "warning"),
            ])

        # Knowledge base quick links
        kb = cached_knowledge_base(category="faq", limit=1)
        gov = cached_knowledge_base(category="governance", limit=2)
        if kb or gov:
            _sidebar_divider("百科")
            for entry in (kb + gov)[:3]:
                title = entry.get("title", "")[:18]
                cat = entry.get("category", "")
                st.markdown(
                    f'<div style="font-size:0.7em;color:{tx2};'
                    f'padding:2px 0;line-height:1.3;">'
                    f'<span style="color:{tx3};">{cat.upper()[:4]}</span> {title}</div>',
                    unsafe_allow_html=True,
                )

        # ── Notification badges ──
        render_sidebar_badge()

        _sidebar_divider("账户")

        # ── User switcher (demo: switch between accounts) ──
        all_users = list_users()
        if len(all_users) > 1:
            current_uid = st.session_state.get("_login_user_id", 1)
            user_options = {
                f'{u["role"].replace("student","[学生]").replace("teacher","[教师]")} '
                f'{u.get("name","") or u["username"]}'
                f'{" · " + u.get("school","")[:8] if u.get("school") else ""}': u["id"]
                for u in all_users
            }
            current_label = next(
                (k for k, v in user_options.items() if v == current_uid),
                list(user_options.keys())[0],
            )
            selected_label = st.selectbox(
                "切换账号",
                list(user_options.keys()),
                index=list(user_options.keys()).index(current_label),
                key="_user_switcher",
                label_visibility="collapsed",
            )
            selected_uid = user_options[selected_label]
            if selected_uid != current_uid:
                st.session_state._login_user_id = selected_uid
                st.session_state.user_profile = get_user_by_id(selected_uid)
                st.session_state.pop("messages", None)
                st.session_state.pop("langchain_memory", None)
                st.session_state.pop("session_ready", None)
                st.session_state.pop("agent", None)
                st.session_state.pop("memory", None)
                invalidate_all()
                st.rerun()

        # ── Theme toggle + Logout row ──
        c_t, c_l = st.columns([1, 1])
        with c_t:
            render_theme_toggle()
        with c_l:
            if st.button("退出", key="_logout", width="stretch"):
                for key in ["_login_user_id", "user_profile", "messages",
                            "langchain_memory", "session_ready", "agent", "memory"]:
                    st.session_state.pop(key, None)
                for key in ["ob_role", "ob_school", "ob_grade", "ob_student_id",
                           "ob_major", "ob_name"]:
                    st.session_state.pop(key, None)
                invalidate_all()
                st.rerun()

        st.caption("知 · 报 · 议 · 督 · 校园治理")

    nav.run()


if __name__ == "__main__":
    main()
