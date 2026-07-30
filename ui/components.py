# ui/components.py
"""Design system — premium UI components with consistent branding."""
import streamlit as st
from contextlib import contextmanager
from datetime import datetime

# ── Shared category label mapping ──
CAT_LABEL = {
    "设施维修": "设施维修", "环境卫生": "环境卫生", "安全隐患": "安全隐患",
    "教学设备": "教学设备", "网络服务": "网络服务", "餐饮问题": "餐饮问题",
    "校园管理": "校园管理", "其他": "其他",
}

# ── Theme-aware token proxy ──
# Instead of a static TOKEN dict, we use a proxy that resolves the active
# theme (light/dark) at access time. This means all existing code like
# TOKEN["primary"] automatically gets the correct color for the current theme.
class _ThemeAwareToken:
    """Dict-like proxy that resolves to the active theme's token dict.

    Usage: TOKEN["primary"] → returns theme-aware color value.
           TOKEN.get("key", default) → theme-aware .get().

    Safe at import time: falls back to light tokens if Streamlit isn't running.
    """
    def __init__(self):
        self._cache_theme = None
        self._cache_dict = None

    def _resolve(self) -> dict:
        """Resolve current theme token dict, with caching per rerun."""
        try:
            from ui.theme import get_token, get_theme
            theme = get_theme()
            if self._cache_theme != theme:
                self._cache_theme = theme
                self._cache_dict = get_token()
            return self._cache_dict
        except Exception:
            # Fallback for import-time / test contexts
            from ui.theme import TOKEN_LIGHT
            return TOKEN_LIGHT

    def __getitem__(self, key):
        return self._resolve()[key]

    def get(self, key, default=None):
        return self._resolve().get(key, default)

    def __contains__(self, key):
        return key in self._resolve()

    def __iter__(self):
        return iter(self._resolve())

    def __len__(self):
        return len(self._resolve())

    def keys(self):
        return self._resolve().keys()

    def values(self):
        return self._resolve().values()

    def items(self):
        return self._resolve().items()


# Drop-in replacement — all existing TOKEN["key"] usage works unchanged
TOKEN = _ThemeAwareToken()

# ── Status tag colors (theme-aware via TOKEN proxy) ──
# Instead of a static dict with hardcoded light-theme pastels, we resolve
# colours at call time so both light and dark modes look native.
_STATUS_TOKEN_KEYS = {
    "待处理": ("danger_bg", "danger_border", "danger"),
    "处理中": ("warning_bg", "warning_border", "warning"),
    "已解决": ("success_bg", "success_border", "success"),
    "讨论中": ("purple_bg", "purple_border", "purple_text"),
    "已回应": ("primary_bg", "primary_border", "primary"),
    "已采纳": ("success_bg", "success_border", "success"),
    "已实施": ("success_bg", "success_border", "success"),
}

def _status_colors(status: str):
    """Return (bg, border, text) tuple resolved from current theme tokens."""
    bg_key, bd_key, fg_key = _STATUS_TOKEN_KEYS.get(
        status, ("slate_bg", "slate_border", "text_muted")
    )
    return (TOKEN[bg_key], TOKEN[bd_key], TOKEN[fg_key])


def configure_altair(chart):
    """Apply theme-aware colours to an Altair chart so it renders correctly in
    both light and dark mode.

    Usage: chart = configure_altair(alt.Chart(df).mark_bar().encode(...))
           st.altair_chart(chart, width="stretch")
    """
    return (
        chart.configure(
            background="transparent",
        )
        .configure_view(
            stroke="transparent",
        )
        .configure_axis(
            labelColor=TOKEN["text_sec"],
            titleColor=TOKEN["text_sec"],
            gridColor=TOKEN["slate_border"],
            domainColor=TOKEN["slate_border"],
            tickColor=TOKEN["slate_border"],
        )
        .configure_title(
            color=TOKEN["text"],
        )
        .configure_legend(
            orient="top",
            title=None,
            labelColor=TOKEN["text_sec"],
            titleColor=TOKEN["text_sec"],
        )
    )


