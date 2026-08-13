# ui/theme.py
"""Theme system — community service counter: warm paper + dual indigo/violet brand.

Design:
  - Light is DEFAULT. Dark available via toggle.
  - TWO brand colors: indigo #4f46e5 (primary actions, selection, active) and
    violet #7c3aed (community-life accent: 议事/活动/通知/邻里温度). Neither is
    used on card borders, dividers, or decoration.
  - Semantic colors (green/amber/red) appear ONLY on status tags and KPI values.
  - Warm neutrals throughout (paper ground, warm near-black text) — no cold gray.
  - 8 community categories get a color-dot (see ui/components.CAT_COLORS).
  - 4 font sizes. 3 font weights. No micro-tuning.
"""

import logging
import streamlit as st  # noqa: F401

_log = logging.getLogger(__name__)

# Light tokens (DEFAULT)
TOKEN_LIGHT = {
        "accent":           "#4f46e5",
    "accent_hover":     "#4338ca",
    "accent_bg":        "#eef0ff",
    "accent_border":    "#cfd4f8",

        "accent2":          "#7c3aed",
    "accent2_hover":    "#6d28d9",
    "accent2_bg":       "#f3eefd",
    "accent2_border":   "#ddd0fb",

        "brand_gradient":   "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
    "brand_gradient_hover": "linear-gradient(135deg, #4338ca 0%, #6d28d9 100%)",

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

        "page_bg":          "#faf9f7",
    "sidebar_bg":       "#f4f1ec",
    "sidebar_surface":  "#ffffff",
    "sidebar_border":   "#e9e5df",
    "sidebar_text":     "#1f1d19",
    "sidebar_text_sec": "#6b665e",
    "sidebar_text_muted": "#9c958a",
    "sidebar_accent":   "#4f46e5",
    "sidebar_accent_bg":"#eef0ff",
    "sidebar_warn_bg":  "#fffbeb",
    "sidebar_warn":     "#d97706",
    "sidebar_dang_bg":  "#fef2f2",
    "sidebar_dang":     "#dc2626",
    "sidebar_succ_bg":  "#ecfdf5",
    "sidebar_succ":     "#059669",
    "surface":          "#f4f1ec",
    "card_bg":          "#ffffff",
    "card_hover":       "#fafaf8",
    "input_bg":         "#ffffff",
    "border":           "#e9e5df",
    "border_visible":   "#d8d3cb",
    "border_focus":     "#cfc9f5",
    "divider":          "#e9e5df",

        "text":             "#1f1d19",
    "text_sec":         "#6b665e",
    "text_muted":       "#9c958a",
    "text_inverse":     "#ffffff",

        "font_display":     "1.35em",
    "font_body":        "0.875em",
    "font_label":       "0.75em",
    "font_micro":       "0.6875em",
    "weight_bold":       "700",
    "weight_semibold":   "600",
    "weight_medium":     "500",
    "tracking_label":    "0.04em",

        "space_2xs":        "4px",
    "space_xs":         "8px",
    "space_sm":         "12px",
    "space_md":         "16px",
    "space_lg":         "20px",
    "space_xl":         "24px",
    "space_2xl":        "32px",

        "radius_input":     "8px",
    "radius_card":      "10px",
    "radius_full":      "99px",

        "shadow_none":      "none",
    "shadow_sm":        "0 1px 2px rgba(31,29,25,0.05)",
    "shadow":           "0 1px 3px rgba(31,29,25,0.07)",
    "shadow_md":        "0 4px 16px rgba(31,29,25,0.08)",

        "transition":       "0.15s ease",

        "chart_grid":       "rgba(31,29,25,0.06)",
}

