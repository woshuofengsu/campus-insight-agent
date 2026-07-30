# ui/theme.py
"""Theme system — light-first with dark mode toggle.

Design:
  - Light is the DEFAULT theme. Dark mode is available via sidebar toggle.
  - The toggle stores theme in st.session_state (survives all reruns and
    st.navigation() page switches) + URL query param for browser-refresh
    persistence.
  - Native theme: st._config.set_option (Streamlit private API) is used
    in apply_native_theme() to set theme colors at the engine level — this
    prevents white/black borders that CSS injection alone cannot fix.
  - st.set_page_config() is called ONLY on the first run (not on every
    rerun).  This prevents it from resetting the native theme to
    config.toml on every st.navigation() page switch.
  - CSS injection (inject_theme_css) handles component-level styling and
    is a safety net for elements the native theme doesn't cover.
  - On fresh app start (no query param), it's light.

Usage:
  from ui.theme import get_token, inject_theme_css, theme_toggle, apply_theme_at_startup

  # In app.py, BEFORE st.set_page_config:
  apply_theme_at_startup()

  # After set_page_config, before content:
  apply_native_theme()
  inject_theme_css()

  # In sidebar:
  theme_toggle()

  # Anywhere you need a color:
  token = get_token()
"""

import streamlit as st  # noqa: F401

# ═══════════════════════════════════════════
# Light tokens (fallback — kept functional)
# ═══════════════════════════════════════════
TOKEN_LIGHT = {
    # Brand accent — indigo, clean
    "primary":        "#5c6cf0",
    "primary_hover":  "#4f46e5",
    "primary_bg":     "#eef2ff",
    "primary_border": "#c7d2fe",
    "primary_light":  "#f5f7ff",

    # Semantic
    "success":        "#059669",
    "success_bg":     "#ecfdf5",
    "success_border": "#a7f3d0",
    "warning":        "#d97706",
    "warning_bg":     "#fffbeb",
    "warning_border": "#fde68a",
    "danger":         "#dc2626",
    "danger_bg":      "#fef2f2",
    "danger_border":  "#fecaca",

    # Purple (for bigscreen / special accents)
    "purple_bg":      "#f5f3ff",
    "purple_border":  "#ddd6fe",
    "purple_text":    "#7c3aed",

    # Surfaces — subtle elevation
    "slate_bg":       "#f8fafc",    # page background
    "slate_border":   "#e2e8f0",    # subtle border
    "card_bg":        "#ffffff",    # card / container surface

    # Text — high contrast on light
    "text":           "#0f172a",
    "text_sec":       "#475569",
    "text_muted":     "#94a3b8",

    # Radius
    "radius_xs":      "4px",
    "radius_sm":      "6px",
    "radius":         "8px",
    "radius_lg":      "12px",
    "radius_full":    "99px",

    # Shadows — very subtle on light
    "shadow_none":    "none",
    "shadow_xs":      "0 1px 2px rgba(0,0,0,0.04)",
    "shadow_sm":      "0 1px 3px rgba(0,0,0,0.06)",
    "shadow":         "0 2px 8px rgba(0,0,0,0.06)",
    "shadow_md":      "0 4px 16px rgba(0,0,0,0.08)",

    "transition":     "0.15s ease",
}

