# ui/sidebar.py
"""Sidebar — brand, user card, governance stats, account controls."""
import streamlit as st
from ui.theme import get_theme, theme_toggle
from ui.notify import render_sidebar_badge
from ui.cache import invalidate_all
from data.db_user import list_users, get_user_by_id


def render_sidebar(profile: dict, role: str):
    """Render the full sidebar. Call once per rerun inside main()."""
    is_dark = get_theme() == "dark"
    tx = "#e8e8ed" if is_dark else "#1a1a1a"
    tx2 = "#9898a2" if is_dark else "#6e6e6e"
    tx3 = "#5e5e6a" if is_dark else "#a0a0a0"
    bd = "#25252e" if is_dark else "#ebebeb"
    card = "#18181f" if is_dark else "#ffffff"
    accent_bg = "rgba(109,107,245,0.10)" if is_dark else "#f0efff"
    accent_bd = "rgba(109,107,245,0.18)" if is_dark else "#d2d0f8"
    accent = "#6d6bf5" if is_dark else "#4f46e5"
    _warn_bg = "rgba(251,191,36,0.08)" if is_dark else "#fffbeb"
    _dang_bg = "rgba(248,113,113,0.08)" if is_dark else "#fef2f2"
    _succ_bg = "rgba(52,211,153,0.08)" if is_dark else "#ecfdf5"
    _warn = "#fbbf24" if is_dark else "#d97706"
    _dang = "#f87171" if is_dark else "#dc2626"
    _succ = "#34d399" if is_dark else "#059669"

    # ── Brand ──
    st.markdown(
        f'<div style="padding:14px 0 8px;">'
        f'<div style="font-size:1.1em;font-weight:700;color:{tx};'
        f'letter-spacing:-0.01em;">CampusInsight</div>'
        f'<div style="font-size:0.7em;color:{tx3};margin-top:1px;">'
        f'{"校园治理平台" if role != "teacher" else "管理后台"}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── User card ──
    if profile:
        school = profile.get("school", "")
        grade = profile.get("grade", "")
        major = profile.get("major", "")
        student_id = profile.get("student_id", "")
        name = profile.get("name", "")
        role_label = "教师" if role == "teacher" else "学生"
        display_name = name or profile.get("username", "User")

        st.markdown(
            f'<div style="background:{accent_bg};border:1px solid {accent_bd};'
            f'border-radius:6px;padding:10px 12px;margin:8px 0;">'
            f'<div style="font-size:0.84em;font-weight:600;color:{tx};">{display_name}</div>'
            f'<div style="font-size:0.7em;color:{tx2};line-height:1.5;">'
            f'<span style="background:{accent}18;color:{accent};'
            f'padding:1px 6px;border-radius:99px;font-size:0.85em;">{role_label}</span>'
            f'{" &middot; " + school if school else ""}'
            f'{" &middot; " + grade if grade else ""}'
            f'{"<br>" + major if major and role != "teacher" else ""}'
            f'{"<br>" + student_id if student_id else ""}'
            f'</div></div>',
            unsafe_allow_html=True,
        )

    # ── Governance stats ──
    _section_label("概览")

    from ui.cache import cached_issues_stats, cached_proposals_stats, cached_knowledge_base
    i_stats = cached_issues_stats()
    p_stats = cached_proposals_stats()
    resolved = i_stats["by_status"].get("已解决", 0)
    pending = i_stats["by_status"].get("待处理", 0)

    if role == "teacher":
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

    # ── Knowledge base ──
    kb = cached_knowledge_base(category="faq", limit=1)
    gov = cached_knowledge_base(category="governance", limit=2)
    if kb or gov:
        _section_label("百科")
        for entry in (kb + gov)[:3]:
            title = entry.get("title", "")[:18]
            cat = entry.get("category", "")
            st.markdown(
                f'<div style="font-size:0.7em;color:{tx2};padding:2px 0;line-height:1.3;">'
                f'<span style="color:{tx3};">{cat.upper()[:4]}</span> {title}</div>',
                unsafe_allow_html=True,
            )

    # ── Notifications ──
    render_sidebar_badge()

    # ── Account ──
    _section_label("账户")

    all_users = list_users()
    if len(all_users) > 1:
        current_uid = st.session_state.get("_login_user_id", 1)
        user_options = {
            f'{u["role"].replace("student","[学生]").replace("teacher","[教师]")} '
            f'{u.get("name","") or u["username"]}'
            f'{" · " + u.get("school","")[:8] if u.get("school") else ""}': u["id"]
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

    # ── Theme + Logout ──
    c_t, c_l = st.columns([1, 1])
    with c_t:
        theme_toggle()
    with c_l:
        if st.button("退出", key="_logout", width="stretch"):
            for k in ["_login_user_id", "user_profile", "messages",
                      "langchain_memory", "session_ready", "agent", "memory",
                      "ob_role", "ob_school", "ob_grade", "ob_student_id",
                      "ob_major", "ob_name"]:
                st.session_state.pop(k, None)
            invalidate_all()
            st.rerun()

    st.caption("知 · 报 · 议 · 督 · 校园治理")


# ── Internal helpers ──

def _section_label(label: str):
    tx3 = "#5e5e6a" if get_theme() == "dark" else "#a0a0a0"
    bd = "#25252e" if get_theme() == "dark" else "#ebebeb"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;margin:12px 0 6px;">'
        f'<span style="font-size:0.68em;font-weight:600;color:{tx3};'
        f'text-transform:uppercase;letter-spacing:0.06em;white-space:nowrap;">{label}</span>'
        f'<div style="flex:1;height:1px;background:{bd};"></div></div>',
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
