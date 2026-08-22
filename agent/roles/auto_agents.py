# agent/roles/auto_agents.py
"""自动/后台角色 Agent：天气守护员（自动监测）+ 网格员工作助手（负责人）。"""

from agent import web_agent as A
from agent.roles.base import BaseAgent


# ---------------------------------------------------------------------------
# 天气守护员（自动运行；不自动执行应急措施）
# ---------------------------------------------------------------------------

class WeatherGuardianAgent(BaseAgent):
    key = "weather_guardian"
    name = "天气守护员"
    icon = "🌤️"
    role_desc = "监测天气，触发预警，联动健康与通知（自动运行）"
    audience = "自动"
    human_stop = "不自动执行应急措施（拨号/撤离等）"
    tools_whitelist = ["db_weather.get_weather_for_display", "db_weather.get_active_alerts"]

    def process(self, ctx: dict) -> dict:
        """天气查询（用户问）或自动预警检查（调度器调）。返回天气 + 生活建议 + 预警。"""
        from agent.web_agent_service import _exec_weather
        text = ctx.get("user_input") or ""
        r_text, status, _ = _exec_weather(text)
        # 预警标签（若当前生效预警）→ 主动协商：通知健康顾问与通知管理员
        try:
            from data.db_weather import get_active_alerts
            alerts = get_active_alerts()
            if alerts:
                tags = "、".join(f"{a.get('alert_type')}{a.get('level')}" for a in alerts[:3])
                r_text += f"\n\n🚨 当前预警：{tags}"
                # 事件触发协商：极端天气 → 健康顾问（健康提醒）+ 通知管理员（通知）
                self._post("health_advisor", "notify", {
                    "event": "extreme_weather", "tags": tags,
                    "suggestion": "提醒老人注意保暖/防暑/减少外出",
                })
                self._post("notification_manager", "notify", {
                    "event": "extreme_weather", "tags": tags,
                })
                self.bb.write("weather_alert", {"tags": tags, "at": self.bb.history[-1]["timestamp"] if self.bb.history else ""},
                              self.key)
        except Exception:
            pass
        tip = A.weather_tip(text)
        if tip and tip not in r_text:
            r_text += f"\n💬 {tip}"
        return self._reply(r_text, status, "天气守护员", chain_note="查询天气并附带预警与生活建议")

    def process_negotiation(self, msg: dict) -> dict | None:
        """天气守护员处理协商（如通知管理员的预警解除确认等）；默认不响应。"""
        return None


# ---------------------------------------------------------------------------
# 网格员工作助手（负责人；不代替审批）
# ---------------------------------------------------------------------------

class GridAssistantAgent(BaseAgent):
    key = "grid_assistant"
    name = "网格员工作助手"
    icon = "🛠️"
    role_desc = "搜索、导出、统计、待办提醒、页面跳转"
    audience = "负责人"
    human_stop = "不代替审批；导出/看手机号需二次确认"
    tools_whitelist = ["db_repair.get_issues", "db_policy.get_frequency_stats",
                       "db_repair.get_overdue_issues", "导出/跳转"]

    def process(self, ctx: dict) -> dict:
        from agent.web_agent_service import _grid_todos, _grid_stats, _grid_search
        text = ctx.get("user_input") or ""
        intent = ctx.get("intent") or "grid"
        st = ctx.get("state") or {}

        # 导出确认续接（停机点：导出需负责人确认）
        if st.get("pending_export"):
            st.pop("pending_export", None)
            if text in ("确认", "确认导出", "确定"):
                return self._reply("已生成脱敏报表，点击下方按钮下载。", "成功", "导出数据",
                                   actions=[{"type": "download", "url": "/api/web/export/issues",
                                             "label": "下载工单报表"}],
                                   chain_note="负责人已确认，生成脱敏导出")
            return self._reply("已取消导出。", "已取消", "导出数据", chain_note="负责人取消导出")

        # 人工处理包（无缝转人工：AI 已整理上下文，可直接处理）
        if any(k in text for k in ("处理包", "人工待办", "转人工的")):
            from data.db_agent import list_handoffs
            rows = list_handoffs(status="待处理", limit=10)
            if not rows:
                return self._reply("当前没有待处理的人工处理包。", "成功", "网格员工作助手",
                                   chain_note="查询人工处理包（空）")
            lines = []
            for h in rows:
                pkg = h.get("package") or {}
                lines.append(f"· #{h['id']} [{h.get('intent')}] {pkg.get('original_input', '')[:30]}"
                             f"（{h.get('reason', '')[:20]}）")
            return self._reply("🤝 待处理人工包（AI 已整理上下文）：\n" + "\n".join(lines),
                               "成功", "网格员工作助手",
                               actions=[{"type": "navigate", "to": "/grid/messages", "label": "去消息中心处理"}],
                               chain_note="返回人工处理包列表（含上下文摘要）")

        if intent in ("待办提醒", "grid") and any(k in text for k in ("待办", "超时", "今天要做什么", "要处理", "待处理")):
            r_text, status, _ = _grid_todos()
            return self._reply(r_text, status, "待办提醒",
                               actions=[{"type": "navigate", "to": "/grid/work-orders", "label": "跳转处理工单"},
                                        {"type": "navigate", "to": "/grid/health", "label": "处理咨询"}],
                               chain_note="统计待办并标记超时")
        if intent == "导出数据" or ("导出" in text or "报表" in text or "下载" in text):
            ctx["state"]["pending_export"] = True
            return self._reply("确认导出数据报表？（将生成脱敏文件）", "需确认", "导出数据",
                               actions=[{"type": "buttons", "options": ["确认导出", "取消"]}],
                               chain_note="停机点：导出需负责人确认")
        if intent == "统计查询" or ("统计" in text or "多少" in text or "本周" in text or "本月" in text):
            r_text, status, _ = _grid_stats(text)
            return self._reply(r_text, status, "统计查询", chain_note="返回统计数字")
        if intent == "搜索资料" or ("查一下" in text or "搜索" in text or "帮我查" in text):
            kw = text.replace("查一下", "").replace("搜索", "").replace("找一下", "").replace("帮我查", "").strip()
            r_text, status, _ = _grid_search(kw or text)
            return self._reply(r_text, status, "搜索资料",
                               actions=[{"type": "navigate", "to": "/grid/work-orders", "label": "去工单页"}],
                               chain_note="按关键词检索工单/提案/知识库")
        if intent == "页面跳转" or ("打开" in text or "跳转" in text or "去" in text):
            to = "/grid/dashboard"
            if "工单" in text or "审核" in text:
                to = "/grid/work-orders"
            elif "提案" in text:
                to = "/grid/proposals"
            elif "通知" in text:
                to = "/grid/notices"
            elif "天气" in text:
                to = "/grid/weather"
            elif "健康" in text or "咨询" in text:
                to = "/grid/health"
            elif "老年" in text:
                to = "/grid/elderly-care"
            return self._reply("正在为您打开页面。", "成功", "页面跳转",
                               actions=[{"type": "navigate", "to": to, "label": "已打开"}],
                               chain_note="按关键词跳转页面")
        return self._reply(A.unknown_reply("grid"), "成功", "网格员工作助手",
                           actions=[{"type": "buttons", "options": A.quick_entries("grid")}],
                           chain_note="未识别，展示快捷指令")
