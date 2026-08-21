"""🔧 接诉即办 · 报修 — 居民端报修工单页：提交、我的工单、详情时间线、反馈、补充、撤回、草稿。"""
import re
import logging
import streamlit as st

from data.db_repair import (
    submit_issue, create_draft, get_drafts, delete_draft,
    get_issues, get_issue_timeline,
    feedback_issue, supplement_issue, withdraw_issue, reopen_issue, resubmit_issue, edit_issue,
)
from tools.action_report_issue import _llm_classify, validate_location
from ui.components import TOKEN, section, info_card, ooda_nav, page_header, resolve_author

_log = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

# 状态 → 颜色（文档《01-报修.md》第七节）
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

_URGENCY_EMOJI = {"紧急": "🔴", "中等": "🟠", "一般": "🟡", "普通": "🔵"}
_URGENCY_LEVELS = ["紧急", "中等", "一般", "普通"]

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else (st.session_state.get("user_profile") or {})
_author = resolve_author(profile)
_my_name = (profile.get("name") or "").strip()


def _current_user_id() -> int | None:
    try:
        from data.db_user import get_current_user
        return (get_current_user() or {}).get("id")
    except Exception:
        return None


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
    return phone or "未填写"


def _my_issues(uid: int | None) -> list[dict]:
    """当前居民的工单：按 reporter_id 主键匹配，老数据回退 reporter_name / author。"""
    all_issues = get_issues(limit=300)
    mine = []
    for it in all_issues:
        if uid and it.get("reporter_id") == uid:
            mine.append(it)
        elif it.get("reporter_name") and _my_name and it["reporter_name"] == _my_name:
            mine.append(it)
        elif (it.get("author") or "") and _author and it["author"] == _author:
            mine.append(it)
    return mine


page_header("🔧 接诉即办 · 报修", "发现社区问题？提交报修工单，全程可追踪、可反馈。", "报")

ooda_nav("issues")

uid = _current_user_id()

# ---------- 草稿恢复入口 ----------
drafts = get_drafts(uid) if uid else []
if drafts:
    with st.container(border=True):
        st.warning(f"📝 您有 {len(drafts)} 份未完成的报修草稿，可继续填写。")
        for d in drafts:
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1:
                st.caption(
                    f"**{((d.get('title') or '')[:30]) or '（未填写标题）'}** · "
                    f"{d.get('issue_type', '')} · {d.get('urgency', '')} · 更新于 {(d.get('updated_at') or '')[:16]}"
                )
            with c2:
                if st.button("✏️ 继续填写", key=f"draft_cont_{d['id']}", width="stretch"):
                    st.session_state["rep_form_title"] = d.get("title", "")
                    st.session_state["rep_form_location"] = d.get("location", "")
                    st.session_state["rep_form_name"] = d.get("reporter_name", "")
                    st.session_state["rep_form_phone"] = d.get("reporter_phone", "")
                    st.session_state["rep_form_type"] = d.get("issue_type", "室外")
                    st.session_state["rep_form_urgency"] = d.get("urgency", "一般")
                    st.session_state["_active_draft_id"] = d["id"]
                    st.rerun()
            with c3:
                if st.button("🗑️ 删除", key=f"draft_del_{d['id']}", width="stretch"):
                    delete_draft(d["id"])
                    st.rerun()

