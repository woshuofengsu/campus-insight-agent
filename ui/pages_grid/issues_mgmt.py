"""📋 工单管理 — 负责人报修工作台：待审核、派单、处理、特殊情况、改派、完整留痕。"""
import csv
import io
import json
import logging
import re
from datetime import datetime
import streamlit as st
from ui.guard import require_role

require_role("grid")

from data.db_repair import (
    STATUS_ALL,
    get_issues, get_issue_timeline, get_pending_review_issues,
    audit_issue, dispatch_issue, start_process, resolve_issue,
    close_issue, transfer_issue, negotiate_issue,
    supplement_issue as db_supplement, confirm_supplement as db_confirm_supplement,
    update_issue_category as db_update_category,
)
from data.db_notifications import log_activity
from ui.cache import invalidate_issues
from ui.components import TOKEN, page_header

_log = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

# 状态 → 颜色（文档《01-报修.md》第七节，与居民端一致）
_STATUS_COLORS = {
    "待审核": "#f59e0b",        # 黄
    "已审核待派单": "#2563eb",  # 蓝
    "已派单": "#2563eb",        # 蓝
    "处理中": "#059669",        # 绿
    "待居民反馈": "#f97316",    # 橙
    "处理结束": "#64748b",      # 灰
    "已撤回": "#64748b",        # 灰
    "退回补充信息": "#dc2626",  # 红
    "已关闭": "#64748b",        # 灰
    "待协商": "#f97316",        # 橙
    "已转出": "#64748b",        # 灰
}
_TERMINAL = {"处理结束", "已关闭", "已转出", "已撤回"}
_ACTIVE = {"待审核", "退回补充信息", "已审核待派单", "已派单", "处理中", "待协商", "待居民反馈"}

_URGENCY_EMOJI = {"紧急": "🔴", "中等": "🟠", "一般": "🟡", "普通": "🔵"}
_DEADLINE_HOURS = {"紧急": 1, "中等": 4, "一般": 24, "普通": 48}


