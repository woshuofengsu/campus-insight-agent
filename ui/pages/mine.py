"""👤 我的 — 个人参与足迹、影响力统计."""
import streamlit as st
from ui.cache import cached_my_issues, cached_my_proposals, cached_my_stats, invalidate_issues
from ui.components import TOKEN, section, stat, info_card, issue_card, ooda_nav, tag, resolve_author, page_header
from data.database import set_satisfaction, get_my_anonymous_issues

agent = st.session_state.get("agent")
memory = st.session_state.get("memory")
if memory is not None:
    profile = memory.get_user_profile()
else:
    profile = {}

# 从档案取身份，必须和 database._resolve_author() 保持一致
author = resolve_author(profile)

page_header("👤 我的", "个人参与记录与统计")

ooda_nav("mine")


def _submit_satisfaction(issue_id: int, value: str):
    """记录居民对已解决工单的评价，顺便刷新缓存。"""
    reason = (st.session_state.get(f"sat_reason_{issue_id}") or "").strip()
    try:
        new_status = set_satisfaction(issue_id, value, reason=reason)
        invalidate_issues()
        if value == "不满意":
            st.session_state["_sat_feedback"] = "🔄 已记录「不满意」，工单已重新打开，网格员将重新处理。"
        else:
            st.session_state["_sat_feedback"] = "✅ 已记录「满意」，感谢你的反馈！"
        st.session_state.pop(f"sat_reason_{issue_id}", None)
    except Exception as e:  # 非关键错误，提示出来就行，别崩
        st.session_state["_sat_feedback"] = f"评价提交失败：{e}"


def _render_satisfaction(issue: dict):
    """满意度反馈控件 — 仅对已解决工单展示，闭环「办结→评价」."""
    sat = issue.get("satisfaction", "")
    iid = issue["id"]
    if sat == "满意":
        st.caption("✅ 已评价：满意")
        return
    if sat == "不满意":
        reason = issue.get("satisfaction_reason", "")
        st.caption("🔄 已评价：不满意" + (f"（原因：{reason}）" if reason else "") + "（等待网格员复核）")
        return
    b1, b2 = st.columns(2)
    with b1:
        st.button("👍 满意", key=f"sat_ok_{iid}", on_click=_submit_satisfaction,
                  args=(iid, "满意"), width="stretch")
    with b2:
        st.button("👎 不满意", key=f"sat_no_{iid}", on_click=_submit_satisfaction,
                  args=(iid, "不满意"), width="stretch")
    st.text_input("不满意原因（选填）", key=f"sat_reason_{iid}",
                  placeholder="若点「不满意」，可简述原因，帮助网格员改进")

