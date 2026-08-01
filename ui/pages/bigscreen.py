# ui/pages/bigscreen.py
"""📺 治理大屏 — 竞赛演示专用，指挥中心风格.

Features:
  - Dark command-center theme with glowing accents
  - Scrolling activity ticker at bottom (CSS animation)
  - Campus district heatmap (CSS grid)
  - Glowing KPI cards with pulse animation on anomalies
  - Real-time clock with seconds (st.components.v1.html)
  - Demo mode: auto-carousel with mock data (?demo=1)
  - Auto-refresh every 30s (configurable via ?refresh=N)
"""
import logging
import streamlit as st
import altair as alt
import pandas as pd
from datetime import datetime, timedelta
from ui.components import TOKEN

_log = logging.getLogger(__name__)


# Mock data for demo mode

def _mock_issue_stats():
    return {
        "total": 127, "by_status": {"待处理": 12, "处理中": 8, "已解决": 107},
        "by_category": {
            "设施维修": 35, "环境卫生": 22, "安全隐患": 8, "网络服务": 19,
            "餐饮问题": 16, "教学设备": 11, "校园管理": 14, "其他": 2,
        },
    }

def _mock_proposal_stats():
    return {"total": 24, "by_status": {"讨论中": 14, "已回应": 5, "已采纳": 3, "已实施": 2}}

def _mock_health_score():
    return {"score": 78, "grade": "良", "resolution_rate": 84, "avg_days": 4.2,
            "new_recent": 15, "resolved_recent": 14, "speed_score": 72, "trend": "↓"}

def _mock_timeline():
    today = datetime.now()
    data = []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        label = d.strftime("%Y-%m-%d")
        new_c = max(0, int(3 + (i - 3.5) ** 2 * 0.7 + (hash(str(d.day)) % 5)))
        res_c = max(0, new_c - (hash(str(d.day + 100)) % 4))
        data.append({"day": label, "new_count": new_c, "resolved_count": res_c})
    return data

def _mock_recent_issues():
    today = datetime.now()
    return [
        {"id": 127, "title": "校园主干道路面坑洼积水", "status": "待处理", "category": "设施维修", "urgency": "普通", "reported_at": today.strftime("%Y-%m-%d")},
        {"id": 126, "title": "一食堂餐具清洗不干净", "status": "处理中", "category": "环境卫生", "urgency": "紧急", "reported_at": (today - timedelta(days=1)).strftime("%Y-%m-%d")},
        {"id": 125, "title": "宿舍区围墙出现裂缝", "status": "处理中", "category": "安全隐患", "urgency": "紧急", "reported_at": (today - timedelta(days=1)).strftime("%Y-%m-%d")},
        {"id": 124, "title": "图书馆电子资源访问慢", "status": "待处理", "category": "网络服务", "urgency": "普通", "reported_at": (today - timedelta(days=1)).strftime("%Y-%m-%d")},
        {"id": 123, "title": "教学楼多媒体设备网络不稳定", "status": "处理中", "category": "网络服务", "urgency": "紧急", "reported_at": (today - timedelta(days=2)).strftime("%Y-%m-%d")},
        {"id": 122, "title": "二食堂二楼空调不制冷", "status": "待处理", "category": "设施维修", "urgency": "普通", "reported_at": (today - timedelta(days=2)).strftime("%Y-%m-%d")},
        {"id": 121, "title": "操场看台座椅锈蚀严重", "status": "已解决", "category": "设施维修", "urgency": "普通", "reported_at": (today - timedelta(days=3)).strftime("%Y-%m-%d")},
        {"id": 120, "title": "教学楼一楼售货机故障", "status": "已解决", "category": "设施维修", "urgency": "普通", "reported_at": (today - timedelta(days=3)).strftime("%Y-%m-%d")},
        {"id": 119, "title": "一食堂麻辣烫涨价问题", "status": "待处理", "category": "餐饮问题", "urgency": "普通", "reported_at": (today - timedelta(days=3)).strftime("%Y-%m-%d")},
        {"id": 118, "title": "图书馆自习区插座不足", "status": "已解决", "category": "设施维修", "urgency": "普通", "reported_at": (today - timedelta(days=4)).strftime("%Y-%m-%d")},
    ]

def _mock_feedback_stats():
    return {"total": 89, "positive": 52, "negative": 21, "neutral": 16}

