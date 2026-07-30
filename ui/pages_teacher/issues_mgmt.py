# ui/pages_teacher/issues_mgmt.py
"""📋 工单管理 — 表格视图、筛选、批量操作."""
import csv
import io
from datetime import datetime
import streamlit as st
from ui.components import TOKEN, tag
from ui.cache import cached_issues, cached_issues_stats, invalidate_issues
from data.database import update_issue_status

# ── Page Render ──
st.markdown(
    f'<span style="font-size:1.2em;font-weight:800;color:{TOKEN["text"]};">'
    f'📋 工单管理</span>',
    unsafe_allow_html=True,
)
st.caption("查看、筛选、处理所有校园问题上报。")

# ── Status filter ──
status_choice = st.radio(
    "状态筛选",
    ["全部", "⏳ 待处理", "🔄 处理中", "✅ 已解决"],
    horizontal=True,
    label_visibility="collapsed",
    key="_issues_status_filter",
)
_STATUS_MAP = {"全部": None, "⏳ 待处理": "待处理", "🔄 处理中": "处理中", "✅ 已解决": "已解决"}
status_val = _STATUS_MAP.get(status_choice)

# ── Filters row ──
c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
with c1:
    cat_choice = st.selectbox(
        "分类",
        ["全部", "设施维修", "环境卫生", "安全隐患", "教学设备", "网络服务", "餐饮问题", "校园管理", "其他"],
        key="_issues_cat_filter",
        label_visibility="collapsed",
    )
with c2:
    search = st.text_input("搜索标题", placeholder="输入关键词...", key="_issues_search", label_visibility="collapsed")
with c3:
    urgency_choice = st.selectbox(
        "紧急度",
        ["全部", "紧急", "普通"],
        key="_issues_urgency_filter",
        label_visibility="collapsed",
    )
with c4:
    batch_mode = st.toggle("🔲 批量", key="_issues_batch_mode")

# ── Fetch data ──
cat_val = None if cat_choice == "全部" else cat_choice
urgency_val = None if urgency_choice == "全部" else urgency_choice

issues = cached_issues(category=cat_val, status=status_val, urgency=urgency_val, limit=200)

if search:
    issues = [i for i in issues if search.lower() in (i.get("title") or "").lower()]

# ── Sort: urgent first, then by status priority (待处理 > 处理中 > 已解决), then newest first ──
_STATUS_PRIORITY = {"待处理": 0, "处理中": 1, "已解决": 2}
issues.sort(key=lambda x: (
    0 if x.get("urgency") == "紧急" else 1,
    _STATUS_PRIORITY.get(x.get("status", ""), 99),
    -(x.get("id") or 0),
))

# ── Stats bar ──
stats = cached_issues_stats()
pending_c = stats["by_status"].get("待处理", 0)
progress_c = stats["by_status"].get("处理中", 0)
resolved_c = stats["by_status"].get("已解决", 0)
c_stats, c_export = st.columns([5, 1])
with c_stats:
    st.caption(
        f'共 {len(issues)} 条 · '
        f'⏳ 待处理 {pending_c} · 🔄 处理中 {progress_c} · ✅ 已解决 {resolved_c}'
    )
with c_export:
    if issues:
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["ID", "标题", "分类", "位置", "状态", "紧急度", "上报人", "上报时间", "解决时间", "问题描述"])
        for i in issues:
            writer.writerow([
                i.get("id"), i.get("title"), i.get("category"), i.get("location"),
                i.get("status"), i.get("urgency"), i.get("author"),
                i.get("reported_at", "")[:10], (i.get("resolved_at") or "")[:10],
                i.get("description", ""),
            ])
        st.download_button(
            "📥 导出CSV",
            csv_buffer.getvalue(),
            file_name=f"工单导出_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            width="stretch",
        )

# ── Quick Response Templates ──
with st.expander("📋 常用回复模板", expanded=False):
    templates = {
        "已派维修": "已通知后勤维修组前往处理，预计24小时内完成。",
        "配件待购": "配件已采购，预计3-5天内到货后立即更换。",
        "已列入计划": "问题已确认，已列入下周维修计划。",
        "已修复": "已安排维修人员处理完毕，请同学核实。",
        "转交部门": "该问题已转交相关管理部门处理，请耐心等待。",
        "需要进一步核实": "已收到反馈，需要进一步现场核实后再做处理。",
    }
    tcols = st.columns(3)
    for i, (label, text) in enumerate(templates.items()):
        with tcols[i % 3]:
            if st.button(f"📝 {label}", key=f"tpl_{label}", width="stretch",
                         help=f"点击选用：{text}"):
                st.session_state["_quick_tpl"] = text
                st.session_state["_quick_tpl_label"] = label

    # Show selected template in a copyable area
    if st.session_state.get("_quick_tpl"):
        selected_label = st.session_state.get("_quick_tpl_label", "")
        selected_text = st.session_state["_quick_tpl"]
        st.markdown("---")
        st.markdown(f"**📋 已选模板：{selected_label}**")
        st.code(selected_text, language=None)
        st.caption("👆 点击右上角复制图标复制模板文本，可用于工单处理备注。")
        if st.button("❌ 清除模板", key="_clear_tpl"):
            st.session_state.pop("_quick_tpl", None)
            st.session_state.pop("_quick_tpl_label", None)

st.markdown("---")

# ── Actions handler ──
def _set_status(iid: int, new_status: str):
    update_issue_status(iid, new_status)
    invalidate_issues()


