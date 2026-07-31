# ui/pages/pulse.py
"""🌊 校园脉搏 · 知 — 正在发生什么？即将发生什么？"""
import streamlit as st
import altair as alt
import pandas as pd
from ui.cache import cached_issues, cached_campus_events as get_campus_events, cached_knowledge_base as get_knowledge_base
from tools.query_weather import get_today_weather, _get_data_source_note as _weather_source_note
from ui.components import TOKEN, section, info_card, event_card, issue_card, stat, ooda_nav, CAT_LABEL, configure_altair

# ── Page header ──
st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">🌊 校园脉搏</span>'
    f'<span style="background:{TOKEN["primary"]};color:#fff;font-size:0.7em;font-weight:600;'
    f'padding:2px 8px;border-radius:99px;margin-left:8px;vertical-align:middle;">知</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption("感知校园动态，不错过任何大事小情。")

ooda_nav("pulse")

# ═══════════════════════════════════════════
# 🧠 AI 自主感知 — 后台引擎定时扫描结果
# ═══════════════════════════════════════════

try:
    from data.db_perception import get_latest_perception, get_perception_status, force_perception_scan
    perception = get_latest_perception()
    p_status = get_perception_status()

    if perception:
        mins_ago = perception.get("minutes_ago")
        if mins_ago is not None and mins_ago < 60:
            time_label = f"{mins_ago} 分钟前"
        elif mins_ago is not None:
            time_label = f"{mins_ago // 60} 小时前"
        else:
            time_label = "刚刚"

        overall = perception.get("overall_summary", "")
        anomaly_count = perception.get("anomaly_count", 0)
        findings = perception.get("key_findings", [])

        # Static status indicator
        dot_color = TOKEN["danger"] if anomaly_count > 0 else TOKEN["success"]

        # Use container(border=True) for proper DOM enclosure
        with st.container(border=True):
            # Header row
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">'
                f'<span style="font-weight:700;color:{TOKEN["text"]};">AI Perception</span>'
                f'<span style="display:inline-block;width:8px;height:8px;'
                f'background:{dot_color};border-radius:50%;margin-left:6px;" '
                f'title="perception active"></span>'
                f'<span style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_muted"]};margin-left:auto;">'
                f'{time_label}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # Summary line
            st.caption(overall)

            # Findings in expander
            if findings:
                with st.expander(f"📋 {len(findings)} 项感知发现", expanded=(anomaly_count > 0)):
                    for f_text in findings:
                        st.markdown(
                            f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
                            f'padding:3px 0;line-height:1.5;">{f_text}</div>',
                            unsafe_allow_html=True,
                        )

            # Manual refresh
            c_refresh, _ = st.columns([1, 4])
            with c_refresh:
                if st.button("🔄 立即感知", key="force_perception", width="stretch",
                             help="手动触发 AI 感知引擎扫描校园数据"):
                    with st.spinner("🧠 AI 感知引擎正在扫描校园数据..."):
                        try:
                            result = force_perception_scan()
                            if result:
                                st.toast(f"✅ 扫描完成 — {result['overall_summary']}", icon="🧠")
                            else:
                                st.toast("扫描完成", icon="✅")
                        except Exception as e:
                            st.toast(f"扫描失败: {e}", icon="❌")
                    st.rerun()
    else:
        # No perception data yet — show initial scan prompt
        st.info("🧠 AI 感知引擎就绪 · 正在初始化首次校园扫描...")

except Exception:
    pass  # Perception engine is optional — don't break the pulse page

# ═══════════════════════════════════════════
# Weather — full card (not compact)
# ═══════════════════════════════════════════

st.markdown("---")

days, location_name, is_real = get_today_weather()