# ---------- 快速报修表单 ----------
with st.container(border=True):
    st.markdown(
        f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin-bottom:6px;">'
        f'⚡ 快速报修</div>',
        unsafe_allow_html=True,
    )
    with st.form("repair_form"):
        title = st.text_input(
            "问题描述（必填，5–200 字）",
            placeholder="比如：3号楼二楼卫生间水龙头漏水、小区广场地面有个坑…",
            key="rep_form_title",
        )
        location = st.text_input(
            "报修地址（必填，小区/院落 + 楼栋单元房号）",
            placeholder="比如：幸福小区3号楼2单元302",
            key="rep_form_location",
        )
        c1, c2 = st.columns(2)
        with c1:
            issue_type = st.radio(
                "分类（必选）", ["室外", "室内"], horizontal=True,
                key="rep_form_type",
                help="室外：社区公共区域，费用由社区承担；室内：您家里，费用自理。",
            )
        with c2:
            urgency = st.selectbox(
                "紧急程度",
                _URGENCY_LEVELS,
                index=2,  # 默认「一般」
                key="rep_form_urgency",
                help="紧急：1小时内上门 · 中等：4小时内上门 · 一般：24小时内上门 · 普通：48小时内解决",
            )
        c3, c4 = st.columns(2)
        with c3:
            reporter_name = st.text_input("报修人姓名", value=_my_name, key="rep_form_name")
        with c4:
            reporter_phone = st.text_input("联系电话（手机号）", placeholder="138****1234", key="rep_form_phone")
        photos = st.file_uploader("现场照片（选填，jpg/png，≤5MB，最多3张）",
                                  type=["jpg", "jpeg", "png"], accept_multiple_files=True,
                                  help="照片仅负责人和您本人可见")
        submitted = st.form_submit_button("📨 提交报修", type="primary", width="stretch")
        saved = st.form_submit_button("💾 保存草稿", width="stretch")

    if saved:
        if not (title or "").strip():
            st.error("请至少填写问题描述后再保存草稿。")
        elif not uid:
            st.error("暂无法识别当前用户，无法保存草稿。")
        else:
            create_draft(
                uid, title=(title or "").strip(),
                category="", issue_type=issue_type,
                location=(location or "").strip(),
                description=(title or "").strip(),
                urgency=urgency,
                reporter_name=(reporter_name or "").strip(),
                reporter_phone=(reporter_phone or "").strip(),
            )
            st.success("草稿已保存，可在上方草稿区继续填写。")

    if submitted:
        title_t = (title or "").strip()
        loc_t = (location or "").strip()
        name_t = (reporter_name or "").strip()
        phone_t = (reporter_phone or "").strip()

        # —— 前端校验（数据层 submit_issue 也会再校验一遍）——
        if not title_t:
            st.error("请填写问题描述。")
        elif len(title_t) < 5:
            st.error("问题描述太短，请至少写 5 个字。")
        elif len(title_t) > 200:
            st.error("问题描述过长，请控制在 200 字以内。")
        elif not loc_t:
            st.error("请填写报修地址（小区/院落名称 + 楼栋单元房号）。")
        else:
            loc_err = validate_location(title_t, loc_t)
            if loc_err:
                st.error(loc_err)
            elif not name_t:
                st.error("请填写报修人姓名。")
            elif not _PHONE_RE.match(phone_t):
                st.error("请输入正确的手机号（11 位，1 开头）。")
            else:
                # 诉求类别交给 AI 分类（紧急程度由居民自选）
                category, _ = _llm_classify(title_t, "")
                photo_before = "[]"
                try:
                    from utils.uploads import save_uploaded_files
                    _saved = save_uploaded_files(photos, folder="issues")
                    if _saved:
                        import json
                        photo_before = json.dumps(_saved, ensure_ascii=False)
                except Exception:
                    pass
                draft_id = st.session_state.get("_active_draft_id")
                issue_id, hint = submit_issue(
                    title=title_t,
                    category=category,
                    issue_type=issue_type,
                    location=loc_t,
                    description=title_t,
                    urgency=urgency,
                    reporter_name=name_t,
                    reporter_phone=phone_t,
                    reporter_id=uid,
                    photo_before=photo_before,
                    draft_id=draft_id,
                )
                if hint == "safety":
                    st.error(
                        "⚠️ **已记录安全提醒，不生成维修工单**\n\n"
                        "请先拨打紧急电话：🚒 消防 **119** · 🔥 燃气 **96777**\n"
                        "系统已记录您的安全提醒，社区负责人会同步跟进。"
                    )
                elif hint == "third_party":
                    st.warning(
                        f"⚠️ 该问题可能属第三方施工责任，已生成工单 **#{issue_id}** 并标记「非社区责任」，"
                        "负责人将核实处理。"
                    )
                elif hint == "violation":
                    st.warning(
                        f"⚠️ 工单 **#{issue_id}** 已生成并标记「违规搭建」，负责人审核通过后将按流程转出处理。"
                    )
                elif issue_id > 0:
                    st.success(
                        f"✅ 工单 **#{issue_id}** 已提交！分类：{category}（{issue_type}）· "
                        f"{_URGENCY_EMOJI.get(urgency, '🔵')} {urgency} · 状态：待审核\n\n"
                        "社区负责人会尽快电话核实，请保持电话畅通。"
                    )
                    # 清空表单（含已恢复的草稿）
                    for k in ("rep_form_title", "rep_form_location", "rep_form_name",
                              "rep_form_phone", "_active_draft_id"):
                        st.session_state.pop(k, None)
                else:
                    st.error(f"提交失败：{hint}")