def _deadline_info(issue: dict) -> tuple[bool, str]:
    """超时判定（R50/R51）：按审核通过时间计时，未结束状态才判；返回 (是否超时, 标签文案)。"""
    if issue.get("status") not in ("已审核待派单", "已派单", "处理中", "待居民反馈"):
        return False, ""
    approved = issue.get("approved_at")
    if not approved:
        return False, ""
    try:
        base = datetime.strptime(str(approved)[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return False, ""
    hours = _DEADLINE_HOURS.get(issue.get("urgency", ""), 24)
    used_h = (datetime.now() - base).total_seconds() / 3600.0
    if used_h > hours:
        return True, f"⏰ 已超时 {int(used_h - hours)} 小时"
    remain = hours - used_h
    if remain < 1:
        return False, f"⏰ 剩余不足 1 小时"
    return False, f"⏰ 剩余 {int(remain)} 小时"

page_header("📋 工单管理", "报修工单负责人工作台：审核、派单、处理、特殊情况、完整留痕。")

_memory = st.session_state.get("memory")
_profile = _memory.get_user_profile() if _memory is not None else (st.session_state.get("user_profile") or {})
_actor = (_profile.get("name") or "").strip() or "负责人"


def _status_badge(status: str) -> str:
    color = _STATUS_COLORS.get(status, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}1f;border:1px solid {color};'
        f'color:{color};border-radius:999px;padding:1px 10px;font-size:0.78em;'
        f'font-weight:600;white-space:nowrap;">{status}</span>'
    )


def _mask_phone(phone: str) -> str:
    phone = (phone or "").strip()
    if len(phone) == 11:
        return f"{phone[:3]}****{phone[7:]}"
    return phone or "—"


def _mask_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "—"
    if len(name) == 1:
        return f"{name}**"
    return f"{name[0]}{'*' * (len(name) - 1)}"


def _do_audit(iid: int, decision: str, opinion: str):
    """审核动作（通过 / 退回，退回必填意见）。"""
    if decision == "✅ 通过":
        ok, msg = audit_issue(iid, approve=True, actor=_actor)
    elif not (opinion or "").strip():
        ok, msg = False, "退回必须填写审核意见"
    else:
        ok, msg = audit_issue(iid, approve=False, opinion=opinion.strip(), actor=_actor)
    if ok:
        st.success("审核完成，状态已更新。")
        invalidate_issues()
        st.rerun()
    else:
        st.error(msg)


def _render_audit_card(issue: dict):
    """待审核队列卡片：电话核实后审核（通过 / 退回必填意见）。"""
    iid = issue["id"]
    status = issue.get("status", "")
    with st.container(border=True):
        st.markdown(
            f'<span style="font-weight:700;color:{TOKEN["text"]};">#{iid} {issue.get("title","")[:40]}</span>'
            f'&nbsp;{_status_badge(status)}'
            + (f'&nbsp;{_URGENCY_EMOJI.get(issue.get("urgency",""), "")} {issue.get("urgency","")}' if issue.get("urgency") else ""),
            unsafe_allow_html=True,
        )
        st.caption(
            f'{issue.get("issue_type", "")} · {issue.get("category", "")} · '
            f'📍 {issue.get("location") or "—"} · 🕐 {(issue.get("reported_at") or "")[:16]}'
        )
        st.caption(
            f'报修人：{_mask_name(issue.get("reporter_name"))} · '
            f'电话：{_mask_phone(issue.get("reporter_phone"))} · '
            f'描述：{(issue.get("description") or issue.get("title") or "")[:60]}'
        )
        with st.form(key=f"pa_audit_{iid}"):
            decision = st.radio("审核决定", ["✅ 通过", "↩️ 退回补充信息"], horizontal=True, key=f"pa_dec_{iid}")
            opinion = st.text_input("审核意见（退回必填；电话无法联系请退回要求补充有效联系方式）", key=f"pa_opinion_{iid}")
            aud_sub = st.form_submit_button("提交审核", width="stretch")
        if aud_sub:
            _do_audit(iid, decision, opinion)


def _render_issue_card(issue: dict):
    """主列表卡片：字段 + 详情（时间线、操作按钮按状态显示）。"""
    iid = issue["id"]
    status = issue.get("status", "")
    overdue, deadline_txt = _deadline_info(issue)
    overdue_html = (f'&nbsp;<span style="color:#ffffff;background:#dc2626;font-size:0.75em;'
                    f'font-weight:700;border-radius:99px;padding:2px 8px;">{deadline_txt}</span>'
                    if overdue else
                    f'&nbsp;<span style="color:#f97316;font-size:0.78em;">{deadline_txt}</span>'
                    if deadline_txt else "")
    card_bg = ' style="border:2px solid #dc2626;"' if overdue else ""
    with st.container(border=True):
        st.markdown(
            f'<div{card_bg}>'
            f'<span style="font-weight:700;color:{TOKEN["text"]};">#{iid} {issue.get("title","")[:40]}</span>'
            f'&nbsp;{_status_badge(status)}'
            + (f'&nbsp;{_URGENCY_EMOJI.get(issue.get("urgency",""), "")} {issue.get("urgency","")}' if issue.get("urgency") else "")
            + overdue_html
            + (f'&nbsp;<span style="color:#dc2626;font-size:0.78em;font-weight:600;">🚧 违规搭建</span>' if issue.get("is_violation") else "")
            + (f'&nbsp;<span style="color:#7c3aed;font-size:0.78em;font-weight:600;">非社区责任</span>' if issue.get("non_community_responsibility") else "")
            + (f'&nbsp;<span style="color:#b45309;font-size:0.78em;font-weight:600;">📝 有补充待确认</span>' if issue.get("supplement_pending") else "")
            + '</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f'{issue.get("issue_type", "")} · {issue.get("category", "")} · '
            f'📍 {issue.get("location") or "—"} · 🕐 {(issue.get("reported_at") or "")[:16]} · '
            f'报修人：{_mask_name(issue.get("reporter_name"))}'
        )
        with st.expander("📄 详情与操作", expanded=False):
            _render_detail(issue)


def _render_detail(issue: dict):
    iid = issue["id"]
    status = issue.get("status", "")
    phone = (issue.get("reporter_phone") or "").strip()

    st.markdown(f"**报修人**：{issue.get('reporter_name') or '—'} · **电话**：{_mask_phone(phone)}")
    st.markdown(f"**报修住址**：{issue.get('location') or '—'}")
    st.markdown(f"**分类**：{issue.get('issue_type', '—')} · **类别**：{issue.get('category', '—')} · **紧急程度**：{issue.get('urgency', '—')}")
    st.markdown(f"**问题描述**：{issue.get('description') or '—'}")
    if issue.get("is_agent_report"):
        st.markdown(
            f"**代报人**：{issue.get('agent_name') or '—'}（{issue.get('agent_relation') or ''}）"
            f" · 电话 {_mask_phone(issue.get('agent_phone'))}"
        )
    if issue.get("assignee_name"):
        st.markdown(f"**维修人员**：{issue['assignee_name']} · 电话 {_mask_phone(issue.get('assignee_phone'))}")
    if issue.get("approved_at"):
        st.markdown(f"**审核通过时间**：{(issue['approved_at'] or '')[:16]}")
    if issue.get("resolve_note"):
        st.markdown(f"**处理结果**：{issue['resolve_note']}")
    if issue.get("no_photo_reason"):
        st.markdown(f"**未上传照片原因**：{issue['no_photo_reason']}")
    try:
        from ui.pages.issues import _load_photos
        _pb = _load_photos(issue.get("photo_before"))
        _pa = _load_photos(issue.get("photo_after"))
        if _pb:
            st.markdown("**📷 现场照片**")
            st.image(_pb, width=160)
        if _pa:
            st.markdown("**📷 维修后照片**")
            st.image(_pa, width=160)
    except Exception:
        pass
    if issue.get("satisfaction"):
        st.markdown(f"**满意度**：{issue['satisfaction']}" + (f"（{issue.get('satisfaction_reason')}）" if issue.get("satisfaction_reason") else ""))

    # 查看完整手机号（二次确认 + 留痕）
    if phone:
        st.markdown("---")
        st.markdown("**查看完整手机号**（需二次确认并留痕）：")
        if st.button("👁️ 请求查看", key=f"m_phone_req_{iid}"):
            st.session_state[f"_phone_confirm_{iid}"] = True
            st.rerun()
        if st.session_state.get(f"_phone_confirm_{iid}") and not st.session_state.get(f"_phone_shown_{iid}"):
            st.caption(f"将记录留痕：{_actor} 查看工单 #{iid} 的报修人完整号码。")
            if st.button("✅ 二次确认并查看", key=f"m_phone_ok_{iid}"):
                log_activity(_actor, "查看完整手机号", "issue", iid,
                             module="报修", detail=f"查看工单 #{iid} 报修人完整号码 {phone}")
                st.session_state[f"_phone_shown_{iid}"] = True
                st.rerun()
        if st.session_state.get(f"_phone_shown_{iid}"):
            st.code(phone)

    # 完整留痕时间线（默认最近 3 条，可展开全部）
    st.markdown("---")
    st.markdown("**📜 完整留痕时间线**")
    timeline = get_issue_timeline(iid)
    if timeline:
        show_all = st.checkbox("展开全部留痕", key=f"m_tl_all_{iid}")
        shown = timeline if show_all else timeline[:3]
        for t in shown:
            before = t.get("before_value") or ""
            after = t.get("after_value") or ""
            trans = f"：{before} → {after}" if (before or after) else ""
            tail = f" — {t['detail']}" if t.get("detail") else ""
            st.caption(
                f"🕐 {(t.get('created_at') or '')[:16]} · {t.get('actor') or ''} · "
                f"{t.get('action')}{trans}{tail}"
            )
        if not show_all and len(timeline) > 3:
            st.caption(f"…共 {len(timeline)} 条留痕，勾选上方展开全部。")
    else:
        st.caption("暂无留痕记录")

    st.markdown("---")
    st.markdown("**🔧 操作**")

    # 1) 审核（待审核 / 退回补充信息）
    if status in ("待审核", "退回补充信息"):
        with st.form(key=f"m_audit_{iid}"):
            decision = st.radio("审核决定", ["✅ 通过", "↩️ 退回补充信息"], horizontal=True, key=f"m_dec_{iid}")
            opinion = st.text_input("审核意见（退回必填）", key=f"m_opinion_{iid}")
            aud_sub = st.form_submit_button("提交审核", width="stretch")
        if aud_sub:
            _do_audit(iid, decision, opinion)

    # 2) 分派 / 改派（已审核待派单 / 已派单 / 处理中）
    if status in ("已审核待派单", "已派单", "处理中"):
        is_reassign = status != "已审核待派单"
        with st.form(key=f"m_dispatch_{iid}"):
            st.markdown(f"**{'改派' if is_reassign else '分派维修人员'}**" + ("（处理中改派需二次确认）" if status == "处理中" else ""))
            aname = st.text_input("维修人员姓名", value=issue.get("assignee_name") or "", key=f"m_aname_{iid}")
            aphone = st.text_input("维修人员电话（手机号）", value=issue.get("assignee_phone") or "", key=f"m_aphone_{iid}")
            confirm = False
            reason = ""
            if status == "处理中":
                confirm = st.checkbox("二次确认：处理中改派，需记录原因并通知原维修人员取消任务", key=f"m_disp_confirm_{iid}")
                reason = st.text_input("改派原因", key=f"m_disp_reason_{iid}")
            disp_sub = st.form_submit_button("确认分派" if not is_reassign else "确认改派", width="stretch")
        if disp_sub:
            if not aname.strip():
                st.error("请填写维修人员姓名。")
            elif not _PHONE_RE.match(aphone.strip()):
                st.error("请输入正确的维修人员手机号。")
            elif status == "处理中" and not confirm:
                st.error("处理中改派需二次确认。")
            elif status == "处理中" and not reason.strip():
                st.error("处理中改派需填写改派原因。")
            else:
                ok, msg = dispatch_issue(iid, aname.strip(), aphone.strip(), actor=_actor)
                if ok:
                    st.success("分派/改派完成，状态已更新为「已派单」。")
                    invalidate_issues()
                    st.rerun()
                else:
                    st.error(msg)

    # 3) 开始处理（已派单 / 待协商）
    if status in ("已派单", "待协商"):
        if st.button("🔨 开始处理（状态 → 处理中）", key=f"m_start_{iid}", width="stretch"):
            ok, msg = start_process(iid, actor=_actor)
            if ok:
                st.success("已开始处理。")
                invalidate_issues()
                st.rerun()

    # 4) 处理中：继续原维修人员（R40，留痕记录选择，不触发改派）
    if status == "处理中" and issue.get("assignee_name"):
        if st.button(f"✅ 继续原维修人员（{issue['assignee_name']}）处理", key=f"m_keep_{iid}", width="stretch"):
            log_activity(_actor, "确认继续原维修人员", "issue", iid, issue.get("title", ""),
                         module="报修", detail=f"继续由 {issue['assignee_name']} 处理，不重新分派")
            st.success("已记录：继续原维修人员处理。")
            invalidate_issues()
            st.rerun()

    # 5) 修改分类（R27；已分派/处理中改分类 → 强制重新分派 R28）
    st.markdown("**🏷️ 修改分类**")
    cat_opts = ["公共设施", "环境卫生", "房屋维修", "水电燃气", "绿化养护", "其他"]
    cur_cat = issue.get("category") or ""
    cat_sel = st.selectbox("选择新分类", cat_opts,
                           index=cat_opts.index(cur_cat) if cur_cat in cat_opts else 0,
                           key=f"m_cat_{iid}")
    if st.button("保存分类修改", key=f"m_cat_save_{iid}", width="stretch"):
        ok, msg = db_update_category(iid, cat_sel, actor=_actor)
        if ok:
            st.success(msg)
            invalidate_issues()
            st.rerun()
        else:
            st.error(msg)

    # 6) 补充信息确认（R34/R35：居民补充后负责人确认，影响紧急程度则计时重算）
    if issue.get("supplement_pending"):
        st.markdown("**📝 待确认补充信息**")
        affects = st.checkbox("补充信息影响紧急程度/分类（确认后计时重新计算）", key=f"m_supp_affects_{iid}")
        if st.button("确认补充信息", key=f"m_supp_ok_{iid}", width="stretch"):
            ok, msg = db_confirm_supplement(iid, affects_timing=affects, actor=_actor)
            if ok:
                st.success(msg)
                invalidate_issues()
                st.rerun()
            else:
                st.error(msg)

    # 4) 填写处理结果（处理中）
    if status == "处理中":
        with st.form(key=f"m_resolve_{iid}"):
            note = st.text_area("处理结果（必填）", key=f"m_note_{iid}")
            photos = st.file_uploader("维修后照片（jpg/png，最多 3 张，选填）",
                                      type=["jpg", "png"], accept_multiple_files=True, key=f"m_photos_{iid}")
            no_photo_reason = st.text_input("未上传照片原因（未上传照片时必填）", key=f"m_nophoto_{iid}")
            res_sub = st.form_submit_button("提交处理结果（状态 → 待居民反馈）", width="stretch")
        if res_sub:
            photo_after = "[]"
            try:
                from utils.uploads import save_uploaded_files
                _saved, _errs = save_uploaded_files(photos, folder="issues")
                if _errs:
                    st.error("；".join(_errs))
                    return
                if _saved:
                    photo_after = json.dumps(_saved, ensure_ascii=False)
            except Exception:
                st.error("维修后照片上传失败，请重试。")
                return
            ok, msg = resolve_issue(iid, (note or "").strip(), photo_after=photo_after,
                                    no_photo_reason=(no_photo_reason or "").strip(), actor=_actor)
            if ok:
                st.success("处理结果已提交，等待居民反馈。")
                invalidate_issues()
                st.rerun()
            else:
                st.error(msg)

    # 5) 特殊情况：违规搭建转出（负责人手动批准；审核通过后）
    if issue.get("is_violation") and status in _ACTIVE and status != "待审核":
        st.markdown("---")
        st.warning("🚧 该工单标记为**违规搭建**，需负责人手动批准转出，转出后流程结束。")
        if st.button("🚧 转出（状态 → 已转出）", key=f"m_transfer_{iid}", width="stretch"):
            ok, msg = transfer_issue(iid, actor=_actor)
            if ok:
                st.success("已转出，工单流程结束。")
                invalidate_issues()
                st.rerun()
            else:
                st.error(msg)

    # 6) 特殊情况：室内费用协商 → 待协商（负责人触发）
    if issue.get("issue_type") == "室内" and status in ("已审核待派单", "已派单", "处理中", "待居民反馈"):
        st.markdown("---")
        st.markdown("**室内维修费用协商**：居民不同意收费时转「待协商」。")
        with st.form(key=f"m_negotiate_{iid}"):
            neg_reason = st.text_input("协商原因（必填）", key=f"m_neg_reason_{iid}")
            neg_sub = st.form_submit_button("转待协商", width="stretch")
        if neg_sub:
            if not neg_reason.strip():
                st.error("协商原因必填。")
            else:
                ok, msg = negotiate_issue(iid, neg_reason.strip(), actor=_actor)
                if ok:
                    st.success("已转待协商。")
                    invalidate_issues()
                    st.rerun()
                else:
                    st.error(msg)

    # 7) 特殊情况：关闭（二次确认；仅特殊原因）
    if status in _ACTIVE and status != "待审核":
        st.markdown("---")
        st.markdown("**特殊关闭**（需二次确认；仅限：居民放弃维修、工单重复且已处理、工单无效等）")
        with st.form(key=f"m_close_{iid}"):
            close_reason = st.text_input("关闭原因（必填）", key=f"m_close_reason_{iid}")
            close_confirm = st.checkbox("二次确认：关闭后将通知居民并说明原因", key=f"m_close_confirm_{iid}")
            close_sub = st.form_submit_button("确认关闭", width="stretch")
        if close_sub:
            if not close_reason.strip():
                st.error("关闭原因必填。")
            elif not close_confirm:
                st.error("关闭需二次确认。")
            else:
                ok, msg = close_issue(iid, close_reason.strip(), actor=_actor)
                if ok:
                    st.success("工单已关闭，居民将收到通知。")
                    invalidate_issues()
                    st.rerun()
                else:
                    st.error(msg)

    if status in _TERMINAL:
        st.caption("该工单已处于终态，无更多操作。")


# ================= 页面主体 =================

# ---------- 筛选 ----------
f1, f2, f3 = st.columns(3)
with f1:
    status_choice = st.selectbox("状态筛选", ["全部"] + STATUS_ALL, key="mgmt_status")
with f2:
    type_choice = st.selectbox("分类", ["全部", "室外", "室内"], key="mgmt_type")
with f3:
    urg_choice = st.selectbox("紧急程度", ["全部", "紧急", "中等", "一般", "普通"], key="mgmt_urgency")
f4, f5 = st.columns(2)
with f4:
    period_choice = st.selectbox("时间范围", ["全部", "近7天", "近30天"], key="mgmt_period")
with f5:
    st.caption("按提交时间过滤")
search = st.text_input("🔍 搜索标题 / 描述 / 地址", key="mgmt_search", placeholder="输入关键词…")

issues = get_issues(
    status=None if status_choice == "全部" else status_choice,
    issue_type=None if type_choice == "全部" else type_choice,
    limit=300,
)
if urg_choice != "全部":
    issues = [i for i in issues if i.get("urgency") == urg_choice]
if period_choice != "全部":
    from datetime import timedelta
    _cut = (datetime.now() - timedelta(days={"近7天": 7, "近30天": 30}[period_choice])).strftime("%Y-%m-%d %H:%M:%S")
    issues = [i for i in issues if (i.get("reported_at") or "") >= _cut]
if search:
    kw = search.lower()
    issues = [
        i for i in issues
        if kw in (i.get("title") or "").lower()
        or kw in (i.get("description") or "").lower()
        or kw in (i.get("location") or "").lower()
    ]
# 紧急优先，再按 id 新的在前
_URG_PRIO = {"紧急": 0, "中等": 1, "一般": 2, "普通": 3}
issues.sort(key=lambda x: (_URG_PRIO.get(x.get("urgency", ""), 9), -(x.get("id") or 0)))

# ---------- 导出 CSV（字段按文档第七节，电话脱敏，不含照片附件） ----------
if issues:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["工单号", "报修人姓名", "电话", "报修住址", "分类", "紧急程度",
                     "问题描述摘要", "提交时间", "状态", "审核通过时间", "维修人员", "处理结果"])
    for i in issues:
        writer.writerow([
            i.get("id"), _mask_name(i.get("reporter_name")), _mask_phone(i.get("reporter_phone")),
            i.get("location"), i.get("issue_type", ""), i.get("urgency", ""),
            (i.get("title") or "")[:50], (i.get("reported_at") or "")[:16],
            i.get("status", ""), (i.get("approved_at") or "")[:16] or "",
            i.get("assignee_name", ""), i.get("resolve_note", ""),
        ])
    def _log_issue_export():
        """导出动作留痕（spec 十）。"""
        from data.db_notifications import log_activity
        log_activity("负责人", "导出工单数据", "issue", module="报修", detail="导出工单 CSV（电话脱敏，不含照片）")

    st.download_button(
        "📥 导出工单数据（CSV）",
        buf.getvalue(),
        file_name=f"工单导出_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        on_click=_log_issue_export,
    )

st.markdown("---")

# ---------- 待审核队列 ----------
pending = get_pending_review_issues(limit=100)
with st.expander(f"⏳ 待审核队列（含退回待补 · {len(pending)} 条）", expanded=True):
    if not pending:
        st.caption("暂无待审核工单。")
    for iss in pending:
        _render_audit_card(iss)

st.markdown("---")

# ---------- 工单列表 ----------
st.caption(
    f"共 {len(issues)} 条工单"
    + (f" · 当前筛选：{status_choice} / {type_choice} / {urg_choice}"
       if status_choice != "全部" or type_choice != "全部" or urg_choice != "全部" else "")
)
if not issues:
    st.info("暂无匹配的工单。")
else:
    for issue in issues:
        _render_issue_card(issue)
