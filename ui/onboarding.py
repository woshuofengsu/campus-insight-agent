# ui/onboarding.py
"""First-time user onboarding — two-step flow: pick role, fill profile."""
import base64
import os
import streamlit as st
from agent.memory import MemoryManager


def _get_bg_base64() -> str:
    """Auto-detect any image in assets/ and return as base64 data URL."""
    assets_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
    if not os.path.isdir(assets_dir):
        return ""
    for fname in os.listdir(assets_dir):
        if fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            fpath = os.path.join(assets_dir, fname)
            ext = fname.rsplit(".", 1)[-1].lower()
            mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(ext, "jpeg")
            with open(fpath, "rb") as f:
                return f"data:image/{mime};base64,{base64.b64encode(f.read()).decode()}"
    return ""


def render_onboarding(memory: MemoryManager) -> bool:
    """Render a premium onboarding screen with two-step flow.

    Caller must check memory.is_onboarding_done() before invoking.
    Returns False (onboarding still in progress).
    """
    bg = _get_bg_base64()
    has_bg = bool(bg)

    # Colors — always light & welcoming
    text_color = "#0f172a"
    muted_color = "#64748b"
    accent = "#4f46e5"

    # Minimal background CSS
    if has_bg:
        st.markdown(f"""
<style>
.stApp {{
    background: url('{bg}') no-repeat center center fixed !important;
    background-size: cover !important;
}}
.stApp::before {{
    content: ''; position: fixed; inset: 0;
    background: linear-gradient(135deg, rgba(15,23,42,0.82) 0%, rgba(15,23,42,0.55) 100%);
    z-index: 0; pointer-events: none;
}}
</style>""", unsafe_allow_html=True)

        profile = memory.get_user_profile()
    existing_role = profile.get("role", "")
    role = st.session_state.get("ob_role", None) or (existing_role if existing_role else None)

    if role is None:
        _render_step_role(text_color, muted_color, accent)
    else:
        _render_step_form(memory, role, text_color, muted_color, accent)

    return False


def _render_step_role(text_color, muted_color, accent):
    """Step 1: Choose role — student or teacher."""
    # Center with columns
    col_l, col_m, col_r = st.columns([1, 1.5, 1])
    with col_m:
        st.markdown(f"""
        <div style="text-align:center;padding:10vh 0 20px;">
            <div style="width:52px;height:52px;background:linear-gradient(135deg,{accent},#7c3aed);
            border-radius:14px;display:inline-flex;align-items:center;justify-content:center;
            font-size:1.5em;color:#fff;margin-bottom:14px;
            box-shadow:0 8px 24px rgba(79,70,229,0.35);">🏛</div>
            <div style="font-size:1.35em;font-weight:800;color:{text_color};letter-spacing:-0.02em;">
            校园先知</div>
            <div style="font-size:0.8em;color:{muted_color};margin-top:2px;">
            CampusInsight · 知报议督</div>
            <div style="font-size:0.82em;font-weight:600;color:{text_color};
            margin-top:32px;margin-bottom:20px;">选择你的身份</div>
        </div>
        """, unsafe_allow_html=True)

        c_stu, c_tea = st.columns(2, gap="medium")
        with c_stu:
            if st.button("🎓\n\n我是学生", key="ob_role_student", use_container_width=True):
                st.session_state.ob_role = "student"
                st.rerun()
            st.caption("上报问题 · 提交提案 · 参与讨论")
        with c_tea:
            if st.button("👨‍🏫\n\n我是教职工", key="ob_role_teacher", use_container_width=True):
                st.session_state.ob_role = "teacher"
                st.rerun()
            st.caption("处理工单 · 回复提案 · 发布通知")

        # Step dots
        st.markdown(f"""
        <div style="display:flex;justify-content:center;gap:8px;margin-top:32px;">
            <div style="width:8px;height:8px;border-radius:50%;background:{accent};"></div>
            <div style="width:8px;height:8px;border-radius:50%;background:#cbd5e1;"></div>
        </div>
        """, unsafe_allow_html=True)


