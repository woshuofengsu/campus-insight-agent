# ui/pages/transparency.py
"""📊 治理透明窗 · 督 — 多维健康度 + 趋势分析 + 参与足迹."""
import streamlit as st
import altair as alt
import pandas as pd
from ui.cache import (
    cached_issues_stats as get_issues_stats,
    cached_proposals_stats as get_proposals_stats,
    cached_active_topics as get_active_topics,
    cached_health_score as compute_health_score,
    cached_issues_timeline as get_issues_timeline,
    cached_issues as get_issues,
    cached_proposals as get_proposals,
    cached_feedback_stats as get_feedback_stats,
    cached_knowledge_base as get_knowledge_base,
)
from ui.components import TOKEN, section, stat, info_card, ooda_nav, CAT_LABEL, configure_altair
import logging
_log = logging.getLogger(__name__)

# ── Page header ──
st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">📊 治理透明窗</span>'
    f'<span style="background:{TOKEN["success"]};color:#fff;font-size:0.7em;font-weight:600;'
    f'padding:2px 8px;border-radius:99px;margin-left:8px;vertical-align:middle;">督</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption("数据透明就是最好的信任机制——看看校园治理的真实状况。")

ooda_nav("transparency")

st.markdown("---")

# -- Health score — multi-dimensional --

try:
    health = compute_health_score()
    issue_stats = get_issues_stats()
    proposal_stats = get_proposals_stats()
except Exception as e:
    st.error(f"⚠️ 数据加载失败：{e}")
    st.info("请刷新页面重试，或检查数据库连接。")
    st.stop()

grade = health["grade"]
score = health["score"]

if grade == "优":
    health_emoji, health_color = "🟢", TOKEN["success"]
    health_detail = "校园治理健康度优秀，问题解决效率高、积压可控。"
elif grade == "良":
    health_emoji, health_color = "🟡", TOKEN["warning"]
    health_detail = "治理基本正常，仍有提升空间。"
else:
    health_emoji, health_color = "🔴", TOKEN["danger"]
    health_detail = "大量问题积压，需要加快处理速度。"

# Health hero card
st.markdown(
    f'<div style="background:{TOKEN["card_bg"]};border:2px solid {health_color};'
    f'border-radius:{TOKEN["radius_card"]};padding:20px 24px;text-align:center;'
    f'box-shadow:0 2px 8px rgba(0,0,0,0.06);margin-bottom:16px;">'
    f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};margin-bottom:6px;">🏥 校园治理健康度</div>'
    f'<div style="font-size:3em;font-weight:800;color:{health_color};">'
    f'{health_emoji} {grade} <span style="font-size:0.5em;color:{TOKEN["text_sec"]};">{score}分</span></div>'
    f'<div style="font-size:0.9em;color:{TOKEN["text_sec"]};margin-top:4px;">{health_detail}</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# Three sub-dimensions
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
        f'border-top:3px solid {TOKEN["accent"]};border-radius:{TOKEN["radius_card"]};'
        f'padding:14px 10px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
        f'<div style="font-size:0.7em;color:{TOKEN["text_sec"]};margin-bottom:3px;">✅ 解决率（40%权重）</div>'
        f'<div style="font-size:1.5em;font-weight:800;color:{TOKEN["accent"]};">{health["resolution_rate"]}%</div>'
        f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">{health["new_recent"]} 件新上报</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with c2:
    avg_days = health.get("avg_days")
    days_text = f"{avg_days} 天" if avg_days else "暂无数据"
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
        f'border-top:3px solid {TOKEN["warning"]};border-radius:{TOKEN["radius_card"]};'
        f'padding:14px 10px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
        f'<div style="font-size:0.7em;color:{TOKEN["text_sec"]};margin-bottom:3px;">⏱️ 平均解决周期（35%权重）</div>'
        f'<div style="font-size:1.5em;font-weight:800;color:{TOKEN["warning"]};">{days_text}</div>'
        f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">速度得分 {health["speed_score"]} 分</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
