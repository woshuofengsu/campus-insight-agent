# agent/orchestrator.py
"""多 Agent 编排器（Orchestrator）：
接待员 → 意图路由 → 业务/自动角色 Agent → 合规审计员 → 返回 + 执行链。

- 黑板：共享上下文（user_input/intent/context/draft/state）
- 消息协议：角色间 post_message（task_request/task_response/notify/error/handoff）
- 异常：Agent 超时重试一次、黑板锁冲突提示、用户取消清理、审计拦截
"""
import logging
import time
from datetime import datetime

from agent.blackboard import Blackboard, BlackboardLockError
from agent.roles import create_agents, role_list

_log = logging.getLogger(__name__)

_AGENT_TIMEOUT_S = 3.0
_RETRY_ONCE = True


def _state_key(uid):
    return f"user:{uid}:state"


def _draft_keys(uid):
    return [f"user:{uid}:work_order_draft", f"user:{uid}:proposal_draft"]


class Orchestrator:
    """多 Agent 编排器（每用户会话一个实例，黑板带 session_id）。"""

    def __init__(self, session_id: str | None = None):
        from agent.blackboard import Blackboard
        from agent.roles import create_agents
        self.bb = Blackboard(session_id=session_id)
        self.agents = create_agents(self.bb)
        from agent.arbiter import Arbiter
        from agent.verifier import Verifier
        self.arbiter = Arbiter()
        self.verifier = Verifier()
        self.execution_chain: list[dict] = []
        self._persisted = False  # 会话落库（v31）

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
        ctx = {"role": role, "uid": uid, "name": name, "user_input": text,
               "elder_uid": elder_uid,
               "state": st}

        # 取消指令：清理草稿与状态（彻底清空，避免残留 step 导致续接）
        if text in ("算了", "取消", "不要了", "先不弄了"):
            for k in _draft_keys(uid):
                try:
                    self.bb.unlock(k)
                    self.bb.write(k, None, "orchestrator", lock=False)
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
        resumed = self._resume_target(st, text)
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

    def _resume_target(self, st: dict, text: str) -> str | None:
        """根据黑板 state 判断是否续接某业务 Agent（追问/草稿确认/导出确认）。"""
        if not st:
            return None
        step = st.get("step")
        intent = st.get("intent")
        if st.get("pending_export"):
            return "grid_assistant"
        if step == "ask_type" or step == "ask_urgency" or (step == "confirm" and intent == "repair"):
            return "repair_dispatch"
        if step == "ask_public" or (step == "confirm" and intent == "proposal"):
            return "proposal_collab"
        return None

    def _dispatch(self, ctx: dict, intent: str) -> dict:
        """按意图路由到业务/自动角色 Agent，末尾过合规审计。"""
        from agent.roles.config import ROUTE_MAP
        target = ROUTE_MAP.get(intent)
        if target is None and intent in self.agents:
            target = intent  # 续接会话时 intent 即角色 key
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
                    result = self._safe_fallback(result, "该内容需人工确认，已为您转人工。")
                    result["status"] = "transferred_to_human"
                else:
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

        # 主动协商：处理目标 Agent 消息队列中的协商消息（事件触发，按优先级）
        result = self._handle_negotiations(target, result)
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
            return self._finish(ctx, audit.get("reply", "该内容需人工审核。"), "拦截",
                                target, [], result.get("related_id"))

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

    def _community_or_withdraw(self, ctx: dict, intent: str) -> dict:
        """联系社区 / 撤回引导（接待员直答，仍过审计）。"""
        if intent == "community":
            from agent.web_agent_service import _exec_community_phone
            phone = _exec_community_phone()
            reply = f"社区服务中心电话：{phone}"
            actions = [{"type": "confirm_call", "label": "一键拨打", "phone": phone}]
            self._log("receptionist", "联系社区", "提供电话并支持一键拨打")
        else:
            reply = "工单在「待审核」状态可以撤回。已为您打开我的报修列表。"
            actions = [{"type": "navigate", "to": "/resident/work-orders", "label": "去我的报修"}]
            self._log("receptionist", "撤回引导", "引导到工单详情")
        audit = self.agents["compliance_auditor"].process({
            "output_text": reply, "role": ctx.get("role"), "uid": ctx.get("uid"),
            "user_input": ctx.get("user_input", ""), "intent": intent,
            "related_id": None, "status": "成功",
        })
        return self._finish(ctx, audit.get("reply", reply), "成功", intent, actions, None)

    # ---- 汇总 ----

    def _finish(self, ctx: dict, reply: str, status: str, intent: str,
                actions: list, related_id) -> dict:
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