# Dark tokens
TOKEN_DARK = {
        "accent":           "#6d6bf5",
    "accent_hover":     "#807ef7",
    "accent_bg":        "rgba(109,107,245,0.10)",
    "accent_border":    "rgba(109,107,245,0.18)",

        "accent2":          "#a78bfa",
    "accent2_hover":    "#b9a0fb",
    "accent2_bg":       "rgba(167,139,250,0.10)",
    "accent2_border":   "rgba(167,139,250,0.18)",

        "brand_gradient":   "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
    "brand_gradient_hover": "linear-gradient(135deg, #4338ca 0%, #6d28d9 100%)",

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

        "page_bg":          "#12100d",
    "sidebar_bg":       "#1a1713",
    "sidebar_surface":  "#201c17",
    "sidebar_border":   "#2c2822",
    "sidebar_text":     "#ece9e4",
    "sidebar_text_sec": "#a39d92",
    "sidebar_text_muted": "#6b665d",
    "sidebar_accent":   "#6d6bf5",
    "sidebar_accent_bg":"rgba(109,107,245,0.10)",
    "sidebar_warn_bg":  "rgba(251,191,36,0.08)",
    "sidebar_warn":     "#fbbf24",
    "sidebar_dang_bg":  "rgba(248,113,113,0.08)",
    "sidebar_dang":     "#f87171",
    "sidebar_succ_bg":  "rgba(52,211,153,0.08)",
    "sidebar_succ":     "#34d399",
    "surface":          "#1a1713",
    "card_bg":          "#201c17",
    "card_hover":       "#262119",
    "input_bg":         "#1c1915",
    "border":           "#2c2822",
    "border_visible":   "#38332c",
    "border_focus":     "rgba(109,107,245,0.25)",
    "divider":          "#2c2822",

        "text":             "#ece9e4",
    "text_sec":         "#a39d92",
    "text_muted":       "#6b665d",
    "text_inverse":     "#12100d",

        "font_display":     "1.35em",
    "font_body":        "0.875em",
    "font_label":       "0.75em",
    "font_micro":       "0.6875em",
    "weight_bold":       "700",
    "weight_semibold":   "600",
    "weight_medium":     "500",
    "tracking_label":    "0.04em",

        "space_2xs":        "4px",
    "space_xs":         "8px",
    "space_sm":         "12px",
    "space_md":         "16px",
    "space_lg":         "20px",
    "space_xl":         "24px",
    "space_2xl":        "32px",

        "radius_input":     "8px",
    "radius_card":      "10px",
    "radius_full":      "99px",

        "shadow_none":      "none",
    "shadow_sm":        "0 1px 2px rgba(0,0,0,0.4)",
    "shadow":           "0 2px 8px rgba(0,0,0,0.5)",
    "shadow_md":        "0 8px 24px rgba(0,0,0,0.6)",

        "transition":       "0.15s ease",

        "chart_grid":       "rgba(255,255,255,0.04)",
}

# Theme state management
_THEME_KEY = "_community_theme_v4"


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
            _log.debug("Failed to read theme from query params at startup", exc_info=True)
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
        _log.debug("Failed to read theme from query params in get_theme", exc_info=True)
        pass
    return "light"


def get_token() -> dict:
    return TOKEN_DARK if get_theme() == "dark" else TOKEN_LIGHT


def apply_native_theme():
    """Override Streamlit engine colors. Call AFTER st.set_page_config()."""
    theme = get_theme()
    try:
        if theme == "dark":
            st._config.set_option("theme.backgroundColor", "#12100d")
            st._config.set_option("theme.secondaryBackgroundColor", "#1a1713")
            st._config.set_option("theme.textColor", "#ece9e4")
        else:
            st._config.set_option("theme.backgroundColor", "#faf9f7")
            st._config.set_option("theme.secondaryBackgroundColor", "#f4f1ec")
            st._config.set_option("theme.textColor", "#1f1d19")
    except Exception:
        _log.debug("Failed to set native theme config options", exc_info=True)
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
            _log.debug("non-critical failure", exc_info=True)
            pass
        st.rerun()


def inject_theme_css():
    """Inject theme CSS. Call once in app.py after set_page_config."""
    theme = get_theme()
    t = TOKEN_DARK if theme == "dark" else TOKEN_LIGHT

    # ── Mobile viewport ──
    st.markdown("""<meta name="viewport" content="width=device-width, \
initial-scale=1.0, maximum-scale=1.0, user-scalable=no">""",
                unsafe_allow_html=True)

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
    --c-accent2: {t["accent2"]};
    --c-accent2-bg: {t["accent2_bg"]};
    --c-accent2-border: {t["accent2_border"]};
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

