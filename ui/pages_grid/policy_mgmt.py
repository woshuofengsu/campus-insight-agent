# ui/pages_grid/policy_mgmt.py
"""📖 政策问答管理（负责人端）— 知识库审核/版本/时效 + 人工待回复（24小时倒计时）+ 提问记录 + 高频统计。

未注册到 app.py 路由，由项目负责人统一注册（建议标题「政策问答管理」）。
"""
import logging

import altair as alt
import pandas as pd
import streamlit as st

from ui.guard import require_role

require_role("grid")

from ui.components import TOKEN, page_header, stat, configure_altair
from data.db_user import get_current_user
from data.db_policy import (
    POLICY_CATEGORIES, KNOWLEDGE_STATUS, STATUS_COLORS,
    create_knowledge, update_knowledge, delete_knowledge, submit_review,
    withdraw_review, audit_knowledge, create_new_version, take_down_knowledge,
    auto_expire_knowledge, auto_close_stale_questions, mark_overdue_questions,
    get_knowledge, get_knowledge_list, get_knowledge_activity, get_version_history,
    get_expiring_knowledge, get_published_options, get_match_threshold, set_match_threshold,
    get_questions, get_question_timeline, get_question_deadline_info,
    get_pending_reply_questions, reply_question, get_frequency_stats,
    masked_nickname,
)

_log = logging.getLogger(__name__)

_profile = get_current_user()
_actor = (_profile.get("name") or "").strip() or (_profile.get("username") or "负责人")

# 进入页面先跑系统任务（幂等留痕）：到期自动下架 / 超时标记 / 7天未反馈自动结束
try:
    auto_expire_knowledge(actor="系统")
    mark_overdue_questions(actor="系统")
    auto_close_stale_questions(actor="系统")
except Exception:
    _log.warning("政策问答系统任务执行失败", exc_info=True)

page_header("📖 政策问答管理", "知识库审核 · 版本管理 · 时效管理 · 人工回复（24h）· 高频统计。", "问")


def _tag_html(status: str) -> str:
    color = STATUS_COLORS.get(status, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}18;color:{color};'
        f'border:1px solid {color}44;border-radius:999px;padding:2px 10px;'
        f'font-size:0.75em;font-weight:600;white-space:nowrap;">{status}</span>'
    )


def _grid_users(exclude: str = "") -> list[dict]:
    """负责人列表（审核人候选，排除发布人）。"""
    from data.db_user import list_users
    out = []
    for u in list_users(role="grid"):
        name = (u.get("name") or "").strip() or (u.get("username") or "")
        if name and name != exclude:
            out.append({"label": f"{name}（{u.get('username')}）", "name": name})
    return out


tab_kb, tab_reply, tab_questions, tab_stats = st.tabs(
    ["📚 知识库管理", "🧑‍💼 人工待回复", "📋 提问记录", "📊 高频统计"]
)

# ================================================================ 知识库管理

