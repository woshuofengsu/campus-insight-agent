# ui/weather_banner.py
"""全局极端天气滚动提醒（居民端/负责人端所有页面顶部统一展示）。

原实现只在天气页/天气管理页内渲染（spec 要求覆盖网页顶部）；
抽成公共组件后由 app.py 在导航前统一注入。
"""
from datetime import datetime

import streamlit as st

from data.db_weather import get_active_alerts, ALERT_TEXTS

_BANNER_HIDE_HOURS = 6  # 临时关闭后每 6 小时再次出现


def _banner_key(uid: int = 0) -> str:
    return f"_weather_banner_closed_{uid or 0}"


def render_weather_banner(uid: int = 0) -> bool:
    """渲染极端天气滚动提醒；无预警或用户临时关闭时静默。返回是否在展示。"""
    try:
        alerts = get_active_alerts()
    except Exception:
        return True
    if not alerts:
        return True
    closed_at = st.session_state.get(_banner_key(uid))
    if closed_at:
        try:
            if (datetime.now() - datetime.fromisoformat(str(closed_at))).total_seconds() < _BANNER_HIDE_HOURS * 3600:
                return True
        except Exception:
            pass

    _LEVEL_COLORS = {"黄色": "#eab308", "橙色": "#f97316", "红色": "#dc2626"}
    has_red = any(a.get("level") == "红色" for a in alerts)
    bg = "#dc2626" if has_red else "#d97706"
    parts = []
    for a in alerts:
        color = _LEVEL_COLORS.get(a.get("level", ""), "#eab308")
        eff = (a.get("effective_time") or "")[:16]
        text = ALERT_TEXTS.get(a.get("alert_type", ""), "")
        parts.append(
            f'<span style="margin:0 32px;color:#ffffff;white-space:nowrap;">'
            f'⚠️ <b>{a.get("alert_type","")}{a.get("level","")}预警</b>'
            f'<span style="opacity:0.85;">（生效 {eff}）</span> {text}</span>'
        )

    st.markdown(
        '<style>'
        '@keyframes weather-marquee { 0% {transform: translateX(100%);} '
        '100% {transform: translateX(-100%);} }'
        '.weather-marquee-wrap { overflow:hidden; border-radius:12px; }'
        '.weather-marquee { display:inline-block; padding-left:100%; '
        'animation: weather-marquee 20s linear infinite; white-space:nowrap; }'
        '</style>',
        unsafe_allow_html=True,
    )
    c_banner, c_close = st.columns([8, 1])
    with c_banner:
        st.markdown(
            f'<div class="weather-marquee-wrap" style="background:{bg};padding:8px 0;">'
            f'<div class="weather-marquee">{"".join(parts)}</div></div>',
            unsafe_allow_html=True,
        )
    with c_close:
        if st.button("✕ 关闭", key="weather_banner_close", width="stretch",
                     help="临时关闭滚动提醒，每次登录或每 6 小时再次出现"):
            st.session_state[_banner_key(uid)] = datetime.now().isoformat()
            st.rerun()
    return True
