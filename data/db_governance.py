# data/db_governance.py
"""Governance tables — community_issues, proposals, discussion_topics, topic_opinions."""
import hashlib
import logging
from data.db_core import get_db

_log = logging.getLogger(__name__)

# 匿名上报的伪名盐值——与密码盐无关，仅用于生成稳定的匿名标识
_ANON_SALT = "community-insight-anon-2026"


def anonymized_author(identity: str) -> str:
    """Generate a stable pseudonymous author label for anonymous reports.

    Hashes the reporter's identity (reporter_id / resident_id) so the public
    author field never leaks the real identity, while the same reporter's
    anonymous reports still share one consistent label — traceable for the
    closed loop, unlinkable to the real person by other residents.
    """
    if not identity:
        return "匿名居民"
    digest = hashlib.sha256(f"{_ANON_SALT}:{identity}".encode("utf-8")).hexdigest()[:8]
    return f"匿名居民#{digest}"


def _resolve_author(author: str = "") -> str:
    """Auto-fill author from current user profile if empty.

    Priority: resident_id → community+building → name → login_id fallback → "匿名"
    Must match ui.components.resolve_author() logic so that issues reported
    via the Agent are visible on the "我的" page.
    """
    if author:
        return author
    try:
        from data.db_user import get_current_user
        profile = get_current_user()
        rid = (profile.get("resident_id") or "").strip()
        if rid:
            return rid
        community = (profile.get("community") or "").strip()
        building = (profile.get("building") or "").strip()
        if community:
            return f"{community}{building}" if building else community
        name = (profile.get("name") or "").strip()
        if name:
            return name
        # Last resort: use raw user id so it's at least unique per-user
        uid = profile.get("id")
        if uid:
            return f"user_{uid}"
    except Exception:  # log and skip
        _log.warning(
            "_resolve_author: failed to resolve user profile, using id-based fallback"
        )
        # Direct session_state read as final fallback
        try:
            import streamlit as st
            uid = st.session_state.get("_login_user_id")
            if uid:
                return f"user_{uid}"
        except Exception:  # best-effort, skip
            _log.debug("Failed to resolve author from session_state fallback", exc_info=True)
            pass
    return "匿名"


# ── Community Issues ──

def _resolve_reporter_id() -> int | None:
    """Resolve the current user's id for reporter tracking (privacy-safe).

    Kept separate from author display: reporter_id enables closed-loop
    notification even when the author field is anonymized.
    """
    try:
        from data.db_user import get_current_user
        profile = get_current_user()
        return profile.get("id")
    except Exception:  # log and skip
        _log.debug("_resolve_reporter_id: failed to resolve current user", exc_info=True)
        return None


def report_issue(title: str, category: str, location: str = "",
                 description: str = "", urgency: str = "普通",
                 author: str = "", suggested_category: str = "",
                 reporter_id: int | None = None,
                 anonymous: bool = False) -> int:
    """Report a community issue. Returns the new issue ID.

    Args:
        suggested_category: the AI's raw classification (stored for grid-manager review)
        reporter_id: submitting user's id — auto-resolved if omitted
        anonymous: if True, the public author field stores a stable pseudonym
            (anonymized_author) instead of the real identity. The reporter_id is
            still stored separately for closed-loop notification.
    """
    if reporter_id is None:
        reporter_id = _resolve_reporter_id()
    with get_db() as conn:
        if anonymous:
            author = anonymized_author(f"user:{reporter_id}" if reporter_id else "")
        else:
            author = _resolve_author(author)
        cur = conn.execute(
            "INSERT INTO community_issues "
            "(title, category, location, description, urgency, author, "
            " suggested_category, reporter_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (title, category, location, description, urgency, author,
             suggested_category, reporter_id),
        )
        conn.commit()
        iid = cur.lastrowid
    _log.info("report_issue #%d created (reporter_id=%s, category=%s, suggested=%s)",
              iid, reporter_id, category, suggested_category or category)
    # Log activity
    try:
        from data.db_notifications import log_activity
        log_activity(author, "上报问题", "issue", iid, title,
                     f"{category} · {location}" if location else category)
    except Exception:  # log and skip
        _log.debug("log_activity failed for report_issue #%d (non-critical)", iid)
    # Cross-session event memory (personalization)
    try:
        from data.db_memory import remember_event
        remember_event(reporter_id, "report_issue", f"上报了工单 #{iid}「{title[:20]}」")
    except Exception:
        _log.debug("remember_event failed for report_issue #%d", iid)
    return iid


