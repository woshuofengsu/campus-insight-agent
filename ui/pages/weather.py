"""🌤️ 社区天气 — 实时天气、未来 3 天预报、穿衣/出行建议、极端天气预警（居民端）。

按《03-天气.md》第七节标准输出实现：
- 顶部极端天气滚动提醒（可临时关闭，每次登录或每 6 小时再次出现）；
- 当前温度（大字号）、天气现象、最高/最低温、风力、湿度、空气质量、紫外线；
- 极端天气预警标签（黄色/橙色/红色）；
- 未来 3 天预报、穿衣建议、出行建议、数据更新时间；
- 数据源故障缓存降级提示（"数据更新于XX时间，当前不可用"）。
"""
import logging
from datetime import datetime

import streamlit as st

from ui.session_state import SS
from ui.components import TOKEN, page_header, section, info_card

_log = logging.getLogger(__name__)

page_header("🌤️ 社区天气", "实时天气 · 未来 3 天预报 · 穿衣出行建议 · 极端天气预警。", "天")

# ---------------- 登录与社区绑定（《03-天气.md》异常处理 4/5） ----------------
memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else (st.session_state.get("user_profile") or {})
uid = profile.get("id") or st.session_state.get(SS.login_user_id, 0)
community = (profile.get("community") or "").strip()

if not uid:
    st.info("请先登录后查看天气。")
    st.switch_page("app.py")  # 回登录页（spec：未登录访问天气页跳转登录）
    st.stop()
if not community:
    st.info("请先绑定所属社区，再查看社区天气。")
    st.stop()

from data.db_weather import (  # noqa: E402  数据层，只调用不写 SQL
    get_weather_for_display,
    get_daily_advice,
    get_reminder_banner_data,
    get_active_alerts,
    ALERT_TEXTS,
    record_weather_view,
)

record_weather_view(community)  # 只记系统访问日志，不进业务留痕

_LEVEL_COLORS = {"黄色": "#eab308", "橙色": "#f97316", "红色": "#dc2626"}
_BANNER_HIDE_HOURS = 6  # 临时关闭后每 6 小时再次出现


def _banner_key() -> str:
    return f"_weather_banner_closed_{uid or 0}"


def _banner_visible() -> bool:
    closed_at = st.session_state.get(_banner_key())
    if not closed_at:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(str(closed_at))).total_seconds() >= _BANNER_HIDE_HOURS * 3600
    except Exception:
        return True


def _render_banner(alerts: list) -> bool:
    """顶部极端天气滚动提醒；返回是否还在展示（False 表示用户刚关闭）。"""
    if not alerts:
        return True
    if not _banner_visible():
        return True

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
            st.session_state[_banner_key()] = datetime.now().isoformat()
            st.rerun()
    return True


# 极端天气滚动提醒已由 app.py 全局注入（所有页面顶部统一展示），这里不再重复渲染
alerts = get_active_alerts()          # 按等级从高到低排序

# ---------------- 天气数据（统一展示入口，含缓存降级） ----------------
try:
    weather = get_weather_for_display(community)
except Exception as e:
    _log.warning("天气数据加载失败", exc_info=True)
    st.error(f"天气数据加载失败：{e}")
    st.stop()

days = weather.get("days") or []
if not days:
    st.warning("天气数据暂不可用，请稍后再试。")
    st.stop()

today = days[0]
location = weather.get("location") or community

# 延迟 / 降级提示（《03-天气.md》缓存降级）
if weather.get("degraded"):
    st.warning(f"⚠️ 天气数据不可用：{weather.get('note') or '数据更新于历史时间，当前不可用'}")
elif weather.get("delay"):
    st.info("🕐 天气数据可能延迟（超过 15 分钟未更新）")
elif weather.get("note"):
    st.caption(weather["note"])

