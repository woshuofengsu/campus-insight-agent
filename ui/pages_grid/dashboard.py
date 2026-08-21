"""📊 工作台 — 网格员端首页：KPI、紧急工单、趋势、热门提案."""
import logging
from datetime import datetime
import streamlit as st
from ui.guard import require_role

require_role("grid")

_log = logging.getLogger(__name__)
import altair as alt
import pandas as pd
from ui.components import TOKEN, tag, stat, section, configure_altair, methodology_panel
from ui.cache import (
    cached_issues, cached_issues_stats, cached_issues_timeline,
    cached_proposals, cached_proposals_stats, cached_health_score,
    invalidate_issues, invalidate_proposals,
)
from data.database import update_issue_status, update_proposal_status, get_db, get_satisfaction_stats, get_dissatisfaction_reasons
from data.db_sla import get_sla_breaches, get_sla_summary, get_escalated_issues


def _now_short() -> str:
    now = datetime.now()
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{now.year}年{now.month}月{now.day}日 {weekdays[now.weekday()]}"


# 页面渲染
memory = st.session_state.get("memory")
if memory is not None:
    profile = memory.get_user_profile()
else:
    profile = {}
community = profile.get("community", "小区")
dept = profile.get("building", "")       # 网格员端：部门存在 building 字段里
display_name = profile.get("name", "") or profile.get("unit", "")

# 天气小部件
weather_html = ""
try:
    from tools.query_weather import get_today_weather
    days, loc, _ = get_today_weather()
    if days:
        d = days[0]
        weather_html = (
            f'<span style="font-size:0.78em;color:{TOKEN["text_sec"]};margin-left:12px;">'
            f'{d["emoji"]} {d["condition"]} {d["temp_low"]}~{d["temp_high"]}°C '
            f'💧{d["rain_prob"]}%</span>'
        )
except Exception:  # 记日志跳过
    _log.debug("拉取天气失败", exc_info=True)

st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:{TOKEN["font_display"]};font-weight:{TOKEN["weight_bold"]};color:{TOKEN["text"]};">'
    f'{community} &middot; 工作台</span>'
    f'<span style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_muted"]};margin-left:12px;">'
    f'{_now_short()}</span>'
    f'{weather_html}'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption(f"欢迎回来，{display_name or dept or '网格员'}。")
st.markdown(f'<div style="height:1px;background:{TOKEN["border"]};margin:8px 0 16px;"></div>', unsafe_allow_html=True)

# 今日待办：先让网格员看到要做什么，而不是发生了什么
_sla_todo = get_sla_summary()
_todo_urgent = cached_issues(urgency="紧急", status=None, limit=100)
_todo_pending_props = sum(1 for p in cached_proposals(sort_by="supporters", limit=200)
                          if p.get("status") in ("讨论中", "已回应"))
_todo_total = len(_todo_urgent) + _sla_todo["total_overdue"] + _todo_pending_props

with st.container(border=True):
    st.markdown(
        f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin-bottom:8px;">'
        f'🎯 今日待办</div>',
        unsafe_allow_html=True,
    )
    if _todo_total == 0:
        st.caption("✅ 今日没有待办，社区运转平稳。")
    else:
        tc1, tc2, tc3 = st.columns(3)
        with tc1:
            st.metric("🔴 紧急工单", f"{len(_todo_urgent)} 件")
        with tc2:
            st.metric("⏰ 超时工单", f"{_sla_todo['total_overdue']} 件")
        with tc3:
            st.metric("💬 待回应提案", f"{_todo_pending_props} 件")
        st.caption("请优先处理上述事项 → 前往「工单管理」/「提案管理」")

st.markdown(f'<div style="height:1px;background:{TOKEN["border"]};margin:12px 0 16px;"></div>', unsafe_allow_html=True)

# KPI 行
stats = cached_issues_stats()
p_stats = cached_proposals_stats()
health = cached_health_score()
urgent_issues = cached_issues(urgency="紧急", status=None, limit=100)
pending_count = stats["by_status"].get("待处理", 0)
in_progress_count = stats["by_status"].get("处理中", 0)
resolved_count = stats["by_status"].get("已解决", 0)
today_new = stats.get("today_new", 0)

# KPI 条：3 列嵌套，手机上堆成 3 行
grade = health.get("grade", "-")
c1, c2, c3 = st.columns(3)
with c1:
    stat("待处理", str(pending_count), TOKEN["warning"])
    stat("今日新增", str(today_new), TOKEN["accent"])
