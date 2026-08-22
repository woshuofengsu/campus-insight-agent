# agent/roles/business_agents.py
"""5 个业务角色 Agent（薄壳）：报修调度员 / 提案协商员 / 政策专员 / 健康顾问 / 通知管理员。
process() 复用现有数据层与规则引擎（web_agent_service / data/*），不复制业务逻辑。
会话状态（追问/草稿）存黑板：user:{uid}:state / user:{uid}:{draft_key}。
"""
from agent import web_agent as A
from agent.roles.base import BaseAgent


def _state_key(uid):
    return f"user:{uid}:state"


def _draft_key(uid, name):
    return f"user:{uid}:{name}"


# ---------------------------------------------------------------------------
# 报修调度员
# ---------------------------------------------------------------------------

class RepairDispatchAgent(BaseAgent):
    key = "repair_dispatch"
    name = "报修调度员"
    icon = "🔧"
    role_desc = "报修全流程：草稿、创建、分派、跟踪、反馈"
    audience = "居民/老人"
    human_stop = "生成工单前必须用户确认"
    tools_whitelist = ["db_repair.submit_issue", "db_repair.get_issues", "撤回引导"]

    def process(self, ctx: dict) -> dict:
        from agent.web_agent_service import _exec_report
        text = ctx.get("user_input") or ""
        uid = ctx.get("uid"); name = ctx.get("name") or "居民"
        st = self._read(_state_key(uid)) or {}
        draft = self._read(_draft_key(uid, "work_order_draft"))
        # 会话恢复（落库后黑板可能无 draft）：有 step 但无 draft 时补空草稿
        if draft is None and st.get("step"):
            draft = {}

        # 追问/确认阶段
        step = st.get("step")
        if step == "ask_type":
            draft["type"] = "室内" if ("内" in text or "家" in text) else "室外"
            st["step"] = "ask_urgency" if draft.get("urgency") is None else "confirm"
        elif step == "ask_urgency":
            draft["urgency"] = "紧急" if ("紧急" in text or "急" in text or st.get("urgent")) else "一般"
            st["step"] = "confirm"
        elif step == "confirm":
            if text in ("确认", "确认提交", "提交", "对", "是"):
                draft["urgency"] = draft.get("urgency") or "一般"  # 确认前兜底
                r_text, status, iid = _exec_report(uid, name, draft)
                self.bb.unlock(_draft_key(uid, "work_order_draft"))
                self._write(_draft_key(uid, "work_order_draft"), None, lock=False)
                st.clear()
                self._write(_state_key(uid), st)
                return self._reply(r_text, status, "报修", related_id=iid,
                                   chain_note="用户确认，工单已创建")
            st.clear()
            self._write(_state_key(uid), st)
            return self._reply("已取消，没有生成工单。", "已取消", "报修", chain_note="用户取消")

        # 新报修
        if draft is None:
            draft = {"desc": text, "type": "室内", "urgency": "紧急" if st.get("urgent") else None}
            if ctx.get("role") == "elderly":
                draft["urgency"] = draft["urgency"] or "一般"
                st["step"] = "confirm"
            else:
                st["step"] = "ask_type"
        else:
            st["step"] = st.get("step") or "ask_type"
        st["intent"] = "repair"

        self._write(_draft_key(uid, "work_order_draft"), draft, lock=False)
        self._write(_state_key(uid), st)

        if st["step"] == "ask_type":
            return self._reply("是您家里还是公共区域？", "追问", "报修",
                               actions=[{"type": "buttons", "options": ["家里", "公共区域"]}],
                               chain_note="追问分类")
        if st["step"] == "ask_urgency":
            return self._reply("是紧急情况吗？", "追问", "报修",
                               actions=[{"type": "buttons", "options": ["紧急", "一般"]}],
                               chain_note="追问紧急程度")
        urgent_txt = "紧急" if draft.get("urgency") == "紧急" else "一般"
        return self._reply(
            f"请您确认报修信息：\n· 问题：{draft.get('desc', '')[:60]}\n· 分类：{draft.get('type')}\n· 紧急程度：{urgent_txt}",
            "需确认", "报修",
            actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
            chain_note="生成草稿，等待用户确认")


# ---------------------------------------------------------------------------
# 提案协商员
# ---------------------------------------------------------------------------

