# ui/pages/policy.py
"""📖 政策问答（居民端）— 提问、自动回答、有帮助/无帮助、转人工、我的提问记录。

未注册到 app.py 路由，由项目负责人统一注册（建议标题「政策问答」）。
"""
import streamlit as st

from data.db_user import get_current_user
from data.db_policy import (
    ask_question, transfer_to_human, feedback_question, delete_question,
    get_my_questions, get_common_questions, masked_nickname,
    STATUS_COLORS, POLICY_CATEGORIES,
)
from ui.components import TOKEN, page_header

_profile = get_current_user()
_user_id = _profile.get("id", 1)
_nick = masked_nickname(_user_id)

page_header("📖 政策问答", "政策咨询与办事指引 · 先自动回答，后人工兜底 · 负责人 24 小时内回复。", "问")


def _tag_html(status: str) -> str:
    color = STATUS_COLORS.get(status, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}18;color:{color};'
        f'border:1px solid {color}44;border-radius:999px;padding:2px 10px;'
        f'font-size:0.75em;font-weight:600;white-space:nowrap;">{status}</span>'
    )


def _md(text: str) -> None:
    """带换行的 markdown（回答里有多行）。"""
    st.markdown((text or "").replace("\n", "  \n"))


tab_ask, tab_mine, tab_hot = st.tabs(["💬 提问", "📋 我的提问", "🔥 常见问题"])

# ================================================================ 提问

