"""提案管理（负责人端）—— 审核、确认公开私有、公示投票统计、决定执行、转部门、填结果、重新执行处理。"""
import csv
import io
from datetime import datetime
import streamlit as st
from ui.guard import require_role

require_role("grid")

from data.db_proposal import (
    get_proposals as db_get_proposals,
    get_proposals_stats as db_get_proposals_stats,
    get_proposal_vote_stats,
    get_vote_stats_batch,
    get_voting_remaining_days,
    is_voting_ended,
    get_proposal_timeline,
    get_export_rows,
    log_export,
    audit_proposal as db_audit,
    remind_confirm as db_remind_confirm,
    decide_execute as db_decide_execute,
    start_execute as db_start_execute,
    resolve_proposal as db_resolve,
    handle_reopen as db_handle_reopen,
    close_proposal as db_close,
    take_down_proposal as db_take_down,
    update_category as db_update_category,
    view_full_phone as db_view_full_phone,
    auto_confirm_overdue,
    auto_end_unfeedback,
    proposal_no,
    VALID_CATEGORIES,
    EXECUTOR_DEPTS,
    STATUS_ALL,
    STATUS_COLORS,
)
from ui.components import TOKEN, tag, page_header
from ui.cache import invalidate_proposals

page_header("💡 提案管理", "审核提案、确认公开/私有、查看公示投票、决定执行并闭环。")

# A 类自动触发（幂等，留痕可复核）：逾期未确认默认执行 / 逾期未反馈自动结束
_auto_done = []
try:
    _auto_done = auto_confirm_overdue() + auto_end_unfeedback()
    if _auto_done:
        invalidate_proposals()
except Exception:
    pass

# 状态颜色（文档第七节）
_COLOR_TOKENS = {
    "黄": ("warning_bg", "warning_border", "warning"),
    "红": ("danger_bg", "danger_border", "danger"),
    "蓝": ("info_bg", "info_border", "info"),
    "绿": ("success_bg", "success_border", "success"),
    "橙": ("accent_bg", "accent_border", "accent"),
    "灰": ("accent_bg", "border", "text_muted"),
}


def _status_tag_html(status: str) -> str:
    color = STATUS_COLORS.get(status or "", "灰")
    bg_k, bd_k, fg_k = _COLOR_TOKENS[color]
    return (
        f'<span style="display:inline-block;background:{TOKEN[bg_k]};border:1px solid {TOKEN[bd_k]};'
        f'color:{TOKEN[fg_k]};border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
        f'font-size:{TOKEN["font_micro"]};white-space:nowrap;font-weight:{TOKEN["weight_semibold"]};">'
        f'{status}</span>'
    )


if _auto_done:
    st.info(f"🤖 系统自动处理了 {len(_auto_done)} 件提案（逾期默认确认公开/私有、逾期未反馈自动结束），已留痕可复核。")

# ---------------------------------------------------------------------------
# 统计横幅
# ---------------------------------------------------------------------------

stats = db_get_proposals_stats()
b_cols = st.columns(6)
with b_cols[0]:
    st.metric("📊 提案总数", stats["total"])
with b_cols[1]:
    st.metric("🟡 待审核", stats["pending_audit"])
with b_cols[2]:
    st.metric("🔵 待确认公开/私有", stats["pending_confirm"])
with b_cols[3]:
    st.metric("🟢 公示中", stats["voting"])
with b_cols[4]:
    st.metric("🟢 执行中", stats["executing"])
with b_cols[5]:
    st.metric("🟠 重新执行处理中", stats["reopening"])

st.markdown("---")

# ---------------------------------------------------------------------------
# 筛选 / 搜索 / 导出
# ---------------------------------------------------------------------------

c_filter, c_export = st.columns([5, 1])
with c_filter:
    status_choice = st.selectbox(
        "状态筛选", ["全部"] + STATUS_ALL, key="_mgmt_status_filter",
    )
    keyword = st.text_input("搜索（标题/内容）", key="_mgmt_keyword", placeholder="输入关键词筛选...")
