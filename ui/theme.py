# ui/theme.py
"""Theme system — enterprise SaaS, cold gray + single indigo accent.

Design:
  - Light is DEFAULT. Dark available via toggle.
  - ONE accent color (#4f46e5). Used only on primary buttons, selection,
    active indicators. Never on card borders, dividers, or decoration.
  - Semantic colors (green/amber/red) appear ONLY on status tags and KPI values.
  - Cold grays throughout. No warm tones.
  - 4 font sizes. 2 font weights. No micro-tuning.
"""

import streamlit as st  # noqa: F401

# Light tokens (DEFAULT)
TOKEN_LIGHT = {
        "accent":           "#4f46e5",
    "accent_hover":     "#4338ca",
    "accent_bg":        "#f0efff",
    "accent_border":    "#d2d0f8",

        "success":          "#059669",
    "success_bg":       "#ecfdf5",
    "success_border":   "#a7f3d0",
    "warning":          "#d97706",
    "warning_bg":       "#fffbeb",
    "warning_border":   "#fde68a",
    "danger":           "#dc2626",
    "danger_bg":        "#fef2f2",
    "danger_border":    "#fecaca",
    "info":             "#0891b2",
    "info_bg":          "#ecfeff",
    "info_border":      "#a5f3fc",

        "page_bg":          "#fafafa",
    "sidebar_bg":       "#f5f5f5",
    "surface":          "#f5f5f5",
    "card_bg":          "#ffffff",
    "card_hover":       "#fafafa",
    "input_bg":         "#ffffff",
    "border":           "#ebebeb",
    "border_visible":   "#dcdcdc",
    "border_focus":     "#d0d0f0",
    "divider":          "#ebebeb",

        "text":             "#1a1a1a",
    "text_sec":         "#6e6e6e",
    "text_muted":       "#a0a0a0",
    "text_inverse":     "#ffffff",

        "font_display":     "1.25em",
    "font_body":        "0.875em",
    "font_label":       "0.75em",
    "font_micro":       "0.6875em",
    "weight_bold":       "700",
    "weight_medium":     "500",
    "tracking_label":    "0.04em",

        "space_2xs":        "4px",
    "space_xs":         "8px",
    "space_sm":         "12px",
    "space_md":         "16px",
    "space_lg":         "20px",
    "space_xl":         "24px",
    "space_2xl":        "32px",

        "radius_input":     "4px",
    "radius_card":      "6px",
    "radius_full":      "99px",

        "shadow_none":      "none",
    "shadow_sm":        "0 1px 2px rgba(0,0,0,0.04)",
    "shadow":           "0 1px 3px rgba(0,0,0,0.06)",
    "shadow_md":        "0 4px 16px rgba(0,0,0,0.06)",

        "transition":       "0.15s ease",

        "chart_grid":       "rgba(0,0,0,0.05)",
}

# Dark tokens
TOKEN_DARK = {
        "accent":           "#6d6bf5",
    "accent_hover":     "#807ef7",
    "accent_bg":        "rgba(109,107,245,0.10)",
    "accent_border":    "rgba(109,107,245,0.18)",

        "success":          "#34d399",
    "success_bg":       "rgba(52,211,153,0.08)",
    "success_border":   "rgba(52,211,153,0.16)",
    "warning":          "#fbbf24",
    "warning_bg":       "rgba(251,191,36,0.08)",
    "warning_border":   "rgba(251,191,36,0.16)",
    "danger":           "#f87171",
    "danger_bg":        "rgba(248,113,113,0.08)",
    "danger_border":    "rgba(248,113,113,0.16)",
    "info":             "#22d3ee",
    "info_bg":          "rgba(34,211,238,0.08)",
    "info_border":      "rgba(34,211,238,0.16)",

        "page_bg":          "#0a0a0f",
    "sidebar_bg":       "#0e0e14",
    "surface":          "#111118",
    "card_bg":          "#18181f",
    "card_hover":       "#1e1e26",
    "input_bg":         "#14141a",
    "border":           "#25252e",
    "border_visible":   "#2e2e38",
    "border_focus":     "rgba(109,107,245,0.25)",
    "divider":          "#25252e",

        "text":             "#e8e8ed",
    "text_sec":         "#9898a2",
    "text_muted":       "#5e5e6a",
    "text_inverse":     "#0a0a0f",

        "font_display":     "1.25em",
    "font_body":        "0.875em",
    "font_label":       "0.75em",
    "font_micro":       "0.6875em",
    "weight_bold":       "700",
    "weight_medium":     "500",
    "tracking_label":    "0.04em",

        "space_2xs":        "4px",
    "space_xs":         "8px",
    "space_sm":         "12px",
    "space_md":         "16px",
    "space_lg":         "20px",
    "space_xl":         "24px",
    "space_2xl":        "32px",

        "radius_input":     "4px",
    "radius_card":      "6px",
    "radius_full":      "99px",

        "shadow_none":      "none",
    "shadow_sm":        "0 1px 2px rgba(0,0,0,0.4)",
    "shadow":           "0 2px 8px rgba(0,0,0,0.5)",
    "shadow_md":        "0 8px 24px rgba(0,0,0,0.6)",

        "transition":       "0.15s ease",

        "chart_grid":       "rgba(255,255,255,0.04)",
}