with tab_ask:
    c_cat, _ = st.columns([2, 3])
    with c_cat:
        cat = st.selectbox("分类（可先筛选再提问）", ["全部"] + POLICY_CATEGORIES,
                           key="pol_cat")
    question = st.text_area(
        "想咨询什么？",
        placeholder="例如：养老金怎么领取？办理高龄补贴需要什么材料？",
        max_chars=200, height=90, key="pol_q",
    )
    if st.button("提问", type="primary", width="stretch", key="pol_ask_btn"):
        q = (question or "").strip()
        if not q:
            st.error("请输入您想咨询的问题")
        else:
            cat_val = None if cat == "全部" else cat
            result = ask_question(_user_id, q, source="居民端", category=cat_val, actor=_nick)
            st.session_state["_pol_latest"] = result
            st.session_state["_pol_unhelp"] = None
            st.rerun()

    latest = st.session_state.get("_pol_latest")
    if latest:
        st.markdown("---")
        if latest.get("matched"):
            qid = latest["question_id"]
            kb = latest.get("knowledge") or {}
            st.markdown(
                f'<div style="background:{TOKEN["card_bg"]};border-radius:{TOKEN["radius_card"]};'
                f'padding:14px 18px;box-shadow:{TOKEN["shadow_sm"]};margin-bottom:8px;">'
                f'<span style="font-size:0.8em;color:{TOKEN["text_muted"]};">您的问题：</span>'
                f'<span style="font-weight:700;color:{TOKEN["text"]};">{latest["question"]}</span>'
                f'&nbsp;{_tag_html("已自动回答")}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("**🤖 自动回答**")
            _md(latest["auto_answer"])
            if kb.get("is_community"):
                st.caption("本指引由社区整理，仅供参考")
            with st.expander("📄 查看政策原文"):
                st.markdown(kb.get("content") or "（无政策原文，仅有通俗解读）")
                if kb.get("policy_number"):
                    st.caption(f"政策文号：{kb['policy_number']}")
                if kb.get("attachment"):
                    from utils.uploads import resolve_path
                    _path = resolve_path(kb["attachment"])
                    if _path:
                        try:
                            with open(_path, "rb") as fh:
                                _data = fh.read()
                            st.download_button(
                                "⬇️ 查看政策原文（PDF）", data=_data,
                                file_name=str(kb["attachment"]).split("/")[-1] or "政策原文.pdf",
                                mime="application/pdf",
                            )
                        except Exception:
                            st.info(f"附件：{kb['attachment']}")
                    else:
                        st.info(f"附件：{kb['attachment']}")

            fb_done = st.session_state.get(f"_fb_{qid}") == "done"
            unhelp_qid = st.session_state.get("_pol_unhelp")
            if fb_done:
                st.success("感谢反馈，我们会持续优化回答内容")
            else:
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("👍 有帮助", key=f"fb_help_{qid}", width="stretch"):
                        feedback_question(qid, True, actor=_nick)
                        st.session_state[f"_fb_{qid}"] = "done"
                        st.rerun()
                with c2:
                    if st.button("👎 无帮助", key=f"fb_unhelp_{qid}", width="stretch"):
                        feedback_question(qid, False, actor=_nick)
                        st.session_state["_pol_unhelp"] = qid
                        st.rerun()

            # 无帮助后提示可转人工（不自动转）
            show_transfer_prompt = unhelp_qid == qid
            if show_transfer_prompt:
                st.warning("没有帮到您吗？可以转人工，由负责人为您详细解答。")
            # 转人工（二次确认）
            conf_key = f"_tf_conf_{qid}"
            if st.session_state.get(conf_key):
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("✅ 确认转人工", key=f"tf_yes_{qid}", type="primary", width="stretch"):
                        ok, msg, _ = transfer_to_human(question_id=qid, actor=_nick)
                        st.session_state.pop(conf_key, None)
                        st.session_state["_pol_latest"] = None
                        st.toast(msg, icon="🧑‍💼")
                        st.rerun()
                with c2:
                    if st.button("↩️ 再想想", key=f"tf_no_{qid}", width="stretch"):
                        st.session_state.pop(conf_key, None)
                        st.rerun()
            else:
                btn_label = "🧑‍💼 转人工（负责人 24 小时内回复）"
                if st.button(btn_label, key=f"tf_btn_{qid}",
                             type="primary" if show_transfer_prompt else "secondary",
                             width="stretch"):
                    st.session_state[conf_key] = True
                    st.rerun()
        else:
            reason = latest.get("reason")
            if reason == "empty":
                st.error("请输入您想咨询的问题")
            elif reason == "too_long":
                st.error("提问最长 200 字")
            else:
                st.info("暂未找到答案，是否转人工？负责人将在 24 小时内回复您。")
                conf_key = "_tf_conf_new"
                if st.session_state.get(conf_key):
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ 确认转人工", key="tf_new_yes", type="primary", width="stretch"):
                            ok, msg, qid = transfer_to_human(
                                user_id=_user_id, question=latest["question"],
                                summary=latest.get("summary"), q_type=latest.get("q_type"),
                                source="居民端", actor=_nick,
                            )
                            st.session_state.pop(conf_key, None)
                            st.session_state["_pol_latest"] = None
                            if ok:
                                st.toast(msg, icon="🧑‍💼")
                            else:
                                st.error(msg)
                            st.rerun()
                    with c2:
                        if st.button("↩️ 再想想", key="tf_new_no", width="stretch"):
                            st.session_state.pop(conf_key, None)
                            st.rerun()
                else:
                    if st.button("🧑‍💼 转人工", key="tf_new_btn", type="primary", width="stretch"):
                        st.session_state[conf_key] = True
                        st.rerun()

# ================================================================ 我的提问

with tab_mine:
    my_questions = get_my_questions(_user_id)
    if not my_questions:
        st.info("还没有提问记录，去「提问」页问一个问题吧。")
    for q in my_questions:
        qid = q["id"]
        st.markdown("---")
        st.markdown(
            f'<span style="font-weight:700;color:{TOKEN["text"]};">{q["summary"]}</span>'
            f'&nbsp;{_tag_html(q["status"])}',
            unsafe_allow_html=True,
        )
        st.caption(
            f'{q["source"]} · {q["q_type"]} · {(q["created_at"] or "")[:16]} · {_nick}'
        )
        with st.expander("查看详情"):
            st.markdown(f"**完整提问**：{q['question']}")
            if q.get("auto_answer"):
                st.markdown("**🤖 自动回答**：")
                _md(q["auto_answer"])
            if q.get("answer"):
                st.markdown("**🧑‍💼 人工回复**：")
                st.info(q["answer"].replace("\n", "  \n"))
                st.caption(f'回复人：{q.get("answered_by") or ""} · {(q.get("answered_at") or "")[:16]}')
            if q.get("feedback"):
                fb = q["feedback"] + (f"（{q['feedback_reason']}）" if q.get("feedback_reason") else "")
                st.caption(f"您的反馈：{fb}")

            if q["status"] == "已回复":
                if st.session_state.get(f"_fbq_{qid}") == "done":
                    st.success("已记录您的反馈")
                else:
                    with st.form(key=f"fb_form_{qid}"):
                        satisfied = st.radio("这个问题解决了吗？", ["已解决", "未解决"],
                                             key=f"fb_radio_{qid}", horizontal=True)
                        reason = st.text_input("未解决原因（必填）", key=f"fb_reason_{qid}")
                        if st.form_submit_button("提交反馈", width="stretch"):
                            ok, msg, _ = feedback_question(
                                qid, satisfied == "已解决",
                                reason if satisfied == "未解决" else "", actor=_nick,
                            )
                            if ok:
                                st.session_state[f"_fbq_{qid}"] = "done"
                                st.toast({"感谢反馈": "感谢反馈 👍", "已结束": "已为您关闭该提问 ✅",
                                          "loop": "已退回人工继续处理 🔄",
                                          "offline": "已超过 3 次循环，转线下沟通 ☎️",
                                          "unhelpful": "已记录，可转人工咨询"}.get(msg, msg), icon="📨")
                                st.rerun()
                            else:
                                st.error(msg)

            # 删除限制：只能删「已结束」或「已自动回答且未转人工」
            if q["status"] in ("已结束", "已自动回答"):
                del_key = f"_delc_{qid}"
                if st.session_state.get(del_key):
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ 确认删除", key=f"del_yes_{qid}", width="stretch"):
                            ok, msg, _ = delete_question(qid, _user_id, actor=_nick)
                            st.session_state.pop(del_key, None)
                            st.toast(msg, icon="🗑️")
                            st.rerun()
                    with c2:
                        if st.button("↩️ 取消", key=f"del_no_{qid}", width="stretch"):
                            st.session_state.pop(del_key, None)
                            st.rerun()
                else:
                    if st.button("🗑️ 删除记录", key=f"del_btn_{qid}", width="stretch"):
                        st.session_state[del_key] = True
                        st.rerun()
            else:
                st.caption("该提问正在处理中，暂不能删除，可等待处理或联系负责人。")

# ================================================================ 常见问题

with tab_hot:
    # R44：按分类展示常见问题（最多 10 条，每条带分类标签）
    _qtypes = ["全部", "社保医保", "养老服务", "住房保障", "办事指引", "社区规定", "其他"]
    _qt = st.selectbox("分类", _qtypes, key="hot_qtype")
    hot = get_common_questions(10, q_type=None if _qt == "全部" else _qt)
    if not hot:
        st.info("暂无常见问题，快去提问吧。")
    else:
        for i, h in enumerate(hot, 1):
            _qt_label = (h.get("q_type") or "其他")
            _qt_color = "#4f46e5" if _qt_label == "社保医保" else "#059669" if _qt_label == "养老服务" else "#d97706"
            st.markdown(
                f'<div style="display:flex;align-items:center;gap:10px;padding:8px 2px;'
                f'border-bottom:1px solid {TOKEN["border"]};font-size:0.9em;">'
                f'<span style="color:{TOKEN["text_muted"]};font-weight:700;">{i}</span>'
                f'<span style="flex:1;color:{TOKEN["text"]};">{h["summary"]}</span>'
                f'<span style="background:{_qt_color}1f;color:{_qt_color};border:1px solid {_qt_color};'
                f'border-radius:99px;padding:1px 10px;font-size:0.75em;font-weight:700;">{_qt_label}</span>'
                f'<span style="color:{TOKEN["text_muted"]};font-size:0.78em;">{h["c"]} 次</span>'
                f'</div>',
                unsafe_allow_html=True,
            )
