# ui/onboarding.py
"""首次使用引导 — 两步：选身份，填资料。"""
import base64
import os
import streamlit as st
from agent.memory import MemoryManager
from ui.components import TOKEN


def _get_bg_base64() -> str:
    """自动找 assets/ 里的图片，转成 base64 数据链接。"""
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
    """渲染两步式引导页。

    调用前记得先查 memory.is_onboarding_done()。
    返回 False（引导还没走完）。
    """
    bg = _get_bg_base64()
    has_bg = bool(bg)

    # 引导页颜色固定用浅色，显得亲切
    text_color = TOKEN["text"]
    muted_color = TOKEN["text_sec"]
    accent = TOKEN["accent"]

    # 背景图 CSS，能少则少
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
    """第一步：选身份 — 居民 / 网格员 / 老年关怀版。"""
    # 用列居中
    col_l, col_m, col_r = st.columns([1, 1.5, 1])
    with col_m:
        st.markdown(f"""
        <div style="text-align:center;padding:10vh 0 20px;">
            <div style="width:52px;height:52px;background:linear-gradient(135deg,{accent},{TOKEN["accent2"]});
            border-radius:14px;display:inline-flex;align-items:center;justify-content:center;
            font-size:1.5em;color:#fff;margin-bottom:14px;
            box-shadow:0 8px 24px rgba(79,70,229,0.35);">🏘️</div>
            <div style="font-size:1.35em;font-weight:800;color:{text_color};letter-spacing:-0.02em;">
            社区先知</div>
            <div style="font-size:0.8em;color:{muted_color};margin-top:2px;">
            CommunityInsight · 知报议督</div>
            <div style="font-size:0.82em;font-weight:600;color:{text_color};
            margin-top:32px;margin-bottom:20px;">选择你的身份</div>
        </div>
        """, unsafe_allow_html=True)

        c_stu, c_tea, c_eld = st.columns(3, gap="medium")
        with c_stu:
            if st.button("🧑\n\n我是居民", key="ob_role_resident", use_container_width=True):
                st.session_state.ob_role = "resident"
                st.rerun()
            st.caption("上报问题 · 提交提案 · 参与讨论")
        with c_tea:
            if st.button("🦺\n\n我是网格员", key="ob_role_grid", use_container_width=True):
                st.session_state.ob_role = "grid"
                st.rerun()
            st.caption("处理工单 · 回复提案 · 发布通知")
        with c_eld:
            if st.button("👴\n\n老年关怀版", key="ob_role_elderly", use_container_width=True):
                st.session_state.ob_role = "elderly"
                st.rerun()
            st.caption("大字模式 · 一键呼叫 · 吃药提醒")

        # 步骤圆点
        st.markdown(f"""
        <div style="display:flex;justify-content:center;gap:8px;margin-top:32px;">
            <div style="width:8px;height:8px;border-radius:50%;background:{accent};"></div>
            <div style="width:8px;height:8px;border-radius:50%;background:{TOKEN["border_visible"]};"></div>
        </div>
        """, unsafe_allow_html=True)


