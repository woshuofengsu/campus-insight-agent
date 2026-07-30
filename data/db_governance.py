# data/db_governance.py
"""Governance tables — campus_issues, proposals, discussion_topics, topic_opinions."""
import logging
from data.db_core import get_db, resolve_author

_log = logging.getLogger(__name__)


def _resolve_author(author: str = "") -> str:
    """Auto-fill author from current user profile if empty.

    Priority: student_id → school+grade → name → login_id fallback → "匿名"
    Must match ui.components.resolve_author() logic so that issues reported
    via the Agent are visible on the "我的" page.
    """
    if author:
        return author
    try:
        from data.db_user import get_current_user
        profile = get_current_user()
        sid = (profile.get("student_id") or "").strip()
        if sid:
            return sid
        school = (profile.get("school") or "").strip()
        grade = (profile.get("grade") or "").strip()
        if school:
            return f"{school}{grade}" if grade else school
        name = (profile.get("name") or "").strip()
        if name:
            return name
        # Last resort: use raw user id so it's at least unique per-user
        uid = profile.get("id")
        if uid:
            return f"user_{uid}"
    except Exception:
        _log.warning(
            "_resolve_author: failed to resolve user profile, using id-based fallback"
        )
        # Direct session_state read as final fallback
        try:
            import streamlit as st
            uid = st.session_state.get("_login_user_id")
            if uid:
                return f"user_{uid}"
        except Exception:
            pass
    return "匿名"


# ── Campus Issues ──

def report_issue(title: str, category: str, location: str = "",
                 description: str = "", urgency: str = "普通",
                 author: str = "") -> int:
    """Report a campus issue. Returns the new issue ID."""
    with get_db() as conn:
        author = _resolve_author(author)
        cur = conn.execute(
            "INSERT INTO campus_issues (title, category, location, description, urgency, author) VALUES (?,?,?,?,?,?)",
            (title, category, location, description, urgency, author),
        )
        conn.commit()
        iid = cur.lastrowid
    # Log activity
    try:
        from data.db_notifications import log_activity
        log_activity(author, "上报问题", "issue", iid, title,
                     f"{category} · {location}" if location else category)
    except Exception:
        _log.debug("log_activity failed for report_issue #%d (non-critical)", iid)
    return iid


def get_issues(category: str | None = None, status: str | None = None,
               urgency: str | None = None, limit: int = 20) -> list[dict]:
    """Query campus issues with optional filters."""
    with get_db() as conn:
        query = "SELECT * FROM campus_issues WHERE 1=1"
        params: list = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        if urgency:
            query += " AND urgency = ?"
            params.append(urgency)
        query += " ORDER BY reported_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_issues_stats() -> dict:
    """Get issue statistics for dashboard: counts by category and status."""
    with get_db() as conn:
        by_category = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM campus_issues GROUP BY category"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM campus_issues GROUP BY status"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as cnt FROM campus_issues").fetchone()
        today_new = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues WHERE date(reported_at) = date('now', 'localtime')"
        ).fetchone()
        return {
            "total": total["cnt"] if total else 0,
            "by_category": {r["category"]: r["cnt"] for r in by_category},
            "by_status": {r["status"]: r["cnt"] for r in by_status},
            "today_new": today_new["cnt"] if today_new else 0,
        }


def get_my_issues(author: str, limit: int = 50) -> list[dict]:
    """Get issues reported by a specific author."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM campus_issues WHERE author = ? ORDER BY reported_at DESC LIMIT ?",
            (author, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_proposals(author: str, limit: int = 50) -> list[dict]:
    """Get proposals created by a specific author."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE author = ? ORDER BY created_at DESC LIMIT ?",
            (author, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_stats(author: str) -> dict:
    """Get participation stats for a specific author."""
    with get_db() as conn:
        total_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues WHERE author = ?", (author,),
        ).fetchone()
        resolved_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM campus_issues WHERE author = ? AND status = '已解决'", (author,),
        ).fetchone()
        total_proposals = conn.execute(
            "SELECT COUNT(*) as cnt FROM proposals WHERE author = ?", (author,),
        ).fetchone()
        adopted_proposals = conn.execute(
            "SELECT COUNT(*) as cnt FROM proposals WHERE author = ? AND status IN ('已采纳','已实施')", (author,),
        ).fetchone()
        return {
            "total_issues": total_issues["cnt"] if total_issues else 0,
            "resolved_issues": resolved_issues["cnt"] if resolved_issues else 0,
            "total_proposals": total_proposals["cnt"] if total_proposals else 0,
            "adopted_proposals": adopted_proposals["cnt"] if adopted_proposals else 0,
        }


