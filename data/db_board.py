# data/db_board.py
"""红黑榜 + 满意度下钻（P2-B4-01）。

红榜（表扬）：满意度满分工单、高效网格员（处理快+满意度高）、已完成提案。
黑榜（待改进）：不满意工单（含原因）、SLA 超时工单、低效网格员。
下钻：满意度统计 → 满意/不满意工单明细（可按分类/网格员筛选）。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 满意度统计口径：工单已解决且有评价
_SATISFIED = "满意"
_DISSATISFIED = "不满意"


def _issue_fields(r) -> dict:
    return {
        "id": r["id"], "title": r["title"], "category": r["category"],
        "urgency": r["urgency"], "status": r["status"],
        "assignee_name": r["assignee_name"] or "",
        "satisfaction": r["satisfaction"] or "",
        "satisfaction_reason": r["satisfaction_reason"] or "",
        "reported_at": (r["reported_at"] or "")[:16],
        "resolved_at": (r["resolved_at"] or "")[:16],
    }


def _resolve_hours(reported_at, resolved_at) -> float | None:
    """处理时长（小时），缺时间戳返回 None。"""
    try:
        from datetime import datetime
        t0 = datetime.strptime(str(reported_at)[:19], "%Y-%m-%d %H:%M:%S")
        t1 = datetime.strptime(str(resolved_at)[:19], "%Y-%m-%d %H:%M:%S")
        return round((t1 - t0).total_seconds() / 3600.0, 1)
    except (ValueError, TypeError):
        return None


def get_red_black_board(days: int = 30, limit: int = 5) -> dict:
    """红黑榜（近 days 天）。

    - red_board: 满意工单 Top（按处理快）+ 高效网格员 Top（满意率高+件数多）+ 已完成满意提案
    - black_board: 不满意工单（含原因）+ SLA 超时工单 + 低效网格员（不满意数多）
    """
    try:
        with get_db() as conn:
            # 满意工单（近 N 天解决）
            red_issues = conn.execute(
                "SELECT * FROM community_issues WHERE satisfaction=? "
                "AND resolved_at >= datetime('now', ?) "
                "ORDER BY resolved_at DESC LIMIT ?",
                (_SATISFIED, f"-{days} days", limit * 2),
            ).fetchall()
            # 不满意工单（近 N 天）
            black_issues = conn.execute(
                "SELECT * FROM community_issues WHERE satisfaction=? "
                "AND resolved_at >= datetime('now', ?) "
                "ORDER BY resolved_at DESC LIMIT ?",
                (_DISSATISFIED, f"-{days} days", limit),
            ).fetchall()
            # 网格员聚合：按 assignee 统计已解决数 / 满意数 / 不满意数
            workers = conn.execute(
                "SELECT assignee_name, COUNT(*) AS total, "
                "SUM(CASE WHEN satisfaction=? THEN 1 ELSE 0 END) AS sat, "
                "SUM(CASE WHEN satisfaction=? THEN 1 ELSE 0 END) AS dis, "
                "AVG(julianday(resolved_at) - julianday(reported_at)) * 24 AS avg_hours "
                "FROM community_issues "
                "WHERE assignee_name != '' AND resolved_at >= datetime('now', ?) "
                "AND satisfaction != '' "
                "GROUP BY assignee_name ORDER BY sat DESC, avg_hours ASC",
                (_SATISFIED, _DISSATISFIED, f"-{days} days"),
            ).fetchall()
            # 已完成且满意的提案
            done_proposals = conn.execute(
                "SELECT id, title, category, status, satisfaction, created_at "
                "FROM proposals WHERE satisfaction=? AND status='已完成' "
                "AND created_at >= datetime('now', ?) "
                "ORDER BY created_at DESC LIMIT ?",
                (_SATISFIED, f"-{days} days", limit),
            ).fetchall()
    except Exception:
        _log.warning("get_red_black_board 查询失败", exc_info=True)
        return {"days": days, "red_board": [], "black_board": []}

    # 红榜
    red_issues_list = []
    for r in red_issues:
        d = _issue_fields(r)
        d["hours"] = _resolve_hours(r["reported_at"], r["resolved_at"])
        red_issues_list.append(d)
    good_workers = []
    for w in workers:
        if w["total"] and (w["sat"] or 0) >= max(1, w["total"] * 0.6):
            good_workers.append({
                "name": w["assignee_name"],
                "solved": w["total"],
                "satisfied": w["sat"] or 0,
                "dissatisfied": w["dis"] or 0,
                "avg_hours": round(w["avg_hours"], 1) if w["avg_hours"] else None,
            })
    red_board = {
        "satisfied_issues": red_issues_list[:limit],
        "good_workers": good_workers[:limit],
        "done_proposals": [dict(r) for r in done_proposals][:limit],
    }

    # 黑榜
    black_issues_list = []
    for r in black_issues:
        d = _issue_fields(r)
        d["hours"] = _resolve_hours(r["reported_at"], r["resolved_at"])
        black_issues_list.append(d)
    slow_workers = []
    for w in workers:
        if (w["dis"] or 0) > 0 and (w["dis"] or 0) >= (w["total"] or 1) * 0.3:
            slow_workers.append({
                "name": w["assignee_name"],
                "solved": w["total"],
                "satisfied": w["sat"] or 0,
                "dissatisfied": w["dis"] or 0,
                "avg_hours": round(w["avg_hours"], 1) if w["avg_hours"] else None,
            })
    # SLA 超时工单（复用 db_sla 判定）
    from data.db_sla import get_sla_breaches
    try:
        breaches = [{"id": b["id"], "title": b.get("title") or "", "urgency": b.get("urgency") or "",
                     "level": b.get("level") or "overdue"} for b in get_sla_breaches()[:limit]]
    except Exception:
        breaches = []
    black_board = {
        "dissatisfied_issues": black_issues_list[:limit],
        "slow_workers": slow_workers[:limit],
        "sla_breaches": breaches,
    }

    return {"days": days, "red_board": red_board, "black_board": black_board}


def get_satisfaction_drilldown(category: str = "", assignee: str = "",
                               satisfaction: str = "", limit: int = 50) -> dict:
    """满意度下钻：按分类/网格员/评价筛选工单明细 + 汇总。

    返回 {summary: {satisfied, dissatisfied, total, rate}, items: [...]}。
    """
    q = "SELECT * FROM community_issues WHERE satisfaction != ''"
    args: list = []
    if category:
        q += " AND category=?"
        args.append(category)
    if assignee:
        q += " AND assignee_name=?"
        args.append(assignee)
    if satisfaction in (_SATISFIED, _DISSATISFIED):
        q += " AND satisfaction=?"
        args.append(satisfaction)
    q += " ORDER BY resolved_at DESC LIMIT ?"
    args.append(limit)
    try:
        with get_db() as conn:
            rows = conn.execute(q, args).fetchall()
            items = []
            for r in rows:
                d = _issue_fields(r)
                d["hours"] = _resolve_hours(r["reported_at"], r["resolved_at"])
                items.append(d)
        from data.db_governance import get_satisfaction_stats
        stats = get_satisfaction_stats() or {}
        return {"summary": stats, "items": items}
    except Exception:
        _log.warning("get_satisfaction_drilldown 查询失败", exc_info=True)
        return {"summary": {}, "items": []}
