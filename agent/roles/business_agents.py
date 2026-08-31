# agent/roles/business_agents.py
"""5 个业务角色 Agent（薄壳）：报修调度员 / 提案协商员 / 政策专员 / 健康顾问 / 通知管理员。
process() 复用现有数据层与规则引擎（web_agent_service / data/*），不复制业务逻辑。
会话状态（追问/草稿）存黑板：user:{uid}:state / user:{uid}:{draft_key}。
"""
from agent import web_agent as A
from agent.roles.base import BaseAgent


def _llm_polish_health_suggestion(tags: str, base: str) -> str:
    """可选 LLM 润色健康协商建议（P1-3）。

    仅在 LLM_NEGOTIATION=1 且配置了 key 时走真实 DeepSeek（WS2：统一走 agent.llm_client）；
    产出强制过 Verifier（健康规则集），BLOCK/WARN 一律回退规则文案（幻觉兜底）。
    任何异常/无 key/熔断一律回退规则文案。
    """
    import os

    if os.getenv("LLM_NEGOTIATION", "0") != "1":
        return base
    from config import DEEPSEEK_API_KEY
    if not DEEPSEEK_API_KEY:
        return base
    from agent.llm_client import chat
    r = chat(
        [{"role": "system", "content":
          "你是社区健康顾问。根据天气预警标签，用一句不超过50字的口语化中文给出老年人"
          "防护建议。不做诊断、不推荐药物、紧急情况提示就医。"},
         {"role": "user", "content": f"天气预警：{tags}。基础建议：{base}"}],
        module="健康润色", purpose=f"{tags}/{base[:40]}",
        temperature=0.3, max_tokens=120, timeout=8,
    )
    if not r["ok"]:
        return base
    text = r["text"].strip()
    # 幻觉防线：健康规则集校验，不过则回退规则文案
    from agent.verifier import Verifier
    v = Verifier().verify({"reply": text}, biz_type="health")
    if v["verdict"] == "pass":
        return text
    return base


def _state_key(uid):
    return f"user:{uid}:state"


def _draft_key(uid, name):
    return f"user:{uid}:{name}"


# 报修地点归一类：区分「室内(家里)」vs「室外(公共区域)」。
# 判据覆盖常见表述；无明确地点词时按上下文默认（默认室内，更贴合老人报修"家里"场景）。
# 注意：室外词优先，避免"我家楼下"这类含"家"又含室外词的场景判错。
_INDOOR_WORDS = ("内", "家", "屋", "卧室", "客厅", "厨房", "卫生间", "厕所", "浴室", "阳台")
_OUTDOOR_WORDS = ("公共", "楼道", "走廊", "楼梯", "楼下", "广场", "过道", "门口", "外面", "室外", "花园", "车库", "电梯")


def _classify_repair_location(text: str) -> str:
    """根据用户描述判断报修地点是室内还是室外。"""
    t = text or ""
    # 室外词优先命中（如"我家楼下广场"含"家"也含"广场"，应判室外）
    if any(w in t for w in _OUTDOOR_WORDS):
        return "室外"
    if any(w in t for w in _INDOOR_WORDS):
        return "室内"
    return "室内"  # 默认室内（老人常直接说"家里漏水"）


def _classify_repair_urgency(text: str, state_urgent: bool | None) -> str:
    """判断紧急程度。显式写紧急/急（排除"不着急/别急"否定）→ 紧急；否则按上下文标记兜底。"""
    t = text or ""
    # 否定词优先：不着急/别急/不用急 → 一般
    if any(k in t for k in ("不着急", "别急", "不用急", "不急", "缓缓", "有空再说", "不紧")):
        return "一般"
    if any(k in t for k in ("紧急", "急", "很急", "马上", "立刻", "尽快", "快点")):
        return "紧急"
    return "紧急" if state_urgent else "一般"


# 安全隐患词 → 隐患类型（P2 扩展2：报修中发现生命财产风险，协商通知管理员升级）。
# 与 web_agent 意图词一致；只用复合/明确风险词，避免"燃气缴费/触电急救"等误路由。
_HAZARD_MAP = [
    (("燃气泄漏", "煤气泄漏", "燃气味", "煤气味", "漏气"), "燃气泄漏"),
    (("漏电", "冒火花"), "漏电隐患"),
    (("起火", "着火", "冒烟", "烧焦味", "焦味", "浓烟"), "火灾风险"),
]