# THEME — Dark command center

BG = "#0b0f19"          # page background
SURFACE = "#141928"     # card background
SURFACE_RAISED = "#1c2233"
BORDER = "rgba(255,255,255,0.06)"   # subtle border
BORDER_GLOW = "rgba(121,132,245,0.15)"
ACCENT = "#7984f5"      # indigo accent
ACCENT_GLOW = "#8f98f7"
SUCCESS = "#4ade80"
SUCCESS_GLOW = "#6ee7b7"
WARNING = "#f59e0b"
WARNING_GLOW = "#fbbf24"
DANGER = "#f87171"
DANGER_GLOW = "#fca5a5"
PURPLE = "#a78bfa"
PURPLE_GLOW = "#c4b5fd"
TEXT = "#e9ecf2"
TEXT_SEC = "#99a1b3"
TEXT_MUTED = "#616a80"

st.markdown(f"""
<style>
    /* ── Global overrides ── */
    .stApp {{
        background: {BG} !important;
    }}
    html, body, #root {{
        background: {BG} !important;
    }}
    .block-container {{
        padding: 1rem 1.8rem !important;
        max-width: 100% !important;
    }}
    header, footer, #MainMenu, .stDeployButton {{
        display: none !important;
    }}

    /* ── Grid dot background ── */
    .stApp::before {{
        content: '';
        position: fixed; inset: 0; z-index: 0; pointer-events: none;
        background-image:
            radial-gradient(circle, {BORDER} 1px, transparent 1px);
        background-size: 40px 40px;
        opacity: 0.4;
    }}
    .stApp > * {{ position: relative; z-index: 1; }}

    /* ── Glowing KPI card ── */
    .kpi-card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 18px 14px;
        text-align: center;
        position: relative;
        overflow: hidden;
        transition: all 0.3s ease;
    }}
    .kpi-card::before {{
        content: '';
        position: absolute; top: 0; left: 0; right: 0;
        height: 2px;
        border-radius: 2px;
        opacity: 0.7;
    }}
    .kpi-card.warn::before {{
        background: linear-gradient(90deg, transparent, {WARNING_GLOW}, transparent);
    }}
    .kpi-card.danger::before {{
        background: linear-gradient(90deg, transparent, {DANGER_GLOW}, transparent);
    }}
    .kpi-card.success::before {{
        background: linear-gradient(90deg, transparent, {SUCCESS_GLOW}, transparent);
    }}
    .kpi-card.info::before {{
        background: linear-gradient(90deg, transparent, {ACCENT_GLOW}, transparent);
    }}
    .kpi-card.purple::before {{
        background: linear-gradient(90deg, transparent, {PURPLE_GLOW}, transparent);
    }}
    .kpi-card.glow {{
        box-shadow: 0 0 20px rgba(59,130,246,0.15), inset 0 1px 0 rgba(255,255,255,0.03);
    }}

    /* ── Number counter ── */
    .kpi-value {{
        font-size: 2.2em;
        font-weight: 800;
        font-variant-numeric: tabular-nums;
        font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
        letter-spacing: -0.02em;
        line-height: 1.2;
    }}
    .kpi-label {{
        font-size: 0.68em;
        color: {TEXT_MUTED};
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 6px;
    }}

    /* ── Anomaly pulse ── */
    @keyframes pulse-ring {{
        0% {{ box-shadow: 0 0 0 0 {DANGER}66; }}
        70% {{ box-shadow: 0 0 0 12px {DANGER}00; }}
        100% {{ box-shadow: 0 0 0 0 {DANGER}00; }}
    }}
    @keyframes glow-breath {{
        0%, 100% {{ box-shadow: 0 0 8px {ACCENT}33, 0 0 20px {ACCENT}11; }}
        50% {{ box-shadow: 0 0 16px {ACCENT}55, 0 0 35px {ACCENT}22; }}
    }}
    @keyframes fadeInUp {{
        from {{ opacity: 0; transform: translateY(16px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    @keyframes slideRight {{
        from {{ opacity: 0; transform: translateX(-24px); }}
        to   {{ opacity: 1; transform: translateX(0); }}
    }}
    @keyframes ticker {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}

    .pulse-anomaly {{ animation: pulse-ring 2s ease-out infinite; }}
    .glow-breathe {{ animation: glow-breath 3s ease-in-out infinite; }}
    .fade-up {{ animation: fadeInUp 0.6s ease-out both; }}

    /* ── Health ring ── */
    .health-ring {{
        display: inline-flex; align-items: center; justify-content: center;
        width: 90px; height: 90px; border-radius: 50%;
        border: 4px solid;
        position: relative;
    }}
    .health-ring::after {{
        content: '';
        position: absolute; inset: -8px; border-radius: 50%;
        opacity: 0.3;
    }}

    /* ── Surface card ── */
    .surface-card {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        padding: 16px;
    }}

    /* ── Section title ── */
    .section-title {{
        font-size: 0.78em; font-weight: 600;
        color: {TEXT_SEC};
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin-bottom: 10px;
        padding-bottom: 8px;
        border-bottom: 1px solid {BORDER};
    }}

    /* ── Demo badge ── */
    .demo-badge {{
        position: fixed; top: 16px; right: 28px; z-index: 9999;
        background: linear-gradient(135deg, #f59e0b, #d97706);
        color: #000; font-weight: 800; font-size: 0.75em;
        padding: 5px 14px; border-radius: 99px;
        box-shadow: 0 0 20px rgba(245,158,11,0.4);
        letter-spacing: 0.05em;
    }}

    /* ── Ticker ── */
    .ticker-wrap {{
        background: {SURFACE_RAISED};
        border: 1px solid {BORDER};
        border-radius: 8px;
        overflow: hidden;
        height: 32px;
        position: relative;
    }}
    .ticker-track {{
        display: flex;
        animation: ticker 30s linear infinite;
        white-space: nowrap;
        height: 100%;
        align-items: center;
    }}
    .ticker-item {{
        display: inline-flex; align-items: center; gap: 6px;
        padding: 0 24px;
        font-size: 0.78em;
        color: {TEXT_SEC};
        white-space: nowrap;
    }}
    .ticker-dot {{
        width: 6px; height: 6px; border-radius: 50%;
        background: {ACCENT};
        box-shadow: 0 0 6px {ACCENT_GLOW};
    }}
    .ticker-wrap:hover .ticker-track {{
        animation-play-state: paused;
    }}

    /* ── Campus heatmap grid ── */
    .heat-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        grid-template-rows: repeat(3, 1fr);
        gap: 6px;
        height: 200px;
    }}
    .heat-cell {{
        border-radius: 8px;
        display: flex; align-items: center; justify-content: center;
        flex-direction: column;
        font-size: 0.7em;
        font-weight: 600;
        color: {TEXT};
        border: 1px solid transparent;
        transition: all 0.3s ease;
        cursor: default;
    }}
    .heat-cell:hover {{
        transform: scale(1.03);
        border-color: {ACCENT_GLOW};
        box-shadow: 0 0 16px rgba(59,130,246,0.2);
        z-index: 2;
    }}

    /* ── Recent issue feed ── */
    .issue-row {{
        display: flex; align-items: center; gap: 10px;
        padding: 6px 10px;
        font-size: 0.8em;
        border-radius: 6px;
        margin: 2px 0;
        transition: background 0.2s;
    }}
    .issue-row:hover {{ background: {SURFACE_RAISED}; }}
    .issue-row.urgent {{
        border-left: 3px solid {DANGER};
        background: linear-gradient(90deg, {DANGER}18 0%, transparent 100%);
    }}

    /* ── Chart overrides for dark theme ── */
    .vega-embed {{ background: transparent !important; }}

    /* ── Scrollbar ── */
    ::-webkit-scrollbar {{ width: 5px; }}
    ::-webkit-scrollbar-track {{ background: {BG}; }}
    ::-webkit-scrollbar-thumb {{ background: {BORDER}; border-radius: 3px; }}
</style>
""", unsafe_allow_html=True)