with c2:
    stat("紧急", str(len(urgent_issues)), TOKEN["danger"])
    stat("处理中", str(in_progress_count), TOKEN["accent"])
with c3:
    stat("健康度", f'{health.get("score", "-")} {grade}',
         TOKEN["success"] if grade == "优" else TOKEN["warning"] if grade == "良" else TOKEN["danger"])
    _sat = get_satisfaction_stats()
    stat("满意率", f'{_sat["rate"]}%' if _sat["rate"] is not None else "—",
         TOKEN["success"] if (_sat["rate"] or 0) >= 80 else TOKEN["warning"])

st.markdown(f'<div style="height:1px;background:{TOKEN["border"]};margin:12px 0 16px;"></div>', unsafe_allow_html=True)

# 不满意反馈透传
_diss = get_dissatisfaction_reasons(limit=5)
if _diss:
    with st.expander(f"😞 不满意反馈（{len(_diss)} 条）"):
        for _d in _diss:
            _reason = _d.get("satisfaction_reason", "")
            st.markdown(
                f"· #{_d['id']}「{(_d.get('title') or '')[:30]}」"
                + (f" — {_reason}" if _reason else " —（未填写原因）")
            )

# 老年关怀：SOS 求助 + 重点关注老人
try:
    from data.db_elderly import get_pending_sos, mark_sos_done, get_elderly_overview
    _sos = get_pending_sos()
    _elders = get_elderly_overview()
    if _sos or _elders:
        st.markdown("---")
        section("👴 老年关怀")
        # SOS（最紧急置顶）
        for _s in _sos:
            st.markdown(f"🚨 **SOS 紧急求助：{_s.get('name','')}**（{( _s.get('created_at') or '')[:16]}）")
            if st.button(f"✅ 已处理 SOS #{_s['id']}", key=f"sos_done_{_s['id']}", width="stretch"):
                mark_sos_done(_s["id"])
                st.rerun()
        # 老人档案：最近活跃 + 血压 + 用药依从
        for _e in _elders:
            _name = _e.get("name") or "老人"
            if _e.get("is_living_alone"):
                _name += "（独居）"
            _last = (_e.get("last_active_at") or "")[:16] or "从未互动"
            _bp = _e.get("latest_bp")
            _bp_txt = f"{_bp.get('sys')}/{_bp.get('dia')} mmHg（{_bp.get('date','')}）" if _bp else "未记录"
            _adh = _e.get("adherence", [])
            _adh_txt = f"近7天确认 {len(_adh)} 次" if _adh else "近7天无确认"
            with st.container(border=True):
                st.markdown(
                    f"<strong>{_name}</strong> · ⏱ 活跃：{_last}",
                    unsafe_allow_html=True,
                )
                st.caption(f"🩺 最近血压 {_bp_txt} · 💊 {_adh_txt}")
except Exception:
    _log.debug("养老关怀模块不可用", exc_info=True)

# 紧急工单（可直接操作）
section("⚠️ 需要立即处理")

if not urgent_issues:
    st.info("🎉 暂无紧急工单，社区运转良好！")
