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
            logger.warning("没发现任何工具，Agent 只能纯聊天了")

        self._last_thinking = ""   # 上一次回复里抽出来的思考块
        self._last_chain = None    # 上一次运行的结构化推理链（给 UI 用）

        logger.info(f"CommunityAgent 初始化完成，共 {len(self.tools)} 个工具")

    def _create_llm(self) -> ChatOpenAI:
        """初始化 DeepSeek 模型"""
        if not DEEPSEEK_API_KEY:
            raise ValueError(
                "未设置 DEEPSEEK_API_KEY，请把 .env.example 复制成 .env 并填入你的 key。\n"
                "配置好后重启应用即可生效。"
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
            return_intermediate_steps=True,   # 记录工具调用轨迹，推理链可视化要用
        )

    # OODA 主循环

    def run(self, user_input: str) -> str:
        """跑一轮完整 OODA：观察 → 定位 → 决策+执行 → 反思 → 关联。

        接口抖动会退避重试，最多 2 次。
        """
        try:
            return self._run_impl(user_input)
        except Exception as e:
            logger.error("致命错误：run() 崩了：%s", e, exc_info=True)
            try:
                self._last_chain = None
                self.memory.add_message("assistant",
                    f"😅 抱歉，系统遇到了一点问题。\n\n"
                    f"> 错误：{e}\n\n"
                    f"请稍后重试，或通过页面顶部的「⚡ 快速报修」直接提交工单。"
                )
            except Exception:  # 兜底：绝不能把整个应用搞崩
                logger.debug("兜底消息写进记忆失败", exc_info=True)
                pass
            return (
                f"😅 抱歉，系统遇到了一点问题。\n\n"
                f"> 错误：{e}\n\n"
                f"请稍后重试，或通过页面顶部的「⚡ 快速报修」直接提交工单。"
            )

    def _run_impl(self, user_input: str) -> str:
        """run() 的真正实现，外面套一层是为了防崩溃。"""
        # 清掉上一轮的推理链
        self._last_chain = None

        # 先把用户消息存进记忆
        self.memory.add_message("user", user_input)

        max_retries = 2
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # 阶段 1：观察
                environment = self._observe()

                # 阶段 2：定位
                oriented_input = self._orient(user_input, environment)

                # 阶段 3：决策 + 执行
                raw_response, intermediate_steps = self._decide_and_act(oriented_input, environment)

                # 阶段 4：反思
                response = self._reflect(raw_response, user_input, environment,
                                         intermediate_steps)

                # 阶段 5：关联（事后分析）
                self._last_chain = self._associate(intermediate_steps, response, user_input)

                # 成功，存回复并返回
                if response:
                    self.memory.add_message("assistant", response)
                return response

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 判断错误能不能重试
                is_retryable = any(kw in error_msg.lower() for kw in (
                    "timeout", "connection", "rate limit", "server error",
                    "internal error", "service unavailable", "overloaded",
                    "too many requests", "429", "500", "502", "503", "504",
                ))

                if is_retryable and attempt < max_retries:
                    import time
                    wait = (attempt + 1) * 1.5  # 退避等待：1.5s、3s，逐次加倍
                    logger.warning(
                        f"Agent 可重试错误（第 {attempt+1}/{max_retries+1} 次尝试），"
                        f"等 {wait}s 再试：{error_msg[:120]}"
                    )
                    time.sleep(wait)
                    continue
                else:
                    logger.error(
                        f"Agent 执行出错（第 {attempt+1} 次尝试）：{error_msg[:200]}"
                    )
                    break

        # 重试都失败了，交给离线 Agent 兜底
        self._last_chain = None

        # 离线 Agent 走规则路由调真工具，比关键词兜底强得多；
        # 不走 offline.run() 是因为用户消息在上面已经存过，避免重复。
        try:
            from agent.offline_agent import OfflineAgent
            from agent.prompt import detect_persona
            offline = OfflineAgent(st.session_state)
            offline.memory = self.memory
            persona = detect_persona(user_input)
            fallback = offline._route(persona, user_input)
            if not fallback:
                fallback = offline._handle_general(user_input)
            logger.info("LLM 失败后转交给 OfflineAgent，共 %d 字", len(fallback))
        except Exception:
            logger.warning("转交 OfflineAgent 失败，改用静态兜底", exc_info=True)
            try:
                fallback = self._graceful_fallback(user_input, last_error)
            except Exception:
                logger.debug("静态兜底也失败了", exc_info=True)
                fallback = f"😅 智能服务暂时不可用，请稍后重试或使用页面顶部的「⚡ 快速报修」。"
        try:
            self.memory.add_message("assistant", fallback)
        except Exception:  # 尽力而为，存不上就算了
            logger.debug("兜底消息保存进记忆失败", exc_info=True)
            pass
        return fallback

    # OODA 各阶段的具体实现

    def _observe(self) -> dict:
        """阶段 1 观察：收集环境上下文。

        跑一遍感知检查（天气、问题热点、已解决事项），再带上时间信息，
        返回一个结构化的环境字典。这里的感知提醒只给 Agent 当上下文，
        不会单独当成聊天消息发出去。
        """
        from perception.monitor import PerceptionMonitor

        monitor = PerceptionMonitor()
        alerts = monitor.run_all_checks()

        now = datetime.now()
        weekday = ["周一","周二","周三","周四","周五","周六","周日"][now.weekday()]

        # 判断现在是哪个时段
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

        # 看看哪些类别的问题积压多（治理热点）
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
            logger.debug("观察阶段加载热门分类失败", exc_info=True)
            hot_categories = []

        return {
            "timestamp": now.isoformat(),
            "weekday": weekday,
            "time_context": time_ctx,
            "alerts": alerts,                 # 感知提醒列表
            "alert_count": len(alerts),
            "hot_categories": hot_categories,  # 治理热点
        }

    def _orient(self, user_input: str, environment: dict) -> str:
        """阶段 2 定位：把角色和环境上下文塞进用户输入里。

        前缀一层层叠在用户消息前面（用户自己看不见）：
        1. 角色上下文 —— 按人设给的语气和关注点提示（来自 detect_persona）
        2. 情境上下文 —— 时间、天气、热点类别、提醒

        Agent 最终看到的是：[角色] [情境] [用户消息]
        """
        parts = []

        # 第一层：角色路由，给 Agent 戴上这轮的"帽子"
        persona = detect_persona(user_input)
        if persona:
            parts.append(
                f"【角色模式：{persona['role']}】{persona['focus_hint']}"
            )

        # 1.5 层：语义工具路由，提示这轮该用哪个工具
        # （语义路由 + 关键词兜底）。prompt 触发词表没覆盖到的说法，
        # 靠它也能指对工具。
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
            logger.debug("语义工具路由跳过（不影响）", exc_info=True)

        # 1.6 层：复杂问题先给个分步计划
        try:
            from agent.planner import plan_steps
            steps = plan_steps(user_input)
            if steps:
                parts.append("【建议步骤计划】" + " → ".join(steps))
        except Exception:
            logger.debug("规划跳过（不影响）", exc_info=True)

        # 1.7 层：个人事件记忆，注入"你最近..."保持连续性
        try:
            uid = self.memory.user_id
            from data.db_memory import get_event_summary
            summary = get_event_summary(uid, limit=3)
            if summary:
                parts.append(f"【与你相关】你最近：{summary}")
        except Exception:
            logger.debug("事件记忆注入跳过（不影响）", exc_info=True)

        # 第二层：时间
        parts.append(
            f"现在是{environment['weekday']}{environment['time_context']}。"
        )

        # 第三层：治理热点
        if environment.get("hot_categories"):
            hot_strs = [
                f"{h['category']}({h['count']}件待处理)" for h in environment["hot_categories"]
            ]
            parts.append(f"治理热点：{'、'.join(hot_strs)}。")

        # 第四层：感知提醒（截断，最多 3 条）
        if environment["alerts"]:
            alert_summaries = [
                f"{a['emoji']}{a['title']}" for a in environment["alerts"][:3]
            ]
            parts.append(f"当前提醒：{'、'.join(alert_summaries)}。")

        # 拼装：上下文放前面，用户消息跟在后面
        if parts:
            context_prefix = "【情境感知】" + " ".join(parts) + "\n"
            return context_prefix + "【用户消息】" + user_input

        return user_input

    def _decide_and_act(self, oriented_input: str, environment: dict) -> tuple[str, list]:
        """阶段 3 决策+执行：LangChain Agent 自己推理并调工具。

        它拿到带上下文的 oriented_input，决定调哪些工具、执行，
        最后生成回复。流式回调会实时把工具执行事件推给 UI，
        用来显示"正在调用工具"的指示。

        返回：
            (output_text, intermediate_steps) —— intermediate_steps 是
            LangChain 的原始工具调用轨迹：list[tuple[AgentAction, str]]
        """
        # Plan-and-Execute 快路径：规则模板直接执行复合查询 + LLM 汇总
        raw_user = oriented_input.split("【用户消息】")[-1] if "【用户消息】" in oriented_input else oriented_input
        try:
            from agent.planner import execute_plan_steps
            plan_results = execute_plan_steps(raw_user)
            if plan_results:
                summary = self._summarize_plan(plan_results, raw_user)
                if summary:
                    return summary, []  # 走了规划执行，无 AgentExecutor 步骤
        except Exception:
            logger.debug("计划-执行快路径跳过", exc_info=True)

        executor = self._build_agent(
            environment_context=self._format_environment_for_prompt(environment)
        )

        # 有 session_state 就挂上流式回调
        callbacks = []
        try:
            from agent.callbacks import StreamingCallback
            # 用初始化 Agent 时同一个 session_state
            st_state = self.memory.st
            if hasattr(st_state, '_stream_events') or isinstance(st_state, dict):
                callback = StreamingCallback(st_state)
                callbacks.append(callback)
                self._last_callback = callback
        except Exception as e:
            logger.debug(f"StreamingCallback 配置跳过（不影响）：{e}")
            self._last_callback = None

        invoke_kwargs: dict = {"input": oriented_input}
        if callbacks:
            invoke_kwargs["config"] = {"callbacks": callbacks}

        result = executor.invoke(invoke_kwargs)
        output = result.get("output", "")
        steps = result.get("intermediate_steps", [])
        return output, steps

    def _summarize_plan(self, plan_results: list[dict], user_input: str) -> str | None:
        """LLM 汇总 Plan-and-Execute 的执行结果，失败了就算了。"""
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
            logger.debug("计划总结失败", exc_info=True)
            return None

    def _reflect(self, raw_response: str, user_input: str, environment: dict,
                 intermediate_steps: list | None = None) -> str:
        """阶段 4 反思：对回复做一轮校验。

        一共七道检查：剥掉思考标签、拦空回复、确认提醒有没有回应、
        回复够不够深入、闭环完整性、是否触发治理体检、防幻觉的工具调用兜底。
        """
        # 4.0：先抽思考块，再做别的处理
        cleaned, thinking = split_thinking(raw_response)
        self._last_thinking = thinking

        # 第 3 类：整行都是工具调用轨迹（LangChain verbose 泄漏出来的）
        cleaned = "\n".join(
            line for line in cleaned.split("\n")
            if not any(line.strip().startswith(p) for p in (
                "Invoking:", "Entering new", "Finished chain", "> Entering",
                "> Finished", "Thought:", "Action:", "Observation:",
            ))
        ).strip()

        # 压缩连续空行（上面过滤行时可能弄出来的）
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

        raw_response = cleaned
        if not raw_response or not raw_response.strip():
            return "😅 抱歉，我没能生成有效的回复。请换个方式描述你的需求试试？"

        # 4.1：高优先级提醒没被回复提到
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

        # 4.2：复杂问题回得太短
        complex_keywords = ["分析", "对比", "汇总", "统计", "治理", "提案", "议题", "民意"]
        is_complex = any(kw in user_input for kw in complex_keywords)
        if is_complex and len(raw_response) < 80:
            raw_response += (
                "\n\n🤔 以上是简要回答。如果需要更详细的分析或方案，"
                "可以告诉我更多细节，我再帮你深入看看~"
            )

        # 4.3：闭环完整性检查
        # 找有没有"悬着"的治理闭环：用户没解决的问题、过期提案、
        # 反复出现的问题。只追加提醒，不拦回复。
        loop_note = self._check_closed_loop(user_input, raw_response)
        if loop_note:
            raw_response += loop_note

        # 4.4：触发治理体检
        # 用户要全面检查时，跨表跑一轮综合分析
        audit_keywords = ["审计", "全面检查", "治理体检", "综合分析", "整体情况"]
        if any(kw in user_input for kw in audit_keywords):
            audit_note = self._governance_audit()
            if audit_note:
                raw_response += "\n\n---\n\n🏥 **治理体检报告**\n\n" + audit_note

        # 4.5：工具调用兜底（防幻觉）
        # 用户明明要报修，LLM 却没真调 report_issue（自己脑补了确认），
        # 这里强制走真工具，把假回复换掉。
        raw_response = self._enforce_tool_call(raw_response, user_input,
                                                intermediate_steps)

        # 4.6：事实核查（防幻觉第二道）
        # 编号存在性（正则护栏）+ LLM 数值/语义一致性核查（主防线）。
        raw_response = self._verify_facts(raw_response, intermediate_steps)

        return raw_response

    def _verify_facts(self, response: str, intermediate_steps: list | None = None) -> str:
        """拿工具返回结果核对回复里引用的数据，实现在 agent/reflection.py。"""
        from agent.reflection import reflect
        return reflect(response, intermediate_steps)

    def _enforce_tool_call(self, response: str, user_input: str,
                           intermediate_steps: list | None) -> str:
        """兜底：报修意图必须真调 report_issue。

        实现在 agent/enforce.py，细节看 enforce_tool_call()。
        """
        from agent.enforce import enforce_tool_call
        return enforce_tool_call(response, user_input, intermediate_steps)

    def _check_closed_loop(self, user_input: str, response: str) -> str:
        """查有没有没闭环的治理事项，返回一句温和的提醒。

        实现在 agent/closed_loop.py，细节看 check_closed_loop()。
        """
        from agent.closed_loop import check_closed_loop
        return check_closed_loop(self.memory, user_input, response)

    def _governance_audit(self) -> str:
        """跑治理体检，实现在 governance_audit 模块。

        从 engine.py 拆出来的（v2 报告卡：分维度打分、趋势箭头、
        排好优先级的行动项）。完整实现和评分方法看 agent/governance_audit.py。
        """
        from agent.governance_audit import run_governance_audit
        return run_governance_audit()

    def _format_environment_for_prompt(self, environment: dict) -> str:
        """把环境上下文压成一段字符串，塞进 system prompt。"""
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
        """事后关联分析：拼推理链、找模式。

        DeepSeek 不按格式调工具时，会用文本解析兜底，
        所以 intermediate_steps 为空也能继续处理。返回 dict 或 None。
        """
        try:
            from agent.reflector import build_reasoning_chain
            # 无条件调 build_reasoning_chain——空 intermediate_steps 它也能
            # 用文本解析兜底 + 最后一步反思处理掉。
            chain = build_reasoning_chain(intermediate_steps, raw_response, user_input)
            n_steps = len(chain.get('steps', []))
            assoc = chain.get('associations') or {}
            has_insight = assoc.get('has_insight', False) if isinstance(assoc, dict) else False
            logger.info(
                f"推理链构建完成：{n_steps} 步，"
                f"关联={'有' if has_insight else '无'}"
            )
            # 只有真没啥可展示时才返回 None
            if not chain or (not chain.get("steps") and not has_insight):
                return None
            return chain
        except ImportError:
            logger.warning("agent.reflector 不可用，跳过关联分析")
            return None
        except Exception as e:
            logger.warning(f"关联分析失败（非致命）：{e}")
            return None

    def _graceful_fallback(self, user_input: str, error: Exception | None = None) -> str:
        """Agent 重试后还是失败时，给一句体面的兜底回复。

        实现在 agent/fallback.py，细节看 graceful_fallback()。
        """
        from agent.fallback import graceful_fallback
        return graceful_fallback(user_input, error)

    def get_last_chain(self) -> dict | None:
        """返回最近一次 run() 的结构化推理链，给 UI（home.py）渲染思考过程用。

        还没跑过或上轮没调工具时返回 None。
        """
        return self._last_chain

    # 对外接口：给外部感知触发用的

    def run_perception_check(self) -> list[dict]:
        """跑感知检查，返回新出现的提醒。

        app.py 空闲时主动提醒用的（和每轮 OODA 的观察阶段分开）。
        """
        environment = self._observe()
        alerts = environment.get("alerts", [])

        # 过滤掉最近已经提醒过的
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