def get_issues(category: str | None = None, status: str | None = None,
               urgency: str | None = None, limit: int = 20) -> list[dict]:
    """Query community issues with optional filters."""
    with get_db() as conn:
        query = "SELECT * FROM community_issues WHERE 1=1"
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
            "SELECT category, COUNT(*) as cnt FROM community_issues GROUP BY category"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM community_issues GROUP BY status"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) as cnt FROM community_issues").fetchone()
        today_new = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues WHERE date(reported_at, 'localtime') = date('now', 'localtime')"
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
            "SELECT * FROM community_issues WHERE author = ? ORDER BY reported_at DESC LIMIT ?",
            (author, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_anonymous_issues(reporter_id: int, limit: int = 50) -> list[dict]:
    """Get the caller's own anonymous issues, resolved by reporter_id.

    Anonymous issues store a pseudonymous author (匿名居民#hash), so the resident
    cannot find them via the normal author-string matching. This queries by
    reporter_id instead — returning only the caller's own anonymous issues without
    exposing any real identity to other residents.
    """
    if not reporter_id:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM community_issues WHERE reporter_id = ? "
            "AND (author = '匿名' OR author LIKE '匿名居民#%') "
            "ORDER BY reported_at DESC LIMIT ?",
            (reporter_id, limit),
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
            "SELECT COUNT(*) as cnt FROM community_issues WHERE author = ?", (author,),
        ).fetchone()
        resolved_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM community_issues WHERE author = ? AND status = '已解决'", (author,),
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


def update_issue_status(issue_id: int, status: str, actor: str = "",
                       processing_note: str = "", assignee: str = "",
                       assignee_id: int | None = None) -> None:
    """Update the status of a community issue. Notifies reporter + logs activity.

    Args:
        issue_id: the issue to update
        status: new status (待处理/处理中/已解决)
        actor: who performed the action (for activity log)
        processing_note: optional note from the grid about the resolution/action
        assignee: optional assignee display name (who is handling this issue)
        assignee_id: optional assignee user id — the stable key for "my todo" filtering
    """
    with get_db() as conn:
        # Fetch issue info before update for notification + activity
        issue = conn.execute(
            "SELECT title, author, category, location FROM community_issues WHERE id = ?",
            (issue_id,),
        ).fetchone()

        if status == "已解决":
            conn.execute(
                "UPDATE community_issues SET status = ?, resolved_at = CURRENT_TIMESTAMP, "
                "satisfaction = '', satisfaction_reason = '', "
                "processing_note = CASE WHEN ? != '' THEN ? ELSE processing_note END, "
                "assignee = CASE WHEN ? != '' THEN ? ELSE assignee END, "
                "assignee_id = CASE WHEN ? IS NOT NULL THEN ? ELSE assignee_id END "
                "WHERE id = ?",
                (status, processing_note, processing_note,
                 assignee, assignee, assignee_id, assignee_id, issue_id),
            )
        else:
            conn.execute(
                "UPDATE community_issues SET status = ?, resolved_at = NULL, "
                "processing_note = CASE WHEN ? != '' THEN ? ELSE processing_note END, "
                "assignee = CASE WHEN ? != '' THEN ? ELSE assignee END, "
                "assignee_id = CASE WHEN ? IS NOT NULL THEN ? ELSE assignee_id END "
                "WHERE id = ?",
                (status, processing_note, processing_note,
                 assignee, assignee, assignee_id, assignee_id, issue_id),
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
                actor or "网格员", action_map.get(status, "更新工单"),
                "issue", issue_id, issue_title,
                f"{issue['category']} · {issue['location']}" if issue["location"] else issue["category"],
            )
        except Exception:  # log and skip
            _log.debug("notify/log_activity failed for issue #%d status change (non-critical)", issue_id)


def set_satisfaction(issue_id: int, value: str, reason: str = "",
                     reopen_on_dissatisfied: bool = True) -> str:
    """Record a resident's satisfaction for a resolved issue.

    Args:
        value: "满意" | "不满意"
        reason: optional free-text reason (especially for "不满意"), stored and
            surfaced to the grid manager so dissatisfaction is actionable.
        reopen_on_dissatisfied: if "不满意", move the issue to "待复核" for the
            grid manager to confirm/驳回 (no longer auto-reopens unilaterally).

    Returns the final status ("已解决" if satisfied, "待复核" if dissatisfied).
    """
    value = value if value in ("满意", "不满意") else "满意"
    reason = (reason or "").strip()
    with get_db() as conn:
        if value == "不满意" and reopen_on_dissatisfied:
            # 进入待复核，由网格员确认是否重开（堵住居民单方面刷单）
            conn.execute(
                "UPDATE community_issues SET satisfaction = ?, satisfaction_reason = ?, "
                "status = '待复核' WHERE id = ?",
                (value, reason, issue_id),
            )
            final_status = "待复核"
        else:
            conn.execute(
                "UPDATE community_issues SET satisfaction = ?, satisfaction_reason = ? WHERE id = ?",
                (value, reason, issue_id),
            )
            final_status = "已解决"
        conn.commit()
    _log.info("set_satisfaction #%d -> %s (reason=%r, status=%s)",
              issue_id, value, reason, final_status)
    # Cross-session event memory (personalization)
    try:
        from data.db_memory import remember_event
        with get_db() as conn:
            _row = conn.execute(
                "SELECT reporter_id FROM community_issues WHERE id = ?", (issue_id,)
            ).fetchone()
        if _row and _row["reporter_id"]:
            remember_event(_row["reporter_id"], "satisfaction", f"对工单 #{issue_id} 评价为{value}")
    except Exception:
        _log.debug("remember_event failed for set_satisfaction #%d", issue_id)
    return final_status