def _load_photos(raw: str | None) -> list[str]:
    """解析照片路径 JSON，返回可显示的绝对路径列表（仅负责人和本人可见）。"""
    import json
    try:
        paths = json.loads(raw or "[]")
    except Exception:
        paths = []
    from utils.uploads import resolve_path
    return [p for p in (resolve_path(x) for x in paths) if p]


def _render_detail(issue: dict):
    iid = issue["id"]
    status = issue.get("status", "")
    reporter_actor = (issue.get("reporter_name") or "").strip() or _my_name or "居民"

    st.markdown(f"**分类**：{issue.get('issue_type', '—')} · **类别**：{issue.get('category', '—')}")
    st.markdown(f"**紧急程度**：{issue.get('urgency', '—')}")
    st.markdown(f"**地址**：{issue.get('location') or '未填写'}")
    st.markdown(f"**问题描述**：{issue.get('description') or '—'}")
    st.markdown(
        f"**报修人**：{issue.get('reporter_name') or '—'} · "
        f"**电话**：{_mask_phone(issue.get('reporter_phone'))}"
    )
    if issue.get("assignee_name"):
        st.markdown(
            f"**维修人员**：{issue['assignee_name']} · "
            f"电话 {_mask_phone(issue.get('assignee_phone'))}"
        )
    if issue.get("resolve_note"):
        st.markdown(f"**处理结果**：{issue['resolve_note']}")
    if issue.get("no_photo_reason"):
        st.markdown(f"**未上传照片原因**：{issue['no_photo_reason']}")
    _photos_b = _load_photos(issue.get("photo_before"))
    _photos_a = _load_photos(issue.get("photo_after"))
    if _photos_b:
        st.markdown("**📷 现场照片**")
        st.image(_photos_b, width=160)
    if _photos_a:
        st.markdown("**📷 维修后照片**")
        st.image(_photos_a, width=160)
    if issue.get("satisfaction"):
        icon = "😊" if issue.get("satisfaction") == "满意" else "😞"
        st.markdown(f"**满意度**：{icon} {issue['satisfaction']}")

    # 状态时间线
    st.markdown("**📜 状态时间线**")
    timeline = get_issue_timeline(iid)
    if timeline:
        for t in timeline:
            before = t.get("before_value") or ""
            after = t.get("after_value") or ""
            trans = f"：{before} → {after}" if (before or after) else ""
            tail = f" — {t['detail']}" if t.get("detail") else ""
            st.caption(f"🕐 {(t.get('created_at') or '')[:16]} · {t.get('actor') or ''} · {t.get('action')}{trans}{tail}")
    else:
        st.caption("暂无留痕记录")

    # 居民操作（按状态）
    if status == "待审核":
        st.markdown("---")
        # 修改工单（撤回/退回后回到待审核时可用，全流程仅一次）
        with st.expander("✏️ 修改工单内容（仅一次机会）", expanded=False):
            with st.form(key=f"edit_{iid}"):
                e_title = st.text_input("问题标题", value=i.get("title", ""))
                e_loc = st.text_input("报修地址", value=i.get("location", ""))
                e_desc = st.text_area("问题描述", value=i.get("description", ""))
                e_urg = st.selectbox("紧急程度", ["紧急", "中等", "一般", "普通"],
                                     index=["紧急", "中等", "一般", "普通"].index(i.get("urgency", "一般")))
                e_sub = st.form_submit_button("保存修改", width="stretch")
            if e_sub:
                ok, msg = edit_issue(iid, actor=reporter_actor, title=e_title,
                                     location=e_loc, description=e_desc, urgency=e_urg)
                if ok:
                    st.success("工单内容已更新，负责人将重新核实。")
                    st.rerun()
                else:
                    st.error(msg)
        if st.button("↩️ 撤回工单", key=f"withdraw_{iid}", width="stretch"):
            ok, msg = withdraw_issue(iid, actor=reporter_actor)
            if ok:
                st.success("工单已撤回。")
                st.rerun()
            else:
                st.error(msg)
    elif status == "已撤回":
        st.markdown("---")
        st.caption("工单已撤回，可重新打开（回到待审核，负责人需重新电话核实）。")
        if st.button("🔓 重新打开工单", key=f"reopen_{iid}", width="stretch"):
            ok, msg = reopen_issue(iid, actor=reporter_actor)
            if ok:
                st.success("工单已重新打开，回到待审核。")
                st.rerun()
            else:
                st.error(msg)
    elif status == "退回补充信息":
        st.markdown("---")
        st.info("负责人已退回工单，请补充有效信息（如联系方式/更清晰的描述），负责人将重新审核。")
        if st.button("📤 重新提交", key=f"resubmit_{iid}", width="stretch"):
            ok, msg = resubmit_issue(iid, actor=reporter_actor)
            if ok:
                st.success("已重新提交，回到待审核。")
                st.rerun()
            else:
                st.error(msg)

    # 待居民反馈：满意度
    if status == "待居民反馈":
        st.markdown("---")
        st.markdown("**满意度反馈**：")
        with st.form(key=f"feedback_{iid}"):
            choice = st.radio("本次维修结果您是否满意？", ["😊 满意", "😞 不满意"], horizontal=True)
            reason = st.text_input("如不满意，请填写原因（必填）")
            fb_sub = st.form_submit_button("提交反馈", width="stretch")
        if fb_sub:
            satisfied = choice == "😊 满意"
            ok, msg = feedback_issue(iid, satisfied=satisfied, reason=(reason or "").strip(), actor=reporter_actor)
            if ok:
                st.success("感谢您的反馈！" if satisfied else "已记录您的不满，负责人将重新处理（时限重新计算）。")
                st.rerun()
            else:
                st.error(msg)

    # 补充信息（非终态）
    if status not in _TERMINAL:
        st.markdown("---")
        st.markdown("**补充信息**（24 小时内最多 2 次）")
        with st.form(key=f"supp_{iid}"):
            content = st.text_area("补充内容", placeholder="补充说明您的情况…（不修改原始内容）")
            sup_sub = st.form_submit_button("提交补充", width="stretch")
        if sup_sub:
            ok, msg = supplement_issue(iid, (content or "").strip(), actor=reporter_actor)
            if ok:
                st.success("补充信息已提交，负责人将收到通知。")
                st.rerun()
            else:
                st.error(msg)