with c3:
    trend = health["trend"]
    trend_color = TOKEN["success"] if "↓" in trend else TOKEN["warning"] if "→" in trend else TOKEN["danger"]
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
        f'border-top:3px solid {trend_color};border-radius:{TOKEN["radius_card"]};'
        f'padding:14px 10px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
        f'<div style="font-size:0.7em;color:{TOKEN["text_sec"]};margin-bottom:3px;">📉 积压趋势（25%权重）</div>'
        f'<div style="font-size:1.5em;font-weight:800;color:{trend_color};">{trend}</div>'
        f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">{health["resolved_recent"]} 件已解决</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# -- Trend chart — 7-day activity --

section("近7天治理活跃度")

timeline = get_issues_timeline(7)
if timeline:
    df_timeline = pd.DataFrame(timeline)
    df_melted = pd.melt(
        df_timeline, id_vars=["day"],
        value_vars=["new_count", "resolved_count"],
        var_name="类型", value_name="数量",
    )
    df_melted["类型"] = df_melted["类型"].replace({"new_count": "新增上报", "resolved_count": "已解决"})

    # Short date labels
    df_melted["日期"] = df_melted["day"].str[5:]  # MM-DD

    chart = configure_altair(
        alt.Chart(df_melted)
        .mark_line(point=True, strokeWidth=2.5)
        .encode(
            x=alt.X("日期:N", title=None, sort=df_timeline["day"].str[5:].tolist()),
            y=alt.Y("数量:Q", title=None),
            color=alt.Color("类型:N", scale=alt.Scale(
                domain=["新增上报", "已解决"],
                range=[TOKEN["danger"], TOKEN["success"]],
            ), legend=alt.Legend(orient="top")),
        )
        .properties(height=180)
    )
    st.altair_chart(chart, width="stretch")
else:
    info_card("治理活动开始后将展示 7 天内上报和解决的动态趋势。")

st.markdown("---")

# -- Core KPIs --

section("核心指标总览")

total_i = issue_stats["total"]
total_p = proposal_stats["total"]
by_status = issue_stats.get("by_status", {})
pending = by_status.get("待处理", 0)

topics = get_active_topics(limit=100)
total_participants = sum(t.get("participant_count", 0) for t in topics)

c1, c2, c3, c4, c5 = st.columns(5)
with c1:
    stat("总上报", str(total_i), TOKEN["accent"])
with c2:
    stat("解决率", f"{health['resolution_rate']}%", TOKEN["success"])
with c3:
    stat("待处理", str(pending), TOKEN["warning"] if pending > 0 else TOKEN["success"])
with c4:
    stat("提案", str(total_p), TOKEN["accent"])
with c5:
    stat("参与人次", str(total_participants), TOKEN["accent"])

st.markdown("---")

# -- Issue status pipeline --

section("工单流转")