# Data loading — real data first, mock only for demo or empty DB

_using_mock = False

try:
    from ui.cache import (
        cached_issues_stats, cached_proposals_stats, cached_health_score,
        cached_issues_timeline, cached_issues, cached_feedback_stats,
    )
    health = cached_health_score()
    issue_stats = cached_issues_stats()
    proposal_stats = cached_proposals_stats()
    feedback = cached_feedback_stats()
    timeline = cached_issues_timeline(7)
    recent_issues = cached_issues(limit=10)
    if issue_stats.get("total", 0) == 0:
        _using_mock = True
except Exception:  # non-critical: logged and suppressed
    _log.warning("Data loading failed, falling back to mock data", exc_info=True)
    _using_mock = True

if _using_mock:
    health = _mock_health_score()
    issue_stats = _mock_issue_stats()
    proposal_stats = _mock_proposal_stats()
    feedback = _mock_feedback_stats()
    timeline = _mock_timeline()
    recent_issues = _mock_recent_issues()

total_i = issue_stats["total"]
by_status = issue_stats.get("by_status", {})
resolved = by_status.get("已解决", 0)
pending = by_status.get("待处理", 0)
processing = by_status.get("处理中", 0)
total_p = proposal_stats["total"]
grade = health["grade"]
score = health["score"]
urgent_count = sum(1 for i in recent_issues if i.get("urgency") == "紧急" and i.get("status") != "已解决")
has_anomaly = pending > 10

