# ui/login.py
"""登录页 — 干净的鉴权入口。"""
import streamlit as st
from ui.components import TOKEN
from data.db_user import authenticate, create_user, get_user_by_username


def render_login():
    st.markdown(f"""
<style>
    .stApp {{ background: {TOKEN["page_bg"]} !important; }}
    [data-testid="stSidebar"] {{ display: none !important; }}
    [data-testid="stSidebar"] * {{ display: none !important; }}
</style>
""", unsafe_allow_html=True)

    col_l, col_m, col_r = st.columns([1, 1.6, 1])

    with col_m:
        st.markdown(f"""
        <div style="text-align:center;padding:28px 0 22px;">
            <div style="width:56px;height:56px;border-radius:16px;
                background:{TOKEN["brand_gradient"]};
                display:flex;align-items:center;justify-content:center;
                font-size:1.6em;margin:0 auto 14px;
                box-shadow:0 8px 24px rgba(79,70,229,0.35);">🏘️</div>
            <div style="font-size:1.5em;font-weight:800;color:{TOKEN["text"]};
                letter-spacing:-0.01em;line-height:1.2;">CommunityInsight</div>
            <div style="font-size:0.85em;color:{TOKEN["text_muted"]};margin-top:5px;">
                社区治理平台 · 接诉即办 · 海淀小区</div>
        </div>
        """, unsafe_allow_html=True)

        st.markdown(
            f'<div style="text-align:center;margin:8px 0 6px;font-size:0.75em;'
            f'color:{TOKEN["text_muted"]};">快速体验</div>',
            unsafe_allow_html=True,
        )
        c_demo1, c_demo2, c_demo3 = st.columns(3)
        with c_demo1:
            if st.button("居民", key="demo_resident", use_container_width=True):
                _login_demo("resident")
        with c_demo2:
            if st.button("网格员", key="demo_grid", use_container_width=True):
                _login_demo("grid")
        with c_demo3:
            if st.button("👴 老年关怀版", key="demo_elderly", use_container_width=True):
                _login_demo("elderly")

        st.markdown("---")

        tab_login, tab_register = st.tabs(["登录", "注册"])

        with tab_login:
            _render_login_form()
        with tab_register:
            _render_register_form()


def _render_login_form():
    muted_color = TOKEN["text_muted"]

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
            st.session_state.pop("user_profile", None)
            st.rerun()
        else:
            st.error("用户名或密码错误")

    st.markdown(
        f'<div style="font-size:0.7em;color:{muted_color};margin-top:12px;text-align:center;">'
        f'演示账号：<code>resident1</code> / <code>grid1</code> — 密码：<code>123</code></div>',
        unsafe_allow_html=True,
    )


def _render_register_form():
    """注册表单（只开放给居民）。"""
    muted_color = TOKEN["text_muted"]

    new_username = st.text_input("用户名", key="reg_username", placeholder="请设置用户名")
    new_password = st.text_input("密码", type="password", key="reg_password", placeholder="请设置密码")
    community = st.text_input("🏘️ 小区", key="reg_community", placeholder="如：海淀小区")
    col_n1, col_n2 = st.columns(2)
    with col_n1:
        building = st.text_input("楼栋", key="reg_building", placeholder="如：3号楼")
    with col_n2:
        unit = st.text_input("单元", key="reg_unit", placeholder="如：2单元")

    if st.button("注册", type="primary", width="stretch", key="reg_btn"):
        if not new_username or not new_password or not community.strip():
            st.error("请填写必填项（用户名 / 密码 / 小区）")
            return
        if get_user_by_username(new_username):
            st.error("用户名已存在")
            return
        uid = create_user(new_username, new_password, community=community.strip(),
                          building=building, unit=unit, role="resident")
        if uid:
            st.session_state["_login_user_id"] = uid
            st.session_state["_ob_role"] = ""
            st.session_state.pop("user_profile", None)
            st.rerun()
        else:
            st.error("注册失败")

    st.markdown(
        f'<div style="font-size:0.7em;color:{muted_color};margin-top:8px;text-align:center;">'
        f'居民自行注册。网格员账号由管理员预创建。</div>',
        unsafe_allow_html=True,
    )


def _login_demo(role: str):
    """演示用的一键登录。"""
    from data.db_user import list_users
    users = list_users()
    target = [u for u in users if u.get("role") == role]
    if target:
        uid = target[0].get("id")
        st.session_state["_login_user_id"] = uid
        st.session_state["_ob_role"] = role
        # 清掉缓存的资料，让 get_user_profile() 重新读库
        st.session_state.pop("user_profile", None)
        st.rerun()
