# agent/fallback.py
"""Graceful fallback — data-backed responses when the LLM is unavailable.

Produces helpful, context-aware responses directly from the database.
"""
import logging

_log = logging.getLogger(__name__)


def graceful_fallback(user_input: str, error: Exception | None = None) -> str:
    """Return a context-aware fallback response using DB data."""
    error_msg = str(error) if error else "未知错误"
    txt = user_input.strip()

    # ── Pulse intent ──
    if any(kw in txt for kw in ("校园脉搏", "动态", "最近发生")):
        try:
            from data.database import get_issues, get_proposals, get_campus_events, get_issues_stats
            stats = get_issues_stats()
            issues = get_issues(status="待处理", limit=5)
            proposals = get_proposals(sort_by="supporters", limit=3)
            events = get_campus_events(limit=3)
            lines = [
                "🤖 智能服务暂时繁忙，以下是从数据库直接查询的最新数据：\n",
                f"📊 **校园脉搏快照**",
                f"- 工单总数：{stats['total']} 件",
            ]
            by_status = stats.get("by_status", {})
            lines.append(
                f"- ⏳ 待处理 {by_status.get('待处理',0)} · "
                f"🔄 处理中 {by_status.get('处理中',0)} · "
                f"✅ 已解决 {by_status.get('已解决',0)}"
            )
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
            _log.debug("Pulse fallback query failed", exc_info=True)

    # ── Weather intent ──
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
            _log.debug("Weather fallback query failed", exc_info=True)

    # ── Repair intent ──
    if any(kw in txt for kw in ("报修", "上报", "坏了", "故障", "漏水", "不亮")):
        return (
            "🔧 看起来你想报修一个问题。\n\n"
            "智能服务暂时不可用，但你可以使用页面顶部的 **快速报修** 功能直接提交工单——"
            "填写问题描述和地点，点击「上报」提交，系统自动分类。\n\n"
            "或者稍后重试对话，服务恢复后会帮你处理。"
        )

    # ── Proposal intent ──
    if any(kw in txt for kw in ("提案", "建议", "提议")):
        return (
            "看起来你想提交建议或查看提案。\n\n"
            "智能服务暂时不可用，但你可以在左侧导航中切换到 **🗳️ 有话说** 页面，"
            "那里可以直接查看热门提案和提交新建议。\n\n"
            "稍后重试对话也可以获得完整的智能分析。"
        )

    # ── Health/stats intent ──
    if any(kw in txt for kw in ("治理", "统计", "数据", "健康度")):
        try:
            from data.database import compute_health_score
            health = compute_health_score()
            return (
                f"🏥 **治理健康度**（本地查询）\n\n"
                f"- 综合评分：{health['score']} 分（{health['grade']}）\n"
                f"- 解决率：{health['resolution_rate']}%\n"
                f"- 趋势：{health['trend']}\n"
                f"- 近7天新增 {health.get('new_recent', '?')} 件 · "
                f"解决 {health.get('resolved_recent', '?')} 件\n\n"
                f"如需更详细分析，请在服务恢复后重试。"
            )
        except Exception:
            _log.debug("Health score fallback query failed", exc_info=True)

    # ── Generic fallback ──
    return (
        f"😅 智能服务暂时不可用（{error_msg[:80]}）。\n\n"
        "你可以尝试以下操作：\n"
        "- 使用页面顶部的 **快速报修** 直接提交工单\n"
        "- 通过左侧导航浏览各功能页面\n"
        "- 稍后重试对话，系统会自动恢复\n\n"
        "如需帮助，请联系管理员。"
    )