now = datetime.now()

# Determine theme-aware colors for the clock iframe
_clock_text = "#e2e8f0" if st.session_state.get("_campus_theme") == "dark" else "#1e293b"
_clock_muted = "#94a3b8" if st.session_state.get("_campus_theme") == "dark" else "#64748b"
_clock_bg = "transparent"

st.components.v1.html(f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: {_clock_bg};
    font-family: 'JetBrains Mono', 'SF Mono', 'Fira Code', monospace;
    display: flex; justify-content: flex-end; align-items: center;
    height: 100%; padding-right: 4px;
  }}
  #clock-bar {{ text-align: right; }}
  #clock-time {{
    font-size: 1.5em; font-weight: 700; color: {_clock_text};
    font-family: 'JetBrains Mono', monospace;
  }}
  #clock-date {{
    font-size: 0.78em; color: {_clock_muted}; margin-left: 12px;
  }}
</style>
</head>
<body>
<div id="clock-bar">
  <span id="clock-time">{now.strftime("%H:%M:%S")}</span>
  <span id="clock-date">{now.strftime("%Y-%m-%d")}</span>
</div>
<script>
  const weekdays = ['周日','周一','周二','周三','周四','周五','周六'];
  function tick() {{
    const now = new Date();
    document.getElementById('clock-time').textContent =
      [now.getHours(), now.getMinutes(), now.getSeconds()]
        .map(n => String(n).padStart(2, '0')).join(':');
    document.getElementById('clock-date').textContent =
      now.getFullYear() + '-' +
      String(now.getMonth()+1).padStart(2,'0') + '-' +
      String(now.getDate()).padStart(2,'0') + ' ' +
      weekdays[now.getDay()];
  }}
  tick();
  setInterval(tick, 1000);
</script>
</body>
</html>
""", height=52)

# HEADER

st.markdown(f"""
<div class="fade-up" style="margin-bottom:8px;">
    <div style="font-size:1.8em;font-weight:800;color:{TEXT};letter-spacing:-0.02em;
        display:flex;align-items:center;gap:12px;">
        <span style="font-size:1.3em;">🏛️</span>
        校园治理实时指挥中心
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;
            background:{SUCCESS};box-shadow:0 0 8px {SUCCESS_GLOW};margin-left:4px;"
            title="系统在线"></span>
    </div>
    <div style="font-size:0.75em;color:{TEXT_MUTED};margin-top:2px;letter-spacing:0.05em;">
        CAMPUSINSIGHT · 知报议督 · 治理闭环
    </div>
</div>
""", unsafe_allow_html=True)

st.markdown(f'<div style="height:1px;background:linear-gradient(90deg,transparent,{BORDER_GLOW},transparent);margin:12px 0;"></div>', unsafe_allow_html=True)

# KPI ROW — 6 glowing cards with animated numbers

resolution_rate = health.get("resolution_rate", 0)
avg_days = health.get("avg_days", 0) or 0
pos_pct = feedback["positive"] / feedback["total"] * 100 if feedback["total"] > 0 else 0

kpi_data = [
    ("🏥 治理健康度", f"{score}", "分", PURPLE, "purple", f"{grade}"),
    ("📝 累计上报", str(total_i), "", ACCENT, "info", ""),
    ("✅ 已解决", f"{resolved}", f" ({resolution_rate}%)", SUCCESS, "success", ""),
    ("⏳ 待处理", str(pending), " 件", DANGER if has_anomaly else WARNING,
     "danger" if has_anomaly else "warn", f"🔥 {urgent_count} 紧急" if urgent_count > 0 else ""),
    ("💡 总提案", str(total_p), "", PURPLE, "purple", ""),
    ("😊 正面舆情", f"{pos_pct:.0f}", "%", SUCCESS, "success", f"共 {feedback['total']} 条"),
]

cols = st.columns(6)
for idx, (label, value, suffix, color, style, sub) in enumerate(kpi_data):
    extra_class = "glow" if (style == "danger" and has_anomaly) or style == "success" else ""
    with cols[idx]:
        st.markdown(f"""
