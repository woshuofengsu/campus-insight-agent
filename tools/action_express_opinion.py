# tools/action_express_opinion.py
"""有话说 — 对民意议题发表意见."""
from langchain.tools import tool
from data.database import (
    add_opinion,
    get_opinion_summary,
    get_active_topics as _db_get_active_topics,
)


@tool
def express_opinion(topic_id: int, content: str) -> str:
    """对校园民意议题发表你的看法和意见。

    参数：
    - topic_id: 议题编号（必填），可在议题列表中查看
    - content: 你的意见内容（必填），可以是支持、反对、建议、或任何想法

    你的意见会匿名展示在议题讨论区。参与讨论可以帮助学校更好地了解学生需求。
    """
    if not topic_id or topic_id <= 0:
        return "⚠️ 请提供有效的议题编号。输入'查看议题'可以浏览所有活跃议题。"

    if not content or len(content.strip()) < 2:
        return "⚠️ 意见内容太短了，请至少写几个字说说你的想法~"

    # Verify topic exists and is active
    topics = _db_get_active_topics(limit=50)
    target = None
    for t in topics:
        if t["id"] == topic_id:
            target = t
            break

    if target is None:
        return (
            f"⚠️ 未找到编号为 #{topic_id} 的活跃议题。\n"
            f"议题可能已结束或编号有误。输入'查看议题'查看当前活跃议题。"
        )

    opinion_id = add_opinion(
        topic_id=topic_id,
        content=content.strip(),
        participant_label="匿名学生",
    )

    summary = get_opinion_summary(topic_id)

    return (
        f"💬 你的意见已发表！\n"
        f"📋 议题：{target['title'][:30]}\n"
        f"👥 当前参与人数：{summary['total_opinions']}\n"
        f"💡 你的声音很重要——AI会定期汇总讨论结果，形成民意报告。"
    )
