# tools/action_support_proposal.py
"""有话说 — 附议提案."""
from langchain.tools import tool
from data.database import support_proposal as _db_support_proposal, get_db


@tool
def support_proposal(proposal_id: int) -> str:
    """附议（支持）一个校园提案。

    参数：
    - proposal_id: 提案编号（必填），可在提案列表中查看每个提案的 #编号

    附议后该提案的支持数+1。附议量高的提案会被推送到治理看板，更容易获得校方关注和回应。
    """
    if not proposal_id or proposal_id <= 0:
        return "⚠️ 请提供有效的提案编号。你可以在提案列表中查看每个提案的 #编号。"

    # Verify proposal exists (direct SQL lookup, not O(n) scan)
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, title FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
    target = dict(row) if row else None

    if target is None:
        return f"⚠️ 未找到编号为 #{proposal_id} 的提案。请检查编号是否正确。你可以输入'查看提案'来浏览所有提案。"

    new_count = _db_support_proposal(proposal_id)

    # Milestone messages
    milestone = ""
    if new_count == 10:
        milestone = " -- 已达成 10 人附议"
    elif new_count == 50:
        milestone = " -- 已达成 50 人附议"
    elif new_count == 100:
        milestone = " -- 已达成 100 人附议，已置顶到治理看板"

    return (
        f"👍 你附议了提案 #{proposal_id} **{target['title'][:30]}**\n"
        f"当前附议人数：**{new_count}**{milestone}\n"
        f"分享给同学以获得更多附议。"
    )