else:
    for issue in urgent_issues[:10]:
        iid = issue["id"]
        title = (issue.get("title") or "")[:40]
        cat = issue.get("category", "")
        loc = issue.get("location", "")
        desc = issue.get("description", "")
        reported = (issue.get("reported_at") or "")[:10]
        author = issue.get("author", "")
        status = issue.get("status", "")

        with st.container(border=True):
            c_left, c_right = st.columns([4, 2])
            with c_left:
                st.markdown(
                    f'<span style="font-size:0.95em;font-weight:600;color:{TOKEN["text"]};">'
                    f'🔴 #{iid} {title}</span>'
                    f'&nbsp;{tag(status)}',
                    unsafe_allow_html=True,
                )
                detail = f'{cat} · {reported}'
                if loc:
                    detail += f' · 📍 {loc}'
                if author:
                    detail += f' · 👤 {author}'
                st.caption(detail)
                if desc:
                    with st.expander("📄 详情"):
                        st.write(desc)
            with c_right:
                st.markdown("<div style='margin-top:4px;'></div>", unsafe_allow_html=True)
                # 快捷处理备注
                quick_note_key = f"_urgent_note_{iid}"
                st.text_input("备注", key=quick_note_key, placeholder="可选备注…", label_visibility="collapsed")
                # 报修状态机工单：dashboard 不做快捷操作（防破坏状态机，R73），引导去工单管理
                _REPAIR_STATUSES = {
                    "待审核", "退回补充信息", "已审核待派单", "已派单", "处理中",
                    "待居民反馈", "已撤回", "已关闭", "待协商", "已转出",
                }
                if status in _REPAIR_STATUSES:
                    st.caption("报修工单，按报修流程处理（审核→派单→处理→反馈）。")
                    if st.button("去工单管理处理", key=f"urgent_goto_{iid}", width="stretch"):
                        st.switch_page("ui/pages_grid/issues_mgmt.py")
                elif status == "待处理":
                    btn_cols = st.columns(2)
                    with btn_cols[0]:
                        if st.button("🔄 处理中", key=f"urgent_progress_{iid}", width="stretch"):
                            update_issue_status(iid, "处理中",
                                              processing_note=st.session_state.get(quick_note_key, ""))
                            invalidate_issues()
                            st.rerun()
                    with btn_cols[1]:
                        if st.button("✅ 已解决", key=f"urgent_resolve_{iid}", width="stretch"):
                            update_issue_status(iid, "已解决",
                                              processing_note=st.session_state.get(quick_note_key, ""))
                            invalidate_issues()
                            st.rerun()
                elif status == "处理中":
                    btn_cols = st.columns(2)
                    with btn_cols[0]:
                        if st.button("✅ 已解决", key=f"urgent_resolve_{iid}", width="stretch"):
                            update_issue_status(iid, "已解决",
                                              processing_note=st.session_state.get(quick_note_key, ""))
                            invalidate_issues()
                            st.rerun()
                    with btn_cols[1]:
                        if st.button("↩️ 退回", key=f"urgent_return_{iid}", width="stretch"):
                            update_issue_status(iid, "待处理",
                                              processing_note=st.session_state.get(quick_note_key, ""))
                            invalidate_issues()
                            st.rerun()
                else:  # 已解决
                    proc_note = issue.get("processing_note", "")
                    st.markdown(
                        f'<span style="font-size:0.78em;color:{TOKEN["success"]};font-weight:600;">'
                        f'✅ 已于 {(issue.get("resolved_at") or "")[:10]} 解决</span>',
                        unsafe_allow_html=True,
                    )
                    if proc_note:
                        st.caption(f"📝 {proc_note[:30]}")
                    if st.button("🔄 重开", key=f"urgent_reopen_{iid}", width="stretch"):
                        update_issue_status(iid, "待处理")
                        invalidate_issues()
                        st.rerun()

# SLA 超时预警：按紧急度分级时限，不是一刀切 7 天
overdue_issues = get_sla_breaches(limit=8)

if overdue_issues:
    section("⏰ SLA 超时预警")
    st.caption("以下工单已超过办理时限（极急 6h / 紧急 24h / 普通 72h），请优先处理。")

    for oi in overdue_issues[:5]:
        oi_id = oi["id"]
        oi_title = (oi.get("title") or "")[:35]
        oi_cat = oi.get("category", "")
        oi_loc = oi.get("location", "")
        oi_hours = oi.get("hours_open", 0)
        oi_urg = oi.get("urgency", "")
        oi_reported = (oi.get("reported_at") or "")[:10]

        level = "🔴" if oi.get("level") == "critical" else "🟠"
        time_str = f"{oi_hours // 24} 天" if oi_hours >= 24 else f"{oi_hours} 小时"
        with st.container(border=True):
            c1, c2 = st.columns([4, 1.5])
            with c1:
                st.markdown(
                    f'{level} <strong>#{oi_id} {oi_title}</strong>&nbsp;{tag(oi_urg)}',
                    unsafe_allow_html=True,
                )
                st.caption(f'{oi_cat} · 📍 {oi_loc} · 🕐 {oi_reported}')
            with c2:
                st.markdown(
                    f'<span style="font-size:1.3em;font-weight:800;color:{TOKEN["danger"]};">'
                    f'{time_str}</span> 未处理',
                    unsafe_allow_html=True,
                )
                sla_note_key = f"_sla_note_{oi_id}"
                st.text_input("备注", key=sla_note_key, placeholder="可选…", label_visibility="collapsed")
                if st.button("🔄 处理", key=f"sla_progress_{oi_id}", width="stretch"):
                    update_issue_status(oi_id, "处理中",
                                      processing_note=st.session_state.get(sla_note_key, ""))
                    invalidate_issues()
                    st.rerun()

