# agent/orchestrator.py
"""多 Agent 编排器（Orchestrator）：
接待员 → 意图路由 → 业务/自动角色 Agent → 合规审计员 → 返回 + 执行链。

- 黑板：共享上下文（user_input/intent/context/draft/state）
- 消息协议：角色间 post_message（task_request/task_response/notify/error/handoff）
- 异常：Agent 超时重试一次、黑板锁冲突提示、用户取消清理、审计拦截
"""
import logging
import re
import time
from datetime import datetime

from agent.blackboard import Blackboard, BlackboardLockError
from agent.roles import create_agents, role_list
from utils.tenant import tenant_of_user

_log = logging.getLogger(__name__)

_AGENT_TIMEOUT_S = 3.0
_RETRY_ONCE = True


def _state_key(uid):
    return f"user:{uid}:state"


def _draft_keys(uid):
    return [f"user:{uid}:work_order_draft", f"user:{uid}:proposal_draft"]


def _draft_type_of(key: str) -> str:
    """user:{uid}:work_order_draft → work_order_draft。"""
    return key.rsplit(":", 1)[-1] if ":" in key else key


class Orchestrator:
    """多 Agent 编排器（每用户会话一个实例，黑板带 session_id）。"""

    def __init__(self, session_id: str | None = None):
        self.bb = Blackboard(session_id=session_id)
        self.agents = create_agents(self.bb)
        from agent.arbiter import Arbiter
        from agent.verifier import Verifier
        self.arbiter = Arbiter()
        self.verifier = Verifier()
        self.execution_chain: list[dict] = []
        self._persisted = False  # 会话落库（v31）
        self.last_active = time.time()  # LRU 淘汰用（P1-1）

    # ---- 执行链 ----

    def _log(self, agent_key: str, action: str, note: str = "", detail: dict | None = None):
        meta = {
            "receptionist": ("社区接待员", "👤"), "repair_dispatch": ("报修调度员", "🔧"),
            "proposal_collab": ("提案协商员", "💡"), "health_advisor": ("健康顾问", "🏥"),
            "policy_expert": ("政策专员", "📖"), "notification_manager": ("通知管理员", "📢"),
            "weather_guardian": ("天气守护员", "🌤️"), "grid_assistant": ("网格员工作助手", "🛠️"),
            "compliance_auditor": ("合规审计员", "🛡️"),
            "negotiation": ("主动协商", "⚡"), "arbiter": ("冲突仲裁", "⚖️"),
        }.get(agent_key, (agent_key, "🤖"))
        self.execution_chain.append({
            "agent": agent_key, "name": meta[0], "icon": meta[1],
            "action": action, "note": note, "detail": detail,
            "timestamp": datetime.now().isoformat(),
        })

    # ---- 主入口 ----

    def run(self, role: str, uid: int, name: str, user_input: str,
            elder_uid: int | None = None) -> dict:
        """处理一轮用户消息。返回 {reply, intent, status, actions, related_id, execution_chain, session_id}。"""
        text = (user_input or "").strip()[:200]
        self.last_active = time.time()  # LRU 淘汰用（P1-1）
        # 会话落库：重启后从 agent_sessions 恢复 state（P1-C5-01 修复）
        from data import db_agent
        try:
            persisted = db_agent.load_session(self.bb.session_id)
            if persisted and isinstance(persisted, dict):
                self._persisted = True
        except Exception:
            persisted = None
        st = self.bb.read(_state_key(uid))
        if st is None:
            st = persisted or {}
            self.bb.write(_state_key(uid), st, "orchestrator")
        # 草稿内容落库恢复（P1-A5-02）：从 draft_contents 回填黑板草稿
        try:
            from data.db_draft import load_draft
            for key in _draft_keys(uid):
                d = load_draft(uid, _draft_type_of(key))
                if d and d.get("content"):
                    self.bb.write(key, d["content"], "system_restore")
        except Exception:
            pass
        # 属地（地区识别 WS4）：会话建立时解析一次放进 ctx，天气/政策等工具复用，避免每轮重复查库。
        # 没有属地（调度器自动巡检、无 uid）时留空 → 各工具回落全局默认城市，行为与升级前一致。
        region = None
        try:
            from utils.region import resolve_region
            from data.db_user import get_user_by_id
            region = resolve_region((get_user_by_id(uid) or {}).get("community")) if uid else None
        except Exception as e:  # noqa: BLE001
            # 属地解析失败不能影响对话，但**必须留痕**（静默吞异常会让"属地化没生效"查不出来）
            _log.warning("会话属地解析失败，回落全局默认：%s", e)
            region = None
        ctx = {"role": role, "uid": uid, "name": name, "user_input": text,
               "elder_uid": elder_uid,
               "region": region,
               "state": st}

        # 协商循环计数按用户轮次重置（P2 扩展前置修复：此前跨轮累计，
        # 同一用户连续多轮协商后相关 agent 计数达上限，会误触发"强制转人工"；
        # 循环防护的本职——单轮内防死循环——由 _drain_negotiations 外层 5 次上限 + 单目标 2 轮共同保障。）
        for _k in self.agents:
            try:
                self.bb.write(f"negotiation:{_k}", 0, "orchestrator")
            except Exception:
                pass

        # 取消指令：清理草稿与状态（彻底清空，避免残留 step 导致续接）
        if text in ("算了", "取消", "不要了", "先不弄了"):
            for k in _draft_keys(uid):
                try:
                    self.bb.unlock(k)
                    self.bb.write(k, None, "orchestrator", lock=False)
                    from data.db_draft import delete_draft
                    delete_draft(uid, _draft_type_of(k))
                except Exception:
                    pass
            self.bb.write(_state_key(uid), {}, "orchestrator")
            try:
                from data import db_agent
                db_agent.delete_session(self.bb.session_id)
            except Exception:
                pass
            self._log("receptionist", "取消", "用户取消，清理草稿与会话")
            return self._finish(ctx, "已取消，没有生成草稿。", "已取消", "取消", [], None)

        # 1) 续接：黑板上已有业务会话（追问/草稿确认）→ 直接路由到对应业务 Agent
        st = ctx["state"]
        resumed = self._resume_target(st, text, role)
        if resumed:
            ctx["intent"] = resumed
            ctx["user_input"] = text
            self._log("receptionist", "续接会话", f"继续「{resumed}」流程")
            return self._dispatch(ctx, resumed)

        # 2) 接待员：意图识别 / 纠错确认 / 情绪安抚 / 快捷回复 / 路由
        self._log("receptionist", "接收输入", "识别意图与上下文")
        r = self.agents["receptionist"].process(ctx)
        if r.get("status") == "routed":
            intent = r.get("intent")
            self._log("receptionist", "识别意图", intent)
            return self._dispatch(ctx, intent)
        # 接待员直接返回（纠错确认/礼貌/帮助/情绪/未知/出行）
        if r.get("chain_note"):
            self._log("receptionist", r.get("intent"), r.get("chain_note"))
        return self._finish(ctx, r["reply"], r.get("status", "成功"), r.get("intent", ""),
                            r.get("actions", []), r.get("related_id"))

    # ---- 分发 ----

    # 追问应答词白名单（话题切换检测用）：这些输入视为对当前追问的回答
    _ANSWER_WORDS = {
        "确认", "确认提交", "提交", "对", "是", "确定", "对，提交", "不是", "算了", "取消",
        "家里", "公共区域", "室内", "室外", "紧急", "一般", "公开", "私有", "不报了", "不要了",
    }

    def _resume_target(self, st: dict, text: str, role: str = "resident") -> str | None:
        """根据黑板 state 判断是否续接某业务 Agent（追问/草稿确认/导出确认）。

        话题切换（C5）：续接前若用户输入非追问应答词且命中**其他新意图**，
        则视为中途改话题——返回 None（由 receptionist 重新识别新意图，原流程草稿保留）。
        """
        if not st:
            return None
        step = st.get("step")
        intent = st.get("intent")
        target = None
        if st.get("pending_export"):
            target = "grid_assistant"
        elif step == "ask_type" or step == "ask_urgency" or (step == "confirm" and intent == "repair"):
            target = "repair_dispatch"
        elif step == "ask_public" or (step == "confirm" and intent == "proposal"):
            target = "proposal_collab"
        if not target:
            return None
        # 话题切换检测：非应答词且识别到其他意图 → 中断当前流程
        if text not in self._ANSWER_WORDS and step:
            # 修复（第八轮终审衍生 BUG）：**新的完整问句**也算改话题。
            # 反例：「有什么热门提案吗」「今天社区有什么新鲜事」这类问句既不是应答词、
            # 又恰好没命中其他业务意图（detect_intent 返回 None）→ 原先会**续接上一次的报修流程**，
            # 用户明明在问社区动态，却收到"请确认报修信息：…"（引用了旧草稿），演示时非常刺眼。
            if self._looks_like_new_question(text):
                self._log("receptionist", "话题切换",
                          "检测到新的完整问句，中断原流程并重新识别意图")
                return None
            try:
                from agent import web_agent as A
                from agent.roles.receptionist import INTENT_KEY_MAP
                # NLU 预处理与接待员同口径（P1-C1-01）：方言/指代/否定后再识别
                recent_entity = (st.get("user_context") or {}).get("recent_entity")
                nlu_text = A.nlu_preprocess(text, recent_entity)
                new_cn = A.detect_intent(nlu_text, role)
                if new_cn:
                    new_key = INTENT_KEY_MAP.get(new_cn)
                    # 其他业务意图（非当前续接目标）→ 视为话题切换
                    if new_key and new_key != target and new_key not in ("community", "withdraw"):
                        return None
            except Exception:
                pass
        return target

    # 新问句识别（话题切换用）：长度 + 疑问特征双重条件，避免把「楼道」这类
    # 简短回答误判成改话题；5 字的「怎么修？」也不会命中（长度 <8）。
    _NEW_QUESTION_RE = re.compile(r"[?？]|吗|呢|什么|哪些|哪个|怎么|如何|多少|有没有|是不是|能不能|可以吗")

    def _looks_like_new_question(self, text: str) -> bool:
        return len(text) >= 8 and bool(self._NEW_QUESTION_RE.search(text))

    def _dispatch(self, ctx: dict, intent: str) -> dict:
        """按意图路由到业务/自动角色 Agent，末尾过合规审计。"""
        from agent.roles.config import ROUTE_MAP
        # 用户主动转人工（T6）→ 生成人工处理包（上下文同步）
        if intent == "handoff":
            self._log("receptionist", "转人工", "用户主动要求")
            result = self._transfer_to_human(
                ctx, {"reply": "", "intent": "handoff", "status": "needs_human"},
                "用户主动要求转人工（T6）")
            return self._finish(ctx, "已为您转接工作人员，他们会直接联系您，不用重新说一遍。",
                                result["status"], "handoff",
                                [{"type": "navigate", "to": "/resident/messages", "label": "查看消息"}],
                                result.get("handoff_id"))
        target = ROUTE_MAP.get(intent)
        if target is None and intent in self.agents:
            target = intent  # 续接会话时 intent 即角色 key
        # 社区动态快照（修复：问「今天社区有什么新鲜事」原先落到"未知意图"，答"我没太理解"）
        if intent == "community_pulse":
            return self._community_pulse(ctx)
        # 通知查询 → 直答**用户自己**能看到的通知列表（不进负责人通知管理）
        # 修复（第八轮终审衍生 BUG）：原先只对老年端特判，导致**居民**问「最近有什么通知」
        # 被路由到 notification_manager，回复是"通知发布请到「通知管理」创建"——那是负责人视角，
        # 居民看了一头雾水。现在居民/老年都走各自的可见通知列表。
        if intent == "notification" and ctx.get("role") in ("elderly", "resident"):
            return self._community_or_withdraw(ctx, "notification")
        if not target:
            # 联系社区 / 撤回引导 等接待员可直答的意图
            if intent in ("community", "withdraw"):
                return self._community_or_withdraw(ctx, intent)
            self._log("receptionist", "无法路由", intent)
            from agent import web_agent as A
            return self._finish(ctx, A.unknown_reply(ctx.get("role") or "resident"),
                                "成功", intent,
                                [{"type": "buttons", "options": A.quick_entries(ctx.get("role") or "resident")}], None)

        agent = self.agents[target]
        ctx["intent"] = intent
        self._log(target, "处理任务", f"接收意图「{intent}」")
        try:
            result = self._call_agent(agent, ctx)
        except BlackboardLockError as e:
            self._log("compliance_auditor", "锁冲突", str(e))
            return self._finish(ctx, "草稿正在处理中，请稍后重试。", "失败", intent, [], None)
        except Exception as e:  # noqa: BLE001
            _log.exception("Agent %s 执行异常", target)
            self._log("compliance_auditor", "异常", str(e)[:80])
            return self._finish(ctx, "服务暂时不可用，请稍后再试。", "失败", intent, [], None)

        # 消息协议：目标 Agent 完成 → notify 接待员
        self.bb.post_message("receptionist", {
            "from": target, "to": "receptionist", "type": "task_response",
            "payload": {"intent": intent, "status": result.get("status")},
        })

        # 统一校验器（LLM 幻觉防线）：业务输出先过 Verifier
        self._log("verifier", "校验", "业务规则检查")
        verify = self.verifier.verify(result, biz_type=target)
        self.bb.write("verify_result", verify, "verifier")
        if verify["verdict"] == "block":
            self._log("verifier", "拦截", verify["violations"][0]["reason"] if verify["violations"] else "block")
            # 重试一次，仍 BLOCK → 仲裁/转人工
            retry = self._call_agent(agent, ctx)
            verify2 = self.verifier.verify(retry, biz_type=target)
            if verify2["verdict"] == "block":
                conflict = {"verify_failed": True, "agent": target,
                            "safety_risk": any("紧急" in v["reason"] or "症状" in v["reason"]
                                               for v in verify2["violations"])}
                arb = self.arbiter.arbitrate(conflict)
                self._log("arbiter", "仲裁", f"校验拦截→{arb['decision']}：{arb['explanation']}")
                if arb["decision"] == "human":
                    result = self._transfer_to_human(ctx, retry, "校验拦截：" + arb["explanation"])
                    return self._finish(ctx, result["reply"], result["status"], target,
                                        [{"type": "navigate", "to": "/resident/messages", "label": "查看消息"}],
                                        result.get("handoff_id"))
                result = self._safe_fallback(result, "该内容需人工审核，请稍候。")
                result["status"] = "拦截"
            else:
                self._log("verifier", "重试通过", "重试后校验通过")
                result = retry
        elif verify["verdict"] == "warn":
            self._log("verifier", "降级", ";".join(w["reason"] for w in verify["warnings"]))
            # 降级为安全回答（保留核心信息，附加安全提示）
            result = dict(result)
            result["reply"] = (result.get("reply", "") +
                               "\n\n已为您提供安全建议，如需详细内容请咨询社区工作人员。").strip()
        else:
            self._log("verifier", "通过", "校验通过")

        # 业务 Agent 标记 needs_human（政策无引用 / 健康紧急症状）→ 无缝转人工
        if result.get("status") == "needs_human":
            reason = result.get("chain_note", "需人工确认")
            result = self._transfer_to_human(ctx, result, reason)
            return self._finish(ctx, result["reply"], result["status"], target,
                                [{"type": "navigate", "to": "/resident/messages", "label": "查看消息"}],
                                result.get("handoff_id"))

        # 主动协商：处理目标 Agent 消息队列中的协商消息（事件触发，按优先级）
        # 真协商（P2-A2-02）：链式处理——响应引发的新消息继续协商，直到队列空或达轮次上限
        # P1-1：LLM 自主协商（可选开关 LLM_ORCHESTRATION=1）——LLM 判断是否联动其他角色
        try:
            from agent.llm_negotiator import decide_collaboration
            dec = decide_collaboration(ctx.get("user_input", ""), intent)
            if dec.get("need") and dec.get("target") and dec["target"] in self.agents:
                self._log("negotiation", "LLM自主协商", f"→{dec['target']}：{dec.get('reason', '')}")
                self.bb.post_message(dec["target"], {
                    "from": target, "to": dec["target"], "type": "notify",
                    "payload": {"event": "llm_collaboration",
                                "reason": dec.get("reason", ""),
                                "context": ctx.get("user_input", "")[:60]},
                })
        except Exception:
            pass
        result = self._drain_negotiations(result, target)
        # 记录目标 Agent 发起的协商（handoff/notify 等，消息保留供后续消费）
        self._record_outbound_negotiations(target)

        # 3) 合规审计员（所有业务输出都过）
        self._log("compliance_auditor", "审计", "脱敏/敏感词/留痕检查")
        audit = self.agents["compliance_auditor"].process({
            "output_text": result.get("reply", ""),
            "role": ctx.get("role"), "uid": ctx.get("uid"),
            "user_input": ctx.get("user_input", ""),
            "intent": result.get("intent", intent),
            "related_id": result.get("related_id"),
            "status": result.get("status", "成功"),
        })
        if not audit.get("passed"):
            self._log("compliance_auditor", "拦截", audit.get("reason", ""))
            # 冲突仲裁：合规优先 → block / 人工
            arb = self.arbiter.arbitrate({"audit_failed": True, "agent": target,
                                          "reason": audit.get("reason")})
            self._log("arbiter", "仲裁", arb["explanation"])
            # 无缝转人工（T7：合规不通过 → 人工审核处理包）
            result = self._transfer_to_human(ctx, result, "合规审计：" + audit.get("reason", ""))
            return self._finish(ctx, audit.get("reply", "该内容需人工审核。"), result["status"],
                                target,
                                [{"type": "navigate", "to": "/resident/messages", "label": "查看消息"}],
                                result.get("handoff_id"))

        if result.get("chain_note"):
            self._log(target, "完成", result["chain_note"])
        return self._finish(ctx, result["reply"], result.get("status", "成功"),
                            target, result.get("actions", []),
                            result.get("related_id"))

    def _record_outbound_negotiations(self, target: str) -> None:
        """记录目标 Agent 发起的主动协商（handoff/notify 等）到执行链（不消费消息）。"""
        for recv, msgs in list(self.bb.messages.items()):
            for m in msgs:
                if m.get("from") == target:
                    payload = m.get("payload") or {}
                    self._log("negotiation", f"主动协商：{target}→{recv}",
                              f"{m.get('type')}·{payload.get('event', '')}")

    def _handle_negotiations(self, target: str, result: dict) -> dict:
        """处理目标 Agent 消息队列中的协商消息（事件触发）。

        - 按优先级排序（high 优先）
        - 循环防护：同一目标累计协商 > 2 轮强制转人工
        - 协商结果合并进当前回复（追加提示）
        """
        msgs = self.bb.get_messages(target)
        if not msgs:
            return result
        # 循环防护计数
        count_key = f"negotiation:{target}"
        rounds = self.bb.read(count_key) or 0
        if rounds >= 2:
            self.bb.clear_messages(target)
            self._log("negotiation", "循环防护", f"{target} 协商超过 2 轮，强制转人工")
            result = dict(result)
            result["reply"] = (result.get("reply", "") + "\n\n系统正在为您协调人工处理，请稍候。").strip()
            result["status"] = "transferred_to_human"
            return result
        self.bb.write(count_key, rounds + 1, "orchestrator")

        agent = self.agents[target]
        for msg in sorted(msgs, key=lambda m: 0 if m.get("priority") == "high" else 1):
            resp = agent.process_negotiation(msg)
            if resp is None:
                continue
            self._log("negotiation", f"协商：{msg.get('from')}→{target}",
                      f"{msg.get('type')}·{msg.get('payload', {}).get('event', '')}")
            # 回复发起方
            self.bb.post_message(msg.get("from", "receptionist"), {
                "from": target, "to": msg.get("from"), "type": "task_response",
                "payload": resp,
            })
            # 合并协商提示到回复（人性化：天气联动健康）
            hint = resp.get("reply")
            if hint and result.get("reply"):
                result = dict(result)
                result["reply"] = (result["reply"] + f"\n\n⚡ 协作提示：{hint}").strip()
        self.bb.clear_messages(target)
        return result

    def _drain_negotiations(self, result: dict, target: str) -> dict:
        """链式真协商（P2-A2-02）：处理目标队列后，响应引发的新消息继续协商。

        一次用户输入内完成多轮 Agent↔Agent 消息往返（如：天气→健康→通知），
        直到所有队列清空或总轮次达上限（防无限循环，上限由 _handle_negotiations 的
        单目标轮次防护 + 这里的目标遍历次数共同兜底）。

        注意：receptionist 是路由汇总终点（_dispatch 每轮向其 post task_response 留痕），
        不参与业务协商，跳过以免轮次误累加。
        """
        result = self._handle_negotiations(target, result)
        # 响应可能触发发起方再次发消息给第三方（如健康确认 → 天气 → 通知管理员）
        for _ in range(5):
            active = [k for k in self.agents if k != "receptionist" and self.bb.get_messages(k)]
            if not active:
                break
            for k in active:
                result = self._handle_negotiations(k, result)
        return result

    def _call_agent(self, agent, ctx: dict) -> dict:
        """调用 Agent.process，超时重试一次。"""
        start = time.time()
        result = agent.process(ctx)
        if time.time() - start > _AGENT_TIMEOUT_S and _RETRY_ONCE:
            _log.warning("%s 超时，重试一次", agent.key)
            result = agent.process(ctx)
        return result

    def _safe_fallback(self, result: dict, hint: str) -> dict:
        """校验/审计拦截后的安全回答（保留原回复核心，附加人工引导）。"""
        r = dict(result)
        r["reply"] = (r.get("reply", "") + f"\n\n{hint}").strip()
        return r

    def _transfer_to_human(self, ctx: dict, result: dict, reason: str) -> dict:
        """无缝转人工：生成人工处理包（上下文快照）→ 审计脱敏 → 落库 → 通知负责人。

        处理包：session/user/original_input/intent/collected_fields/execution_chain/
                pending_issues/recent_history/verification_result。
        负责人打开即可处理，无需重新询问用户。
        """
        from data import db_agent
        uid = ctx.get("uid") or 0
        role = ctx.get("role") or "resident"
        text = ctx.get("user_input") or ""

        # 已收集字段（黑板草稿）
        collected = {}
        for key in ("user:{0}:work_order_draft".format(uid), "user:{0}:proposal_draft".format(uid)):
            try:
                d = self.bb.read(key)
                if d:
                    collected.update(d)
            except Exception:
                pass
        if not collected and ctx.get("state", {}).get("intent"):
            collected = {"intent": ctx["state"]["intent"]}

        # 最近对话
        try:
            recent = [{"role": "user" if not d.get("is_bot") else "assistant",
                       "content": (d.get("text") or "")[:200], "time": (d.get("created_at") or "")[:16]}
                      for d in db_agent.get_dialogs(uid, role, limit=5)]
        except Exception:
            recent = []

        package = {
            "session_id": self.bb.session_id,
            "user": {
                "user_id": uid, "name": ctx.get("name") or "",
                "phone_masked": "", "role": role,
            },
            "original_input": text,
            "intent": ctx.get("intent") or result.get("intent") or "",
            "collected_fields": collected,
            "execution_chain": self.execution_chain[-8:],
            "pending_issues": [reason],
            "related_citations": [],
            "recent_history": recent,
            "verification_result": self.bb.read("verify_result") or {},
            "transferred_at": datetime.now().isoformat(),
        }

        # 合规审计员脱敏检查（处理包不得含完整手机号/身份证）
        audit = self.agents["compliance_auditor"].process({
            "output_text": text + " " + str(collected) + " " + reason,
            "role": role, "uid": uid, "user_input": text,
            "intent": result.get("intent") or "", "related_id": None, "status": "转人工",
        })
        if not audit.get("passed"):
            # 移除敏感字段（脱敏兜底）
            for f in ("phone", "phone_masked"):
                package["user"].pop(f, None)
            collected.pop("phone", None)

        try:
            hid = db_agent.create_handoff(self.bb.session_id, uid, role,
                                          package["intent"], reason, package)
            # 通知负责人（消息中心）
            from data.db_notifications import create_notification
            from data.db_user import list_users
            for gu in list_users(role="grid"):
                try:
                    create_notification(gu["id"], "agent_handoff",
                                        f"🤝 人工处理：{package['intent']}",
                                        f"用户「{ctx.get('name') or uid}」需人工处理：{reason}（AI 已整理上下文）",
                                        related_id=hid)
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            _log.warning("转人工落库/通知失败：%s", e)
            hid = None

        self._log("negotiation", "转人工", f"{reason}（处理包 #{hid or '—'}）")
        result = dict(result)
        result["reply"] = (result.get("reply", "") +
                           "\n\n已为您转接工作人员，他们会直接联系您，不用重新说一遍。").strip()
        result["status"] = "transferred_to_human"
        result["handoff_id"] = hid
        return result

    def _community_pulse(self, ctx: dict) -> dict:
        """社区动态快照：最新通知 + 今日天气 + 我名下的待办（接待员直答，仍过审计）。

        修复背景（第九轮自查）：居民问「今天社区有什么新鲜事」这类**自然问句**原先没有任何意图命中，
        回复是"我没太理解您的意思"——演示时很掉分。这里用**已有数据**拼一个真实快照回答，
        取数失败逐项降级，绝不整段失败。
        """
        parts: list[str] = []
        # ① 最新通知（取用户可见的前 3 条）
        try:
            from data.db_notice import get_visible_notices
            role = ctx.get("role") if ctx.get("role") in ("elderly", "resident") else "resident"
            rows = get_visible_notices(role, ctx.get("uid"), limit=3,
                                                    tenant=tenant_of_user(ctx.get("uid"))) or []
            if rows:
                parts.append("📢 最新通知：" + "；".join(n.get("title", "") for n in rows))
        except Exception:  # noqa: BLE001
            pass
        # ② 今日天气
        try:
            from data.db_weather import get_simplified_weather
            w = get_simplified_weather("") or {}
            if w.get("condition"):
                parts.append(f"🌤️ 今日天气：{w.get('condition')} "
                             f"{w.get('temp_low')}°~{w.get('temp_high')}°")
        except Exception:  # noqa: BLE001
            pass
        # ③ 我名下的未结报修
        try:
            from data.db_repair import get_issues
            mine = get_issues(reporter_id=ctx.get("uid"), limit=100) if ctx.get("uid") else []
            open_n = sum(1 for r in mine if r.get("status") not in ("处理结束", "已关闭", "已撤回"))
            if mine:
                parts.append(f"🔧 您的报修：{open_n} 条处理中")
        except Exception:  # noqa: BLE001
            pass

        reply = ("社区最近的情况：\n" + "\n".join(parts)) if parts else \
            "社区最近比较平稳，暂时没有需要特别提醒的新情况。"
        actions = [{"type": "navigate", "to": "/resident/notices", "label": "查看通知"}]
        self._log("receptionist", "社区动态", "返回社区动态快照（通知+天气+我的报修）")
        audit = self.agents["compliance_auditor"].process({
            "output_text": reply, "role": ctx.get("role"), "uid": ctx.get("uid"),
            "user_input": ctx.get("user_input", ""), "intent": "community_pulse",
            "related_id": None, "status": "成功",
        })
        return self._finish(ctx, audit.get("reply", reply), "成功", "community_pulse", actions, None)

    def _community_or_withdraw(self, ctx: dict, intent: str) -> dict:
        """联系社区 / 撤回引导 / 老年通知查询（接待员直答，仍过审计）。"""
        if intent == "community":
            from agent.web_agent_service import _exec_community_phone
            phone = _exec_community_phone()
            reply = f"社区服务中心电话：{phone}"
            actions = [{"type": "confirm_call", "label": "一键拨打", "phone": phone}]
            self._log("receptionist", "联系社区", "提供电话并支持一键拨打")
        elif intent == "withdraw":
            reply = "工单在「待审核」状态可以撤回。已为您打开我的报修列表。"
            actions = [{"type": "navigate", "to": "/resident/work-orders", "label": "去我的报修"}]
            self._log("receptionist", "撤回引导", "引导到工单详情")
        elif intent == "notification":
            # 通知查询 → 直接返回该角色可见的通知列表（居民/老年大字；不再让居民看到负责人口吻）
            role = ctx.get("role") if ctx.get("role") in ("elderly", "resident") else "resident"
            try:
                from data.db_notice import get_visible_notices
                rows = get_visible_notices(role, ctx.get("uid"), limit=5,
                                                 tenant=tenant_of_user(ctx.get("uid")))
                if rows:
                    lines = [f"· {n.get('title', '')}" for n in rows]
                    reply = "🔔 最近通知：\n" + "\n".join(lines)
                else:
                    reply = "最近没有新通知。"
                to = "/elderly/notices" if role == "elderly" else "/resident/notices"
                label = "去听通知" if role == "elderly" else "查看通知"
                actions = [{"type": "navigate", "to": to, "label": label}]
            except Exception:
                reply = "通知查询暂时不可用。"
                actions = []
            self._log("receptionist", "通知查询", f"返回{role}可见通知列表")
        else:
            reply = "正在为您处理。"
            actions = []
        audit = self.agents["compliance_auditor"].process({
            "output_text": reply, "role": ctx.get("role"), "uid": ctx.get("uid"),
            "user_input": ctx.get("user_input", ""), "intent": intent,
            "related_id": None, "status": "成功",
        })
        return self._finish(ctx, audit.get("reply", reply), "成功", intent, actions, None)

    # ---- 汇总 ----

    def _finish(self, ctx: dict, reply: str, status: str, intent: str,
                actions: list, related_id) -> dict:
        # 草稿内容落库（P1-A5-02）：每轮持久化黑板草稿；提交成功则删除
        try:
            from data.db_draft import save_draft, delete_draft
            uid = ctx.get("uid") or 0
            for key in _draft_keys(uid):
                val = self.bb.read(key)
                if val and isinstance(val, dict):
                    save_draft(uid, _draft_type_of(key), val,
                               step=(ctx.get("state") or {}).get("step", ""))
                elif status == "成功" and intent in ("repair_dispatch", "proposal_collab"):
                    delete_draft(uid, _draft_type_of(key))
        except Exception as e:  # noqa: BLE001
            _log.warning("草稿落库失败：%s", e)
        # M2：关怀前置 —— 情绪安抚句 + 场景共情句（会话级去重），统一在此拼进最终回复
        try:
            from agent import tone
            st = ctx.get("state") or {}
            comfort = st.pop("emotion_comfort", "")
            scene = None
            if status == "成功" and intent in ("repair_dispatch", "proposal_collab"):
                scene = "repair_ok"
            elif intent == "handoff" or status in ("needs_human", "transferred_to_human"):
                scene = "sos"
            elif status == "失败":
                scene = "fail"
            used = self.bb.read("empathized") or set()
            line = tone.pick(scene, used) if scene else ""
            if used:
                self.bb.write("empathized", used, "orchestrator")
            prefix = " ".join([c for c in (comfort, line) if c])
            if prefix and reply:
                reply = f"{prefix}\n{reply}"
            # U4：关怀量化——有安抚句/场景共情句时记一条关怀事件（无 PII，只存标签）
            if prefix:
                try:
                    from data.db_care_metrics import log_care_event
                    emo_tag = ""
                    try:
                        emo_tag, _c = tone.detect_emotion(ctx.get("user_input") or "")
                    except Exception:
                        emo_tag = ""
                    log_care_event(ctx.get("uid"), ctx.get("role") or "resident",
                                   emotion_tag=emo_tag or "", comfort_used=bool(comfort),
                                   scene=scene or "", scene_line_used=bool(line),
                                   intent=intent or "", status=status or "")
                except Exception:
                    pass
        except Exception:
            pass
        # 会话落库：state 持久化（重启不丢）
        try:
            from data import db_agent
            db_agent.save_session(self.bb.session_id, ctx.get("uid") or 0,
                                  ctx.get("role") or "resident", ctx.get("state") or {})
        except Exception as e:  # noqa: BLE001
            _log.warning("会话落库失败：%s", e)
        # 对话落库（历史）
        try:
            from data import db_agent
            uid = ctx.get("uid"); role = ctx.get("role") or "resident"
            ui = ctx.get("user_input", "")
            if ui:
                db_agent.add_dialog(uid, role, ui, is_bot=0, intent=intent)
            db_agent.add_dialog(uid, role, reply, is_bot=1, intent=intent, related_id=related_id)
        except Exception as e:  # noqa: BLE001
            _log.warning("对话落库失败：%s", e)
        return {
            "reply": reply,
            "intent": intent,
            "status": status,
            "actions": actions,
            "related_id": related_id,
            "execution_chain": self.execution_chain,
            "session_id": self.bb.session_id,
            "roles": role_list(),
        }
