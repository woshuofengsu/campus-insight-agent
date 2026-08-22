# -*- coding: utf-8 -*-
"""轻量黑板（Blackboard）—— 多 Agent 共享上下文 + 消息协议 + 锁 + 历史。

9 个角色 Agent 通过黑板协作：
- shared_data：共享数据键值（带写入者/版本/时间戳）
- messages：Agent 间消息队列（task_request / task_response / notify / error / handoff）
- locks：写锁（防并发写同一键）
- history：全量操作历史（供执行链/审计/复盘）
"""
import uuid
from datetime import datetime
from typing import Any, Optional


class BlackboardLockError(Exception):
    """黑板键被锁定时写操作抛出。"""


class Blackboard:
    """共享黑板：跨 Agent 的键值存储 + 消息队列 + 锁。"""

    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())
        self.shared_data: dict[str, dict] = {}
        self.messages: dict[str, list[dict]] = {}
        self.locks: dict[str, bool] = {}
        self.history: list[dict] = []

    # ---- 共享数据 ----

    def write(self, key: str, value: Any, writer: str, lock: bool = False) -> None:
        """写入共享键（可选加锁，锁后他人写会抛 BlackboardLockError）。"""
        if self.locks.get(key):
            raise BlackboardLockError(f"Key {key} is locked")
        self.shared_data[key] = {
            "value": value,
            "timestamp": datetime.now().isoformat(),
            "writer": writer,
            "version": self.shared_data.get(key, {}).get("version", 0) + 1,
        }
        if lock:
            self.locks[key] = True
        self._hist("write", key, writer, {"value": str(value)[:120]})

    def read(self, key: str, reader: str = "") -> Any:
        """读取共享键值；无则 None。"""
        item = self.shared_data.get(key)
        if reader:
            self._hist("read", key, reader)
        return item["value"] if item else None

    def read_meta(self, key: str) -> Optional[dict]:
        """读取共享键完整元数据（值/写入者/版本/时间）。"""
        return self.shared_data.get(key)

    # ---- 消息协议 ----

    def post_message(self, target_agent: str, message: dict) -> None:
        """向目标 Agent 发消息（含消息类型与载荷）。"""
        if target_agent not in self.messages:
            self.messages[target_agent] = []
        self.messages[target_agent].append({
            **message,
            "timestamp": datetime.now().isoformat(),
        })

    def get_messages(self, agent_name: str) -> list[dict]:
        return list(self.messages.get(agent_name, []))

    def clear_messages(self, agent_name: str) -> None:
        self.messages[agent_name] = []

    # ---- 锁 ----

    def lock(self, key: str) -> None:
        self.locks[key] = True

    def unlock(self, key: str) -> None:
        self.locks[key] = False

    # ---- 历史 ----

    def _hist(self, action: str, key: str, agent: str, detail: Any = None) -> None:
        self.history.append({
            "action": action,
            "key": key,
            "agent": agent,
            "detail": detail,
            "timestamp": datetime.now().isoformat(),
        })

    def get_history(self, limit: int = 100) -> list[dict]:
        """黑板操作历史（供执行链可视化/审计）。"""
        return self.history[-limit:]

    def to_dict(self) -> dict:
        """序列化（供前端执行链/审计展示；值截断防泄露敏感详情）。"""
        return {
            "session_id": self.session_id,
            "shared_keys": [{
                "key": k,
                "writer": v.get("writer"),
                "version": v.get("version"),
                "locked": self.locks.get(k, False),
                "timestamp": v.get("timestamp"),
            } for k, v in self.shared_data.items()],
            "messages": {k: len(v) for k, v in self.messages.items()},
            "history": self.get_history(50),
        }