# SLA 升级工单：超时两倍自动升级
escalated_issues = get_escalated_issues(limit=5)
if escalated_issues:
    st.markdown("---")
    section("⏫ SLA 升级工单")
    st.caption("以下工单超时已达 2 倍时限（极急 12h / 紧急 48h / 普通 144h），已标记升级并尝试邮件通知。")
    for ei in escalated_issues:
        st.markdown(
            f"🔴 **#{ei['id']} {(ei.get('title') or '')[:30]}** · {ei.get('category', '')} "
            f"· 👷 {ei.get('assignee') or '未指派'} · 已超时 {ei.get('hours_open', 0)} 小时",
        )

st.markdown("---")

# 关联洞察：系统主动发现
try:
    from agent.reflector import get_proactive_insights as _get_insights
    _insights = _get_insights()
    if _insights.get("has_insight"):
        with st.container(border=True):
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
                f'<span style="background:{TOKEN["brand_gradient"]};color:#ffffff;'
                f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
                f'padding:2px 10px;border-radius:{TOKEN["radius_full"]};">🤖 AI 主动发现</span>'
                f'<span style="font-size:0.95em;font-weight:700;color:{TOKEN["text"]};">🧠 智能洞察</span>'
                f'<span style="font-size:0.75em;color:{TOKEN["text_muted"]};margin-left:auto;">'
                f'系统自动分析 · 实时更新</span></div>',
                unsafe_allow_html=True,
            )
            # 异常告警
            for za in _insights.get("z_anomalies", [])[:2]:
                level_icon = {"critical": "🔴", "high": "🟠", "moderate": "🟡"}.get(za.get("level", ""), "⚪")
                st.markdown(
                    f'{level_icon} **{za["category"]}** 类异常 · 严重度 {za["severity"]}/10 '
                    f'· 本周 {za["recent"]} 件'
                    + (f' · 紧急 {za["urgent_pending"]} 件' if za.get("urgent_pending") else ''),
                )
            # 跨周趋势
            ct = _insights.get("cross_time", {})
            if ct:
                trend_icon = "⚠️" if ct.get("is_worsening") else "✅" if ct.get("is_improving") else "📊"
                st.markdown(
                    f'{trend_icon} 本周新增 {ct.get("new_this_week", 0)} 件 '
                    f'({ct.get("new_trend", "→")}) · '
                    f'解决 {ct.get("resolved_this_week", 0)} 件 '
                    f'({ct.get("resolved_trend", "→")})'
                )
            # 升级建议
            for u in _insights.get("uncovered_upgrades", [])[:2]:
                st.markdown(
                    f'🚀 **{u["category"]}** 类 {u["issue_count"]} 件待处理，建议发起治理提案'
                )
            st.caption(f'🕐 基于 {datetime.now().strftime("%H:%M")} 数据 · 由系统自动生成')
except ImportError:
    _log.warning("Reflector 模块没装，主动洞察出不来", exc_info=True)
except Exception:
    _log.warning("加载主动洞察失败", exc_info=True)

# 健康风险概览（公共组件，精简版）
try:
    from data.db_health_alerts import cached_health_risk as _cached_health
    from ui.health_card import render_health_risk_overview
    _h = _cached_health()
    render_health_risk_overview(_h)
except Exception:
    _log.warning("健康风险模块不可用", exc_info=True)

st.markdown("---")

