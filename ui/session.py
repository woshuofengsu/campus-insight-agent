# ui/session.py
"""公共的会话初始化 — 数据库、Agent、记忆，都缓存在 st.session_state。"""
import streamlit as st
from config import DB_PATH, OFFLINE_MODE
from data.database import init_db
from data.seed import seed_all
from ui.session_state import SS
import logging
_log = logging.getLogger(__name__)

# 改代码后记得 +1，热重载会留着 session_state，靠版本号强制重建 agent
_AGENT_VERSION = 4


def init_session(need_agent: bool = True):
    """初始化数据库。need_agent=True 时同时建 agent 和记忆。

    登录页只跑 DB 部分（<0.1s），agent 延迟到登录后创建，避免登录页等 4s+。
    """
    init_db(DB_PATH)

    # 热重载会保留 session_state 但重新加载模块，用版本号强制重建
    cached_version = st.session_state.get(SS.agent_version, 0)
    if cached_version != _AGENT_VERSION:
        # 清掉缓存的 agent，下次用最新代码重建
        st.session_state.pop(SS.agent, None)
        st.session_state.pop(SS.memory, None)
        st.session_state.pop("session_ready", None)
        st.session_state[SS.agent_version] = _AGENT_VERSION

    if "session_ready" in st.session_state:
        return st.session_state.agent, st.session_state.memory

    seed_all(DB_PATH)
    try:
        from data.live_generator import generate_today_events
        generate_today_events()
    except Exception:
        _log.debug("非致命错误", exc_info=True)
        pass  # 不是关键步骤，光有种子数据也能跑
    try:
        from data.db_perception import run_perception_scan
        run_perception_scan()
    except Exception:
        _log.debug("非致命错误", exc_info=True)
        pass  # 感知扫描挂了不影响，可选的

    if need_agent:
        _create_agent()
        agent = st.session_state.agent
        memory = agent.memory
        st.session_state.memory = memory
        st.session_state.session_ready = True
        return agent, memory
    return None, None


def ensure_agent():
    """登录后补建 agent（若之前懒初始化没建）。幂等。"""
    if st.session_state.get("session_ready"):
        return st.session_state.agent, st.session_state.memory
    init_session(need_agent=True)
    return st.session_state.agent, st.session_state.memory


def _create_agent():
    """按离线/在线模式创建 agent（进程级工具缓存，第二次会话起近 0 耗时）。"""
    is_offline = OFFLINE_MODE
    try:
        qp = st.query_params.get("offline")
        if qp and str(qp).lower() in ("1", "true", "yes"):
            is_offline = True
    except Exception:  # 尽力而为，读不到就算了
        _log.debug("非致命错误", exc_info=True)
        pass
    # 强制离线开关（没配 API key 时自动打开）
    if st.session_state.get(SS.force_offline, False):
        is_offline = True
    if "agent" not in st.session_state:
        if is_offline:
            from agent.offline_agent import OfflineAgent
            st.session_state.agent = OfflineAgent(st.session_state)
        else:
            from agent.engine import CommunityAgent
            st.session_state.agent = CommunityAgent(st.session_state)