def _render_step_form(memory, role, text_color, muted_color, accent):
    """Step 2: Fill in role-specific profile info."""
    is_student = role == "student"
    emoji = "🎓" if is_student else "👨‍🏫"
    title = "学生信息" if is_student else "教职工信息"
    subtitle = "填写基本信息，开始你的校园治理之旅" if is_student else "填写工作信息，进入校园治理管理后台"
    btn_label = "✨ 开始参与校园治理" if is_student else "✨ 进入治理工作台"

    # Center with columns
    col_l, col_m, col_r = st.columns([1, 2.2, 1])
    with col_m:
        st.markdown(f"""
        <div style="text-align:center;padding:4vh 0 20px;">
            <div style="font-size:2.4em;margin-bottom:6px;line-height:1;">{emoji}</div>
            <div style="font-size:1.15em;font-weight:800;color:{text_color};letter-spacing:-0.01em;">
            {title}</div>
            <div style="font-size:0.76em;color:{muted_color};margin-top:4px;">{subtitle}</div>
        </div>
        """, unsafe_allow_html=True)

                user_name = ""
        user_major = ""

        school = st.text_input("🏫 学校", placeholder="请输入你的大学名称", key="ob_school")

        if is_student:
            grade = st.selectbox(
                "📚 年级",
                ["大一", "大二", "大三", "大四", "研一", "研二", "研三", "博士"],
                index=None, placeholder="请选择年级", key="ob_grade",
            )
            student_id = st.text_input("🔢 学号", placeholder="请输入你的学号", key="ob_student_id")
            user_major = st.text_input("📖 专业", placeholder="请输入你的专业", key="ob_major")
            user_name = st.text_input("👤 姓名", placeholder="请输入你的姓名（选填）", key="ob_name")
        else:
            grade = st.selectbox(
                "🏢 部门",
                ["学生处", "教务处", "后勤处", "保卫处", "信息中心", "宣传部", "团委", "其他"],
                index=None, placeholder="请选择所在部门", key="ob_grade",
            )
            student_id = st.text_input("🔢 工号", placeholder="请输入你的工号", key="ob_student_id")
            user_name = st.text_input("👤 姓名", placeholder="请输入你的姓名（选填）", key="ob_name")

                c_back, c_submit = st.columns([1, 2.2], gap="medium")
        with c_back:
            if st.button("← 返回", key="ob_back", type="secondary", use_container_width=True):
                st.session_state.pop("ob_role", None)
                st.rerun()
        with c_submit:
            submitted = st.button(btn_label, type="primary", use_container_width=True)

        # Step dots
        st.markdown(f"""
        <div style="display:flex;justify-content:center;gap:8px;margin-top:24px;">
            <div style="width:8px;height:8px;border-radius:50%;background:#cbd5e1;"></div>
            <div style="width:8px;height:8px;border-radius:50%;background:{accent};"></div>
        </div>
        """, unsafe_allow_html=True)

    if submitted:
        if not school:
            st.warning("请至少填写学校名称")
            return

        memory.update_profile(
            school=school, grade=grade or "", student_id=student_id or "",
            major=user_major or "", role=role, name=user_name or "",
        )
        memory.complete_onboarding()

        if is_student:
            memory.add_message(
                "assistant",
                f"👋 嗨！{school}的{grade or ''}{user_name or user_major or ''}同学，欢迎使用校园先知！\n\n"
                "我是你的校园治理伙伴，围绕知·报·议·督四个板块运行。\n\n"
                "🌊 **知** · 输入'校园脉搏'看本周热点\n"
                "🔧 **报** · 发现校园问题，直接描述即可上报\n"
                "🗳️ **议** · 有想法？'我有个提案'或参与讨论\n"
                "📊 **督** · 治理透明窗看校园数据全貌\n\n"
                "你的每一次参与，都在让校园变得更好。",
            )
        else:
            memory.add_message(
                "assistant",
                f"👋 欢迎！{school}的{user_name or '老师'}，已进入教职工工作台。\n\n"
                "这里是校园治理管理后台：\n\n"
                "📊 **工作台** · 查看校园治理全貌，处理紧急工单\n"
                "📋 **工单管理** · 查看和处理所有上报问题\n"
                "💡 **提案管理** · 回复和采纳学生提案\n"
                "📢 **内容发布** · 发布通知和讨论议题\n\n"
                "你的每一次行动，都在让校园变得更好。",
            )
        st.rerun()