# 社区感知：后台引擎跑出来的结果
try:
    from data.db_perception import get_latest_perception, get_perception_status
    perception = get_latest_perception()
    if perception:
        mins_ago = perception.get("minutes_ago")
        if mins_ago is not None and mins_ago < 60:
            time_label = f"{mins_ago} 分钟前"
        elif mins_ago is not None:
            time_label = f"{mins_ago // 60} 小时前"
        else:
            time_label = "刚刚"

        anomaly_count = perception.get("anomaly_count", 0)
        overall = perception.get("overall_summary", "")
        findings = perception.get("key_findings", [])[:3]

        alert_color = TOKEN["danger"] if anomaly_count > 0 else TOKEN["success"]
        alert_icon = "🚨" if anomaly_count > 0 else "✅"

        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(
                    f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
                    f'<span style="background:{TOKEN["brand_gradient"]};color:#ffffff;'
                    f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
                    f'padding:2px 10px;border-radius:{TOKEN["radius_full"]};">🛰️ 后台自动扫描</span>'
                    f'<span style="font-size:0.95em;font-weight:700;color:{TOKEN["text"]};">🧠 社区感知</span>'
                    f'<span style="font-size:0.75em;color:{TOKEN["text_muted"]};">{time_label} 自动扫描</span>'
                    f'<span style="font-size:0.85em;color:{alert_color};margin-left:auto;font-weight:600;">'
                    f'{alert_icon} {overall[:50]}</span></div>',
                    unsafe_allow_html=True,
                )
                if findings:
                    for f_text in findings:
                        st.markdown(
                            f'<span style="font-size:0.76em;color:{TOKEN["text_sec"]};">{f_text}</span>',
                            unsafe_allow_html=True,
                        )
            with c2:
                st.markdown("")
                if anomaly_count > 0:
                    st.markdown(
                        f'<div style="text-align:center;padding-top:8px;">'
                        f'<div style="font-size:2em;">{alert_icon}</div>'
                        f'<div style="font-size:1.4em;font-weight:800;color:{alert_color};">{anomaly_count}</div>'
                        f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};">项异常</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="text-align:center;padding-top:8px;">'
                        f'<div style="font-size:2em;">🌿</div>'
                        f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};">一切正常</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
except Exception:
    _log.warning("感知引擎不可用", exc_info=True)

st.markdown("---")

# 最近已解决（让人看到成果）
section("✅ 最近已解决")
recently_resolved = cached_issues(status="已解决", limit=8)
if not recently_resolved:
    st.caption("暂无已解决的工单。")
else:
    # 已解决卡片紧凑横排
    for ri in recently_resolved[:6]:
        ri_id = ri["id"]
        ri_title = (ri.get("title") or "")[:30]
        ri_cat = ri.get("category", "")
        ri_resolved = (ri.get("resolved_at") or "")[:10]
        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(
                    f'🟢 <strong>#{ri_id} {ri_title}</strong>',
                    unsafe_allow_html=True,
                )
                st.caption(f'{ri_cat} · 解决于 {ri_resolved}')
            with c2:
                if st.button("🔄 重开", key=f"dash_reopen_resolved_{ri_id}", width="stretch"):
                    update_issue_status(ri_id, "待处理")
                    invalidate_issues()
                    st.rerun()

st.markdown("---")