# Theme state management
_THEME_KEY = "_campus_theme_v4"


def apply_theme_at_startup():
    """Set default theme to light before st.set_page_config."""
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
    return TOKEN_DARK if get_theme() == "dark" else TOKEN_LIGHT


def apply_native_theme():
    """Override Streamlit engine colors. Call AFTER st.set_page_config()."""
    theme = get_theme()
    try:
        if theme == "dark":
            st._config.set_option("theme.backgroundColor", "#0a0a0f")
            st._config.set_option("theme.secondaryBackgroundColor", "#111118")
            st._config.set_option("theme.textColor", "#e8e8ed")
        else:
            st._config.set_option("theme.backgroundColor", "#fafafa")
            st._config.set_option("theme.secondaryBackgroundColor", "#f5f5f5")
            st._config.set_option("theme.textColor", "#1a1a1a")
    except Exception:
        pass


def theme_toggle():
    theme = get_theme()
    is_dark = theme == "dark"
    label = "☀️ Light" if is_dark else "🌙 Dark"
    if st.button(label, key="_theme_toggle_btn", width="stretch"):
        new = "light" if is_dark else "dark"
        st.session_state[_THEME_KEY] = new
        try:
            st.query_params["theme"] = new
        except Exception:
            pass
        st.rerun()


