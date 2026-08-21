"""🗳️ 邻里议事 · 议 — 提交提案、我的提案（确认公开私有/撤回/反馈）、公开提案投票、议题讨论。"""
import logging
import streamlit as st

from data.db_proposal import (
    submit_proposal as db_submit_proposal,
    resubmit_proposal as db_resubmit_proposal,
    withdraw_proposal as db_withdraw_proposal,
    reopen_proposal as db_reopen_proposal,
    confirm_visibility as db_confirm_visibility,
    feedback_proposal as db_feedback_proposal,
    vote_proposal as db_vote_proposal,
    has_voted as db_has_voted,
    get_my_proposals as db_my_proposals,
    get_active_public as db_active_public,
    get_proposal_vote_stats,
    get_voting_remaining_days,
    get_proposal_timeline,
    get_proposals_stats,
    save_draft as db_save_draft,
    get_drafts as db_get_drafts,
    delete_draft as db_delete_draft,
    proposal_no,
    VALID_CATEGORIES,
    STATUS_COLORS,
)
from data.database import (
    add_opinion, get_opinion_summary,
)
from ui.cache import (
    cached_active_topics as get_active_topics,
    cached_opinions_by_topic as get_opinions,
    invalidate_proposals,
    invalidate_opinions,
)
from ui.components import (
    TOKEN, section, stat, info_card, ooda_nav, resolve_author, page_header,
)

_log = logging.getLogger(__name__)

agent = st.session_state.get("agent")
memory = st.session_state.get("memory")
if memory is not None:
    profile = memory.get_user_profile()
else:
    profile = {}

_user_id = st.session_state.get("_login_user_id", 0)
_author = resolve_author(profile)

page_header("🗳️ 邻里议事", "提交提案、确认公开/私有、参与公示投票、反馈满意度。", "议")

ooda_nav("voice")

# 状态颜色：第七节标准输出（黄/红/蓝/绿/橙/灰）
_COLOR_TOKENS = {
    "黄": ("warning_bg", "warning_border", "warning"),
    "红": ("danger_bg", "danger_border", "danger"),
    "蓝": ("info_bg", "info_border", "info"),
    "绿": ("success_bg", "success_border", "success"),
    "橙": ("accent_bg", "accent_border", "accent"),
    "灰": ("accent_bg", "border", "text_muted"),
}


def _status_tag(status: str) -> str:
    color = STATUS_COLORS.get(status or "", "灰")
    bg_k, bd_k, fg_k = _COLOR_TOKENS[color]
    return (
        f'<span style="display:inline-block;background:{TOKEN[bg_k]};border:1px solid {TOKEN[bd_k]};'
        f'color:{TOKEN[fg_k]};border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
        f'font-size:{TOKEN["font_micro"]};white-space:nowrap;font-weight:{TOKEN["weight_semibold"]};">'
        f'{status}</span>'
    )


def _vote_line(pid: int) -> str:
    """提案的投票/公示摘要文本。"""
    s = get_proposal_vote_stats(pid)
    if s["vote_count"] == 0:
        return "暂无评分"
    avg = f"{s['avg_score']:.1f}" if s["avg_score"] is not None else "—"
    rank = f" · 排名 {s['rank']}/{s['scored_count']}" if s["rank"] else ""
    return f"评分 {s['vote_count']} 人 · 平均 {avg}{rank}"


# ---------------------------------------------------------------------------
# 我的提案（进度 + 可操作项）
# ---------------------------------------------------------------------------

section("我的提案")

my_props = db_my_proposals(_user_id) if _user_id else []
if not my_props:
    info_card("你还没有提案，在下方提交第一份提案吧！")
