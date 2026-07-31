# ui/notify.py
"""Real-time notification system — sidebar badges + toast alerts.

Tracks "last seen" counts in st.session_state and detects changes on each
rerun. When new issues appear (student view) or urgent items increase
(teacher view), shows a toast notification and sidebar badge.

Architecture:
  - Each check compares current DB counts vs. cached session_state counts
  - On detection, updates cache + fires toast + renders badge
  - Badge is a CSS red dot with count, rendered in sidebar
  - Toast uses st.toast (Streamlit 1.59+)
"""

import logging
import streamlit as st
from ui.components import TOKEN
from ui.session_state import SS

_log = logging.getLogger(__name__)


def _fetch_counts():
    """Fetch current counts from DB. Returns dict or None if DB unavailable."""
    try:
        from ui.cache import cached_issues_stats, cached_proposals_stats
        i_stats = cached_issues_stats()
        p_stats = cached_proposals_stats()
        # Query DB directly for urgent count
        try:
            from data.database import get_issues
            urgent_issues = get_issues(urgency="紧急", limit=100)
            urgent = len([i for i in urgent_issues if i.get("status") != "已解决"])
        except Exception:
            urgent = 0

        return {
            "total": i_stats["total"],
            "pending": i_stats["by_status"].get("待处理", 0),
            "urgent": urgent,
            "proposal_total": p_stats["total"],
            "proposal_pending": p_stats["by_status"].get("讨论中", 0),
        }
    except Exception:  # non-critical: graceful degradation
        return None


def check_and_notify():
    """Main entry point — check for new items, fire toasts, cache counts.

    Call once per rerun, before page content (after onboarding gate).

    For students: alerts on new pending issues matching their reports.
    For teachers: alerts on new urgent issues, new proposals.
    """
    counts = _fetch_counts()
    if not counts:
        return

    role = st.session_state.get("memory")
    if role:
        try:
            role = role.get_user_profile().get("role", "student")
        except Exception:
            role = "student"
    else:
        role = "student"

    # ── Student: new issues since last check ──
    if role == "student":
        last_total = st.session_state.get(SS.notif_last_total, 0)
        if counts["total"] > last_total and last_total > 0:
            new_count = counts["total"] - last_total
            try:
                st.toast(
                    f"📢 校园新增 {new_count} 件工单，点击左侧「🌊 校园脉搏」查看最新动态",
                    icon="📢",
                )
            except Exception:  # non-critical: logged and suppressed
                _log.debug("st.toast failed for student notification (non-critical)")
        st.session_state[SS.notif_last_total] = counts["total"]

    # ── Teacher: new urgent issues + new proposals ──
    else:
        last_urgent = st.session_state.get(SS.notif_last_urgent, -1)
        last_proposal = st.session_state.get(SS.notif_last_proposal, -1)

        # First load — just cache, don't notify
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
            except Exception:  # non-critical: logged and suppressed
                _log.debug("st.toast failed for teacher notification (non-critical)")

        st.session_state[SS.notif_last_urgent] = counts["urgent"]
        st.session_state[SS.notif_last_proposal] = counts["proposal_total"]
        st.session_state[SS.notif_last_pending] = counts["pending"]


def render_sidebar_badge():
    """Render notification badges in the sidebar.

    Shows:
      - 🔴 badge for urgent items (teacher only)
      - 🟡 badge for pending items
      - 🔔 badge for unread notifications (both roles)
    """
    counts = _fetch_counts()
    if not counts:
        return

    role = st.session_state.get("memory")
    if role:
        try:
            role = role.get_user_profile().get("role", "student")
        except Exception:  # non-critical: graceful degradation
            return
    else:
        return

    user_id = st.session_state.get("_login_user_id", 0)

    # ── Unread notification count (both roles) ──
    unread_note = 0
    try:
        from data.db_notifications import get_unread_count
        unread_note = get_unread_count(user_id)
    except Exception:  # non-critical: logged and suppressed
        _log.debug("get_unread_count failed for user #%d (non-critical)", user_id)

    if role == "teacher":
        urgent = counts.get("urgent", 0)
        pending = counts.get("pending", 0)

        badge_html = '<div style="display:flex;gap:8px;align-items:center;margin:4px 0;flex-wrap:wrap;">'

        if urgent > 0:
            badge_html += (
                f'<span style="background:{TOKEN["danger_bg"]};color:{TOKEN["danger"]};'
                f'border:1px solid {TOKEN["danger_border"]};border-radius:99px;'
                f'padding:2px 10px;font-size:0.72em;font-weight:700;white-space:nowrap;">'
                f'🔴 {urgent} 紧急</span>'
            )

        if pending > 0:
            badge_html += (
                f'<span style="background:{TOKEN["warning_bg"]};color:{TOKEN["warning"]};'
                f'border:1px solid {TOKEN["warning_border"]};border-radius:99px;'
                f'padding:2px 10px;font-size:0.72em;font-weight:700;white-space:nowrap;">'
                f'⏳ {pending} 待处理</span>'
            )

        badge_html += '</div>'

        if urgent > 0 or pending > 0:
            st.markdown(badge_html, unsafe_allow_html=True)

    # Student: show pending count + unread notifications
    else:
        pending = counts.get("pending", 0)
        if pending > 5 or unread_note > 0:
            parts = []
            if pending > 5:
                parts.append(f'⏳ 全校 {pending} 件待处理')
            if unread_note > 0:
                parts.append(f'🔔 {unread_note} 条新消息')
            st.markdown(
                f'<div style="font-size:0.72em;color:{TOKEN["warning"]};'
                f'padding:3px 0;">{" · ".join(parts)}</div>',
                unsafe_allow_html=True,
            )
