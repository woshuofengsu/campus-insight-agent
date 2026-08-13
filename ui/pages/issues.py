# ui/pages/issues.py
"""🔧 接诉即办 · 报 — 直接上报、追踪工单、看分类分布."""
import streamlit as st
import altair as alt
import pandas as pd
from data.database import get_issues, report_issue as db_report_issue
from ui.cache import cached_issues_stats as get_issues_stats, invalidate_issues
from tools.action_report_issue import _llm_classify, validate_location
from ui.components import TOKEN, section, stat, issue_card, info_card, ooda_nav, CAT_LABEL, resolve_author, configure_altair, page_header
import logging
_log = logging.getLogger(__name__)

agent = st.session_state.get("agent")
memory = st.session_state.get("memory")
if memory is not None:
    profile = memory.get_user_profile()
else:
    profile = {}

# Derive author identity from profile
_author = resolve_author(profile)

page_header("🔧 接诉即办", "发现社区诉求？一句话上报，自动分类定级。", "报")

ooda_nav("issues")

# ⚡ Quick report — native form (no chat needed)

def _do_issues_report():
    """Callback for quick report form — runs BEFORE page rerender."""
    title = st.session_state.quick_report_title.strip()
    loc = st.session_state.quick_report_location.strip()
    if not title:
        st.session_state._report_error = "请至少输入问题描述。"
        return
    # Dedup check — simple substring containment
    existing = get_issues(limit=100)
    dup = None
    title_lower = title.lower()
    for e in existing:
        e_title_lower = e.get("title", "").lower()
        # Check if one title contains the other (high recall, low FP)
        if len(title_lower) >= 4 and len(e_title_lower) >= 4:
            if title_lower in e_title_lower or e_title_lower in title_lower:
                dup = e
                break
    if dup:
        st.session_state._report_error = (
            f"⚠️ 检测到相似问题已存在：#{dup['id']}「{dup['title'][:30]}」（{dup['status']}）\n"
            f"建议先关注该工单进展，如确是新问题请修改描述后重试。"
        )
        return
    # Validate location for dorm/classroom issues
    loc_err = validate_location(title, loc)
    if loc_err:
        st.session_state._report_error = loc_err
        return
    # Auto classify (single LLM call, cached) and submit
    category, urgency = _llm_classify(title, "")
    # Anonymous reporting: public author field stores a stable pseudonym; reporter_id
    # still tracks identity for closed-loop notification.
    anonymous = st.session_state.get("quick_report_anonymous", False)
    try:
        issue_id = db_report_issue(
            title=title,
            category=category,
            location=loc,
            description="",
            urgency=urgency,
            author=_author,
            suggested_category=category,  # persist AI classification for grid-manager review
            anonymous=anonymous,
        )
        urgency_emoji = {"普通": "🔵", "紧急": "🟠", "极急": "🔴"}
        invalidate_issues()  # ensure "我的" page shows fresh data
        st.session_state._report_result = (
            f"✅ 工单 #{issue_id} 已生成！分类：{category} · 紧急程度：{urgency_emoji.get(urgency, '🔵')} {urgency}"
        )
        st.session_state._report_error = ""
        st.session_state.quick_report_title = ""
        st.session_state.quick_report_location = ""
    except Exception as e:
        _log.debug("non-critical failure", exc_info=True)
        st.session_state._report_error = f"上报失败：{e}"
        st.session_state._report_result = ""
        import traceback
        st.session_state._report_trace = traceback.format_exc()


with st.container(border=True):
    st.markdown(
        f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin-bottom:6px;">'
        f'⚡ 快速上报</div>',
        unsafe_allow_html=True,
    )
    st.text_input(
        "问题描述",
        placeholder="比如：3号楼二楼卫生间水龙头漏水、小区广场地面有个坑...",
        label_visibility="collapsed",
        key="quick_report_title",
    )
    c1, c2 = st.columns([2, 1])
    with c1:
        st.text_input(
            "📍 地点（可选）",
            placeholder="比如：3号楼二楼卫生间",
            key="quick_report_location",
        )
        st.checkbox("🙈 匿名上报（不公开我的信息）", key="quick_report_anonymous")
    with c2:
        st.button("上报", type="primary", width="stretch", key="quick_report_btn", on_click=_do_issues_report)

