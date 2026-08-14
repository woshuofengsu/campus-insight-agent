"""健康管理（网格员端）—— 全小区健康风险、预警推送、防护建议."""
import streamlit as st
import altair as alt
import pandas as pd
from ui.guard import require_role

require_role("grid")

from ui.components import TOKEN, section, stat, tag, configure_altair, page_header
import logging
_log = logging.getLogger(__name__)

page_header("🏥 健康管理", "小区健康风险监测 · 疾病预警推送 · 防护措施建议。")

try:
    from data.db_health_alerts import cached_health_risk
    h = cached_health_risk()
except Exception as e:
    st.error(f"健康数据加载失败：{e}")
    st.stop()

hl = h["overall_level"]
he = h["overall_emoji"]
hc = h["overall_color"]
hs = h["overall_score"]
hcolor = TOKEN[hc] if hc in ("success", "warning", "danger") else TOKEN["accent"]

# 总览横幅

level_label = {"low": "🟢 低风险", "moderate": "🟡 注意防护", "high": "🟠 警示", "critical": "🔴 高危预警"}
st.markdown(
    f'<div style="background:{TOKEN["card_bg"]};border:2px solid {hcolor};'
    f'border-radius:{TOKEN["radius_card"]};padding:20px 24px;text-align:center;'
    f'box-shadow:{TOKEN["shadow"]};margin-bottom:16px;">'
    f'<div style="font-size:2.5em;">{he}</div>'
    f'<div style="font-size:1.2em;font-weight:800;color:{TOKEN["text"]};">'
    f'全小区健康风险：{level_label.get(hl, "—")} · {hs} 分</div>'
    f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};margin-top:4px;">'
    f'{h["advice_summary"]}</div></div>',
    unsafe_allow_html=True,
)

c1, c2, c3, c4 = st.columns(4)
with c1:
    stat("活跃疾病", str(len(h["diseases"])), TOKEN["warning"], sub="种")
with c2:
    stat("高风险疾病", str(sum(1 for d in h["diseases"] if d["adjusted_risk"] >= 60)),
         TOKEN["danger"], sub="风险≥60分")
with c3:
    stat("天气影响", f"+{h.get('weather_mod_total', 0)}", TOKEN["warning"])
with c4:
    stat("人员密度", f"+{h.get('community_density', {}).get('score', 0)}",
         TOKEN["accent"])

st.markdown("---")

# 疾病风险表

section("🦠 疾病风险明细表")

diseases_sorted = sorted(h["diseases"], key=lambda x: -x["adjusted_risk"])

# 组装表格数据
df_rows = []
for d in diseases_sorted:
    ar = d["adjusted_risk"]
    if ar >= 60:
        level = "🔴 高风险"
    elif ar >= 40:
        level = "🟠 注意"
    elif ar >= 20:
        level = "🟡 低风险"
    else:
        level = "🟢 安全"
    df_rows.append({
        "疾病": d["name"],
        "风险等级": level,
        "风险分": ar,
        "基础分": d["base_risk"],
        "症状": d["symptoms"][:60],
        "季节": d["season"],
    })

df = pd.DataFrame(df_rows)

# 画条形图
bar_chart = configure_altair(
    alt.Chart(df)
    .mark_bar(size=22)
    .encode(
        x=alt.X("风险分:Q", title=None, scale=alt.Scale(domain=[0, 100])),
        y=alt.Y("疾病:N", title=None, sort="-x"),
        color=alt.Color("风险分:Q", scale=alt.Scale(
            domain=[0, 30, 50, 70, 100],
            range=[TOKEN["success"], "#eab308", TOKEN["warning"], TOKEN["danger"], "#991b1b"],
        ), legend=None),
        tooltip=["疾病", "风险分", "症状", "季节"],
    )
    .properties(height=max(150, len(df_rows) * 36))
)
st.altair_chart(bar_chart, width="stretch")

st.markdown("---")

# 各疾病详情卡片，带操作按钮

section("📋 详细防护建议")

for d in diseases_sorted:
    ar = d["adjusted_risk"]
    with st.container(border=True):
        c1, c2 = st.columns([4, 1])
        with c1:
            risk_icon = "🔴" if ar >= 60 else "🟠" if ar >= 40 else "🟡" if ar >= 20 else "🟢"
            st.markdown(
                f'<span style="font-size:0.95em;font-weight:700;color:{TOKEN["text"]};">'
                f'{risk_icon} {d["name"]}</span>'
                f'&nbsp;{tag(f"风险分 {ar}")}',
                unsafe_allow_html=True,
            )
            st.caption(f'🤒 {d["symptoms"]}')
            st.markdown(
                f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
                f'background:{TOKEN["accent_bg"]};padding:8px 12px;border-radius:6px;">'
                f'💡 <strong>预防建议：</strong>{d["advice"]}</div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f'<div style="text-align:center;padding-top:16px;">'
                f'<div style="font-size:1.8em;font-weight:800;color:{hcolor};">{ar}</div>'
                f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};">风险分</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # 快捷操作：推送提醒（先占位）
            if ar >= 50:
                if st.button("📢 推送提醒", key=f"health_push_{d['name']}", width="stretch"):
                    st.toast(f"已推送「{d['name']}」防护提醒到全小区通知", icon="📢")

# 人员密度

st.markdown("---")
section("👥 小区人员密度评估")

cd = h.get("community_density", {})
density_score = cd.get("score", 0)
density_reasons = cd.get("reasons", [])

if density_reasons:
    for r in density_reasons:
        st.markdown(
            f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};padding:4px 0;">'
            f'📌 {r}</div>',
            unsafe_allow_html=True,
        )
else:
    st.info("当前小区人员密度正常，无特殊聚集风险。")

st.markdown(
    f'<div style="font-size:0.78em;color:{TOKEN["text_muted"]};margin-top:6px;">'
    f'人员密度影响传染风险评分：当前 +{density_score} 分</div>',
    unsafe_allow_html=True,
)

# 天气因子

st.markdown("---")
section("🌡️ 天气风险因子")

wd = h.get("weather_details", {})
if wd:
    cw1, cw2, cw3, cw4 = st.columns(4)
    with cw1:
        st.metric("🌡️ 最高温", f'{wd.get("temp_high", "—")}°C')
    with cw2:
        st.metric("🌡️ 最低温", f'{wd.get("temp_low", "—")}°C')
    with cw3:
        st.metric("💧 降水概率", f'{wd.get("rain_prob", "—")}%')
    with cw4:
        st.metric("🌤️ 天气", wd.get("condition", "—"))

weather_breakdown = h.get("weather_breakdown", {})
if weather_breakdown:
    for reason, score in weather_breakdown.items():
        st.markdown(
            f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};padding:2px 0;">'
            f'{"🔴" if score >= 20 else "🟠" if score >= 10 else "🟡"} {reason}：+{score}</div>',
            unsafe_allow_html=True,
        )
else:
    st.caption("当前天气条件良好，无显著健康风险因子。")

st.markdown("---")
st.markdown(
    f'<div style="text-align:center;font-size:0.78em;color:{TOKEN["text_muted"]};">'
    f'数据基于季节模型 + 实时天气 + 小区密度评估 · 每30分钟刷新 · {h["evaluated_at"]}</div>',
    unsafe_allow_html=True,
)
