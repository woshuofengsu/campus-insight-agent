# ui/prefetch.py
"""Intent-based data prefetch — provides real DB data as context to the agent.

Each prefetch function detects a user intent from keywords and returns
pre-formatted context data. This ensures the AI has real data to work with
even when the LLM decides not to call tools.
"""
import logging
from collections.abc import Callable
from data.database import (
    get_issues, get_issues_stats, get_recent_issue_counts,
    get_proposals, get_campus_events, get_active_topics,
    get_opinion_summaries_batch,
    compute_health_score,
)

_logger = logging.getLogger("ui.prefetch")

PREFETCH_SIGNALS: list[tuple[list[str], str]] = [
    (["校园脉搏", "动态", "最近动态", "校园动态", "最近发生", "发生什么了", "最近有什么", "这周情况", "今天发生"], "_prefetch_pulse"),
    (["治理数据", "统计数据", "治理统计", "治理情况", "健康度", "解决率", "工单概览"], "_prefetch_stats"),
    (["天气", "温度", "下雨", "刮风", "空气质量", "多少度", "冷不冷", "热不热", "带伞", "防晒"], "_prefetch_weather"),
    (["提案", "建议", "提议", "大家提了", "看看有什么想法", "有什么好主意"], "_prefetch_proposals"),
    (["议题", "讨论", "大家在聊", "热门话题", "民意", "大家怎么想"], "_prefetch_topics"),
    (["工单", "报修", "上报了", "有哪些问题", "看看问题", "查一下问题"], "_prefetch_query_issues"),
]


def _prefetch_pulse() -> str:
    """Pre-fetch campus pulse data from DB."""
    try:
        issues = get_issues(status="待处理", limit=5)
        proposals = get_proposals(sort_by="supporters", limit=5)
        events = get_campus_events(limit=5)
        stats = get_issues_stats()

        lines = ["## 校园脉搏快照（系统预取）", ""]
        lines.append(f"📊 工单总数：{stats['total']} 件")
        by_status = stats.get("by_status", {})
        lines.append(f"   ⏳ 待处理 {by_status.get('待处理', 0)} · 🔄 处理中 {by_status.get('处理中', 0)} · ✅ 已解决 {by_status.get('已解决', 0)}")

        if issues:
            lines.append("\n🔧 待处理问题：")
            for i in issues[:5]:
                lines.append(f"   #{i['id']} {i['title'][:30]} [{i.get('category','')}] ({i.get('urgency','')})")

        if proposals:
            lines.append("\n💡 热门提案：")
            for p in proposals[:3]:
                lines.append(f"   🥇 #{p['id']} {p['title'][:30]} · {p['supporter_count']}人附议")

        if events:
            lines.append("\n📅 近期事件：")
            for e in events[:3]:
                lines.append(f"   · {e.get('title','')[:40]}")

        return "\n".join(lines)
    except Exception as e:
        _logger.warning("_prefetch_pulse failed: %s", e)
        return ""


def _prefetch_stats() -> str:
    """Pre-fetch governance stats from DB."""
    try:
        health = compute_health_score()
        recent = get_recent_issue_counts(7)
        stats = get_issues_stats()

        lines = ["## 治理数据快照（系统预取）", ""]
        lines.append(f"🏥 治理健康度：{health['score']}分（{health['grade']}）")
        lines.append(f"📈 解决率：{health['resolution_rate']}%")
        if health.get('avg_days') is not None:
            lines.append(f"⏱️ 平均解决时间：{health['avg_days']}天")
        else:
            lines.append("⏱️ 暂无解决数据")
        lines.append(f"📊 近7天：新增 {recent['new_last_n_days']} 件 · 解决 {recent['resolved_last_n_days']} 件")
        lines.append(f"📋 趋势：{health['trend']}")

        by_cat = stats.get("by_category", {})
        if by_cat:
            lines.append("\n📂 分类分布：")
            for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1])[:5]:
                lines.append(f"   · {cat}：{cnt} 件")

        return "\n".join(lines)
    except Exception as e:
        _logger.warning("_prefetch_stats failed: %s", e)
        return ""