with tab_kb:
    c_new, c_th, c_exp = st.columns([1, 2, 2])
    with c_new:
        if st.button("➕ 新建知识库条目", key="kb_new_btn", width="stretch"):
            st.session_state["_kb_form_mode"] = "new"
            st.session_state.pop("_kb_form_id", None)
            st.rerun()
    with c_th:
        th = st.number_input("自动回答匹配阈值", min_value=0.1, max_value=10.0,
                             value=float(get_match_threshold()), step=0.5, key="kb_th")
        if st.button("💾 保存阈值（立即生效）", key="kb_th_save", width="stretch"):
            ok, msg = set_match_threshold(th, actor=_actor)
            if ok:
                st.toast(f"阈值已调整为 {th}", icon="⚙️")
            else:
                st.error(msg)
            st.rerun()
    with c_exp:
        expiring = get_expiring_knowledge(7)
        if expiring:
            st.warning(f"⚠️ {len(expiring)} 条政策将在 7 天内到期，请及时更新或下架")

    # 表单（新建 / 编辑 / 新版本）
    mode = st.session_state.get("_kb_form_mode")
    if mode:
        st.markdown("---")
        kid = st.session_state.get("_kb_form_id")
        base = get_knowledge(kid) if kid else None
        if mode == "new":
            st.markdown("### ➕ 新建知识库条目")
        elif mode == "edit":
            st.markdown(f"### ✏️ 编辑条目 #{kid}（{base.get('audit_status') if base else ''}）")
        else:
            st.markdown(f"### 📝 创建新版本（基于 #{kid}，版本号自动递增）")
        defaults = base or {}
        with st.form(key=f"kb_form_{mode}"):
            f_title = st.text_input("标题（必填，≤50字）", value=defaults.get("title", ""))
            cat_idx = POLICY_CATEGORIES.index(defaults.get("category")) \
                if defaults.get("category") in POLICY_CATEGORIES else 0
            f_cat = st.selectbox("分类（必填）", POLICY_CATEGORIES, index=cat_idx)
            f_source = st.text_input("来源（必填）", value=defaults.get("source", ""),
                                     placeholder="权威机构名称，或填「社区整理」")
            f_content = st.text_area("政策原文（选填；社区整理内容将自动标注开头）",
                                     value=defaults.get("content", ""), height=110)
            f_interp = st.text_area("通俗解读（必填，自动回答优先引用）",
                                    value=defaults.get("plain_interpretation", ""), height=110)
            f_summary = st.text_area("摘要（选填，≤200字）", value=defaults.get("summary", ""), height=60)
            f_keywords = st.text_input("关键词（必填，1-5个，逗号分隔）", value=defaults.get("keywords", ""))
            c1, c2 = st.columns(2)
            with c1:
                f_eff = st.text_input("生效日期（必填，YYYY-MM-DD）", value=defaults.get("effective_date", ""))
            with c2:
                f_exp = st.text_input("失效日期（选填，YYYY-MM-DD）", value=defaults.get("expire_date", ""))
            c3, c4 = st.columns(2)
            with c3:
                f_pnum = st.text_input("政策文号（选填）", value=defaults.get("policy_number", ""))
            with c4:
                f_area = st.text_input("适用地区", value=defaults.get("applicable_area", "") or "全社区通用")
            f_attach_file = st.file_uploader("附件（选填，PDF，≤5MB）", type=["pdf"], key="kb_attach_file",
                                             help="政策原文 PDF，居民端可查看")
            auditor_opts = _grid_users(exclude=_actor)
            if not auditor_opts:
                st.warning("⚠️ 没有其他负责人可作为审核人（审核人不能与发布人相同），提交审核前请先添加负责人账号。")
            auditor_labels = [o["label"] for o in auditor_opts] or ["（无其他负责人）"]
            pre_auditor = defaults.get("auditor", "")
            pre_idx = next((i for i, o in enumerate(auditor_opts) if o["name"] == pre_auditor), 0)
            f_auditor = st.selectbox("审核人（必填，不能与发布人相同）", auditor_labels,
                                     index=pre_idx if auditor_labels else 0)
            b1, b2 = st.columns(2)
            with b1:
                save_btn = st.form_submit_button(
                    "💾 保存草稿" if mode != "new_version" else "📝 创建新版本草稿", width="stretch")
            with b2:
                submit_btn = st.form_submit_button(
                    "📨 保存并提交审核" if mode != "new_version" else "📨 创建并提交审核", width="stretch")
        if st.button("❌ 取消编辑", key="kb_form_cancel"):
            st.session_state.pop("_kb_form_mode", None)
            st.session_state.pop("_kb_form_id", None)
            st.rerun()

        if save_btn or submit_btn:
            auditor_name = ""
            if auditor_labels:
                auditor_name = auditor_opts[pre_idx if pre_idx < len(auditor_opts) else 0]["name"]
            _attach_val = defaults.get("attachment", "") or ""
            try:
                if f_attach_file:
                    from utils.uploads import save_uploaded_files
                    _saved = save_uploaded_files([f_attach_file], folder="knowledge", max_count=1)
                    if _saved:
                        _attach_val = _saved[0]
            except Exception:
                pass
            kw = dict(title=f_title, category=f_cat, plain_interpretation=f_interp,
                      source=f_source, keywords=f_keywords, effective_date=f_eff,
                      content=f_content, summary=f_summary, expire_date=f_exp,
                      policy_number=f_pnum, applicable_area=f_area, attachment=_attach_val)
            kid2, err = 0, ""
            if mode == "new":
                kid2, err = create_knowledge(actor=_actor, **kw)
            elif mode == "edit":
                ok, err = update_knowledge(kid, actor=_actor, **kw)
                kid2 = kid
            else:
                kid2, err = create_new_version(kid, actor=_actor, auditor=auditor_name, **kw)
            if err:
                st.error(err)
            else:
                if submit_btn:
                    ok2, err2 = submit_review(kid2, auditor=auditor_name, actor=_actor)
                    if not ok2:
                        st.error(err2)
                    else:
                        st.session_state.pop("_kb_form_mode", None)
                        st.session_state.pop("_kb_form_id", None)
                        st.toast("已保存并提交审核", icon="📨")
                        st.rerun()
                else:
                    st.session_state.pop("_kb_form_mode", None)
                    st.session_state.pop("_kb_form_id", None)
                    st.toast("已保存草稿", icon="💾")
                    st.rerun()

    st.markdown("---")
    c1, c2, c3 = st.columns([2, 2, 3])
    with c1:
        stf = st.radio("状态", ["全部"] + KNOWLEDGE_STATUS, horizontal=True, key="kb_status_filter")
    with c2:
        catf = st.selectbox("分类", ["全部"] + POLICY_CATEGORIES, key="kb_cat_filter")
    with c3:
        search = st.text_input("搜索标题/关键词", key="kb_search")

    rows = get_knowledge_list(
        status=None if stf == "全部" else stf,
        category=None if catf == "全部" else catf,
        search=search,
    )
    if not rows:
        st.info("暂无知识库条目。")
    for row in rows:
        kid = row["id"]
        status = row.get("audit_status") or ""
        status_show = status
        if status == "已下架" and row.get("audit_opinion"):
            status_show = f"已下架（{row['audit_opinion']}）"
        with st.container(border=True):
            st.markdown(
                f'<span style="font-weight:700;color:{TOKEN["text"]};">'
                f'#{kid} {row.get("title","")}</span>'
                f'&nbsp;{_tag_html(status_show)}'
                f'&nbsp;<span style="color:{TOKEN["text_muted"]};font-size:0.78em;">'
                f'V{row.get("version") or 1}</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                f'{row.get("category","")} · 来源：{row.get("source","") or "—"} · '
                f'发布人：{row.get("publisher","") or "—"} · 审核人：{row.get("auditor","") or "—"} · '
                f'生效 {row.get("effective_date","") or "—"}'
                + (f' · 失效 {row.get("expire_date","")}' if row.get("expire_date") else "")
                + f' · 被引用 {row.get("cite_count") or 0} 次'
            )
            act_cells = []
            if status == "草稿":
                act_cells.append(("✏️ 编辑", "edit"))
                act_cells.append(("📨 提交审核", "submit"))
                act_cells.append(("🗑️ 删除", "delete"))
            elif status == "待审核":
                act_cells.append(("🔍 审核", "audit"))
                act_cells.append(("↩️ 撤回", "withdraw"))
            elif status == "审核不通过":
                act_cells.append(("✏️ 编辑", "edit"))
                act_cells.append(("📨 重新提交", "submit"))
            elif status == "已发布":
                act_cells.append(("📝 新版本", "new_version"))
                act_cells.append(("⏬ 下架", "down"))
            act_cells.append(("📄 详情", "detail"))
            cols = st.columns(len(act_cells))
            for col, (label, action) in zip(cols, act_cells):
                with col:
                    if st.button(label, key=f"kb_{action}_{kid}", width="stretch"):
                        if action in ("edit", "new_version"):
                            st.session_state["_kb_form_mode"] = action
                            st.session_state["_kb_form_id"] = kid
                        elif action == "submit":
                            ok, msg = submit_review(kid, actor=_actor)
                            st.toast(msg, icon="📨" if ok else "⚠️")
                            st.rerun()
                        elif action == "withdraw":
                            ok, msg = withdraw_review(kid, actor=_actor)
                            st.toast(msg, icon="↩️" if ok else "⚠️")
                            st.rerun()
                        elif action == "delete":
                            st.session_state[f"_kbdel_{kid}"] = True
                            st.rerun()
                        elif action == "audit":
                            st.session_state[f"_kbaudit_{kid}"] = True
                            st.rerun()
                        elif action == "down":
                            st.session_state[f"_kbdown_{kid}"] = True
                            st.rerun()
                        elif action == "detail":
                            st.session_state[f"_kbd_{kid}"] = not st.session_state.get(f"_kbd_{kid}", False)
                            st.rerun()

            # 删除草稿二次确认
            if st.session_state.get(f"_kbdel_{kid}"):
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ 确认删除草稿", key=f"kbdel_yes_{kid}", width="stretch"):
                        ok, msg = delete_knowledge(kid, actor=_actor)
                        st.session_state.pop(f"_kbdel_{kid}", None)
                        st.toast(msg, icon="🗑️" if ok else "⚠️")
                        st.rerun()
                with c2:
                    if st.button("↩️ 取消", key=f"kbdel_no_{kid}", width="stretch"):
                        st.session_state.pop(f"_kbdel_{kid}", None)
                        st.rerun()

            # 审核
            if st.session_state.get(f"_kbaudit_{kid}"):
                st.markdown(f"**审核 #{kid}**（发布人：{row.get('publisher','')}，指定审核人：{row.get('auditor','')}）")
                with st.form(key=f"audit_form_{kid}"):
                    a_decision = st.radio("审核结论", ["通过", "不通过"], horizontal=True,
                                          key=f"audit_dec_{kid}")
                    a_opinion = st.text_input("审核意见（不通过时必填）", key=f"audit_op_{kid}")
                    if st.form_submit_button("✅ 确认审核", width="stretch"):
                        ok, msg = audit_knowledge(kid, a_decision == "通过",
                                                  opinion=a_opinion, actor=_actor)
                        st.session_state.pop(f"_kbaudit_{kid}", None)
                        st.toast(msg, icon="✅" if ok else "⚠️")
                        st.rerun()
                if st.button("↩️ 取消审核", key=f"kbaudit_no_{kid}"):
                    st.session_state.pop(f"_kbaudit_{kid}", None)
                    st.rerun()

            # 下架二次确认（原因必填）
            if st.session_state.get(f"_kbdown_{kid}"):
                st.markdown("**⏬ 下架该条目**（下架后不再被自动回答引用）")
                d_reason = st.text_input("下架原因（必填）", key=f"down_reason_{kid}")
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ 确认下架", key=f"kbdown_yes_{kid}", width="stretch"):
                        ok, msg = take_down_knowledge(kid, d_reason, actor=_actor)
                        st.session_state.pop(f"_kbdown_{kid}", None)
                        st.toast(msg, icon="⏬" if ok else "⚠️")
                        st.rerun()
                with c2:
                    if st.button("↩️ 取消", key=f"kbdown_no_{kid}", width="stretch"):
                        st.session_state.pop(f"_kbdown_{kid}", None)
                        st.rerun()

            # 详情
            if st.session_state.get(f"_kbd_{kid}"):
                with st.container(border=True):
                    st.markdown("**📄 条目详情**")
                    st.write(f"**标题**：{row.get('title','')}（V{row.get('version') or 1}）")
                    st.write(f"**分类**：{row.get('category','')} · **状态**：{status}")
                    st.write(f"**来源**：{row.get('source','') or '—'} · **政策文号**：{row.get('policy_number','') or '—'}")
                    st.write(f"**发布人**：{row.get('publisher','') or '—'} · **审核人**：{row.get('auditor','') or '—'}")
                    st.write(f"**生效日期**：{row.get('effective_date','') or '—'} · **失效日期**：{row.get('expire_date','') or '长期有效'}")
                    st.write(f"**适用地区**：{row.get('applicable_area','') or '全社区通用'} · **附件**：{row.get('attachment','') or '无'}")
                    st.write(f"**关键词**：{row.get('keywords','') or '—'} · **被引用**：{row.get('cite_count') or 0} 次")
                    if row.get("audit_opinion"):
                        st.warning(f"审核意见/下架原因：{row['audit_opinion']}")
                    st.markdown("**📖 政策原文**：")
                    st.info(row.get("content") or "（无原文）")
                    st.markdown("**💡 通俗解读**：")
                    st.success(row.get("plain_interpretation") or "（无）")
                    st.markdown("**📌 摘要**：")
                    st.caption(row.get("summary") or "（无）")

                    st.markdown("**🕘 版本历史**（当前生效高亮）：")
                    for v in get_version_history(kid):
                        vtag = "✅ 当前" if v.get("is_current") else "📦 历史"
                        st.caption(
                            f'{vtag} V{v.get("version") or 1} · {v.get("audit_status")} · '
                            f'{v.get("title","")[:24]}'
                            + (f' · {v.get("audit_opinion")}' if v.get("audit_opinion") else "")
                        )
                    st.markdown("**📜 操作留痕**（最近 10 条）：")
                    for act in get_knowledge_activity(kid, limit=10):
                        st.caption(
                            f'{act["actor"]} · {act["action"]} · {(act["created_at"] or "")[:16]}'
                            + (f' · {act["detail"]}' if act.get("detail") else "")
                        )
                    if st.button("❌ 收起详情", key=f"kbd_close_{kid}", width="stretch"):
                        st.session_state[f"_kbd_{kid}"] = False
                        st.rerun()