if days:
    d = days[0]
    source = _weather_source_note(real=is_real)
    rain = f" 💧降水{d['rain_prob']}%" if d.get("rain_prob", 0) >= 60 else ""
    wind_str = d.get("wind", "")
    wind_show = f" 💨{wind_str}" if wind_str else ""

    col_w1, col_w2 = st.columns([1, 2])
    with col_w1:
        st.markdown(
            f'<div style="background:{TOKEN["primary_bg"]};border:1px solid {TOKEN["primary_border"]};'
            f'border-radius:{TOKEN["radius"]};padding:20px 16px;text-align:center;'
            f'box-shadow:{TOKEN["shadow"]};">'
            f'<div style="font-size:3em;margin-bottom:8px;">{d["emoji"]}</div>'
            f'<div style="font-size:1.1em;font-weight:700;color:{TOKEN["text"]};">{d["condition"]}</div>'
            f'<div style="font-size:2em;font-weight:800;color:{TOKEN["text"]};">{d["temp_high"]}°</div>'
            f'<div style="font-size:0.85em;color:{TOKEN["text_sec"]};">{d["temp_low"]}°C ~ {d["temp_high"]}°C</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    with col_w2:
        st.markdown(
            f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["slate_border"]};'
            f'border-radius:{TOKEN["radius"]};padding:16px;box-shadow:{TOKEN["shadow"]};">'
            f'<div style="font-size:0.95em;font-weight:700;color:{TOKEN["text"]};margin-bottom:8px;">📍 {location_name}</div>'
            f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};line-height:2;">'
            f'🌡️ 温度：{d["temp_low"]}°C ~ {d["temp_high"]}°C<br>'
            f'🌬️ 风力：{wind_str or "—"}<br>'
            f'🌧️ 降水概率：{d.get("rain_prob","—")}%{rain}{wind_show}<br>'
            f'{"🟢" if is_real else "🟡"} {source}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

# ═══════════════════════════════════════════
# 🏥 疾病防治 — 健康风险卡片
# ═══════════════════════════════════════════

try:
    from data.db_health_alerts import cached_health_risk
    health = cached_health_risk()
    h_level = health["overall_level"]
    h_emoji = health["overall_emoji"]
    h_color = health["overall_color"]
    h_score = health["overall_score"]

    level_label = {"low": "低风险 · 校园健康", "moderate": "注意防护", "high": "警示 · 加强预防", "critical": "高危 · 立即行动"}
    h_label = level_label.get(h_level, "—")

    bar_color = TOKEN[h_color] if h_color in ("success", "warning", "danger") else TOKEN["primary"]
    risk_bar_pct = min(100, h_score)

    # Build alert rows HTML
    alerts_html = ""
    for alert in health.get("top_alerts", [])[:2]:
        alert_emoji = alert.get("emoji", "💊")
        alerts_html += (
            f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
            f'padding:4px 0;line-height:1.5;">'
            f'{alert_emoji} <strong>{alert["title"]}</strong> — {alert["message"][:100]}'
            f'</div>'
        )

    # Weather reasons
    weather_note = ""
    if health.get("weather_mod_total", 0) >= 10:
        reasons = health.get("weather_breakdown", {})
        if reasons:
            reason_str = " · ".join(list(reasons.keys())[:2])
            weather_note = (
                f'<div style="font-size:0.72em;color:{TOKEN["text_muted"]};margin-top:6px;">'
                f'🌡️ 天气关联：{reason_str}</div>'
            )

    # ── Single HTML block — NO cross-st.markdown div spanning ──
    st.markdown("---")
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1.5px solid {bar_color};'
        f'border-radius:{TOKEN["radius"]};padding:16px 20px;box-shadow:{TOKEN["shadow"]};'
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

        # Risk bar
        f'<div style="height:6px;background:{TOKEN["slate_border"]};border-radius:3px;margin:6px 0 10px;">'
        f'<div style="width:{risk_bar_pct}%;height:100%;background:linear-gradient(90deg,'
        f'#22c55e 0%, #eab308 35%, #f97316 65%, #ef4444 100%);border-radius:3px;'
        f'transition:width 0.5s ease;"></div></div>'

        # Alerts
        f'{alerts_html}'

        # Advice
        f'<div style="font-size:0.78em;color:{TOKEN["text_muted"]};margin-top:6px;'
        f'padding:8px 12px;background:{TOKEN["primary_bg"]};border-radius:6px;">'
        f'💡 {health["advice_summary"]}</div>'

        # Weather note
        f'{weather_note}'

        f'</div>',
        unsafe_allow_html=True,
    )

except Exception:
    pass  # Health module is optional — don't break the pulse page

