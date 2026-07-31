# ui/session_state.py
"""Typed access layer for st.session_state keys.

All session_state key constants are defined HERE — nowhere else should
raw string keys be used. This prevents typos (e.g. "_login_user_id" vs
"_login_user_Id") and makes key discovery trivial.

Usage:
    from ui.session_state import SS, session
    uid = SS.login_user_id          # reads st.session_state
    SS.login_user_id = 42           # writes st.session_state
    SS.setdefault("_tour_step", 0)  # setdefault pattern

For dynamic keys (those that embed an id), use the `key()` method:
    SS.key("_batch", issue_id)      # → "_batch_42"
"""

import streamlit as st


# ═══════════════════════════════════════════
# Key Constants — single source of truth
# ═══════════════════════════════════════════

class _Keys:
    """Namespace for all session_state key constants."""

    # ── Core (set during init_session) ──
    agent: str = "_agent"
    memory: str = "_memory"
    login_user_id: str = "_login_user_id"
    ob_role: str = "_ob_role"
    agent_version: str = "_agent_version"

    # ── Theme ──
    campus_theme: str = "_campus_theme"

    # ── Onboarding ──
    tour_step: str = "_tour_step"
    force_offline: str = "_force_offline"

    # ── Chat / OODA flow ──
    home_last_chain: str = "_home_last_chain"
    stream_events: str = "_stream_events"
    stream_current_tool: str = "_stream_current_tool"
    last_interaction: str = "_last_interaction"
    last_check_time: str = "_last_check_time"

    # ── Quick report ──
    home_report_ok: str = "_home_report_ok"
    home_report_error: str = "_home_report_error"
    home_quick_title: str = "_home_quick_title"
    home_quick_loc: str = "_home_quick_loc"

    # ── Agent reporting (action_report_issue) ──
    report_trace: str = "_report_trace"
    report_result: str = "_report_result"
    report_error: str = "_report_error"

    # ── Quick action chips ──
    quick_tpl: str = "_quick_tpl"
    quick_tpl_label: str = "_quick_tpl_label"

    # ── Create proposal ──
    create_proposal_error: str = "_create_proposal_error"
    create_proposal_feedback: str = "_create_proposal_feedback"

    # ── Support proposal ──
    support_error: str = "_support_error"
    support_feedback: str = "_support_feedback"

    # ── Express opinion ──
    opinion_feedback: str = "_opinion_feedback"

    # ── Dashboard / Issues quick actions ──
    prop_reply_pid: str = "_prop_reply_pid"
    prop_reply_title: str = "_prop_reply_title"
    dash_reply_pid: str = "_dash_reply_pid"
    batch_note: str = "_batch_note"

    # ── Notification tracking (ui/notify.py) ──
    notif_last_total: str = "_ss_last_total"
    notif_last_urgent: str = "_ss_last_urgent"
    notif_last_pending: str = "_ss_last_pending"
    notif_last_proposal: str = "_ss_last_proposal"

    # ── Dynamic keys (embed entity id) ──
    @staticmethod
    def key(prefix: str, entity_id: int) -> str:
        """Generic dynamic key: SS.key('_batch', 42) → '_batch_42'."""
        return f"{prefix}_{entity_id}"

    @staticmethod
    def batch(issue_id: int) -> str:
        return f"_batch_{issue_id}"

    @staticmethod
    def detail(issue_id: int) -> str:
        return f"_detail_{issue_id}"

    @staticmethod
    def detail_note(issue_id: int) -> str:
        return f"_detail_note_{issue_id}"

    @staticmethod
    def detail_assignee(issue_id: int) -> str:
        return f"_detail_assignee_{issue_id}"

    @staticmethod
    def quick_note(issue_id: int) -> str:
        return f"_quick_note_{issue_id}"

    @staticmethod
    def sla_note(issue_id: int) -> str:
        return f"_sla_note_{issue_id}"

    @staticmethod
    def opinion_input(topic_id: int) -> str:
        return f"_opinion_input_{topic_id}"

    @staticmethod
    def confirm_delete(entity_id: int) -> str:
        return f"_confirm_delete_{entity_id}"


# Single canonical instance
SS = _Keys()


# ═══════════════════════════════════════════
# Typed Accessor
# ═══════════════════════════════════════════

class _Session:
    """Typed property access to frequently-used session_state values.

    Use `session.login_user_id` instead of `st.session_state.get("_login_user_id", 0)`.
    """

    @property
    def login_user_id(self) -> int:
        return st.session_state.get(SS.login_user_id, 0)

    @login_user_id.setter
    def login_user_id(self, value: int) -> None:
        st.session_state[SS.login_user_id] = value

    @property
    def agent(self):
        return st.session_state.get(SS.agent)

    @agent.setter
    def agent(self, value) -> None:
        st.session_state[SS.agent] = value

    @property
    def memory(self):
        return st.session_state.get(SS.memory)

    @memory.setter
    def memory(self, value) -> None:
        st.session_state[SS.memory] = value

    @property
    def campus_theme(self) -> str:
        return st.session_state.get(SS.campus_theme, "light")

    @campus_theme.setter
    def campus_theme(self, value: str) -> None:
        st.session_state[SS.campus_theme] = value

    def get(self, key: str, default=None):
        """Typed get — prefer specific properties for common keys."""
        return st.session_state.get(key, default)

    def setdefault(self, key: str, default) -> None:
        """Set a key in session_state if not already present."""
        if key not in st.session_state:
            st.session_state[key] = default

    def pop(self, key: str, default=None):
        """Pop a key from session_state (useful for one-shot flags)."""
        return st.session_state.pop(key, default) if key in st.session_state else default

    def clear_key(self, key: str) -> None:
        """Safely remove a key from session_state."""
        st.session_state.pop(key, None)


# Singleton instance for property access
session = _Session()