# ================================================================ 人工待回复

with tab_reply:
    pending = get_pending_reply_questions()
    if not pending:
        st.success("当前没有待回复的提问 🎉")
    for q in pending:
        qid = q["id"]
        info = get_question_deadline_info(q)
        overdue = info["overdue"]
        show_status = "超时未回复" if overdue else "已转人工"
        with st.container(border=True):
            st.markdown(
                f'<span style="font-weight:700;color:{TOKEN["text"]};">#{qid} {q["summary"]}</span>'
                f'&nbsp;{_tag_html(show_status)}',
                unsafe_allow_html=True,
            )
            st.caption(
                f'{masked_nickname(q["user_id"])} · {q["source"]} · {q["q_type"]} · '
                f'提问 {(q["created_at"] or "")[:16]}'
            )
            if overdue:
                st.markdown(
                    f'<span style="color:{TOKEN["danger"]};font-size:0.85em;font-weight:700;">'
                    f'⏰ 已超时 {abs(info["remaining_hours"]):.1f} 小时，请尽快回复</span>',
                    unsafe_allow_html=True,
                )
            else:
                st.caption(f'⏳ 剩余时限：{info["remaining_hours"]:.1f} 小时（24h 内回复）')
            with st.expander("💬 查看并回复"):
                st.markdown(f"**完整提问**：{q['question']}")
                if q.get("auto_answer"):
                    st.markdown("**🤖 自动回答**：")
                    st.info(q["auto_answer"].replace("\n", "  \n"))
                if q.get("feedback"):
                    st.caption(
                        f"居民反馈：{q['feedback']}"
                        + (f"（{q['feedback_reason']}）" if q.get("feedback_reason") else "")
                        + f" · 第 {q.get('loop_count') or 0} 次循环"
                    )
                with st.form(key=f"reply_form_{qid}"):
                    cite_opts = get_published_options()
                    opt_labels = ["（不引用知识库）"] + [o["label"] for o in cite_opts]
                    sel = st.selectbox("引用知识库（选填，自动附带「参考：XX政策」）",
                                       opt_labels, key=f"cite_{qid}")
                    reply = st.text_area("回复内容（必填，≤2000字）", key=f"reply_{qid}", height=110)
                    if st.form_submit_button("✅ 提交回复", width="stretch"):
                        cid = None
                        if sel != opt_labels[0]:
                            cid = next(o["id"] for o in cite_opts if o["label"] == sel)
                        ok, msg, _ = reply_question(qid, reply, actor=_actor, cited_knowledge_id=cid)
                        if ok:
                            st.toast("已回复，居民端将显示回复", icon="✅")
                            st.rerun()
                        else:
                            st.error(msg)

