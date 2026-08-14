# ui/css.py
"""全局 CSS 注入：所有 Streamlit 的样式覆盖和响应式规则都集中在这。"""
import streamlit as st

GLOBAL_CSS = """<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    *, *::before, *::after { box-sizing: border-box; }

    /* 隐藏 Streamlit 右上角工具栏（精准选择器，不碰 header 结构，避免 removeChild） */
    .stDeployButton { display: none !important; }
    #MainMenu { visibility: hidden !important; }
    footer { display: none !important; }

    body {
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC",
                     "Microsoft YaHei", "Helvetica Neue", sans-serif;
        -webkit-font-smoothing: antialiased;
    }

    .block-container {
        padding-top: 1.5rem !important; padding-bottom: 1rem !important;
        max-width: 100% !important; padding-left: 1.5rem !important;
        padding-right: 1.5rem !important;
    }

    [data-testid="stChatMessage"] {
        background: var(--c-surface, #ffffff); border: 1px solid var(--c-border, #e9e5df);
        padding: 10px 14px; margin: 6px auto 6px 0; max-width: 92%; border-radius: 10px;
    }
    [data-testid="stChatMessage"][aria-label*="user"] {
        background: var(--c-accent-bg, #eef0ff); border-color: var(--c-accent-border, #cfd4f8);
        border-radius: 10px; margin-left: auto; margin-right: 0; max-width: 85%;
    }
    [data-testid="stChatMessage"][aria-label*="assistant"] {
        background: var(--c-surface, #ffffff); border-color: var(--c-border, #e9e5df); border-radius: 10px;
    }
    [data-testid="stChatMessage"] img { width: 28px !important; height: 28px !important; border-radius: 6px; }
    [data-testid="stChatMessage"] [data-testid="stCaptionContainer"] {
        font-size: 0.75em; color: var(--c-text-muted, #9c958a); margin-top: 4px;
    }

    .stButton > button {
        border-radius: 8px !important; font-weight: 500 !important; font-size: 0.8em !important;
        transition: all 0.15s ease !important; border: 1px solid var(--c-border-visible, #d8d3cb) !important;
        box-shadow: none !important; min-height: 32px !important;
    }
    .stButton > button:hover { border-color: var(--c-accent-border, #cfd4f8) !important; box-shadow: none !important; }
    .stButton > button[kind="primary"] { border: none !important; background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%) !important; box-shadow: 0 4px 12px rgba(79,70,229,0.28) !important; }
    .stButton > button[kind="primary"]:hover { background: linear-gradient(135deg, #4338ca 0%, #6d28d9 100%) !important; filter: none !important; }

    .stRadio [role="radiogroup"] { gap: 6px; }
    .stRadio label {
        border: 1px solid var(--c-border, #e9e5df); border-radius: 10px;
        padding: 4px 12px; font-size: 0.82em; transition: all 0.15s ease;
    }
    .stRadio label:hover { border-color: var(--c-accent-border, #cfd4f8); background: var(--c-accent-bg, #eef0ff); }

    .stSelectbox > div > div, .stTextInput > div > div > input, .stTextArea textarea {
        border-radius: 8px !important; border-color: var(--c-border, #e9e5df) !important;
    }
    .stSelectbox > div > div:focus-within,
    .stTextInput > div > div > input:focus,
    .stTextArea textarea:focus {
        box-shadow: 0 0 0 1px rgba(79,70,229,0.15) !important;
        border-color: var(--c-accent-border, #cfd4f8) !important;
    }

    .stExpander { border-radius: 10px !important; box-shadow: none !important; border: 1px solid var(--c-border, #e9e5df) !important; }
    .stTabs [data-baseweb="tab"] { font-size: 0.84em !important; font-weight: 500 !important; padding: 8px 16px !important; }
    .stTabs [data-baseweb="tab"][aria-selected="true"] { color: var(--c-accent, #4f46e5) !important; }
    hr { border-color: var(--c-border, #e9e5df) !important; margin: 16px 0 !important; border-width: 0.5px !important; }

    [data-testid="stMetric"] {
        background: var(--c-surface, #ffffff); border: 1px solid var(--c-border, #e9e5df);
        border-radius: 10px; padding: 12px 16px; box-shadow: var(--c-shadow-sm, 0 1px 2px rgba(31,29,25,0.05));
    }
    [data-testid="stVerticalBlockBorderWrapper"] { border-radius: 10px !important; border-color: var(--c-border, #e9e5df) !important; }
    [data-testid="stToast"] { border-radius: 10px !important; font-size: 0.88em !important; }
    [data-testid="stStatus"] { border-radius: 10px !important; border: 1px solid var(--c-border, #e9e5df) !important; }

    @media (min-width: 1025px) {
        .block-container { max-width: 88rem !important; padding-left: 2.5rem !important; padding-right: 2.5rem !important; }
        [data-testid="stHorizontalBlock"] > div { gap: 1rem; }
        [data-testid="stSidebar"] { max-width: 300px !important; }
        [data-testid="stChatMessage"][aria-label*="user"] { max-width: 75%; }
        [data-testid="stChatMessage"][aria-label*="assistant"] { max-width: 88%; }
    }

    @media (min-width: 769px) and (max-width: 1024px) {
        .block-container { max-width: 100% !important; padding: 1rem 1.2rem !important; }
        [data-testid="stHorizontalBlock"] > div { flex-wrap: wrap; }
        [data-testid="stHorizontalBlock"] > div > div { flex: 0 0 calc(50% - 0.5rem) !important; min-width: calc(50% - 0.5rem) !important; }
    }

    @media (max-width: 768px) {
        .block-container { padding: 0.5rem 0.6rem !important; max-width: 100% !important; }
        [data-testid="stHorizontalBlock"] > div { flex-direction: column !important; gap: 0.5rem !important; }
        [data-testid="stHorizontalBlock"] > div > div { min-width: 100% !important; width: 100% !important; }
        .stButton > button { width: 100% !important; font-size: 0.92em !important; min-height: 44px !important; }
        .stRadio [role="radiogroup"] { flex-direction: column !important; flex-wrap: wrap; }
        .stRadio label { width: 100%; padding: 8px 12px; font-size: 0.88em; }
        [data-testid="stChatMessage"][aria-label*="user"],
        [data-testid="stChatMessage"][aria-label*="assistant"] { max-width: 98% !important; }
        .stSelectbox > div > div, .stTextInput > div > div > input { min-height: 40px !important; }
        .stCaption, caption, [data-testid="stCaptionContainer"] { font-size: 0.82em !important; }
        /* Mobile: let Streamlit natively collapse sidebar to hamburger.
           Expanded sidebar overlays full screen for easy reading. */
        [data-testid="stSidebar"][aria-expanded="true"] { min-width: 100vw !important; max-width: 100vw !important; width: 100vw !important; z-index: 9999 !important; }
    }

    @media (max-width: 480px) {
        .block-container { padding: 0.3rem 0.4rem !important; }
        [data-testid="stHorizontalBlock"] > div { gap: 0.3rem !important; }
        html { font-size: 15px; }
        .stButton > button { min-height: 46px !important; font-size: 0.95em !important; }
        .stat-card { padding: 10px 8px !important; }
        .stat-value { font-size: 1.3em !important; }
        .stat-label { font-size: 0.75em !important; }
        input, select, textarea, [data-baseweb="select"] { font-size: 16px !important; }
    }

    @supports (padding-bottom: env(safe-area-inset-bottom)) {
        .block-container { padding-bottom: calc(1rem + env(safe-area-inset-bottom)) !important; }
    }

    @media print {
        [data-testid="stSidebar"], .stButton, button, [data-testid="stHeader"] { display: none !important; }
        .block-container { max-width: 100% !important; padding: 0 !important; }
    }
</style>"""

SIDEBAR_FORCE_CSS = """<style>
/* 仅约束桌面端侧边栏宽度；不再强制展开已折叠的侧边栏（aria-expanded=false 的
   强制显示会与 Streamlit 前端 DOM 状态冲突，触发 removeChild 错误导致白屏）。 */
@media (min-width: 769px) {
    [data-testid="stSidebar"] {
        min-width: 240px !important; max-width: 300px !important;
    }
}
</style>"""


def inject_global_css():
    """注入全部全局 CSS，app.py 里在 inject_theme_css() 之后调用一次。"""
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def inject_sidebar_force_css():
    """桌面端侧边栏宽度设置，在 inject_global_css() 之后调用。"""
    st.markdown(SIDEBAR_FORCE_CSS, unsafe_allow_html=True)
