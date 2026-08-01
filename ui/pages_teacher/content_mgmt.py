# ui/pages_teacher/content_mgmt.py
"""📢 内容发布 — 发布通知、创建议题、管理已发布内容."""
import streamlit as st
from ui.components import TOKEN
from ui.cache import cached_knowledge_base, cached_active_topics, invalidate_content
from data.database import get_db, create_topic, close_topic
import logging
_log = logging.getLogger(__name__)

st.markdown(
    f'<span style="font-size:1.2em;font-weight:800;color:{TOKEN["text"]};">'
    f'📢 内容发布</span>',
    unsafe_allow_html=True,
)
st.caption("发布校园通知和讨论议题，管理已发布的内容。")

pub_tab = st.radio(
    "发布类型",
    ["📝 发布通知", "💬 创建议题"],
    horizontal=True,
    label_visibility="collapsed",
    key="_content_pub_type",
)

st.markdown("---")

if pub_tab == "📝 发布通知":
    st.markdown("### 📝 发布新通知")

    notice_title = st.text_input("通知标题", placeholder="输入通知标题...", key="_notice_title")
    notice_cat = st.selectbox(
        "分类",
        ["通知", "事件", "日历", "百科"],
        key="_notice_cat",
    )
    notice_content = st.text_area("通知内容", placeholder="输入通知正文...", height=150, key="_notice_content")
    notice_keywords = st.text_input("关键词（逗号分隔）", placeholder="停水,检修,周三", key="_notice_keywords")

    if st.button("🚀 发布通知", type="primary", width="stretch"):
        if not notice_title:
            st.warning("请输入通知标题")
        elif not notice_content:
            st.warning("请输入通知内容")
        else:
            with get_db() as conn:
                conn.execute(
                    "INSERT INTO knowledge_base (category, title, content, keywords) VALUES (?,?,?,?)",
                    (notice_cat, notice_title, notice_content, notice_keywords),
                )
                conn.commit()
            invalidate_content()
            st.toast(f"通知「{notice_title}」已发布", icon="✅")
            for k in ["_notice_title", "_notice_content", "_notice_keywords", "_notice_cat"]:
                st.session_state.pop(k, None)
            st.rerun()

else:
    st.markdown("### 💬 创建讨论议题")

    topic_title = st.text_input("议题标题", placeholder="输入议题标题...", key="_topic_title")
    topic_cat = st.selectbox(
        "分类",
        ["校园管理", "教学事务", "生活服务", "学生权益", "其他"],
        key="_topic_cat",
    )
    topic_desc = st.text_area("议题简介", placeholder="描述议题背景和讨论要点...", height=150, key="_topic_desc")

    if st.button("🚀 创建议题", type="primary", width="stretch"):
        if not topic_title:
            st.warning("请输入议题标题")
        elif not topic_desc:
            st.warning("请输入议题简介")
        else:
            tid = create_topic(topic_title, topic_desc, topic_cat, created_by_agent=False)
            invalidate_content()
            st.toast(f"议题「{topic_title}」已创建（#{tid}）", icon="✅")
            for k in ["_topic_title", "_topic_desc", "_topic_cat"]:
                st.session_state.pop(k, None)
            st.rerun()

st.markdown("---")

st.markdown("### 📋 最近发布")
col1, col2 = st.columns(2)

_confirm_delete_key = "_content_confirm_delete"

with col1:
    st.markdown("**📢 通知 / 百科**")
    notices = cached_knowledge_base(limit=10)
    if not notices:
        st.caption("暂无已发布的通知。")
    else:
        for entry in notices:
            eid = entry["id"]
            cat = entry.get("category", "")
            title = entry.get("title", "")[:30]
            content = entry.get("content", "")[:60]

            # Check if this entry is pending delete confirmation
            confirming = st.session_state.get(_confirm_delete_key) == eid

            with st.container(border=True):
                c_left, c_right = st.columns([5, 1.5])
                with c_left:
                    st.markdown(
                        f'<div style="font-size:0.85em;padding:4px 0;">'
                        f'📌 <strong>{title}</strong>'
                        f'<br><span style="font-size:0.78em;color:{TOKEN["text_muted"]};">'
                        f'{cat} · {content}...</span></div>',
                        unsafe_allow_html=True,
                    )
                with c_right:
                    if confirming:
                        b1, b2 = st.columns(2)
                        with b1:
                            if st.button("✅ 确认", key=f"del_confirm_{eid}", width="stretch"):
                                with get_db() as conn:
                                    conn.execute("DELETE FROM knowledge_base WHERE id = ?", (eid,))
                                    conn.commit()
                                invalidate_content()
                                st.session_state.pop(_confirm_delete_key, None)
                                st.toast(f"已删除「{title}」", icon="🗑️")
                                st.rerun()
                        with b2:
                            if st.button("❌ 取消", key=f"del_cancel_{eid}", width="stretch"):
                                st.session_state.pop(_confirm_delete_key, None)
                                st.rerun()
                    else:
                        if st.button("🗑️ 删除", key=f"del_notice_{eid}", width="stretch"):
                            st.session_state[_confirm_delete_key] = eid
                            st.rerun()

with col2:
    st.markdown("**💬 议题管理**")

    # Show active topics first, then recently closed
    active_topics = cached_active_topics(limit=10)
    # Also fetch recently closed topics
    closed_topics = []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM discussion_topics WHERE is_active = 0 "
                "ORDER BY ended_at DESC LIMIT 5"
            ).fetchall()
            closed_topics = [dict(r) for r in rows]
    except Exception:  # non-critical: silent pass intended
        _log.debug("non-critical failure", exc_info=True)
        pass

    all_topics = list(active_topics) + list(closed_topics)

    if not all_topics:
        st.caption("暂无议题。")
    else:
        for topic in all_topics:
            tid = topic["id"]
            ttitle = topic.get("title", "")[:28]
            participants = topic.get("participant_count", 0)
            is_active = topic.get("is_active", 1)

            with st.container(border=True):
                c_left, c_right = st.columns([5, 1.5])
                with c_left:
                    status_badge = "🟢 进行中" if is_active else "🔒 已结束"
                    st.markdown(
                        f'<div style="font-size:0.85em;padding:4px 0;">'
                        f'💬 <strong>{ttitle}</strong>'
                        f'<br><span style="font-size:0.78em;color:{TOKEN["text_muted"]};">'
                        f'{status_badge} · {participants} 人参与</span></div>',
                        unsafe_allow_html=True,
                    )
                with c_right:
                    if is_active:
                        if st.button("🔒 结束", key=f"close_topic_{tid}", width="stretch",
                                     help="结束此议题讨论"):
                            close_topic(tid)
                            invalidate_content()
                            st.toast(f"议题「{ttitle}」已结束", icon="🔒")
                            st.rerun()
                    else:
                        ended = (topic.get("ended_at") or "")[:10]
                        st.caption(f"已于 {ended} 结束")
