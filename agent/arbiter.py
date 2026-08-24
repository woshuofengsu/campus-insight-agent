# agent/arbiter.py
"""冲突仲裁器：合规优先 → 安全优先 → 专业优先 → 人工优先 → 数据一致 → 默认保守。

裁决结果：
- block：拦截输出（合规审计否决权）
- human：转人工
- professional：采纳专业 Agent 意见
- latest_version：使用最新数据版本
- default：无法裁决转人工
"""
from datetime import datetime
from typing import Any


class Arbiter:
    """按规则顺序裁决 Agent 间冲突。"""

    def __init__(self):
        self.rules: list[dict[str, Any]] = [
            {
                "name": "compliance_first",
                "condition": lambda c: c.get("audit_failed", False),
                "decision": "block",
                "explanation": "合规审计不通过，输出被拦截",
            },
            {
                "name": "safety_first",
                "condition": lambda c: c.get("safety_risk", False),
                "decision": "human",
                "explanation": "涉及人身安全，转人工处理",
            },
            {
                "name": "professional_first",
                "condition": lambda c: c.get("professional_domain", False),
                "decision": "professional",
                "explanation": "业务判断以专业 Agent 意见为准",
            },
            {
                "name": "manual_required",
                "condition": lambda c: c.get("irreversible", False) or c.get("cost_involved", False),
                "decision": "human",
                "explanation": "涉及费用或不可逆操作，需人工确认",
            },
            {
                "name": "data_version",
                "condition": lambda c: c.get("version_conflict", False),
                "decision": "latest_version",
                "explanation": "数据版本冲突，以最新版本为准",
            },
        ]

    def arbitrate(self, conflict: dict[str, Any]) -> dict[str, Any]:
        """裁决：按规则顺序返回首个命中；否则默认转人工。每次决策落 agent_logs 留痕（P1-2）。"""
        result = None
        for rule in self.rules:
            try:
                if rule["condition"](conflict):
                    result = {
                        "decision": rule["decision"],
                        "explanation": rule["explanation"],
                        "rule": rule["name"],
                        "timestamp": datetime.now().isoformat(),
                    }
                    break
            except Exception:
                continue
        if result is None:
            result = {
                "decision": "human",
                "explanation": "无法自动裁决，转人工处理",
                "rule": "default",
                "timestamp": datetime.now().isoformat(),
            }
        self._log_decision(conflict, result)
        return result

    def _log_decision(self, conflict: dict[str, Any], result: dict[str, Any]) -> None:
        """仲裁决策留痕（模块来源=Agent，供 grid 端 /agent/logs?intent=仲裁 查询）。失败不阻断主流程。"""
        try:
            from data.db_agent import log_agent
            log_agent(None, "system", str(conflict)[:180], "仲裁",
                      routed=f"仲裁/{result['rule']}", status=result["decision"],
                      error=result["explanation"][:120])
        except Exception:
            pass
