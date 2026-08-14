# ui/guard.py
"""角色访问守卫 — 防止越权访问网格员/居民页面。

Streamlit 的 st.navigation 已按角色路由，这里是防御层：万一未来改路由或页面被
直接引用，也能在页面级兜住越权（居民进不了网格员页、反之亦然）。
"""
import streamlit as st


def require_role(required: str) -> None:
    """当前登录角色和 required 对不上就拦下这个页面。"""
    profile = st.session_state.get("user_profile") or {}
    role = profile.get("role", "resident")
    if role != required:
        st.error("⛔ 无权限访问该页面，请切换到对应角色。")
        st.stop()
