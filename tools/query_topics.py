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
    """查看当前社区热议的民意议题。这些议题由AI根据社区近期情况自动发起，或由网格员手动发布。

    返回活跃议题列表，每个议题包含标题、参与人数、部分观点摘要。
    你也可以对任何议题发表自己的意见。
    """
    topics = _db_get_active_topics(limit=8)

    if not topics:
        return (
            "📢 当前暂无活跃的民意议题。\n"
            "AI 会自动根据社区近期热点发起议题讨论。你也可以在'邻里议事'板块创建提案来表达你的想法！"
        )

    lines = ["🗳️ **民意广场 · 正在热议**", ""]

    for i, t in enumerate(topics, 1):
        summary = get_opinion_summary(t["id"])
        source_tag = "系统自动发起" if t.get("created_by_agent") else "👤 网格员发布"
        lines.append(
            f"{i}. **{t['title'][:35]}**\n"
            f"   {source_tag} · {summary['total_opinions']} 人参与讨论\n"
            f"   {t.get('description', '')[:60]}..."
        )

        # 每条议题带几条最新观点
        if summary["recent_opinions"]:
            lines.append(f"   💬 最新观点：")
            for op in summary["recent_opinions"][:2]:
                label = op.get("participant_label", "居民")
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
    source_tag = "系统自动发起" if t.get("created_by_agent") else "👤 网格员发布"

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
            label = op.get("participant_label", "居民")
            content = op.get("content", "")
            lines.append(f"· **{label}**：{content}")
    else:
        lines.append("· 暂无观点，来做第一个发声的人！")

    lines.append("")
    lines.append("输入你的意见发表看法。")

    return "\n".join(lines)


def _discover_hot_topic() -> dict | None:
    """分析最近的社区数据，找有没有能聊起来的热点。

    感知引擎调它来自动发起议题：某类诉求扎堆、反复出现等
    情况命中时就会生成。

    有热点就返回 {title, description, category}，没有就 None。
    """
    issues = get_issues(limit=50)
    if not issues:
        return None

    # 统计各类别数量，找扎堆的
    cat_counts: dict[str, int] = {}
    for issue in issues:
        cat = issue.get("category", "其他")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # 某类最近有 5 件以上就算热点
    for cat, count in cat_counts.items():
        if count >= 5:
            topic_templates = {
                "设施维修": {
                    "title": f"小区设施维修频发——{cat}问题集中讨论",
                    "description": f"近期收到{count}件设施维修相关上报。你觉得小区设施维护存在哪些问题？有什么改进建议？",
                },
                "环境卫生": {
                    "title": "小区环境卫生问题引发关注",
                    "description": f"近期收到{count}件环境卫生相关反馈。哪些区域的卫生状况需要改善？你有什么建议？",
                },
                "安全隐患": {
                    "title": "小区安全隐患，你我共同关注",
                    "description": f"近期上报了{count}件安全隐患问题。你注意到小区里有哪些不安全的地方吗？",
                },
                "停车管理": {
                    "title": "停车难问题集中反馈",
                    "description": f"近期收到{count}件停车管理相关反馈。你觉得小区停车存在哪些问题？有什么改进建议？",
                },
                "噪音扰民": {
                    "title": "噪音扰民问题引发关注",
                    "description": f"近期收到{count}件噪音扰民相关反馈。你觉得小区里有哪些噪音困扰？有什么解决办法？",
                },
                "物业服务": {
                    "title": "物业服务满意度调查",
                    "description": f"近期收到{count}件物业服务相关反馈。你对物业服务有什么建议？",
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