# Show result/error from callback (survives rerun)
if st.session_state.get("_report_error"):
    st.error(st.session_state.pop("_report_error"))
    if st.session_state.get("_report_trace"):
        st.code(st.session_state.pop("_report_trace"))
if st.session_state.get("_report_result"):
    st.success(st.session_state.pop("_report_result"))

st.markdown("---")

# Stats overview

try:
    stats = get_issues_stats()
except Exception as e:
    st.error(f"⚠️ 数据加载失败：{e}")
    st.stop()
total = stats["total"]

if total == 0:
    info_card("在上方输入框描述问题，成为第一个让社区变好的人！")
    st.stop()

by_status = stats.get("by_status", {})
pending = by_status.get("待处理", 0)
processing = by_status.get("处理中", 0)
resolved = by_status.get("已解决", 0)

c1, c2, c3, c4 = st.columns(4)
with c1:
    stat("总数", str(total), TOKEN["accent"])
with c2:
    stat("待处理", str(pending), TOKEN["warning"])
with c3:
    stat("处理中", str(processing), TOKEN["accent"])
with c4:
    stat("已解决", str(resolved), TOKEN["success"])

st.markdown("")

# Status pipeline chart

section("工单状态分布")

if by_status:
    status_order = ["待处理", "处理中", "已解决"]
    status_colors = {
        "待处理": TOKEN["danger"], "处理中": TOKEN["warning"], "已解决": TOKEN["success"],
    }
    df_status = pd.DataFrame([
        {"状态": s, "数量": by_status.get(s, 0), "颜色": status_colors.get(s, TOKEN["accent"])}
        for s in status_order if by_status.get(s, 0) > 0
    ])
    if not df_status.empty:
        chart = configure_altair(
            alt.Chart(df_status)
            .mark_bar(size=24)
            .encode(
                x=alt.X("数量:Q"),
                y=alt.Y("状态:N", title=None, sort=status_order),
                color=alt.Color("状态:N", scale=alt.Scale(
                    domain=list(status_colors.keys()),
                    range=list(status_colors.values()),
                ), legend=None),
            )
            .properties(height=100)
        )
        st.altair_chart(chart, width="stretch")

st.markdown("---")

# Category distribution

section("问题类别分布")

by_cat = stats.get("by_category", {})
if by_cat:
    df_cat = pd.DataFrame([
        {"类别": CAT_LABEL.get(k, k), "数量": v}
        for k, v in sorted(by_cat.items(), key=lambda x: -x[1])
    ])
    col_chart, col_table = st.columns([3, 2])
    with col_chart:
        chart = configure_altair(
            alt.Chart(df_cat)
            .mark_bar(color=TOKEN["warning"], opacity=0.85, size=20)
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

# All issues — filterable

section("全部工单")

# Accept cross-page filter from pulse (via session_state)
cross_filter = st.session_state.pop("_filter_category", None)

f1, f2 = st.columns(2)
with f1:
    status_filter = st.radio(
        "按状态筛选", ["全部", "待处理", "处理中", "已解决"],
        horizontal=True, key="issue_status_filter",
    )
with f2:
    cat_options = ["全部"] + sorted(set(
        i.get("category", "其他") for i in get_issues(limit=200)
    ))
    # Use cross_filter if set, otherwise default to "全部"
    default_idx = cat_options.index(cross_filter) if cross_filter in cat_options else 0
    cat_filter = st.selectbox(
        "按类别筛选", cat_options,
        index=default_idx,
        key="issue_cat_filter",
    )

all_issues = get_issues(limit=200)
if status_filter != "全部":
    all_issues = [i for i in all_issues if i.get("status") == status_filter]
if cat_filter != "全部":
    all_issues = [i for i in all_issues if i.get("category") == cat_filter]

if not all_issues:
    st.info("该状态下暂无工单。")
else:
    cols = st.columns(2)
    for idx, issue in enumerate(all_issues):
        with cols[idx % 2]:
            issue_card(issue)
