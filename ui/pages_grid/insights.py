# ui/pages_grid/insights.py
"""📈 数据洞察 — 7 维关联分析：异常检测、空间热点、解决效率、升级路径."""
import streamlit as st
import altair as alt
import pandas as pd
from ui.guard import require_role

require_role("grid")

from ui.components import TOKEN, tag, configure_altair, page_header, methodology_panel
from data.database import get_db
from data.db_sla import get_sla_breaches

# ── Reuse reflector's battle-tested analysis functions ──
import logging
_log = logging.getLogger(__name__)
from agent.reflector import (
    _z_score_anomalies,
    _cross_time_comparison,
    _detect_upgrade_paths,
)

# ── Page Render ──
page_header("📈 数据洞察", "基于 OODA 反射器的 7 维关联分析，自动发现社区治理中的隐藏模式和趋势。")

methodology_panel()

# -- 🤖 治理周报 — 一键生成 --
st.markdown("---")

c_rpt, c_btn = st.columns([3, 1])
with c_rpt:
    st.markdown(
        f'<span style="font-size:1.05em;font-weight:700;color:{TOKEN["text"]};">'
        f'🤖 治理周报</span>',
        unsafe_allow_html=True,
    )
    st.caption("自动分析社区治理数据，生成包含执行摘要、异常预警、趋势分析的结构化周报。")
with c_btn:
    generate_btn = st.button(
        "🔄 生成周报", key="gen_weekly_report", width="stretch",
        type="primary",
    )

if generate_btn:
    with st.spinner("🤖 正在分析社区治理数据并生成周报..."):
        from agent.weekly_report import generate_weekly_report
        report = generate_weekly_report(include_llm_summary=True)
        st.session_state._weekly_report = report
else:
    # Persist report in session state so it stays visible after interactions
    if "_weekly_report" not in st.session_state:
        st.session_state._weekly_report = None

