# ui/pages_teacher/issues_mgmt.py
"""📋 工单管理 — 表格视图、筛选、批量操作、指派、时效统计."""
import csv
import io
import logging
from datetime import datetime
import streamlit as st
from ui.components import TOKEN, tag
from ui.cache import cached_issues, cached_issues_stats, invalidate_issues
from data.database import update_issue_status, get_db

_log = logging.getLogger(__name__)

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

# ── Filters (2+2 grid: stacks to 4 rows on mobile) ──
c1, c2 = st.columns(2)
with c1:
    cat_choice = st.selectbox(
        "分类",
        ["全部", "设施维修", "环境卫生", "安全隐患", "教学设备", "网络服务", "餐饮问题", "校园管理", "其他"],
        key="_issues_cat_filter",
        label_visibility="collapsed",
    )
with c2:
    search = st.text_input("搜索标题", placeholder="输入关键词...", key="_issues_search", label_visibility="collapsed")
c3, c4 = st.columns(2)
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


# ═══════════════════════════════════════════════════════════════
# Auto Category Suggestion (keyword-based, no LLM)
# ═══════════════════════════════════════════════════════════════
_CATEGORY_KEYWORDS = {
    "设施维修": ["灯", "水龙头", "空调", "门", "窗", "电梯", "厕所", "卫生间", "漏水", "坏了", "故障", "不亮", "不漏", "关不上", "打不开", "墙", "地板", "天花板", "管道", "暖气"],
    "环境卫生": ["垃圾", "脏", "臭", "清洁", "卫生", "异味", "蟑螂", "老鼠", "虫子", "发霉", "长毛", "烟头", "纸屑", "落叶"],
    "安全隐患": ["火", "电线", "裸露", "消防", "灭火器", "应急灯", "护栏", "松动", "摇晃", "塌", "滑", "摔", "漏电", "冒烟"],
    "教学设备": ["投影", "电脑", "黑板", "白板", "桌椅", "话筒", "音响", "多媒体", "机房", "实验室", "仪器"],
    "网络服务": ["网", "wifi", "WiFi", "信号", "校园网", "VPN", "宽带", "断网", "网速", "卡顿"],
    "餐饮问题": ["食堂", "餐厅", "饭菜", "涨价", "价格", "口味", "窗口", "排队", "座位", "筷子", "碗", "餐具"],
    "校园管理": ["快递", "停车", "自行车", "电动车", "校门", "保安", "宿舍", "自习室", "图书馆", "开放时间"],
}


def _suggest_category(title: str, description: str = "") -> str:
    """Suggest a category based on keyword matching. Returns '' if uncertain."""
    text = f"{title} {description}".lower()
    scores = {}
    for cat, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in text)
        if score > 0:
            scores[cat] = score
    if not scores:
        return ""
    # Return best match, but only if it's a clear winner (score >= 2 or > 2x runner-up)
    best = max(scores, key=scores.get)
    best_score = scores[best]
    runner_up = max((s for k, s in scores.items() if k != best), default=0)
    if best_score >= 2 or best_score > runner_up * 2:
        return best
    return ""


# ── Teacher processing stats ──
with st.expander("📊 我的处理统计", expanded=False):
    try:
        with get_db() as conn:
            my_processed = conn.execute(
                "SELECT COUNT(*) as cnt FROM activity_log "
                "WHERE action IN ('开始处理', '解决问题', '重新打开', '更新工单') "
                "AND date(created_at) = date('now', 'localtime')"
            ).fetchone()
            today_processed = my_processed["cnt"] if my_processed else 0

            my_week = conn.execute(
                "SELECT COUNT(*) as cnt FROM activity_log "
                "WHERE action IN ('开始处理', '解决问题') "
                "AND created_at > date('now', '-7 days')"
            ).fetchone()
            week_processed = my_week["cnt"] if my_week else 0

            # Avg resolution time this month
            avg_days_row = conn.execute(
                "SELECT ROUND(AVG(julianday(resolved_at) - julianday(reported_at)), 1) as avg_days "
                "FROM campus_issues WHERE status = '已解决' AND resolved_at > date('now', '-30 days')"
            ).fetchone()
            avg_days = avg_days_row["avg_days"] if avg_days_row and avg_days_row["avg_days"] is not None else None
    except Exception:
        _log.warning("Failed to load teacher processing stats", exc_info=True)
        today_processed, week_processed, avg_days = 0, 0, None

    mc1, mc2, mc3 = st.columns(3)
    with mc1:
        st.metric("今日处理", f"{today_processed} 件")
    with mc2:
        st.metric("本周处理", f"{week_processed} 件")
    with mc3:
        st.metric("月均解决时间", f"{avg_days} 天" if avg_days else "—")