class ProposalCollabAgent(BaseAgent):
    key = "proposal_collab"
    name = "提案协商员"
    icon = "💡"
    role_desc = "提案提交、公示、投票、执行、反馈"
    audience = "居民"
    human_stop = "执行决定必须负责人批准"
    tools_whitelist = ["db_proposal.submit_proposal", "db_proposal.get_proposals"]

    def process(self, ctx: dict) -> dict:
        from agent.web_agent_service import _exec_proposal
        text = ctx.get("user_input") or ""
        uid = ctx.get("uid"); name = ctx.get("name") or "居民"
        st = self._read(_state_key(uid)) or {}
        draft = self._read(_draft_key(uid, "proposal_draft"))
        if draft is None and st.get("step"):
            draft = {}

        step = st.get("step")
        if step == "ask_public":
            draft["is_public"] = 1 if ("公开" in text or "公" in text) else 0
            st["step"] = "confirm"
        elif step == "confirm":
            if text in ("确认", "确认提交", "提交", "对", "是"):
                r_text, status, pid = _exec_proposal(uid, name, draft)
                self.bb.unlock(_draft_key(uid, "proposal_draft"))
                self._write(_draft_key(uid, "proposal_draft"), None, lock=False)
                st.clear()
                self._write(_state_key(uid), st)
                return self._reply(r_text, status, "提案", related_id=pid,
                                   chain_note="用户确认，提案已提交")
            st.clear()
            self._write(_state_key(uid), st)
            return self._reply("已取消，没有生成提案。", "已取消", "提案", chain_note="用户取消")

        if draft is None:
            draft = {"desc": text}
            st["step"] = "ask_public"
        else:
            st["step"] = st.get("step") or "ask_public"
        st["intent"] = "proposal"

        self._write(_draft_key(uid, "proposal_draft"), draft, lock=False)
        self._write(_state_key(uid), st)
        if st.get("step") == "confirm":
            pub = "公开" if draft.get("is_public") else "私有"
            return self._reply(
                f"请您确认提案信息：\n· 内容：{draft.get('desc', '')[:60]}\n· 公开方式：{pub}",
                "需确认", "提案",
                actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                chain_note="生成提案草稿，等待用户确认")
        return self._reply("您想公开还是私有？（公开会进入公示投票）", "追问", "提案",
                           actions=[{"type": "buttons", "options": ["公开", "私有"]}],
                           chain_note="追问公开/私有")


# ---------------------------------------------------------------------------
# 政策专员（无引用不回答）
# ---------------------------------------------------------------------------

class PolicyExpertAgent(BaseAgent):
    key = "policy_expert"
    name = "政策专员"
    icon = "📖"
    role_desc = "政策问答，强制引用知识库，无引用不回答"
    audience = "居民/老人"
    human_stop = "无引用不回答，转人工"
    tools_whitelist = ["db_policy.ask_question", "db_policy.get_knowledge_list"]

    def process(self, ctx: dict) -> dict:
        from data.db_policy import ask_question
        text = ctx.get("user_input") or ""
        uid = ctx.get("uid")
        r = ask_question(uid, text, source="Agent")
        if r.get("matched"):
            # 强制引用：附带知识条目标题（spec：无引用不回答）
            title = (r.get("knowledge") or {}).get("title", "")
            answer = r.get("auto_answer", "")
            ref = f"\n\n📎 参考：《{title}》" if title else ""
            return self._reply(f"✅ 已为您找到答案：\n{answer}{ref}", "成功", "政策问答",
                               related_id=r.get("question_id"),
                               actions=[{"type": "buttons", "options": ["有帮助", "无帮助"]}],
                               chain_note="命中知识库，附带引用")
        return self._reply(f"暂未找到答案。{r.get('manual_text', '')}", "needs_human", "政策问答",
                           related_id=r.get("question_id"),
                           actions=[{"type": "confirm_transfer", "label": "转人工咨询",
                                     "related_id": r.get("question_id")}],
                           chain_note="未命中知识库：转人工（无引用不回答）")


# ---------------------------------------------------------------------------
# 健康顾问（不诊断，仅给建议）
# ---------------------------------------------------------------------------