# ================================================================ 提问记录

with tab_questions:
    stf2 = st.radio(
        "状态筛选",
        ["全部", "已自动回答", "已转人工", "已回复", "已结束", "需线下沟通"],
        horizontal=True, key="pq_status_filter",
    )
    qs = get_questions(status=None if stf2 == "全部" else stf2)
    if not qs:
        st.info("暂无提问记录。")
    for q in qs[:100]:
        qid = q["id"]
        info = get_question_deadline_info(q)
        show_status = "超时未回复" if (q["status"] == "已转人工" and info["overdue"]) else q["status"]
        with st.container(border=True):
            st.markdown(
                f'<span style="font-weight:700;color:{TOKEN["text"]};">#{qid} {q["summary"]}</span>'
                f'&nbsp;{_tag_html(show_status)}',
                unsafe_allow_html=True,
            )
            st.caption(
                f'{masked_nickname(q["user_id"])} · {q["source"]} · {q["q_type"]} · '
                f'{(q["created_at"] or "")[:16]}'
            )
            with st.expander("📄 详情"):
                st.markdown(f"**完整提问**：{q['question']}")
                if q.get("auto_answer"):
                    st.markdown("**🤖 自动回答**：")
                    st.info(q["auto_answer"].replace("\n", "  \n"))
                if q.get("answer"):
                    st.markdown("**🧑‍💼 人工回复**：")
                    st.success(q["answer"].replace("\n", "  \n"))
                    st.caption(f'回复人：{q.get("answered_by") or ""} · {(q.get("answered_at") or "")[:16]}')
                if q.get("feedback"):
                    st.caption(
                        f"居民反馈：{q['feedback']}"
                        + (f"（{q['feedback_reason']}）" if q.get("feedback_reason") else "")
                    )
                st.markdown("**📜 状态留痕**：")
                for act in get_question_timeline(qid):
                    st.caption(
                        f'{act["actor"]} · {act["action"]} · {(act["created_at"] or "")[:16]}'
                        + (f' · {act["detail"]}' if act.get("detail") else "")
                    )