def _batch_set_status(selected_ids: list[int], new_status: str):
    """Bulk update status for selected issues."""
    count = 0
    for iid in selected_ids:
        update_issue_status(iid, new_status)
        count += 1
    invalidate_issues()
    return count


# ── Batch action bar ──
if batch_mode and issues:
    # Gather selected checkboxes
    selected_ids: list[int] = []
    for issue in issues:
        iid = issue["id"]
        if st.session_state.get(f"_batch_{iid}", False):
            selected_ids.append(iid)

    if selected_ids:
        n = len(selected_ids)
        with st.container(border=True):
            st.markdown(
                f'<span style="font-weight:600;color:{TOKEN["primary"]};font-size:0.88em;">'
                f'✅ 已选 {n} 条</span>',
                unsafe_allow_html=True,
            )
            b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
            with b1:
                if st.button("🔄 标记处理中", key="_batch_progress", width="stretch"):
                    cnt = _batch_set_status(selected_ids, "处理中")
                    st.toast(f"已将 {cnt} 条工单标记为「处理中」", icon="🔄")
                    for iid in selected_ids:
                        st.session_state[f"_batch_{iid}"] = False
                    st.rerun()
            with b2:
                if st.button("✅ 标记已解决", key="_batch_resolve", width="stretch"):
                    cnt = _batch_set_status(selected_ids, "已解决")
                    st.toast(f"已将 {cnt} 条工单标记为「已解决」", icon="✅")
                    for iid in selected_ids:
                        st.session_state[f"_batch_{iid}"] = False
                    st.rerun()
            with b3:
                if st.button("🔄 重新打开", key="_batch_reopen", width="stretch"):
                    cnt = _batch_set_status(selected_ids, "待处理")
                    st.toast(f"已将 {cnt} 条工单重新打开", icon="🔄")
                    for iid in selected_ids:
                        st.session_state[f"_batch_{iid}"] = False
                    st.rerun()
            with b4:
                pass  # spacer
    else:
        st.caption("👆 勾选下方工单即可批量操作")

    # Quick select/deselect
    c_all, c_none = st.columns([1, 6])
    with c_all:
        if st.button("☑️ 全选", key="_batch_select_all"):
            for issue in issues:
                st.session_state[f"_batch_{issue['id']}"] = True
            st.rerun()
    with c_none:
        if st.button("🔲 取消全选", key="_batch_deselect_all"):
            for issue in issues:
                st.session_state[f"_batch_{issue['id']}"] = False
            st.rerun()

    st.markdown("---")


# ── Table ──
if not issues:
    st.info("暂无匹配的工单。")
else:
    for i, issue in enumerate(issues):
        iid = issue["id"]
        status = issue.get("status", "")
        urgency = issue.get("urgency", "")
        title = issue.get("title", "")[:40]
        cat = issue.get("category", "")
        loc = issue.get("location", "")
        author = issue.get("author", "")
        reported = issue.get("reported_at", "")[:10]
        desc = issue.get("description", "")

        urgency_icon = "🔴" if urgency == "紧急" else "🟡" if status == "待处理" else "🔵" if status == "处理中" else "🟢"

        with st.container(border=True):
            if batch_mode:
                c_chk, c_main, c_act = st.columns([0.5, 4.5, 2])
                with c_chk:
                    st.checkbox(
                        "选",
                        key=f"_batch_{iid}",
                        label_visibility="collapsed",
                    )
            else:
                c_main, c_act = st.columns([5, 2])

            with c_main:
                st.markdown(
                    f'{urgency_icon} <strong>#{iid} {title}</strong>'
                    f'&nbsp;{tag(status)}'
                    f'{"&nbsp;" + tag(urgency) if urgency == "紧急" else ""}',
                    unsafe_allow_html=True,
                )
                detail = f'{cat}'
                if loc:
                    detail += f' · 📍 {loc}'
                if author:
                    detail += f' · 👤 {author}'
                detail += f' · 🕐 {reported}'
                if status == "已解决":
                    resolved_at = (issue.get("resolved_at") or "")[:10]
                    if resolved_at:
                        detail += f' · ✅ {resolved_at}'
                # Overdue badge: pending > 7 days
                if status in ("待处理", "处理中"):
                    try:
                        rd = datetime.strptime(issue.get("reported_at", "")[:10], "%Y-%m-%d")
                        days_open = (datetime.now() - rd).days
                        if days_open > 7:
                            overdue_icon = "🔴" if days_open > 14 else "🟠"
                            detail += f' · {overdue_icon} 逾期 {days_open} 天'
                    except (ValueError, TypeError):
                        pass
                st.caption(detail, unsafe_allow_html=True if "逾期" in detail else False)
                if desc:
                    with st.expander("📄 详情"):
                        st.write(desc)
            with c_act:
                if not batch_mode:
                    st.markdown("<div style='margin-top:4px;'></div>", unsafe_allow_html=True)
                    if status == "待处理":
                        if st.button("🔄 标记处理中", key=f"mgmt_prog_{iid}", width="stretch"):
                            _set_status(iid, "处理中")
                            st.rerun()
                    if status in ("待处理", "处理中"):
                        if st.button("✅ 标记已解决", key=f"mgmt_resolve_{iid}", width="stretch"):
                            _set_status(iid, "已解决")
                            st.rerun()
                    if status == "已解决":
                        if st.button("🔄 重新打开", key=f"mgmt_reopen_{iid}", width="stretch"):
                            _set_status(iid, "待处理")
                            st.rerun()
