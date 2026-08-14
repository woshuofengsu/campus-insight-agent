# agent/memory.py
"""记忆系统：工作记忆（会话）、长期记忆（SQLite）、知识库（SQLite）。

记忆裁剪：工作记忆最多留 MAX_WORKING_MESSAGES 条（滑动窗口）；
LangChain 的 ConversationBufferMemory 截到 MAX_LANGCHAIN_MESSAGES 轮，
防止长会话里 token 无限膨胀。
"""
import json
import logging
from typing import Any
from langchain_classic.memory import ConversationBufferMemory
from langchain_core.messages import HumanMessage, AIMessage
from data.database import get_current_user, update_user_profile, set_onboarding_done

_logger = logging.getLogger("agent.memory")

# 裁剪上限
MAX_WORKING_MESSAGES = 60      # 会话里最多留 60 条消息
MAX_LANGCHAIN_MESSAGES = 20    # 给 LLM 的上下文最多留 10 轮（20 条）


class MemoryManager:
    """三层记忆：工作（会话）、长期（SQLite）、知识库（SQLite）。

    user_id 存在会话里，每个用户的历史和个人资料互不干扰。
    """

    def __init__(self, session_state: Any):
        """用 Streamlit 的 session_state 初始化。"""
        self.st = session_state

        # 确保会话状态里的键都存在
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
        # LangChain 记忆：只建一次，多轮复用
        if "langchain_memory" not in self.st:
            self.st.langchain_memory = ConversationBufferMemory(
                memory_key="chat_history",
                return_messages=True,
                input_key="input",
                output_key="output",
            )

    # 用户身份

    @property
    def user_id(self) -> int:
        """当前登录用户的 ID。"""
        return self.st.get("_login_user_id", 1)

    def refresh_profile(self):
        """切换账号或资料更新后，从数据库重新读一遍用户资料。"""
        self.st.user_profile = get_current_user()

    # 工作记忆（session_state.messages）

    def get_working_memory(self) -> list[dict]:
        return self.st.messages

    def add_message(self, role: str, content: str):
        from datetime import datetime
        self.st.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        # 更新最后交互时间，空闲检测要用
        import time
        self.st.last_interaction = time.time()

        # 超了上限就裁剪工作记忆
        if len(self.st.messages) > MAX_WORKING_MESSAGES:
            excess = len(self.st.messages) - MAX_WORKING_MESSAGES
            self.st.messages = self.st.messages[excess:]
            _logger.debug("清理工作记忆里的旧消息（共 %d 条，现在剩 %d 条）",
                          excess, len(self.st.messages))

    def get_conversation_history(self, last_n: int = 20) -> list[dict]:
        """取最近 N 条消息给 LangChain 当上下文。"""
        return self.st.messages[-last_n:]

    def _prune_langchain_memory(self):
        """裁剪 LangChain 的 ConversationBufferMemory，防止 token 无限涨。

        只留最近 MAX_LANGCHAIN_MESSAGES 条消息（10 轮对话）。
        每次调 Agent 前先裁一遍，prompt 才不会越堆越长。
        """
        try:
            lc_memory = self.st.langchain_memory
            buf = lc_memory.chat_memory.messages if hasattr(lc_memory, 'chat_memory') else []
            if len(buf) > MAX_LANGCHAIN_MESSAGES:
                excess = len(buf) - MAX_LANGCHAIN_MESSAGES
                lc_memory.chat_memory.messages = lc_memory.chat_memory.messages[excess:]
                _logger.debug("清理 LangChain 记忆里的旧消息（共 %d 条，现在剩 %d 条）",
                              excess, len(lc_memory.chat_memory.messages))
        except Exception:
            _logger.debug("清理 LangChain 记忆失败", exc_info=True)
            pass  # 非关键——裁失败最多就是记忆多占点地方

    # 长期记忆（SQLite user_profile）

    def get_user_profile(self) -> dict:
        """取用户资料，必要时从数据库同步。

        这里用 try/except 是因为 Streamlit 的 session_state 代理比较坑：
        就算 in 检查通过了，取值还是可能抛 AttributeError。
        """
        try:
            profile = self.st.user_profile
        except AttributeError:
            profile = None
        if not profile:
            self.st.user_profile = get_current_user()
        return self.st.user_profile

    def update_profile(self, **kwargs):
        """更新用户资料，会话和数据库都改。"""
        uid = kwargs.pop("user_id", self.user_id)
        update_user_profile(user_id=uid, **kwargs)
        # 刷新会话里的资料
        self.st.user_profile = get_current_user()

    def complete_onboarding(self):
        """把当前用户的引导流程标记为已完成。"""
        set_onboarding_done(self.user_id)
        self.st.user_profile = get_current_user()

    def is_onboarding_done(self) -> bool:
        profile = self.get_user_profile()
        return bool(profile.get("onboarding_done", False))

    # 工具注册表

    def register_tools(self, tool_names: list[str]):
        self.st.tool_registry = tool_names

    def get_tool_registry(self) -> list[str]:
        return self.st.tool_registry

    # LangChain 对接

    def get_langchain_memory(self) -> ConversationBufferMemory:
        """返回常驻的 LangChain ConversationBufferMemory（存在 session_state 里）。

        返回前先裁掉旧消息，LLM 上下文才不会越堆越长。
        """
        self._prune_langchain_memory()
        return self.st.langchain_memory