st.markdown("---")

# ---------- 我的工单 ----------
section("我的工单")
mine = _my_issues(uid)

if not mine:
    info_card("您还没有报修工单。", "在上方提交报修后，可在这里查看进度和反馈。")
else:
    total = len(mine)
    pending = sum(1 for i in mine if i.get("status") in ("待审核", "退回补充信息"))
    processing = sum(1 for i in mine if i.get("status") in ("已审核待派单", "已派单", "处理中", "待协商", "待居民反馈"))
    done = sum(1 for i in mine if i.get("status") in ("处理结束", "已关闭", "已转出", "已撤回"))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("我的工单", f"{total} 件")
    with c2:
        st.metric("待审核", f"{pending} 件")
    with c3:
        st.metric("处理中", f"{processing} 件")
    with c4:
        st.metric("已结束", f"{done} 件")

    for issue in mine:
        iid = issue["id"]
        status = issue.get("status", "")
        title = issue.get("title", "") or ""
        urgency = issue.get("urgency", "")
        with st.container(border=True):
            st.markdown(
                f'<span style="font-size:1.02em;font-weight:700;color:{TOKEN["text"]};">'
                f'#{iid} {title[:40]}</span>'
                f'&nbsp;{_status_badge(status)}'
                + (f'&nbsp;{_URGENCY_EMOJI.get(urgency, "")} {urgency}' if urgency else ""),
                unsafe_allow_html=True,
            )
            st.caption(
                f'{issue.get("issue_type", "")} · {issue.get("category", "")} · '
                f'📍 {issue.get("location") or "未填写"} · 🕐 {(issue.get("reported_at") or "")[:16]}'
            )
            with st.expander("📄 查看详情与操作", expanded=False):
                _render_detail(issue)