def inject_theme_css():
    """Inject theme CSS. Call once in app.py after set_page_config."""
    theme = get_theme()
    t = TOKEN_DARK if theme == "dark" else TOKEN_LIGHT

    root_vars = f"""
:root {{
    --c-bg: {t["page_bg"]};
    --c-bg-secondary: {t["surface"]};
    --c-surface: {t["card_bg"]};
    --c-surface-hover: {t["card_hover"]};
    --c-border: {t["border"]};
    --c-border-visible: {t["border_visible"]};
    --c-text: {t["text"]};
    --c-text-secondary: {t["text_sec"]};
    --c-text-muted: {t["text_muted"]};
    --c-accent: {t["accent"]};
    --c-accent-bg: {t["accent_bg"]};
    --c-accent-border: {t["accent_border"]};
    --c-success: {t["success"]};
    --c-success-bg: {t["success_bg"]};
    --c-warning: {t["warning"]};
    --c-warning-bg: {t["warning_bg"]};
    --c-danger: {t["danger"]};
    --c-danger-bg: {t["danger_bg"]};
    --c-shadow-sm: {t["shadow_sm"]};
    --c-shadow: {t["shadow"]};
    --c-sidebar-bg: {t["sidebar_bg"]};
    --c-input-bg: {t["input_bg"]};
}}"""

    css = f"""<style>
{root_vars}

/* ═══════════════════════════════════════════
   Foundation
   ═══════════════════════════════════════════ */

html, body, #root, [id="root"] {{
    background: {t["page_bg"]} !important;
    margin: 0 !important;
    padding: 0 !important;
    min-height: 100vh !important;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

.stApp {{
    background: {t["page_bg"]} !important;
    color: {t["text"]} !important;
    min-height: 100vh !important;
}}
.stApp > div {{
    background: {t["page_bg"]} !important;
}}

[data-testid="stMain"],
[data-testid="stMain"] > div,
[data-testid="stMain"] > div > div,
[data-testid="stAppViewContainer"],
[data-testid="stAppViewContainer"] > div {{
    background: {t["page_bg"]} !important;
}}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    min-width: 220px !important;
    max-width: 280px !important;
    background: {t["sidebar_bg"]} !important;
    border-right: 1px solid {t["border"]} !important;
}}
[data-testid="stSidebar"] * {{
    color: {t["text"]} !important;
}}
[data-testid="stSidebar"] hr {{
    border-color: {t["border"]} !important;
}}

/* ── Cards ── */
[data-testid="stVerticalBlockBorderWrapper"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: {t["radius_card"]} !important;
    box-shadow: {t["shadow_sm"]} !important;
}}

/* ── Expanders ── */
.stExpander {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: {t["radius_card"]} !important;
}}
.stExpander [data-testid="stExpanderDetails"] {{
    background: transparent !important;
}}

/* ── Inputs ── */
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
    background: {t["input_bg"]} !important;
    color: {t["text"]} !important;
    border-color: {t["border"]} !important;
    caret-color: {t["accent"]} !important;
    border-radius: {t["radius_input"]} !important;
    font-size: {t["font_body"]} !important;
}}
.stTextInput input::placeholder,
.stTextArea textarea::placeholder,
[data-baseweb="input"] input::placeholder {{
    color: {t["text_muted"]} !important;
}}
.stTextInput input:hover,
.stTextArea textarea:hover {{
    border-color: {t["border_visible"]} !important;
}}

/* ── Chat input ── */
[data-testid="stChatInput"],
[data-testid="stChatInput"] *,
[data-testid="stChatInput"] *::before,
[data-testid="stChatInput"] *::after,
[data-testid="stChatInput"] [data-baseweb],
[data-testid="stChatInput"] [data-baseweb] * {{
    background: {t["page_bg"]} !important;
    border-color: {t["border"]} !important;
    outline-color: {t["border"]} !important;
    box-shadow: none !important;
}}
[data-testid="stChatInput"] textarea,
[data-testid="stChatInput"] [data-baseweb="input"] {{
    background: {t["input_bg"]} !important;
    color: {t["text"]} !important;
    caret-color: {t["accent"]} !important;
    border-color: {t["border_visible"]} !important;
    border-radius: {t["radius_card"]} !important;
}}
[data-testid="stChatInput"] textarea::placeholder {{
    color: {t["text_muted"]} !important;
}}

/* ── Buttons ── */
.stButton > button {{
    background: {t["card_bg"]} !important;
    color: {t["text_sec"]} !important;
    border: 1px solid {t["border_visible"]} !important;
    border-radius: {t["radius_input"]} !important;
    font-size: {t["font_label"]} !important;
    font-weight: {t["weight_medium"]} !important;
    transition: all {t["transition"]} !important;
    min-height: 32px !important;
    padding: 4px 14px !important;
}}
.stButton > button:hover {{
    border-color: {t["accent_border"]} !important;
    background: {t["accent_bg"]} !important;
    color: {t["accent"]} !important;
}}
.stButton > button[kind="primary"] {{
    background: {t["accent"]} !important;
    color: #fff !important;
    border-color: transparent !important;
    font-weight: {t["weight_bold"]} !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: {t["accent_hover"]} !important;
    filter: none !important;
}}

/* ── Tabs ── */
.stTabs [data-baseweb="tab"] {{
    color: {t["text_muted"]} !important;
    font-size: {t["font_body"]} !important;
    font-weight: {t["weight_medium"]} !important;
}}
.stTabs [data-baseweb="tab"][aria-selected="true"] {{
    color: {t["accent"]} !important;
}}

/* ── Radio ── */
.stRadio label {{
    border-color: {t["border"]} !important;
    color: {t["text_sec"]} !important;
    background: {t["card_bg"]} !important;
    border-radius: {t["radius_card"]} !important;
    font-size: {t["font_body"]} !important;
}}
.stRadio label:hover {{
    border-color: {t["accent_border"]} !important;
    background: {t["accent_bg"]} !important;
}}

/* ── Select popover ── */
[data-baseweb="popover"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border_visible"]} !important;
    border-radius: {t["radius_card"]} !important;
    box-shadow: {t["shadow_md"]} !important;
}}
[data-baseweb="popover"] li,
[data-baseweb="popover"] div {{
    color: {t["text"]} !important;
    background: transparent !important;
}}
[data-baseweb="popover"] li:hover,
[data-baseweb="popover"] li[aria-selected="true"] {{
    background: {t["accent_bg"]} !important;
    border-radius: {t["radius_input"]} !important;
}}

/* ── Toast ── */
[data-testid="stToast"] {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["border_visible"]} !important;
    border-radius: {t["radius_card"]} !important;
    box-shadow: {t["shadow_md"]} !important;
}}

/* ── Caption ── */
.stCaption, .stCaptionContainer, [data-testid="stCaptionContainer"] {{
    color: {t["text_muted"]} !important;
    font-size: {t["font_label"]} !important;
}}

/* ── Metric ── */
[data-testid="stMetric"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: {t["radius_card"]} !important;
    box-shadow: {t["shadow_sm"]} !important;
}}
[data-testid="stMetric"] label {{
    color: {t["text_muted"]} !important;
    font-size: {t["font_label"]} !important;
    font-weight: {t["weight_medium"]} !important;
    letter-spacing: {t["tracking_label"]} !important;
    text-transform: uppercase !important;
}}
[data-testid="stMetric"] [data-testid="stMetricValue"] {{
    color: {t["text"]} !important;
    font-weight: {t["weight_bold"]} !important;
}}

/* ── Chat messages ── */
[data-testid="stChatMessage"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: {t["radius_card"]} !important;
}}
[data-testid="stChatMessage"][aria-label*="user"] {{
    background: {t["accent_bg"]} !important;
    border-color: {t["accent_border"]} !important;
}}
[data-testid="stChatMessage"][aria-label*="assistant"] {{
    background: {t["card_bg"]} !important;
    border-color: {t["border"]} !important;
}}

/* ── Alerts ── */
.stAlert {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border_visible"]} !important;
    color: {t["text"]} !important;
    border-radius: {t["radius_card"]} !important;
}}
.stAlert [data-testid="stMarkdownContainer"] {{
    color: {t["text"]} !important;
}}

/* ── Dividers ── */
hr {{
    border-color: {t["border"]} !important;
    margin: 20px 0 !important;
    border-width: 0.5px !important;
}}

/* ── Tables ── */
[data-testid="stTable"] table {{ background: transparent !important; color: {t["text"]} !important; }}
[data-testid="stTable"] th {{
    background: {t["surface"]} !important;
    color: {t["text_muted"]} !important;
    font-weight: {t["weight_medium"]} !important;
    font-size: {t["font_label"]} !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}}
[data-testid="stTable"] td {{
    color: {t["text"]} !important;
    border-color: {t["border"]} !important;
    font-size: {t["font_body"]} !important;
}}

/* ── Scrollbar ── */
::-webkit-scrollbar {{ width: 5px; height: 5px; }}
::-webkit-scrollbar-thumb {{
    background: {"rgba(255,255,255,0.10)" if theme == "dark" else "rgba(0,0,0,0.12)"} !important;
    border-radius: 3px;
}}
::-webkit-scrollbar-track {{ background: transparent !important; }}
::-webkit-scrollbar-thumb:hover {{
    background: {"rgba(255,255,255,0.16)" if theme == "dark" else "rgba(0,0,0,0.20)"} !important;
}}

/* ── Charts ── */
.vega-embed {{ background: transparent !important; }}
.vega-embed canvas {{ background: transparent !important; }}

/* ── Status indicator ── */
[data-testid="stStatus"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border"]} !important;
    color: {t["text"]} !important;
    border-radius: {t["radius_card"]} !important;
}}

/* ── Checkbox ── */
[data-baseweb="checkbox"] {{ background: {t["input_bg"]} !important; }}

/* ── Multiselect tags ── */
[data-baseweb="tag"] {{
    background: {t["accent_bg"]} !important;
    color: {t["accent"]} !important;
    border-radius: {t["radius_input"]} !important;
}}

/* ── Tooltip ── */
[data-baseweb="tooltip"] {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["border_visible"]} !important;
    border-radius: {t["radius_input"]} !important;
}}

/* ── Spinner ── */
.stSpinner {{
    border-color: {t["border"]} !important;
    border-top-color: {t["accent"]} !important;
}}

/* ── Block container ── */
.block-container {{
    color: {t["text"]};
    background: transparent !important;
}}

/* ── Date / number inputs ── */
.stDateInput input,
.stNumberInput input {{
    background: {t["input_bg"]} !important;
    color: {t["text"]} !important;
    border-color: {t["border"]} !important;
    border-radius: {t["radius_input"]} !important;
}}

/* ── Code ── */
code, pre {{
    background: {t["surface"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["border"]} !important;
    border-radius: {t["radius_input"]} !important;
}}

/* ── Markdown ── */
[data-testid="stMarkdownContainer"] {{ color: {t["text"]}; }}

/* ── Download button ── */
[data-testid="stDownloadButton"] button {{
    background: {t["card_bg"]} !important;
    color: {t["text"]} !important;
    border: 1px solid {t["border_visible"]} !important;
    border-radius: {t["radius_input"]} !important;
}}
</style>"""
    st.markdown(css, unsafe_allow_html=True)