else:
    for p in my_props:
        pid = p["id"]
        s = p.get("status", "")
        with st.container(border=True):
            st.markdown(
                f'<div style="font-size:0.9em;font-weight:700;color:{TOKEN["text"]};">'
                f'{proposal_no(pid)} {p.get("title","")[:40]} {_status_tag(s)}</div>',
                unsafe_allow_html=True,
            )
            st.caption(
                f'{p.get("category","")} · {"公开" if p.get("is_public") else "私有"} · '
                f'提交于 {(p.get("created_at") or "")[:16]}'
                + (f' · 重新执行 {p.get("reopen_count",0)} 次' if p.get("reopen_count") else "")
            )
            if s == "待审核":
                st.caption("⏳ 等待负责人审核，可撤回。")
                if st.button("↩️ 撤回提案", key=f"my_withdraw_{pid}"):
                    ok, msg = db_withdraw_proposal(pid, actor=_author or "居民")
                    if ok:
                        invalidate_proposals()
                        st.success(f"已撤回 {proposal_no(pid)}，可重新打开后修改。")
                    else:
                        st.error(msg)
                    st.rerun()
            elif s == "退回修改":
                st.caption(f"🔴 审核意见：{p.get('audit_opinion') or '未填写'}")
                with st.expander("✏️ 修改并重新提交", expanded=True):
                    rt = st.text_input("标题", value=p.get("title",""), key=f"re_title_{pid}", max_chars=50)
                    rd = st.text_area("内容", value=p.get("description",""), key=f"re_desc_{pid}", height=80)
                    rc = st.selectbox("类别", VALID_CATEGORIES,
                                      index=VALID_CATEGORIES.index(p.get("category")) if p.get("category") in VALID_CATEGORIES else 4,
                                      key=f"re_cat_{pid}")
                    if st.button("📤 重新提交（回到待审核）", key=f"re_submit_{pid}", type="primary"):
                        ok, msg = db_resubmit_proposal(pid, rt, rd, rc, actor=_author or "居民")
                        if ok:
                            invalidate_proposals()
                            st.success("已重新提交，等待负责人重新审核。")
                            st.rerun()
                        else:
                            st.error(msg)
            elif s == "已撤回":
                st.caption("已撤回。可重新打开（不修改）或修改后重新提交。")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("🔓 重新打开", key=f"my_reopen_{pid}"):
                        ok, msg = db_reopen_proposal(pid, actor=_author or "居民")
                        if ok:
                            invalidate_proposals()
                            st.success("已重新打开，回到待审核。")
                            st.rerun()
                        else:
                            st.error(msg)
                with c2:
                    with st.expander("✏️ 修改后重新提交"):
                        rt = st.text_input("标题", value=p.get("title",""), key=f"rw_title_{pid}", max_chars=50)
                        rd = st.text_area("内容", value=p.get("description",""), key=f"rw_desc_{pid}", height=80)
                        if st.button("📤 重新提交", key=f"rw_submit_{pid}", type="primary"):
                            ok, msg = db_resubmit_proposal(pid, rt, rd, p.get("category",""), actor=_author or "居民")
                            if ok:
                                invalidate_proposals()
                                st.success("已重新提交，等待负责人重新审核。")
                                st.rerun()
                            else:
                                st.error(msg)
            elif s == "待确认公示/私有":
                st.caption("审核已通过，请在 7 天内确认公开/私有（可修改一次，逾期按提交时选择执行）。")
                choice = st.radio(
                    "公开方式", ["公开", "私有"],
                    index=0 if p.get("is_public") else 1,
                    horizontal=True, key=f"confirm_choice_{pid}",
                )
                if st.button("✅ 确认", key=f"confirm_btn_{pid}", type="primary"):
                    ok, msg = db_confirm_visibility(pid, 1 if choice == "公开" else 0, actor=_author or "居民")
                    if ok:
                        invalidate_proposals()
                        st.success("已确认" + ("公开，进入 7 天公示与投票。" if choice == "公开" else "私有，等待负责人转部门执行。"))
                        st.rerun()
                    else:
                        st.error(msg)
            elif s == "公示中":
                days = get_voting_remaining_days(pid)
                st.caption(f"🔵 公示中" + (f"，剩余 {days} 天" if days is not None else "") + f" · {_vote_line(pid)}")
            elif s == "待执行":
                st.caption("🔵 私有提案，等待负责人转部门执行。")
            elif s == "执行中":
                st.caption(f"🟢 执行中 · 执行部门：{p.get('executor_dept') or '待定'}")
            elif s == "待提案人反馈":
                st.caption(f"🟠 执行已完成，请反馈满意度（7 天内，逾期视为满意）。")
                if p.get("execution_result"):
                    st.markdown(
                        f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};background:{TOKEN["success_bg"]};'
                        f'padding:8px 12px;border-radius:6px;">执行结果：{p["execution_result"][:200]}</div>',
                        unsafe_allow_html=True,
                    )
                sat = st.radio("满意度", ["满意", "不满意"], horizontal=True, key=f"sat_{pid}")
                reason = ""
                if sat == "不满意":
                    reason = st.text_input("不满意原因（必填）", key=f"sat_reason_{pid}")
                if st.button("📤 提交反馈", key=f"sat_btn_{pid}", type="primary"):
                    ok, msg = db_feedback_proposal(pid, sat == "满意", reason, actor=_author or "居民")
                    if ok:
                        invalidate_proposals()
                        st.success("反馈已提交。" + ("感谢你的认可！" if sat == "满意" else "提案将进入重新执行流程。"))
                        st.rerun()
                    else:
                        st.error(msg)
            elif s == "重新执行":
                st.caption("🟠 重新执行处理中（负责人处理中）。" + ("超过 2 次，等待负责人决定关闭或继续。" if (p.get("reopen_count") or 0) >= 2 else ""))
            elif s == "已完成":
                st.caption(f"✅ 已完成。{p.get('satisfaction') or '满意'}")
            elif s == "不予执行":
                st.caption(f"决定不予执行，原因：{p.get('decision_reason') or '—'}")
            elif s == "违规下架":
                st.caption(f"违规下架，原因：{p.get('decision_reason') or '—'}")
            elif s == "已关闭":
                st.caption("已关闭。")
            elif s == "已结束":
                st.caption("已结束（未及时反馈，视为满意）。")

            # 留痕时间线（居民只看自己提案的状态变化，最近 3 条，可展开全部）
            timeline = get_proposal_timeline(pid, limit=100)
            if timeline:
                with st.expander("📜 状态变化（留痕）"):
                    for t in timeline[:3]:
                        st.markdown(
                            f'<div style="font-size:0.78em;color:{TOKEN["text_sec"]};">'
                            f'· {(t.get("created_at") or "")[:16]} {t.get("action","")}'
                            f'（{t.get("before_value","")} → {t.get("after_value","")}）</div>',
                            unsafe_allow_html=True,
                        )
                    if len(timeline) > 3:
                        with st.expander("查看全部留痕"):
                            for t in timeline:
                                st.markdown(
                                    f'<div style="font-size:0.78em;color:{TOKEN["text_sec"]};">'
                                    f'· {(t.get("created_at") or "")[:16]} {t.get("action","")}'
                                    f'（{t.get("before_value","")} → {t.get("after_value","")}）'
                                    f'{("：" + t.get("detail","")[:60]) if t.get("detail") else ""}</div>',
                                    unsafe_allow_html=True,
                                )