<div class="kpi-card {style} {extra_class} fade-up" style="animation-delay:{idx*0.06}s;">
    <div class="kpi-label">{label}</div>
    <div class="kpi-value" style="color:{color};">{value}{suffix}</div>
    {"<div style='font-size:0.68em;color:" + TEXT_MUTED + ";margin-top:2px;'>" + sub + "</div>" if sub else ""}
</div>
""", unsafe_allow_html=True)

# MAIN GRID: trend chart + health ring + pipeline

col_main, col_side = st.columns([3, 2])

with col_main:
    st.markdown('<div class="section-title">📈 近 7 天治理趋势</div>', unsafe_allow_html=True)

    if timeline:
        df_timeline = pd.DataFrame(timeline)
        df_melted = pd.melt(
            df_timeline, id_vars=["day"],
            value_vars=["new_count", "resolved_count"],
            var_name="类型", value_name="数量",
        )
        df_melted["类型"] = df_melted["类型"].replace({"new_count": "新增上报", "resolved_count": "已解决"})
        df_melted["日期"] = df_melted["day"].str[5:]

        base = alt.Chart(df_melted).encode(
            x=alt.X("日期:N", title=None, sort=df_timeline["day"].str[5:].tolist(),
                    axis=alt.Axis(labelColor=TEXT_MUTED, gridColor=BORDER, titleColor=TEXT_MUTED)),
            y=alt.Y("数量:Q", title=None, axis=alt.Axis(labelColor=TEXT_MUTED, gridColor=BORDER)),
        )
        line = base.mark_line(strokeWidth=3, point={"size": 70, "filled": True}).encode(
            color=alt.Color("类型:N", scale=alt.Scale(
                domain=["新增上报", "已解决"],
                range=[DANGER, SUCCESS],
            ), legend=alt.Legend(orient="top", title=None, labelColor=TEXT_SEC)),
        )
        chart = line.properties(height=220).configure(background="transparent").configure_view(strokeWidth=0)
        st.altair_chart(chart, width="stretch")

        recent_new = int(df_timeline.iloc[-1].get("new_count", 0))
        recent_res = int(df_timeline.iloc[-1].get("resolved_count", 0))
        if abs(recent_new - recent_res) <= 2:
            trend_note = "📊 新增与解决持平，治理节奏良好"
        elif recent_new > recent_res:
            trend_note = "⚠️ 新增速度超过解决速度，建议关注"
        else:
            trend_note = "✅ 解决速度超过新增，积压在减少"
        st.caption(trend_note)
    else:
        st.info("暂无趋势数据")

with col_side:
    st.markdown('<div class="section-title">🏥 健康仪表</div>', unsafe_allow_html=True)

    # Health ring + resolution pipeline side by side
    c_ring, c_pipe = st.columns([1, 1.5])

    with c_ring:
        ring_color = SUCCESS if grade == "优" else WARNING if grade == "良" else DANGER
        ring_glow = SUCCESS_GLOW if grade == "优" else WARNING_GLOW if grade == "良" else DANGER_GLOW
        st.markdown(f"""
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:8px 0;">
    <div class="health-ring glow-breathe" style="border-color:{ring_color};
        box-shadow:0 0 20px {ring_glow}44;">
        <div style="text-align:center;">
            <div style="font-size:1.8em;font-weight:800;color:{ring_color};line-height:1;">{score}</div>
            <div style="font-size:0.65em;color:{TEXT_MUTED};">分</div>
        </div>
    </div>
    <div style="font-size:1em;font-weight:700;color:{ring_color};margin-top:6px;">{grade}</div>
    <div style="font-size:0.65em;color:{TEXT_MUTED};">治理健康度</div>
