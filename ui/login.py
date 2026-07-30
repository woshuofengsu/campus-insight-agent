# ui/login.py
"""Login page — multi-user authentication gate."""
import streamlit as st
from data.db_user import authenticate, create_user, get_user_by_username


def render_login():
    """Render the login page. Sets st.session_state._login_user_id on success."""
    from ui.theme import get_theme
    is_dark = get_theme() == "dark"

    # Theme-adaptive colors
    page_bg = "#0a0a1a" if is_dark else "#f8fafc"
    card_bg = "#111827" if is_dark else "#ffffff"
    card_border = "rgba(99,102,241,0.2)" if is_dark else "#e2e8f0"
    text_color = "#e2e8f0" if is_dark else "#1e293b"
    muted_color = "#94a3b8" if is_dark else "#64748b"
    input_bg = "#1e293b" if is_dark else "#f8fafc"
    input_border = "rgba(99,102,241,0.25)" if is_dark else "#e2e8f0"
    accent = "#818cf8"
    accent2 = "#a78bfa"

    # ── Minimal CSS for login page — hide sidebar, set background ──
    st.markdown(f"""
<style>
    .stApp {{
        background: {page_bg} !important;
    }}
    [data-testid="stSidebar"] {{
        display: none !important;
    }}
    [data-testid="stSidebar"] * {{
        display: none !important;
    }}
</style>
""", unsafe_allow_html=True)

    # ── Center the card using columns ──
    col_l, col_m, col_r = st.columns([1, 2, 1])

    with col_m:
        st.markdown("""
        <div style="text-align:center;padding:24px 0 0;">
            <div style="font-size:3em;">🏛️</div>
            <div style="font-size:1.6em;font-weight:800;
                background:linear-gradient(135deg,#818cf8,#a78bfa,#60a5fa);
                -webkit-background-clip:text;-webkit-text-fill-color:transparent;
                background-clip:text;">校园先知</div>
            <div style="font-size:0.8em;color:#64748b;margin-bottom:16px;">
                CampusInsight · 知报议督 · AI 校园治理平台</div>
        </div>
        """, unsafe_allow_html=True)

        # ── Demo quick access ──
        st.markdown(
            f'<div style="text-align:center;margin:8px 0 6px;font-size:0.76em;'
            f'color:{muted_color};">👇 评委 / 访客快速体验</div>',
            unsafe_allow_html=True,
        )
        c_demo1, c_demo2 = st.columns(2)
        with c_demo1:
            if st.button("🎓 一键体验（学生）", key="demo_student", use_container_width=True):
                _login_demo("student")
        with c_demo2:
            if st.button("👨‍🏫 一键体验（教师）", key="demo_teacher", use_container_width=True):
                _login_demo("teacher")

        st.markdown("---")

        # ── Login / Register Tabs ──
        tab_login, tab_register = st.tabs(["🔑 登录", "📝 注册（学生）"])

        with tab_login:
            _render_login_form(is_dark)
        with tab_register:
            _render_register_form(is_dark)


def _render_login_form(is_dark: bool = True):
    """Login form."""
    username = st.text_input("用户名", placeholder="输入用户名", key="login_username")
    password = st.text_input(
        "密码", placeholder="学生无需密码，教师必填",
        type="password", key="login_password"
    )

    if st.button("登录", key="login_btn", type="primary", use_container_width=True):
        if not username.strip():
            st.warning("请输入用户名")
            return
        user = authenticate(username.strip(), password)
        if user:
            _do_login(user)
        else:
            st.error("用户名或密码错误。教师账号需要密码，学生账号无需密码。")


def _render_register_form(is_dark: bool = True):
    """Student registration form."""
    st.caption("创建学生账号，即可参与校园治理。教师账号需管理员创建。")

    reg_user = st.text_input("用户名 *", placeholder="字母或拼音，如 xiaoming", key="reg_username")
    reg_pw = st.text_input("密码（选填）", placeholder="留空则无需密码", type="password", key="reg_password")
    reg_name = st.text_input("姓名（选填）", placeholder="你的真实姓名", key="reg_name")
    reg_school = st.text_input("学校 *", placeholder="如：北京工商大学", key="reg_school")
    reg_grade = st.selectbox(
        "年级", ["大一", "大二", "大三", "大四", "研一", "研二", "研三", "博士"],
        index=None, placeholder="选择年级", key="reg_grade",
    )
    reg_major = st.text_input("专业", placeholder="你的专业", key="reg_major")
    reg_sid = st.text_input("学号", placeholder="你的学号", key="reg_sid")

    if st.button("注册", key="reg_btn", type="primary", use_container_width=True):
        if not reg_user.strip():
            st.warning("用户名不能为空")
            return
        if not reg_school.strip():
            st.warning("学校不能为空")
            return
        if get_user_by_username(reg_user.strip()):
            st.error(f"用户名 '{reg_user}' 已被占用，请换一个")
            return
        try:
            uid = create_user(
                username=reg_user.strip(),
                password=reg_pw,
                role="student",
                school=reg_school.strip(),
                grade=reg_grade or "",
                major=reg_major.strip() or "",
                name=reg_name.strip() or "",
                student_id=reg_sid.strip() or "",
            )
            from data.db_user import get_user_by_id
            user = get_user_by_id(uid)
            _do_login(user)
        except Exception as e:
            st.error(f"注册失败: {e}")


def _login_demo(role: str = "student"):
    """Auto-create + login a demo user."""
    from data.db_user import get_user_by_username, create_user, get_user_by_id
    from data.database import set_onboarding_done
    if role == "teacher":
        username, password, name = "demo_teacher", "demo123", "张老师"
    else:
        username, password, name = "demo_student", "", "小明"
    user = get_user_by_username(username)
    if user is None:
        uid = create_user(
            username=username, password=password, role=role,
            school="北京工商大学", grade="大三" if role == "student" else "",
            major="计算机科学" if role == "student" else "",
            name=name, student_id="20240001" if role == "student" else "",
        )
        user = get_user_by_id(uid)
        set_onboarding_done(uid)
    _do_login(user)


def _do_login(user: dict):
    """Set session state after successful login."""
    st.session_state._login_user_id = user["id"]
    st.session_state.user_profile = user
    for key in ["session_ready", "agent", "memory", "messages", "langchain_memory"]:
        st.session_state.pop(key, None)
    st.rerun()
