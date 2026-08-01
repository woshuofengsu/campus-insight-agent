# ui/pages/notifications.py
"""🔔 消息中心 — 查看所有通知，标记已读."""
import streamlit as st
from ui.session_state import SS
from ui.components import TOKEN
from data.db_notifications import get_notifications, mark_read, mark_all_read, get_unread_count


try:
    unread = get_unread_count(st.session_state.get(SS.login_user_id, 0))
except Exception:
    unread = 0

st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">🔔 消息中心</span>'
    + (f'<span style="background:{TOKEN["danger"]};color:#fff;font-size:0.7em;font-weight:600;'
       f'padding:2px 8px;border-radius:99px;margin-left:8px;vertical-align:middle;">{unread} 条未读</span>'
       if unread else '')
    + '</div>',
    unsafe_allow_html=True,
)
st.caption("教师处理反馈、提案进展、系统提醒 — 全部在这里。")

if unread:
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("✅ 全部标为已读", width="stretch", type="primary"):
            n = mark_all_read(st.session_state.get(SS.login_user_id, 0))
            st.toast(f"已标记 {n} 条为已读", icon="✅")
            st.rerun()

st.markdown("---")

user_id = st.session_state.get(SS.login_user_id, 0)
if not user_id:
    st.info("请先登录。")
    st.stop()

notifications = get_notifications(user_id, limit=50)

if not notifications:
    # Empty state
    st.markdown(
        f'<div style="text-align:center;padding:48px 0;">'
        f'<div style="font-size:3em;margin-bottom:12px;">📭</div>'
        f'<div style="font-size:1em;font-weight:600;color:{TOKEN["text"]};">暂无消息</div>'
        f'<div style="font-size:0.8em;color:{TOKEN["text_muted"]};margin-top:4px;">'
        f'当老师处理你的报修或回复你的提案时，消息会出现在这里。</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()

type_config = {
    "issue_update":   ("📋", TOKEN["accent"]),
    "proposal_update": ("💡", TOKEN["accent"]),
    "health_alert":   ("🏥", TOKEN["danger"]),
    "system":         ("🔔", TOKEN["text_muted"]),
}

for n in notifications:
    nid = n["id"]
    ntype = n.get("type", "system")
    icon, color = type_config.get(ntype, ("🔔", TOKEN["text_muted"]))
    is_unread = not n.get("is_read", 0)
    created = (n.get("created_at", "") or "")[:16]

    # Card with left border accent for unread
    border_style = (
        f'border-left:3px solid {TOKEN["accent"]};'
        if is_unread else
        f'border-left:3px solid transparent;'
    )

    with st.container(border=True):
        st.markdown(
            f'<div style="{border_style}padding:4px 0 4px 12px;">'
            f'<div style="display:flex;align-items:flex-start;gap:8px;">'
            f'<span style="font-size:1.2em;">{icon}</span>'
            f'<div style="flex:1;">'
            f'<div style="font-size:0.9em;font-weight:{700 if is_unread else 500};'
            f'color:{TOKEN["text"]};">{n["title"]}</div>'
            f'<div style="font-size:0.8em;color:{TOKEN["text_sec"]};margin-top:2px;">'
            f'{n["content"]}</div>'
            f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};margin-top:4px;">'
            f'{created}</div>'
            f'</div>'
            + (f'<span style="background:{TOKEN["accent"]};width:8px;height:8px;'
               f'border-radius:50%;flex-shrink:0;margin-top:4px;" title="未读"></span>'
               if is_unread else '')
            + '</div></div>',
            unsafe_allow_html=True,
        )

        if is_unread:
            if st.button("✓ 标为已读", key=f"read_{nid}"):
                mark_read(nid)
                st.rerun()
