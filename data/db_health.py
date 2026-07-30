# data/db_health.py
"""Governance health analytics — scoring, timelines, efficiency metrics."""
from datetime import datetime, timedelta
from data.db_core import get_db


def get_avg_resolution_days() -> float | None:
    """Average days from creation to resolution for resolved issues. None if no resolved issues."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT AVG(julianday(resolved_at) - julianday(reported_at)) AS avg_days "
            "FROM campus_issues WHERE status = '已解决' AND resolved_at IS NOT NULL"
        ).fetchone()
        return round(row["avg_days"], 1) if row and row["avg_days"] else None


def get_recent_issue_counts(days: int = 7) -> dict:
    """Count new and resolved issues in the last N days."""
    with get_db() as conn:
        new_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM campus_issues "
            "WHERE reported_at >= datetime('now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()
        resolved_row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM campus_issues "
            "WHERE status = '已解决' AND resolved_at >= datetime('now', ? || ' days')",
            (f"-{days}",),
        ).fetchone()
        return {
            "new_last_n_days": new_row["cnt"] if new_row else 0,
            "resolved_last_n_days": resolved_row["cnt"] if resolved_row else 0,
            "days": days,
        }


def get_issues_timeline(days: int = 7) -> list[dict]:
    """Daily counts of reported and resolved issues for the past N days."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DATE(reported_at) as day, COUNT(*) as count "
            "FROM campus_issues WHERE reported_at >= datetime('now', ? || ' days') "
            "GROUP BY DATE(reported_at) ORDER BY day",
            (f"-{days}",),
        ).fetchall()
        new_by_day = {r["day"]: r["count"] for r in rows}

        rows = conn.execute(
            "SELECT DATE(resolved_at) as day, COUNT(*) as count "
            "FROM campus_issues WHERE status = '已解决' "
            "AND resolved_at >= datetime('now', ? || ' days') "
            "GROUP BY DATE(resolved_at) ORDER BY day",
            (f"-{days}",),
        ).fetchall()
        resolved_by_day = {r["day"]: r["count"] for r in rows}

    result = []
    for i in range(days, -1, -1):
        day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        result.append({
            "day": day,
            "new_count": new_by_day.get(day, 0),
            "resolved_count": resolved_by_day.get(day, 0),
        })
    return result


def compute_health_score() -> dict:
    """Multi-dimensional campus governance health score.

    Returns a dict with:
      - score: 0-100 composite
      - grade: 优/良/需改进
      - resolution_rate: percentage
      - avg_days: average resolution time in days
      - trend: backlog trend label
      - speed_score: resolution speed sub-score (0-100)
      - backlog_score: backlog health sub-score (0-100)
    """
    from data.db_governance import get_issues_stats

    stats = get_issues_stats()
    total = stats["total"]
    resolved = stats["by_status"].get("已解决", 0)

    # Dimension 1: Resolution rate (40% weight)
    resolution_rate = resolved / total * 100 if total > 0 else 100

    # Dimension 2: Resolution speed (35% weight)
    avg_days = get_avg_resolution_days()
    if avg_days is not None:
        speed_score = max(0, min(100, 120 - avg_days * 8))
    else:
        speed_score = 70  # No data yet, assume neutral
        avg_days = 0

    # Dimension 3: Backlog trend (25% weight)
    recent = get_recent_issue_counts(7)
    new_recent = recent["new_last_n_days"]
    resolved_recent = recent["resolved_last_n_days"]

    if new_recent == 0:
        backlog_score = 100
    elif resolved_recent >= new_recent:
        backlog_score = min(100, 60 + (resolved_recent - new_recent) / max(new_recent, 1) * 40)
    else:
        ratio = resolved_recent / max(new_recent, 1)
        backlog_score = max(0, min(95, int(ratio * 100 + 10)))

    # Trend label
    if backlog_score >= 75:
        trend = "↓ 改善中"
    elif backlog_score >= 45:
        trend = "→ 持平"
    else:
        trend = "↑ 需关注"

    # Composite
    composite = resolution_rate * 0.40 + speed_score * 0.35 + backlog_score * 0.25

    if composite >= 80:
        grade = "优"
    elif composite >= 50:
        grade = "良"
    else:
        grade = "需改进"

    return {
        "score": round(composite, 1),
        "grade": grade,
        "resolution_rate": round(resolution_rate, 1),
        "avg_days": avg_days if avg_days else None,
        "trend": trend,
        "speed_score": round(speed_score, 1),
        "backlog_score": round(backlog_score, 1),
        "new_recent": new_recent,
        "resolved_recent": resolved_recent,
    }