def _detect_hazard(text: str) -> str:
    """识别报修描述中的安全隐患类型，无则返回空串。"""
    t = text or ""
    for words, label in _HAZARD_MAP:
        if any(w in t for w in words):
            return label
    return ""


# 健康词表（从 HealthAdvisorAgent.process 内联提取，供协商共用；行为不变）
_DISCOMFORT_WORDS = ("不舒服", "难受", "头晕", "头疼", "胸闷", "心慌", "没力气",
                     "胸痛", "呼吸困难", "意识不清", "大出血", "抽搐")
_URGENT_SYMPTOM_WORDS = ("胸痛", "呼吸困难", "意识不清", "大出血", "抽搐")
# 对健康有影响的预警类型（扩展1：健康顾问反向查询天气守护员时过滤用）
_WEATHER_HEALTH_TYPES = ("高温", "寒潮", "暴雨", "台风", "大雾", "雷电", "重污染")


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
            draft["type"] = _classify_repair_location(text)
            st["step"] = "ask_urgency" if draft.get("urgency") is None else "confirm"
        elif step == "ask_urgency":
            draft["urgency"] = _classify_repair_urgency(text, st.get("urgent"))
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
            # P2 扩展2：安全隐患 → 紧急直确认 + 安全引导 + 协商通知管理员（跳过"家里/公共区域"追问）
            hazard = _detect_hazard(text)
            if hazard:
                draft = {"desc": text, "type": _classify_repair_location(text), "urgency": "紧急"}
                st["step"] = "confirm"
                st["intent"] = "repair"
                self._write(_draft_key(uid, "work_order_draft"), draft, lock=False)
                self._write(_state_key(uid), st)
                self._post("notification_manager", "notify", {
                    "event": "safety_hazard", "hazard": hazard,
                    "location": draft["type"], "desc": text[:60],
                })
                return self._reply(
                    f"🚨 这属于{hazard}，请先确保安全：远离现场、不要开关电器、"
                    f"{'开窗通风、' if hazard == '燃气泄漏' else ''}到安全位置，必要时拨打 119。\n\n"
                    f"已按「紧急」为您准备好工单，确认后立即通知负责人处理：\n"
                    f"· 问题：{text[:50]}\n· 位置：{draft['type']}\n· 紧急程度：紧急",
                    "需确认", "报修",
                    actions=[{"type": "buttons", "options": ["确认提交", "取消"]}],
                    chain_note=f"安全隐患（{hazard}）：紧急直确认 + 主动协商通知管理员")
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
        # 紧急症状（胸痛/呼吸困难等）独立触发，确保即使不在普通不适词表也转人工（P1-D3-01 评测暴露）
        if any(k in text for k in _DISCOMFORT_WORDS):
            # 疑似紧急症状 → 主动协商：handoff 接待员转人工
            urgent_symptom = any(k in text for k in _URGENT_SYMPTOM_WORDS)
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
            # P2 扩展1：非紧急不适 + 生效天气预警 → 主动查询天气守护员（健康→天气反向协商）
            try:
                from data.db_weather import get_active_alerts
                alerts = [a for a in get_active_alerts()
                          if a.get("alert_type") in _WEATHER_HEALTH_TYPES]
            except Exception:
                alerts = []
            if alerts:
                tags = "、".join(f"{a.get('alert_type')}{a.get('level')}" for a in alerts[:2])
                symptom = next((k for k in _DISCOMFORT_WORDS if k in text), "")
                self._post("weather_guardian", "task_request", {
                    "event": "health_weather_risk_query",
                    "symptom": symptom, "tags": tags, "question": text[:60],
                })
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
        """健康顾问处理协商（真协商 P2-A2-02）：天气守护员极端天气 → 健康风险评估。"""
        payload = msg.get("payload") or {}
        if payload.get("event") == "extreme_weather":
            tags = payload.get("tags", "")
            # 极端天气对老人有风险 → 建议升级通知（触发天气→通知管理员链路）
            escalate = any(k in tags for k in ("高温", "寒潮", "台风", "暴雨"))
            base = "提醒老人注意防暑/保暖，减少外出，备好常用药" if escalate else (payload.get("suggestion") or "")
            # P1-3：可选 LLM 润色建议文案（产出过 Verifier 健康规则集，BLOCK 回退规则文案）。
            # 注意：escalate 用原始确定性条件判定（tags 高危词），不依赖 LLM 措辞，保证守护员升级逻辑稳定。
            suggestion = _llm_polish_health_suggestion(tags, base)
            if escalate:
                return {
                    "accepted": True,
                    "reply": f"已根据天气预警准备健康提醒：{suggestion}",
                    "suggestion": suggestion,
                    "event": "extreme_weather",
                    "tags": tags,
                    "escalate": True,
                }
            return {"accepted": True, "reply": f"已根据天气预警准备健康提醒：{suggestion}",
                    "suggestion": suggestion, "event": "extreme_weather",
                    "tags": tags, "escalate": False}
        # P2 扩展1：天气守护员的风险评估回执（健康顾问发起反向查询的响应）
        if msg.get("type") == "task_response" and payload.get("event") == "health_weather_risk_confirmed":
            # WS5：真实分歧 → 仲裁 → 改写最终文案（不只留痕，进入用户可见回复）
            # 天气守护员评估"可正常活动/无直接风险"，但健康侧看到高危症状说明 → 应更保守。
            # 触发条件：天气评估低风险 + 高危症状（头晕/胸闷/心慌），或安全类症状（胸痛/呼吸困难）。
            symptom = payload.get("symptom") or ""
            low_risk = payload.get("risk_level") in ("none", "")
            high_risk_symptom = symptom in ("头晕", "胸闷", "心慌")
            safety_symptom = any(w in symptom for w in ("胸痛", "呼吸困难", "抽搐", "大出血"))
            if (low_risk and high_risk_symptom) or safety_symptom:
                try:
                    from agent.arbiter import Arbiter
                    arb = Arbiter().arbitrate({
                        "professional_domain": True,          # 专业判断以健康顾问为准
                        "safety_risk": bool(safety_symptom),  # 涉人身安全 → safety_first(human)
                        "agent": self.key,
                        "conflict_summary": (
                            "天气评估可正常活动/无直接风险，但健康侧判断症状需保守处理"
                            if not safety_symptom else
                            "天气评估无直接风险，但症状疑为紧急，需转人工确认"),
                    })
                    self._write("last_arbitration", arb)
                    decision = arb.get("decision")
                    # 仲裁结果进入用户可见协作提示（不再丢弃）
                    if decision == "human":
                        collab = ("【仲裁·转人工】该症状可能与天气无关且建议进一步确认，"
                                  "已升级人工/家属跟进，请及时就医。")
                        need_human = True
                    else:  # professional
                        collab = ("【仲裁·专业优先】尽管天气评估可正常活动，结合您的症状，"
                                  "健康侧建议以保守稳妥为主：减少外出、注意休息、早睡早起，"
                                  "症状持续请及时就医。")
                        need_human = False
                    return {"accepted": True,
                            "reply": collab, "need_human": need_human,
                            "arbitration": decision}
                except Exception:
                    pass
            return {"accepted": True}  # 无 reply：不重复合并文本，仅留执行链节点
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

    def process_negotiation(self, msg: dict) -> dict | None:
        """通知管理员处理协商（真协商 P2-A2-02）：天气升级的预警通知草稿。

        停机点：紧急通知必须负责人手动发布——Agent 只生成草稿引导，不自动发布。
        """
        payload = msg.get("payload") or {}
        if payload.get("event") == "extreme_weather":
            return {
                "accepted": True,
                "reply": "已生成天气预警通知草稿（含老人防护提示），需负责人确认后发布",
                "draft_ready": True,
            }
        # P2 扩展2：报修调度员上报安全隐患 → 生成紧急预警通知草稿（停机点：仍需负责人确认发布）
        if payload.get("event") == "safety_hazard":
            hazard = payload.get("hazard", "安全隐患")
            return {
                "accepted": True,
                "reply": f"【通知管理员】已生成「{hazard}」紧急预警通知草稿"
                         f"（提醒相关楼栋居民避险），待负责人确认后立即发布",
                "draft_ready": True, "hazard": hazard,
            }
        return None
