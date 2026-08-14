# ui/notify.py
"""实时通知 — 侧边栏角标 + toast 弹提醒。

在 st.session_state 里记「上次看到」的计数，每次 rerun 对比变化。
居民端有新房客问题、网格员端紧急工单变多时，弹 toast 并在侧边栏显示角标。

架构：
  - 每次把库里当前计数和 session_state 里缓存的计数比一下
  - 发现变化就更新缓存 + 弹 toast + 画角标
  - 角标是 CSS 红点带数字，画在侧边栏
  - toast 用 st.toast（Streamlit 1.59+）
"""

import logging
import streamlit as st
from ui.components import TOKEN
from ui.session_state import SS

_log = logging.getLogger(__name__)


def _fetch_counts():
    """从库里取当前计数，库不可用时返回 None。"""
    try:
        from ui.cache import cached_issues_stats, cached_proposals_stats
        i_stats = cached_issues_stats()
        p_stats = cached_proposals_stats()
        # 紧急工单数直接查库
        try:
            from data.database import get_issues
            urgent_issues = get_issues(urgency="紧急", limit=100)
            urgent = len([i for i in urgent_issues if i.get("status") != "已解决"])
        except Exception:
            _log.debug("查询通知要用的紧急工单数失败", exc_info=True)
            urgent = 0

        return {
            "total": i_stats["total"],
            "pending": i_stats["by_status"].get("待处理", 0),
            "urgent": urgent,
            "proposal_total": p_stats["total"],
            "proposal_pending": p_stats["by_status"].get("讨论中", 0),
        }
    except Exception:  # 挂了就算了，不阻塞
        _log.debug("_fetch_counts 挂了", exc_info=True)
        return None


def check_and_notify():
    """入口 — 检查有没有新东西，弹 toast，更新缓存计数。

    每次 rerun 调一次，放在页面内容之前（引导页通过之后）。

    居民端：有新工单就提醒；网格员端：新紧急工单、新提案会提醒。
    """
    counts = _fetch_counts()
    if not counts:
        return

    role = st.session_state.get("memory")
    if role:
        try:
            role = role.get_user_profile().get("role", "resident")
        except Exception:
            _log.debug("从记忆档案解析用户角色失败", exc_info=True)
            role = "resident"
    else:
        role = "resident"

    if role == "resident":
        last_total = st.session_state.get(SS.notif_last_total, 0)
        if counts["total"] > last_total and last_total > 0:
            new_count = counts["total"] - last_total
            try:
                st.toast(
                    f"📢 社区新增 {new_count} 件工单，点击左侧「🌊 社区脉搏」查看最新动态",
                    icon="📢",
                )
            except Exception:  # 记个日志跳过就行
                _log.debug("st.toast 弹居民端通知失败（非致命错误）")
        st.session_state[SS.notif_last_total] = counts["total"]

    else:
        last_urgent = st.session_state.get(SS.notif_last_urgent, -1)
        last_proposal = st.session_state.get(SS.notif_last_proposal, -1)

        # 第一次进来只缓存，不弹通知
        if last_urgent == -1:
            st.session_state[SS.notif_last_urgent] = counts["urgent"]
            st.session_state[SS.notif_last_proposal] = counts["proposal_total"]
            st.session_state[SS.notif_last_pending] = counts["pending"]
            return

        toasts = []

        if counts["urgent"] > last_urgent:
            new_urgent = counts["urgent"] - last_urgent
            toasts.append(f"🔴 {new_urgent} 件新紧急工单需要立即处理")

        if counts["proposal_total"] > last_proposal:
            new_props = counts["proposal_total"] - last_proposal
            toasts.append(f"💡 {new_props} 件新提案等待回复")

        for msg in toasts:
            try:
                st.toast(msg, icon="🔔")
            except Exception:  # 记个日志跳过就行
                _log.debug("st.toast 弹网格端通知失败（非致命错误）")

        st.session_state[SS.notif_last_urgent] = counts["urgent"]
        st.session_state[SS.notif_last_proposal] = counts["proposal_total"]
        st.session_state[SS.notif_last_pending] = counts["pending"]


def render_sidebar_badge():
    """在侧边栏渲染通知角标。

    展示：
      - 🔴 紧急工单数（只有网格员看得到）
      - 🟡 待处理数
      - 🔔 未读消息数（两个角色都有）
    """
    counts = _fetch_counts()
    if not counts:
        return

    role = st.session_state.get("memory")
    if role:
        try:
            role = role.get_user_profile().get("role", "resident")
        except Exception:  # 挂了就算了
            _log.debug("在 render_sidebar_badge 里解析用户角色失败", exc_info=True)
            return
    else:
        return

    user_id = st.session_state.get(SS.login_user_id, 0)

    unread_note = 0
    try:
        from data.db_notifications import get_unread_count
        unread_note = get_unread_count(user_id)
    except Exception:  # 记个日志跳过就行
        _log.debug("用户 #%d 的 get_unread_count 查不到（非致命错误）", user_id)

    if role == "grid":
        urgent = counts.get("urgent", 0)
        pending = counts.get("pending", 0)

        badge_html = '<div style="display:flex;gap:8px;align-items:center;margin:4px 0;flex-wrap:wrap;">'

        if urgent > 0:
            badge_html += (
                f'<span style="background:{TOKEN["sidebar_dang_bg"]};color:{TOKEN["sidebar_dang"]};'
                f'border:1px solid {TOKEN["sidebar_dang"]};border-radius:99px;'
                f'padding:2px 10px;font-size:0.75em;font-weight:700;white-space:nowrap;">'
                f'🔴 {urgent} 紧急</span>'
            )

        if pending > 0:
            badge_html += (
                f'<span style="background:{TOKEN["sidebar_warn_bg"]};color:{TOKEN["sidebar_warn"]};'
                f'border:1px solid {TOKEN["sidebar_warn"]};border-radius:99px;'
                f'padding:2px 10px;font-size:0.75em;font-weight:700;white-space:nowrap;">'
                f'⏳ {pending} 待处理</span>'
            )

        badge_html += '</div>'

        if urgent > 0 or pending > 0:
            st.markdown(badge_html, unsafe_allow_html=True)

    # 居民端：显示待处理数 + 未读消息
    else:
        pending = counts.get("pending", 0)
        if pending > 5 or unread_note > 0:
            parts = []
            if pending > 5:
                parts.append(f'⏳ 全小区 {pending} 件待处理')
            if unread_note > 0:
                parts.append(f'🔔 {unread_note} 条新消息')
            st.markdown(
                f'<div style="font-size:0.75em;color:{TOKEN["sidebar_warn"]};'
                f'padding:3px 0;">{" · ".join(parts)}</div>',
                unsafe_allow_html=True,
            )