st.markdown("---")

# ---------------------------------------------------------------------------
# 提交提案（含草稿恢复）
# ---------------------------------------------------------------------------

create_feedback = st.session_state.get("_create_proposal_feedback", "")
create_error = st.session_state.get("_create_proposal_error", "")

with st.container(border=True):
    st.markdown(
        f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin-bottom:6px;">'
        f'✍️ 提交提案</div>',
        unsafe_allow_html=True,
    )

    drafts = db_get_drafts(_user_id) if _user_id else []
    if drafts:
        d = drafts[0]
        st.info(
            f"📝 您有未完成的提案草稿（保存于 {(d.get('updated_at') or '')[:16]}，7 天内有效）。"
            "点击「继续填写」恢复，或「丢弃草稿」重新开始。"
        )
        c_d1, c_d2 = st.columns(2)
        with c_d1:
            if st.button("继续填写", key="draft_continue"):
                for k, v in [("create_proposal_title", d.get("title","")),
                             ("create_proposal_desc", d.get("description","")),
                             ("create_proposal_cat", d.get("category","")),
                             ("create_proposal_public", "公开" if d.get("is_public") else "私有"),
                             ("create_proposal_name", d.get("reporter_name","")),
                             ("create_proposal_phone", d.get("reporter_phone","")),
                             ("create_proposal_attach", bool(d.get("attachment_public"))),
                             ("create_proposal_agent", bool(d.get("is_agent_report"))),
                             ("create_proposal_agent_name", d.get("agent_name","")),
                             ("create_proposal_agent_phone", d.get("agent_phone","")),
                             ("create_proposal_agent_rel", d.get("agent_relation",""))]:
                    st.session_state[k] = v
                st.rerun()
        with c_d2:
            if st.button("丢弃草稿", key="draft_discard"):
                db_delete_draft(d["id"])
                for k in ("create_proposal_title", "create_proposal_desc", "create_proposal_cat",
                          "create_proposal_public", "create_proposal_name", "create_proposal_phone",
                          "create_proposal_attach", "create_proposal_agent",
                          "create_proposal_agent_name", "create_proposal_agent_phone",
                          "create_proposal_agent_rel"):
                    if k in st.session_state:
                        del st.session_state[k]
                st.rerun()

    prop_title = st.text_input(
        "提案标题（≤50 字）",
        placeholder="比如：建议活动室延长开放时间到23:00...",
        key="create_proposal_title",
    )
    prop_desc = st.text_area(
        "提案内容（10~1000 字）",
        placeholder="说说为什么提这个建议、具体怎么实施...",
        key="create_proposal_desc",
        height=90,
    )
    c1, c2 = st.columns(2)
    with c1:
        prop_category = st.selectbox(
            "提案类别（必选）", VALID_CATEGORIES, key="create_proposal_cat",
        )
    with c2:
        prop_public = st.radio(
            "公开方式（必选）", ["公开", "私有"],
            help="公开：公示 7 天并接受全体居民匿名评分；私有：不公示不投票，直接转部门执行。",
            horizontal=True, key="create_proposal_public",
        )
    c3, c4 = st.columns(2)
    with c3:
        prop_name = st.text_input("提案人姓名（必填）", key="create_proposal_name")
    with c4:
        prop_phone = st.text_input("联系电话（必填，11 位手机号）", key="create_proposal_phone")
    prop_building = st.text_input("所属小区/楼栋（选填）", key="create_proposal_building")
    prop_attach = st.checkbox(
        "公开附件（选填，默认不公开；公开需负责人审核确认不含个人隐私，公示期间其他居民可见）",
        key="create_proposal_attach",
    )
    prop_files = st.file_uploader("附件图片（选填，jpg/png，≤5MB，最多3张）",
                                  type=["jpg", "jpeg", "png"], accept_multiple_files=True,
                                  key="create_proposal_files",
                                  help="附件仅负责人可见；选择公开且审核通过后，公示期间其他居民可见")
    with st.expander("👴 代报信息（选填，老人可由家属/负责人代报）"):
        prop_agent = st.checkbox("这是代报", key="create_proposal_agent")
        c_a1, c_a2, c_a3 = st.columns(3)
        with c_a1:
            agent_name = st.text_input("代报人姓名", key="create_proposal_agent_name")
        with c_a2:
            agent_phone = st.text_input("代报人电话", key="create_proposal_agent_phone")
        with c_a3:
            agent_rel = st.text_input("与提案人关系", key="create_proposal_agent_rel")

    c_b1, c_b2, c_b3 = st.columns([2, 2, 1])
    with c_b1:
        submit_prop = st.button("📤 提交提案", type="primary", width="stretch", key="create_proposal_btn")
    with c_b2:
        save_draft_btn = st.button("💾 保存草稿", width="stretch", key="create_proposal_save_draft")
    with c_b3:
        st.markdown("")  # 占位

    if save_draft_btn:
        if _user_id:
            db_save_draft(
                _user_id, title=prop_title, description=prop_desc, category=prop_category,
                is_public=1 if prop_public == "公开" else 0, reporter_name=prop_name,
                reporter_phone=prop_phone, attachment_public=1 if prop_attach else 0,
                is_agent_report=1 if prop_agent else 0, agent_name=agent_name,
                agent_phone=agent_phone, agent_relation=agent_rel,
            )
            st.session_state._create_proposal_feedback = "✅ 草稿已保存（7 天内有效），可随时回来继续填写。"
            st.session_state._create_proposal_error = ""
            st.rerun()
        else:
            st.warning("请先登录后再保存草稿。")

    if submit_prop:
        title = prop_title.strip()
        desc = prop_desc.strip()
        if not title or not desc:
            st.session_state._create_proposal_error = "请填写提案标题和内容。"
            st.session_state._create_proposal_feedback = ""
        else:
            _attach = "[]"
            try:
                from utils.uploads import save_uploaded_files
                _saved = save_uploaded_files(prop_files, folder="proposals")
                if _saved:
                    import json
                    _attach = json.dumps(_saved, ensure_ascii=False)
            except Exception:
                pass
            pid, msg = db_submit_proposal(
                title=title, description=desc, category=prop_category,
                reporter_name=prop_name.strip(), reporter_phone=prop_phone.strip(),
                is_public=1 if prop_public == "公开" else 0,
                community_building=prop_building.strip(),
                attachment_public=1 if prop_attach else 0,
                attachment=_attach,
                reporter_id=_user_id or None,
                is_agent_report=1 if prop_agent else 0,
                agent_name=agent_name, agent_phone=agent_phone, agent_relation=agent_rel,
                draft_id=drafts[0]["id"] if drafts else None,
                author=_author,
            )
            if pid:
                invalidate_proposals()
                st.session_state._create_proposal_feedback = (
                    f"✅ 提案 {proposal_no(pid)}「{title[:25]}」已提交！状态：待审核，"
                    "负责人审核通过后请确认公开/私有。"
                )
                st.session_state._create_proposal_error = ""
                for _key in ("create_proposal_title", "create_proposal_desc", "create_proposal_cat",
                             "create_proposal_public", "create_proposal_name", "create_proposal_phone",
                             "create_proposal_building", "create_proposal_attach",
                             "create_proposal_agent", "create_proposal_agent_name",
                             "create_proposal_agent_phone", "create_proposal_agent_rel"):
                    if _key in st.session_state:
                        del st.session_state[_key]
            else:
                # 提交失败：自动保存草稿，防止文字丢失
                if _user_id:
                    db_save_draft(
                        _user_id, title=title, description=desc, category=prop_category,
                        is_public=1 if prop_public == "公开" else 0, reporter_name=prop_name.strip(),
                        reporter_phone=prop_phone.strip(), attachment_public=1 if prop_attach else 0,
                        is_agent_report=1 if prop_agent else 0, agent_name=agent_name,
                        agent_phone=agent_phone, agent_relation=agent_rel,
                    )
                st.session_state._create_proposal_error = f"⚠️ {msg}（已自动保存草稿，可继续填写）"
                st.session_state._create_proposal_feedback = ""
        st.rerun()

