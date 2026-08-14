"""📋 我的工单 — 大字版进度查看."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

st.markdown('<div class="elderly-title">📋 我的工单</div>', unsafe_allow_html=True)
st.caption("您上报过的问题，都在这里。")

from data.database import get_my_issues, get_my_anonymous_issues
from ui.components import resolve_author

_author = resolve_author(profile)
issues = get_my_issues(_author, limit=20)
anon = get_my_anonymous_issues(uid, limit=20) if uid else []
seen_ids = {i["id"] for i in issues}
issues += [a for a in anon if a["id"] not in seen_ids]

_status_emoji = {"待处理": "⏳", "处理中": "🔄", "已解决": "✅", "待复核": "🧐"}

if not issues:
    st.info("还没有工单。有问题就点「一句话上报」。")
else:
    for i in issues[:10]:
        emoji = _status_emoji.get(i.get("status", ""), "📌")
        assignee = i.get("assignee") or "未指派"
        big_card(
            f"{emoji} <strong>#{i['id']} {i.get('title', '')[:30]}</strong><br>"
            f"状态：{i.get('status', '')} · 处理人：{assignee}"
        )

if st.button("🏠 返回首页", key="progress_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
