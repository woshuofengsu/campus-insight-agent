# agent/roles/__init__.py
"""角色 Agent 包：9 个声明式角色 + 元数据 + 工厂。"""
from agent.roles.base import BaseAgent
from agent.roles.config import ROLE_META, ROUTE_MAP
from agent.roles.receptionist import ReceptionistAgent
from agent.roles.business_agents import (
    RepairDispatchAgent, ProposalCollabAgent, PolicyExpertAgent,
    HealthAdvisorAgent, NotificationManagerAgent,
)
from agent.roles.auto_agents import WeatherGuardianAgent, GridAssistantAgent
from agent.roles.compliance import ComplianceAuditorAgent

AGENT_CLASSES = {
    "receptionist": ReceptionistAgent,
    "repair_dispatch": RepairDispatchAgent,
    "proposal_collab": ProposalCollabAgent,
    "health_advisor": HealthAdvisorAgent,
    "policy_expert": PolicyExpertAgent,
    "notification_manager": NotificationManagerAgent,
    "weather_guardian": WeatherGuardianAgent,
    "grid_assistant": GridAssistantAgent,
    "compliance_auditor": ComplianceAuditorAgent,
}


def create_agents(blackboard) -> dict:
    """实例化全部角色（共享同一黑板）。"""
    return {key: cls(blackboard) for key, cls in AGENT_CLASSES.items()}


def role_list() -> list[dict]:
    """角色清单（答辩/文档自动生成）。"""
    return [{"key": k, **ROLE_META[k]} for k in ("receptionist", "repair_dispatch",
            "proposal_collab", "health_advisor", "policy_expert", "notification_manager",
            "weather_guardian", "grid_assistant", "compliance_auditor")]
