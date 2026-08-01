# ui/components.py
"""Design system — enterprise SaaS components for CampusInsight."""
import logging
import streamlit as st
from contextlib import contextmanager
from datetime import datetime
from utils.text import split_thinking  # re-export

_log = logging.getLogger(__name__)


class _ThemeAwareToken:
    def __init__(self):
        self._theme = None
        self._dict = None

    def _resolve(self):
        from ui.theme import get_token, get_theme
        t = get_theme()
        if self._theme != t:
            self._theme = t
            self._dict = get_token()
        return self._dict

    def __getitem__(self, key):
        return self._resolve()[key]

    def get(self, key, default=None):
        return self._resolve().get(key, default)

    def __contains__(self, key):
        return key in self._resolve()

    def keys(self):
        return self._resolve().keys()

    def values(self):
        return self._resolve().values()

    def items(self):
        return self._resolve().items()


TOKEN = _ThemeAwareToken()

CAT_LABEL = {
    "设施维修": "设施维修", "环境卫生": "环境卫生", "安全隐患": "安全隐患",
    "教学设备": "教学设备", "网络服务": "网络服务", "餐饮问题": "餐饮问题",
    "校园管理": "校园管理", "其他": "其他",
}


# Status tag

_STATUS_TOKEN_KEYS = {
    "待处理": ("danger_bg", "danger_border", "danger"),
    "处理中": ("warning_bg", "warning_border", "warning"),
    "已解决": ("success_bg", "success_border", "success"),
    "讨论中": ("accent_bg", "accent_border", "accent"),
    "已回应": ("info_bg", "info_border", "info"),
    "已采纳": ("success_bg", "success_border", "success"),
    "已实施": ("success_bg", "success_border", "success"),
}


def _status_colors(status: str):
    bg_key, bd_key, fg_key = _STATUS_TOKEN_KEYS.get(
        status, ("accent_bg", "border", "text_muted")
    )
    return (TOKEN[bg_key], TOKEN[bd_key], TOKEN[fg_key])


def tag(status: str) -> str:
    bg, bd, fg = _status_colors(status)
    return (
        f'<span style="display:inline-block;background:{bg};border:1px solid {bd};color:{fg};'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 8px;font-size:{TOKEN["font_micro"]};'
        f'white-space:nowrap;font-weight:{TOKEN["weight_medium"]};">{status}</span>'
    )


# KPI — Horizontal strip (no card border)