if total_i > 0:
    pipeline_data = [
        ("⏳", "待处理", by_status.get("待处理", 0), TOKEN["danger"]),
        ("🔄", "处理中", by_status.get("处理中", 0), TOKEN["warning"]),
        ("✅", "已解决", by_status.get("已解决", 0), TOKEN["success"]),
    ]
    cols = st.columns(3)
    for idx, (emoji, label, count, color) in enumerate(pipeline_data):
        with cols[idx]:
            pct = f"{count/total_i*100:.0f}%" if total_i > 0 else "0%"
            st.markdown(
                f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
                f'border-top:3px solid {color};border-radius:{TOKEN["radius_card"]};'
                f'padding:16px 10px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
                f'<div style="font-size:1.5em;margin-bottom:4px;">{emoji}</div>'
                f'<div style="font-size:1.6em;font-weight:800;color:{TOKEN["text"]};">{count}</div>'
                f'<div style="font-size:0.8em;color:{TOKEN["text_sec"]};">{label}（{pct}）</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

st.markdown("---")

# -- Category breakdown --

section("问题类别明细")

by_cat = issue_stats.get("by_category", {})
if by_cat:
    cat_label = CAT_LABEL
    df_cat = pd.DataFrame([
        {"类别": cat_label.get(k, k), "数量": v, "占比": f"{v/total_i*100:.0f}%"}
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
    ])
    col_chart, col_table = st.columns([3, 2])
    with col_chart:
        chart = configure_altair(
            alt.Chart(df_cat)
            .mark_bar(color=TOKEN["success"], opacity=0.85, size=20)
            .encode(
                x=alt.X("数量:Q"),
                y=alt.Y("类别:N", title=None, sort="-x"),
            )
            .properties(height=200)
        )
        st.altair_chart(chart, width="stretch")
    with col_table:
        st.dataframe(
            df_cat.set_index("类别"),
            column_config={"数量": st.column_config.NumberColumn(width="small")},
            width="stretch",
            height=220,
        )

st.markdown("---")

# -- 📢 舆情情感分析 — from feedback_items --

section("学生舆情分析")

fb = get_feedback_stats()
if fb["total"] > 0:
    pos, neg, neu = fb["positive"], fb["negative"], fb["neutral"]
    total_fb = fb["total"]

    # Sentiment bar
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
            f'border-top:3px solid {TOKEN["success"]};border-radius:{TOKEN["radius_card"]};'
            f'padding:12px 8px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
            f'<div style="font-size:0.7em;color:{TOKEN["text_sec"]};">😊 正面</div>'
            f'<div style="font-size:1.4em;font-weight:800;color:{TOKEN["success"]};">{pos}</div>'
            f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">{pos/total_fb*100:.0f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
            f'border-top:3px solid {TOKEN["warning"]};border-radius:{TOKEN["radius_card"]};'
            f'padding:12px 8px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
            f'<div style="font-size:0.7em;color:{TOKEN["text_sec"]};">😐 中性</div>'
            f'<div style="font-size:1.4em;font-weight:800;color:{TOKEN["warning"]};">{neu}</div>'
            f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">{neu/total_fb*100:.0f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
            f'border-top:3px solid {TOKEN["danger"]};border-radius:{TOKEN["radius_card"]};'
            f'padding:12px 8px;text-align:center;box-shadow:{TOKEN["shadow"]};">'
            f'<div style="font-size:0.7em;color:{TOKEN["text_sec"]};">😟 负面</div>'
            f'<div style="font-size:1.4em;font-weight:800;color:{TOKEN["danger"]};">{neg}</div>'
            f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};">{neg/total_fb*100:.0f}%</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Hot feedback topics
    if fb.get("top_topics"):
        st.markdown(
            f'<div style="font-size:0.78em;color:{TOKEN["text_muted"]};margin:10px 0 4px;">🔥 热议话题</div>',
            unsafe_allow_html=True,
        )
        topic_tags = "　".join(
            f'<span style="background:{TOKEN["warning_bg"]};color:{TOKEN["warning"]};'
            f'padding:2px 10px;border-radius:99px;font-size:0.82em;">{t["topic"]}（{t["cnt"]}条）</span>'
            for t in fb.get("top_topics", [])[:5]
        )
        st.markdown(f'<div style="line-height:2.2;">{topic_tags}</div>', unsafe_allow_html=True)

st.markdown("---")

# -- ⚠️ 积压预警 — oldest unresolved issues --

section("积压预警")

stale_issues = sorted(
    get_issues(status="待处理", limit=50),
    key=lambda i: i.get("reported_at", ""),
)