if profile:
    community = profile.get("community", "")
    building = profile.get("building", "")
    unit = profile.get("unit", "")
    name = profile.get("name", "")
    display_name = name or (f"{community}" if community else "邻居")
    st.markdown(
        f'<div style="background:{TOKEN["card_bg"]};border:1px solid {TOKEN["border"]};'
        f'border-radius:{TOKEN["radius_card"]};padding:16px 20px;box-shadow:{TOKEN["shadow_sm"]};'
        f'margin-bottom:12px;">'
        f'<div style="font-size:1.1em;font-weight:700;color:{TOKEN["text"]};margin-bottom:4px;">'
        f'{display_name}</div>'
        f'<div style="font-size:0.85em;color:{TOKEN["text_sec"]};">{community} · {building} · {unit}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

stats = cached_my_stats(author)

# ---------- 老年关怀绑定（家属绑定老人 → 老年端免登录代操作，spec 06） ----------
with st.container(border=True):
    section("👴 老年关怀")
    _me = memory.get_user_profile() if memory is not None else {}
    _me_id = (_me or {}).get("id")
    if _me_id:
        from data.db_user import get_bound_elderly, bind_elderly, unbind_elderly
        bound = get_bound_elderly(_me_id)
        if bound:
            st.success(f"✅ 已绑定老人：{bound.get('name') or '（无姓名）'}")
            st.caption("您登录后会自动以老人身份进入老年关怀端，可代为设置用药提醒、紧急联系人等。")
            if st.button("🔓 解除绑定", key="mine_unbind"):
                unbind_elderly(_me_id)
                st.rerun()
        else:
            st.caption("绑定家里老人后，可进入老年关怀端代为设置用药提醒、紧急联系人等。")
            with st.form("mine_bind_form"):
                elderly_user = st.text_input("老人账号（如 demo_elderly）", key="mine_bind_user")
                bind_sub = st.form_submit_button("绑定老人", width="stretch")
            if bind_sub:
                if not elderly_user.strip():
                    st.error("请填写老人账号")
                else:
                    from data.db_user import get_user_by_username
                    e = get_user_by_username(elderly_user.strip())
                    if e is None:
                        st.error("未找到该老人账号")
                    elif e["role"] != "elderly":
                        st.error("该账号不是老年关怀账号")
                    else:
                        ok, msg = bind_elderly(_me_id, e["id"])
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

with st.container(border=True):
    section("我的影响力")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        stat("上报问题", str(stats["total_issues"]), TOKEN["accent"])
    with col2:
        stat("已解决", str(stats["resolved_issues"]), TOKEN["success"])
    with col3:
        stat("提交提案", str(stats["total_proposals"]), TOKEN["accent"])
    with col4:
        stat("提案被采纳", str(stats["adopted_proposals"]), TOKEN["success"])

    # 影响力总结（治理化表述：聚焦「你推动了什么」，不做排行榜式等级）
    if stats["total_issues"] + stats["total_proposals"] > 0:
        resolved = stats["resolved_issues"]
        adopted = stats["adopted_proposals"]
        impact = f"🌱 你上报的 {stats['total_issues']} 件诉求中 {resolved} 件已解决"
        if adopted:
            impact += f"，{adopted} 条提案被采纳"
        st.markdown(
            f'<div style="text-align:center;margin:8px 0 4px;">'
            f'<span style="background:{TOKEN["accent_bg"]};color:{TOKEN["text"]};font-size:0.85em;'
            f'padding:6px 14px;border-radius:99px;border:1px solid {TOKEN["accent_border"]};">{impact}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")

section("我上报的问题")

my_issues = cached_my_issues(author, limit=20)

if not my_issues:
    info_card("还没有上报过诉求", "成为第一个让社区变好的人")
    if st.button("🔧 去上报诉求", type="primary", width="stretch"):
        st.switch_page("ui/pages/issues.py")
else:
    # 状态统计
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

    if st.session_state.get("_sat_feedback"):
        st.success(st.session_state.pop("_sat_feedback"))

    cols = st.columns(2)
    for idx, issue in enumerate(my_issues):
        with cols[idx % 2]:
            issue_card(issue)
            if issue.get("status") == "已解决":
                _render_satisfaction(issue)
            elif issue.get("status") == "待复核":
                _reason = issue.get("satisfaction_reason", "")
                st.caption("🔄 已评价：不满意" + (f"（原因：{_reason}）" if _reason else "") + "，等待网格员复核")

st.markdown("---")

# 匿名工单：按 reporter_id 追溯，不暴露真实身份
_reporter_id = (profile or {}).get("id")
_anon_issues = get_my_anonymous_issues(_reporter_id, limit=20) if _reporter_id else []
if _anon_issues:
    st.markdown("---")
    section("我的匿名工单")
    st.caption("🙈 匿名上报的工单只对你本人可见（按身份哈希追溯），不会公开你的真实信息。")
    _acols = st.columns(2)
    for _idx, _issue in enumerate(_anon_issues):
        with _acols[_idx % 2]:
            issue_card(_issue)
            if _issue.get("status") == "已解决":
                _render_satisfaction(_issue)
            elif _issue.get("status") == "待复核":
                _reason = _issue.get("satisfaction_reason", "")
                st.caption("🔄 已评价：不满意" + (f"（原因：{_reason}）" if _reason else "") + "，等待网格员复核")

st.markdown("---")

section("我提交的提案")

my_proposals = cached_my_proposals(author, limit=20)

if not my_proposals:
    info_card("还没有发起过提案", "在「邻里议事」发起你的第一个提案")
    if st.button("💬 去发起提案", type="primary", width="stretch"):
        st.switch_page("ui/pages/voice.py")
else:
    for p in my_proposals:
        s = p.get("status", "讨论中")
        emoji_map = {"讨论中": "💬", "已回应": "📝", "已采纳": "✅", "已实施": "🎉"}
        emoji = emoji_map.get(s, "📌")
        bg_color = {"讨论中": TOKEN["accent_bg"], "已回应": TOKEN["accent_bg"], "已采纳": TOKEN["success_bg"], "已实施": TOKEN["success_bg"]}.get(s, TOKEN["page_bg"])
        bd_color = {"讨论中": TOKEN["accent_border"], "已回应": TOKEN["accent_border"], "已采纳": TOKEN["success_border"], "已实施": TOKEN["success_border"]}.get(s, TOKEN["border"])
        st.markdown(
            f'<div style="background:{bg_color};border:1px solid {bd_color};'
            f'border-radius:{TOKEN["radius_card"]};padding:12px 16px;margin:6px 0;'
            f'box-shadow:{TOKEN["shadow_sm"]};font-size:0.88em;line-height:1.5;">'
            f'{emoji} <strong style="color:{TOKEN["text"]};">{p.get("title","")[:40]}</strong>'
            f'&nbsp;{tag(s)}'
            f'<br><span style="color:{TOKEN["text_sec"]};font-size:0.82em;">'
            f'👍 {p.get("supporter_count",0)} 人附议 · {p.get("category","")}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")

st.markdown(
    f'<div style="text-align:center;font-size:0.82em;color:{TOKEN["text_muted"]};margin-top:12px;">'
    f'参与记录 · 实时更新</div>',
    unsafe_allow_html=True,
)
