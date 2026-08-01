# ui/login.py
"""Login page — clean authentication gate."""
import streamlit as st
from data.db_user import authenticate, create_user, get_user_by_username


def render_login():
    from ui.theme import get_theme
    is_dark = get_theme() == "dark"

    page_bg = "#0a0a0f" if is_dark else "#fafafa"

    st.markdown(f"""
<style>
    .stApp {{ background: {page_bg} !important; }}
    [data-testid="stSidebar"] {{ display: none !important; }}
    [data-testid="stSidebar"] * {{ display: none !important; }}
</style>
""", unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 1.6, 1])

    with col_m:
        st.markdown(f"""
        <div style="text-align:center;padding:32px 0 20px;">
            <div style="font-size:1.35em;font-weight:700;color:{("#e8e8ed" if is_dark else "#1a1a1a")};
                letter-spacing:-0.01em;margin-bottom:4px;">CampusInsight</div>
            <div style="font-size:0.8em;color:{("#5e5e6a" if is_dark else "#a0a0a0")};">
                校园治理平台</div>
        </div>
        """, unsafe_allow_html=True)

                st.markdown(
            f'<div style="text-align:center;margin:8px 0 6px;font-size:0.75em;'
            f'color:{("#5e5e6a" if is_dark else "#a0a0a0")};">快速体验</div>',
            unsafe_allow_html=True,
        )
        c_demo1, c_demo2 = st.columns(2)
        with c_demo1:
            if st.button("学生", key="demo_student", use_container_width=True):
                _login_demo("student")
        with c_demo2:
            if st.button("教师", key="demo_teacher", use_container_width=True):
                _login_demo("teacher")

        st.markdown("---")

        tab_login, tab_register = st.tabs(["登录", "注册"])

        with tab_login:
            _render_login_form(is_dark)
        with tab_register:
            _render_register_form(is_dark)


def _render_login_form(is_dark: bool):
    muted_color = "#5e5e6a" if is_dark else "#a0a0a0"

    username = st.text_input("用户名", key="login_username", placeholder="请输入用户名")
    password = st.text_input("密码", type="password", key="login_password", placeholder="请输入密码")

    if st.button("登录", type="primary", width="stretch", key="login_btn"):
        if not username or not password:
            st.error("请输入用户名和密码")
            return
        uid = authenticate(username, password)
        if uid:
            st.session_state["_login_user_id"] = uid
            st.session_state["_ob_role"] = ""
            st.rerun()
        else:
            st.error("用户名或密码错误")

    st.markdown(
        f'<div style="font-size:0.7em;color:{muted_color};margin-top:12px;text-align:center;">'
        f'演示账号：<code>student1</code> / <code>teacher1</code> — 密码：<code>123</code></div>',
        unsafe_allow_html=True,
    )


def _render_register_form(is_dark: bool):
    """Registration form (student only)."""
    muted_color = "#5e5e6a" if is_dark else "#a0a0a0"

    new_username = st.text_input("用户名", key="reg_username", placeholder="请设置用户名")
    new_password = st.text_input("密码", type="password", key="reg_password", placeholder="请设置密码")
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        school = st.text_input("院系", key="reg_school", placeholder="如：计算机学院")
    with col_n2:
        grade = st.text_input("年级", key="reg_grade", placeholder="如：2024")

    if st.button("注册", type="primary", width="stretch", key="reg_btn"):
        if not new_username or not new_password:
            st.error("请填写必填项")
            return
        if get_user_by_username(new_username):
            st.error("用户名已存在")
            return
        uid = create_user(new_username, new_password, school, grade, role="student")
        if uid:
            st.session_state["_login_user_id"] = uid
            st.session_state["_ob_role"] = ""
            st.rerun()
        else:
            st.error("注册失败")

    st.markdown(
        f'<div style="font-size:0.7em;color:{muted_color};margin-top:8px;text-align:center;">'
        f'学生自行注册。教师账号由管理员预创建。</div>',
        unsafe_allow_html=True,
    )


def _login_demo(role: str):
    """Quick demo login."""
    from data.db_user import list_users
    users = list_users()
    target = [u for u in users if u.get("role") == role]
    if target:
        uid = target[0].get("id")
        st.session_state["_login_user_id"] = uid
        st.session_state["_ob_role"] = role
        st.rerun()