# ── Stats bar ──
stats = cached_issues_stats()
pending_c = stats["by_status"].get("待处理", 0)
progress_c = stats["by_status"].get("处理中", 0)
resolved_c = stats["by_status"].get("已解决", 0)

# ── SLA summary ──
overdue_total = 0
urgent_unresolved = 0
try:
    with get_db() as conn:
        overdue_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues "
            "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
        ).fetchone()
        overdue_total = overdue_row["cnt"] if overdue_row else 0
        urgent_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues "
            "WHERE urgency='紧急' AND status != '已解决'"
        ).fetchone()
        urgent_unresolved = urgent_row["cnt"] if urgent_row else 0
except Exception:
    _log.warning("Failed to load SLA/urgent counts", exc_info=True)

c_stats, c_export = st.columns([5, 1])
with c_stats:
    sla_parts = []
    if urgent_unresolved > 0:
        sla_parts.append(f'🔴 紧急未处理 {urgent_unresolved}')
    if overdue_total > 0:
        sla_parts.append(f'⚠️ 超7天积压 {overdue_total}')
    sla_str = ' · '.join(sla_parts) if sla_parts else ''
    st.caption(
        f'共 {len(issues)} 条 · '
        f'⏳ 待处理 {pending_c} · 🔄 处理中 {progress_c} · ✅ 已解决 {resolved_c}'
        + (f' · {sla_str}' if sla_str else '')
    )