# 近 7 天趋势图
section("📈 最近7天趋势")
timeline = cached_issues_timeline(days=7)
if timeline:
    df = pd.DataFrame(timeline)
    df_melt = df.melt(id_vars=["day"], value_vars=["new_count", "resolved_count"],
                       var_name="类型", value_name="数量")
    df_melt["类型"] = df_melt["类型"].map({"new_count": "新增", "resolved_count": "已解决"})
    color_map = {"新增": TOKEN["accent"], "已解决": TOKEN["success"]}

    chart = configure_altair(
        alt.Chart(df_melt)
        .mark_line(point=True)
        .encode(
            x=alt.X("day:N", title=None, axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("数量:Q", title=None, scale=alt.Scale(domainMin=0)),
            color=alt.Color("类型:N", scale=alt.Scale(
                domain=list(color_map.keys()),
                range=list(color_map.values()),
            )),
            tooltip=["day", "类型", "数量"],
        )
        .properties(height=180)
    )
    st.altair_chart(chart, width="stretch")
else:
    st.caption("暂无足够数据生成趋势图。")

st.markdown("---")

# 动态时间线（真实 activity_log）
section("📡 社区动态时间线")

try:
    from data.db_notifications import get_activity_feed, get_activity_summary
    act_summary = get_activity_summary()
    feed = get_activity_feed(limit=12)

    if act_summary.get("today_issues") or act_summary.get("today_resolved") or act_summary.get("today_proposals"):
        ev_cols = st.columns(3)
        with ev_cols[0]:
            st.metric("📝 今日上报", f'{act_summary["today_issues"]} 件')
        with ev_cols[1]:
            st.metric("✅ 今日解决", f'{act_summary["today_resolved"]} 件')
        with ev_cols[2]:
            st.metric("💡 今日提案", f'{act_summary["today_proposals"]} 件')

    if feed:
        # 精简动态流
        action_icons = {
            "上报问题": "📝", "解决问题": "✅", "开始处理": "🔄", "重新打开": "🔓",
            "提交提案": "💡", "附议提案": "👍", "回复提案": "💬",
            "采纳提案": "✅", "实施提案": "🎉",
        }
        for entry in feed[:10]:
            actor = entry.get("actor", "") or "系统"
            action = entry.get("action", "")
            icon = action_icons.get(action, "📌")
            detail = entry.get("detail", "")
            created = (entry.get("created_at", "") or "")[:16]

            st.markdown(
                f'<div style="font-size:0.78em;color:{TOKEN["text_sec"]};'
                f'padding:3px 0;display:flex;align-items:baseline;gap:6px;">'
                f'<span>{icon}</span>'
                f'<span style="font-weight:600;color:{TOKEN["text"]};">{actor}</span>'
                f'<span>{action}</span>'
                f'<span style="color:{TOKEN["text_muted"]};">{detail[:30]}</span>'
                f'<span style="color:{TOKEN["text_muted"]};font-size:0.9em;margin-left:auto;">{created}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

        # 动态为空就退回 live_generator 生成
        if len(feed) == 0:
            try:
                from data.live_generator import generate_today_events
                live_events = generate_today_events()
                if live_events.get("new_issues") or live_events.get("resolved_issues"):
                    st.caption("📡 系统感知（暂无用户活动数据）："
                               + f'新增 {live_events.get("new_issues", 0)} 件'
                               + f' · 解决 {live_events.get("resolved_issues", 0)} 件')
            except Exception:
                _log.warning("live generator 事件拿不到", exc_info=True)
    else:
        st.caption("暂无社区动态。当居民上报问题或提交提案时，这里会实时更新。")
except Exception:  # 记日志跳过
    _log.debug("动态流跳过了", exc_info=True)

# 热门提案
section("💡 热门提案 TOP 5")
proposals = cached_proposals(sort_by="supporters", limit=5)
if not proposals:
    st.info("暂无提案。")
else:
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, prop in enumerate(proposals):
        pid = prop["id"]
        ptitle = (prop.get("title") or "")[:35]
        supporters = prop.get("supporter_count", 0)
        pstatus = prop.get("status", "讨论中")
        pcat = prop.get("category", "")
        response = prop.get("response_text", "")

        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(
                    f'{medals[i] if i < len(medals) else "📌"} '
                    f'<strong>{ptitle}</strong>&nbsp;{tag(pstatus)}',
                    unsafe_allow_html=True,
                )
                st.caption(f'{pcat} · 👍 {supporters} 人附议')
                if response:
                    st.markdown(
                        f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
                        f'background:{TOKEN["success_bg"]};padding:6px 10px;border-radius:6px;'
                        f'margin-top:4px;">💬 回复：{response[:120]}</div>',
                        unsafe_allow_html=True,
                    )
            with c2:
                if pstatus == "讨论中":
                    if st.button("💬 回复", key=f"dash_reply_{pid}", width="stretch"):
                        st.session_state._dash_reply_pid = pid
                        st.rerun()
                elif pstatus == "已回应":
                    if st.button("✅ 采纳", key=f"dash_adopt_{pid}", width="stretch"):
                        update_proposal_status(pid, "已采纳")
                        invalidate_proposals()
                        st.rerun()
                elif pstatus == "已采纳":
                    if st.button("🎉 实施", key=f"dash_implement_{pid}", width="stretch"):
                        update_proposal_status(pid, "已实施")
                        invalidate_proposals()
                        st.rerun()

# 回复提案的输入区
if st.session_state.get("_dash_reply_pid"):
    pid = st.session_state["_dash_reply_pid"]
    st.markdown("---")
    st.markdown("### ✏️ 回复提案")
    reply_text = st.text_area("回复内容", placeholder="输入你对这个提案的回复...", key="dash_reply_text")
    c_btn1, c_btn2 = st.columns(2)
    with c_btn1:
        if st.button("📤 提交回复", type="primary", width="stretch"):
            if reply_text.strip():
                update_proposal_status(pid, "已回应", reply_text.strip())
                invalidate_proposals()
                st.session_state.pop("_dash_reply_pid", None)
                st.session_state.pop("dash_reply_text", None)
                st.rerun()
            else:
                st.warning("请输入回复内容")
    with c_btn2:
        if st.button("取消", width="stretch"):
            st.session_state.pop("_dash_reply_pid", None)
            st.rerun()

methodology_panel()