</div>
""", unsafe_allow_html=True)

    with c_pipe:
        if total_i > 0:
            pipeline = [
                ("⏳ 待处理", pending, DANGER),
                ("🔄 处理中", processing, WARNING),
                ("✅ 已解决", resolved, SUCCESS),
            ]
            for label, count, color in pipeline:
                pct = count / total_i * 100 if total_i > 0 else 0
                st.markdown(f"""
<div style="margin:6px 0;">
    <div style="display:flex;justify-content:space-between;font-size:0.72em;color:{TEXT_SEC};margin-bottom:1px;">
        <span>{label}</span><span style="color:{color};">{count} · {pct:.0f}%</span>
    </div>
    <div style="height:6px;background:{SURFACE_RAISED};border-radius:3px;overflow:hidden;">
        <div style="height:100%;width:{pct}%;background:{color};border-radius:3px;
            box-shadow:0 0 6px {color}44;transition:width 0.6s ease;"></div>
    </div>
</div>
""", unsafe_allow_html=True)

    # Avg resolution speed
    st.markdown(f"""
<div style="margin-top:8px;font-size:0.72em;color:{TEXT_MUTED};text-align:center;">
    ⏱️ 平均解决周期：<strong style="color:{WARNING if avg_days > 3 else SUCCESS};">{avg_days} 天</strong>
    &nbsp;·&nbsp;
    🏃 解决速度：<strong style="color:{SUCCESS};">{health.get('speed_score', '—')} 分</strong>
</div>
""", unsafe_allow_html=True)

st.markdown(f'<div style="height:1px;background:linear-gradient(90deg,transparent,{BORDER_GLOW},transparent);margin:16px 0;"></div>', unsafe_allow_html=True)

# BOTTOM ROW: campus heatmap + recent issues

col_heat, col_recent = st.columns([1, 1])

with col_heat:
    st.markdown('<div class="section-title">🗺️ 校园问题热力分布</div>', unsafe_allow_html=True)

    by_cat = issue_stats.get("by_category", {})
    # Build intensity map data
    campus_areas = {
        "教学区": by_cat.get("教学设备", 0) + by_cat.get("网络服务", 0) // 2,
        "图书馆": by_cat.get("设施维修", 0) // 3 + by_cat.get("网络服务", 0) // 3,
        "食堂": by_cat.get("餐饮问题", 0) + by_cat.get("环境卫生", 0) // 3,
        "宿舍区": by_cat.get("设施维修", 0) // 3 + by_cat.get("网络服务", 0) // 3 + by_cat.get("安全隐患", 0) // 3,
        "运动场": by_cat.get("设施维修", 0) // 4,
        "主干道": by_cat.get("设施维修", 0) // 4 + by_cat.get("环境卫生", 0) // 3,
        "行政楼": by_cat.get("校园管理", 0),
        "校医院": by_cat.get("安全隐患", 0) // 3,
        "绿化区": by_cat.get("环境卫生", 0) // 3,
        "停车场": by_cat.get("设施维修", 0) // 4,
        "快递站": by_cat.get("校园管理", 0) // 2,
        "活动中心": by_cat.get("校园管理", 0) // 2 + by_cat.get("其他", 0),
    }
    max_heat = max(campus_areas.values()) if any(campus_areas.values()) else 1

    def heat_color(count, max_val):
        if max_val == 0: return (SURFACE_RAISED, TEXT_MUTED)
        intensity = count / max_val
        if intensity >= 0.7:
            r, g, b = 239, 68, 68  # red
            alpha = 0.35 + intensity * 0.5
        elif intensity >= 0.4:
            r, g, b = 245, 158, 11  # amber
            alpha = 0.25 + intensity * 0.4
        elif intensity > 0:
            r, g, b = 59, 130, 246  # blue
            alpha = 0.15 + intensity * 0.35
        else:
            return (SURFACE_RAISED, TEXT_MUTED)
        return (f"rgba({r},{g},{b},{alpha:.2f})", TEXT if intensity >= 0.4 else TEXT_SEC)

    heat_cells = "".join(
        f'<div class="heat-cell" style="background:{heat_color(v, max_heat)[0]};color:{heat_color(v, max_heat)[1]};">'
        f'<div style="font-size:1em;">{v}</div>'
        f'<div style="font-size:0.7em;opacity:0.7;">{k}</div></div>'
        for k, v in campus_areas.items()
    )
    st.markdown(f'<div class="heat-grid">{heat_cells}</div>', unsafe_allow_html=True)

    # Category annotation
    if by_cat:
        top_cat = max(by_cat, key=by_cat.get)
        top_count = by_cat[top_cat]
        st.markdown(f"""