# ═══════════════════════════════════════════
# Dark tokens — Linear-inspired professional
# ═══════════════════════════════════════════
TOKEN_DARK = {
    # Brand accent — muted indigo, not neon
    "primary":        "#7984f5",
    "primary_hover":  "#8f98f7",
    "primary_bg":     "rgba(121,132,245,0.10)",
    "primary_border": "rgba(121,132,245,0.20)",
    "primary_light":  "rgba(121,132,245,0.06)",

    # Semantic
    "success":        "#4ade80",
    "success_bg":     "rgba(74,222,128,0.08)",
    "success_border": "rgba(74,222,128,0.18)",
    "warning":        "#f59e0b",
    "warning_bg":     "rgba(245,158,11,0.08)",
    "warning_border": "rgba(245,158,11,0.18)",
    "danger":         "#f87171",
    "danger_bg":      "rgba(248,113,113,0.08)",
    "danger_border":  "rgba(248,113,113,0.18)",

    # Purple (for bigscreen / special accents)
    "purple_bg":      "rgba(167,139,250,0.08)",
    "purple_border":  "rgba(167,139,250,0.18)",
    "purple_text":    "#a78bfa",

    # Surfaces — subtle depth through brightness, not color
    "slate_bg":       "#0b0f19",   # page background (deepest)
    "slate_border":   "rgba(255,255,255,0.06)",  # barely visible
    "card_bg":        "#141928",   # card / container surface

    # Text — off-white, never pure white
    "text":           "#e9ecf2",
    "text_sec":       "#99a1b3",
    "text_muted":     "#616a80",

    # Radius — Linear uses small, consistent radius
    "radius_xs":      "4px",
    "radius_sm":      "6px",
    "radius":         "8px",
    "radius_lg":      "12px",
    "radius_full":    "99px",

    # Shadows — offset + soft blur on dark (subtle)
    "shadow_none":    "none",
    "shadow_xs":      "0 1px 2px rgba(0,0,0,0.3)",
    "shadow_sm":      "0 2px 4px rgba(0,0,0,0.4)",
    "shadow":         "0 4px 12px rgba(0,0,0,0.5)",
    "shadow_md":      "0 8px 24px rgba(0,0,0,0.6)",

    "transition":     "0.15s ease",
}

# Session-state key for the current theme
# Bumped to v2 to invalidate old dark-mode sessions — default is now light
_THEME_KEY = "_campus_theme_v2"


def apply_theme_at_startup():
    """Ensure theme is in session state BEFORE st.set_page_config.

    Must be called at the top of main(), before st.set_page_config().
    Currently hard-forced to light — dark mode toggle available in sidebar.
    """
    # Force light mode as the starting default, always.
    # URL param can still override to dark if user explicitly toggles.
    if _THEME_KEY not in st.session_state:
        mode = "light"
        try:
            qp = st.query_params.get("theme")
            if isinstance(qp, list):
                qp = qp[0] if qp else None
            if qp in ("light", "dark"):
                mode = qp
        except Exception:
            pass
        st.session_state[_THEME_KEY] = mode


def get_theme() -> str:
    """Return current theme: 'dark' or 'light'."""
    if _THEME_KEY in st.session_state:
        return st.session_state[_THEME_KEY]
    try:
        qp = st.query_params.get("theme")
        if isinstance(qp, list):
            qp = qp[0] if qp else None
        if qp in ("light", "dark"):
            return qp
    except Exception:
        pass
    return "light"


def get_token() -> dict:
    """Return the active theme's token dict."""
    return TOKEN_DARK if get_theme() == "dark" else TOKEN_LIGHT


def apply_native_theme():
    """Override Streamlit's native theme after set_page_config.

    MUST be called AFTER st.set_page_config() in app.py.

    Config.toml provides the dark-mode base (Linear style). We use
    st._config.set_option to switch the native theme at runtime for BOTH
    modes.  This is necessary because app.py skips st.set_page_config()
    after the first run.

    This changes colors at the Streamlit engine level, not via CSS,
    so there are no white/black borders in either mode.
    """
    theme = get_theme()
    try:
        if theme == "dark":
            st._config.set_option("theme.backgroundColor", "#0b0f19")
            st._config.set_option("theme.secondaryBackgroundColor", "#141928")
            st._config.set_option("theme.textColor", "#e9ecf2")
        else:
            st._config.set_option("theme.backgroundColor", "#f8fafc")
            st._config.set_option("theme.secondaryBackgroundColor", "#f1f5f9")
            st._config.set_option("theme.textColor", "#0f172a")
    except Exception:
        pass  # Private API — fail silently, CSS injection is the fallback


def theme_toggle():
    """Render a theme toggle button. Use in sidebar.

    Session state is the source of truth — survives all st.navigation()
    page switches. Query param synced for browser-refresh persistence.
    """
    theme = get_theme()
    is_dark = theme == "dark"
    label = "☀️ 亮色" if is_dark else "🌙 暗色"
    if st.button(label, key="_theme_toggle_btn", width="stretch"):
        new = "light" if is_dark else "dark"
        st.session_state[_THEME_KEY] = new
        try:
            st.query_params["theme"] = new
        except Exception:
            pass
        st.rerun()


