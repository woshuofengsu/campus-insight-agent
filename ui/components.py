# ui/components.py
"""Design system — enterprise SaaS components for CommunityInsight."""
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
    "停车管理": "停车管理", "噪音扰民": "噪音扰民", "物业服务": "物业服务",
    "邻里矛盾": "邻里矛盾", "社区事务": "社区事务", "其他": "其他",
    # 兼容旧版校园分类（旧数据库残留行兜底映射，避免校园词泄漏）
    "教学设备": "设施维修", "网络服务": "物业服务",
    "餐饮问题": "环境卫生", "校园管理": "社区事务",
}

# Category color-dot system — 8 community categories each get a scannable dot.
# Dot colors are mid-saturation so they read on both light and dark grounds.
CAT_COLORS = {
    "设施维修": "#2563eb",  # blue
    "环境卫生": "#059669",  # green
    "安全隐患": "#dc2626",  # red
    "停车管理": "#d97706",  # amber
    "噪音扰民": "#7c3aed",  # violet
    "物业服务": "#0891b2",  # cyan
    "邻里矛盾": "#db2777",  # rose
    "社区事务": "#64748b",  # slate
}

CAT_COLOR_BG = {
    "设施维修": "#eff4ff", "环境卫生": "#ecfdf5", "安全隐患": "#fef2f2",
    "停车管理": "#fffbeb", "噪音扰民": "#f3eefd", "物业服务": "#ecfeff",
    "邻里矛盾": "#fdf2f8", "社区事务": "#f1f3f5",
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
        f'border-radius:{TOKEN["radius_full"]};padding:2px 8px;font-size:{TOKEN["font_micro"]};'
        f'white-space:nowrap;font-weight:{TOKEN["weight_semibold"]};">{status}</span>'
    )


def category_dot(cat: str) -> str:
    """Category pill — tinted background + color dot + label (8-category system)."""
    cat = CAT_LABEL.get(cat, cat)
    color = CAT_COLORS.get(cat, TOKEN["text_muted"])
    bg = CAT_COLOR_BG.get(cat, "transparent")
    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'background:{bg};color:{color};padding:2px 9px;'
        f'border-radius:{TOKEN["radius_full"]};font-size:{TOKEN["font_micro"]};'
        f'font-weight:{TOKEN["weight_semibold"]};white-space:nowrap;">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{color};'
        f'flex-shrink:0;"></span>{cat}</span>'
    )


# KPI — Horizontal strip (no card border)

