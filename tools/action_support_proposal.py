# tools/action_support_proposal.py
"""邻里议事 — 为公示中的公开提案匿名评分（1~5 星，一票制）。

原「附议」功能按《02-提案.md》改造为公示期匿名投票：
- 评分只存分数与时间，不存用户与分数的关联；
- proposal_vote_dedup 表只用于防重复，不对任何人展示；
- 提案人不能给自己提案投票。
"""
from langchain.tools import tool
from data.db_proposal import (
    vote_proposal as _db_vote_proposal,
    get_proposal as _db_get_proposal,
    get_proposal_vote_stats,
)


def _current_user_id() -> int:
    """解析当前登录用户 ID（UI/Agent 场景），拿不到返回 0。"""
    try:
        from data.db_user import get_current_user
        profile = get_current_user()
        return profile.get("id") or 0
    except Exception:
        return 0


@tool
def support_proposal(proposal_id: int, score: int | None = None) -> str:
    """给公示中的公开提案匿名评分（1~5 星，每人每提案限投一票）。

    参数：
    - proposal_id: 提案编号（必填），可在提案列表中查看每个提案的 #编号
    - score: 评分（必填），1~5 星，5 星为最高

    投票完全匿名：系统只记录分数与时间，不记录是谁投的；提案人不能投自己的提案；
    投票后不可修改。公示结束后负责人根据平均分和实际情况决定是否执行。
    """
    if not proposal_id or proposal_id <= 0:
        return "⚠️ 请提供有效的提案编号。你可以在提案列表中查看每个提案的 #编号。"
    if score is None:
        return "⚠️ 请提供评分（1~5 星）。"

    target = _db_get_proposal(proposal_id)
    if target is None:
        return f"⚠️ 未找到编号为 #{proposal_id} 的提案。请检查编号是否正确。"

    ok, msg = _db_vote_proposal(proposal_id, _current_user_id(), score)
    if not ok:
        return f"⚠️ 评分失败：{msg}"

    try:
        from ui.cache import invalidate_proposals
        invalidate_proposals()
    except Exception:
        pass

    stats = get_proposal_vote_stats(proposal_id)
    avg = f"{stats['avg_score']:.1f}" if stats["avg_score"] is not None else "—"
    return (
        f"🗳️ 评分成功！你给提案 #{proposal_id} **{target['title'][:30]}** 评了 {score} 星（匿名）。\n"
        f"当前平均分：**{avg}**，共 {stats['vote_count']} 人评分。\n"
        f"投票匿名且不可修改，感谢你的参与。"
    )