def _card(inner: str, bg: str = "", border: str = "", top_color: str = "",
          pad: str = "14px 16px", shadow: str = "", hover: bool = True,
          left_accent: str = "") -> str:
    """Build a theme-aware card with optional hover effects and accent borders.

    Args:
        left_accent: Color for a 3px left border accent (use TOKEN["danger"] etc.)
    """
    bg = bg or TOKEN["card_bg"]
    top = f"border-top: 3px solid {top_color};" if top_color else ""
    left = f"border-left: 3px solid {left_accent};" if left_accent else ""
    sh = shadow or TOKEN["shadow_xs"]
    hov = (
        f"transition: box-shadow {TOKEN['transition']}, border-color {TOKEN['transition']}, "
        f"transform {TOKEN['transition']};"
        f"cursor: pointer;"
    ) if hover else ""
    return (
        f'<div style="background:{bg};border:1px solid {border or TOKEN["slate_border"]};'
        f'border-radius:{TOKEN["radius"]};padding:{pad};margin:5px 0;'
        f'box-shadow:{sh};{top}{left}{hov}font-size:0.88em;line-height:1.55;"'
        f' onmouseover="this.style.boxShadow=\'{TOKEN["shadow"]}\';'
        f'this.style.borderColor=\'{TOKEN["primary_border"]}\';'
        f'this.style.transform=\'translateY(-1px)\';"'
        f' onmouseout="this.style.boxShadow=\'{sh}\';'
        f'this.style.borderColor=\'{border or TOKEN["slate_border"]}\';'
        f'this.style.transform=\'translateY(0)\';">'
        f'{inner}</div>'
    )


def tag(status: str) -> str:
    bg, bd, fg = _status_colors(status)
    return (
        f'<span style="background:{bg};border:1px solid {bd};color:{fg};'
        f'border-radius:{TOKEN["radius_full"]};padding:2px 10px;font-size:0.76em;'
        f'white-space:nowrap;font-weight:600;letter-spacing:0.02em;">{status}</span>'
    )


def section(title: str, pillar: str = "", accent: str = ""):
    accent = accent or TOKEN["primary"]
    pillar_tag = (
        f'<span style="background:{accent};color:#fff;font-size:0.65em;font-weight:600;'
        f'padding:2px 8px;border-radius:{TOKEN["radius_full"]};margin-left:8px;'
        f'vertical-align:middle;letter-spacing:0.05em;">{pillar}</span>'
    ) if pillar else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin:20px 0 10px;">'
        f'<span style="font-size:0.95em;font-weight:700;color:{TOKEN["text"]};'
        f'letter-spacing:-0.01em;">{title}{pillar_tag}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def page_header(emoji: str, title: str, subtitle: str = "", badge: str = "",
                badge_color: str = ""):
    """Consistent page header with gradient accent line.

    Args:
        emoji: Emoji icon for the header
        title: Main title text
        subtitle: Gray caption below title
        badge: Optional OODA pillar badge text
        badge_color: Badge background color (defaults to primary)
    """
    bc = badge_color or TOKEN["primary"]
    badge_html = (
        f'<span style="background:{bc};color:#fff;font-size:0.7em;font-weight:600;'
        f'padding:2px 8px;border-radius:{TOKEN["radius_full"]};margin-left:8px;'
        f'vertical-align:middle;letter-spacing:0.05em;">{badge}</span>'
    ) if badge else ""

    st.markdown(
        f'<div style="margin-bottom:4px;">'
        f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};'
        f'letter-spacing:-0.01em;">{emoji} {title}{badge_html}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.caption(subtitle)
    st.markdown(
        f'<div style="height:2px;background:linear-gradient(90deg,'
        f'{TOKEN["primary"]}44,{TOKEN["primary_border"]}88,transparent);'
        f'border-radius:1px;margin:6px 0 12px;"></div>',
        unsafe_allow_html=True,
    )


