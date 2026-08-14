# ui/session_state.py
"""st.session_state 键的带类型访问层。

所有 session_state 键的常量都只在这里定义，别处不许再用裸字符串，
防止手滑打错（比如 "_login_user_id" 和 "_login_user_Id"），找键也方便。

用法：
    from ui.session_state import SS, session
    uid = SS.login_user_id          # 读 st.session_state
    SS.login_user_id = 42           # 写 st.session_state
    SS.setdefault("_tour_step", 0)  # setdefault 用法

动态键（里面要嵌 id 的）用 key() 方法：
    SS.key("_batch", issue_id)      # → "_batch_42"
"""

import streamlit as st


# 键常量 — 唯一的定义处

class _Keys:
    """所有 session_state 键常量的命名空间。"""

    agent: str = "_agent"
    memory: str = "_memory"
    login_user_id: str = "_login_user_id"
    ob_role: str = "_ob_role"
    agent_version: str = "_agent_version"

    community_theme: str = "_community_theme"

    tour_step: str = "_tour_step"
    force_offline: str = "_force_offline"

    home_last_chain: str = "_home_last_chain"
    stream_events: str = "_stream_events"
    stream_current_tool: str = "_stream_current_tool"
    last_interaction: str = "_last_interaction"
    last_check_time: str = "_last_check_time"

    home_report_ok: str = "_home_report_ok"
    home_report_error: str = "_home_report_error"
    home_quick_title: str = "_home_quick_title"
    home_quick_loc: str = "_home_quick_loc"

    report_trace: str = "_report_trace"
    report_result: str = "_report_result"
    report_error: str = "_report_error"

    quick_tpl: str = "_quick_tpl"
    quick_tpl_label: str = "_quick_tpl_label"

    create_proposal_error: str = "_create_proposal_error"
    create_proposal_feedback: str = "_create_proposal_feedback"

    support_error: str = "_support_error"
    support_feedback: str = "_support_feedback"

    opinion_feedback: str = "_opinion_feedback"

    prop_reply_pid: str = "_prop_reply_pid"
    prop_reply_title: str = "_prop_reply_title"
    dash_reply_pid: str = "_dash_reply_pid"
    batch_note: str = "_batch_note"

    notif_last_total: str = "_ss_last_total"
    notif_last_urgent: str = "_ss_last_urgent"
    notif_last_pending: str = "_ss_last_pending"
    notif_last_proposal: str = "_ss_last_proposal"

    @staticmethod
    def key(prefix: str, entity_id: int) -> str:
        """动态键：SS.key('_batch', 42) → '_batch_42'。"""
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


# 唯一的实例
SS = _Keys()


# 带类型的访问器

class _Session:
    """常用 session_state 值的属性化访问。

    用 `session.login_user_id` 代替 `st.session_state.get("_login_user_id", 0)`。
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
    def community_theme(self) -> str:
        return st.session_state.get(SS.community_theme, "light")

    @community_theme.setter
    def community_theme(self, value: str) -> None:
        st.session_state[SS.community_theme] = value

    def get(self, key: str, default=None):
        """带类型的 get，常用键优先用上面的属性。"""
        return st.session_state.get(key, default)

    def setdefault(self, key: str, default) -> None:
        """键不存在时才写入 session_state。"""
        if key not in st.session_state:
            st.session_state[key] = default

    def pop(self, key: str, default=None):
        """从 session_state 弹出键（一次性标记用）。"""
        return st.session_state.pop(key, default) if key in st.session_state else default

    def clear_key(self, key: str) -> None:
        """安全删除 session_state 里的键。"""
        st.session_state.pop(key, None)


# 单例，供属性访问
session = _Session()