def update_issue_status(issue_id: int, status: str, actor: str = "") -> None:
    """Update the status of a campus issue. Notifies reporter + logs activity."""
    with get_db() as conn:
        # Fetch issue info before update for notification + activity
        issue = conn.execute(
            "SELECT title, author, category, location FROM campus_issues WHERE id = ?",
            (issue_id,),
        ).fetchone()

        if status == "已解决":
            conn.execute(
                "UPDATE campus_issues SET status = ?, resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, issue_id),
            )
        else:
            conn.execute(
                "UPDATE campus_issues SET status = ?, resolved_at = NULL WHERE id = ?",
                (status, issue_id),
            )
        conn.commit()

    # ── Notify reporter + log activity (outside transaction) ──
    if issue:
        issue_title = issue["title"] or ""
        try:
            from data.db_notifications import notify_issue_status_change, log_activity
            notify_issue_status_change(issue_id, status)
            action_map = {
                "处理中": "开始处理", "已解决": "解决问题",
                "待处理": "重新打开",
            }
            log_activity(
                actor or "教师", action_map.get(status, "更新工单"),
                "issue", issue_id, issue_title,
                f"{issue['category']} · {issue['location']}" if issue["location"] else issue["category"],
            )
        except Exception:
            _log.debug("notify/log_activity failed for issue #%d status change (non-critical)", issue_id)


# ── Proposals ──

def create_proposal(title: str, description: str, category: str = "其他",
                     author: str = "") -> int:
    """Create a new campus proposal. Returns the new proposal ID."""
    with get_db() as conn:
        author = _resolve_author(author)
        cur = conn.execute(
            "INSERT INTO proposals (title, description, category, author) VALUES (?,?,?,?)",
            (title, description, category, author),
        )
        conn.commit()
        pid = cur.lastrowid
    try:
        from data.db_notifications import log_activity
        log_activity(author, "提交提案", "proposal", pid, title, category)
    except Exception:
        _log.debug("log_activity failed for create_proposal #%d (non-critical)", pid)
    return pid


