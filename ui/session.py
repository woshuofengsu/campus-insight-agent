# ui/session.py
"""Shared session initialization — DB, Agent, Memory. Cached in st.session_state."""
import streamlit as st
from config import DB_PATH, OFFLINE_MODE
from data.database import init_db
from data.seed import seed_all
from ui.session_state import SS

# Bump this when agent code changes to force recreation on hot-reload.
# The agent instance is cached in session_state and Streamlit's hot-reload
# preserves session_state, so old agent code survives file changes.
_AGENT_VERSION = 4


def init_session():
    """Initialize database, agent, and memory. Idempotent — runs once per session."""
    # ── Database (ALWAYS init — must survive Streamlit hot-reload which
    #     preserves session_state but resets module-level _DB_PATH) ──
    init_db(DB_PATH)

    # ── Agent version check: force recreation when code changes ──
    # Streamlit hot-reload preserves session_state but reloads Python modules,
    # so the agent instance in session_state runs OLD code after a file edit.
    # Comparing a version stamp detects this and rebuilds the agent.
    cached_version = st.session_state.get(SS.agent_version, 0)
    if cached_version != _AGENT_VERSION:
        # Clear cached agent so it gets recreated with latest code
        st.session_state.pop(SS.agent, None)
        st.session_state.pop(SS.memory, None)
        st.session_state.pop("session_ready", None)
        st.session_state[SS.agent_version] = _AGENT_VERSION

    if "session_ready" in st.session_state:
        return st.session_state.agent, st.session_state.memory

    seed_all(DB_PATH)
    # ── Live data generation (time-driven, makes data feel alive) ──
    try:
        from data.live_generator import generate_today_events
        generate_today_events()
    except Exception:
        pass  # non-critical — demo still works with seed data alone
    # ── Background perception scan (AI autonomously senses campus) ──
    try:
        from data.db_perception import run_perception_scan
        run_perception_scan()
    except Exception:
        pass  # non-critical — perception is optional

    # ── Offline mode via URL param, env var, or forced (no API key) ──
    is_offline = OFFLINE_MODE
    try:
        qp = st.query_params.get("offline")
        if qp and str(qp).lower() in ("1", "true", "yes"):
            is_offline = True
    except Exception:  # non-critical: silent pass intended
        pass
    # Check for forced offline (auto-detected when no API key)
    if st.session_state.get(SS.force_offline, False):
        is_offline = True

    # ── Agent (offline or real) ──
    if "agent" not in st.session_state:
        if is_offline:
            from agent.offline_agent import OfflineAgent
            st.session_state.agent = OfflineAgent(st.session_state)
        else:
            from agent.engine import CampusAgent
            st.session_state.agent = CampusAgent(st.session_state)

    agent = st.session_state.agent
    memory = agent.memory
    st.session_state.memory = memory
    st.session_state.session_ready = True

    return agent, memory