def stat(label: str, value: str, accent: str = "", sub: str = ""):
    """KPI card. Elevated surface, muted label, bold value (colored when semantic)."""
    color = accent or TOKEN["text"]
    sub_html = (
        f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_muted"]};'
        f'margin-top:3px;">{sub}</div>'
        if sub else ""
    )
    st.markdown(
        f'<div class="stat-card" style="background:{TOKEN["card_bg"]};'
        f'border:1px solid {TOKEN["border"]};border-radius:{TOKEN["radius_card"]};'
        f'padding:14px 16px;box-shadow:{TOKEN["shadow_sm"]};">'
        f'<div class="stat-label" style="font-size:{TOKEN["font_micro"]};'
        f'font-weight:{TOKEN["weight_semibold"]};color:{TOKEN["text_muted"]};'
        f'letter-spacing:0.03em;margin-bottom:5px;">{label}</div>'
        f'<div class="stat-value" style="font-size:1.7em;font-weight:{TOKEN["weight_bold"]};'
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

    # 责任网格员（处理进度透明：谁在处理，居民一眼可见）
    assignee = (issue.get("assignee") or "").strip()
    assignee_html = (
        f'<br><span style="color:{TOKEN["text_muted"]};font-size:{TOKEN["font_micro"]};">'
        f'👷 {assignee}</span>'
        if assignee else ""
    )

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
        f'#{issue["id"]} {issue.get("title","")[:32]}{urgency_mark}{assignee_html}</span>'
        f'{category_dot(issue.get("category", ""))}'
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
        f'border:1px solid {TOKEN["warning_border"]};'
        f'padding:12px 16px;border-radius:{TOKEN["radius_card"]};'
        f'margin:10px 0;">'
        f'<strong style="color:{TOKEN["text"]};font-size:{TOKEN["font_body"]};">{title}</strong><br>'
        f'<span style="color:{TOKEN["text_sec"]};font-size:{TOKEN["font_label"]};">{message}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


# Section & Page Header

def section(title: str):
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin:26px 0 12px;">'
        f'<div style="width:4px;height:20px;border-radius:2px;'
        f'background:{TOKEN["brand_gradient"]};flex-shrink:0;"></div>'
        f'<div style="font-size:1.12em;font-weight:{TOKEN["weight_bold"]};'
        f'color:{TOKEN["text"]};line-height:1.2;">{title}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def page_header(title: str, subtitle: str = "", badge: str = ""):
    """Gradient hero band — the unified page masthead for every surface."""
    badge_html = (
        f'<span style="background:rgba(255,255,255,0.22);color:#ffffff;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'padding:3px 11px;border-radius:{TOKEN["radius_full"]};'
        f'margin-left:10px;vertical-align:middle;'
        f'border:1px solid rgba(255,255,255,0.35);">{badge}</span>'
    ) if badge else ""
    sub_html = (
        f'<div style="color:rgba(255,255,255,0.88);font-size:{TOKEN["font_body"]};'
        f'margin-top:5px;font-weight:{TOKEN["weight_medium"]};'
        f'max-width:760px;line-height:1.5;">{subtitle}</div>'
    ) if subtitle else ""

    st.markdown(
        f'<div style="background:{TOKEN["brand_gradient"]};'
        f'border-radius:14px;padding:22px 26px;margin-bottom:16px;'
        f'box-shadow:0 10px 28px rgba(79,70,229,0.28);">'
        f'<div style="font-size:1.45em;font-weight:{TOKEN["weight_bold"]};color:#ffffff;'
        f'letter-spacing:-0.01em;line-height:1.25;">{title}{badge_html}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


# Navigation — step indicator (minimal)

_OODA_STEPS = [
    {"key": "home",          "label": "对话",      "pillar": ""},
    {"key": "pulse",         "label": "社区脉搏",   "pillar": "知"},
    {"key": "issues",        "label": "接诉即办",   "pillar": "报"},
    {"key": "voice",         "label": "邻里议事",   "pillar": "议"},
    {"key": "transparency",  "label": "社区治理看板", "pillar": "督"},
    {"key": "mine",          "label": "我的",       "pillar": ""},
]
_OODA_PAGE_MAP = {s["key"]: f"ui/pages/{s['key']}.py" for s in _OODA_STEPS}


def ooda_nav(current: str):
    """Compact horizontal strip — one light bar of 6 steps, active step highlighted.

    Replaces the old two-layer stepper (numbered dots + labels + connectors, plus a
    second button row) with a single row so the page's real focal point isn't crowded.
    """
    n = len(_OODA_STEPS)
    cols = st.columns(n)
    for i, step in enumerate(_OODA_STEPS):
        is_active = (step["key"] == current)
        with cols[i]:
            if is_active:
                st.button(
                    step["label"], key=f"ooda_nav_{step['key']}_on",
                    type="primary", width="stretch",
                )
            else:
                if st.button(
                    step["label"], key=f"ooda_nav_{step['key']}", width="stretch",
                ):
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
    """Resolve display author from user profile.

    Priority: resident_id → community+building → name → login_id fallback → "我"
    Must match data.db_governance._resolve_author() logic so that proposals
    created via the Agent are visible on the "我的" page.
    """
    rid = (profile.get("resident_id") or "").strip()
    if rid:
        return rid
    community = (profile.get("community") or "").strip()
    building = (profile.get("building") or "").strip()
    if community:
        return f"{community}{building}" if building else community
    name = (profile.get("name") or "").strip()
    if name:
        return name
    uid = profile.get("id")
    if uid:
        return f"user_{uid}"
    # session_state fallback
    try:
        import streamlit as st
        sid_uid = st.session_state.get("_login_user_id")
        if sid_uid:
            return f"user_{sid_uid}"
    except Exception:
        pass
    return "我"


# Methodology / 口径面板

def methodology_panel():
    """📐 分析口径与方法论 — 披露每个数字背后的计算方式，建立评委与用户的信任。

    直接回应「AI 是否真的在工作」的质疑：把分类、SLA、异常检测、满意率的
    计算口径一次性说清楚，且 SLA 口径直接引用 data/db_sla.py 的单一事实来源。
    """
    from data.db_sla import SLA_HOURS
    sla_str = " · ".join(f"{k} {v} 小时" for k, v in SLA_HOURS.items())
    with st.expander("📐 分析口径与方法论", expanded=False):
        st.markdown(
            f"- **诉求分类**：DeepSeek 大模型语义分类（temperature=0，5s 超时），"
            f"失败自动降级为关键词匹配；分类集为设施维修 / 环境卫生 / 安全隐患 / "
            f"停车管理 / 噪音扰民 / 物业服务 / 邻里矛盾 / 社区事务。\n"
            f"- **紧急度分级**：极急（人身安全 / 大面积影响）> 紧急（影响较大）> 普通。\n"
            f"- **SLA 时效口径**：{sla_str}；超过时限仍未解决即记为「超时」预警。\n"
            f"- **异常检测**：z-score 标准差法（严重度 1–10）+ 跨周对比（本周 vs 上周）。\n"
            f"- **满意率**：已解决工单中「满意」占比 = 满意 ÷（满意 + 不满意）。\n"
            f"- **隐私**：匿名上报仅隐藏公开作者字段，后台仍以 reporter_id 定向通知本人。"
        )