def get_proposals(category: str | None = None, status: str | None = None,
                  sort_by: str = "supporters", limit: int = 20) -> list[dict]:
    """Query proposals with optional filters and sorting."""
    with get_db() as conn:
        query = "SELECT * FROM proposals WHERE 1=1"
        params: list = []
        if category:
            query += " AND category = ?"
            params.append(category)
        if status:
            query += " AND status = ?"
            params.append(status)
        order = "supporter_count DESC" if sort_by == "supporters" else "created_at DESC"
        query += f" ORDER BY {order} LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def support_proposal(proposal_id: int, actor: str = "") -> int:
    """Add one supporter to a proposal. Returns new supporter count."""
    with get_db() as conn:
        conn.execute(
            "UPDATE proposals SET supporter_count = supporter_count + 1 WHERE id = ?",
            (proposal_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT supporter_count, title FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        new_count = row["supporter_count"] if row else 0
    try:
        from data.db_notifications import log_activity
        log_activity(actor or "同学", "附议提案", "proposal", proposal_id,
                     row["title"] if row else "", f"共 {new_count} 人附议")
    except Exception:
        _log.debug("log_activity failed for support_proposal #%d (non-critical)", proposal_id)
    return new_count


def update_proposal_status(proposal_id: int, status: str,
                           response_text: str = "", actor: str = "") -> None:
    """Update proposal status and optionally add a response. Notifies author + logs."""
    with get_db() as conn:
        # Fetch before update
        prop = conn.execute(
            "SELECT title, author, category FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()

        if response_text:
            conn.execute(
                "UPDATE proposals SET status = ?, response_text = ? WHERE id = ?",
                (status, response_text, proposal_id),
            )
        else:
            conn.execute(
                "UPDATE proposals SET status = ? WHERE id = ?",
                (status, proposal_id),
            )
        conn.commit()

    if prop:
        try:
            from data.db_notifications import notify_proposal_status_change, log_activity
            notify_proposal_status_change(proposal_id, status, response_text)
            action_map = {
                "已回应": "回复提案", "已采纳": "采纳提案", "已实施": "实施提案",
            }
            log_activity(
                actor or "教师", action_map.get(status, "更新提案"),
                "proposal", proposal_id, prop["title"], prop["category"],
            )
        except Exception:
            _log.debug("notify/log_activity failed for proposal #%d status change (non-critical)", proposal_id)


def get_proposals_stats() -> dict:
    """Get proposal statistics."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM proposals").fetchone()
        by_category = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM proposals GROUP BY category"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status"
        ).fetchall()
        return {
            "total": total["cnt"] if total else 0,
            "by_category": {r["category"]: r["cnt"] for r in by_category},
            "by_status": {r["status"]: r["cnt"] for r in by_status},
        }


# ── Discussion Topics ──

def create_topic(title: str, description: str, category: str = "",
                  created_by_agent: bool = True) -> int:
    """Create a new discussion topic. Returns the new topic ID."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO discussion_topics (title, description, category, created_by_agent) VALUES (?,?,?,?)",
            (title, description, category, int(created_by_agent)),
        )
        conn.commit()
        return cur.lastrowid


def get_active_topics(limit: int = 10) -> list[dict]:
    """Get currently active discussion topics."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM discussion_topics WHERE is_active = 1 ORDER BY participant_count DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def close_topic(topic_id: int) -> None:
    """Close/end a discussion topic."""
    with get_db() as conn:
        conn.execute(
            "UPDATE discussion_topics SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE id = ?",
            (topic_id,),
        )
        conn.commit()


def increment_topic_participants(topic_id: int) -> int:
    """Increment participant count for a topic."""
    with get_db() as conn:
        conn.execute(
            "UPDATE discussion_topics SET participant_count = participant_count + 1 WHERE id = ?",
            (topic_id,),
        )
        conn.commit()
        row = conn.execute(
            "SELECT participant_count FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        return row["participant_count"] if row else 0


# ── Topic Opinions ──

def add_opinion(topic_id: int, content: str, participant_label: str = "匿名学生") -> int:
    """Add an opinion to a discussion topic. Returns the opinion ID."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO topic_opinions (topic_id, content, participant_label) VALUES (?,?,?)",
            (topic_id, content, participant_label),
        )
        conn.commit()
        conn.execute(
            "UPDATE discussion_topics SET participant_count = participant_count + 1 WHERE id = ?",
            (topic_id,),
        )
        conn.commit()
        return cur.lastrowid


def get_opinions_by_topic(topic_id: int, limit: int = 50) -> list[dict]:
    """Get opinions for a specific topic."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM topic_opinions WHERE topic_id = ? ORDER BY created_at DESC LIMIT ?",
            (topic_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_opinion_summary(topic_id: int) -> dict:
    """Get summary stats for a topic's opinions."""
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM topic_opinions WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        topic = conn.execute(
            "SELECT * FROM discussion_topics WHERE id = ?", (topic_id,)
        ).fetchone()
        recent = conn.execute(
            "SELECT * FROM topic_opinions WHERE topic_id = ? ORDER BY created_at DESC LIMIT 5",
            (topic_id,),
        ).fetchall()
        return {
            "topic": dict(topic) if topic else {},
            "total_opinions": total["cnt"] if total else 0,
            "recent_opinions": [dict(r) for r in recent],
        }


def get_opinion_summaries_batch(topic_ids: list[int]) -> dict[int, dict]:
    """Get opinion counts for multiple topics in a single query — eliminates N+1.

    Returns {topic_id: {"total_opinions": int, "topic_title": str}, ...}
    """
    if not topic_ids:
        return {}
    with get_db() as conn:
        placeholders = ",".join("?" for _ in topic_ids)
        # Count opinions per topic in one query
        count_rows = conn.execute(
            f"SELECT topic_id, COUNT(*) as cnt FROM topic_opinions "
            f"WHERE topic_id IN ({placeholders}) GROUP BY topic_id",
            topic_ids,
        ).fetchall()
        counts = {r["topic_id"]: r["cnt"] for r in count_rows}
        # Get topic titles in one query
        topic_rows = conn.execute(
            f"SELECT id, title FROM discussion_topics "
            f"WHERE id IN ({placeholders})",
            topic_ids,
        ).fetchall()
        titles = {r["id"]: r["title"] for r in topic_rows}
        result = {}
        for tid in topic_ids:
            result[tid] = {
                "total_opinions": counts.get(tid, 0),
                "topic_title": titles.get(tid, ""),
            }
        return result
