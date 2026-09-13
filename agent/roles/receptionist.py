# agent/roles/receptionist.py
"""社区接待员：统一入口。意图识别、纠错确认、情绪安抚、礼貌回复、帮助/自我介绍、路由。
"""
from agent import web_agent as A
from agent import tone as A_intent_tone
from agent.roles.base import BaseAgent

# 中文意图 → 路由 key（与 roles/config.py ROUTE_MAP 对应）
INTENT_KEY_MAP = {
    "报修": "repair",
    "撤回引导": "withdraw",  # 独立处理：不建报修草稿
    "提案": "proposal",
    "政策问答": "policy",
    "通知查询": "notification",
    "社区动态": "community_pulse",   # 修复：自然问句「今天社区有什么新鲜事」原先回"我没太理解"
    "天气查询": "weather",
    "身体不适": "health",
    "联系社区": "community",
    "待办提醒": "grid", "导出数据": "grid", "统计查询": "grid",
    "搜索资料": "grid", "页面跳转": "grid",
}

# 「报修查询」判定词（查询类）与「报修名词」：两者同时命中才算"问数字"，而不是"报故障"
_QUERY_MARKERS = ("统计", "多少", "几条", "数量", "总数", "汇总", "列表", "有哪些",
                  "情况", "记录", "进度", "都报了什么", "报过")
_REPAIR_NOUNS = ("报修", "工单", "维修", "我的报修")


def _looks_like_repair_query(text: str) -> bool:
    """是不是在**查**报修情况（而不是报一个新的故障）。

    纯规则、无副作用：只对「报修/工单」这类名词 + 查询词同时出现时判定，
    真实报修描述（"我家水管漏水了"）不含查询词，不会误判。
    """
    return any(m in text for m in _QUERY_MARKERS) and any(n in text for n in _REPAIR_NOUNS)


