# agent/engine.py
"""Agent 推理引擎 —— OODA 循环：观察 → 定位 → 决策 → 反思 → 关联

每个 run() 调用执行全部五个阶段，让 Agent 不仅回答问题，还能主动感知
校园动态、自我纠错、发现关联模式。
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
from agent.helpers import get_author_identifier
from tools import discover_tools
from utils.logger import get_logger

logger = get_logger(__name__)


class CampusAgent:
    """校园先知主 Agent —— OODA 认知循环"""

    def __init__(self, session_state):
        self.memory = MemoryManager(session_state)
        self.llm = self._create_llm()
        self.tools = discover_tools()
        self.memory.register_tools([t.name for t in self.tools])

        if not self.tools:
            logger.warning("No tools discovered! Agent will be chat-only.")

        self._last_thinking = ""   # extracted thinking blocks from last response
        self._last_chain = None    # structured reasoning chain from last run (for UI)

        logger.info(f"CampusAgent initialized with {len(self.tools)} tools")

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

    def _build_agent(self, environment_context: str = "") -> AgentExecutor:
        """构建 LangChain Agent，注入感知上下文（天气、预警等）"""
        user_profile = self.memory.get_user_profile()
        system_prompt = get_system_prompt(user_profile, environment_context)

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        agent = create_openai_functions_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt,
        )

        return AgentExecutor(
            agent=agent,
            tools=self.tools,
            memory=self.memory.get_langchain_memory(),
            max_iterations=AGENT_MAX_ITERATIONS,
            max_execution_time=AGENT_TIMEOUT,
            verbose=False,
            handle_parsing_errors=True,
            return_intermediate_steps=True,   # capture tool-call trace for reasoning chain viz
        )

    # ═══════════════════════════════════════════════════════════════
    # OODA Loop
    # ═══════════════════════════════════════════════════════════════

    def run(self, user_input: str) -> str:
        """Execute one full OODA turn with the given user input.

        Observe → Orient → Decide+Act → Reflect → Associate (post-hoc)

        Includes automatic retry (up to 2 attempts) on transient API errors
        with exponential backoff. Falls back to a graceful cached-style response
        if all retries are exhausted.

        Outermost try/except ensures NO exception propagates to Streamlit
        (prevents the app from crashing on unexpected errors).
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
            except Exception:
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

        # ── All retries exhausted — graceful degradation ──
        self._last_chain = None

        # Try to provide a cached/db-based fallback instead of raw error
        try:
            fallback = self._graceful_fallback(user_input, last_error)
        except Exception:
            fallback = f"😅 AI 服务暂时不可用，请稍后重试或使用页面顶部的「⚡ 快速报修」。"
        try:
            self.memory.add_message("assistant", fallback)
        except Exception:
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

    def _reflect(self, raw_response: str, user_input: str, environment: dict,
                 intermediate_steps: list | None = None) -> str:
        """Phase 4 — Reflect: post-response quality check + thinking extraction.

        Runs seven checks:
        1. Strip AI thinking tags (DeepSeek) — saved to memory for UI expander
        2. Empty response → friendly fallback
        3. High-priority alerts unaddressed → append gentle reminder
        4. Response too short for complex governance query → suggest elaboration
        5. Closed-loop integrity — detect unresolved issues / stale proposals
        6. Governance audit trigger — comprehensive cross-table analysis
        7. Tool-call safety net — auto-call report_issue if LLM faked it
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

        return raw_response

    def _enforce_tool_call(self, response: str, user_input: str,
                           intermediate_steps: list | None) -> str:
        """Safety net: guarantee report_issue is called AND succeeds for repair intents.

        Handles TWO failure modes:
        1. LLM didn't call report_issue at all (hallucinated a fake response)
        2. LLM called report_issue but it returned an error (e.g. validate_location
           blocked it) — the LLM may still respond as if it succeeded

        In both cases we force a real, successful tool call.
        """
        if not intermediate_steps:
            intermediate_steps = []

        # ── Check if report_issue was called AND succeeded ──
        report_called = False
        report_succeeded = False
        for step in intermediate_steps:
            if len(step) >= 2:
                tool = step[0]  # (AgentAction, observation) tuple
                tool_name = getattr(tool, 'tool', '')
                if tool_name == "report_issue":
                    report_called = True
                    observation = step[1]  # tool return value
                    # Check if the tool returned an error
                    if not any(observation.startswith(p) for p in ("⚠️", "❌")):
                        report_succeeded = True
                    break

        if report_succeeded:
            return response  # Tool was called and succeeded — nothing to do

        # ── Check if user input looks like a problem report ──
        from agent.prompt import detect_persona
        persona = detect_persona(user_input)
        is_repair_intent = bool(persona and "报修助手" in persona.get("role", ""))

        if not is_repair_intent:
            return response

        # ── Force the real tool call ──
        if report_called:
            logger.warning(
                "Safety net: report_issue was called but FAILED. Retrying. "
                "user_input=%r", user_input[:80]
            )
        else:
            logger.warning(
                "Safety net: report_issue NOT called for repair intent. "
                "Enforcing real tool call. user_input=%r, response_preview=%r",
                user_input[:80], response[:80]
            )

        try:
            from tools.action_report_issue import report_issue, _keyword_classify, _keyword_urgency
            from agent.helpers import extract_location

            # Strip prefetch context from title
            clean_input = user_input.split("\n\n[📊")[0].strip()
            title = clean_input[:80]
            location = extract_location(clean_input)

            # Pre-compute category + urgency with fast keyword methods
            # (no LLM API call — instant, and good enough for safety net)
            cat = _keyword_classify(title, clean_input)
            urg = _keyword_urgency(title, clean_input)

            # If location is still empty, try extracting from full user_input
            if not location:
                location = extract_location(user_input)

            result = report_issue.invoke({
                "title": title,
                "category": cat,
                "location": location,
                "description": clean_input,
                "urgency": urg,       # fast path: skips _llm_classify
            })

            # If result is STILL an error, validate_location blocked us.
            # Retry with the full input as location fallback.
            if result.startswith("⚠️") or result.startswith("❌"):
                logger.warning(
                    "Safety net retry also blocked by validation. "
                    "Falling back with full-input location. error=%r", str(result)[:80]
                )
                result = report_issue.invoke({
                    "title": title,
                    "category": cat,
                    "location": location or clean_input[:60],
                    "description": clean_input,
                    "urgency": urg,
                })

            logger.info("Safety net: report_issue result=%r", str(result)[:120])
            return str(result)
        except Exception as e:
            logger.error("Safety net report_issue also failed: %s", e)
            # DON'T return the LLM's hallucinated response with a fake ticket number.
            # Give the user an honest error message instead.
            return (
                "很抱歉，自动上报没有成功 😥\n\n"
                "你可以试试页面顶部的「⚡ 快速报修」——它不走 AI，直接写入数据库，"
                "不会出现这种问题。\n\n"
                f"（错误信息：{str(e)[:100]}）"
            )

    def _check_closed_loop(self, user_input: str, response: str) -> str:
        """Check for open governance loops and return a gentle reminder note."""
        try:
            from data.database import get_issues, get_proposals, get_db

            author = get_author_identifier(self.memory)
            if not author:
                return ""

            all_issues = get_issues(limit=200)
            my_pending = [
                i for i in all_issues
                if i.get("author") == author and i.get("status") in ("待处理", "处理中")
            ]
            my_resolved = [
                i for i in all_issues
                if i.get("author") == author and i.get("status") == "已解决"
            ]

            notes: list[str] = []

            if my_pending:
                pending_titles = "、".join(
                    f"#{i['id']}「{i['title'][:15]}」({i['status']})"
                    for i in my_pending[:3]
                )
                extra = f"等 {len(my_pending)} 件" if len(my_pending) > 3 else ""
                notes.append(
                    f"📋 你还有 {len(my_pending)} 件待处理工单：{pending_titles}{extra}。"
                    f"输入「查看我的工单」追踪进度"
                )

            if my_resolved and not my_pending:
                today = datetime.now().strftime("%Y-%m-%d")
                recent_resolved = [
                    i for i in my_resolved
                    if (i.get("resolved_at") or "")[:10] == today
                ]
                if recent_resolved:
                    notes.append(
                        f"✅ 你上报的 {len(recent_resolved)} 个问题今天已解决！"
                        f"感谢你的参与 ✨"
                    )

            all_props = get_proposals(limit=200)
            my_props_unresponded = [
                p for p in all_props
                if p.get("author") == author
                and p.get("status") in ("讨论中",)
                and p.get("supporter_count", 0) >= 5
            ]
            if my_props_unresponded:
                prop = my_props_unresponded[0]
                notes.append(
                    f"💡 你的提案 #{prop['id']}「{prop['title'][:20]}」已有 "
                    f"{prop['supporter_count']} 人附议，输入「查看我的提案」了解进展"
                )

            with get_db() as conn:
                stale = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
                ).fetchone()
            if stale and stale["cnt"] >= 3:
                notes.append(
                    f"⚠️ 全校有 {stale['cnt']} 件工单超过 7 天未处理，建议关注积压问题"
                )

            if not notes:
                return ""

            return "\n\n---\n\n🔄 **闭环追踪**\n\n" + "\n\n".join(notes)

        except Exception as e:
            logger.warning(f"Closed-loop check failed (non-fatal): {e}")
            return ""

    def _governance_audit(self) -> str:
        """Run a comprehensive governance audit across all tables.

        Enhanced v2: structured report card with per-dimension grades (A+ through F),
        trend arrows, and prioritized action items.
        """
        try:
            from data.database import get_db, compute_health_score

            # ── Use authoritative health score (single source of truth from db_health) ──
            health = compute_health_score()
            resolution_rate = health["resolution_rate"]
            avg_resolution_days = health["avg_days"]

            lines: list[str] = []
            grades: dict[str, dict] = {}  # dimension → {score, grade, detail}

            with get_db() as conn:
                # ── 1. Issue Management (工单管理维度) ──
                issue_summary = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM campus_issues GROUP BY status"
                ).fetchall()
                total_i = sum(r["cnt"] for r in issue_summary)
                by_status = {r["status"]: r["cnt"] for r in issue_summary}
                pending = by_status.get("待处理", 0)
                processing = by_status.get("处理中", 0)
                resolved = by_status.get("已解决", 0)

                # Urgency breakdown
                urgent = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE urgency='紧急' AND status != '已解决'"
                ).fetchone()
                urgent_unresolved = urgent["cnt"] if urgent else 0

                # Stale detection
                stale = conn.execute(
                    "SELECT COUNT(*) as cnt FROM campus_issues "
                    "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
                ).fetchone()
                stale_count = stale["cnt"] if stale else 0

                # Issue management grade
                issue_score = 100.0
                if total_i > 0:
                    issue_score -= max(0, (1 - resolution_rate / 80) * 30)  # penalize low resolution
                if urgent_unresolved > 0:
                    issue_score -= min(urgent_unresolved * 5, 25)
                if stale_count > 0:
                    issue_score -= min(stale_count * 3, 20)
                issue_score = max(0, issue_score)
                grades["📝 工单管理"] = {
                    "score": round(issue_score),
                    "detail": f"解决率 {resolution_rate:.0f}% · 紧急未处理 {urgent_unresolved} · 积压 {stale_count}",
                    "trend": "↑" if resolution_rate >= 70 else "↓",
                }
                lines.append(f"**📝 工单管理**：{total_i} 件 · 待处理 {pending} · 处理中 {processing} · 已解决 {resolved}")
                if avg_resolution_days is not None:
                    lines.append(f"   ⏱️ 平均解决时间：{avg_resolution_days} 天")
                if stale_count > 0:
                    lines.append(f"   ⚠️ 积压 {stale_count} 件超过7天未处理")

                # ── 2. Proposal Engagement (提案参与维度) ──
                prop_summary = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status"
                ).fetchall()
                total_p = sum(r["cnt"] for r in prop_summary)
                by_pstatus = {r["status"]: r["cnt"] for r in prop_summary}
                unresponded = by_pstatus.get("讨论中", 0)
                responded = by_pstatus.get("已回应", 0)
                adopted = by_pstatus.get("已采纳", 0) + by_pstatus.get("已实施", 0)
                adoption_rate = adopted / total_p * 100 if total_p > 0 else 0

                # Avg supporters
                avg_sup_row = conn.execute(
                    "SELECT ROUND(AVG(supporter_count), 1) as avg_sup FROM proposals"
                ).fetchone()
                avg_supporters = avg_sup_row["avg_sup"] if avg_sup_row else 0

                prop_score = 100.0
                if total_p > 0:
                    if unresponded > 0:
                        prop_score -= min(unresponded * 8, 40)
                    prop_score += min(adoption_rate / 50 * 20, 20)
                prop_score = max(0, min(100, prop_score))
                grades["💡 提案参与"] = {
                    "score": round(prop_score),
                    "detail": f"采纳率 {adoption_rate:.0f}% · 待回复 {unresponded} · 人均附议 {avg_supporters}",
                    "trend": "↑" if adoption_rate >= 30 else "↓",
                }
                lines.append(f"\n**💡 提案参与**：{total_p} 件 · 待回复 {unresponded} · 已采纳/实施 {adopted}")
                lines.append(f"   人均附议：{avg_supporters} 人")

                # ── 3. Citizen Engagement (公民参与维度) ──
                topic_rows = conn.execute(
                    "SELECT COUNT(*) as cnt, SUM(participant_count) as total_parts FROM discussion_topics"
                ).fetchone()
                total_topics = topic_rows["cnt"] if topic_rows else 0
                total_participants = topic_rows["total_parts"] if topic_rows else 0
                unique_authors_row = conn.execute(
                    "SELECT COUNT(DISTINCT author) as cnt FROM campus_issues"
                ).fetchone()
                unique_authors = unique_authors_row["cnt"] if unique_authors_row else 0

                eng_score = 100.0
                if unique_authors < 3:
                    eng_score -= 30
                elif unique_authors < 5:
                    eng_score -= 15
                if total_participants < 10:
                    eng_score -= 20
                eng_score = max(0, eng_score)
                grades["🗣️ 公民参与"] = {
                    "score": round(eng_score),
                    "detail": f"{unique_authors} 人上报 · {total_participants} 人次参与讨论 · {total_topics} 个议题",
                    "trend": "↑" if unique_authors >= 5 else "→",
                }
                lines.append(f"\n**🗣️ 公民参与**：{unique_authors} 位用户上报问题 · {total_participants} 人次参与议题讨论")

                # ── 4. Hotspot & Risk Indicators ──
                cat_rows = conn.execute(
                    "SELECT category, COUNT(*) as cnt FROM campus_issues "
                    "WHERE status != '已解决' GROUP BY category ORDER BY cnt DESC LIMIT 3"
                ).fetchall()
                if cat_rows:
                    cat_strs = [f"{r['category']}({r['cnt']}件)" for r in cat_rows]
                    lines.append(f"\n**🔥 热点类别**：{'、'.join(cat_strs)}")

            # ── 5. Overall Health ──
            lines.append(f"\n**🏥 治理健康度**：{health['grade']}（{health['score']} 分）")

            # ── 5.5 Report Card Summary ──
            lines.append("\n### 📊 分维度评分")
            for dim, g in grades.items():
                letter = "A" if g["score"] >= 85 else "B" if g["score"] >= 70 else "C" if g["score"] >= 50 else "D"
                lines.append(
                    f"- {dim}：{letter} ({g['score']}分) {g['trend']} — {g['detail']}"
                )

            # ── 6. Action Items (prioritized) ──
            actions: list[tuple[int, str]] = []
            if urgent_unresolved > 0:
                actions.append((10, f"🔴 处理 {urgent_unresolved} 件紧急工单（最高优先）"))
            if unresponded > 0:
                actions.append((8, f"💬 回复 {unresponded} 件待回复提案"))
            if stale_count >= 3:
                actions.append((7, f"⚠️ 清理 {stale_count} 件超7天积压工单"))
            if resolution_rate < 50 and total_i > 5:
                actions.append((5, f"📈 提升解决率（当前仅 {resolution_rate:.0f}%）"))
            if cat_rows and cat_rows[0]["cnt"] >= 5:
                actions.append((4, f"🚀 建议为「{cat_rows[0]['category']}」类问题发起系统性治理提案"))

            if actions:
                actions.sort(key=lambda x: -x[0])
                lines.append("\n### 🎯 优先行动建议")
                for _, action_text in actions[:3]:
                    lines.append(f"- {action_text}")

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Governance audit failed (non-fatal): {e}")
            return f"*治理体检暂时不可用：{e}*"

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
        """Post-hoc association analysis: build reasoning chain + discover insights.

        Called after _reflect() so we work with the cleaned response.
        Uses the Reflector module to parse tool-call traces into a structured
        reasoning chain and compute spatial/temporal/recurrence associations.

        IMPORTANT: We do NOT short-circuit on empty intermediate_steps — the
        reflector has a text-action fallback parser (_parse_text_actions) that
        recovers pseudo-steps from the agent's natural-language response when
        DeepSeek skips formal tool calls. Empty intermediate_steps is exactly
        the case where that fallback matters most.

        Returns the full reasoning chain dict (see agent/reflector.py) or None
        if reflector is unavailable or both steps and text are empty.
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

        Tries to produce a context-aware response based on the user's input intent
        and available DB data, rather than showing a raw error message.
        """
        error_msg = str(error) if error else "未知错误"

        # Try to match common intents and provide helpful guidance
        txt = user_input.strip()

        if any(kw in txt for kw in ("校园脉搏", "动态", "最近发生")):
            try:
                from data.database import get_issues, get_proposals, get_campus_events, get_issues_stats
                stats = get_issues_stats()
                issues = get_issues(status="待处理", limit=5)
                proposals = get_proposals(sort_by="supporters", limit=3)
                events = get_campus_events(limit=3)
                lines = [
                    "🤖 AI 服务暂时繁忙，以下是从数据库直接查询的最新数据：\n",
                    f"📊 **校园脉搏快照**",
                    f"- 工单总数：{stats['total']} 件",
                ]
                by_status = stats.get("by_status", {})
                lines.append(f"- ⏳ 待处理 {by_status.get('待处理',0)} · 🔄 处理中 {by_status.get('处理中',0)} · ✅ 已解决 {by_status.get('已解决',0)}")
                if issues:
                    lines.append("\n🔧 **待处理问题**：")
                    for i in issues[:3]:
                        lines.append(f"- #{i['id']} {i.get('title','')[:30]} [{i.get('category','')}]")
                if proposals:
                    lines.append("\n💡 **热门提案**：")
                    for p in proposals[:3]:
                        lines.append(f"- {p.get('title','')[:30]} · 👍{p.get('supporter_count',0)}")
                if events:
                    lines.append("\n📅 **近期事件**：")
                    for e in events[:3]:
                        lines.append(f"- {e.get('title','')[:40]}")
                return "\n".join(lines)
            except Exception:
                pass

        if any(kw in txt for kw in ("天气", "温度", "下雨", "多少度")):
            try:
                from tools.query_weather import get_today_weather
                days, location, is_real = get_today_weather()
                if days:
                    d = days[0]
                    return (
                        f"🌤️ **{location}** 今日天气（本地查询）\n\n"
                        f"{d['emoji']} {d['condition']} · {d['temp_low']}°C~{d['temp_high']}°C\n"
                        f"💧 降水概率 {d['rain_prob']}% · {d['wind']}\n"
                        f"💡 {d['advice']}"
                    )
            except Exception:
                pass

        if any(kw in txt for kw in ("报修", "上报", "坏了", "故障", "漏水", "不亮")):
            return (
                "🔧 看起来你想报修一个问题。\n\n"
                "AI 服务暂时不可用，但你可以使用页面顶部的 **快速报修** 功能直接提交工单——"
                "填写问题描述和地点，点击「🚀 上报」即可，系统会自动分类。\n\n"
                "或者稍后重试对话，AI 恢复后会帮你处理。"
            )

        if any(kw in txt for kw in ("提案", "建议", "提议")):
            return (
                "💡 看起来你想提交建议或查看提案。\n\n"
                "AI 服务暂时不可用，但你可以在左侧导航中切换到 **🗳️ 有话说** 页面，"
                "那里可以直接查看热门提案和提交新建议。\n\n"
                "稍后重试对话也可以获得 AI 的智能分析。"
            )

        if any(kw in txt for kw in ("治理", "统计", "数据", "健康度")):
            try:
                from data.database import compute_health_score
                health = compute_health_score()
                return (
                    f"🏥 **治理健康度**（本地查询）\n\n"
                    f"- 综合评分：{health['score']} 分（{health['grade']}）\n"
                    f"- 解决率：{health['resolution_rate']}%\n"
                    f"- 趋势：{health['trend']}\n"
                    f"- 近7天新增 {health.get('new_recent', '?')} 件 · 解决 {health.get('resolved_recent', '?')} 件\n\n"
                    f"💡 如需更详细分析，请在 AI 恢复后重试。"
                )
            except Exception:
                pass

        # Generic fallback
        return (
            f"😅 AI 服务暂时不可用（{error_msg[:80]}）。\n\n"
            "你可以尝试以下操作：\n"
            "- 使用页面顶部的 **快速报修** 直接提交工单\n"
            "- 通过左侧导航浏览各功能页面\n"
            "- 稍后重试对话，系统会自动恢复\n\n"
            "如需帮助，请联系管理员。"
        )

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
