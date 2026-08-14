# agent/engine.py
"""Agent 推理模块 —— OODA 治理工作流：观察 → 定位 → 决策 → 反思 → 关联

每个 run() 调用执行全部五个阶段，让 Agent 不仅回答问题，还能主动感知
社区动态、自我纠错、发现关联模式。
"""
import re
from datetime import datetime
from utils.text import split_thinking

from langchain_openai import ChatOpenAI
from langchain_classic.agents import AgentExecutor, create_openai_functions_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    AGENT_MAX_ITERATIONS, AGENT_TIMEOUT, AGENT_TEMPERATURE,
)
from agent.prompt import get_system_prompt, detect_persona
from agent.memory import MemoryManager
from tools import discover_tools
from utils.logger import get_logger

logger = get_logger(__name__)


class CommunityAgent:
    """主编排类 —— OODA 治理工作流"""

    def __init__(self, session_state):
        self.memory = MemoryManager(session_state)
        self.llm = self._create_llm()
        self.tools = discover_tools()
        self.memory.register_tools([t.name for t in self.tools])

        if not self.tools:
            logger.warning("No tools discovered! Agent will be chat-only.")

        self._last_thinking = ""   # extracted thinking blocks from last response
        self._last_chain = None    # structured reasoning chain from last run (for UI)

        logger.info(f"CommunityAgent initialized with {len(self.tools)} tools")

    def _create_llm(self) -> ChatOpenAI:
        """初始化 DeepSeek 模型"""
        if not DEEPSEEK_API_KEY:
            raise ValueError(
                "DEEPSEEK_API_KEY not set. Please create a .env file with your API key.\n"
                "Copy .env.example to .env and fill in your key."
            )
        return ChatOpenAI(
            model=DEEPSEEK_MODEL,
            openai_api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            temperature=AGENT_TEMPERATURE,
            max_tokens=2000,
        )

    def _filter_tools_for_role(self, role: str) -> list:
        """按角色裁剪工具集，让 LLM 不被无关工具干扰。

        老年：极简 4 工具（上报/查单/天气/脉搏）。
        网格员：去掉居民侧动作（上报/附议/发意见/建提案）。
        居民：全量。
        """
        if role == "elderly":
            allowed = {"report_issue", "query_my_issues", "get_weather", "get_community_pulse"}
            return [t for t in self.tools if t.name in allowed]
        if role == "grid":
            excluded = {"report_issue", "support_proposal", "express_opinion", "create_proposal"}
            return [t for t in self.tools if t.name not in excluded]
        return self.tools

    def _build_agent(self, environment_context: str = "") -> AgentExecutor:
        """构建 LangChain Agent，注入感知上下文（天气、预警等）"""
        user_profile = self.memory.get_user_profile()
        system_prompt = get_system_prompt(user_profile, environment_context)
        role = user_profile.get("role", "resident")
        tools = self._filter_tools_for_role(role)

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        agent = create_openai_functions_agent(
            llm=self.llm,
            tools=tools,
            prompt=prompt,
        )

        return AgentExecutor(
            agent=agent,
            tools=tools,
            memory=self.memory.get_langchain_memory(),
            max_iterations=AGENT_MAX_ITERATIONS,
            max_execution_time=AGENT_TIMEOUT,
            verbose=False,
            handle_parsing_errors=True,
            return_intermediate_steps=True,   # capture tool-call trace for reasoning chain viz
        )

    # -- OODA Loop --

    def run(self, user_input: str) -> str:
        """Execute one full OODA turn: Observe → Orient → Decide+Act → Reflect → Associate.

        Retries up to 2 times on transient API errors with backoff.
        """
        try:
            return self._run_impl(user_input)
        except Exception as e:
            logger.error("FATAL: run() crashed: %s", e, exc_info=True)
            try:
                self._last_chain = None
                self.memory.add_message("assistant",
                    f"😅 抱歉，系统遇到了一点问题。\n\n"
                    f"> 错误：{e}\n\n"
                    f"请稍后重试，或通过页面顶部的「⚡ 快速报修」直接提交工单。"
                )
            except Exception:  # safety net: must not crash the app
                logger.debug("Failed to add fallback message to memory", exc_info=True)
                pass
            return (
                f"😅 抱歉，系统遇到了一点问题。\n\n"
                f"> 错误：{e}\n\n"
                f"请稍后重试，或通过页面顶部的「⚡ 快速报修」直接提交工单。"
            )

    def _run_impl(self, user_input: str) -> str:
        """Internal implementation of run() — wrapped by run() for crash safety."""
        # Reset chain from previous run
        self._last_chain = None

        # Save user message
        self.memory.add_message("user", user_input)

        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # ── Phase 1: OBSERVE ──
                environment = self._observe()

                # ── Phase 2: ORIENT ──
                oriented_input = self._orient(user_input, environment)

                # ── Phase 3: DECIDE + ACT ──
                raw_response, intermediate_steps = self._decide_and_act(oriented_input, environment)

                # ── Phase 4: REFLECT ──
                response = self._reflect(raw_response, user_input, environment,
                                         intermediate_steps)

                # ── Phase 5: ASSOCIATE (post-hoc) ──
                self._last_chain = self._associate(intermediate_steps, response, user_input)

                # Success — save and return
                if response:
                    self.memory.add_message("assistant", response)
                return response

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # Classify error type for retry decision
                is_retryable = any(kw in error_msg.lower() for kw in (
                    "timeout", "connection", "rate limit", "server error",
                    "internal error", "service unavailable", "overloaded",
                    "too many requests", "429", "500", "502", "503", "504",
                ))

                if is_retryable and attempt < max_retries:
                    import time
                    wait = (attempt + 1) * 1.5  # exponential-ish backoff: 1.5s, 3s
                    logger.warning(
                        f"Agent retryable error (attempt {attempt+1}/{max_retries+1}), "
                        f"waiting {wait}s: {error_msg[:120]}"
                    )
                    time.sleep(wait)
                    continue
                else:
                    logger.error(
                        f"Agent execution error (attempt {attempt+1}): {error_msg[:200]}"
                    )
                    break

        # ── All retries exhausted — delegate to OfflineAgent ──
        self._last_chain = None

        # OfflineAgent calls real tools with rule-based routing — far richer
        # than keyword-based fallback. Bypass offline.run() to avoid adding a
        # duplicate user message (already saved above in _run_impl).
        try:
            from agent.offline_agent import OfflineAgent
            from agent.prompt import detect_persona
            offline = OfflineAgent(st.session_state)
            offline.memory = self.memory
            persona = detect_persona(user_input)
            fallback = offline._route(persona, user_input)
            if not fallback:
                fallback = offline._handle_general(user_input)
            logger.info("Delegated to OfflineAgent after LLM failure — %d chars", len(fallback))
        except Exception:
            logger.warning("OfflineAgent delegation failed, using static fallback", exc_info=True)
            try:
                fallback = self._graceful_fallback(user_input, last_error)
            except Exception:
                logger.debug("Static fallback also failed", exc_info=True)
                fallback = f"😅 智能服务暂时不可用，请稍后重试或使用页面顶部的「⚡ 快速报修」。"
        try:
            self.memory.add_message("assistant", fallback)
        except Exception:  # best-effort, skip
            logger.debug("Failed to save fallback message to memory", exc_info=True)
            pass
        return fallback

    # ── OODA Phase Implementations ──

    def _observe(self) -> dict:
        """Phase 1 — Observe: gather environmental context.

        Runs perception checks (weather, issue hotspots, resolved issues) and
        collects time/date context. Returns a structured environment dict.

        Perception alerts here become CONTEXT for the agent's reasoning,
        not standalone messages in the chat.
        """
        from perception.monitor import PerceptionMonitor

        monitor = PerceptionMonitor()
        alerts = monitor.run_all_checks()

        now = datetime.now()
        weekday = ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()]

        # Determine time-of-day context
        hour = now.hour
        if 6 <= hour < 8:
            time_ctx = "清晨"
        elif 8 <= hour < 12:
            time_ctx = "上午"
        elif 12 <= hour < 14:
            time_ctx = "午间"
        elif 14 <= hour < 18:
            time_ctx = "下午"
        elif 18 <= hour < 22:
            time_ctx = "晚间"
        else:
            time_ctx = "深夜"

        # Check for governance hot spots (pending issues by category)
        from data.database import get_issues
        try:
            issues = get_issues(limit=50)
            pending_by_cat: dict[str, int] = {}
            for i in issues:
                if i.get("status") in ("待处理", "处理中"):
                    cat = i.get("category", "其他")
                    pending_by_cat[cat] = pending_by_cat.get(cat, 0) + 1
            hot_categories = [
                {"category": cat, "count": count}
                for cat, count in sorted(pending_by_cat.items(), key=lambda x: -x[1])[:3]
            ]
        except Exception:
            logger.debug("Failed to load hot categories for Observe phase", exc_info=True)
            hot_categories = []

        return {
            "timestamp": now.isoformat(),
            "weekday": weekday,
            "time_context": time_ctx,
            "alerts": alerts,                 # perception alerts list
            "alert_count": len(alerts),
            "hot_categories": hot_categories,  # governance hot spots
        }

    def _orient(self, user_input: str, environment: dict) -> str:
        """Phase 2 — Orient: inject persona + environmental context into user input.

        Layers prepended to the user's message (each invisible to user):
        1. Persona context — role-specific tone & focus hint (from detect_persona)
        2. Situation context — time, weather, hot categories, alerts

        The agent sees: [PERSONA] [SITUATION] [USER MESSAGE]
        """
        parts = []

        # Layer 1: Persona routing — set the agent's "hat" for this turn
        persona = detect_persona(user_input)
        if persona:
            parts.append(
                f"【角色模式：{persona['role']}】{persona['focus_hint']}"
            )

        # Layer 1.5: Semantic tool routing — suggest which tool fits this turn
        # (semantic route + keyword fallback). Helps the agent call the right tool
        # even for phrasing not covered by the prompt's trigger-word table.
        try:
            from agent.router import route_intent
            route = route_intent(user_input)
            if route.get("tool"):
                parts.append(
                    f"【本轮建议工具：{route['tool']}（{route['confidence']}置信度/{route['method']}路由）】"
                )
            elif route.get("needs_clarification"):
                parts.append(
                    f"【意图不明确，需追问澄清：{route.get('question') or '请用户补充关键信息'}】"
                )
        except Exception:
            logger.debug("Semantic tool routing skipped (non-fatal)", exc_info=True)

        # Layer 1.6: Plan-and-Execute — inject a step plan for complex queries
        try:
            from agent.planner import plan_steps
            steps = plan_steps(user_input)
            if steps:
                parts.append("【建议步骤计划】" + " → ".join(steps))
        except Exception:
            logger.debug("Planning skipped (non-fatal)", exc_info=True)

        # Layer 1.7: Personal event memory — inject "你最近..." for continuity
        try:
            uid = self.memory.user_id
            from data.db_memory import get_event_summary
            summary = get_event_summary(uid, limit=3)
            if summary:
                parts.append(f"【与你相关】你最近：{summary}")
        except Exception:
            logger.debug("Event memory injection skipped (non-fatal)", exc_info=True)

        # Layer 2: Time context
        parts.append(
            f"现在是{environment['weekday']}{environment['time_context']}。"
        )

        # Layer 3: Governance hot spots
        if environment.get("hot_categories"):
            hot_strs = [
                f"{h['category']}({h['count']}件待处理)" for h in environment["hot_categories"]
            ]
            parts.append(f"治理热点：{'、'.join(hot_strs)}。")

        # Layer 4: Perception alerts (truncated)
        if environment["alerts"]:
            alert_summaries = [
                f"{a['emoji']}{a['title']}" for a in environment["alerts"][:3]
            ]
            parts.append(f"当前提醒：{'、'.join(alert_summaries)}。")

        # Assemble: context as prefix, user input follows
        if parts:
            context_prefix = "【情境感知】" + " ".join(parts) + "\n"
            return context_prefix + "【用户消息】" + user_input

        return user_input

    def _decide_and_act(self, oriented_input: str, environment: dict) -> tuple[str, list]:
        """Phase 3 — Decide+Act: the LangChain agent reasons and calls tools.

        The agent receives the oriented_input (with injected context), decides
        which tools to invoke, executes them, and produces a response.

        Streaming callback captures tool execution events in real-time for the
        UI tool-call indicator.

        Returns:
            (output_text, intermediate_steps) — intermediate_steps is the raw
            LangChain tool-call trace: list[tuple[AgentAction, str]]
        """
        # ── Plan-and-Execute 快路径：规则模板复合查询直接执行 + LLM 汇总 ──
        raw_user = oriented_input.split("【用户消息】")[-1] if "【用户消息】" in oriented_input else oriented_input
        try:
            from agent.planner import execute_plan_steps
            plan_results = execute_plan_steps(raw_user)
            if plan_results:
                summary = self._summarize_plan(plan_results, raw_user)
                if summary:
                    return summary, []  # 走了规划执行，无 AgentExecutor 步骤
        except Exception:
            logger.debug("Plan-and-Execute fast path skipped", exc_info=True)

        executor = self._build_agent(
            environment_context=self._format_environment_for_prompt(environment)
        )

        # Attach streaming callback if session_state is available
        callbacks = []
        try:
            from agent.callbacks import StreamingCallback
            # Use the same session_state that the agent was initialized with
            st_state = self.memory.st
            if hasattr(st_state, '_stream_events') or isinstance(st_state, dict):
                callback = StreamingCallback(st_state)
                callbacks.append(callback)
                self._last_callback = callback
        except Exception as e:
            logger.debug(f"StreamingCallback setup skipped (non-fatal): {e}")
            self._last_callback = None

        invoke_kwargs: dict = {"input": oriented_input}
        if callbacks:
            invoke_kwargs["config"] = {"callbacks": callbacks}

        result = executor.invoke(invoke_kwargs)
        output = result.get("output", "")
        steps = result.get("intermediate_steps", [])
        return output, steps

    def _summarize_plan(self, plan_results: list[dict], user_input: str) -> str | None:
        """LLM 汇总 Plan-and-Execute 执行结果（best-effort）。"""
        try:
            from langchain_openai import ChatOpenAI
            from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
            if not DEEPSEEK_API_KEY:
                return None
            llm = ChatOpenAI(
                model=DEEPSEEK_MODEL, openai_api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL, temperature=0.3, max_tokens=600, timeout=8,
            )
            facts = "\n".join(f"[{r['tool']}]\n{r['observation']}" for r in plan_results)
            prompt = (
                "你是社区助手。根据下面工具返回的真实数据回答用户问题。\n"
                "引用具体数字，先给结论再给细节，末尾给 1 个下一步建议。\n\n"
                f"用户：{user_input}\n\n工具数据：\n{facts}\n"
            )
            resp = llm.invoke(prompt)
            content = (getattr(resp, "content", "") or "").strip()
            return content or None
        except Exception:
            logger.debug("plan summarize failed", exc_info=True)
            return None

    def _reflect(self, raw_response: str, user_input: str, environment: dict,
                 intermediate_steps: list | None = None) -> str:
        """Phase 4 — Reflect: post-response validation.

        Runs seven checks: strip thinking tags, catch empty responses, verify
        alerts were addressed, check response depth, closed-loop integrity,
        governance audit trigger, and anti-hallucination tool-call enforcement.
        """
        # ── 4.0: Extract thinking blocks before any other processing ──
        cleaned, thinking = split_thinking(raw_response)
        self._last_thinking = thinking

        # Pattern 3: Lines that are pure tool-call trace (LangChain verbose leak)
        cleaned = "\n".join(
            line for line in cleaned.split("\n")
            if not any(line.strip().startswith(p) for p in (
                "Invoking:", "Entering new", "Finished chain", "> Entering",
                "> Finished", "Thought:", "Action:", "Observation:",
            ))
        ).strip()

        # Collapse blank lines (may have been introduced by line filtering above)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        raw_response = cleaned
        if not raw_response or not raw_response.strip():
            return "😅 抱歉，我没能生成有效的回复。请换个方式描述你的需求试试？"

        # ── 4.1: High-priority alerts unaddressed ──
        high_alerts = [
            a for a in environment.get("alerts", [])
            if a["title"] in ("恶劣天气预警", "问题解决通知")
        ]
        if high_alerts:
            mentioned = any(
                a["title"] in raw_response for a in high_alerts
            )
            if not mentioned:
                note = "\n\n💡 *另外提醒：{}*".format(
                    "；".join(f"{a['emoji']} {a['title']}" for a in high_alerts[:2])
                )
                raw_response += note

        # ── 4.2: Complex query short response ──
        complex_keywords = ["分析", "对比", "汇总", "统计", "治理", "提案", "议题", "民意"]
        is_complex = any(kw in user_input for kw in complex_keywords)
        if is_complex and len(raw_response) < 80:
            raw_response += (
                "\n\n🤔 以上是简要回答。如果需要更详细的分析或方案，"
                "可以告诉我更多细节，我再帮你深入看看~"
            )

        # ── 4.3: Closed-loop integrity check ──
        # Detect open governance loops: user's unresolved issues, stale proposals,
        # and recurrence patterns. Only appends a note — doesn't block the response.
        loop_note = self._check_closed_loop(user_input, raw_response)
        if loop_note:
            raw_response += loop_note

        # ── 4.4: Governance audit trigger ──
        # When user asks for a comprehensive check, run cross-table analysis
        audit_keywords = ["审计", "全面检查", "治理体检", "综合分析", "整体情况"]
        if any(kw in user_input for kw in audit_keywords):
            audit_note = self._governance_audit()
            if audit_note:
                raw_response += "\n\n---\n\n🏥 **治理体检报告**\n\n" + audit_note

        # ── 4.5: Tool-call safety net (anti-hallucination) ──
        # When the user clearly wants to report an issue but the LLM didn't
        # actually call report_issue (it hallucinated a confirmation), force
        # the real tool call and replace the fake response.
        raw_response = self._enforce_tool_call(raw_response, user_input,
                                                intermediate_steps)

        # ── 4.6: Fact reflection (anti-hallucination #2) ──
        # 编号存在性（正则护栏）+ LLM 数值/语义一致性核查（主防线）。
        raw_response = self._verify_facts(raw_response, intermediate_steps)

        return raw_response

    def _verify_facts(self, response: str, intermediate_steps: list | None = None) -> str:
        """Reflect on cited facts against tool results. Delegates to agent/reflection.py."""
        from agent.reflection import reflect
        return reflect(response, intermediate_steps)

    def _enforce_tool_call(self, response: str, user_input: str,
                           intermediate_steps: list | None) -> str:
        """Safety net: guarantee report_issue is called for repair intents.

        Delegates to agent/enforce.py.  See enforce_tool_call() for details.
        """
        from agent.enforce import enforce_tool_call
        return enforce_tool_call(response, user_input, intermediate_steps)

    def _check_closed_loop(self, user_input: str, response: str) -> str:
        """Check for open governance loops and return a gentle reminder note.

        Delegates to agent/closed_loop.py.  See check_closed_loop() for details.
        """
        from agent.closed_loop import check_closed_loop
        return check_closed_loop(self.memory, user_input, response)

    def _governance_audit(self) -> str:
        """Run a governance audit — delegates to governance_audit module.

        Extracted from engine.py (v2 report card with per-dimension grades,
        trend arrows, and prioritized action items). See agent/governance_audit.py
        for the full implementation and scoring methodology.
        """
        from agent.governance_audit import run_governance_audit
        return run_governance_audit()

    def _format_environment_for_prompt(self, environment: dict) -> str:
        """Format environment context as a compact string for the system prompt."""
        parts = []
        if environment.get("hot_categories"):
            hot_strs = [
                f"{h['category']}({h['count']}件)" for h in environment["hot_categories"]
            ]
            parts.append(f"治理热点：{'、'.join(hot_strs)}")
        if environment.get("alerts"):
            alert_strs = [
                f"{a['emoji']}{a['title']}" for a in environment["alerts"]
            ]
            parts.append(f"📡 环境提醒：{'、'.join(alert_strs)}")
        if parts:
            return "\n".join(parts)
        return ""

    def _associate(self, intermediate_steps: list, raw_response: str, user_input: str) -> dict | None:
        """Post-hoc association analysis. Builds reasoning chain, discovers patterns.

        Uses text-action fallback parser when DeepSeek skips formal tool calls,
        so empty intermediate_steps is still processed. Returns dict or None.
        """
        try:
            from agent.reflector import build_reasoning_chain
            # Always call build_reasoning_chain — it handles empty intermediate_steps
            # gracefully with text-action fallback + final reflect step.
            chain = build_reasoning_chain(intermediate_steps, raw_response, user_input)
            n_steps = len(chain.get('steps', []))
            assoc = chain.get('associations') or {}
            has_insight = assoc.get('has_insight', False) if isinstance(assoc, dict) else False
            logger.info(
                f"Reasoning chain built: {n_steps} steps, "
                f"associations={'found' if has_insight else 'none'}"
            )
            # Only return None when there's truly nothing to show
            if not chain or (not chain.get("steps") and not has_insight):
                return None
            return chain
        except ImportError:
            logger.warning("agent.reflector not available — skipping association analysis")
            return None
        except Exception as e:
            logger.warning(f"Association analysis failed (non-fatal): {e}")
            return None

    def _graceful_fallback(self, user_input: str, error: Exception | None = None) -> str:
        """Provide a graceful fallback response when the agent fails after retries.

        Delegates to agent/fallback.py.  See graceful_fallback() for details.
        """
        from agent.fallback import graceful_fallback
        return graceful_fallback(user_input, error)

    def get_last_chain(self) -> dict | None:
        """Return the structured reasoning chain from the most recent run().

        For use by UI layer (home.py) to render the thinking visualization.
        Returns None if no run has completed yet or if the last run had no tool calls.
        """
        return self._last_chain

    # ── Public API for external perception triggers ──

    def run_perception_check(self) -> list[dict]:
        """Run perception checks and return new alerts.

        Used by app.py for idle-based proactive alerting (separate from
        the per-turn OODA Observe phase).
        """
        environment = self._observe()
        alerts = environment.get("alerts", [])

        # Filter out alerts already shown recently
        recent_messages = self.memory.get_working_memory()[-5:]
        new_alerts = []
        for alert in alerts:
            already_shown = any(
                alert["title"] in msg.get("content", "")
                for msg in recent_messages
            )
            if not already_shown:
                new_alerts.append(alert)
        return new_alerts