if create_feedback:
    st.success(create_feedback)
    st.session_state._create_proposal_feedback = ""
if create_error:
    st.error(create_error)
    st.session_state._create_proposal_error = ""

st.markdown("---")

# ---------------------------------------------------------------------------
# 公开提案列表（公示投票入口）
# ---------------------------------------------------------------------------

pstats = get_proposals_stats()

c1, c2, c3, c4 = st.columns(4)
with c1:
    stat("提案总数", str(pstats["total"]), TOKEN["accent"])
with c2:
    stat("待审核", str(pstats.get("by_status", {}).get("待审核", 0)), TOKEN["warning"])
with c3:
    stat("公示中", str(pstats["voting"]), TOKEN["info"])
with c4:
    stat("已完成", str(pstats["completed"]), TOKEN["success"])

st.markdown("")

section("公开提案（含公示投票）")

pub_props = db_active_public(limit=50)
if not pub_props:
    info_card("暂无公开提案。提交后经审核确认公开，就会在这里公示并接受评分。")
else:
    # 公示中的排前面，其余按时间
    pub_props.sort(key=lambda p: (0 if p.get("status") == "公示中" else 1, -(p.get("id") or 0)))

    # 当前用户本次会话内自己的评分回显（仅前端记忆，不入库，保证匿名）
    my_votes = st.session_state.setdefault("_my_proposal_votes", {})

    for p in pub_props:
        pid = p["id"]
        s = p.get("status", "")
        with st.container(border=True):
            st.markdown(
                f'<div style="font-size:0.9em;font-weight:700;color:{TOKEN["text"]};">'
                f'{proposal_no(pid)} {p.get("title","")[:40]} {_status_tag(s)}</div>',
                unsafe_allow_html=True,
            )
            line = f'{p.get("category","")} · 提交于 {(p.get("created_at") or "")[:10]}'
            if s == "公示中":
                days = get_voting_remaining_days(pid)
                line += f' · ⏳ 公示剩余 {days} 天' if days is not None else ""
                vs = _vote_line(pid)
                line += f" · {vs}" if vs != "暂无评分" else ""
            else:
                vs = _vote_line(pid)
                line += f" · {vs}" if vs != "暂无评分" else ""
            if s == "执行中" and p.get("executor_dept"):
                line += f" · 执行部门：{p['executor_dept']}"
            st.caption(line)
            if s == "已完成" and p.get("execution_result"):
                st.markdown(
                    f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};">✅ 执行结果：{p["execution_result"][:120]}</div>',
                    unsafe_allow_html=True,
                )
            elif s in ("不予执行", "违规下架") and p.get("decision_reason"):
                st.markdown(
                    f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};">'
                    f'{"决定不予执行" if s == "不予执行" else "违规下架"}原因：{p["decision_reason"][:120]}</div>',
                    unsafe_allow_html=True,
                )

            # 投票入口：仅公示中、未投过、非本人提案
            if s == "公示中" and _user_id:
                if p.get("reporter_id") and _user_id == p.get("reporter_id"):
                    st.caption("🔒 这是您自己的提案，不能给自己提案投票。")
                elif str(pid) in my_votes:
                    st.caption(f"⭐ 您已评分：{my_votes[str(pid)]} 星（匿名，不可修改）。")
                elif db_has_voted(pid, _user_id):
                    st.caption("⭐ 您已评分（匿名，不可修改）。")
                else:
                    score = st.radio(
                        "评分（1~5 星，匿名，一票制）", [1, 2, 3, 4, 5],
                        format_func=lambda x: "⭐" * x, horizontal=True,
                        key=f"vote_{pid}",
                    )
                    if st.button("🗳️ 提交评分", key=f"vote_btn_{pid}", type="primary"):
                        ok, msg = db_vote_proposal(pid, _user_id, score, actor=_author or "居民")
                        if ok:
                            my_votes[str(pid)] = score
                            invalidate_proposals()
                            st.success(f"评分成功（匿名）：{score} 星。")
                            st.rerun()
                        else:
                            st.error(msg)
                            st.rerun()