def stat(emoji: str, label: str, value: str, accent: str = "", sub: str = ""):
    """Clean KPI tile with consistent styling and optional subtitle."""
    color = accent or TOKEN["primary"]
    sub_html = (
        f'<div style="font-size:0.68em;color:{TOKEN["text_muted"]};margin-top:2px;">{sub}</div>'
        if sub else ""
    )
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["slate_border"]};'
        f'border-radius:{TOKEN["radius"]};padding:16px 12px;text-align:center;'
        f'box-shadow:{TOKEN["shadow_xs"]};transition:box-shadow 0.2s,transform 0.2s;"'
        f' onmouseover="this.style.boxShadow=\'{TOKEN["shadow"]}\';this.style.transform=\'translateY(-1px)\';"'
        f' onmouseout="this.style.boxShadow=\'{TOKEN["shadow_xs"]}\';this.style.transform=\'translateY(0)\';">'
        f'<div style="font-size:0.72em;font-weight:600;color:{TOKEN["text_muted"]};'
        f'letter-spacing:0.04em;margin-bottom:4px;text-transform:uppercase;">{emoji} {label}</div>'
        f'<div style="font-size:1.6em;font-weight:800;color:{color};letter-spacing:-0.02em;">{value}</div>'
        f'{sub_html}'
        f'</div>',
        unsafe_allow_html=True,
    )


def info_card(emoji: str, title: str, detail: str, bg: str = "", border: str = "", top: str = ""):
    bg = bg or TOKEN["primary_bg"]
    bd = border or TOKEN["primary_border"]
    st.markdown(
        _card(
            f'<strong style="color:{TOKEN["text"]};">{emoji} {title}</strong>'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:0.88em;">{detail}</span>',
            bg=bg, border=bd, top_color=top, hover=False,
        ),
        unsafe_allow_html=True,
    )


def issue_card(issue: dict):
    s = issue.get("status", "")
    bg, bd, _ = _status_colors(s)
    urgency = issue.get("urgency", "")
    urgency_badge = (
        f'<span style="color:{TOKEN["danger"]};font-weight:600;font-size:0.78em;">🔴 {urgency}</span>'
        if urgency in ("紧急", "极急") else ""
    )
    st.markdown(
        _card(
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
            f'<strong style="color:{TOKEN["text"]};">#{issue["id"]} {issue.get("title","")[:28]}</strong>'
            f'{tag(s)}</div>'
            f'<div style="margin-top:4px;display:flex;gap:8px;align-items:center;">'
            f'<span style="color:{TOKEN["text_muted"]};font-size:0.78em;">'
            f'{issue.get("category","")} · {issue.get("reported_at","")[:10]}</span>'
            f'{urgency_badge}</div>',
            bg=bg, border=bd, hover=True,
        ),
        unsafe_allow_html=True,
    )


def proposal_card(proposal: dict):
    s = proposal.get("status", "讨论中")
    bg, bd, _ = _status_colors(s)
    emoji = {"讨论中": "💬", "已回应": "📝", "已采纳": "✅", "已实施": "🎉"}.get(s, "📌")
    supporters = proposal.get("supporter_count", 0)
    supporter_text = f"👍 {supporters} 人附议" if supporters else "尚无附议"
    st.markdown(
        _card(
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
            f'<span>{emoji} <strong style="color:{TOKEN["text"]};">{proposal.get("title","")[:30]}</strong></span>'
            f'{tag(s)}</div>'
            f'<div style="margin-top:4px;color:{TOKEN["text_sec"]};font-size:0.82em;">'
            f'{supporter_text}</div>',
            bg=bg, border=bd, hover=True,
        ),
        unsafe_allow_html=True,
    )


