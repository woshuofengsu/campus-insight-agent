# tools/query_topics.py
"""议题查询 —— 活跃议题列表 + 热点自动发现."""
from datetime import datetime
from langchain.tools import tool
from data.database import (
    get_active_topics as _db_get_active_topics,
    get_opinions_by_topic,
    get_opinion_summary,
    get_issues,
)


@tool
def get_topics() -> str:
    """查看当前校园热议的民意议题。这些议题由AI根据校园近期情况自动发起，或由管理员手动发布。

    返回活跃议题列表，每个议题包含标题、参与人数、部分观点摘要。
    你也可以对任何议题发表自己的意见。
    """
    topics = _db_get_active_topics(limit=8)

    if not topics:
        return (
            "📢 当前暂无活跃的民意议题。\n"
            "AI 会自动根据校园近期热点发起议题讨论。你也可以在'有话说'板块创建提案来表达你的想法！"
        )

    lines = ["🗳️ **民意广场 · 正在热议**", ""]

    for i, t in enumerate(topics, 1):
        summary = get_opinion_summary(t["id"])
        source_tag = "系统自动发起" if t.get("created_by_agent") else "👤 管理员发布"
        lines.append(
            f"{i}. **{t['title'][:35]}**\n"
            f"   {source_tag} · {summary['total_opinions']} 人参与讨论\n"
            f"   {t.get('description', '')[:60]}..."
        )

        # Show a few recent opinions
        if summary["recent_opinions"]:
            lines.append(f"   💬 最新观点：")
            for op in summary["recent_opinions"][:2]:
                label = op.get("participant_label", "学生")
                content = op.get("content", "")[:50]
                lines.append(f"     · {label}：{content}...")
        lines.append("")

    lines.append("对议题有想法？输入「我想对议题X发表意见」。")

    return "\n".join(lines)


@tool
def get_topic_detail(topic_id: int) -> str:
    """查看某个议题的详细讨论内容。想看某个议题大家都说了什么？用这个。

    参数：
    - topic_id: 议题编号，可在议题列表中查看

    返回该议题的详细信息和最近的观点。
    """
    if not topic_id or topic_id <= 0:
        return "⚠️ 请提供有效的议题编号。"

    summary = get_opinion_summary(topic_id)
    if not summary["topic"]:
        return f"⚠️ 未找到编号为 #{topic_id} 的议题。"

    t = summary["topic"]
    source_tag = "系统自动发起" if t.get("created_by_agent") else "👤 管理员发布"

    lines = [
        f"🗳️ **{t['title']}**",
        f"{source_tag} · {summary['total_opinions']} 人参与",
        f"",
        f"📝 {t.get('description', '')}",
        f"",
        f"### 💬 大家怎么说",
    ]

    opinions = get_opinions_by_topic(topic_id, limit=20)
    if opinions:
        for op in opinions:
            label = op.get("participant_label", "学生")
            content = op.get("content", "")
            lines.append(f"· **{label}**：{content}")
    else:
        lines.append("· 暂无观点，来做第一个发声的人！")

    lines.append("")
    lines.append("输入你的意见发表看法。")

    return "\n".join(lines)


def _discover_hot_topic() -> dict | None:
    """Analyze recent campus data to discover potential hot topics.

    Called by the perception engine to auto-generate discussion topics
    when certain patterns are detected (e.g., same category spikes,
    recurring complaints).

    Returns a dict with title/description/category if a hot topic is found,
    or None if nothing notable.
    """
    issues = get_issues(limit=50)
    if not issues:
        return None

    # Find category spikes
    cat_counts: dict[str, int] = {}
    for issue in issues:
        cat = issue.get("category", "其他")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # If any category has >= 5 recent issues, it's a hot topic
    for cat, count in cat_counts.items():
        if count >= 5:
            topic_templates = {
                "设施维修": {
                    "title": f"校园设施维修频发——{cat}问题集中讨论",
                    "description": f"近期收到{count}件设施维修相关上报。你觉得学校设施维护存在哪些问题？有什么改进建议？",
                },
                "环境卫生": {
                    "title": "校园环境卫生问题引发关注",
                    "description": f"近期收到{count}件环境卫生相关反馈。哪些区域的卫生状况需要改善？你有什么建议？",
                },
                "安全隐患": {
                    "title": "校园安全隐患，你我共同关注",
                    "description": f"近期上报了{count}件安全隐患问题。你注意到校园里有哪些不安全的地方吗？",
                },
                "餐饮问题": {
                    "title": "食堂餐饮问题集中反馈",
                    "description": f"近期收到{count}件餐饮相关反馈。你觉得食堂在哪些方面需要改进？菜品价格、种类、还是服务？",
                },
                "网络服务": {
                    "title": "校园网络服务满意度调查",
                    "description": f"近期收到{count}件网络相关反馈。你遇到的网络问题有哪些？对校园网络有什么建议？",
                },
            }
            template = topic_templates.get(cat, {
                "title": f"{cat}问题近期受到关注",
                "description": f"近期共收到{count}件{cat}相关反馈。你怎么看这个问题？有什么好的解决方案吗？",
            })
            return {
                "title": template["title"],
                "description": template["description"],
                "category": cat,
            }

    return None