def _render_step_form(memory, role, text_color, muted_color, accent):
    """第二步：按身份填对应的资料。"""
    is_resident = role == "resident"
    is_elderly = role == "elderly"
    if is_elderly:
        emoji, title, subtitle, btn_label = "👴", "老年关怀版", "大字模式 · 操作更简单", "进入关怀版"
    elif is_resident:
        emoji, title, subtitle, btn_label = "🧑", "居民信息", "填写基本信息", "开始使用"
    else:
        emoji, title, subtitle, btn_label = "🦺", "网格员信息", "填写工作信息，进入网格员工作台", "进入工作台"

    # 用列居中
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
        user_unit = ""
        child_phone = ""

        community = st.text_input("🏘️ 小区", placeholder="请输入你的小区名称", key="ob_community")

        if is_resident:
            building = st.selectbox(
                "🏢 楼栋",
                ["1号楼", "2号楼", "3号楼", "4号楼", "5号楼", "6号楼",
                 "7号楼", "8号楼", "9号楼", "10号楼", "11号楼", "12号楼"],
                index=None, placeholder="请选择楼栋", key="ob_building",
            )
            resident_id = st.text_input("🔢 门牌号", placeholder="请输入你的门牌号", key="ob_resident_id")
            user_unit = st.text_input("🚪 单元房号", placeholder="如：2单元501", key="ob_unit")
            user_name = st.text_input("👤 姓名", placeholder="请输入你的姓名（选填）", key="ob_name")
        elif is_elderly:
            building = st.text_input("🏢 楼栋", placeholder="如：11号楼", key="ob_building")
            resident_id = st.text_input("🔢 门牌号", placeholder="如：3单元301", key="ob_resident_id")
            user_name = st.text_input("👤 姓名", placeholder="如：张大爷", key="ob_name")
            child_phone = st.text_input("👨‍👩‍👧 子女电话（紧急联系，选填）", placeholder="如：138xxxx", key="ob_child_phone")
        else:
            building = st.selectbox(
                "🏢 部门",
                ["居委会", "网格办", "物业", "警务室", "信息中心", "宣传部", "志愿者队", "其他"],
                index=None, placeholder="请选择所在部门", key="ob_building",
            )
            resident_id = st.text_input("🔢 工号", placeholder="请输入你的工号", key="ob_resident_id")
            user_name = st.text_input("👤 姓名", placeholder="请输入你的姓名（选填）", key="ob_name")

        c_back, c_submit = st.columns([1, 2.2], gap="medium")
        with c_back:
            if st.button("← 返回", key="ob_back", type="secondary", use_container_width=True):
                st.session_state.pop("ob_role", None)
                st.rerun()
        with c_submit:
            submitted = st.button(btn_label, type="primary", use_container_width=True)

        # 步骤圆点
        st.markdown(f"""
        <div style="display:flex;justify-content:center;gap:8px;margin-top:24px;">
            <div style="width:8px;height:8px;border-radius:50%;background:{TOKEN["border_visible"]};"></div>
            <div style="width:8px;height:8px;border-radius:50%;background:{accent};"></div>
        </div>
        """, unsafe_allow_html=True)

    if submitted:
        if not community:
            st.warning("请至少填写小区名称")
            return

        memory.update_profile(
            community=community, building=building or "", resident_id=resident_id or "",
            unit=user_unit or "", role=role, name=user_name or "",
        )

        # elderly 角色：保存子女紧急联系 + 默认标记独居（可在页面里改）
        if is_elderly:
            try:
                from data.db_elderly import set_emergency_contact, set_living_alone
                uid = memory.user_id
                if child_phone.strip():
                    set_emergency_contact(uid, [{"name": "子女", "relation": "子女", "phone": child_phone.strip()}])
                set_living_alone(uid, True)
            except Exception:
                pass  # 非关键，不影响进入

        memory.complete_onboarding()

        if is_elderly:
            memory.add_message(
                "assistant",
                f"👴 欢迎，{user_name or '大爷/阿姨'}！这是您的关怀版页面。\n\n"
                "大按钮，点一下就行：\n"
                "🗣️ **一句话上报** · 说出问题就能上报\n"
                "📞 **一键呼叫** · 子女/网格员/物业\n"
                "💊 **吃药提醒** · 到点提醒你吃药\n"
                "🆘 **我出事了** · 红色按钮，有事马上按",
            )
        elif is_resident:
            memory.add_message(
                "assistant",
                f"👋 嗨！{community}的{building or ''}{user_name or user_unit or ''}邻居，欢迎使用社区先知！\n\n"
                "我是你的社区治理伙伴，围绕知·报·议·督四个板块运行。\n\n"
                "🌊 **知** · 输入'社区脉搏'看本周热点\n"
                "🔧 **报** · 发现社区诉求，直接描述即可上报\n"
                "🗳️ **议** · 有想法？'我有个提案'或参与讨论\n"
                "📊 **督** · 社区治理看板看社区数据全貌\n\n"
                "输入「社区脉搏」开始体验。",
            )
        else:
            memory.add_message(
                "assistant",
                f"👋 欢迎！{community}的{user_name or '网格员'}，已进入网格员工作台。\n\n"
                "这里是社区治理网格员工作台：\n\n"
                "📊 **工作台** · 查看社区治理全貌，处理紧急工单\n"
                "📋 **工单管理** · 查看和处理所有上报问题\n"
                "💡 **提案管理** · 回复和采纳居民提案\n"
                "📢 **内容发布** · 发布通知和讨论议题\n\n"
                "工作台已就绪。",
            )
        st.rerun()
