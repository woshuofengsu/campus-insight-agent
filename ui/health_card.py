# ui/health_card.py
"""🏥 健康风险卡片 — 共用渲染组件.

提供两个可复用的渲染函数，供 health.py、pulse.py、dashboard.py 等页面使用：

  render_health_risk_overview(h: dict) → None
    紧凑概览卡片 — 用于 pulse.py（校园脉搏）和 dashboard.py（教师工作台）。
    显示：风险等级、评分、渐变风险条、Top 告警、综合建议、天气关联因子。

  render_disease_detail_cards(h: dict) → None
    逐病种明细卡片 — 用于 health.py（健康防护专页）。
    每张卡片显示：疾病名称、风险徽章、监测数据标注、症状、防护建议、风险仪表条。

输入参数 h 为 data.db_health_alerts.cached_health_risk() 的返回值 dict。
所有用户可见文案保持中文。
"""
import streamlit as st
from ui.components import TOKEN


def render_health_risk_overview(h: dict) -> None:
    """渲染紧凑的健康风险概览卡片（pulse / dashboard 共用）.

    包含：标题行（emoji + 等级标签 + 评分）、渐变风险条、
          Top 2 告警条目、综合建议、天气关联提示。
    """
    h_level = h["overall_level"]
    h_emoji = h["overall_emoji"]
    h_color = h["overall_color"]
    h_score = h["overall_score"]

    level_label = {
        "low": "低风险 · 校园健康",
        "moderate": "注意防护",
        "high": "警示 · 加强预防",
        "critical": "高危 · 立即行动",
    }
    h_label = level_label.get(h_level, "—")

    bar_color = TOKEN[h_color] if h_color in ("success", "warning", "danger") else TOKEN["accent"]
    risk_bar_pct = min(100, h_score)

    # ── Build alert rows HTML ──
    alerts_html = ""
    for alert in h.get("top_alerts", [])[:2]:
        alert_emoji = alert.get("emoji", "💊")
        alerts_html += (
            f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
            f'padding:4px 0;line-height:1.5;">'
            f'{alert_emoji} <strong>{alert["title"]}</strong> — {alert["message"][:100]}'
            f'</div>'
        )

    # ── Weather reasons ──
    weather_note = ""
    if h.get("weather_mod_total", 0) >= 10:
        reasons = h.get("weather_breakdown", {})
        if reasons:
            reason_str = " · ".join(list(reasons.keys())[:2])
            weather_note = (
                f'<div style="font-size:0.72em;color:{TOKEN["text_muted"]};margin-top:6px;">'
                f'🌡️ 天气关联：{reason_str}</div>'
            )

    # ── Source note ──
    source_note = h.get("source_note", "")
    source_html = ""
    if source_note:
        source_html = (
            f'<div style="font-size:0.68em;color:{TOKEN["text_muted"]};'
            f'margin-top:6px;opacity:0.75;">📋 {source_note}</div>'
        )

    # ── Render card ──
    st.markdown("---")
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1.5px solid {bar_color};'
        f'border-radius:{TOKEN["radius_card"]};padding:16px 20px;box-shadow:{TOKEN["shadow"]};'
        f'margin-bottom:8px;">'

        # Header row
        f'<div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;">'
        f'<span style="font-size:2em;">🏥</span>'
        f'<div style="flex:1;">'
        f'<span style="font-size:1.05em;font-weight:700;color:{TOKEN["text"]};">校园健康风险</span>'
        f'<span style="font-size:0.78em;color:{bar_color};margin-left:10px;font-weight:600;">'
        f'{h_emoji} {h_label}</span>'
        f'</div>'
        f'<span style="font-size:1.6em;font-weight:800;color:{bar_color};">{h_score}</span>'
        f'<span style="font-size:0.7em;color:{TOKEN["text_muted"]};">分</span>'
        f'</div>'

        # Gradient risk bar
        f'<div style="height:6px;background:{TOKEN["border"]};border-radius:3px;margin:6px 0 10px;">'
        f'<div style="width:{risk_bar_pct}%;height:100%;background:linear-gradient(90deg,'
        f'#22c55e 0%, #eab308 35%, #f97316 65%, #ef4444 100%);border-radius:3px;'
        f'transition:width 0.5s ease;"></div></div>'

        # Alerts
        f'{alerts_html}'

        # Advice
        f'<div style="font-size:0.78em;color:{TOKEN["text_muted"]};margin-top:6px;'
        f'padding:8px 12px;background:{TOKEN["accent_bg"]};border-radius:6px;">'
        f'💡 {h["advice_summary"]}</div>'

        # Weather note
        f'{weather_note}'

        # Source note
        f'{source_html}'

        f'</div>',
        unsafe_allow_html=True,
    )


def render_disease_detail_cards(h: dict) -> None:
    """渲染逐病种风险明细卡片（health 防护专页使用）.

    每张卡片包含：疾病名称、风险等级徽章、全国监测趋势标注、
    症状描述、防护建议、风险评分仪表条（含基线与天气修正说明）。
    """
    from ui.components import section as _section

    _section("疾病风险明细")

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
            direction_cn = {
                "rising": "全国上升", "peak": "全国高发", "falling": "全国下降",
                "trough": "全国低谷", "stable": "全国平稳",
            }
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
                if ar < 30:
                    gauge_color = TOKEN["success"]
                elif ar < 50:
                    gauge_color = TOKEN["warning"]
                elif ar < 70:
                    gauge_color = "#f97316"
                else:
                    gauge_color = TOKEN["danger"]
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