/* ── Sidebar (warm surface, matches main content) ── */
@media (min-width: 769px) {{
    [data-testid="stSidebar"] {{
        min-width: 220px !important;
        max-width: 280px !important;
        background: {t["sidebar_bg"]} !important;
        border-right: 1px solid {t["sidebar_border"]} !important;
    }}
}}
[data-testid="stSidebar"] {{
    background: {t["sidebar_bg"]} !important;
}}
[data-testid="stSidebar"] * {{
    color: {t["sidebar_text"]} !important;
}}
[data-testid="stSidebar"] hr {{
    border-color: {t["sidebar_border"]} !important;
}}
[data-testid="stSidebar"] .stButton > button {{
    background: {t["sidebar_surface"]} !important;
    color: {t["sidebar_text"]} !important;
    border-color: {t["sidebar_border"]} !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    border-color: {t["sidebar_accent"]} !important;
    background: {t["sidebar_accent_bg"]} !important;
    color: {t["sidebar_accent"]} !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: {t["brand_gradient"]} !important;
    color: #fff !important;
    border-color: transparent !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] > div {{
    background: {t["sidebar_surface"]} !important;
    border-color: {t["sidebar_border"]} !important;
}}
[data-testid="stSidebar"] [data-baseweb="select"] * {{
    color: {t["sidebar_text"]} !important;
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
    background: {t["brand_gradient"]} !important;
    color: #ffffff !important;
    border: none !important;
    font-weight: {t["weight_semibold"]} !important;
    box-shadow: 0 4px 12px rgba(79,70,229,0.28) !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: {t["brand_gradient_hover"]} !important;
    box-shadow: 0 6px 18px rgba(79,70,229,0.36) !important;
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
    background: {t["brand_gradient"]} !important;
    border: none !important;
    box-shadow: 0 4px 14px rgba(79,70,229,0.24) !important;
}}
[data-testid="stChatMessage"][aria-label*="user"] [data-testid="stMarkdownContainer"] {{
    color: #ffffff !important;
}}
[data-testid="stChatMessage"][aria-label*="user"] [data-testid="stCaptionContainer"],
[data-testid="stChatMessage"][aria-label*="user"] .stCaption {{
    color: rgba(255,255,255,0.78) !important;
}}
[data-testid="stChatMessage"][aria-label*="assistant"] {{
    background: {t["card_bg"]} !important;
    border: 1px solid {t["border"]} !important;
    border-left: 3px solid {t["accent"]} !important;
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
    background: {"rgba(255,255,255,0.10)" if theme == "dark" else "rgba(31,29,25,0.12)"} !important;
    border-radius: 3px;
}}
::-webkit-scrollbar-track {{ background: transparent !important; }}
::-webkit-scrollbar-thumb:hover {{
    background: {"rgba(255,255,255,0.16)" if theme == "dark" else "rgba(31,29,25,0.20)"} !important;
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

/* ═══════════════════════════════════════════
   Responsive
   ═══════════════════════════════════════════ */

/* ── ≤768px ── */
@media (max-width: 768px) {{
    [data-testid="stHorizontalBlock"] {{
        flex-direction: column !important;
        gap: 8px !important;
    }}
    [data-testid="stHorizontalBlock"] > div {{
        flex: 1 1 100% !important;
        max-width: 100% !important;
    }}

    .stButton > button {{
        width: 100% !important;
        min-height: 44px !important;
        font-size: 0.9em !important;
    }}

    [data-testid="stVerticalBlockBorderWrapper"] {{
        padding: 10px !important;
    }}

    [data-testid="stMetric"] {{
        padding: 8px 10px !important;
    }}
    [data-testid="stMetric"] [data-testid="stMetricValue"] {{
        font-size: 1.3em !important;
    }}
    [data-testid="stMetric"] label {{
        font-size: 0.68em !important;
    }}

    .stTabs [data-baseweb="tab"] {{
        font-size: 0.8em !important;
        padding: 6px 10px !important;
    }}

    [data-testid="stSidebar"] {{
        min-width: unset !important;
        max-width: unset !important;
    }}

    [data-testid="stChatMessage"] {{
        padding: 10px 12px !important;
    }}
}}

/* ── ≤480px ── */
@media (max-width: 480px) {{
    button,
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-secondary"],
    [kind="primary"],
    [kind="secondary"] {{
        min-height: 44px !important;
        font-size: 0.95em !important;
        padding: 8px 16px !important;
    }}

    input, select, textarea,
    [data-baseweb="input"],
    [data-baseweb="select"] {{
        font-size: 16px !important;
    }}

    [data-testid="stVerticalBlockBorderWrapper"] {{
        padding: 8px !important;
        border-radius: 4px !important;
    }}

    h1 {{ font-size: 1.3em !important; }}
    h2 {{ font-size: 1.15em !important; }}
    h3 {{ font-size: 1em !important; }}

    .block-container {{
        padding: 12px 8px !important;
    }}

    [data-testid="stChatInput"] {{
        padding: 6px 8px !important;
    }}

    .stExpander {{
        padding: 6px 10px !important;
    }}

    [data-testid="stTable"] {{
        overflow-x: auto !important;
    }}
    [data-testid="stTable"] table {{
        font-size: 0.75em !important;
    }}
    [data-testid="stTable"] th,
    [data-testid="stTable"] td {{
        padding: 4px 6px !important;
    }}
}}
</style>"""
    st.markdown(css, unsafe_allow_html=True)