<div style="font-size:0.72em;color:{TEXT_MUTED};margin-top:8px;">
    🔥 最高发：「{top_cat}」— {top_count} 件，占 {top_count/total_i*100:.0f}%
</div>
""", unsafe_allow_html=True)

with col_recent:
    st.markdown('<div class="section-title">📰 最近工单</div>', unsafe_allow_html=True)

    if recent_issues:
        for idx, issue in enumerate(recent_issues[:8]):
            s = issue.get("status", "")
            is_urgent = issue.get("urgency") == "紧急" and s != "已解决"
            icon = {"待处理": "⏳", "处理中": "🔄", "已解决": "✅"}.get(s, "📌")
            st.markdown(f"""
<div class="issue-row {"urgent" if is_urgent else ""} fade-up" style="animation-delay:{idx*0.03}s;">
    <span style="font-size:1.2em;">{icon}</span>
    <span style="flex:1;color:{TEXT};">
        <strong style="color:{DANGER if is_urgent else TEXT};">#{issue["id"]}</strong>
        {issue.get("title","")[:26]}
    </span>
    <span style="color:{TEXT_MUTED};font-size:0.85em;white-space:nowrap;">
        {issue.get("reported_at","")[:10]}
    </span>
</div>
""", unsafe_allow_html=True)

# ANOMALY ALERT BAR

if has_anomaly or urgent_count > 0:
    alerts = []
    if urgent_count > 0:
        alerts.append(f"🔴 {urgent_count} 件紧急工单需要立即处理")
    if pending > 15:
        alerts.append(f"⏳ 待处理工单积压 {pending} 件，超过警戒线")
    if health.get("avg_days", 0) and health.get("avg_days", 0) > 5:
        alerts.append(f"⏱️ 平均解决周期 {health['avg_days']} 天，效率偏低")
    alert_text = "　|　".join(alerts)
    st.markdown(f"""
<div class="pulse-anomaly" style="background:{SURFACE_RAISED};border:1px solid {DANGER}44;
    border-radius:10px;padding:10px 18px;margin-top:12px;
    display:flex;align-items:center;gap:10px;">
    <span style="font-size:1.3em;">🚨</span>
    <span style="color:{DANGER};font-weight:700;font-size:0.82em;">{alert_text}</span>
</div>
""", unsafe_allow_html=True)

# BOTTOM TICKER — scrolling activity feed

ticker_events = []
for i in recent_issues[:6]:
    s = i.get("status", "")
    emoji = {"待处理": "📝", "处理中": "🔄", "已解决": "✅"}.get(s, "")
    ticker_events.append(
        f'{emoji} #{i["id"]} {i.get("title","")[:20]} — {s} · {i.get("reported_at","")[:10]}'
    )

# Add proposal events
ticker_events += [
    "💡 提案 #8「延长图书馆开放时间」获 73 人附议",
    "✅ 工单 #118「图书馆插座不足」已解决",
    "📢 新通知「秋季学期校历」已发布",
    "🎉 提案 #3「增设快递柜」已进入实施阶段",
]
# Double up for seamless loop
ticker_events = ticker_events + ticker_events

ticker_html = "".join(
    f'<span class="ticker-item"><span class="ticker-dot"></span>{e}</span>'
    for e in ticker_events
)
st.markdown(f"""
<div class="ticker-wrap" style="margin-top:12px;">
    <div class="ticker-track">{ticker_html}</div>
</div>
""", unsafe_allow_html=True)

# FOOTER

st.markdown(f"""
<div style="text-align:center;font-size:0.65em;color:{TEXT_MUTED};margin-top:8px;">
    CampusInsight · Campus Monitor · Real-time Monitoring
    · {now.strftime("%Y-%m-%d %H:%M:%S")}
</div>
""", unsafe_allow_html=True)

refresh_sec = int(st.query_params.get("refresh", "30"))
st.markdown(f'<meta http-equiv="refresh" content="{refresh_sec}">', unsafe_allow_html=True)