def review_dissatisfaction(issue_id: int, reopen: bool) -> str:
    """Grid manager reviews a resident's "不满意" rating.

    reopen=True  → 确认重开（status='待处理'，保留不满意原因供追踪）。
    reopen=False → 驳回（status='已解决'，保留评价但不重开）。

    Returns the resulting status.
    """
    new_status = "待处理" if reopen else "已解决"
    with get_db() as conn:
        if reopen:
            conn.execute(
                "UPDATE community_issues SET status = '待处理', resolved_at = NULL WHERE id = ?",
                (issue_id,),
            )
        else:
            conn.execute(
                "UPDATE community_issues SET status = '已解决', resolved_at = CURRENT_TIMESTAMP WHERE id = ?",
                (issue_id,),
            )
        conn.commit()
    _log.info("review_dissatisfaction #%d -> %s (reopen=%s)", issue_id, new_status, reopen)
    try:
        from data.db_notifications import notify_issue_status_change, log_activity
        notify_issue_status_change(issue_id, new_status)
        log_activity("网格员", "复核满意度" if reopen else "驳回不满意",
                     "issue", issue_id, "", new_status)
    except Exception:
        _log.debug("notify/log_activity failed for review_dissatisfaction #%d", issue_id)
    return new_status


def get_satisfaction_stats() -> dict:
    """Aggregate satisfaction across resolved issues (for grid-manager dashboard)."""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT "
                "SUM(CASE WHEN satisfaction = '满意' THEN 1 ELSE 0 END) AS satisfied, "
                "SUM(CASE WHEN satisfaction = '不满意' THEN 1 ELSE 0 END) AS dissatisfied "
                "FROM community_issues WHERE satisfaction != ''"
            ).fetchone()
            satisfied = row["satisfied"] or 0
            dissatisfied = row["dissatisfied"] or 0
            total = satisfied + dissatisfied
            return {
                "satisfied": satisfied,
                "dissatisfied": dissatisfied,
                "total": total,
                "rate": round(satisfied / total * 100, 1) if total else None,
            }
    except Exception:
        _log.warning("get_satisfaction_stats failed", exc_info=True)
        return {"satisfied": 0, "dissatisfied": 0, "total": 0, "rate": None}


def get_dissatisfaction_reasons(limit: int = 10) -> list[dict]:
    """Return recently-dissatisfied issues with their reasons (for grid workbench).

    Surfaces the free-text reason residents leave on a 「不满意」 rating, so the
    grid manager can act on the concrete cause instead of just the count.
    """
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title, category, author, satisfaction_reason, resolved_at "
                "FROM community_issues "
                "WHERE satisfaction = '不满意' "
                "ORDER BY resolved_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        _log.warning("get_dissatisfaction_reasons failed", exc_info=True)
        return []


# ── Proposals ──

def create_proposal(title: str, description: str, category: str = "其他",
                     author: str = "", reporter_id: int | None = None) -> int:
    """Create a new community proposal. Returns the new proposal ID."""
    if reporter_id is None:
        reporter_id = _resolve_reporter_id()
    with get_db() as conn:
        author = _resolve_author(author)
        cur = conn.execute(
            "INSERT INTO proposals (title, description, category, author, reporter_id) "
            "VALUES (?,?,?,?,?)",
            (title, description, category, author, reporter_id),
        )
        conn.commit()
        pid = cur.lastrowid
    try:
        from data.db_notifications import log_activity
        log_activity(author, "提交提案", "proposal", pid, title, category)
    except Exception:  # log and skip
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
        log_activity(actor or "居民", "附议提案", "proposal", proposal_id,
                     row["title"] if row else "", f"共 {new_count} 人附议")
    except Exception:  # log and skip
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
                actor or "网格员", action_map.get(status, "更新提案"),
                "proposal", proposal_id, prop["title"], prop["category"],
            )
        except Exception:  # log and skip
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

def add_opinion(topic_id: int, content: str, participant_label: str = "匿名居民") -> int:
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
