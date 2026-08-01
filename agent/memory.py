# agent/memory.py
"""Memory system: working (session), long-term (SQLite), knowledge (SQLite).

Memory pruning: working memory capped at MAX_WORKING_MESSAGES (sliding window).
LangChain ConversationBufferMemory is trimmed to MAX_LANGCHAIN_MESSAGES exchanges
to prevent unbounded token growth in long sessions.
"""
import json
import logging
from typing import Any
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage
from data.database import get_current_user, update_user_profile, set_onboarding_done

_logger = logging.getLogger("agent.memory")

# ── Pruning limits ──
MAX_WORKING_MESSAGES = 60      # keep last 60 messages in session_state
MAX_LANGCHAIN_MESSAGES = 20    # keep last 10 exchanges (20 messages) for LLM context


class MemoryManager:
    """Manages the three-tier memory system for the Agent.

    Multi-user aware: stores user_id in session_state and passes it to all
    DB operations so each user gets their own profile, preferences, and history.
    """

    def __init__(self, session_state: Any):
        """Initialize with Streamlit session_state."""
        self.st = session_state

        # Ensure session state keys exist
        if "messages" not in self.st:
            self.st.messages = []
        if "user_profile" not in self.st:
            self.st.user_profile = get_current_user()
        if "last_check_time" not in self.st:
            self.st.last_check_time = None
        if "last_interaction" not in self.st:
            self.st.last_interaction = None
        if "tool_registry" not in self.st:
            self.st.tool_registry = []
        # LangChain memory: create once, reuse across turns
        if "langchain_memory" not in self.st:
            self.st.langchain_memory = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                input_key="input",
                output_key="output",
            )

    # ── User identity ──

    @property
    def user_id(self) -> int:
        """The currently logged-in user's ID."""
        return self.st.get("_login_user_id", 1)

    def refresh_profile(self):
        """Re-read user profile from DB after a switch or update."""
        self.st.user_profile = get_current_user()

    # ── Working Memory (session_state.messages) ──

    def get_working_memory(self) -> list[dict]:
        return self.st.messages

    def add_message(self, role: str, content: str):
        from datetime import datetime
        self.st.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        # Update last_interaction for idle detection
        import time
        self.st.last_interaction = time.time()

        # ── Prune working memory if over limit ──
        if len(self.st.messages) > MAX_WORKING_MESSAGES:
            excess = len(self.st.messages) - MAX_WORKING_MESSAGES
            self.st.messages = self.st.messages[excess:]
            _logger.debug("Pruned %d old messages from working memory (now %d)",
                          excess, len(self.st.messages))

    def get_conversation_history(self, last_n: int = 20) -> list[dict]:
        """Get last N messages for LangChain context."""
        return self.st.messages[-last_n:]

    def _prune_langchain_memory(self):
        """Trim LangChain ConversationBufferMemory to prevent unbounded token growth.

        Keeps only the last MAX_LANGCHAIN_MESSAGES messages (10 exchanges).
        Called before each agent invocation so the LLM prompt stays compact.
        """
        try:
            lc_memory = self.st.langchain_memory
            buf = lc_memory.chat_memory.messages if hasattr(lc_memory, 'chat_memory') else []
            if len(buf) > MAX_LANGCHAIN_MESSAGES:
                excess = len(buf) - MAX_LANGCHAIN_MESSAGES
                lc_memory.chat_memory.messages = lc_memory.chat_memory.messages[excess:]
                _logger.debug("Pruned %d old messages from LangChain memory (now %d)",
                              excess, len(lc_memory.chat_memory.messages))
        except Exception:
            _logger.debug("Failed to prune LangChain memory messages", exc_info=True)
            pass  # non-critical — if pruning fails, memory just grows

    # ── Long-Term Memory (SQLite user_profile) ──

    def get_user_profile(self) -> dict:
        """Get user profile, syncing from DB if needed.

        Uses try/except because Streamlit's session_state proxy may raise
        AttributeError even after an ``"in"`` containment check passes.
        """
        try:
            profile = self.st.user_profile
        except AttributeError:
            profile = None
        if not profile:
            self.st.user_profile = get_current_user()
        return self.st.user_profile

    def update_profile(self, **kwargs):
        """Update user profile in both session and DB."""
        uid = kwargs.pop("user_id", self.user_id)
        update_user_profile(user_id=uid, **kwargs)
        # Refresh session state
        self.st.user_profile = get_current_user()

    def complete_onboarding(self):
        """Mark onboarding as done for the current user."""
        set_onboarding_done(self.user_id)
        self.st.user_profile = get_current_user()

    def is_onboarding_done(self) -> bool:
        profile = self.get_user_profile()
        return bool(profile.get("onboarding_done", False))

    # ── Tool Registry ──

    def register_tools(self, tool_names: list[str]):
        self.st.tool_registry = tool_names

    def get_tool_registry(self) -> list[str]:
        return self.st.tool_registry

    # ── LangChain Integration ──

    def get_langchain_memory(self) -> ConversationBufferMemory:
        """Return the persistent LangChain ConversationBufferMemory (stored in session_state).

        Prunes old messages before returning to keep the LLM context compact.
        """
        self._prune_langchain_memory()
        return self.st.langchain_memory