report = st.session_state._weekly_report
if report:
    # ── 发送到邮箱（QQ SMTP；凭据在 .env，未配置则提示）──
    if st.button("📧 发送到邮箱", key="send_report_email"):
        from data.email_notify import send_email, is_configured
        if not is_configured():
            st.warning("未配置 SMTP 邮箱（.env 中的 SMTP_USER / SMTP_PASS），无法发送。")
        elif send_email(f"[社区先知] {report.get('title', '社区治理周报')}", report.get("markdown", "")):
            st.success("📧 周报已发送到邮箱。")
        else:
            st.warning("邮件发送失败，请检查 .env 中的 SMTP 配置（QQ 邮箱需使用授权码）。")

    # ── Executive summary card ──
    if report.get("exec_summary"):
        st.markdown(
            f'<div style="background:linear-gradient(135deg,{TOKEN["accent_bg"]},'
            f'{TOKEN["accent_bg"]});border:1px solid {TOKEN["accent_border"]};'
            f'border-radius:{TOKEN["radius_card"]};padding:16px 20px;margin:8px 0;">'
            f'<div style="font-size:0.78em;font-weight:700;color:{TOKEN["accent"]};'
            f'margin-bottom:6px;">🧠 分析摘要</div>'
            f'<div style="font-size:0.88em;color:{TOKEN["text"]};line-height:1.7;">'
            f'{report["exec_summary"]}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    elif not generate_btn:
        st.info("👆 点击「生成周报」按钮，系统将自动分析数据并生成完整报告。")

    # ── Report sections in expandable cards ──
    data = report.get("data", {})
    if data:
        # KPI quick glance
        kpi = data.get("kpi", {})
        if kpi:
            k1, k2, k3 = st.columns(3)
            with k1:
                st.metric("📝 总工单", kpi.get("total", 0))
            with k2:
                st.metric("⏳ 待处理", kpi.get("pending", 0))
            with k3:
                st.metric("🔥 紧急", kpi.get("urgent", 0))
            k4, k5 = st.columns(2)
            with k4:
                st.metric("📥 本周新增", kpi.get("week_new", 0))
            with k5:
                st.metric("📤 本周解决", kpi.get("week_resolved", 0))

        # Full report in expander
        with st.expander("📋 查看完整周报", expanded=False):
            st.markdown(report.get("markdown", ""))

        # Download button
        st.download_button(
            "📥 下载周报 (Markdown)",
            data=report.get("markdown", ""),
            file_name=f"治理周报_{report.get('title', 'report')}.md",
            mime="text/markdown",
            key="dl_weekly_report",
        )

st.markdown("---")

# ── Helper: run analysis once ──
@st.cache_data(ttl=60, show_spinner="正在分析社区治理数据...")
def _run_insight_analysis():
    """Run all 7 analysis dimensions and return structured results."""
    try:
        with get_db() as conn:
            z_anomalies = _z_score_anomalies(conn)
            cross_time = _cross_time_comparison(conn)
            upgrade_paths = _detect_upgrade_paths(conn)

            # Spatial hotspots: locations with most pending issues
            spatial_raw = conn.execute("""
                SELECT location, COUNT(*) as cnt,
                       SUM(CASE WHEN urgency='紧急' THEN 1 ELSE 0 END) as urgent_cnt
                FROM community_issues
                WHERE status IN ('待处理', '处理中') AND location != ''
                GROUP BY location
                ORDER BY cnt DESC LIMIT 8
            """).fetchall()
            spatial_hotspots = [dict(r) for r in spatial_raw]

            # Resolution efficiency by category
            eff_raw = conn.execute("""
                SELECT category,
                       COUNT(*) AS resolved_count,
                       ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) AS avg_days
                FROM community_issues
                WHERE status = '已解决' AND resolved_at IS NOT NULL
                GROUP BY category
                HAVING resolved_count >= 2
                ORDER BY avg_days DESC
            """).fetchall()
            resolution_eff = [dict(r) for r in eff_raw]

            # Recurrence detection: similar unresolved titles matching resolved ones
            recurrence_raw = conn.execute("""
                SELECT a.title AS unresolved_title, a.category, a.location, a.status,
                       b.title AS resolved_title, b.resolved_at
                FROM community_issues a
                JOIN community_issues b ON a.category = b.category
                    AND a.id != b.id AND b.status = '已解决'
                WHERE a.status IN ('待处理', '处理中')
                    AND a.location = b.location
                ORDER BY a.reported_at DESC LIMIT 8
            """).fetchall()
            recurrences = [dict(r) for r in recurrence_raw]

            # Category correlations: co-occurring in same location
            corr_raw = conn.execute("""
                SELECT a.category AS cat_a, b.category AS cat_b, COUNT(*) AS co_count
                FROM community_issues a
                JOIN community_issues b ON a.location = b.location AND a.id < b.id
                    AND a.location != '' AND b.location != ''
                WHERE a.category != b.category
                GROUP BY cat_a, cat_b
                ORDER BY co_count DESC LIMIT 6
            """).fetchall()
            correlations = [dict(r) for r in corr_raw]

            # Overdue SLA — 分级口径（极急6h / 紧急24h / 普通72h），统一走 data/db_sla.py
            overdues = get_sla_breaches(limit=10)

            # Category breakdown with urgency mix
            cat_breakdown_raw = conn.execute("""
                SELECT category,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='待处理' THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN status='处理中' THEN 1 ELSE 0 END) AS in_progress,
                       SUM(CASE WHEN status='已解决' THEN 1 ELSE 0 END) AS resolved,
                       SUM(CASE WHEN urgency='紧急' THEN 1 ELSE 0 END) AS urgent
                FROM community_issues
                GROUP BY category
                ORDER BY total DESC
            """).fetchall()
            cat_breakdown = [dict(r) for r in cat_breakdown_raw]

    except Exception as e:
        st.error(f"数据分析查询失败: {e}")
        return None

    return {
        "z_anomalies": z_anomalies,
        "cross_time": cross_time,
        "upgrade_paths": upgrade_paths,
        "spatial_hotspots": spatial_hotspots,
        "resolution_eff": resolution_eff,
        "recurrences": recurrences,
        "correlations": correlations,
        "overdues": overdues,
        "cat_breakdown": cat_breakdown,
    }


data = _run_insight_analysis()
if data is None:
    st.stop()

# -- Row 1: Alert Cards (异常 + 超时SLA) --
st.markdown("### 🚨 预警中心")

alert_cols = st.columns(3)

with alert_cols[0]:
    za = data["z_anomalies"]
    critical_count = sum(1 for a in za if a["level"] == "critical")
    high_count = sum(1 for a in za if a["level"] == "high")
    if za:
        level_icon = {"critical": "🔴", "high": "🟠", "moderate": "🟡"}
        st.metric(
            "🔬 统计异常",
            f"{len(za)} 个类别",
            delta=f"{critical_count}严重 {high_count}高度" if (critical_count + high_count) > 0 else "无严重异常",
        )
        for a in za[:4]:
            icon = level_icon.get(a["level"], "⚪")
            st.markdown(
                f'{icon} **{a["category"]}** — 严重度 {a["severity"]}/10，'
                f'本周 {a["recent"]} 件，紧急 {a.get("urgent_pending", 0)} 件',
            )
    else:
        st.metric("🔬 统计异常", "无", delta="数据正常")
        st.caption("所有类别均处于正常波动范围。")

with alert_cols[1]:
    ct = data["cross_time"]
    if ct:
        is_worsening = ct.get("is_worsening", False)
        is_improving = ct.get("is_improving", False)
        net_icon = "⚠️" if is_worsening else "✅" if is_improving else "→"
        st.metric(
            "📅 跨周趋势",
            f"新增 {ct.get('new_this_week', 0)} · 解决 {ct.get('resolved_this_week', 0)}",
            delta=f"{net_icon} {'恶化中' if is_worsening else '改善中' if is_improving else '平稳'}",
        )
        ntw, nlw = ct.get("new_this_week", 0), ct.get("new_last_week", 0)
        rtw, rlw = ct.get("resolved_this_week", 0), ct.get("resolved_last_week", 0)
        st.caption(
            f"新增: {ct.get('new_trend', '→')} (上周 {nlw} → 本周 {ntw})  |  "
            f"解决: {ct.get('resolved_trend', '→')} (上周 {rlw} → 本周 {rtw})"
        )
    else:
        st.metric("📅 跨周趋势", "数据不足", delta="—")

with alert_cols[2]:
    overdues = data["overdues"]
    critical_overdue = [o for o in overdues if o.get("level") == "critical"]
    st.metric(
        "⏰ SLA 超时",
        f"{len(overdues)} 件超时",
        delta=f"🔴 {len(critical_overdue)} 件紧急" if critical_overdue else "无紧急超时",
    )
    if overdues:
        for o in overdues[:4]:
            hours = o.get("hours_open", 0)
            time_str = f"{hours // 24} 天" if hours >= 24 else f"{hours} 小时"
            urg = "🔴" if o.get("level") == "critical" else "🟡"
            st.markdown(
                f'{urg} #{o["id"]} {o.get("title", "")[:22]} — '
                f'<span style="color:{TOKEN["danger"]};font-weight:600;">{time_str}</span>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("✅ 所有工单均在时效内处理。")

st.markdown("---")

# -- Row 2: Category Breakdown Chart + Spatial Hotspots --
chart_col1, chart_col2 = st.columns([3, 2])

with chart_col1:
    st.markdown("### 📊 各类别工单分布")
    cat_data = data["cat_breakdown"]
    if cat_data:
        df_cat = pd.DataFrame(cat_data)
        df_melt = df_cat.melt(
            id_vars=["category"], value_vars=["pending", "in_progress", "resolved"],
            var_name="状态", value_name="数量"
        )
        status_labels = {"pending": "待处理", "in_progress": "处理中", "resolved": "已解决"}
        df_melt["状态"] = df_melt["状态"].map(status_labels)

        bar_chart = configure_altair(
            alt.Chart(df_melt)
            .mark_bar()
            .encode(
                x=alt.X("数量:Q", title=None),
                y=alt.Y("category:N", title=None, sort="-x"),
                color=alt.Color(
                    "状态:N",
                    scale=alt.Scale(
                        domain=["待处理", "处理中", "已解决"],
                        range=[TOKEN["warning"], TOKEN["accent"], TOKEN["success"]],
                    ),
                ),
                tooltip=["category", "状态", "数量"],
            )
            .properties(height=220)
        )
        st.altair_chart(bar_chart, width="stretch")
    else:
        st.caption("暂无足够数据。")

with chart_col2:
    st.markdown("### 📍 空间热点")
    hotspots = data["spatial_hotspots"]
    if hotspots:
        for h in hotspots[:6]:
            loc = h["location"]
            cnt = h["cnt"]
            urg = h.get("urgent_cnt", 0)
            bar_width = min(100, int(cnt / max(1, hotspots[0]["cnt"]) * 100))
            urg_str = f' 🔴{urg}' if urg > 0 else ""
            st.markdown(
                f'<div style="margin-bottom:6px;">'
                f'<span style="font-size:0.85em;font-weight:600;">{loc}</span>'
                f'<span style="float:right;font-size:0.85em;color:{TOKEN["text_sec"]};">'
                f'{cnt} 件待处理{urg_str}</span>'
                f'<div style="background:{TOKEN["border"]};border-radius:4px;height:6px;margin-top:2px;">'
                f'<div style="background:{TOKEN["warning"]};border-radius:4px;height:6px;width:{bar_width}%;">'
                f'</div></div></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("暂无空间热点数据。")

st.markdown("---")

# -- Row 3: Resolution Efficiency + Upgrade Paths --
eff_col1, eff_col2 = st.columns(2)

with eff_col1:
    st.markdown("### ⏱️ 解决效率排行")
    re_data = data["resolution_eff"]
    if re_data and len(re_data) >= 2:
        df_eff = pd.DataFrame(re_data)
        # Color bars: fast = green, slow = red
        df_eff["color"] = df_eff["avg_days"].apply(
            lambda d: TOKEN["success"] if d <= 3 else TOKEN["warning"] if d <= 7 else TOKEN["danger"]
        )
        eff_chart = configure_altair(
            alt.Chart(df_eff)
            .mark_bar()
            .encode(
                x=alt.X("avg_days:Q", title="平均解决天数"),
                y=alt.Y("category:N", title=None, sort="x"),
                color=alt.Color(
                    "color:N", scale=None, legend=None
                ),
                tooltip=["category", "avg_days", "resolved_count"],
            )
            .properties(height=180)
        )
        st.altair_chart(eff_chart, width="stretch")
        # Text summary
        slowest = re_data[0]
        fastest = re_data[-1]
        st.caption(
            f"🐢 最慢：「{slowest['category']}」均 {slowest['avg_days']} 天 "
            f"| 🐇 最快：「{fastest['category']}」均 {fastest['avg_days']} 天"
        )
    else:
        st.caption("已解决工单不足，暂无效率数据。")

with eff_col2:
    st.markdown("### 治理升级路径")
    up_data = data["upgrade_paths"]
    if up_data:
        for u in up_data[:5]:
            cat = u["category"]
            count = u["issue_count"]
            has_prop = u.get("has_proposal", False)
            action = u.get("action", "")
            icon = "✅" if has_prop else "⚠️"
            st.markdown(
                f'{icon} **{cat}** — {count} 件待处理'
                f'{" · 已有提案在推进" if has_prop else " · 建议发起新提案"}',
            )
            if not has_prop:
                st.caption(f"   ↳ {action}")
    else:
        st.caption("暂无升级建议。所有类别待处理数均低于阈值。")

st.markdown("---")

# -- Row 4: Recurrence Detection + Category Correlations --
rec_col1, rec_col2 = st.columns(2)

with rec_col1:
    st.markdown("### 🔄 复发检测")
    recs = data["recurrences"]
    if recs:
        for r in recs[:5]:
            utitle = r.get("unresolved_title", "")[:25]
            rtitle = r.get("resolved_title", "")[:20]
            st.markdown(
                f'🔄 **{utitle}**...  \n'
                f'<span style="font-size:0.78em;color:{TOKEN["text_muted"]};">'
                f'曾解决：{rtitle}... · 同区域「{r.get("location", "")}」复发</span>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("✅ 未发现明显复发模式。所有问题均为首次出现。")

with rec_col2:
    st.markdown("### 🔗 类别关联")
    corrs = data["correlations"]
    if corrs:
        for c in corrs[:5]:
            cat_a = c["cat_a"]
            cat_b = c["cat_b"]
            co = c["co_count"]
            st.markdown(
                f'🔗 **{cat_a}** ↔ **{cat_b}** — '
                f'<span style="font-size:0.85em;color:{TOKEN["text_sec"]};">{co} 次共现</span>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("暂无显著类别关联。")

st.markdown("---")

# -- Row 5: Overdue SLA Detail Table --
if data["overdues"]:
    st.markdown("### ⏰ SLA 超时明细")
    st.caption("以下工单已超时未解决（按紧急度分级口径），需立即关注。")

    for o in data["overdues"][:8]:
        oid = o["id"]
        hours = o.get("hours_open", 0)
        time_str = f"{hours // 24} 天" if hours >= 24 else f"{hours} 小时"
        title = o.get("title", "")[:40]
        cat = o.get("category", "")
        loc = o.get("location", "")
        urg = o.get("urgency", "")
        reported = o.get("reported_at", "")[:10]
        o_level = o.get("level", "")

        level = "🔴" if o_level == "critical" else "🟡"
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(
                    f'{level} <strong>#{oid} {title}</strong>&nbsp;{tag(urg)}',
                    unsafe_allow_html=True,
                )
                st.caption(
                    f'{cat} · 📍 {loc} · 🕐 {reported} · '
                    f'<span style="color:{TOKEN["danger"]};font-weight:600;">超时 {time_str}</span>',
                    unsafe_allow_html=True,
                )
            with c2:
                st.caption("已滞留")
                st.markdown(
                    f'<span style="font-size:1.3em;font-weight:800;color:{TOKEN["danger"]};">{time_str}</span>',
                    unsafe_allow_html=True,
                )