# ---------------- 当前天气主卡片 ----------------
st.markdown(
    f'<div style="background:{TOKEN["accent_bg"]};border:1px solid {TOKEN["accent_border"]};'
    f'border-radius:{TOKEN["radius_card"]};padding:22px 18px;text-align:center;'
    f'box-shadow:{TOKEN["shadow"]};margin-bottom:12px;">'
    f'<div style="font-size:0.9em;font-weight:600;color:{TOKEN["text_sec"]};">📍 {location}</div>'
    f'<div style="font-size:3.4em;margin-top:2px;">{today.get("emoji", "")}</div>'
    f'<div style="font-size:1.15em;font-weight:700;color:{TOKEN["text"]};">{today.get("condition", "—")}</div>'
    f'<div style="font-size:3.2em;font-weight:800;color:{TOKEN["text"]};line-height:1.1;">'
    f'{today.get("temp_high", "—")}°</div>'
    f'<div style="font-size:0.9em;color:{TOKEN["text_sec"]};">'
    f'最低 {today.get("temp_low", "—")}°C · 最高 {today.get("temp_high", "—")}°C</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# 极端天气预警标签（黄色/橙色/红色）
if alerts:
    tag_html = "".join(
        f'<span style="display:inline-block;background:{_LEVEL_COLORS.get(a.get("level",""),"#eab308")};'
        f'color:#ffffff;border-radius:{TOKEN["radius_full"]};padding:3px 12px;font-size:{TOKEN["font_label"]};'
        f'font-weight:{TOKEN["weight_bold"]};margin-right:6px;white-space:nowrap;">'
        f'⚠️ {a.get("alert_type","")}{a.get("level","")}预警</span>'
        for a in alerts
    )
    st.markdown(
        f'<div style="margin-bottom:10px;">{tag_html}</div>',
        unsafe_allow_html=True,
    )

# ---------------- 天气详情指标 ----------------
c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    st.metric("🌬️ 风力", today.get("wind") or "—")
with c2:
    st.metric("💧 湿度", f'{today.get("humidity", "—")}%' if today.get("humidity") is not None else "—")
with c3:
    st.metric("🍃 空气质量", today.get("aqi", "—") if today.get("aqi") is not None else "—")
with c4:
    st.metric("🌞 紫外线", today.get("uv", "—") if today.get("uv") is not None else "—")
with c5:
    st.metric("🌧️ 降水概率", f'{today.get("rain_prob", "—")}%')
st.caption("湿度 / 空气质量 / 紫外线以数据源提供为准，暂未提供时显示 —。")

st.markdown("---")

# ---------------- 未来 3 天预报 ----------------
section("未来 3 天预报")
forecast = days[1:4]
if forecast:
    cols = st.columns(len(forecast))
    for i, d in enumerate(forecast):
        with cols[i]:
            with st.container(border=True):
                st.markdown(
                    f'<div style="text-align:center;">'
                    f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};font-weight:600;">'
                    f'{d.get("weekday", "")} {str(d.get("date", ""))[5:]}</div>'
                    f'<div style="font-size:2em;margin:4px 0;">{d.get("emoji", "")}</div>'
                    f'<div style="font-size:0.9em;font-weight:700;color:{TOKEN["text"]};">'
                    f'{d.get("condition", "—")}</div>'
                    f'<div style="font-size:0.85em;color:{TOKEN["text_sec"]};">'
                    f'{d.get("temp_low", "—")}°C ~ {d.get("temp_high", "—")}°C</div>'
                    f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};">'
                    f'降水 {d.get("rain_prob", "—")}%</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
else:
    info_card("暂无未来天气预报数据")

st.markdown("---")

# ---------------- 穿衣 / 出行建议（每天生成一次） ----------------
section("穿衣 / 出行建议")
try:
    advice = get_daily_advice(city=community)
    if advice:
        st.markdown(
            f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
            f'border-radius:{TOKEN["radius_card"]};padding:14px 18px;box-shadow:{TOKEN["shadow_sm"]};">'
            f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin-bottom:6px;">👕 穿衣建议</div>'
            f'<div style="font-size:0.9em;color:{TOKEN["text_sec"]};line-height:1.7;">{advice.get("dress", "—")}</div>'
            f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin:10px 0 6px;">🚶 出行建议</div>'
            f'<div style="font-size:0.9em;color:{TOKEN["text_sec"]};line-height:1.7;">{advice.get("travel", "—")}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
except Exception as e:
    _log.debug("穿衣出行建议生成失败", exc_info=True)
    info_card("建议生成失败，请稍后再试", str(e))

st.markdown("---")

# ---------------- 数据更新时间 ----------------
updated_at = weather.get("data_updated_at") or ""
if weather.get("degraded"):
    note = f'<span style="color:{TOKEN["danger"]};">数据更新于{updated_at or "历史时间"}，当前不可用（缓存降级）</span>'
elif weather.get("delay"):
    note = f'<span style="color:{TOKEN["warning"]};">数据更新于{updated_at or "—"}，天气数据可能延迟</span>'
else:
    note = f'数据更新于{updated_at or "—"}'
st.markdown(
    f'<div style="text-align:center;font-size:0.78em;color:{TOKEN["text_muted"]};">'
    f'{note} · 实时天气约每 10 分钟刷新，预报每天早 8 点 / 晚 8 点更新'
    f'</div>',
    unsafe_allow_html=True,
)
