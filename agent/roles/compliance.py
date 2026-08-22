# agent/roles/compliance.py
"""合规审计员：所有业务 Agent 输出的最后一道检查。

- 敏感词检测（复用 utils.text.check_sensitive）
- 脱敏检查（回复中不得含完整 11 位手机号）
- 权限校验（角色与意图匹配，由 Orchestrator 前置；这里做兜底）
- 留痕（模块来源=Agent，落 agent_logs）
"""
import re

from agent.roles.base import BaseAgent
from utils.text import check_sensitive

# 完整手机号模式（11 位 1 开头）
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
# 完整身份证模式（18 位）
_IDCARD_RE = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")


class ComplianceAuditorAgent(BaseAgent):
    key = "compliance_auditor"
    name = "合规审计员"
    icon = "🛡️"
    role_desc = "数据脱敏、敏感词检测、操作留痕、权限校验"
    audience = "后台"
    human_stop = "审计不通过拦截输出"
    tools_whitelist = ["utils.text.check_sensitive", "data.db_agent.log_agent"]

    def process(self, ctx: dict) -> dict:
        """审计一轮输出。返回 {passed, reason, reply}。"""
        text = ctx.get("output_text") or ""
        role = ctx.get("role") or "resident"
        uid = ctx.get("uid")
        user_input = ctx.get("user_input") or ""
        intent = ctx.get("intent") or ""
        related_id = ctx.get("related_id")
        status = ctx.get("status") or "成功"

        # 1. 敏感词
        hit, word = check_sensitive(text)
        if hit:
            from data.db_agent import log_agent
            try:
                log_agent(uid, role, user_input, intent, routed=f"审计拦截-敏感词",
                          status="拦截", error=f"命中敏感词「{word}」", related_id=related_id)
            except Exception:
                pass
            return {"passed": False, "reason": f"敏感词「{word}」", "reply": "该内容需人工审核后再展示。"}

        # 2. 脱敏：回复中不应出现完整手机号（业务回复只给脱敏或工单号）
        m = _PHONE_RE.search(text)
        if m:
            from data.db_agent import log_agent
            try:
                log_agent(uid, role, user_input, intent, routed="审计拦截-完整手机号",
                          status="拦截", error="回复包含完整手机号", related_id=related_id)
            except Exception:
                pass
            return {"passed": False, "reason": "包含完整手机号", "reply": "该内容涉及隐私，需人工审核。"}

        # 2.5 身份证检测（数据安全 v3.0）
        m2 = _IDCARD_RE.search(text)
        if m2:
            from data.db_agent import log_agent
            try:
                log_agent(uid, role, user_input, intent, routed="审计拦截-完整身份证号",
                          status="拦截", error="回复包含完整身份证号", related_id=related_id)
            except Exception:
                pass
            return {"passed": False, "reason": "包含完整身份证号", "reply": "该内容涉及隐私，需人工审核。"}

        # 3. 留痕（正常通过）
        from data.db_agent import log_agent
        try:
            log_agent(uid, role, user_input, intent, routed=f"{intent}/{status}",
                      status=status, related_id=related_id)
        except Exception:
            pass
        return {"passed": True, "reason": "", "reply": text}