def inject_theme_css():
    """Inject theme CSS with hardcoded color values.

    Call once in app.py after set_page_config, before any page content.

    Uses Python-level token values directly in the CSS rules — avoids
    CSS variable resolution issues where Streamlit's baseweb (Styletron)
    atomic CSS overrides everything.
    """
    theme = get_theme()
    manual = _THEME_KEY in st.session_state
    t = TOKEN_DARK if theme == "dark" else TOKEN_LIGHT

    # ── :root CSS variables for app.py global CSS block (var(--c-*)) ──
    if theme == "dark":
        root_vars = f"""
:root {{
    --c-bg: #0b0f19;
    --c-bg-secondary: #141928;
    --c-bg-tertiary: #1c2233;
    --c-surface: #141928;
    --c-surface-hover: #1c2233;
    --c-border: rgba(255,255,255,0.06);
    --c-border-light: rgba(255,255,255,0.04);
    --c-text: #e9ecf2;
    --c-text-secondary: #99a1b3;
    --c-text-muted: #616a80;
    --c-primary: #7984f5;
    --c-primary-bg: rgba(121,132,245,0.10);
    --c-primary-border: rgba(121,132,245,0.20);
    --c-success: #4ade80;
    --c-success-bg: rgba(74,222,128,0.08);
    --c-warning: #f59e0b;
    --c-warning-bg: rgba(245,158,11,0.08);
    --c-danger: #f87171;
    --c-danger-bg: rgba(248,113,113,0.08);
    --c-shadow-sm: 0 1px 2px rgba(0,0,0,0.3);
    --c-shadow: 0 4px 12px rgba(0,0,0,0.5);
    --c-sidebar-bg: #0b0f19;
}}"""
    else:
        root_vars = f"""
:root {{
    --c-bg: #f8fafc;
    --c-bg-secondary: #f1f5f9;
    --c-bg-tertiary: #e2e8f0;
    --c-surface: #ffffff;
    --c-surface-hover: #f8fafc;
    --c-border: #e2e8f0;
    --c-border-light: #f1f5f9;
    --c-text: #0f172a;
    --c-text-secondary: #475569;
    --c-text-muted: #94a3b8;
    --c-primary: #5c6cf0;
    --c-primary-bg: #eef2ff;
    --c-primary-border: #c7d2fe;
    --c-success: #059669;
    --c-success-bg: #ecfdf5;
    --c-warning: #d97706;
    --c-warning-bg: #fffbeb;
    --c-danger: #dc2626;
    --c-danger-bg: #fef2f2;
    --c-shadow-sm: 0 1px 2px rgba(0,0,0,0.04);
    --c-shadow: 0 2px 8px rgba(0,0,0,0.06);
    --c-sidebar-bg: #f8fafc;
}}"""

    # ── Element-level CSS with hardcoded values ──
    css = f"""<style>
{root_vars}


html, body, #root, [id="root"] {{
    background: {t["slate_bg"]} !important;
    margin: 0 !important;
    padding: 0 !important;
    min-height: 100vh !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

.stApp {{
    background: {t["slate_bg"]} !important;
    color: {t["text"]} !important;
    min-height: 100vh !important;
}}
.stApp > div {{
    background: {t["slate_bg"]} !important;
}}

[data-testid="stMain"] {{
    background: {t["slate_bg"]} !important;
}}
[data-testid="stMain"] > div {{
    background: {t["slate_bg"]} !important;
}}
[data-testid="stMain"] > div > div {{
    background: {t["slate_bg"]} !important;
}}
[data-testid="stAppViewContainer"] {{
    background: {t["slate_bg"]} !important;
}}
[data-testid="stAppViewContainer"] > div {{
    background: {t["slate_bg"]} !important;
}}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    min-width: 220px !important;
    max-width: 280px !important;
    background: {t["slate_bg"]} !important;
    border-right: 1px solid {t["slate_border"]} !important;
}}
[data-testid="stSidebar"] * {{
    color: {t["text"]} !important;
}}
[data-testid="stSidebar"] hr {{
    border-color: {t["slate_border"]} !important;
}}

/* ── Containers — border cards → subtle elevation ── */
[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_sm"]} !important;
    box-shadow: {t["shadow_xs"]} !important;
}}
.stHorizontalBlock > div {{
    background: transparent !important;
}}

/* ── Expanders ── */
.stExpander {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_sm"]} !important;
}}
.stExpander [data-testid="stExpanderDetails"] {{
    background: transparent !important;
}}

/* ── Text inputs, textareas, selects ── */
.stTextInput input,
.stTextInput input:focus,
.stTextArea textarea,
.stTextArea textarea:focus,
.stSelectbox > div > div,
[data-baseweb="input"],
[data-baseweb="input"] > div,
[data-baseweb="input"] input,
[data-baseweb="select"],
[data-baseweb="select"] > div {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border-color: {t["slate_border"]} !important;
    caret-color: {t["text"]} !important;
    border-radius: {t["radius_xs"]} !important;
    font-size: 0.82em !important;
}}
.stTextInput input::placeholder,
.stTextArea textarea::placeholder,
[data-baseweb="input"] input::placeholder {{
    color: {t["text_muted"]} !important;
}}
.stTextInput input:hover,
.stTextArea textarea:hover {{
    border-color: {"rgba(255,255,255,0.14)" if theme == "dark" else "#cbd5e1"} !important;
}}

/* ── Chat input ── */
[data-testid="stChatInput"],
[data-testid="stChatInput"] *,
[data-testid="stChatInput"] *::before,
[data-testid="stChatInput"] *::after,
[data-testid="stChatInput"] [data-baseweb],
[data-testid="stChatInput"] [data-baseweb] * {{
    background: {t["slate_bg"]} !important;
    border-color: {t["slate_border"]} !important;
    outline-color: {t["slate_border"]} !important;
    box-shadow: none !important;
}}
[data-testid="stChatInput"] textarea,
[data-testid="stChatInput"] [data-baseweb="input"] {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    caret-color: {t["text"]} !important;
    border-color: {t["slate_border"]} !important;
    border-radius: {t["radius_sm"]} !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{
    color: {t["text_muted"]} !important;
}}

/* ── Radio buttons ── */
.stRadio label {{
    border-color: {t["slate_border"]} !important;
    color: {t["text_sec"]} !important;
    background: {t["card_bg"]} !important;
    border-radius: {t["radius_xs"]} !important;
    font-size: 0.8em !important;
}}
.stRadio label:hover {{
    border-color: {t["primary_border"]} !important;
    background: {t["primary_bg"]} !important;
}}

/* ── Tabs — subtle underline style ── */
.stTabs [data-baseweb="tab"] {{
    color: {t["text_muted"]} !important;
    font-size: 0.82em !important;
    font-weight: 500 !important;
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{
    color: {t["primary"]} !important;
}}

/* ── Metric cards ── */
[data-testid="stMetric"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_sm"]} !important;
    box-shadow: {t["shadow_xs"]} !important;
}}
[data-testid="stMetric"] label {{
    color: {t["text_muted"]} !important;
    font-size: 0.72em !important;
    font-weight: 500 !important;
    letter-spacing: 0.02em !important;
    text-transform: uppercase !important;
}}
[data-testid="stMetric"] [data-testid="stMetricValue"] {{
    color: {t["text"]} !important;
    font-weight: 600 !important;
}}

/* ── Chat messages ── */
[data-testid="stChatMessage"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius"]} !important;
}}
[data-testid="stChatMessage"][aria-label*="user"] {{
    background: {t["primary_bg"]} !important;
    border-color: {t["primary_border"]} !important;
}}
[data-testid="stChatMessage"][aria-label*="assistant"] {{
    background: {t["card_bg"]} !important;
    border-color: {t["slate_border"]} !important;
}}

/* ── Buttons — ghost style, minimal ── */
.stButton > button {{
    background: {t["card_bg"]} !important;
    color: {t["text_sec"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_xs"]} !important;
    font-size: 0.8em !important;
    font-weight: 500 !important;
    transition: all {t["transition"]} !important;
    min-height: 32px !important;
    padding: 4px 12px !important;
}}
.stButton > button:hover {{
    border-color: {t["primary_border"]} !important;
    background: {t["primary_bg"]} !important;
    color: {t["text"]} !important;
}}
.stButton > button[kind="primary"] {{
    background: {t["primary"]} !important;
    color: #fff !important;
    border-color: transparent !important;
    font-weight: 600 !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: {t["primary_hover"]} !important;
    filter: none !important;
}}

/* ── Select dropdown popover ── */
[data-baseweb="popover"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_sm"]} !important;
    box-shadow: {t["shadow_md"]} !important;
}}
[data-baseweb="popover"] li,
[data-baseweb="popover"] div {{
    color: {t["text"]} !important;
    background: transparent !important;
}}
[data-baseweb="popover"] li:hover,
[data-baseweb="popover"] li[aria-selected="true"] {{
    background: {t["primary_bg"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}

/* ── Toast ── */
[data-testid="stToast"] {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_sm"]} !important;
    box-shadow: {t["shadow_md"]} !important;
}}

/* ── Caption / small text ── */
.stCaption, .stCaptionContainer, [data-testid="stCaptionContainer"] {{
    color: {t["text_muted"]} !important;
    font-size: 0.78em !important;
}}

/* ── Alerts ── */
.stAlert {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    color: {t["text"]} !important;
    border-radius: {t["radius_sm"]} !important;
}}
.stAlert [data-testid="stMarkdownContainer"] {{
    color: {t["text"]} !important;
}}

/* ── Main content area ── */
.block-container {{
    color: {t["text"]};
    background: transparent !important;
}}

/* ── Dividers — subtle, barely visible ── */
hr {{
    border-color: {t["slate_border"]} !important;
    margin: 20px 0 !important;
    border-width: 0.5px !important;
    opacity: 0.6;
}}

/* ── Code blocks ── */
code, pre {{
    background: {t["slate_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}

/* ── Tables / DataFrames ── */
[data-testid="stTable"] table {{
    background: transparent !important;
    color: {t["text"]} !important;
}}
[data-testid="stTable"] th {{
    background: {t["slate_bg"]} !important;
    color: {t["text_muted"]} !important;
    font-weight: 500 !important;
    font-size: 0.75em !important;
    text-transform: uppercase !important;
    letter-spacing: 0.03em !important;
}}
[data-testid="stTable"] td {{
    color: {t["text"]} !important;
    border-color: {t["slate_border"]} !important;
    font-size: 0.82em !important;
}}

/* ── Scrollbar — thin, subtle ── */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-thumb {{
    background: {"rgba(255,255,255,0.08)" if theme == "dark" else "rgba(0,0,0,0.10)"} !important;
    border-radius: 3px;
}}
::-webkit-scrollbar-track {{
    background: transparent !important;
}}
::-webkit-scrollbar-thumb:hover {{
    background: {"rgba(255,255,255,0.14)" if theme == "dark" else "rgba(0,0,0,0.18)"} !important;
}}

/* ── Charts ── */
.vega-embed {{
    background: transparent !important;
}}
.vega-embed canvas {{
    background: transparent !important;
}}

/* ── Markdown ── */
[data-testid="stMarkdownContainer"] {{
    color: {t["text"]};
}}

/* ── Spinner ── */
.stSpinner {{
    border-color: {t["slate_border"]} !important;
    border-top-color: {t["primary"]} !important;
}}

/* ── Date / number inputs ── */
.stDateInput input,
.stNumberInput input,
[data-baseweb="input"] {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border-color: {t["slate_border"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}

/* ── Checkbox ── */
[data-baseweb="checkbox"] {{
    background: {t["card_bg"]} !important;
}}

/* ── Tooltip ── */
[data-baseweb="tooltip"] {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}

/* ── Status indicator ── */
[data-testid="stStatus"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    color: {t["text"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}

/* ── Download button ── */
[data-testid="stDownloadButton"] button {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["slate_border"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}

/* ── Multiselect tags ── */
[data-baseweb="tag"] {{
    background: {t["primary_bg"]} !important;
    color: {t["primary"]} !important;
    border-radius: {t["radius_xs"]} !important;
}}
</style>"""
    st.markdown(css, unsafe_allow_html=True)
