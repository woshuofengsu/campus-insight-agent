# agent/roles/base.py
"""角色 Agent 基类：每个角色 = 职责声明 + 工具白名单 + 停机点 + process()。

薄壳设计：process() 调用现有数据层/规则引擎（web_agent / data/*），不复制业务逻辑。
"""
from __future__ import annotations

from typing import Any, Optional


class BaseAgent:
    """所有角色 Agent 的基类。"""

    # ---- 角色元数据（可被 Orchestrator 汇总成「角色清单」，供答辩/文档） ----
    key: str = ""                 # 机器标识，如 repair_dispatch
    name: str = ""                # 显示名，如 报修调度员
    icon: str = ""                # 前端图标 emoji
    role_desc: str = ""           # 职责描述
    audience: str = ""            # 面向用户：居民/老人/负责人/自动/后台
    tools_whitelist: list[str] = []   # 可调用工具/数据域白名单
    human_stop: str = ""          # 停机点（必须人工确认/批准的地方）

    def __init__(self, blackboard):
        self.bb = blackboard

    # ---- 协议接口 ----

    def process(self, ctx: dict) -> dict:
        """处理一轮请求。ctx 含 user_input / user_context / state 等。
        返回 {reply, status, intent, actions, related_id, chain_note, done}。
        """
        raise NotImplementedError

    def process_negotiation(self, msg: dict) -> dict | None:
        """处理协商消息（task_request/notify/handoff）。返回响应 payload 或 None（不响应）。

        默认不响应；业务 Agent 按需覆盖（如健康顾问处理天气联动的健康提醒）。
        """
        return None

    # ---- 工具 ----

    def _read(self, key: str, default: Any = None) -> Any:
        v = self.bb.read(key)
        return default if v is None else v

    def _write(self, key: str, value: Any, lock: bool = False) -> None:
        self.bb.write(key, value, self.key, lock=lock)

    def _post(self, target: str, mtype: str, payload: dict) -> None:
        self.bb.post_message(target, {
            "from": self.key, "to": target, "type": mtype, "payload": payload,
        })

    def _reply(self, text: str, status: str = "成功", intent: str = "",
               actions: Optional[list] = None, related_id: Optional[int] = None,
               done: bool = True, chain_note: str = "") -> dict:
        return {
            "reply": text, "status": status, "intent": intent or self.key,
            "actions": actions or [], "related_id": related_id, "done": done,
            "chain_note": chain_note,
        }
