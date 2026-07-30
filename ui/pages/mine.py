# ui/pages/mine.py
"""👤 我的 — 个人参与足迹、影响力统计."""
import streamlit as st
from ui.cache import cached_my_issues, cached_my_proposals, cached_my_stats
from ui.components import TOKEN, section, stat, info_card, issue_card, ooda_nav, tag, resolve_author

agent = st.session_state.get("agent")
memory = st.session_state.get("memory")
if memory is not None:
    profile = memory.get_user_profile()
else:
    profile = {}

# Derive author identity from profile — must match database._resolve_author()
author = resolve_author(profile)

st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">👤 我的</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption("你在校园治理中的每一次参与，都算数。")

ooda_nav("mine")

st.markdown("---")

# ── User identity card ──
if profile:
    school = profile.get("school", "")
    grade = profile.get("grade", "")
    major = profile.get("major", "")
    name = profile.get("name", "")
    display_name = name or (f"{school}" if school else "同学")
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["slate_border"]};'
        f'border-radius:{TOKEN["radius"]};padding:16px 20px;box-shadow:{TOKEN["shadow_sm"]};'
        f'margin-bottom:12px;">'
        f'<div style="font-size:1.1em;font-weight:700;color:{TOKEN["text"]};margin-bottom:4px;">'
        f'{display_name}</div>'
        f'<div style="font-size:0.85em;color:{TOKEN["text_sec"]};">{school} · {grade} · {major}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── Impact stats ──
stats = cached_my_stats(author)

section("📊 我的影响力", "", TOKEN["primary"])

col1, col2, col3, col4 = st.columns(4)
with col1:
    stat("📝", "上报问题", str(stats["total_issues"]), TOKEN["primary"])
with col2:
    stat("✅", "已解决", str(stats["resolved_issues"]), TOKEN["success"])
with col3:
    stat("💡", "提交提案", str(stats["total_proposals"]), TOKEN["purple_text"])
with col4:
    stat("🎉", "提案被采纳", str(stats["adopted_proposals"]), TOKEN["success"])

# Impact summary
if stats["total_issues"] + stats["total_proposals"] > 0:
    impact_score = stats["resolved_issues"] * 10 + stats["adopted_proposals"] * 20 + stats["total_proposals"] * 5
    if impact_score >= 200:
        level, level_emoji, level_color = "钻石治理者", "💎", "#7c3aed"
    elif impact_score >= 100:
        level, level_emoji, level_color = "黄金守卫者", "🥇", TOKEN["warning"]
    elif impact_score >= 50:
        level, level_emoji, level_color = "白银参与者", "🥈", TOKEN["text_sec"]
    elif impact_score >= 20:
        level, level_emoji, level_color = "青铜新星", "🥉", "#b45309"
    else:
        level, level_emoji, level_color = "萌芽观察者", "🌱", TOKEN["success"]
    st.markdown(
        f'<div style="text-align:center;margin:8px 0 16px;">'
        f'<span style="background:{level_color};color:#fff;font-size:0.9em;font-weight:600;'
        f'padding:6px 18px;border-radius:99px;">{level_emoji} {level} · {impact_score} 分</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ── My issues ──
section("📝 我上报的问题", "", TOKEN["primary"])

my_issues = cached_my_issues(author, limit=20)

if not my_issues:
    info_card("📝", "还没有上报过问题", "去「随手报修」页面提交第一个校园问题吧！")
else:
    # Status summary
    pending_count = len([i for i in my_issues if i.get("status") == "待处理"])
    processing_count = len([i for i in my_issues if i.get("status") == "处理中"])
    resolved_count = len([i for i in my_issues if i.get("status") == "已解决"])

    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            f'<div style="text-align:center;font-size:0.8em;color:{TOKEN["text_muted"]};">'
            f'⏳ 待处理 <strong style="color:{TOKEN["danger"]};">{pending_count}</strong></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f'<div style="text-align:center;font-size:0.8em;color:{TOKEN["text_muted"]};">'
            f'🔄 处理中 <strong style="color:{TOKEN["warning"]};">{processing_count}</strong></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f'<div style="text-align:center;font-size:0.8em;color:{TOKEN["text_muted"]};">'
            f'✅ 已解决 <strong style="color:{TOKEN["success"]};">{resolved_count}</strong></div>',
            unsafe_allow_html=True,
        )

    cols = st.columns(2)
    for idx, issue in enumerate(my_issues):
        with cols[idx % 2]:
            issue_card(issue)

st.markdown("---")

# ── My proposals ──
section("💡 我提交的提案", "", TOKEN["purple_text"])

my_proposals = cached_my_proposals(author, limit=20)

if not my_proposals:
    info_card("💡", "还没有提交过提案", "去「有话说」页面创建你的第一个提案！")
else:
    for p in my_proposals:
        s = p.get("status", "讨论中")
        emoji_map = {"讨论中": "💬", "已回应": "📝", "已采纳": "✅", "已实施": "🎉"}
        emoji = emoji_map.get(s, "📌")
        bg_color = {"讨论中": TOKEN["purple_bg"], "已回应": TOKEN["primary_bg"], "已采纳": TOKEN["success_bg"], "已实施": TOKEN["success_bg"]}.get(s, TOKEN["slate_bg"])
        bd_color = {"讨论中": TOKEN["purple_border"], "已回应": TOKEN["primary_border"], "已采纳": TOKEN["success_border"], "已实施": TOKEN["success_border"]}.get(s, TOKEN["slate_border"])
        st.markdown(
            f'<div style="background:{bg_color};border:1px solid {bd_color};'
            f'border-radius:{TOKEN["radius"]};padding:12px 16px;margin:6px 0;'
            f'box-shadow:{TOKEN["shadow_sm"]};font-size:0.88em;line-height:1.5;">'
            f'{emoji} <strong style="color:{TOKEN["text"]};">{p.get("title","")[:40]}</strong>'
            f'&nbsp;{tag(s)}'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:0.82em;">'
            f'👍 {p.get("supporter_count",0)} 人附议 · {p.get("category","")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")

# ── Quick summary ──
st.markdown(
    f'<div style="text-align:center;font-size:0.82em;color:{TOKEN["text_muted"]};margin-top:12px;">'
    f'每一次上报、每一个提案，都在让校园变得更好 🌱</div>',
    unsafe_allow_html=True,
)
