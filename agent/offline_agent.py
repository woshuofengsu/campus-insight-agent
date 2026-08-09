# agent/offline_agent.py
"""Offline agent — 无 LLM 依赖，通过规则匹配 + 工具调用生成回复。

用于 OFFLINE_MODE=true 或 ?offline=1 场景。所有回复基于数据库真实数据，
通过模板转化为自然语言响应。
"""
import logging
import random
from agent.memory import MemoryManager
from agent.prompt import detect_persona
from agent.helpers import (
    get_author_identifier, get_user_name, extract_location, random_encouragement,
)

_log = logging.getLogger(__name__)


class OfflineAgent:
    """基于规则的回复路由 —— 调用 tool.invoke()，模板化为自然语言回复。"""

    def __init__(self, session_state):
        self.memory = MemoryManager(session_state)
        from tools import get_tool_names
        self.memory.register_tools(get_tool_names())
        self._last_thinking = ""
        self._last_chain = None
        self._conversation_turns = 0

    def run(self, user_input: str) -> str:
        self.memory.add_message("user", user_input)
        self._last_chain = None
        self._conversation_turns += 1

        persona = detect_persona(user_input)
        response = self._route(persona, user_input)

        if not response:
            response = self._handle_general(user_input)

        self.memory.add_message("assistant", response)
        return response

    def get_last_chain(self) -> dict | None:
        return self._last_chain

    def run_perception_check(self) -> list[dict]:
        return []

    # ── Router ──

    def _route(self, persona: dict | None, txt: str) -> str | None:
        if persona is None:
            return None
        role = persona.get("role", "")

        if "观察员" in role:
            return self._respond_pulse()
        if "数据分析师" in role:
            return self._respond_stats(txt)
        if "报修助手" in role:
            return self._respond_report(txt)
        if "议事顾问" in role:
            return self._respond_proposal(txt)
        return None

    # -- 🌊 校园脉搏 — 综合快报 --

    def _respond_pulse(self) -> str:
        """校园脉搏 — 调用 get_campus_pulse + get_weather，格式化为自然播报。"""
        parts = []

        # ── 天气 ──
        try:
            from tools.query_weather import get_weather
            w = str(get_weather.invoke(""))
            # Extract key weather facts
            parts.append(f"🌤️ {self._extract_weather_line(w)}")
        except Exception:
            _log.debug("get_weather.invoke() failed, trying get_today_weather fallback", exc_info=True)
            from tools.query_weather import get_today_weather
            try:
                days, loc, _ = get_today_weather()
                if days:
                    d = days[0]
                    parts.append(
                        f"🌤️ **{loc}** {d['emoji']} {d['condition']}，"
                        f"{d['temp_low']}°C ~ {d['temp_high']}°C，"
                        f"降水概率 {d['rain_prob']}%"
                    )
            except Exception:
                    _log.debug("get_today_weather fallback also failed", exc_info=True)
                    parts.append("🌤️ 今日天气晴好，适合校园活动~")

        # ── 本周数据 ──
        try:
            from data.database import get_issues_stats, get_proposals, get_issues
            stats = get_issues_stats()
            proposals = get_proposals(sort_by="supporters", limit=4)
            recent = get_issues(limit=6)
            pending = stats["by_status"].get("待处理", 0)
            resolved = stats["by_status"].get("已解决", 0)
            total = stats["total"]

            # Hot categories
            by_cat = stats.get("by_category", {})
            hot_cats = sorted(by_cat.items(), key=lambda x: -x[1])[:3]

            parts.append("")
            parts.append("📡 **本周热点**")
            parts.append(
                f"校园共收到 **{total}** 件问题上报，"
                f"已解决 **{resolved}** 件，**{pending}** 件正在处理中。"
            )

            if hot_cats:
                cat_strs = [f"{c}（{n}件）" for c, n in hot_cats]
                parts.append(f"🔥 最受关注的类别：{'、'.join(cat_strs)}")

            if proposals:
                top = proposals[0]
                parts.append(
                    f"💡 最热提案「**{top.get('title', '')[:28]}**」"
                    f"已有 **{top.get('supporter_count', 0)}** 人附议"
                )

            if recent:
                parts.append("")
                parts.append("📰 **最新动态**")
                for i in recent[:4]:
                    status_icon = {"待处理": "⏳", "处理中": "🔄", "已解决": "✅"}.get(
                        i.get("status", ""), "📌"
                    )
                    parts.append(
                        f"{status_icon} #{i['id']} {i.get('title', '')[:32]} "
                        f"· {i.get('category', '')} · {i.get('reported_at', '')[:10]}"
                    )

        except Exception as e:
            _log.debug("Failed to load stats for _respond_pulse: %s", e)
            parts.append(f"\n📡 *本周数据加载中...（{e}）*")

        parts.append("")
        parts.append(self._random_encouragement("pulse"))
        return "\n".join(parts)

    # -- 📊 治理数据 — 统计 + 分析 --

    def _respond_stats(self, txt: str) -> str:
        """治理统计 — 调用 get_governance_stats，包装为分析报告。"""
        parts = ["📊 **校园治理数据报告**\n"]

        try:
            from tools.query_campus_issues import get_governance_stats
            raw = str(get_governance_stats.invoke(""))
            parts.append(self._reformat_stats(raw))
        except Exception:
            _log.debug("get_governance_stats failed, falling back to DB stats", exc_info=True)
            try:
                from data.database import get_issues_stats
                stats = get_issues_stats()
                parts.append(self._build_stats_from_db(stats))
            except Exception as e:
                _log.debug("DB stats fallback failed: %s", e, exc_info=True)
                parts.append(f"*统计数据暂时无法加载（{e}）*")

        # ── 针对性查询 ──
        cat_map = {
            "设施": "设施维修", "维修": "设施维修", "餐饮": "餐饮问题",
            "卫生": "环境卫生", "环境": "环境卫生", "安全": "安全隐患",
            "网络": "网络服务", "教学": "教学设备", "设备": "教学设备",
            "校园": "校园管理", "管理": "校园管理",
        }
        for kw, cn in cat_map.items():
            if kw in txt:
                try:
                    from tools.query_campus_issues import query_issues
                    result = str(query_issues.invoke({"category": cn, "limit": 5}))
                    parts.append(f"\n🔍 **{cn}类工单详情**\n{self._reformat_issue_list(result)}")
                except Exception:  # best-effort, skip
                    _log.debug("query_issues for category=%r failed", cn, exc_info=True)
                    pass
                break

        parts.append(f"\n💡 {self._random_encouragement('stats')}")
        return "\n".join(parts)

    # -- 🔧 报修 — 创建工单 --

    def _respond_report(self, txt: str) -> str:
        """报修 — 调用 report_issue.invoke()，提取工单号并给出追踪提示。"""
        title = txt[:80]
        location = self._extract_location(txt)

        try:
            from tools.action_report_issue import report_issue
            result = report_issue.invoke({
                "title": title,
                "category": "",
                "location": location,
                "description": txt,
            })
            raw = str(result)

            # Extract issue ID
            import re
            id_match = re.search(r'#(\d+)', raw)
            issue_id = id_match.group(1) if id_match else "?"

            # Extract category and urgency
            cat_match = re.search(r'分类[：:]\s*(\S+)', raw)
            urg_match = re.search(r'紧急程度[：:]\s*(\S+)', raw)
            cat = cat_match.group(1) if cat_match else "设施维修"
            urgency = urg_match.group(1) if urg_match else "普通"

            urg_emoji = {"普通": "🔵", "紧急": "🟠", "极急": "🔴"}.get(urgency, "🔵")

            lines = [
                "✅ **工单已生成！**\n",
                f"📋 工单编号：**#{issue_id}**",
                f"📂 自动分类：{cat}",
                f"{urg_emoji} 紧急程度：{urgency}",
            ]
            if location:
                lines.append(f"📍 位置：{location}")

            lines.append("")
            if urgency in ("紧急", "极急"):
                lines.append(
                    "⚠️ 该问题已标记为紧急，建议同步拨打后勤管理处电话 "
                    "（010-12345690，工作时间）加快处理。"
                )
            else:
                lines.append(
                    "维修/保洁人员会尽快处理。你随时可以输入「**查看我的工单**」追踪进度。"
                )
            lines.append("")
            lines.append(self._random_encouragement("report"))
            return "\n".join(lines)

        except Exception as e:
            import logging
            _log = logging.getLogger(__name__)
            _log.error("report_issue.invoke() failed for title=%r: %s", title, e)
            return (
                f"⚠️ 上报未能完成：{e}\n\n"
                f"请稍后重试，或通过顶部导航「🔧 随手报修」页面手动提交。"
            )

    # -- 💡 提案 — 查看 + 创建引导 --

    def _respond_proposal(self, txt: str) -> str:
        """提案 — 调用 get_proposals + get_topics，展示热门提案。"""
        parts = ["💡 **校园提案与讨论**\n"]

        try:
            from tools.query_proposals import get_proposals
            raw = str(get_proposals.invoke({"sort_by": "supporters", "limit": 5}))
            parts.append(self._reformat_proposal_list(raw))
        except Exception:
            _log.debug("get_proposals tool failed, trying DB fallback", exc_info=True)
            try:
                from data.database import get_proposals as db_props
                props = db_props(sort_by="supporters", limit=5)
                if props:
                    parts.append("🔥 **热门提案 TOP 5**\n")
                    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
                    for i, p in enumerate(props):
                        parts.append(
                            f"{medals[i]} **{p.get('title','')[:30]}** "
                            f"— 👍 {p.get('supporter_count',0)} 人附议 "
                            f"[{p.get('status','讨论中')}]"
                        )
            except Exception as e:
                _log.debug("DB proposals fallback failed: %s", e, exc_info=True)
                parts.append(f"*提案数据暂不可用（{e}）*")

        # ── 议题 ──
        if any(kw in txt for kw in ["议题", "讨论", "话题", "热议"]):
            try:
                from tools.query_topics import get_topics
                raw = str(get_topics.invoke(""))
                parts.append(f"\n💬 **活跃议题**\n{self._reformat_topic_list(raw)}")
            except Exception:  # best-effort, skip
                _log.debug("get_topics failed", exc_info=True)
                pass

        # ── 创建意图 ──
        if any(kw in txt for kw in ["创建", "发起", "提一个", "我想提", "新提案"]):
            parts.append(
                "\n✨ 好的！直接在对话框里告诉我：\n"
                "1. **提案标题**（一句话概括）\n"
                "2. **为什么要提**（背景和理由）\n"
                "3. **你期望的效果**\n\n"
                "我会帮你创建提案并发布到「🗳️ 有话说」页面~"
            )

        parts.append(f"\n{self._random_encouragement('proposal')}")
        return "\n".join(parts)

    # -- 🤔 通用 — 未匹配到具体意图 --

    def _handle_general(self, txt: str) -> str:
        """Fallback：未匹配任何 persona 时的通用回复。"""

        # ── 感谢/正向反馈（必须在问候之前检查）──
        if any(kw in txt for kw in ["谢谢", "感谢", "太好了", "很棒", "不错", "厉害"]):
            return random.choice([
                "😊 不客气！能帮到你我也很开心~校园因为你的参与变得更好了一点 ✨",
                "🙏 谢谢你的反馈！有任何校园问题随时找我~",
                "💪 一起让校园变得更好！有什么需要随时叫我~",
            ])

        # ── 打招呼 ──
        greetings = [
            "你好", "嗨", "hello", "hi", "在吗", "你是", "你是谁",
            "帮忙", "什么是", "怎么用", "介绍一下",
        ]
        if any(g in txt.lower() for g in greetings):
            name = self._get_name()
            greeting = random.choice([
                f"👋 嗨！{'📛 ' + name + '，' if name else ''}欢迎回到校园先知~",
                f"你好呀！{'📛 ' + name + '，' if name else ''}今天有什么可以帮你的？",
                f"Hi there！{'📛 ' + name + '，' if name else ''}校园先知在线中~",
            ])
            return (
                f"{greeting}\n\n"
                f"我是校园先知，围绕 **知·报·议·督** 四字闭环运行：\n\n"
                f"🌊 **知** · 输入「**校园脉搏**」看本周校园动态\n"
                f"🔧 **报** · 发现设施问题？直接告诉我，我帮你上报\n"
                f"🗳️ **议** · 有想法？说「**我有个提案**」参与校园建设\n"
                f"📊 **督** · 输入「**治理数据**」查看全局统计\n\n"
                f"想了解什么？试试上面任意一个~"
            )

        # ── 查看工单意图 ──
        if any(kw in txt for kw in ["我的工单", "我的上报", "我上报的", "查看工单"]):
            return self._my_issues()

        # ── 查看我的提案意图 ──
        if any(kw in txt for kw in ["我的提案", "我提的", "我提议"]):
            return self._my_proposals()

        # ── 真正的兜底 ──
        hints = [
            "🌊 输入「校园脉搏」看本周热点",
            "🔧 直接描述问题，如「教三楼灯坏了」",
            "📊 输入「治理数据」看统计",
            "💡 输入「有什么提案」看热门建议",
        ]
        random.shuffle(hints)
        return (
            f"🤔 收到你的消息。以下是我可以帮你做的事情：\n\n"
            + "\n".join(f"- {h}" for h in hints[:4])
            + "\n\n你想试试哪个？"
        )

    # -- 👤 我的 — 个人工单/提案追踪 --

    def _my_issues(self) -> str:
        """查看我的工单。"""
        author = self._get_author_identifier()
        if not author:
            return "😅 无法确认你的身份。请先在「👤 我的」页面完善个人信息~"
        try:
            from data.database import get_issues
            all_issues = get_issues(limit=200)
            mine = [
                i for i in all_issues
                if i.get("author") == author
            ]
            if not mine:
                return f"📋 你还没有上报过问题。发现校园设施问题？直接描述，我帮你上报！"

            pending = [i for i in mine if i.get("status") in ("待处理", "处理中")]
            resolved = [i for i in mine if i.get("status") == "已解决"]

            lines = [f"📋 **你的工单**（共 {len(mine)} 件）\n"]
            if pending:
                lines.append(f"⏳ **处理中（{len(pending)} 件）**")
                for i in pending[:5]:
                    lines.append(
                        f"  #{i['id']} {i.get('title','')[:30]} "
                        f"[{i.get('status','')}] · {i.get('reported_at','')[:10]}"
                    )
            if resolved:
                lines.append(f"\n✅ **已解决（{len(resolved)} 件）**")
                for i in resolved[:3]:
                    lines.append(
                        f"  #{i['id']} {i.get('title','')[:30]} "
                        f"· 解决于 {(i.get('resolved_at') or '')[:10]}"
                    )
            if pending:
                lines.append(f"\n💡 有 {len(pending)} 件还在处理中，我会持续追踪~")
            return "\n".join(lines)
        except Exception as e:
            _log.debug("my_issues query failed: %s", e, exc_info=True)
            return f"📋 工单查询暂时不可用（{e}），请稍后重试。"

    def _my_proposals(self) -> str:
        """查看我的提案。"""
        author = self._get_author_identifier()
        if not author:
            return "😅 无法确认你的身份。请先在「👤 我的」页面完善个人信息~"
        try:
            from data.database import get_proposals
            all_props = get_proposals(limit=200)
            mine = [p for p in all_props if p.get("author") == author]
            if not mine:
                return "💡 你还没有提交过提案。有想法？直接告诉我，我帮你创建！"

            lines = [f"💡 **你的提案**（共 {len(mine)} 件）\n"]
            for p in mine:
                status_icon = {
                    "讨论中": "💬", "已回应": "📝",
                    "已采纳": "✅", "已实施": "🎉",
                }.get(p.get("status", ""), "📌")
                lines.append(
                    f"{status_icon} **{p.get('title','')[:30]}** "
                    f"— 👍 {p.get('supporter_count', 0)} 人 [{p.get('status','')}]"
                )
                if p.get("response_text"):
                    lines.append(f"  💬 回复：{p['response_text'][:100]}")
            return "\n".join(lines)
        except Exception as e:
            _log.debug("my_proposals query failed: %s", e, exc_info=True)
            return f"💡 提案查询暂时不可用（{e}），请稍后重试。"

    # -- Helpers --

    def _get_name(self) -> str:
        return get_user_name(self.memory)

    def _get_author_identifier(self) -> str:
        return get_author_identifier(self.memory)

    def _extract_location(self, txt: str) -> str:
        return extract_location(txt)

    def _extract_weather_line(self, weather_text: str) -> str:
        """从 get_weather 输出中提取一行天气摘要。"""
        for line in weather_text.split("\n"):
            line = line.strip()
            if any(kw in line for kw in ["°C", "℃", "度", "晴", "雨", "云", "风", "温度"]):
                # Clean up tool output formatting
                cleaned = line.replace("**", "").strip("·- ")
                if len(cleaned) > 10:
                    return cleaned
        return weather_text[:120]

    def _reformat_stats(self, raw: str) -> str:
        """将 get_governance_stats 的原始输出重新排版为更自然的格式。"""
        # Extract key numbers
        import re
        total_m = re.search(r'总数[：:]\s*(\d+)', raw)
        pending_m = re.search(r'待处理[：:]\s*(\d+)', raw)
        resolved_m = re.search(r'已解决[：:]\s*(\d+)', raw)
        processing_m = re.search(r'处理中[：:]\s*(\d+)', raw)
        health_m = re.search(r'健康度[：:]\s*(.+?)(?:\n|$)', raw)

        lines = []
        if total_m:
            total = int(total_m.group(1))
            pending = int(pending_m.group(1)) if pending_m else 0
            resolved = int(resolved_m.group(1)) if resolved_m else 0
            processing = int(processing_m.group(1)) if processing_m else 0

            rate = resolved / total * 100 if total > 0 else 0
            lines.append(
                f"📝 累计上报 **{total}** 件 | ⏳ 待处理 **{pending}** 件 | "
                f"🔄 处理中 **{processing}** 件 | ✅ 已解决 **{resolved}** 件"
            )
            lines.append(f"🏥 解决率：**{rate:.0f}%**")

        if health_m:
            lines.append(f"📊 治理健康度：{health_m.group(1).strip()}")

        # Category breakdown
        cat_section = re.findall(r'([🔧🧹⚠💻🌐🍽📌]\S+)[：:]\s*(\d+)', raw)
        if cat_section:
            lines.append("\n📂 **分类分布**")
            for icon_name, count in cat_section[:6]:
                lines.append(f"  {icon_name}：{count} 件")

        return "\n".join(lines) if lines else raw[:600]

    def _reformat_issue_list(self, raw: str) -> str:
        """简化工单列表的展示。"""
        lines = []
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("#") and "📝" in line:
                # Extract and simplify
                import re
                id_m = re.search(r'#(\d+)', line)
                title_m = re.search(r'📝\s*(.+?)(?:\n|$)', line)
                if id_m and title_m:
                    lines.append(f"  #{id_m.group(1)} {title_m.group(1)[:40]}")
        return "\n".join(lines[:5]) if lines else raw[:400]

    def _reformat_proposal_list(self, raw: str) -> str:
        """简化提案列表。"""
        lines = []
        for line in raw.split("\n"):
            line = line.strip()
            if "📝" in line and any(kw in line for kw in ["附议", "👍"]):
                lines.append(f"  {line[:80]}")
        return "\n".join(lines[:5]) if lines else raw[:400]

    def _reformat_topic_list(self, raw: str) -> str:
        """简化议题列表。"""
        lines = []
        for line in raw.split("\n"):
            line = line.strip()
            if line and not line.startswith("#") and len(line) > 5:
                lines.append(f"  💬 {line[:80]}")
        return "\n".join(lines[:4]) if lines else raw[:300]

    def _build_stats_from_db(self, stats: dict) -> str:
        """直接从 DB stats dict 构建统计报告。"""
        total = stats["total"]
        by_status = stats.get("by_status", {})
        pending = by_status.get("待处理", 0)
        processing = by_status.get("处理中", 0)
        resolved = by_status.get("已解决", 0)
        rate = resolved / total * 100 if total > 0 else 0

        lines = [
            f"📝 累计上报 **{total}** 件",
            f"⏳ 待处理 **{pending}** 件 · 🔄 处理中 **{processing}** 件 · ✅ 已解决 **{resolved}** 件",
            f"🏥 解决率：**{rate:.0f}%**",
        ]

        by_cat = stats.get("by_category", {})
        if by_cat:
            lines.append("\n📂 **分类分布**")
            for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"  {cat}：{cnt} 件")
        return "\n".join(lines)

    def _random_encouragement(self, context: str = "") -> str:
        return random_encouragement(context)