def topic_card(topic: dict):
    source = "🤖 AI 发起" if topic.get("created_by_agent") else "👤 管理员"
    participants = topic.get("participant_count", 0)
    st.markdown(
        _card(
            f'<strong style="color:{TOKEN["text"]};">{topic.get("title","")[:32]}</strong>'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:0.82em;">'
            f'{source} · {participants} 人参与</span>',
            bg=TOKEN["warning_bg"], border=TOKEN["warning_border"], hover=True,
        ),
        unsafe_allow_html=True,
    )


def event_card(event: dict):
    content = event.get("content", "")
    preview = content[:80] + ("…" if len(content) > 80 else "")
    st.markdown(
        _card(
            f'<strong style="color:{TOKEN["text"]};">{event.get("title","")}</strong>'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:0.82em;">{preview}</span>',
            bg=TOKEN["primary_bg"], border=TOKEN["primary_border"], hover=True,
        ),
        unsafe_allow_html=True,
    )


def reminder(title: str, message: str, emoji: str = "⚠️"):
    st.markdown(
        f'<div style="background:{TOKEN["warning_bg"]};border-left:4px solid {TOKEN["warning"]};'
        f'padding:12px 16px;border-radius:0 {TOKEN["radius"]} {TOKEN["radius"]} 0;'
        f'margin:10px 0;box-shadow:{TOKEN["shadow_xs"]};">'
        f'<strong style="color:{TOKEN["text"]};font-size:0.9em;">{emoji} {title}</strong><br>'
        f'<span style="color:{TOKEN["text_sec"]};font-size:0.85em;">{message}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )


@contextmanager
def loading(message: str = "思考中..."):
    with st.spinner(message):
        yield


def time_ago(ts: str) -> str:
    try:
        diff = datetime.now() - datetime.fromisoformat(ts)
        secs = diff.total_seconds()
        if secs < 60:       return "刚刚"
        if secs < 3600:     return f"{int(secs // 60)}分钟前"
        if secs < 86400:    return f"{int(secs // 3600)}小时前"
        return f"{diff.days}天前"
    except Exception:
        return ""


# ═══════════════════════════════════════════
# OODA 步骤导航 — 连接线式步骤指示器
# ═══════════════════════════════════════════

def ooda_nav(current: str):
    """Render a connected-step indicator for the OODA flow.

    Visual: HTML stepper with filled circles (active) + outlined circles (inactive)
    connected by lines. Navigation: small Streamlit buttons for inactive steps.

    OODA_STEPS is defined inside the function (not at module level) so that
    TOKEN colours are resolved at call time and follow the active theme
    (light/dark) instead of being frozen at import time.
    """
    # ── Mobile: scrollable stepper on narrow screens ──
    st.markdown("""
<style>
@media (max-width: 768px) {
    .ooda-stepper-wrap {
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        max-width: 100vw !important;
        padding: 4px 0 !important;
    }
    .ooda-stepper-inner {
        min-width: 420px;
        max-width: 560px;
        margin: 0 auto;
    }
}
@media (max-width: 480px) {
    .ooda-step-label { display: none !important; }
    .ooda-line { flex: 0.05 !important; }
    .ooda-step { min-width: 44px; }
    .ooda-stepper-inner { min-width: 340px; }
}
</style>
""", unsafe_allow_html=True)

    OODA_STEPS = [
        {"key": "home",          "emoji": "💬", "label": "对话",   "pillar": "",   "color": TOKEN["primary"]},
        {"key": "pulse",         "emoji": "🌊", "label": "校园脉搏", "pillar": "知", "color": TOKEN["primary"]},
        {"key": "issues",        "emoji": "🔧", "label": "随手报修", "pillar": "报", "color": TOKEN["warning"]},
        {"key": "voice",         "emoji": "🗳️", "label": "有话说",  "pillar": "议", "color": TOKEN["purple_text"]},
        {"key": "transparency",  "emoji": "📊", "label": "治理透明窗","pillar": "督", "color": TOKEN["success"]},
        {"key": "mine",          "emoji": "👤", "label": "我的",   "pillar": "",   "color": TOKEN["primary"]},
    ]
    _OODA_PAGE_MAP = {s["key"]: f"ui/pages/{s['key']}.py" for s in OODA_STEPS}

    n = len(OODA_STEPS)
    active_idx = next(i for i, s in enumerate(OODA_STEPS) if s["key"] == current)

    # ── Visual stepper (pure HTML) ──
    parts = []
    for i, step in enumerate(OODA_STEPS):
        is_active = i == active_idx
        color = step["color"]
        pillar = step["pillar"]
        circle_size = "26px"

        if is_active:
            parts.append(
                f'<div class="ooda-step" style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1;">'
                f'<div style="width:{circle_size};height:{circle_size};border-radius:50%;background:{color};'
                f'display:flex;align-items:center;justify-content:center;font-size:0.72em;'
                f'box-shadow:0 0 0 2px {color}22;">'
                f'<span style="color:#fff;">{step["emoji"]}</span></div>'
                f'<div class="ooda-step-label" style="font-size:0.65em;font-weight:600;color:{color};text-align:center;line-height:1.2;">'
                f'{step["label"]}'
                f'{"<br>" if pillar else ""}'
                f'{f"<span style=\"font-size:0.6em;background:{color};color:#fff;padding:0px 4px;border-radius:99px;\">{pillar}</span>" if pillar else ""}'
                f'</div></div>'
            )
        else:
            parts.append(
                f'<div class="ooda-step" style="display:flex;flex-direction:column;align-items:center;gap:2px;flex:1;'
                f'cursor:pointer;opacity:0.45;transition:opacity 0.15s;" '
                f'onmouseover="this.style.opacity=\'0.75\'" onmouseout="this.style.opacity=\'0.45\'">'
                f'<div style="width:{circle_size};height:{circle_size};border-radius:50%;'
                f'border:1.5px solid {TOKEN["slate_border"]};background:{TOKEN["card_bg"]};'
                f'display:flex;align-items:center;justify-content:center;font-size:0.72em;">'
                f'{step["emoji"]}</div>'
                f'<div class="ooda-step-label" style="font-size:0.62em;color:{TOKEN["text_muted"]};text-align:center;line-height:1.2;">'
                f'{step["label"]}</div></div>'
            )

    # Interleave connecting lines
    final_parts = []
    for i, p in enumerate(parts):
        final_parts.append(p)
        if i < n - 1:
            line_color = TOKEN["primary"] if i < active_idx else TOKEN["slate_border"]
            final_parts.append(
                f'<div class="ooda-line" style="flex:0.2;display:flex;align-items:flex-start;padding-top:13px;">'
                f'<div style="width:100%;height:1px;background:{line_color};border-radius:1px;opacity:0.5;"></div></div>'
            )

    st.markdown(
        f'<div class="ooda-stepper-wrap">'
        f'<div class="ooda-stepper-inner" style="display:flex;align-items:flex-start;justify-content:center;'
        f'padding:8px 4px 2px;margin:0 auto;max-width:560px;">'
        f'{"".join(final_parts)}</div></div>',
        unsafe_allow_html=True,
    )

    # ── Click targets: invisible Streamlit buttons for inactive steps ──
    cols = st.columns(n)
    for i, step in enumerate(OODA_STEPS):
        if step["key"] != current:
            with cols[i]:
                if st.button(
                    f"→ {step['label']}",
                    key=f"ooda_nav_{step['key']}",
                    width="stretch",
                ):
                    st.switch_page(_OODA_PAGE_MAP[step["key"]])


# Re-export from standalone text utils (avoids Streamlit exec()-context import issues)
from utils.text import split_thinking  # noqa: F401


def resolve_author(profile: dict) -> str:
    """Derive author identity from user profile, shared across all pages."""
    sid = profile.get("student_id", "")
    if sid:
        return sid
    fallback = f"{profile.get('school', '')}{profile.get('grade', '')}"
    return fallback or "我"