# ================================================================ 高频统计

with tab_stats:
    period = st.radio("时间范围", ["近7天", "近30天", "全部"], horizontal=True, key="stat_period")
    days = {"近7天": 7, "近30天": 30, "全部": None}[period]
    s = get_frequency_stats(days)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        stat("提问次数", str(s["total_questions"]), TOKEN["accent"])
    with c2:
        stat("自动回答成功", str(s["auto_success"]), TOKEN["success"])
    with c3:
        stat("转人工", str(s["transferred"]), TOKEN["warning"])
    with c4:
        stat("无帮助", str(s["unhelpful"]), TOKEN["danger"])
    with c5:
        stat("匹配失败", str(s["match_failed"]), TOKEN["danger"],
             sub=f'平均回复 {s["avg_reply_hours"]} 小时' if s["avg_reply_hours"] is not None else "暂无回复")

    st.markdown("---")
    st.markdown("**📈 近 7 天提问量趋势**")
    df = pd.DataFrame(s["trend"])
    chart = alt.Chart(df).mark_bar(size=22).encode(
        x=alt.X("day:N", title=None),
        y=alt.Y("count:Q", title="提问数"),
        tooltip=["day", "count"],
    )
    st.altair_chart(configure_altair(chart), width="stretch")

    st.markdown("---")
    st.markdown("**🔥 高频提问 TOP10**（便于补充知识库）")
    if s["top_questions"]:
        for i, t in enumerate(s["top_questions"], 1):
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;padding:6px 2px;'
                f'border-bottom:1px solid {TOKEN["border"]};font-size:0.88em;">'
                f'<span style="color:{TOKEN["text_muted"]};font-weight:700;">{i}</span>'
                f'<span style="flex:1;color:{TOKEN["text"]};">{t["summary"]}</span>'
                f'<span style="color:{TOKEN["text_muted"]};">{t["c"]} 次</span></div>',
                unsafe_allow_html=True,
            )
    else:
        st.caption("暂无数据")

    st.markdown("---")
    st.markdown("**❌ 自动回答失败**（两类分开统计）")
    f1, f2 = st.tabs(["① 匹配失败", "② 居民点无帮助"])
    with f1:
        if s["match_failed_list"]:
            for f in s["match_failed_list"]:
                st.caption(f'{f["created_at"][:16]} · {f["actor"]} · {f["detail"]}')
        else:
            st.caption("暂无匹配失败记录")
    with f2:
        if s["unhelpful_list"]:
            for u in s["unhelpful_list"]:
                st.caption(
                    f'{(u["created_at"] or "")[:16]} · {u["target_title"] or u["actor"]} · '
                    f'原因：{u["detail"] or "—"}'
                )
        else:
            st.caption("暂无无帮助记录")

    if s["expiring"]:
        st.markdown("---")
        st.markdown("**⏰ 7 天内即将到期的政策**")
        for e in s["expiring"]:
            st.caption(f'#{e["id"]} {e["title"]} · 失效日期 {e["expire_date"]}')