st.markdown("---")

# ---------------------------------------------------------------------------
# 正在热议的议题，可直接发言
# ---------------------------------------------------------------------------

section("正在热议")

topics = get_active_topics(limit=20)

if not topics:
    info_card("系统会根据社区热点自动发起讨论")
else:
    opinion_feedback = st.session_state.get("_opinion_feedback", {})

    for t in topics:
        tid = t["id"]
        with st.container(border=True):
            source = "🤖 系统发起" if t.get("created_by_agent") else "👤 管理员"
            st.markdown(
                f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};'
                f'margin-bottom:2px;">🔥 {t.get("title","")[:50]}</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"{source} · {t.get('participant_count',0)} 人参与 · {t.get('category','')}")
            if t.get("description"):
                st.markdown(
                    f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};margin:4px 0 8px;">'
                    f'{t["description"][:150]}</div>',
                    unsafe_allow_html=True,
                )

            opinions = get_opinions(tid, limit=6)
            if opinions:
                st.markdown(
                    f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};margin:8px 0 4px;">'
                    f'💬 最新意见（{len(opinions)} 条）</div>',
                    unsafe_allow_html=True,
                )
                for op in opinions[:4]:
                    st.markdown(
                        f'<div style="background:{TOKEN["page_bg"]};border-radius:{TOKEN["radius_card"]};'
                        f'padding:6px 10px;margin:3px 0;font-size:0.82em;color:{TOKEN["text"]};">'
                        f'<span style="color:{TOKEN["text_muted"]};font-size:0.85em;">{op.get("participant_label","匿名")}：</span>'
                        f'{op.get("content","")[:100]}</div>',
                        unsafe_allow_html=True,
                    )

            with st.expander("💬 发表你的意见", expanded=False):
                opinion_text = st.text_area(
                    "你的意见（匿名）",
                    placeholder="说说你的想法...",
                    key=f"opinion_input_{tid}",
                    label_visibility="collapsed",
                )
                if st.button("📤 发表意见", key=f"submit_opinion_{tid}"):
                    content = opinion_text.strip()
                    if len(content) < 2:
                        st.warning("意见太短了，至少写几个字~")
                    else:
                        try:
                            add_opinion(topic_id=tid, content=content, participant_label="匿名居民")
                            invalidate_opinions()
                            summary = get_opinion_summary(tid)
                            st.session_state._opinion_feedback = {
                                str(tid): f"✅ 已发表！当前 {summary['total_opinions']} 条意见"
                            }
                            del st.session_state[f"opinion_input_{tid}"]
                        except Exception as e:
                            _log.debug("非致命错误", exc_info=True)
                            st.session_state._opinion_feedback = {str(tid): f"❌ 发表失败：{e}"}
                        st.rerun()

            fb_key = str(tid)
            if fb_key in opinion_feedback:
                st.success(opinion_feedback[fb_key])
                del st.session_state._opinion_feedback[fb_key]

st.markdown("---")

# 状态图例
legend_colors = {
    "待审核": "黄", "退回修改": "红", "待确认公示/私有": "蓝", "公示中": "蓝",
    "待执行": "蓝", "执行中": "绿", "待提案人反馈": "橙", "已完成": "灰",
    "重新执行": "橙", "不予执行": "灰", "违规下架": "灰", "已撤回": "灰", "已关闭": "灰", "已结束": "灰",
}
legend_html = "  ".join(
    f'<span style="color:{TOKEN["text_sec"]};">{stt}({legend_colors[stt]})</span>'
    for stt in ["待审核", "退回修改", "待确认公示/私有", "公示中", "待执行", "执行中",
                "待提案人反馈", "已完成", "重新执行", "不予执行", "违规下架", "已撤回", "已关闭", "已结束"]
)
st.markdown(
    f'<div style="font-size:0.72em;color:{TOKEN["text_muted"]};margin-top:12px;line-height:1.9;">'
    f'提案状态图例：<br>{legend_html}</div>',
    unsafe_allow_html=True,
)