def stat(label: str, value: str, accent: str = "", sub: str = ""):
    """KPI strip. Label muted, value bold. No card box. Accent only for semantic KPIs."""
    color = accent or TOKEN["text"]
    sub_html = (
        f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_muted"]};'
        f'margin-top:1px;">{sub}</div>'
        if sub else ""
    )
    st.markdown(
        f'<div style="padding:8px 0;text-align:center;">'
        f'<div style="font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_medium"]};'
        f'color:{TOKEN["text_muted"]};text-transform:uppercase;letter-spacing:0.05em;'
        f'margin-bottom:2px;">{label}</div>'
        f'<div style="font-size:1.6em;font-weight:{TOKEN["weight_bold"]};'
        f'color:{color};line-height:1.1;">{value}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# Row-style cards (compact, not boxes)

def issue_row(issue: dict, show_checkbox: bool = False, checked: bool = False,
              checkbox_key: str = ""):
    """Issue as a single table-like row. Left status dot, title, right tag."""
    s = issue.get("status", "")
    _, _, fg = _status_colors(s)
    urgency = issue.get("urgency", "")
    urgency_mark = f' <span style="color:{TOKEN["danger"]};font-weight:600;">!</span>' if urgency in ("紧急", "极急") else ""

    cb_html = ""
    if show_checkbox:
        val = "true" if checked else "false"
        cb_html = (
            f'<input type="checkbox" id="{checkbox_key}" '
            f'{"checked" if checked else ""} '
            f'style="margin-right:8px;accent-color:{TOKEN["accent"]};">'
        )

    st.markdown(
        f'<div style="display:flex;align-items:center;padding:8px 0;'
        f'border-bottom:1px solid {TOKEN["border"]};gap:10px;'
        f'font-size:{TOKEN["font_body"]};">'
        f'{cb_html}'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{fg};flex-shrink:0;"></span>'
        f'<span style="flex:1;color:{TOKEN["text"]};min-width:0;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;">'
        f'#{issue["id"]} {issue.get("title","")[:32]}{urgency_mark}</span>'
        f'<span style="color:{TOKEN["text_muted"]};font-size:{TOKEN["font_micro"]};'
        f'white-space:nowrap;">{issue.get("category","")}</span>'
        f'<span style="color:{TOKEN["text_muted"]};font-size:{TOKEN["font_micro"]};'
        f'white-space:nowrap;">{issue.get("reported_at","")[:10]}</span>'
        f'{tag(s)}'
        f'</div>',
        unsafe_allow_html=True,
    )


def proposal_row(proposal: dict):
    """Proposal as a compact row."""
    s = proposal.get("status", "讨论中")
    _, _, fg = _status_colors(s)
    supporters = proposal.get("supporter_count", 0)

    st.markdown(
        f'<div style="display:flex;align-items:center;padding:8px 0;'
        f'border-bottom:1px solid {TOKEN["border"]};gap:10px;'
        f'font-size:{TOKEN["font_body"]};">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{fg};flex-shrink:0;"></span>'
        f'<span style="flex:1;color:{TOKEN["text"]};min-width:0;overflow:hidden;'
        f'text-overflow:ellipsis;white-space:nowrap;">{proposal.get("title","")[:36]}</span>'
        f'<span style="color:{TOKEN["text_muted"]};font-size:{TOKEN["font_micro"]};'
        f'white-space:nowrap;">{supporters} supports</span>'
        f'{tag(s)}'
        f'</div>',
        unsafe_allow_html=True,
    )


# Card system (for detail views, not lists)

def _card(inner: str, bg: str = "", border: str = "",
          pad: str = "", shadow: str = "", hover: bool = True) -> str:
    bg = bg or TOKEN["card_bg"]
    bd = border or TOKEN["border"]
    pd = pad or TOKEN["space_md"]
    sh = shadow or TOKEN["shadow_sm"]
    hov = (
        f"transition: box-shadow {TOKEN['transition']}, transform {TOKEN['transition']};"
        f"cursor: pointer;"
    ) if hover else ""
    return (
        f'<div style="background:{bg};border:1px solid {bd};'
        f'border-radius:{TOKEN["radius_card"]};padding:{pd};margin:5px 0;'
        f'box-shadow:{sh};{hov}font-size:{TOKEN["font_body"]};line-height:1.55;"'
        f' onmouseover="this.style.boxShadow=\'{TOKEN["shadow"]}\';'
        f'this.style.transform=\'translateY(-1px)\';"'
        f' onmouseout="this.style.boxShadow=\'{sh}\';'
        f'this.style.transform=\'translateY(0)\';">'
        f'{inner}</div>'
    )


def info_card(title: str, detail: str = ""):
    detail_html = (
        f'<br><span style="color:{TOKEN["text_sec"]};font-size:{TOKEN["font_label"]};">{detail}</span>'
        if detail else ""
    )
    st.markdown(
        _card(
            f'<strong style="color:{TOKEN["text"]};">{title}</strong>{detail_html}',
            bg=TOKEN["accent_bg"], border=TOKEN["accent_border"], hover=False,
        ),
        unsafe_allow_html=True,
    )


# Legacy card wrappers — still use for backward compat in detail views
issue_card = issue_row
proposal_card = proposal_row


def topic_card(topic: dict):
    source = "AI" if topic.get("created_by_agent") else "Admin"
    participants = topic.get("participant_count", 0)
    st.markdown(
        _card(
            f'<strong style="color:{TOKEN["text"]};">{topic.get("title","")[:32]}</strong>'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:{TOKEN["font_label"]};">'
            f'{source} · {participants} participants</span>',
            bg=TOKEN["accent_bg"], border=TOKEN["accent_border"], hover=True,
        ),
        unsafe_allow_html=True,
    )


def event_card(event: dict):
    content = event.get("content", "")
    preview = content[:80] + ("..." if len(content) > 80 else "")
    st.markdown(
        _card(
            f'<strong style="color:{TOKEN["text"]};">{event.get("title","")}</strong>'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:{TOKEN["font_label"]};">{preview}</span>',
            bg=TOKEN["info_bg"], border=TOKEN["info_border"], hover=True,
        ),
        unsafe_allow_html=True,
    )


def reminder(title: str, message: str):
    st.markdown(
        f'<div style="background:{TOKEN["warning_bg"]};'
        f'border-left:2px solid {TOKEN["warning"]};'
        f'padding:12px 16px;border-radius:0 {TOKEN["radius_card"]} {TOKEN["radius_card"]} 0;'
        f'margin:10px 0;">'
        f'<strong style="color:{TOKEN["text"]};font-size:{TOKEN["font_body"]};">{title}</strong><br>'
        f'<span style="color:{TOKEN["text_sec"]};font-size:{TOKEN["font_label"]};">{message}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# Section & Page Header

def section(title: str):
    st.markdown(
        f'<div style="margin:24px 0 10px;font-size:{TOKEN["font_display"]};'
        f'font-weight:{TOKEN["weight_bold"]};color:{TOKEN["text"]};">{title}</div>',
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "", badge: str = ""):
    badge_html = (
        f'<span style="background:{TOKEN["accent_bg"]};color:{TOKEN["accent"]};'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_medium"]};'
        f'padding:2px 8px;border-radius:{TOKEN["radius_full"]};'
        f'margin-left:8px;vertical-align:middle;">{badge}</span>'
    ) if badge else ""

    st.markdown(
        f'<div style="margin-bottom:4px;">'
        f'<span style="font-size:{TOKEN["font_display"]};font-weight:{TOKEN["weight_bold"]};'
        f'color:{TOKEN["text"]};">{title}{badge_html}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.caption(subtitle)
    st.markdown(
        f'<div style="height:1px;background:{TOKEN["border"]};margin:8px 0 16px;"></div>',
        unsafe_allow_html=True,
    )


# Navigation — step indicator (minimal)

_OODA_STEPS = [
    {"key": "home",          "label": "对话",      "pillar": ""},
    {"key": "pulse",         "label": "校园脉搏",   "pillar": "知"},
    {"key": "issues",        "label": "随手报修",   "pillar": "报"},
    {"key": "voice",         "label": "有话说",     "pillar": "议"},
    {"key": "transparency",  "label": "治理透明窗", "pillar": "督"},
    {"key": "mine",          "label": "我的",       "pillar": ""},
]
_OODA_PAGE_MAP = {s["key"]: f"ui/pages/{s['key']}.py" for s in _OODA_STEPS}


def ooda_nav(current: str):
    """Minimal step indicator. No emojis, no glow."""

    st.markdown("""
<style>
@media (max-width: 768px) {
    .ooda-stepper-wrap { overflow-x: auto !important; -webkit-overflow-scrolling: touch; }
    .ooda-stepper-inner { min-width: 380px; max-width: 520px; margin: 0 auto; }
}
@media (max-width: 480px) {
    .ooda-step-label { display: none !important; }
    .ooda-stepper-inner { min-width: 300px; }
}
</style>
""", unsafe_allow_html=True)

    n = len(_OODA_STEPS)
    active_idx = next(i for i, s in enumerate(_OODA_STEPS) if s["key"] == current)

    parts = []
    for i, step in enumerate(_OODA_STEPS):
        is_active = i == active_idx
        dot_size = "20px"

        parts.append(
            f'<div class="ooda-step" style="display:flex;flex-direction:column;'
            f'align-items:center;gap:3px;flex:1;'
            f'opacity:{1.0 if is_active else 0.35};transition:opacity 0.15s;">'
            f'<div style="width:{dot_size};height:{dot_size};border-radius:50%;'
            f'background:{TOKEN["accent"] if is_active else "transparent"};'
            f'border:1.5px solid {TOKEN["accent"] if is_active else TOKEN["border_visible"]};'
            f'display:flex;align-items:center;justify-content:center;font-size:0.65em;'
            f'color:{TOKEN["accent"] if is_active else TOKEN["text_muted"]};'
            f'font-weight:600;">{i + 1}</div>'
            f'<div class="ooda-step-label" style="font-size:{TOKEN["font_micro"]};'
            f'font-weight:{TOKEN["weight_medium"] if is_active else "400"};'
            f'color:{TOKEN["text"] if is_active else TOKEN["text_muted"]};'
            f'text-align:center;line-height:1.2;">{step["label"]}</div></div>'
        )

    final_parts = []
    for i, p in enumerate(parts):
        final_parts.append(p)
        if i < n - 1:
            line_color = TOKEN["accent"] if i < active_idx else TOKEN["border"]
            final_parts.append(
                f'<div style="flex:0.15;display:flex;align-items:flex-start;padding-top:10px;">'
                f'<div style="width:100%;height:1px;background:{line_color};'
                f'border-radius:1px;opacity:0.4;"></div></div>'
            )

    st.markdown(
        f'<div class="ooda-stepper-wrap">'
        f'<div class="ooda-stepper-inner" style="display:flex;align-items:flex-start;'
        f'justify-content:center;padding:6px 4px 2px;margin:0 auto;max-width:520px;">'
        f'{"".join(final_parts)}</div></div>',
        unsafe_allow_html=True,
    )

    cols = st.columns(n)
    for i, step in enumerate(_OODA_STEPS):
        if step["key"] != current:
            with cols[i]:
                if st.button(f"{step['label']}", key=f"ooda_nav_{step['key']}", width="stretch"):
                    st.switch_page(_OODA_PAGE_MAP[step["key"]])


# Altair chart theming

def configure_altair(chart):
    return (
        chart.configure(background="transparent")
        .configure_view(stroke="transparent")
        .configure_axis(
            labelColor=TOKEN["text_sec"],
            titleColor=TOKEN["text_sec"],
            gridColor=TOKEN["chart_grid"],
            domainColor=TOKEN["border"],
            tickColor=TOKEN["border"],
        )
        .configure_title(color=TOKEN["text"])
        .configure_legend(
            orient="top", title=None,
            labelColor=TOKEN["text_sec"], titleColor=TOKEN["text_sec"],
        )
    )


# Utilities

@contextmanager
def loading(message: str = "Loading..."):
    with st.spinner(message):
        yield


def time_ago(ts: str) -> str:
    try:
        diff = datetime.now() - datetime.fromisoformat(ts)
        secs = diff.total_seconds()
        if secs < 60:       return "just now"
        if secs < 3600:     return f"{int(secs // 60)}m ago"
        if secs < 86400:    return f"{int(secs // 3600)}h ago"
        return f"{diff.days}d ago"
    except Exception:
        _log.debug("time_ago parsing failed for ts=%r", ts, exc_info=True)
        return ""


def resolve_author(profile: dict) -> str:
    sid = profile.get("student_id", "")
    if sid: return sid
    return f"{profile.get('school', '')}{profile.get('grade', '')}" or "me"