with c_export:
    st.markdown("<div style='margin-top:28px;'></div>", unsafe_allow_html=True)
    rows = get_export_rows()
    if rows:
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        st.download_button(
            "📥 导出CSV（脱敏）",
            csv_buffer.getvalue(),
            file_name=f"提案导出_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            width="stretch",
            on_click=log_export,
        )

status_filter = status_choice if status_choice != "全部" else None
all_props = db_get_proposals(status=status_filter, keyword=keyword, limit=300)

st.caption(f"共 {len(all_props)} 条 · 导出字段已脱敏，不含个体投票明细与附件")

st.markdown("---")

if not all_props:
    st.info("暂无匹配的提案。")
else:
    vote_map = get_vote_stats_batch([p["id"] for p in all_props])

    for p in all_props:
        pid = p["id"]
        s = p.get("status", "")
        v = vote_map.get(pid, {})
        reopen_n = p.get("reopen_count") or 0
        is_public = p.get("is_public")

        with st.container(border=True):
            head = (
                f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};">'
                f'{proposal_no(pid)} {p.get("title","")[:40]} {_status_tag_html(s)}'
                f'{" · " + tag("重新执行" + (f"×{reopen_n}" if reopen_n > 1 else "")) if reopen_n else ""}'
                f'</div>'
            )
            st.markdown(head, unsafe_allow_html=True)
            st.caption(
                f'{p.get("category","")} · {"🔓 公开" if is_public else "🔒 私有"} · '
                f'👤 {p.get("reporter_name") or p.get("author") or "—"} '
                f'（{p.get("reporter_phone")[:3] + "****" + p.get("reporter_phone")[-4:] if p.get("reporter_phone") and len(p.get("reporter_phone"))==11 else "****"}）'
                f' · {p.get("community_building") or "楼栋未知"} · 🕐 {(p.get("created_at") or "")[:16]}'
            )

            # 状态摘要
            summary = ""
            if s == "公示中":
                days = get_voting_remaining_days(pid)
                if days is not None:
                    summary = f"⏳ 公示剩余 {days} 天"
                ended = is_voting_ended(pid)
                if ended:
                    vs = get_proposal_vote_stats(pid)
                    rank = f"，排名 {vs['rank']}/{vs['scored_count']}" if vs["rank"] else ""
                    summary = f"公示已结束 · 评分人数：{vs['vote_count']}，平均分：{vs['avg_score'] if vs['avg_score'] is not None else '—'}{rank}"
                elif v.get("vote_count"):
                    summary += f" · 评分 {v['vote_count']} 人 · 平均 {v['avg_score'] if v['avg_score'] is not None else '—'}"
            elif v.get("vote_count") and is_public:
                summary = f"评分 {v['vote_count']} 人 · 平均 {v['avg_score'] if v['avg_score'] is not None else '—'}"
            if s == "执行中" and p.get("executor_dept"):
                summary += f" · 执行部门：{p['executor_dept']}"
            if s == "待提案人反馈":
                summary += " · 等待提案人反馈（7 天未反馈自动结束）"
            if s in ("不予执行", "违规下架") and p.get("decision_reason"):
                summary += f" · 原因：{p['decision_reason'][:80]}"
            if s == "待提案人反馈" and p.get("execution_result"):
                summary += f" · 执行结果：{p['execution_result'][:80]}"
            if s == "已完成":
                summary += f" · 反馈：{p.get('satisfaction') or '满意'}"
            if s == "待提案人反馈" and p.get("satisfaction") == "不满意":
                summary += f" · 不满意原因：{p.get('feedback_reason') or ''}"
            if summary:
                st.caption(summary)

            with st.expander("📄 详情 / 操作", expanded=False):
                if p.get("description"):
                    st.markdown(f'**提案内容：**\n\n{p.get("description","")}')
                if p.get("audit_opinion"):
                    st.markdown(f'**审核意见：** {p.get("audit_opinion")}')
                if p.get("decision_reason") and s not in ("不予执行", "违规下架"):
                    st.markdown(f'**决定理由：** {p.get("decision_reason")}')
                if p.get("execution_result") and s not in ("待提案人反馈",):
                    st.markdown(f'**执行结果：** {p.get("execution_result")}')
                if p.get("is_agent_report"):
                    st.markdown(
                        f'**代报信息：** {p.get("agent_name") or "—"} · {p.get("agent_phone") or "—"} · '
                        f'与提案人关系：{p.get("agent_relation") or "—"}'
                    )
                if p.get("attachment_public"):
                    st.markdown("**附件：** 提案人已选择公开附件（公示中居民可见；审核时需确认不含隐私）")

                # ---- 状态操作 ----
                acted = False
                if s in ("待审核", "退回修改"):
                    acted = True
                    st.markdown("**🔍 审核**（退回必须填写意见；附件公开需一并审核）")
                    approve = st.radio("结论", ["通过", "退回"], horizontal=True,
                                       key=f"mgmt_audit_res_{pid}")
                    opinion = st.text_area("审核意见", key=f"mgmt_audit_opinion_{pid}",
                                           placeholder="退回必填；附件含隐私请注明'附件不公开'",
                                           height=70)
                    attach_has_privacy = st.checkbox(
                        "提案人选了公开附件，但附件含个人隐私（审核不通过附件公开，不影响提案本身）",
                        key=f"mgmt_audit_attach_{pid}",
                    )
                    if st.button("✅ 提交审核", key=f"mgmt_audit_btn_{pid}", type="primary"):
                        ok, msg = db_audit(
                            pid, approve == "通过", opinion,
                            attachment_public_ok=(False if attach_has_privacy else None),
                        )
                        if ok:
                            invalidate_proposals()
                            st.success("审核已提交。" if approve == "通过" else "已退回修改。")
                            st.rerun()
                        else:
                            st.error(msg)
                elif s == "待确认公示/私有":
                    acted = True
                    st.markdown(f"**📣 居民尚未确认公开/私有**（{'公开' if is_public else '私有'}，7 天窗口内）")
                    if st.button("🔔 提醒居民确认", key=f"mgmt_remind_{pid}"):
                        ok, msg = db_remind_confirm(pid)
                        if ok:
                            st.success("已发送提醒通知。")
                        else:
                            st.error(msg)
                elif s == "公示中":
                    acted = True
                    if not is_voting_ended(pid):
                        st.markdown(f"⏳ 公示期内不能提前决定执行/不执行，剩余 {get_voting_remaining_days(pid)} 天。")
                    else:
                        st.markdown("**⚖️ 公示已结束，请决定是否执行**（理由必填）")
                        reason = st.text_input("决定理由", key=f"mgmt_dec_reason_{pid}")
                        c_d1, c_d2 = st.columns(2)
                        with c_d1:
                            if st.button("✅ 决定执行", key=f"mgmt_dec_yes_{pid}", type="primary"):
                                ok, msg = db_decide_execute(pid, True, reason)
                                if ok:
                                    invalidate_proposals()
                                    st.success("已决定执行，等待转部门。")
                                    st.rerun()
                                else:
                                    st.error(msg)
                        with c_d2:
                            if st.button("⛔ 决定不执行", key=f"mgmt_dec_no_{pid}"):
                                ok, msg = db_decide_execute(pid, False, reason)
                                if ok:
                                    invalidate_proposals()
                                    st.success("已决定不予执行（已通知提案人）。")
                                    st.rerun()
                                else:
                                    st.error(msg)
                elif s == "待执行":
                    acted = True
                    st.markdown("**🚚 转部门执行 / 决定不予执行**")
                    dept_idx = st.selectbox(
                        "执行部门", EXECUTOR_DEPTS + ["自定义..."],
                        key=f"mgmt_dept_{pid}",
                    )
                    dept = dept_idx
                    if dept_idx == "自定义...":
                        dept = st.text_input("自定义部门", key=f"mgmt_dept_custom_{pid}")
                    c_e1, c_e2 = st.columns(2)
                    with c_e1:
                        if st.button("🚀 转部门执行", key=f"mgmt_exec_{pid}", type="primary"):
                            ok, msg = db_start_execute(pid, dept)
                            if ok:
                                invalidate_proposals()
                                st.success(f"已转 {dept} 执行。")
                                st.rerun()
                            else:
                                st.error(msg)
                    with c_e2:
                        reason_no = st.text_input("不予执行理由", key=f"mgmt_noexec_reason_{pid}")
                        if st.button("⛔ 不予执行", key=f"mgmt_noexec_{pid}"):
                            ok, msg = db_decide_execute(pid, False, reason_no)
                            if ok:
                                invalidate_proposals()
                                st.success("已决定不予执行（已通知提案人）。")
                                st.rerun()
                            else:
                                st.error(msg)
                elif s == "执行中":
                    acted = True
                    st.markdown(f"**🔧 填写执行结果**（执行部门：{p.get('executor_dept') or '—'}）")
                    result = st.text_area("执行结果", key=f"mgmt_result_{pid}",
                                          placeholder="执行完成情况、备注...", height=70)
                    if st.button("✅ 提交执行结果（进入待提案人反馈）", key=f"mgmt_result_btn_{pid}", type="primary"):
                        ok, msg = db_resolve(pid, result)
                        if ok:
                            invalidate_proposals()
                            st.success("执行结果已提交，等待提案人反馈满意度。")
                            st.rerun()
                        else:
                            st.error(msg)
                elif s == "待提案人反馈":
                    acted = True
                    st.markdown("**📨 等待提案人反馈**（7 天未反馈将自动标记已结束）")
                elif s == "重新执行":
                    acted = True
                    st.markdown(
                        f"**🔁 重新执行处理**（第 {reopen_n} 次）"
                        + ("：已超过 2 次，请选择「关闭」或「继续」" if reopen_n >= 2 else "")
                    )
                    if reopen_n >= 2:
                        st.warning("重新执行已超过 2 次，请选择关闭或继续（留痕）。")
                    if p.get("is_public"):
                        st.markdown("公开提案：继续将重新公示 3 天并重新投票（数据清零）。")
                        dept_needed = ""
                    else:
                        dept_idx = st.selectbox("重新选择执行部门", EXECUTOR_DEPTS + ["自定义..."],
                                                key=f"mgmt_redept_{pid}")
                        dept_needed = dept_idx
                        if dept_idx == "自定义...":
                            dept_needed = st.text_input("自定义部门", key=f"mgmt_redept_custom_{pid}")
                    c_r1, c_r2 = st.columns(2)
                    with c_r1:
                        if st.button("▶️ 继续重新执行", key=f"mgmt_reopen_go_{pid}", type="primary"):
                            ok, msg = db_handle_reopen(pid, close=False, dept=dept_needed)
                            if ok:
                                invalidate_proposals()
                                st.success("已继续重新执行。" + ("（已重新公示 3 天）" if p.get("is_public") else ""))
                                st.rerun()
                            else:
                                st.error(msg)
                    with c_r2:
                        close_reason = st.text_input("关闭原因", key=f"mgmt_reopen_close_reason_{pid}")
                        if st.button("⛔ 关闭提案", key=f"mgmt_reopen_close_{pid}"):
                            ok, msg = db_handle_reopen(pid, close=True, reason=close_reason)
                            if ok:
                                invalidate_proposals()
                                st.success("已关闭。")
                                st.rerun()
                            else:
                                st.error(msg)

                # ---- 通用管理操作（非终点状态）----
                if s not in ("已完成", "不予执行", "违规下架", "已关闭", "已撤回", "已结束"):
                    st.markdown("---")
                    st.markdown("**🛠️ 管理操作**（关闭/下架需二次确认）")
                    c_g1, c_g2, c_g3 = st.columns(3)
                    with c_g1:
                        cat_idx = VALID_CATEGORIES.index(p.get("category")) if p.get("category") in VALID_CATEGORIES else 4
                        new_cat = st.selectbox("修改类别", VALID_CATEGORIES, index=cat_idx, key=f"mgmt_cat_{pid}")
                        if st.button("保存类别", key=f"mgmt_cat_btn_{pid}"):
                            ok, msg = db_update_category(pid, new_cat)
                            if ok:
                                invalidate_proposals()
                                st.success("类别已修改（留痕）。")
                                st.rerun()
                            else:
                                st.error(msg)
                    with c_g2:
                        confirm_close = st.checkbox("我确认：特殊情况关闭（提案人放弃/重复/违法违规）",
                                                    key=f"mgmt_close_ck_{pid}")
                        close_reason = st.text_input("关闭原因", key=f"mgmt_close_reason_{pid}")
                        if st.button("🗑️ 关闭提案", key=f"mgmt_close_btn_{pid}"):
                            if not confirm_close:
                                st.warning("请先勾选二次确认。")
                            else:
                                ok, msg = db_close(pid, close_reason)
                                if ok:
                                    invalidate_proposals()
                                    st.success("已关闭。")
                                    st.rerun()
                                else:
                                    st.error(msg)
                    with c_g3:
                        confirm_down = st.checkbox("我确认：违规下架（内容违法违规）",
                                                   key=f"mgmt_down_ck_{pid}")
                        down_reason = st.text_input("下架原因", key=f"mgmt_down_reason_{pid}")
                        if st.button("🚫 违规下架", key=f"mgmt_down_btn_{pid}"):
                            if not confirm_down:
                                st.warning("请先勾选二次确认。")
                            else:
                                ok, msg = db_take_down(pid, down_reason)
                                if ok:
                                    invalidate_proposals()
                                    st.success("已违规下架。")
                                    st.rerun()
                                else:
                                    st.error(msg)
                    # 查看完整手机号（二次确认，留痕）
                    if st.button("📱 查看完整手机号（留痕）", key=f"mgmt_phone_{pid}"):
                        st.session_state[f"_mgmt_show_phone_{pid}"] = True
                    if st.session_state.get(f"_mgmt_show_phone_{pid}"):
                        if st.button("确认查看", key=f"mgmt_phone_confirm_{pid}"):
                            phone = db_view_full_phone(pid)
                            st.session_state[f"_mgmt_show_phone_{pid}"] = False
                            st.info(f"提案人完整手机号：{phone}（查看已留痕）")
                elif s == "已撤回":
                    st.markdown("居民已撤回提案。")

                # 留痕时间线（默认最近 3 条，可展开全部）
                timeline = get_proposal_timeline(pid, limit=100)
                if timeline:
                    st.markdown("---")
                    st.markdown("**📜 留痕**（默认最近 3 条）")
                    for t in timeline[:3]:
                        st.markdown(
                            f'<div style="font-size:0.78em;color:{TOKEN["text_sec"]};">'
                            f'· {(t.get("created_at") or "")[:16]} {t.get("actor","")} '
                            f'{t.get("action","")}（{t.get("before_value","")} → {t.get("after_value","")}）'
                            f'{"：" + t.get("detail","")[:60] if t.get("detail") else ""}</div>',
                            unsafe_allow_html=True,
                        )
                    if len(timeline) > 3:
                        with st.expander("查看全部留痕"):
                            for t in timeline:
                                st.markdown(
                                    f'<div style="font-size:0.78em;color:{TOKEN["text_sec"]};">'
                                    f'· {(t.get("created_at") or "")[:16]} {t.get("actor","")} '
                                    f'{t.get("action","")}（{t.get("before_value","")} → {t.get("after_value","")}）'
                                    f'{"：" + t.get("detail","") if t.get("detail") else ""}</div>',
                                    unsafe_allow_html=True,
                                )