# ═══════════════════════════════════════════
# Upcoming events
# ═══════════════════════════════════════════

section("即将发生")

events = get_campus_events(limit=10)
if events:
    cols = st.columns(2)
    for i, e in enumerate(events):
        with cols[i % 2]:
            event_card(e)
else:
    info_card("添加校历信息后可在此查看即将发生的大事")


# ═══════════════════════════════════════════
# 📡 校园动态时间线 — 实时活动
# ═══════════════════════════════════════════

section("校园动态")

try:
    from data.db_notifications import get_activity_feed
    feed = get_activity_feed(limit=8)

    if feed:
        action_icons = {
            "上报问题": "📝", "解决问题": "✅", "开始处理": "🔄", "重新打开": "🔓",
            "提交提案": "💡", "附议提案": "👍", "回复提案": "💬",
            "采纳提案": "✅", "实施提案": "🎉",
        }
        for entry in feed[:8]:
            actor = entry.get("actor", "") or "同学"
            action = entry.get("action", "")
            icon = action_icons.get(action, "📌")
            detail = entry.get("detail", "")
            target_title = entry.get("target_title", "")
            display_title = target_title[:28] if target_title else detail[:28]
            created = (entry.get("created_at", "") or "")[:16]

            with st.container(border=True):
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(
                        f'{icon} <strong style="color:{TOKEN["text"]};">{actor}</strong> '
                        f'<span style="color:{TOKEN["text_sec"]};">{action}</span> '
                        f'· <span style="color:{TOKEN["text_muted"]};font-size:0.82em;">{display_title}</span>',
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.caption(created)
    else:
        # Fallback: show live_generator summary if no real activity yet
        try:
            from data.live_generator import get_live_summary
            summary = get_live_summary()
            if summary:
                st.info(f"📡 {summary}")
            else:
                st.caption("暂无校园动态。当同学们开始上报问题和提交提案时，这里会实时更新。")
        except Exception:
            st.caption("暂无校园动态。")
except Exception:
    pass  # activity feed is optional


# ═══════════════════════════════════════════
# 📚 校园百科 — RAG 语义搜索 + quick access
# ═══════════════════════════════════════════

section("校园百科")

# ── Semantic search bar ──
kb_search_query = st.text_input(
    "🔍 搜索校规、通知、FAQ...",
    placeholder="例如：食堂营业时间、奖学金申请条件、宿舍管理规定...",
    key="pulse_kb_search",
    label_visibility="collapsed",
)

if kb_search_query.strip():
    # ── RAG semantic search ──
    from agent.rag import semantic_search
    results = semantic_search(kb_search_query.strip(), top_k=6)
    if results:
        st.caption(f"🔎 「{kb_search_query.strip()}」— 找到 {len(results)} 条结果（语义搜索）")
        kb_icons = {"faq": "📞", "governance": "📋", "notice": "📢", "event": "📅", "calendar": "🗓️"}
        for r in results:
            icon = kb_icons.get(r.get("category", ""), "📌")
            score_pct = min(int(r.get("score", 0) * 100), 99)
            with st.container(border=True):
                c1, c2 = st.columns([20, 1])
                with c1:
                    st.markdown(
                        f'**{icon} {r["title"]}** '
                        f'`{r.get("category", "")}` · 相关度 {score_pct}%',
                    )
                    st.markdown(
                        f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};">'
                        f'{r["content"][:200]}{"..." if len(r.get("content","")) > 200 else ""}'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown("")  # spacer
    else:
        st.info(f"🔍 未找到与「{kb_search_query.strip()}」相关的百科信息。试试换个说法？")
else:
    # ── Default: browse recent entries ──
    kb_entries = get_knowledge_base(limit=10)
    if kb_entries:
        kb_icons = {"faq": "📞", "governance": "📋", "notice": "📢", "event": "📅", "calendar": "🗓️"}
        kb_cols = st.columns(3)
        for i, entry in enumerate(kb_entries):
            icon = kb_icons.get(entry.get("category", ""), "📌")
            with kb_cols[i % 3]:
                with st.container(border=True):
                    st.markdown(
                        f'<div style="font-size:0.85em;font-weight:700;color:{TOKEN["text"]};">'
                        f'{icon} {entry.get("title","")[:25]}</div>',
                        unsafe_allow_html=True,
                    )
                    content = entry.get("content", "")
                    st.markdown(
                        f'<div style="font-size:0.76em;color:{TOKEN["text_sec"]};line-height:1.4;">'
                        f'{content[:90]}{"..." if len(content) > 90 else ""}</div>',
                        unsafe_allow_html=True,
                    )
    else:
        info_card("添加校历、通知、常用电话等信息后展示")


# ═══════════════════════════════════════════
# Weekly hot spots
# ═══════════════════════════════════════════

section("本周热点")

issues = cached_issues(limit=100)
if issues:
    total = len(issues)
    pending = len([i for i in issues if i.get("status") == "待处理"])
    resolved = len([i for i in issues if i.get("status") == "已解决"])
    processing = len([i for i in issues if i.get("status") == "处理中"])

    # KPI row (2×2 grid: stacks to 4 rows on mobile)
    c1, c2 = st.columns(2)
    with c1:
        stat("总上报", str(total), TOKEN["primary"])
    with c2:
        stat("待处理", str(pending), TOKEN["warning"])
    c3, c4 = st.columns(2)
    with c3:
        stat("处理中", str(processing), TOKEN["primary"])
    with c4:
        stat("已解决", str(resolved), TOKEN["success"])

    st.markdown("")

    # ── 🧠 AI 智能洞察（Agent 主动发现）──
    try:
        from agent.reflector import get_proactive_insights as _get_insights
        _insights = _get_insights()
        if _insights.get("has_insight"):
            with st.container(border=True):
                st.markdown(
                    f'<span style="font-size:0.9em;font-weight:700;color:{TOKEN["text"]};">'
                    f'🧠 AI 智能洞察</span>'
                    f'<span style="font-size:0.68em;color:{TOKEN["text_muted"]};margin-left:6px;">'
                    f'Agent 自动发现</span>',
                    unsafe_allow_html=True,
                )
                for part in _insights.get("summary_parts", [])[:3]:
                    st.markdown(
                        f'<span style="font-size:0.82em;color:{TOKEN["text"]};">{part}</span>',
                        unsafe_allow_html=True,
                    )
                from datetime import datetime
                st.caption(f'🕐 {datetime.now().strftime("%H:%M")} · AI Agent 自动分析')
    except ImportError:
        pass
    except Exception:  # non-critical: silent pass intended
        pass

    # Category hotness
    cats: dict[str, int] = {}
    for i in issues:
        cat = i.get("category", "其他")
        cats[cat] = cats.get(cat, 0) + 1

    if cats:
        df = pd.DataFrame([
            {"类别": CAT_LABEL.get(k, k), "数量": v}
            for k, v in sorted(cats.items(), key=lambda x: -x[1])
        ])
        chart = configure_altair(
            alt.Chart(df)
            .mark_bar(color=TOKEN["primary"], opacity=0.85, size=20)
            .encode(
                x=alt.X("数量:Q"),
                y=alt.Y("类别:N", title=None, sort="-x"),
            )
            .properties(height=180)
        )
        st.altair_chart(chart, width="stretch")

    # Hot category highlight — clickable to filter issues page
    hot_cat = max(cats, key=cats.get)
    c_hot, c_btn = st.columns([3, 1])
    with c_hot:
        st.markdown(
            f'<div style="background:{TOKEN["warning_bg"]};border:1px solid {TOKEN["warning_border"]};'
            f'border-radius:{TOKEN["radius_sm"]};padding:10px 14px;margin-top:8px;">'
            f'🔥 本周最热：<strong style="color:{TOKEN["warning"]};">{hot_cat}</strong> — '
            f'共 {cats[hot_cat]} 件上报，占总数的 {cats[hot_cat]/total*100:.0f}%</div>',
            unsafe_allow_html=True,
        )
    with c_btn:
        st.markdown("")  # spacer
        if st.button("🔍 查看详情 →", key="pulse_goto_issues"):
            st.session_state._filter_category = hot_cat
            st.switch_page("ui/pages/issues.py")
