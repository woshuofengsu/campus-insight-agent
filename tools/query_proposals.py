# tools/query_proposals.py
"""邻里议事 — 查询社区提案（公开可见范围，含公示投票统计）。"""
from langchain.tools import tool
from data.db_proposal import (
    get_proposals as _db_get_proposals,
    get_proposals_stats as _db_get_proposals_stats,
    get_vote_stats_batch,
    get_voting_remaining_days,
    proposal_no,
    VALID_CATEGORIES,
)

# 居民可见的提案状态（待审核/退回修改/待确认/已撤回/已关闭 不对外展示）
_VISIBLE_STATUSES = [
    "公示中", "待执行", "执行中", "待提案人反馈", "已完成",
    "重新执行", "不予执行", "违规下架", "已结束",
]


@tool
def get_proposals(category: str = "", status: str = "", sort_by: str = "latest",
                  limit: int = 10) -> str:
    """查询社区公开提案列表（含公示投票人数与平均分）。

    参数：
    - category: 按类别筛选（可选），五选一：公共设施/环境卫生/文化活动/安全治理/其他
    - status: 按状态筛选（可选），如：公示中/执行中/已完成/不予执行
    - sort_by: 排序方式，'hot'按平均分（默认按最新），'latest'按最新
    - limit: 返回数量（默认10条）

    只返回公开提案（私有提案不对居民展示）；公示中的提案显示剩余天数，
    其他显示投票人数与平均分（匿名汇总，不含个体投票明细）。
    """
    cat = category if category else None
    st = status if status in _VISIBLE_STATUSES else None
    proposals = _db_get_proposals(
        category=cat, status=st, is_public=1,
        exclude_statuses=[s for s in ["待审核", "退回修改", "待确认公示/私有", "已撤回", "已关闭"] if s != st],
        limit=limit,
    )

    if not proposals:
        cat_msg = f"（类别：{category}）" if category else ""
        return (
            f"📢 暂无公开提案{cat_msg}。\n"
            f"有什么想法？输入'我想提议...'来提交第一份提案吧！"
        )

    stats = _db_get_proposals_stats()
    vote_map = get_vote_stats_batch([p["id"] for p in proposals])

    # 排序：hot 按平均分（有评分在前，无评分在后），latest 按最新
    if sort_by == "hot":
        proposals = sorted(
            proposals,
            key=lambda p: (-((vote_map.get(p["id"], {}).get("avg_score")) or 0),
                           -(vote_map.get(p["id"], {}).get("vote_count") or 0)),
        )

    lines = [f"🗳️ **社区公开提案**（共 {stats['total']} 件）", ""]

    for i, p in enumerate(proposals, 1):
        v = vote_map.get(p["id"], {})
        s = p.get("status", "")
        extra = ""
        if s == "公示中":
            days = get_voting_remaining_days(p["id"])
            extra = f" · ⏳ 剩余 {days} 天" if days is not None else ""
            if v.get("vote_count"):
                extra += f" · 评分 {v['vote_count']} 人 · 平均 {v['avg_score']:.1f}"
        elif v.get("vote_count"):
            extra = f" · 评分 {v['vote_count']} 人 · 平均 {v['avg_score']:.1f}"
        reason_note = ""
        if s in ("不予执行", "违规下架") and p.get("decision_reason"):
            reason_note = f"\n    ↳ 原因：{p['decision_reason'][:50]}"
        dept_note = f" · 执行部门：{p.get('executor_dept')}" if s == "执行中" and p.get("executor_dept") else ""
        result_note = ""
        if s in ("已完成", "待提案人反馈") and p.get("execution_result"):
            result_note = f"\n    ↳ 执行结果：{p['execution_result'][:50]}"
        lines.append(
            f"{i}. **{p['title'][:40]}**\n"
            f"   {proposal_no(p['id'])} · {p.get('category','')} · {s}{extra}{dept_note}"
            f"{reason_note}{result_note}"
        )

    lines.append("")
    lines.append("公示中的提案可匿名评分（1~5 星，一票制），平均分越高越受关注。")
    return "\n".join(lines)