with c_export:
    if issues:
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["ID", "标题", "分类", "建议分类", "位置", "状态", "紧急度",
                         "上报人", "指派人", "上报时间", "解决时间", "处理耗时(天)",
                         "处理备注", "问题描述"])
        for i in issues:
            resolved_at = (i.get("resolved_at") or "")
            reported_at = i.get("reported_at", "")
            days_to_resolve = ""
            if resolved_at and reported_at:
                try:
                    rd = datetime.strptime(resolved_at[:10], "%Y-%m-%d")
                    rp = datetime.strptime(reported_at[:10], "%Y-%m-%d")
                    days_to_resolve = str((rd - rp).days)
                except (ValueError, TypeError):
                    pass
            writer.writerow([
                i.get("id"), i.get("title"), i.get("category"),
                i.get("suggested_category", ""), i.get("location"),
                i.get("status"), i.get("urgency"), i.get("author"),
                i.get("assignee", ""),
                reported_at[:10] if reported_at else "",
                resolved_at[:10] if resolved_at else "",
                days_to_resolve,
                i.get("processing_note", ""),
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
def _set_status(iid: int, new_status: str, note: str = "", assignee: str = ""):
    update_issue_status(iid, new_status, processing_note=note, assignee=assignee)
    invalidate_issues()


def _batch_set_status(selected_ids: list[int], new_status: str, note: str = ""):
    """Bulk update status for selected issues."""
    count = 0
    for iid in selected_ids:
        update_issue_status(iid, new_status, processing_note=note)
        count += 1
    invalidate_issues()
    return count


# ── Resolve author for display ──
def _resolve_author_display(author: str) -> str:
    if not author:
        return "匿名"
    return author


# ── Compute processing time ──
def _compute_days(reported_at: str, resolved_at: str = "") -> tuple[int | None, int | None]:
    """Return (days_open, days_to_resolve)."""
    days_open = None
    days_to_resolve = None
    try:
        rd = datetime.strptime(reported_at[:10], "%Y-%m-%d")
        days_open = (datetime.now() - rd).days
        if resolved_at:
            rv = datetime.strptime(resolved_at[:10], "%Y-%m-%d")
            days_to_resolve = (rv - rd).days
    except (ValueError, TypeError):
        pass
    return days_open, days_to_resolve


# ── Batch action bar ──
if batch_mode and issues:
    selected_ids: list[int] = []
    for issue in issues:
        iid = issue["id"]
        if st.session_state.get(f"_batch_{iid}", False):
            selected_ids.append(iid)

    if selected_ids:
        n = len(selected_ids)
        with st.container(border=True):
            st.markdown(
                f'<span style="font-weight:600;color:{TOKEN["accent"]};font-size:0.88em;">'
                f'✅ 已选 {n} 条</span>',
                unsafe_allow_html=True,
            )
            # Batch note
            batch_note = st.text_input(
                "批量处理备注", key="_batch_note",
                placeholder="可选：为所选工单添加统一备注…",
            )
            b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
            with b1:
                if st.button("🔄 标记处理中", key="_batch_progress", width="stretch"):
                    cnt = _batch_set_status(selected_ids, "处理中", note=batch_note)
                    st.toast(f"已将 {cnt} 条工单标记为「处理中」", icon="🔄")
                    _clear_batch()
                    st.rerun()
            with b2:
                if st.button("✅ 标记已解决", key="_batch_resolve", width="stretch"):
                    cnt = _batch_set_status(selected_ids, "已解决", note=batch_note)
                    st.toast(f"已将 {cnt} 条工单标记为「已解决」", icon="✅")
                    _clear_batch()
                    st.rerun()
            with b3:
                if st.button("🔄 重新打开", key="_batch_reopen", width="stretch"):
                    cnt = _batch_set_status(selected_ids, "待处理", note=batch_note)
                    st.toast(f"已将 {cnt} 条工单重新打开", icon="🔄")
                    _clear_batch()
                    st.rerun()
            with b4:
                pass
    else:
        st.caption("👆 勾选下方工单即可批量操作")

    c_all, c_none = st.columns([1, 6])
    with c_all:
        if st.button("☑️ 全选", key="_batch_select_all"):
            for issue in issues:
                st.session_state[f"_batch_{issue['id']}"] = True
            st.rerun()
    with c_none:
        if st.button("🔲 取消全选", key="_batch_deselect_all"):
            _clear_batch()
            st.rerun()

    st.markdown("---")


def _clear_batch():
    """Clear all batch checkboxes."""
    for k in list(st.session_state.keys()):
        if k.startswith("_batch_") and k != "_batch_note":
            st.session_state[k] = False
    if "_batch_note" in st.session_state:
        del st.session_state["_batch_note"]


# ── Table ──
if not issues:
    st.info("暂无匹配的工单。")
else:
    # ── Column headers ──
    col_hdr = st.columns([3, 2, 1.5, 1.5, 2])
    with col_hdr[0]:
        st.caption("📋 工单信息")
    with col_hdr[1]:
        st.caption("👤 上报人 / 指派人")
    with col_hdr[2]:
        st.caption("⏱️ 时效")
    with col_hdr[3]:
        st.caption("🏷️ 建议分类")
    with col_hdr[4]:
        st.caption("🔧 操作")

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
        proc_note = issue.get("processing_note", "")
        assignee = issue.get("assignee", "")
        suggested_cat = issue.get("suggested_category", "")
        resolved_at = (issue.get("resolved_at") or "")[:10]

        days_open, days_to_resolve = _compute_days(
            issue.get("reported_at", ""),
            issue.get("resolved_at", ""),
        )

        urgency_icon = "🔴" if urgency == "紧急" else "🟡" if status == "待处理" else "🔵" if status == "处理中" else "🟢"

        with st.container(border=True):
            if batch_mode:
                c_chk, c_main, c_assignee, c_time, c_suggest, c_act = st.columns([1, 3, 1.5, 1.2, 1.2, 2])
                with c_chk:
                    st.checkbox("选", key=f"_batch_{iid}", label_visibility="collapsed")
            else:
                c_main, c_assignee, c_time, c_suggest, c_act = st.columns([3, 1.5, 1.2, 1.2, 2])

            # ── Column 1: Main info ──
            with c_main:
                st.markdown(
                    f'{urgency_icon} <strong>#{iid} {title}</strong>'
                    f'&nbsp;{tag(status)}'
                    f'{"&nbsp;" + tag(urgency) if urgency == "紧急" else ""}',
                    unsafe_allow_html=True,
                )
                detail_parts = [cat]
                if loc:
                    detail_parts.append(f'📍 {loc}')
                detail_parts.append(f'🕐 {reported}')
                if status == "已解决" and resolved_at:
                    detail_parts.append(f'✅ {resolved_at}')
                st.caption(' · '.join(detail_parts))

            # ── Column 2: Author + Assignee ──
            with c_assignee:
                st.caption(f"上报：{_resolve_author_display(author)}")
                if assignee:
                    st.caption(f"👷 {assignee}")

            # ── Column 3: Processing time ──
            with c_time:
                if status == "已解决" and days_to_resolve is not None:
                    time_color = TOKEN["success"] if days_to_resolve <= 3 else TOKEN["warning"] if days_to_resolve <= 7 else TOKEN["danger"]
                    st.markdown(
                        f'<span style="font-size:0.78em;color:{time_color};font-weight:600;">'
                        f'✅ {days_to_resolve}天解决</span>',
                        unsafe_allow_html=True,
                    )
                elif status in ("待处理", "处理中") and days_open is not None:
                    if days_open > 14:
                        time_color, icon = TOKEN["danger"], "🔴"
                    elif days_open > 7:
                        time_color, icon = TOKEN["warning"], "🟠"
                    elif days_open > 3:
                        time_color, icon = TOKEN["warning"], "🟡"
                    else:
                        time_color, icon = TOKEN["text_sec"], "⏳"
                    st.markdown(
                        f'<span style="font-size:0.78em;color:{time_color};font-weight:600;">'
                        f'{icon} {days_open}天</span>',
                        unsafe_allow_html=True,
                    )

            # ── Column 4: Suggested category ──
            with c_suggest:
                if not suggested_cat:
                    suggested_cat = _suggest_category(title, desc)
                if suggested_cat and suggested_cat != cat:
                    st.markdown(
                        f'<span style="font-size:0.72em;background:{TOKEN["accent_bg"]};'
                        f'color:{TOKEN["accent"]};padding:1px 6px;border-radius:4px;'
                        f'font-weight:600;cursor:pointer;" title="AI建议将此类问题归类为「{suggested_cat}」">'
                        f'🤖 {suggested_cat}</span>',
                        unsafe_allow_html=True,
                    )
                elif suggested_cat == cat:
                    st.caption("🤖 一致")

            # ── Column 5: Actions ──
            with c_act:
                if not batch_mode:
                    # Detail dialog trigger
                    detail_key = f"_detail_{iid}"
                    if st.button("📄 详情", key=f"detail_btn_{iid}", width="stretch"):
                        st.session_state[detail_key] = not st.session_state.get(detail_key, False)
                        st.rerun()

            # ── Detail expander (below the row) ──
            detail_key = f"_detail_{iid}"
            if st.session_state.get(detail_key, False):
                with st.container(border=True):
                    st.markdown(f"### 📄 工单 #{iid} 详情")
                    st.write(f"**标题**：{title}")
                    st.write(f"**分类**：{cat}")
                    if suggested_cat and suggested_cat != cat:
                        st.info(f"🤖 建议分类：**{suggested_cat}**")
                    st.write(f"**位置**：{loc or '未指定'}")
                    st.write(f"**状态**：{status} · **紧急度**：{urgency}")
                    st.write(f"**上报人**：{_resolve_author_display(author)}")
                    st.write(f"**上报时间**：{reported}")
                    if resolved_at:
                        st.write(f"**解决时间**：{resolved_at}")
                    if days_open is not None:
                        st.write(f"**已开启**：{days_open} 天"
                                 + (f"（{days_to_resolve} 天解决）" if days_to_resolve else ""))
                    if desc:
                        st.markdown("**问题描述**：")
                        st.info(desc)
                    if proc_note:
                        st.markdown("**📝 处理备注**：")
                        st.success(proc_note)

                    # Activity history
                    st.markdown("**📜 处理记录**：")
                    try:
                        with get_db() as conn:
                            activity = conn.execute(
                                "SELECT * FROM activity_log WHERE target_type = 'issue' "
                                "AND target_id = ? ORDER BY created_at DESC LIMIT 10",
                                (iid,),
                            ).fetchall()
                            if activity:
                                for act in activity:
                                    act_icon = {"上报问题": "📝", "开始处理": "🔄", "解决问题": "✅",
                                                "重新打开": "🔓", "更新工单": "📋"}.get(act["action"], "📌")
                                    st.caption(
                                        f'{act_icon} {act["actor"]} · {act["action"]} · '
                                        f'{(act["created_at"] or "")[:16]}'
                                        + (f' — {act["detail"]}' if act.get("detail") else '')
                                    )
                            else:
                                st.caption("暂无处理记录")
                    except Exception:
                        _log.debug("non-critical failure", exc_info=True)
                        st.caption("处理记录暂不可用")

                    # ── Action buttons in detail view ──
                    st.markdown("---")
                    st.markdown("**🔧 处理操作**")
                    dc1, dc2, dc3 = st.columns(3)
                    detail_note_key = f"_detail_note_{iid}"
                    detail_assignee_key = f"_detail_assignee_{iid}"
                    with dc1:
                        st.text_input("处理备注", key=detail_note_key, placeholder="添加处理说明…",
                                     label_visibility="collapsed")
                    with dc2:
                        st.text_input("指派处理人", key=detail_assignee_key, placeholder="输入姓名…",
                                     label_visibility="collapsed")
                    with dc3:
                        pass

                    dbtn1, dbtn2, dbtn3, dbtn4 = st.columns(4)
                    if status == "待处理":
                        with dbtn1:
                            if st.button("🔄 处理中", key=f"detail_prog_{iid}", width="stretch"):
                                _set_status(iid, "处理中",
                                           note=st.session_state.get(detail_note_key, ""),
                                           assignee=st.session_state.get(detail_assignee_key, ""))
                                if detail_note_key in st.session_state:
                                    del st.session_state[detail_note_key]
                                if detail_assignee_key in st.session_state:
                                    del st.session_state[detail_assignee_key]
                                st.rerun()
                        with dbtn2:
                            if st.button("✅ 已解决", key=f"detail_resolve_{iid}", width="stretch"):
                                _set_status(iid, "已解决",
                                           note=st.session_state.get(detail_note_key, ""),
                                           assignee=st.session_state.get(detail_assignee_key, ""))
                                if detail_note_key in st.session_state:
                                    del st.session_state[detail_note_key]
                                if detail_assignee_key in st.session_state:
                                    del st.session_state[detail_assignee_key]
                                st.rerun()
                    elif status == "处理中":
                        with dbtn1:
                            if st.button("✅ 标记已解决", key=f"detail_resolve_{iid}", width="stretch"):
                                _set_status(iid, "已解决",
                                           note=st.session_state.get(detail_note_key, ""),
                                           assignee=st.session_state.get(detail_assignee_key, ""))
                                if detail_note_key in st.session_state:
                                    del st.session_state[detail_note_key]
                                if detail_assignee_key in st.session_state:
                                    del st.session_state[detail_assignee_key]
                                st.rerun()
                        with dbtn2:
                            if st.button("↩️ 退回待处理", key=f"detail_return_{iid}", width="stretch"):
                                _set_status(iid, "待处理",
                                           note=st.session_state.get(detail_note_key, ""),
                                           assignee=st.session_state.get(detail_assignee_key, ""))
                                if detail_note_key in st.session_state:
                                    del st.session_state[detail_note_key]
                                if detail_assignee_key in st.session_state:
                                    del st.session_state[detail_assignee_key]
                                st.rerun()
                    elif status == "已解决":
                        with dbtn1:
                            if st.button("🔄 重新打开", key=f"detail_reopen_{iid}", width="stretch"):
                                _set_status(iid, "待处理",
                                           note=st.session_state.get(detail_note_key, ""),
                                           assignee=st.session_state.get(detail_assignee_key, ""))
                                if detail_note_key in st.session_state:
                                    del st.session_state[detail_note_key]
                                if detail_assignee_key in st.session_state:
                                    del st.session_state[detail_assignee_key]
                                st.rerun()

                    # Quick assignee fill
                    if st.session_state.get(detail_note_key, "") == "" and proc_note:
                        st.session_state[detail_note_key] = proc_note
                    if st.session_state.get(detail_assignee_key, "") == "" and assignee:
                        st.session_state[detail_assignee_key] = assignee

                    if st.button("❌ 收起详情", key=f"detail_close_{iid}", width="stretch"):
                        st.session_state[detail_key] = False
                        st.rerun()
