# tools/query_proposals.py
"""邻里议事 — 查询社区提案."""
from langchain.tools import tool
from data.database import get_proposals as _db_get_proposals, get_proposals_stats


@tool
def get_proposals(category: str = "", sort_by: str = "supporters", limit: int = 10) -> str:
    """查询社区提案列表。看看大家都在提什么建议，附议你支持的提案。

    参数：
    - category: 按分类筛选（可选），留空则显示全部。可选：设施维修/环境卫生/安全隐患/停车管理/噪音扰民/物业服务/邻里矛盾/社区事务
    - sort_by: 排序方式，'supporters'按附议数排序（默认），'latest'按最新排序
    - limit: 返回数量（默认10条）

    返回提案列表，包含标题、附议数、状态等信息。
    """
    cat = category if category else None
    sort = "supporters" if sort_by == "supporters" else "latest"
    proposals = _db_get_proposals(category=cat, sort_by=sort, limit=limit)

    if not proposals:
        cat_msg = f"（分类：{category}）" if category else ""
        return (
            f"📢 暂无提案{cat_msg}。\n"
            f"有什么想法？输入'我想提议...'来创建第一个提案吧！"
        )

    stats = get_proposals_stats()

    lines = [f"🗳️ **社区提案**（共 {stats['total']} 件）", ""]

    status_emoji = {
        "讨论中": "💬", "已回应": "📝", "已采纳": "✅", "已实施": "🎉",
    }

    for i, p in enumerate(proposals, 1):
        emoji = status_emoji.get(p["status"], "📌")
        response_note = ""
        if p.get("response_text"):
            response_note = f"\n    ↳ 社区回应：{p['response_text'][:50]}..."
        lines.append(
            f"{i}. {emoji} **{p['title'][:40]}**\n"
            f"   👍 {p['supporter_count']} 人附议 · {p['status']} · {p.get('category', '其他')}{response_note}"
        )

    lines.append("")
    lines.append("附议越多越容易被社区/物业关注。")

    return "\n".join(lines)
