# ui/sidebar.py
"""侧边栏 — 品牌、用户卡片、治理统计、账号操作。"""
import streamlit as st
from config import DEMO_MODE
from ui.session_state import SS
from ui.theme import theme_toggle
from ui.components import TOKEN
from ui.notify import render_sidebar_badge
from ui.cache import invalidate_all
from data.db_user import list_users, get_user_by_id


def render_sidebar(profile: dict, role: str):
    """渲染整个侧边栏，main() 里每次 rerun 调用一次。"""
    # 大字模式：放大全局根字号（老年友好，浏览器原生缩放之外的显式入口）
    if st.session_state.get("_large_font"):
        st.markdown('<style>html { font-size: 18px !important; }</style>', unsafe_allow_html=True)

    tx = TOKEN["sidebar_text"]
    tx2 = TOKEN["sidebar_text_sec"]
    tx3 = TOKEN["sidebar_text_muted"]
    bd = TOKEN["sidebar_border"]
    card = TOKEN["sidebar_surface"]
    accent_bg = TOKEN["sidebar_accent_bg"]
    accent_bd = TOKEN["sidebar_border"]
    accent = TOKEN["sidebar_accent"]
    _warn_bg = TOKEN["sidebar_warn_bg"]
    _dang_bg = TOKEN["sidebar_dang_bg"]
    _succ_bg = TOKEN["sidebar_succ_bg"]
    _warn = TOKEN["sidebar_warn"]
    _dang = TOKEN["sidebar_dang"]
    _succ = TOKEN["sidebar_succ"]

    # 品牌区
    st.markdown(
        f'<div style="padding:14px 0 10px;display:flex;align-items:center;gap:10px;">'
        f'<div style="width:36px;height:36px;border-radius:10px;'
        f'background:linear-gradient(135deg,{TOKEN["accent"]},{TOKEN["accent2"]});'
        f'display:flex;align-items:center;justify-content:center;'
        f'font-size:1.15em;color:#fff;flex-shrink:0;'
        f'box-shadow:0 4px 12px rgba(79,70,229,0.35);">🏘️</div>'
        f'<div style="min-width:0;">'
        f'<div style="font-size:1.05em;font-weight:700;color:{tx};'
        f'letter-spacing:-0.01em;line-height:1.25;">CommunityInsight</div>'
        f'<div style="font-size:0.75em;color:{tx3};margin-top:1px;">'
        f'{"社区治理平台" if role != "grid" else "网格员工作台"}</div>'
        f'</div></div>',
        unsafe_allow_html=True,
    )

    # 用户卡片
    if profile:
        community = profile.get("community", "")
        building = profile.get("building", "")
        unit = profile.get("unit", "")
        resident_id = profile.get("resident_id", "")
        name = profile.get("name", "")
        role_label = "网格员" if role == "grid" else "居民"
        display_name = name or profile.get("username", "User")

        st.markdown(
            f'<div style="background:{accent_bg};border:1px solid {accent_bd};'
            f'border-radius:6px;padding:10px 12px;margin:8px 0;">'
            f'<div style="font-size:0.84em;font-weight:600;color:{tx};">{display_name}</div>'
            f'<div style="font-size:0.7em;color:{tx2};line-height:1.5;">'
            f'<span style="background:{accent}18;color:{accent};'
            f'padding:1px 6px;border-radius:99px;font-size:0.85em;">{role_label}</span>'
            f'{" &middot; " + community if community else ""}'
            f'{" &middot; " + building if building else ""}'
            f'{"<br>" + unit if unit and role != "grid" else ""}'
            f'{"<br>" + resident_id if resident_id else ""}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # 治理概览统计
    _section_label("概览")

    from ui.cache import cached_issues_stats, cached_proposals_stats, cached_knowledge_base
    i_stats = cached_issues_stats()
    p_stats = cached_proposals_stats()
    resolved = i_stats["by_status"].get("已解决", 0)
    pending = i_stats["by_status"].get("待处理", 0)

    if role == "grid":
        from ui.cache import cached_issues
        urgent_issues = cached_issues(urgency="紧急", limit=100)
        urgent_count = len(urgent_issues)
        _stat_grid([
            ("工单", str(i_stats["total"]), card, tx),
            ("提案", str(p_stats["total"]), card, tx),
            ("待处理", str(pending), _warn_bg, _warn),
            ("紧急", str(urgent_count), _dang_bg, _dang),
        ], tx3)
    else:
        _stat_grid([
            ("上报", str(i_stats["total"]), card, tx),
            ("提案", str(p_stats["total"]), card, tx),
            ("已解决", str(resolved), _succ_bg, _succ),
            ("待处理", str(pending), _warn_bg, _warn),
        ], tx3)

    # 知识库
    kb = cached_knowledge_base(category="faq", limit=1)
    gov = cached_knowledge_base(category="governance", limit=2)
    if kb or gov:
        _section_label("百科")
        for entry in (kb + gov)[:3]:
            title = (entry.get("title") or "")[:18]
            cat = entry.get("category", "")
            st.markdown(
                f'<div style="font-size:0.7em;color:{tx2};padding:2px 0;line-height:1.3;">'
                f'<span style="color:{tx3};">{cat.upper()[:4]}</span> {title}</div>',
                unsafe_allow_html=True,
            )

    # 紧急联系（居民/老人一键拨打；网格员自己就是处理人，不需要这个）
    if role != "grid":
        _section_label("紧急联系")
        c_tel1, c_tel2 = st.columns(2)
        with c_tel1:
            st.link_button("📞 网格员", "tel:62319876", width="stretch")
        with c_tel2:
            st.link_button("🔧 物业", "tel:62310086", width="stretch")

    # 通知角标
    render_sidebar_badge()

    # 账户区
    _section_label("账户")

    # 演示专用：账号切换仅在 DEMO_MODE 开启时显示。正式环境靠「退出→重新登录」隔离双角色，
    # 避免任何登录用户一键越权切到网格员账号。
    if DEMO_MODE:
        all_users = list_users()
        if len(all_users) > 1:
            current_uid = st.session_state.get(SS.login_user_id, 1)
            user_options = {
                f'{u["role"].replace("resident","[居民]").replace("grid","[网格员]")} '
                f'{u.get("name","") or u["username"]}'
                f'{" · " + u.get("community","")[:8] if u.get("community") else ""}': u["id"]
                for u in all_users
            }
            current_label = next((k for k, v in user_options.items() if v == current_uid),
                                 list(user_options.keys())[0])
            selected_label = st.selectbox(
                "切换账号", list(user_options.keys()),
                index=list(user_options.keys()).index(current_label),
                key="_user_switcher", label_visibility="collapsed",
            )
            selected_uid = user_options[selected_label]
            if selected_uid != current_uid:
                st.session_state._login_user_id = selected_uid
                st.session_state.user_profile = get_user_by_id(selected_uid)
                for k in ["messages", "langchain_memory", "session_ready", "agent", "memory"]:
                    st.session_state.pop(k, None)
                invalidate_all()
                st.rerun()

    # 主题 + 大字 + 退出
    c_t, c_f, c_l = st.columns([1, 1, 1])
    with c_t:
        theme_toggle()
    with c_f:
        st.toggle("🔠 大字", key="_large_font", value=st.session_state.get("_large_font", False))
    with c_l:
        if st.button("退出", key="_logout", width="stretch"):
            for k in [SS.login_user_id, "user_profile", "messages",
                      "langchain_memory", "session_ready", "agent", "memory",
                      "ob_role", "ob_community", "ob_building", "ob_resident_id",
                      "ob_unit", "ob_name"]:
                st.session_state.pop(k, None)
            invalidate_all()
            st.rerun()

    st.caption("知 · 报 · 议 · 督 · 社区治理")


# 内部小工具

def _section_label(label: str):
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin:14px 0 6px;">'
        f'<span style="font-size:0.75em;font-weight:600;color:{TOKEN["sidebar_text_muted"]};'
        f'letter-spacing:0.06em;white-space:nowrap;">{label}</span>'
        f'<div style="flex:1;height:1px;background:{TOKEN["sidebar_border"]};"></div></div>',
        unsafe_allow_html=True,
    )


def _stat_grid(items: list[tuple], muted_color: str):
    cells = []
    for label, value, bg, color in items:
        cells.append(
            f'<div style="background:{bg};padding:6px 8px;border-radius:4px;text-align:center;">'
            f'<div style="color:{muted_color};">{label}</div>'
            f'<div style="font-weight:600;color:{color};">{value}</div></div>'
        )
    st.markdown(
        f'<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.7em;">'
        f'{"".join(cells)}</div>',
        unsafe_allow_html=True,
    )
