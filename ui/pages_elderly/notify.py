"""🔊 听通知 — 大字通知列表 + TTS 朗读."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

st.markdown('<div class="elderly-title">🔊 听通知</div>', unsafe_allow_html=True)
st.caption("点「朗读」按钮，系统会念给您听。")

from data.db_notifications import get_notifications, mark_all_read

notifs = get_notifications(uid, limit=10) if uid else []

if not notifs:
    st.info("暂无通知。")
else:
    if st.button("全部标为已读", key="mark_all_read", width="stretch"):
        if uid:
            mark_all_read(uid)
        st.rerun()
    for n in notifs:
        big_card(
            f"<strong>{n.get('title', '')}</strong>"
            + (f"<br>{n.get('content', '')}" if n.get('content') else "")
        )
        tts_speak((n.get('title', '') or '') + "。" + (n.get('content', '') or ''))

if st.button("🏠 返回首页", key="notify_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
