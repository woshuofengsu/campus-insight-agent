"""🏥 疾病预防管理（负责人端）— 内容发布审核、居民健康咨询、天气联动、阈值配置。

按《04-疾病预防.md》第七节负责人后台标准输出实现：
1. 内容管理：创建（来源/审核人必填）、编辑（草稿/审核不通过）、提交审核、撤回、
   审核通过/不通过（不通过必填意见）、删除草稿、置顶/取消置顶、下架（原因必填+二次确认）；
2. 咨询管理：列表（编号、脱敏昵称、脱敏电话、类型、时间、状态颜色、回复时限倒计时）、
   回复（回复建议必填 + "请勿进行疾病诊断"提示留痕 + 需线下就医二次确认）、
   超时自动标记（24 小时未回复）；
3. 联动记录：触发/关闭/永久关闭/重新开启/阈值调整（来自留痕），修改记录默认折叠；
4. 阈值配置：高温/低温/24 小时降温阈值，仅疾病预防负责人可调，调整即留痕。
"""
import json
import logging
from datetime import datetime

import streamlit as st

from ui.guard import require_role

require_role("grid")

from ui.components import TOKEN, page_header, section, stat  # noqa: E402
from data.db_user import list_users  # noqa: E402
from data.db_health_content import (  # noqa: E402  数据层，只调用不写 SQL
    CONTENT_TYPES,
    CONSULT_TYPES,
    WEATHER_LINK_KEYS,
    NO_DIAGNOSIS_HINT,
    REPLY_HOURS,
    create_content,
    update_content,
    submit_for_review,
    withdraw_submission,
    review_content,
    delete_draft,
    set_pinned,
    take_down_content,
    list_contents,
    list_consults,
    export_contents_csv,
    export_consults_csv,
    reply_consult,
    mark_overdue_consults,
    log_diagnosis_disclaimer_shown,
    get_linkage_records,
    get_linkage_thresholds,
    set_linkage_thresholds,
    close_linkage,
    reopen_linkage,
    is_disease_prevention_manager,
    mask_phone,
)
from data.db_core import get_db  # noqa: E402

_log = logging.getLogger(__name__)

page_header("🏥 疾病预防管理", "健康内容发布与审核 · 居民健康咨询处理 · 天气联动与阈值配置。")

_memory = st.session_state.get("memory")
_profile = _memory.get_user_profile() if _memory is not None else (st.session_state.get("user_profile") or {})
_actor = (_profile.get("name") or "").strip() or "负责人"
_uid = _profile.get("id") or 0
_is_dpm = is_disease_prevention_manager(_profile)  # 疾病预防负责人（含自动成为咨询处理人）

# 状态颜色（《04-疾病预防.md》：咨询 待回复/超时未回复红黄、已回复/继续回复蓝、结束/关闭灰）
_CONTENT_COLORS = {
    "草稿": "#64748b", "待审核": "#d97706", "审核通过": "#2563eb",
    "审核不通过": "#dc2626", "已发布": "#059669", "已下架": "#64748b",
}
_CONSULT_COLORS = {
    "待回复": "#d97706", "超时未回复": "#dc2626", "已回复": "#2563eb",
    "继续回复": "#2563eb", "已结束": "#64748b", "已关闭": "#64748b", "已撤回": "#64748b",
}


def _badge(status: str, colors: dict) -> str:
    color = colors.get(status, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}1a;border:1px solid {color};'
        f'color:{color};border-radius:999px;padding:1px 10px;font-size:0.78em;'
        f'font-weight:600;white-space:nowrap;">{status}</span>'
    )


def _type_pill(content_type: str) -> str:
    return (
        f'<span style="display:inline-block;background:{TOKEN["accent_bg"]};'
        f'color:{TOKEN["accent"]};border:1px solid {TOKEN["accent_border"]};'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 10px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">{content_type}</span>'
    )