class HealthAdvisorAgent(BaseAgent):
    key = "health_advisor"
    name = "健康顾问"
    icon = "🏥"
    role_desc = "健康咨询、就医指引、疾病预防提醒（不诊断，仅给建议）"
    audience = "居民"
    human_stop = "不诊断，仅给建议；紧急症状提示就医"
    tools_whitelist = ["db_health_content.get_published_contents", "紧急求助引导"]

    def process(self, ctx: dict) -> dict:
        text = ctx.get("user_input") or ""
        # 身体不适 → 提示联系社区/家属 + 紧急求助（不诊断）
        if any(k in text for k in ("不舒服", "难受", "头晕", "头疼", "胸闷", "心慌", "没力气")):
            # 疑似紧急症状 → 主动协商：handoff 接待员转人工
            urgent_symptom = any(k in text for k in ("胸痛", "呼吸困难", "意识不清", "大出血", "抽搐"))
            if urgent_symptom:
                self._post("receptionist", "handoff", {
                    "event": "urgent_symptom", "reason": "疑似紧急症状，需人工确认",
                    "suggestion": "建议立即就医或拨打 120",
                })
                return self._reply(
                    "您描述的疑似紧急症状需要专业人士确认。社区顾问不做诊断，请及时就医，必要时拨打 120。已为您转人工跟进。",
                    "needs_human", "健康顾问",
                    actions=[{"type": "buttons", "options": ["拨打 120", "联系社区", "紧急求助"]},
                             {"type": "navigate", "to": "/resident/health", "label": "去健康防护"}],
                    chain_note="疑似紧急症状：转人工（停机点）")
            return self._reply(
                "您感觉不舒服吗？请不要着急。社区顾问不做诊断，如果症状持续或加重，请及时就医。"
                "需要的话，可以帮您联系社区或家属，也可以长按红色紧急求助按钮。",
                "成功", "健康顾问",
                actions=[{"type": "navigate", "to": "/elderly/home", "label": "紧急求助（长按3秒）"},
                         {"type": "buttons", "options": ["联系社区", "查天气"]}],
                chain_note="身体不适：不做诊断，提示就医与求助")
        # 健康知识/疾病预防 → 返回已发布内容
        try:
            from data.db_health_content import get_published_contents
            rows = get_published_contents(limit=3)
            if rows:
                lines = [f"· {r.get('title', '')}" for r in rows]
                return self._reply("为您推荐最近的健康内容：\n" + "\n".join(lines), "成功", "健康顾问",
                                   actions=[{"type": "navigate", "to": "/resident/health", "label": "去健康防护"}],
                                   chain_note="推荐已发布健康内容")
        except Exception:
            pass
        return self._reply("健康咨询请到「健康防护」提交，负责人会在 24 小时内回复。", "成功", "健康顾问",
                           actions=[{"type": "navigate", "to": "/resident/health", "label": "去健康防护"}],
                           chain_note="引导到健康咨询表单")

    def process_negotiation(self, msg: dict) -> dict | None:
        """健康顾问处理协商：天气守护员极端天气 → 准备健康提醒文案。"""
        payload = msg.get("payload") or {}
        if payload.get("event") == "extreme_weather":
            return {
                "accepted": True,
                "reply": f"已根据天气预警准备健康提醒：{payload.get('suggestion', '')}",
            }
        return None


# ---------------------------------------------------------------------------
# 通知管理员（紧急通知需负责人人工审核，Agent 不直接发布紧急通知）
# ---------------------------------------------------------------------------

class NotificationManagerAgent(BaseAgent):
    key = "notification_manager"
    name = "通知管理员"
    icon = "📢"
    role_desc = "通知创建、定时、发布；紧急通知需负责人审核"
    audience = "负责人"
    human_stop = "紧急通知二次确认；Agent 不直接发布紧急通知"
    tools_whitelist = ["db_notice.get_notices_with_stats", "通知发布引导"]

    def process(self, ctx: dict) -> dict:
        text = ctx.get("user_input") or ""
        # 紧急相关：Agent 不能直接发布，引导负责人手动
        if any(k in text for k in ("紧急", "预警", "停水", "停电")):
            return self._reply(
                "紧急通知需要负责人手动发布（含二次确认与置顶）。已为您打开通知管理页。",
                "成功", "通知管理员",
                actions=[{"type": "navigate", "to": "/grid/notices", "label": "去通知管理"}],
                chain_note="停机点：紧急通知必须负责人手动发布")
        # 普通通知：引导到发布页
        return self._reply("通知发布请到「通知管理」创建（支持定时与附件）。", "成功", "通知管理员",
                           actions=[{"type": "navigate", "to": "/grid/notices", "label": "去通知管理"}],
                           chain_note="引导到通知管理")
