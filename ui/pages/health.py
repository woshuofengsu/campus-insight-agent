# ui/pages/health.py
"""🏥 健康防护 — 疾病风险预警、预防建议、季节提醒."""
import streamlit as st
import altair as alt
import pandas as pd
from ui.components import TOKEN, section, stat, info_card, configure_altair

st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">🏥 健康防护</span>'
    f'<span style="background:{TOKEN["success"]};color:#fff;font-size:0.7em;font-weight:600;'
    f'padding:2px 8px;border-radius:99px;margin-left:8px;vertical-align:middle;">防</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption("校园健康风险预警 · 季节性疾病预防 · 你的校园健康卫士。")

st.markdown("---")

try:
    from data.db_health_alerts import cached_health_risk
    h = cached_health_risk()
except Exception as e:
    st.error(f"健康数据加载失败：{e}")
    st.stop()

# Hero — overall risk level

hl = h["overall_level"]
he = h["overall_emoji"]
hc = h["overall_color"]
hs = h["overall_score"]
hcolor = TOKEN[hc] if hc in ("success", "warning", "danger") else TOKEN["accent"]

level_map = {
    "low": ("低风险", "校园健康状态良好", "继续保持良好卫生习惯"),
    "moderate": ("注意防护", "部分疾病进入高发期", "建议关注以下提醒并做好预防"),
    "high": ("警示", "多种风险因素叠加", "请认真阅读以下防护建议并转发同学"),
    "critical": ("高危预警", "需要立即采取防护措施", "建议辅导员向全院转发健康提醒"),
}
lvl_label, lvl_subtitle, lvl_action = level_map.get(hl, level_map["low"])

st.markdown(
    f'<div style="background:{TOKEN["card_bg"]};border:2px solid {hcolor};'
    f'border-radius:{TOKEN["radius_card"]};padding:24px;text-align:center;'
    f'box-shadow:{TOKEN["shadow_md"]};margin-bottom:16px;">'
    f'<div style="font-size:4em;margin-bottom:8px;">{he}</div>'
    f'<div style="font-size:1.4em;font-weight:800;color:{TOKEN["text"]};">'
    f'校园健康风险等级：<span style="color:{hcolor};">{lvl_label}</span></div>'
    f'<div style="font-size:3em;font-weight:800;color:{hcolor};margin:8px 0;">{hs} 分</div>'
    f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};">{lvl_subtitle}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

c1, c2, c3 = st.columns(3)
with c1:
    wd = h.get("weather_details", {})
    temp_str = f'{wd.get("temp_low", "?")}~{wd.get("temp_high", "?")}°C'
    stat("天气风险", f"+{h.get('weather_mod_total', 0)}",
         TOKEN["warning"] if h.get("weather_mod_total", 0) >= 10 else TOKEN["success"],
         sub=temp_str)
with c2:
    cd = h.get("campus_density", {})
    stat("人员密度", f"+{cd.get('score', 0)}",
         TOKEN["warning"] if cd.get("score", 0) >= 8 else TOKEN["success"],
         sub=" · ".join(cd.get("reasons", ["正常"])))
with c3:
    stat("更新时间", h.get("evaluated_at", "—"), TOKEN["accent"],
         sub=f'{h.get("weekday", "")}')

if h.get("weather_breakdown"):
    st.markdown("---")
    st.markdown(
        f'<span style="font-size:0.9em;font-weight:700;color:{TOKEN["text"]};">🌡️ 天气关联因子</span>',
        unsafe_allow_html=True,
    )
    for reason, score in h["weather_breakdown"].items():
        st.markdown(
            f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};padding:2px 0;">'
            f'{"🔴" if score >= 20 else "🟠" if score >= 10 else "🟡"} {reason}：+{score} 分</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")

# Per-disease risk cards

section("疾病风险明细")

diseases_sorted = sorted(h["diseases"], key=lambda x: -x["adjusted_risk"])

for d in diseases_sorted:
    ar = d["adjusted_risk"]
    if ar >= 60:
        badge, badge_color = "🔴 高风险", TOKEN["danger"]
    elif ar >= 40:
        badge, badge_color = "🟠 注意", TOKEN["warning"]
    elif ar >= 20:
        badge, badge_color = "🟡 低风险", TOKEN["accent"]
    else:
        badge, badge_color = "🟢 安全", TOKEN["success"]

        surv = d.get("surveillance", {})
    surv_note = ""
    if surv.get("surveillance_available"):
        direction_cn = {"rising": "全国上升", "peak": "全国高发", "falling": "全国下降",
                       "trough": "全国低谷", "stable": "全国平稳"}
        dir_label = direction_cn.get(surv.get("trend_direction", ""), "")
        surv_note = (
            f'<span style="font-size:0.68em;color:{TOKEN["success"]};margin-left:6px;'
            f'font-weight:600;">📡 {dir_label}</span>'
        )

    with st.container(border=True):
        c_left, c_right = st.columns([3, 1])
        with c_left:
            st.markdown(
                f'<span style="font-size:1em;font-weight:700;color:{TOKEN["text"]};">'
                f'{d["name"]}</span>'
                f'<span style="font-size:0.72em;color:{badge_color};margin-left:10px;'
                f'font-weight:600;">{badge}</span>'
                f'{surv_note}',
                unsafe_allow_html=True,
            )
            st.caption(f'🤒 症状：{d["symptoms"]}')
            st.markdown(
                f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
                f'background:{TOKEN["accent_bg"]};padding:8px 12px;border-radius:6px;'
                f'margin-top:4px;">💡 {d["advice"]}</div>',
                unsafe_allow_html=True,
            )
        with c_right:
            # Risk gauge bar
            pct = min(100, ar)
            gauge_color = TOKEN["success"] if ar < 30 else TOKEN["warning"] if ar < 50 else "#f97316" if ar < 70 else TOKEN["danger"]
            st.markdown(
                f'<div style="text-align:center;padding-top:12px;">'
                f'<div style="font-size:2em;font-weight:800;color:{gauge_color};">{ar}</div>'
                f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">风险分</div>'
                f'<div style="height:4px;background:{TOKEN["border"]};border-radius:2px;'
                f'margin-top:4px;width:80px;margin-left:auto;margin-right:auto;">'
                f'<div style="width:{pct}%;height:100%;background:{gauge_color};border-radius:2px;"></div>'
                f'</div>'
                f'<div style="font-size:0.65em;color:{TOKEN["text_muted"]};margin-top:2px;">'
                f'基础 {d["base_risk"]} · 天气 +{h.get("weather_mod_total", 0)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

st.markdown("---")
st.markdown(
    f'<div style="background:{TOKEN["accent_bg"]};border:1px solid {TOKEN["accent_border"]};'
    f'border-radius:{TOKEN["radius_card"]};padding:16px 20px;">'
    f'<div style="font-size:0.95em;font-weight:700;color:{TOKEN["text"]};margin-bottom:6px;">'
    f'📋 综合建议</div>'
    f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};line-height:1.8;">'
    f'{h["advice_summary"]}</div></div>',
    unsafe_allow_html=True,
)

cd = h.get("campus_density", {})
if cd.get("reasons"):
    st.markdown("---")
    st.caption("🏫 校园人员密度评估：" + " · ".join(cd["reasons"]))

st.markdown("---")
st.markdown(
    f'<div style="text-align:center;font-size:0.78em;color:{TOKEN["text_muted"]};">'
    f'数据来源：国家疾控局月度公报 × 季节模型 × 实时天气 × 校园密度 · 仅供参考 · {h["evaluated_at"]}</div>',
    unsafe_allow_html=True,
)