def _pinned_badge() -> str:
    return (
        f'<span style="display:inline-block;background:{TOKEN["warning_bg"]};'
        f'color:{TOKEN["warning"]};border:1px solid {TOKEN["warning_border"]};'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">📌 置顶</span>'
    )


def _mask_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return "—"
    if len(name) == 1:
        return f"{name}**"
    return f"{name[0]}{'*' * (len(name) - 1)}"


def _grid_users() -> list[dict]:
    try:
        return list_users(role="grid")
    except Exception:
        _log.debug("读取负责人名单失败", exc_info=True)
        return []


def _user_label(u: dict) -> str:
    return (u.get("name") or u.get("username") or f"负责人#{u.get('id')}").strip()


def _consult_remaining(c: dict) -> str:
    """回复时限倒计时（待回复按创建时间、继续回复按 feedback_at 重新计时）。"""
    if c.get("status") not in ("待回复", "继续回复"):
        return ""
    base = (c.get("feedback_at") if c.get("status") == "继续回复" else None) or c.get("created_at") or ""
    try:
        base_dt = datetime.strptime(str(base), "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ""
    remaining = REPLY_HOURS - (datetime.utcnow() - base_dt).total_seconds() / 3600.0
    if remaining < 0:
        return f'<span style="color:{TOKEN["danger"]};">已超时 {abs(remaining):.1f} 小时</span>'
    color = TOKEN["danger"] if remaining < 1 else TOKEN["success"]
    return f'<span style="color:{color};">剩余 {remaining:.1f} 小时</span>'


# 咨询超时自动标记（24 小时未回复 → 超时未回复，幂等留痕）
try:
    mark_overdue_consults()
except Exception:
    _log.debug("咨询超时标记失败", exc_info=True)

t_content, t_consult, t_linkage, t_threshold = st.tabs(
    ["📄 内容管理", "💬 咨询管理", "☁️ 天气联动", "🎚️ 阈值配置"]
)

# ============================================================
# Tab 1：内容管理
# ============================================================
with t_content:
    all_contents = list_contents(limit=200)
    stat_c1, stat_c2, stat_c3 = st.columns(3)
    with stat_c1:
        stat("全部内容", str(len(all_contents)), TOKEN["accent"], sub="含草稿与已发布")
    with stat_c2:
        stat("待审核", str(len([x for x in all_contents if x.get("status") == "待审核"])), TOKEN["warning"],
             sub="需要审核人处理")
    with stat_c3:
        stat("已发布", str(len([x for x in all_contents if x.get("status") == "已发布"])), TOKEN["success"],
             sub="居民端可见")
    csv_data, csv_name = export_contents_csv()
    st.download_button("📥 导出内容列表（CSV）", data=csv_data, file_name=csv_name, mime="text/csv",
                       key="hc_export_contents")

    with st.expander("➕ 创建健康内容（草稿）", expanded=False):
        with st.form("content_create_form"):
            n_title = st.text_input("标题（必填，最长 50 字）", key="cc_title")
            n_type = st.selectbox("内容类型（必填）", CONTENT_TYPES, key="cc_type")
            n_body = st.text_area("正文内容（必填，最长 5000 字）", height=140, key="cc_body")
            n_source = st.text_input("内容来源（必填，如：国家疾控中心 / 省卫健委 / 社区自编）",
                                     placeholder="社区自编内容将自动标注免责声明", key="cc_source")
            auditor_options = _grid_users()
            auditor_names = [_user_label(u) for u in auditor_options] if auditor_options else []
            n_auditor = st.selectbox("审核人（必填，不能与发布人相同）", ["（选择审核人）"] + auditor_names,
                                     key="cc_auditor")
            n_pinned = st.checkbox("置顶（每个内容类型最多置顶 1 条）", key="cc_pinned")
            n_links = st.multiselect("联动天气（选填，多选）", WEATHER_LINK_KEYS, key="cc_links")
            n_elderly = st.text_input("老年端提醒文案（联动天气时必填，口语化，最多 30 字）", key="cc_elderly")
            d1, d2 = st.columns(2)
            with d1:
                n_info_dt = st.date_input("信息更新时间（疫苗接种提醒类必填）", value=None,
                                          key="cc_info_dt", format="YYYY-MM-DD")
            with d2:
                n_expire_dt = st.date_input("信息有效期（疫苗接种提醒类必填，过期自动下架）", value=None,
                                            key="cc_expire_dt", format="YYYY-MM-DD")
            created = st.form_submit_button("🚀 创建草稿", type="primary", width="stretch")
        if created:
            auditor = ""
            if n_auditor != "（选择审核人）" and n_auditor in auditor_names:
                idx = auditor_names.index(n_auditor)
                chosen = auditor_options[idx]
                auditor = (chosen.get("name") or chosen.get("username") or "").strip()
            cid, msg = create_content(
                n_title, n_type, n_body, n_source.strip() or "社区自编", _actor,
                auditor=auditor,
                weather_link=n_links,
                elderly_reminder_text=(n_elderly or "").strip(),
                info_updated_at=str(n_info_dt) if n_info_dt else "",
                expire_at=str(n_expire_dt) if n_expire_dt else "",
                is_pinned=1 if n_pinned else 0,
            )
            if cid:
                st.toast(f"草稿 #{cid} 已创建，填写审核人后可提交审核", icon="✅")
                st.rerun()
            else:
                st.error(msg)

    st.markdown("---")

    f1, f2, f3 = st.columns(3)
    with f1:
        c_status = st.selectbox("状态筛选", ["全部"] + ["草稿", "待审核", "审核通过", "审核不通过", "已发布", "已下架"],
                                key="content_status_filter")
    with f2:
        c_type_f = st.selectbox("类型筛选", ["全部"] + CONTENT_TYPES, key="content_type_filter")
    with f3:
        c_kw = st.text_input("关键词（标题/正文）", key="content_kw_filter")

    contents = list_contents(
        status=None if c_status == "全部" else c_status,
        content_type=None if c_type_f == "全部" else c_type_f,
        keyword=(c_kw or "").strip() or None,
        limit=100,
    )
    if not contents:
        st.caption("暂无符合条件的内容。")
    else:
        for c in contents:
            cid = c["id"]
            cstatus = c.get("status", "")
            with st.container(border=True):
                st.markdown(
                    f'<span style="font-weight:700;color:{TOKEN["text"]};">#{cid} {c.get("title","")[:40]}</span>'
                    + (f'&nbsp;{_pinned_badge()}' if c.get("is_pinned") else "")
                    + f'&nbsp;{_type_pill(c.get("content_type",""))}'
                    + f'&nbsp;{_badge(cstatus, _CONTENT_COLORS)}',
                    unsafe_allow_html=True,
                )
                st.caption(
                    f'来源：{c.get("source") or "—"} · 发布人：{c.get("publisher") or "—"} · '
                    f'审核人：{c.get("auditor") or "—"} · 创建：{(c.get("created_at") or "")[:16]}'
                    + (f' · 发布：{(c.get("published_at") or "")[:16]}' if c.get("published_at") else "")
                    + (f' · 有效期至：{c.get("expire_at")}' if c.get("expire_at") else "")
                    + (f' · 联动：{"、".join(c.get("weather_link") or [])}' if c.get("weather_link") else "")
                )
                if c.get("audit_opinion"):
                    st.caption(f'📝 审核意见：{c.get("audit_opinion")}')

                # ---- 操作区（按状态） ----
                if cstatus in ("草稿", "审核不通过"):
                    with st.expander("✏️ 编辑内容", expanded=False):
                        with st.form(key=f"content_edit_{cid}"):
                            e_title = st.text_input("标题", value=c.get("title", ""), key=f"ce_title_{cid}")
                            e_type = st.selectbox("内容类型", CONTENT_TYPES,
                                                  index=CONTENT_TYPES.index(c.get("content_type", CONTENT_TYPES[0])),
                                                  key=f"ce_type_{cid}")
                            e_body = st.text_area("正文", value=c.get("body", ""), height=120, key=f"ce_body_{cid}")
                            e_source = st.text_input("内容来源", value=c.get("source", ""), key=f"ce_source_{cid}")
                            e_links = st.multiselect("联动天气", WEATHER_LINK_KEYS,
                                                     default=c.get("weather_link") or [], key=f"ce_links_{cid}")
                            e_elderly = st.text_input("老年端提醒文案", value=c.get("elderly_reminder_text") or "",
                                                      key=f"ce_elderly_{cid}")
                            e_saved = st.form_submit_button("保存修改", width="stretch")
                        if e_saved:
                            ok, msg = update_content(
                                cid, _actor, title=e_title, content_type=e_type, body=e_body,
                                source=e_source, weather_link=e_links,
                                elderly_reminder_text=e_elderly,
                            )
                            if ok:
                                st.toast(f"内容 #{cid} 已保存", icon="✅")
                                st.rerun()
                            else:
                                st.error(msg)

                act_cols = st.columns(6)
                # 提交审核（草稿/审核不通过）
                if cstatus in ("草稿", "审核不通过"):
                    with act_cols[0]:
                        if st.button("📤 提交审核", key=f"c_submit_{cid}", width="stretch"):
                            ok, msg = submit_for_review(cid, auditor=c.get("auditor") or "", actor=_actor)
                            if ok:
                                st.toast(f"内容 #{cid} 已提交审核", icon="📤")
                                st.rerun()
                            else:
                                st.error(msg)
                # 待审核：撤回 / 审核
                if cstatus == "待审核":
                    with act_cols[0]:
                        if st.button("↩️ 撤回", key=f"c_withdraw_{cid}", width="stretch"):
                            ok, msg = withdraw_submission(cid, actor=_actor)
                            if ok:
                                st.toast("已撤回为草稿", icon="↩️")
                                st.rerun()
                            else:
                                st.error(msg)
                    with act_cols[1]:
                        if st.button("✅ 审核通过", key=f"c_approve_{cid}", width="stretch"):
                            ok, msg = review_content(cid, approve=True, actor=_actor)
                            if ok:
                                st.toast(f"内容 #{cid} 审核通过并发布", icon="✅")
                                st.rerun()
                            else:
                                st.error(msg)
                    with act_cols[2]:
                        if st.button("❌ 审核不通过", key=f"c_reject_{cid}", width="stretch"):
                            st.session_state[f"_content_reject_{cid}"] = True
                            st.rerun()
                    if st.session_state.get(f"_content_reject_{cid}"):
                        with st.form(key=f"content_reject_{cid}"):
                            opinion = st.text_input("审核意见（审核不通过必填）", key=f"c_opinion_{cid}")
                            rejected = st.form_submit_button("确认审核不通过", width="stretch")
                        if rejected:
                            ok, msg = review_content(cid, approve=False, opinion=opinion or "", actor=_actor)
                            if ok:
                                st.session_state.pop(f"_content_reject_{cid}", None)
                                st.toast(f"内容 #{cid} 已退回（审核不通过）", icon="❌")
                                st.rerun()
                            else:
                                st.error(msg)
                    st.caption(f"仅审核人 {c.get('auditor') or '—'} 可审核（原审核人重新审核）")
                # 已发布：下架 / 置顶切换
                if cstatus == "已发布":
                    with act_cols[0]:
                        if c.get("is_pinned"):
                            if st.button("📌 取消置顶", key=f"c_unpin_{cid}", width="stretch"):
                                ok, msg = set_pinned(cid, False, actor=_actor)
                                if ok:
                                    st.toast("已取消置顶", icon="📌")
                                    st.rerun()
                                else:
                                    st.error(msg)
                        else:
                            if st.button("📌 置顶", key=f"c_pin_{cid}", width="stretch"):
                                ok, msg = set_pinned(cid, True, actor=_actor)
                                if ok:
                                    st.toast("已置顶", icon="📌")
                                    st.rerun()
                                else:
                                    st.error(msg)
                    with act_cols[1]:
                        if st.button("⤵️ 下架", key=f"c_down_{cid}", width="stretch"):
                            st.session_state[f"_content_down_{cid}"] = True
                            st.rerun()
                    if st.session_state.get(f"_content_down_{cid}"):
                        with st.form(key=f"content_down_{cid}"):
                            reason = st.text_input("下架原因（必填）", key=f"c_down_reason_{cid}")
                            confirm = st.checkbox("二次确认：下架后居民端不再显示，后台保留留痕", key=f"c_down_confirm_{cid}")
                            downed = st.form_submit_button("确认下架", width="stretch")
                        if downed:
                            ok, msg = take_down_content(cid, reason or "", confirm=confirm, actor=_actor)
                            if ok:
                                st.session_state.pop(f"_content_down_{cid}", None)
                                st.toast(f"内容 #{cid} 已下架", icon="⤵️")
                                st.rerun()
                            else:
                                st.error(msg)
                # 草稿：删除
                if cstatus == "草稿":
                    with act_cols[3]:
                        if st.button("🗑️ 删除草稿", key=f"c_del_{cid}", width="stretch"):
                            ok, msg = delete_draft(cid, actor=_actor)
                            if ok:
                                st.toast(f"草稿 #{cid} 已删除", icon="🗑️")
                                st.rerun()
                            else:
                                st.error(msg)

# ============================================================
# Tab 2：咨询管理
# ============================================================
with t_consult:
    consults = list_consults(limit=200)
    cs1, cs2, cs3 = st.columns(3)
    with cs1:
        stat("待回复", str(len([x for x in consults if x.get("status") == "待回复"])), TOKEN["warning"], sub="24小时内回复")
    with cs2:
        stat("超时未回复", str(len([x for x in consults if x.get("status") == "超时未回复"])), TOKEN["danger"],
             sub="已标记并再次提醒")
    with cs3:
        stat("已回复/继续", str(len([x for x in consults if x.get("status") in ("已回复", "继续回复")])),
             TOKEN["info"], sub="待居民反馈")

    csv_data2, csv_name2 = export_consults_csv()
    st.download_button("📥 导出咨询列表（CSV，脱敏）", data=csv_data2, file_name=csv_name2, mime="text/csv",
                       key="hc_export_consults")

    k1, k2, k3 = st.columns(3)
    with k1:
        q_status = st.selectbox("状态筛选", ["全部"] + ["待回复", "已回复", "继续回复", "超时未回复", "已结束", "已关闭", "已撤回"],
                                key="consult_status_filter")
    with k2:
        q_type = st.selectbox("类型筛选", ["全部"] + CONSULT_TYPES, key="consult_type_filter")
    with k3:
        q_kw = st.text_input("关键词搜索（昵称/电话/内容）", key="consult_kw_filter")

    consults = list_consults(
        status=None if q_status == "全部" else q_status,
        consult_type=None if q_type == "全部" else q_type,
        keyword=(q_kw or "").strip() or None,
        limit=100,
    )
    if not consults:
        st.caption("暂无符合条件的咨询。")
    else:
        for c in consults:
            cid = c["id"]
            cstatus = c.get("status", "")
            with st.container(border=True):
                st.markdown(
                    f'<span style="font-weight:700;color:{TOKEN["text"]};">{c.get("code","")}</span>'
                    f'&nbsp;{_type_pill(c.get("consult_type",""))}&nbsp;{_badge(cstatus, _CONSULT_COLORS)}'
                    f'&nbsp;<span style="font-size:0.85em;color:{TOKEN["text_sec"]};">'
                    f'{_mask_name(c.get("name"))} · {c.get("phone_masked") or mask_phone(c.get("phone",""))}'
                    f' · {(c.get("created_at") or "")[:16]}</span>',
                    unsafe_allow_html=True,
                )
                # 电话可点击拨打（spec：负责人端联系电话可直接拨打）
                _pnum = (c.get("phone") or "").strip()
                if len(_pnum) == 11:
                    st.markdown(
                        f'<a href="tel:{_pnum}" style="color:{TOKEN["accent"]};text-decoration:none;'
                        f'font-size:0.85em;">📞 拨打 {_pnum[:3]}****{_pnum[-4:]}</a>',
                        unsafe_allow_html=True,
                    )
                st.markdown(f'<span style="font-size:0.85em;color:{TOKEN["text"]};">{_consult_remaining(c)}</span>',
                            unsafe_allow_html=True)
                # 列表不直接展示内容和附件（《04-疾病预防.md》）
                with st.expander("🔍 查看详情 / 回复", expanded=False):
                    st.markdown(f'**咨询内容：**\n\n{c.get("content","")}')
                    if c.get("building"):
                        st.caption(f'楼栋：{c.get("building")}')
                    if c.get("is_agent_report"):
                        st.caption(f'代报：{c.get("agent_name")}（{c.get("agent_relation") or "关系未填"}）')
                    # 状态流转留痕（spec：咨询全程留痕可查）
                    try:
                        with get_db() as _conn:
                            _acts = _conn.execute(
                                "SELECT actor, action, created_at, detail FROM activity_log "
                                "WHERE module='疾病预防' AND target_type='health_consult' AND target_id=? "
                                "ORDER BY id DESC LIMIT 10",
                                (cid,),
                            ).fetchall()
                        if _acts:
                            st.markdown("**📜 处理留痕**")
                            for _a in _acts:
                                st.caption(
                                    f"{(str(_a['created_at']) or '')[:16]} · {_a['actor'] or ''} · "
                                    f"{_a['action'] or ''}"
                                    + (f" · {(str(_a['detail']) or '')[:60]}" if _a.get("detail") else "")
                                )
                    except Exception:
                        pass
                    try:
                        atts = json.loads(c.get("attachment_json") or "[]")
                    except (ValueError, TypeError):
                        atts = []
                    if atts:
                        from utils.uploads import resolve_path
                        _imgs = [x for x in (resolve_path(x) for x in atts) if x]
                        if _imgs:
                            st.markdown("**📎 附件图片**（仅处理人和咨询人本人可见）")
                            st.image(_imgs, width=140)
                        else:
                            st.caption(f'📎 附件 {len(atts)} 张（仅处理人和咨询人本人可见）')
                    if c.get("reply"):
                        reply_display = c.get("reply", "")
                        if c.get("reply_need_offline"):
                            reply_display = "【建议尽快线下就医】" + reply_display
                        st.markdown(
                            f'<div style="background:{TOKEN["accent_bg"]};border:1px solid {TOKEN["accent_border"]};'
                            f'border-radius:8px;padding:8px 12px;">'
                            f'<div style="font-size:0.8em;font-weight:700;color:{TOKEN["accent"]};">'
                            f'💬 已回复（{(c.get("reply_at") or "")[:16]}）</div>'
                            f'<div style="font-size:0.86em;color:{TOKEN["text"]};">{reply_display}</div>'
                            + (f'<div style="font-size:0.8em;color:{TOKEN["text_sec"]};">就医指引：{c.get("reply_doctor_guide")}</div>'
                               if c.get("reply_doctor_guide") else "")
                            + f'</div>',
                            unsafe_allow_html=True,
                        )
                    if c.get("feedback"):
                        st.caption(f'居民反馈：{c.get("feedback")}'
                                   + (f'（原因：{c.get("feedback_reason")}）' if c.get("feedback_reason") else ""))

                    # 回复表单（仅 待回复/继续回复/超时未回复）
                    if cstatus in ("待回复", "继续回复", "超时未回复"):
                        if not st.session_state.get(f"_diag_logged_{cid}"):
                            try:
                                log_diagnosis_disclaimer_shown(cid)
                                st.session_state[f"_diag_logged_{cid}"] = True
                            except Exception:
                                _log.debug("非诊断提示留痕失败", exc_info=True)
                        with st.form(key=f"consult_reply_{cid}"):
                            st.caption(f'⚠️ {NO_DIAGNOSIS_HINT}（提示已留痕）')
                            r_text = st.text_area("回复建议（必填）", key=f"cr_text_{cid}", height=100)
                            r_guide = st.text_input("就医指引（选填：医院科室、地址、注意事项）", key=f"cr_guide_{cid}")
                            r_offline = st.checkbox("判断需线下就医", key=f"cr_off_{cid}")
                            r_offline_confirm = False
                            if r_offline:
                                r_offline_confirm = st.checkbox(
                                    "二次确认：在回复中置顶显示「建议尽快线下就医」", key=f"cr_offc_{cid}")
                            r_sub = st.form_submit_button("💬 提交回复", width="stretch")
                        if r_sub:
                            ok, msg = reply_consult(
                                cid, r_text, actor=_actor, doctor_guide=(r_guide or "").strip(),
                                need_offline=r_offline, offline_confirmed=r_offline_confirm,
                            )
                            if ok:
                                st.toast(f"咨询 {c.get('code','')} 已回复", icon="💬")
                                st.rerun()
                            else:
                                st.error(msg)

# ============================================================
# Tab 3：天气联动
# ============================================================
with t_linkage:
    if not _is_dpm:
        st.info("仅「疾病预防负责人」角色可关闭/修改联动提醒；当前账号仅可查看联动记录。")

    section("📡 联动提醒记录")
    records = get_linkage_records(limit=50)
    if not records:
        st.caption("暂无联动提醒记录。")
    else:
        rows = []
        for r in records:
            rows.append({
                "时间": (r.get("created_at") or "")[:16],
                "操作人": r.get("actor") or "系统",
                "操作": r.get("action", ""),
                "关联内容": (r.get("target_title") or "")[:30],
                "详情": (r.get("detail") or "")[:60],
                "状态": r.get("after_value") or r.get("before_value") or "—",
            })
        st.dataframe(rows, width="stretch", hide_index=True)
        with st.expander("📜 修改记录明细（默认折叠）"):
            for r in records[:20]:
                st.markdown(
                    f'<span style="font-size:0.82em;color:{TOKEN["text_sec"]};">'
                    f'[{ (r.get("created_at") or "")[:16] }] {r.get("actor") or "系统"} · '
                    f'{r.get("action","")} · {r.get("detail","")}</span>',
                    unsafe_allow_html=True,
                )

    st.markdown("---")
    section("🔛 联动开关管理")

    # 从留痕推断每个联动键当前状态（永久关闭后未重新开启 → 已永久关闭）
    def _linkage_key_status(key: str) -> str:
        perm = False
        for r in records:
            if r.get("action") == "永久关闭联动" and r.get("detail") == key:
                perm = True
            elif r.get("action") == "重新开启联动" and r.get("detail") == key:
                if perm:
                    perm = False
        return "已永久关闭" if perm else "开启中"

    for key in WEATHER_LINK_KEYS:
        status = _linkage_key_status(key)
        with st.container(border=True):
            ck1, ck2 = st.columns([3, 2])
            with ck1:
                st.markdown(
                    f'<span style="font-weight:700;color:{TOKEN["text"]};">{key}联动</span>'
                    f'&nbsp;<span style="font-size:0.82em;color:{TOKEN["success"] if status == "开启中" else TOKEN["text_muted"]};">'
                    f'（{status}）</span>',
                    unsafe_allow_html=True,
                )
            with ck2:
                if _is_dpm:
                    if status == "已永久关闭":
                        if st.button(f"🔓 重新开启「{key}」", key=f"lk_reopen_{key}", width="stretch"):
                            st.session_state[f"_lk_reopen_confirm_{key}"] = True
                            st.rerun()
                        if st.session_state.get(f"_lk_reopen_confirm_{key}"):
                            with st.form(key=f"lk_reopen_form_{key}"):
                                rc = st.checkbox("二次确认：重新开启该天气联动", key=f"lk_reopen_c_{key}")
                                reopened = st.form_submit_button("确认重新开启", width="stretch")
                            if reopened:
                                ok, msg = reopen_linkage(key, actor=_actor, confirm=rc)
                                if ok:
                                    st.session_state.pop(f"_lk_reopen_confirm_{key}", None)
                                    st.toast(f"「{key}」联动已重新开启", icon="🔓")
                                    st.rerun()
                                else:
                                    st.error(msg)
                    else:
                        if st.button(f"✕ 关闭「{key}」", key=f"lk_close_{key}", width="stretch"):
                            st.session_state[f"_lk_close_confirm_{key}"] = True
                            st.rerun()
                        if st.session_state.get(f"_lk_close_confirm_{key}"):
                            with st.form(key=f"lk_close_form_{key}"):
                                reason = st.text_input("关闭原因（必填）", key=f"lk_close_reason_{key}")
                                c_mode = st.radio("关闭方式", ["临时关闭（同一天气事件内不再触发）", "永久关闭（需重新开启后才能再次触发）"],
                                                  key=f"lk_close_mode_{key}")
                                cc = st.checkbox("二次确认：关闭联动并留痕", key=f"lk_close_c_{key}")
                                closed = st.form_submit_button("确认关闭", width="stretch")
                            if closed:
                                permanent = "永久关闭" in c_mode
                                ok, msg = close_linkage(key, reason or "", actor=_actor,
                                                        permanent=permanent, confirm=cc)
                                if ok:
                                    st.session_state.pop(f"_lk_close_confirm_{key}", None)
                                    st.toast(f"「{key}」联动已关闭", icon="✕")
                                    st.rerun()
                                else:
                                    st.error(msg)
                else:
                    st.caption("仅疾病预防负责人可操作")

# ============================================================
# Tab 4：阈值配置
# ============================================================
with t_threshold:
    section("🎚️ 气温联动阈值")
    thresholds = get_linkage_thresholds()
    st.caption("触发条件：高温（当日最高温 ≥ 高温阈值℃）；天气转冷（当日最低温 ≤ 低温阈值℃ 或 24 小时降温 ≥ 降温阈值℃）。"
               "调整后立即生效并留痕，不需二次确认（仅疾病预防负责人可操作）。")

    if not _is_dpm:
        st.info("仅「疾病预防负责人」角色可调整联动阈值。")
        st.markdown(
            f'- 高温阈值：**{thresholds.get("high_temp")}℃**\n'
            f'- 低温阈值：**{thresholds.get("low_temp")}℃**\n'
            f'- 24 小时降温阈值：**{thresholds.get("temp_drop")}℃**'
        )
    else:
        with st.form("threshold_form"):
            th1, th2, th3 = st.columns(3)
            with th1:
                v_high = st.number_input("高温阈值（℃）", value=int(thresholds.get("high_temp", 35)),
                                         min_value=30, max_value=45, step=1, key="th_high")
            with th2:
                v_low = st.number_input("低温阈值（℃）", value=int(thresholds.get("low_temp", 5)),
                                        min_value=-10, max_value=10, step=1, key="th_low")
            with th3:
                v_drop = st.number_input("24 小时降温阈值（℃）", value=int(thresholds.get("temp_drop", 8)),
                                         min_value=3, max_value=20, step=1, key="th_drop")
            saved = st.form_submit_button("💾 保存阈值（立即生效并留痕）", type="primary", width="stretch")
        if saved:
            new_th = set_linkage_thresholds(high_temp=int(v_high), low_temp=int(v_low),
                                            temp_drop=int(v_drop), actor=_actor)
            st.toast(f"阈值已更新：高温 {new_th['high_temp']}℃ / 低温 {new_th['low_temp']}℃ / "
                     f"降温 {new_th['temp_drop']}℃（已留痕）", icon="💾")
            st.rerun()