class ReceptionistAgent(BaseAgent):
    key = "receptionist"
    name = "社区接待员"
    icon = "👤"
    role_desc = "统一入口：意图识别、追问引导、情绪安抚、纠错确认、路由分发"
    audience = "居民/老人"
    human_stop = "意图不明确时转人工"
    tools_whitelist = ["意图识别", "纠错", "情绪识别", "路由"]

    # ---- 快捷回复 ----

    def _polite(self):
        return "不客气，有需要随时找我。"

    def _intro(self):
        return "我是社区小助手，可以帮您报修、查政策、看天气、看通知，也可以帮您联系社区。"

    def _help(self, role):
        entries = "、".join(A.quick_entries(role))
        return f"我可以帮您：{entries}。直接对我说就行，或点击下方快捷按钮。"

    # ---- 我的报修概览（查询类，不建草稿） ----

    def _my_issue_summary(self, ctx: dict) -> dict:
        """用**真实数据**回答「报修统计有多少」这类查询。

        只读自己名下的工单（按 reporter_id / author 过滤），不建草稿、不进状态机；
        取数失败时降级为「打开我的报修列表」引导，绝不让用户卡在原地。
        """
        uid = ctx.get("uid")
        try:
            from data.db_repair import get_issues
            rows = get_issues(reporter_id=uid, limit=200) if uid else []
            if not rows:
                rows = []
            total = len(rows)
            doing = sum(1 for r in rows if r.get("status") in ("待审核", "已审核待派单", "已派单", "处理中", "待居民反馈"))
            done = sum(1 for r in rows if r.get("status") == "处理结束")
            recent = "；".join(f"#{r.get('id')} {r.get('title', '')[:12]}（{r.get('status')}）"
                              for r in rows[:3])
            reply = f"您名下共有 {total} 条报修：处理中 {doing} 条、已办结 {done} 条。"
            if recent:
                reply += f"\n最近：{recent}"
        except Exception:  # noqa: BLE001 — 查询失败不阻塞，降级引导
            reply = "报修统计暂时查不到，已为您打开我的报修列表。"
        # 留痕到黑板（供执行链/审计查看），与其它接待员分支一致
        self._write("intent_note", "报修查询：直答本人报修概览，未建草稿")
        return self._reply(reply, intent="报修查询",
                           actions=[{"type": "navigate", "to": "/resident/work-orders",
                                     "label": "查看我的报修"}],
                           chain_note="查询类输入 → 直答概览，不走报修状态机")

    def process(self, ctx: dict) -> dict:
        text = (ctx.get("user_input") or "").strip()[:200]
        role = ctx.get("role") or "resident"

        # NLU 预处理（P1-C1-01）：方言归一化 → 指代消解（最近实体）→ 否定取肯定目标
        recent_entity = (ctx["state"].get("user_context") or {}).get("recent_entity")
        pre = A.nlu_preprocess(text, recent_entity)
        if pre != text:
            text = pre
            ctx["user_input"] = text

        # 礼貌 / 自我介绍 / 使用帮助
        if A.detect_polite(text):
            return self._reply(self._polite(), intent="礼貌回复", chain_note="识别到礼貌用语")
        if "你是谁" in text or "你叫什么" in text:
            return self._reply(self._intro(), intent="自我介绍", chain_note="自我介绍")
        if A.detect_intent(text, role) == "使用帮助":
            return self._reply(self._help(role), intent="使用帮助", chain_note="展示功能介绍")

        # 纠错确认（先展示确认再继续；否认保留原文）
        pc = ctx["state"].get("pending_correct")
        if pc:
            ctx["state"].pop("pending_correct")
            text = pc["corrected"] if text in ("对", "确认", "是的", "确定", "对，提交") else pc["original"]
            ctx["user_input"] = text

        # 用户主动要求转人工（T6：转人工/人工客服/找真人）
        if any(k in text for k in ("转人工", "人工客服", "找真人", "人工处理", "叫工作人员", "真人帮我")):
            ctx["state"]["user_requested_human"] = True
            return self._reply("", status="routed", intent="handoff", done=False,
                               chain_note="用户主动要求转人工")

        # Prompt 注入防护（P2-06 第一层：输入过滤）—— 拦截 + 留痕
        from agent.prompt_guard import detect_injection, safe_reply
        inj = detect_injection(text)
        if inj:
            ctx["state"]["injection_blocked"] = inj
            try:
                from data import db_agent
                db_agent.log_agent(ctx.get("uid"), ctx.get("role") or "resident",
                                   text, "注入拦截", routed=f"注入-{inj}", status="拦截",
                                   error=f"检测到注入类别「{inj}」")
            except Exception:
                pass
            return self._reply(safe_reply(), intent="注入拦截", chain_note=f"拦截注入（{inj}）")

        corrected = A.correct_text(text)
        if corrected and corrected != text:
            ctx["state"]["pending_correct"] = {"original": text, "corrected": corrected}
            return self._reply(f"您说的是「{corrected}」吗？", status="需确认", intent="纠正确认",
                               actions=[{"type": "buttons", "options": ["对", "不是"]}],
                               chain_note="检测到错别字，先请用户确认")

        # 紧急语义 / 情绪
        ctx["state"]["urgent"] = A.detect_emergency(text)
        emotion = A.detect_emotion(text)

        # 意图识别（多意图取第一个主要意图；紧急语义默认联想报修）
        intent = A.detect_intent(text, role)

        # 查询 vs 报修 消歧（第八轮终审衍生 BUG）：
        # legacy 人设路由早就写明「分析类关键词压过报修类——"统计报修数量"是查询，不是报修」，
        # 但主线原先缺这条规则：「报修统计有多少」被判成**新报修**，追问"是您家里还是公共区域"，
        # 用户问数字却被要求描述位置。这里补上：命中「报修/工单 + 统计类词」→ 直接答他自己的报修概览。
        if intent == "报修" and _looks_like_repair_query(text):
            return self._my_issue_summary(ctx)

        if not intent:
            if ctx["state"].get("urgent"):
                intent = "repair"
            elif A.detect_go_out(text):
                return self._reply("需要帮您查天气吗？", intent="出行联想",
                                   actions=[{"type": "buttons", "options": ["查今天天气", "不用了"]}],
                                   chain_note="出行场景联想")
            elif emotion:
                return self._reply("我理解您的着急，马上为您处理。请告诉我具体的问题，比如是漏水、灯坏还是其他。",
                                   intent="情绪安抚",
                                   actions=[{"type": "buttons", "options": ["报修", "提案", "政策问答", "查天气"]}],
                                   chain_note="先安抚再引导")
            else:
                # WS4：规则全未命中才花一次 LLM（默认关，RECEPTION_LLM_FALLBACK=1 启用）
                from agent import intent_llm as A_llm
                llm_intent = A_llm.llm_intent(text, role)
                if llm_intent:
                    intent = llm_intent
                    ctx["state"]["intent_via"] = "llm"
                else:
                    return self._reply(A.unknown_reply(role), intent="未知意图",
                                       actions=[{"type": "buttons", "options": A.quick_entries(role)}],
                                       chain_note="未识别意图，展示快捷入口")

        # M2：情绪先安抚 —— 命中则把安抚句种到 state，由 orchestrator._finish 统一前置（会话级一次）
        em_tag, em_comfort = A_intent_tone.detect_emotion(text)
        if em_comfort:
            ctx["state"]["emotion"] = em_tag
            ctx["state"]["emotion_comfort"] = em_comfort
            self._write("emotion", em_tag)  # 黑板留痕（执行链/审计可见）

        # 接待员落意图到黑板，交 Orchestrator 路由
        self._write("user_input", text)
        intent_key = INTENT_KEY_MAP.get(intent, "receptionist")
        self._write("user_intent", intent_key)
        # 会话最近实体（P1-C1-01 指代消解用）：报修/提案对象，如「水管」「路灯」
        entity = A.extract_recent_entity(text)
        prev_ctx = ctx["state"].get("user_context") or {}
        prev_ctx.update({
            "role": role, "uid": ctx.get("uid"), "name": ctx.get("name"),
            "text": text, "intent_cn": intent,
        })
        if entity:
            prev_ctx["recent_entity"] = entity
        self._write("user_context", prev_ctx)
        return self._reply("", status="routed", intent=intent_key, done=False,
                           chain_note=f"识别为「{intent}」，路由中")
