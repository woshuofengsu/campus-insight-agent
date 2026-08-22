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
        """裁决：按规则顺序返回首个命中；否则默认转人工。"""
        for rule in self.rules:
            try:
                if rule["condition"](conflict):
                    return {
                        "decision": rule["decision"],
                        "explanation": rule["explanation"],
                        "rule": rule["name"],
                        "timestamp": datetime.now().isoformat(),
                    }
            except Exception:
                continue
        return {
            "decision": "human",
            "explanation": "无法自动裁决，转人工处理",
            "rule": "default",
            "timestamp": datetime.now().isoformat(),
        }