if stale_issues:
    # Find issues older than 5 days
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    old_issues = [i for i in stale_issues if i.get("reported_at", "") <= cutoff]
    if old_issues:
        st.warning(f"🚨 {len(old_issues)} 个问题超过 5 天未处理，建议优先解决：")
        cols = st.columns(2)
        for idx, issue in enumerate(old_issues[:6]):
            with cols[idx % 2]:
                st.markdown(
                    f'<div style="background:{TOKEN["danger_bg"]};border:1px solid {TOKEN["danger_border"]};'
                    f'border-radius:{TOKEN["radius_card"]};padding:8px 12px;margin:3px 0;font-size:0.84em;">'
                    f'🔴 <strong>#{issue["id"]}</strong> {issue.get("title","")[:30]}'
                    f'<br><span style="color:{TOKEN["text_muted"]};font-size:0.8em;">'
                    f'{issue.get("category","")} · {issue.get("reported_at","")[:10]} · {issue.get("urgency","")}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
    else:
        st.success("✅ 所有待处理问题都在 5 天内，没有积压。")
else:
    st.success("✅ 暂无待处理问题。")

st.markdown("---")

# -- 🔥 类别热力矩阵 — 类别 × 状态交叉透视 --

section("类别热力矩阵")

issues_all = get_issues(limit=500)
if issues_all and len(issues_all) >= 5:
    from collections import Counter
    # Build cross-tab: category × status
    heat_data: dict[str, dict[str, int]] = {}
    all_statuses: set[str] = set()
    for i in issues_all:
        cat = i.get("category", "其他")
        sts = i.get("status", "未知")
        all_statuses.add(sts)
        if cat not in heat_data:
            heat_data[cat] = {}
        heat_data[cat][sts] = heat_data[cat].get(sts, 0) + 1

    # Sort categories by total
    cat_totals = {c: sum(sd.values()) for c, sd in heat_data.items()}
    sorted_cats = sorted(cat_totals, key=cat_totals.get, reverse=True)

    # Build DataFrame
    status_list = ["待处理", "处理中", "已解决"]
    heat_rows = []
    for cat in sorted_cats:
        row = {"类别": CAT_LABEL.get(cat, cat)[:4]}
        for sts in status_list:
            row[sts] = heat_data.get(cat, {}).get(sts, 0)
        heat_rows.append(row)

    df_heat = pd.DataFrame(heat_rows)
    if not df_heat.empty and len(df_heat.columns) > 1:
        # Melt for Altair heatmap
        id_vars = ["类别"]
        value_vars = [c for c in df_heat.columns if c != "类别"]
        df_melt = df_heat.melt(id_vars=id_vars, value_vars=value_vars,
                               var_name="状态", value_name="数量")

        heat_chart = configure_altair(
            alt.Chart(df_melt)
            .mark_rect(stroke=TOKEN["border"], strokeWidth=1)
            .encode(
                x=alt.X("状态:N", title=None, sort=status_list,
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("类别:N", title=None, sort=sorted_cats),
                color=alt.Color("数量:Q", scale=alt.Scale(
                    scheme="orangered", type="sequential",
                ), legend=alt.Legend(orient="right", title="数量")),
                tooltip=["类别", "状态", "数量"],
            )
            .properties(height=max(120, len(sorted_cats) * 32))
        )
        st.altair_chart(heat_chart, width="stretch")
        st.caption("颜色越深表示该类别在该状态下的工单越多。关注深色「待处理」区域。")

st.markdown("---")

# -- 🏆 贡献者排行榜 TOP 10 --

section("社区贡献者 TOP 10")

if issues_all and len(issues_all) >= 3:
    from collections import Counter
    from data.database import get_proposals

    # ── Most active reporters ──
    author_counts = Counter(i.get("author", "匿名") for i in issues_all if i.get("author"))
    top_reporters = author_counts.most_common(10)

    # ── Most supported proposals ──
    proposals_all = get_proposals(limit=200)
    prop_authors: dict[str, int] = {}
    for p in proposals_all:
        auth = p.get("author", "匿名")
        supporters = p.get("supporter_count", 0)
        prop_authors[auth] = prop_authors.get(auth, 0) + supporters

    # Build leaderboard rows
    leaderboard: list[dict] = []
    seen = set()
    for rank, (author, count) in enumerate(top_reporters):
        seen.add(author)
        supporters = prop_authors.get(author, 0)
        leaderboard.append({
            "排名": rank + 1,
            "贡献者": author[:12],
            "上报数": count,
            "附议数": supporters,
            "影响力": count * 2 + supporters,
        })

    # Add proposal-only authors not already in list
    extra_authors = sorted(prop_authors.items(), key=lambda x: -x[1])
    for author, supporters in extra_authors:
        if author not in seen and len(leaderboard) < 10:
            leaderboard.append({
                "排名": len(leaderboard) + 1,
                "贡献者": author[:12],
                "上报数": 0,
                "附议数": supporters,
                "影响力": supporters,
            })
            seen.add(author)

    if leaderboard:
        # Sort by influence
        leaderboard.sort(key=lambda x: -x["影响力"])
        for i, row in enumerate(leaderboard):
            row["排名"] = i + 1

        df_leader = pd.DataFrame(leaderboard[:10])

        # Top 3 medals
        def _medal(rank):
            return {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"{rank}")

        # Render as styled cards for top 3, table for rest
        c_l1, c_l2 = st.columns([3, 2])

        with c_l1:
            # Horizontal bar chart
            df_bar = df_leader.head(10).copy()
            df_bar["贡献者"] = df_bar["排名"].apply(_medal) + " " + df_bar["贡献者"]
            bar_chart = configure_altair(
                alt.Chart(df_bar)
                .mark_bar(color=TOKEN["accent"], opacity=0.85, size=18)
                .encode(
                    x=alt.X("影响力:Q", title=None),
                    y=alt.Y("贡献者:N", title=None, sort="-x"),
                    tooltip=["贡献者", "上报数", "附议数", "影响力"],
                )
                .properties(height=200)
            )
            st.altair_chart(bar_chart, width="stretch")

        with c_l2:
            st.dataframe(
                df_leader.set_index("排名"),
                column_config={
                    "贡献者": st.column_config.TextColumn("贡献者"),
                    "上报数": st.column_config.NumberColumn("上报"),
                    "附议数": st.column_config.NumberColumn("附议"),
                    "影响力": st.column_config.NumberColumn("影响力⭐"),
                },
                column_order=["贡献者", "上报数", "附议数", "影响力"],
                width="stretch",
                height=240,
                hide_index=False,
            )

        st.caption("影响力 = 上报数×2 + 获得附议数。积极上报问题和提出优秀提案都能为校园治理做出贡献！")

st.markdown("---")

# -- Recent activity feed --

section("最近动态")

issues = get_issues(limit=5)
proposals_list = get_proposals(sort_by="latest", limit=3)

feed_items = []
for i in issues:
    s = i.get("status", "")
    icon = {"待处理": "📝", "处理中": "🔄", "已解决": "✅"}.get(s, "📌")
    feed_items.append({
        "icon": icon,
        "text": f'{i.get("title", "")} — <span style="color:{TOKEN["text_muted"]};">{s}</span>',
        "time": i.get("reported_at", "")[:10],
    })
for p in proposals_list:
    feed_items.append({
        "icon": "💡",
        "text": f'新提案：{p.get("title", "")} — 👍 {p.get("supporter_count", 0)} 人附议',
        "time": p.get("created_at", "")[:10],
    })
feed_items.sort(key=lambda x: x["time"], reverse=True)

if feed_items:
    for item in feed_items[:12]:
        st.markdown(
            f'<div style="font-size:0.88em;padding:4px 0;border-bottom:1px solid {TOKEN["border"]};">'
            f'{item["icon"]} {item["text"]} '
            f'<span style="color:{TOKEN["text_muted"]};font-size:0.78em;">{item["time"]}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")
st.markdown(
    f'<div style="text-align:center;font-size:0.82em;color:{TOKEN["text_muted"]};margin-top:12px;">'
    f'数据实时更新 · 每一次参与都让校园更好 🌱</div>',
    unsafe_allow_html=True,
)