def _prefetch_weather() -> str:
    """Pre-fetch weather data."""
    try:
        from tools.query_weather import get_today_weather
        days, location_name, is_real = get_today_weather()
        if not days:
            return ""
        lines = ["## 天气数据（系统预取）", ""]
        lines.append(f"📍 {location_name} · {'实时API' if is_real else '模拟数据'}")
        for i, d in enumerate(days[:3]):
            prefix = "📌 今天" if i == 0 else "📅 明天" if i == 1 else "📅 后天"
            lines.append(
                f"{prefix} {d['weekday']} {d['emoji']} {d['condition']} "
                f"{d['temp_low']}°C~{d['temp_high']}°C "
                f"降水{d['rain_prob']}% {d['wind']} "
                f"— {d['advice']}"
            )
        return "\n".join(lines)
    except Exception as e:
        _logger.warning("_prefetch_weather failed: %s", e)
        return ""


def _prefetch_proposals() -> str:
    """Pre-fetch proposal list."""
    try:
        proposals = get_proposals(sort_by="supporters", limit=8)
        if not proposals:
            return ""
        lines = ["## 提案数据快照（系统预取）", ""]
        lines.append(f"💡 共 {len(proposals)} 件提案")
        for p in proposals[:5]:
            lines.append(
                f"   🥇 #{p['id']} {p['title'][:35]} "
                f"· 👍{p['supporter_count']} · {p['status']}"
            )
        return "\n".join(lines)
    except Exception as e:
        _logger.warning("_prefetch_proposals failed: %s", e)
        return ""


def _prefetch_topics() -> str:
    """Pre-fetch discussion topics with batched opinion counts (no N+1)."""
    try:
        topics = get_active_topics(limit=5)
        if not topics:
            return ""
        # Batch query — single DB round-trip instead of 1 + N
        topic_ids = [t["id"] for t in topics]
        summaries = get_opinion_summaries_batch(topic_ids)
        lines = ["## 议题数据快照（系统预取）", ""]
        lines.append(f"🗳️ 共 {len(topics)} 个活跃议题")
        for t in topics[:5]:
            s = summaries.get(t["id"], {"total_opinions": 0, "topic_title": t["title"]})
            lines.append(
                f"   · #{t['id']} {t['title'][:35]} "
                f"— {s['total_opinions']} 人参与"
            )
        return "\n".join(lines)
    except Exception as e:
        _logger.warning("_prefetch_topics failed: %s", e)
        return ""


def _prefetch_query_issues() -> str:
    """Pre-fetch recent issues."""
    try:
        issues = get_issues(limit=8)
        if not issues:
            return ""
        lines = ["## 工单数据快照（系统预取）", ""]
        pending = [i for i in issues if i.get("status") != "已解决"]
        lines.append(f"📋 共 {len(issues)} 件工单（最近），{len(pending)} 件待处理")
        for i in issues[:5]:
            urgency_icon = {"紧急": "🔴", "极急": "🔴", "普通": "🔵"}.get(i.get("urgency", ""), "⚪")
            lines.append(
                f"   {urgency_icon} #{i['id']} {i['title'][:30]} "
                f"[{i.get('category','')}] {i.get('status','')}"
            )
        return "\n".join(lines)
    except Exception as e:
        _logger.warning("_prefetch_query_issues failed: %s", e)
        return ""


# Name → function mapping
PREFETCH_FUNCTIONS: dict[str, Callable[[], str]] = {
    "_prefetch_pulse": _prefetch_pulse,
    "_prefetch_stats": _prefetch_stats,
    "_prefetch_weather": _prefetch_weather,
    "_prefetch_proposals": _prefetch_proposals,
    "_prefetch_topics": _prefetch_topics,
    "_prefetch_query_issues": _prefetch_query_issues,
}


def try_prefetch(user_input: str) -> str | None:
    """Check user input against prefetch signals and return pre-fetched context.

    Returns None if no match or pre-fetch failed.
    """
    txt = user_input.strip()
    if len(txt) < 2:
        return None
    for keywords, method_name in PREFETCH_SIGNALS:
        if any(kw in txt for kw in keywords):
            fn = PREFETCH_FUNCTIONS.get(method_name)
            if fn:
                result = fn()
                if result:
                    return result
    return None
