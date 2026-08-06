# data/db_notifications.py
"""Notification system — persistent notifications for the feedback loop.

Triggers:
  - Teacher updates issue status → notifies the reporter
  - Teacher responds/adopts proposal → notifies the author
  - Health alerts → notifies all users (future)

Displayed in sidebar badge + notification center page.
"""
from data.db_core import get_db


# ── Create ──

def create_notification(user_id: int, type_: str, title: str,
                        content: str = "", related_id: int | None = None) -> int:
    """Create a notification for a specific user. Returns the new notification ID."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO notifications (user_id, type, title, content, related_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, type_, title, content, related_id),
        )
        conn.commit()
        return cur.lastrowid


def broadcast_notification(type_: str, title: str,
                           content: str = "", related_id: int | None = None) -> int:
    """Broadcast a notification to all active student users. Returns count of recipients."""
    with get_db() as conn:
        students = conn.execute(
            "SELECT id FROM user_profile WHERE role = 'student' AND is_active = 1"
        ).fetchall()
        count = 0
        for s in students:
            conn.execute(
                "INSERT INTO notifications (user_id, type, title, content, related_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (s["id"], type_, title, content, related_id),
            )
            count += 1
        conn.commit()
    return count


def notify_issue_status_change(issue_id: int, new_status: str,
                                reporter_username: str = "") -> None:
    """When teacher changes issue status, notify the reporter.

    Resolves the reporter from the issue's author field, then looks up
    the user by that author name/student_id.
    """
    with get_db() as conn:
        issue = conn.execute(
            "SELECT title, author FROM campus_issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if not issue:
            return

        issue_title = issue["title"] or f"工单 #{issue_id}"
        author = (issue["author"] or "").strip()

        # Resolve author to user_id — try student_id, name, then username
        reporter = None
        if author:
            reporter = conn.execute(
                "SELECT id, username, name FROM user_profile "
                "WHERE (student_id = ? OR name = ? OR username = ?) AND is_active = 1 "
                "LIMIT 1",
                (author, author, author),
            ).fetchone()

        if not reporter:
            return  # can't find the reporter — skip notification

        status_cn = {
            "处理中": ("🔄 处理中", f"你上报的「{issue_title}」已被受理，正在处理中。"),
            "已解决": ("✅ 已解决", f"你上报的「{issue_title}」已解决！感谢你的反馈。"),
            "待处理": ("🔄 重新打开", f"你上报的「{issue_title}」已被重新打开，将再次处理。"),
        }
        notify_title, notify_content = status_cn.get(
            new_status,
            (f"📋 状态更新", f"你上报的「{issue_title}」状态已更新为「{new_status}」。"),
        )

        create_notification(
            reporter["id"], "issue_update", notify_title,
            notify_content, related_id=issue_id,
        )


def notify_proposal_status_change(proposal_id: int, new_status: str,
                                   response_text: str = "") -> None:
    """When teacher responds/adopts proposal, notify the author."""
    with get_db() as conn:
        prop = conn.execute(
            "SELECT title, author FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not prop:
            return

        prop_title = prop["title"] or f"提案 #{proposal_id}"
        author = (prop["author"] or "").strip()

        proposer = None
        if author:
            proposer = conn.execute(
                "SELECT id FROM user_profile "
                "WHERE (student_id = ? OR name = ? OR username = ?) AND is_active = 1 "
                "LIMIT 1",
                (author, author, author),
            ).fetchone()

        if not proposer:
            return

        status_config = {
            "已回应": (
                "💬 收到回复",
                f"你的提案「{prop_title}」收到了老师回复"
                + (f"：{response_text[:100]}" if response_text else "。"),
            ),
            "已采纳": (
                "✅ 已被采纳",
                f"你的提案「{prop_title}」已被学校采纳！"
                + (f" 回复：{response_text[:100]}" if response_text else ""),
            ),
            "已实施": (
                "🎉 已实施",
                f"你的提案「{prop_title}」已经落地实施！感谢你的建言。",
            ),
        }
        notify_title, notify_content = status_config.get(
            new_status,
            (f"📋 状态更新", f"你的提案「{prop_title}」状态已更新为「{new_status}」。"),
        )

        create_notification(
            proposer["id"], "proposal_update", notify_title,
            notify_content, related_id=proposal_id,
        )


# ── Query ──

def get_notifications(user_id: int, unread_only: bool = False,
                      limit: int = 50) -> list[dict]:
    """Get notifications for a user, newest first."""
    with get_db() as conn:
        if unread_only:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE user_id = ? AND is_read = 0 "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM notifications WHERE user_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_unread_count(user_id: int) -> int:
    """Get count of unread notifications for a user."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM notifications "
            "WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
        return row["cnt"] if row else 0


def mark_read(notification_id: int) -> None:
    """Mark a single notification as read."""
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,),
        )
        conn.commit()


def mark_all_read(user_id: int) -> int:
    """Mark all notifications for a user as read. Returns count of updated rows."""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (user_id,),
        )
        conn.commit()
        return cur.rowcount


# ── Activity Log ──

def log_activity(actor: str, action: str, target_type: str = "",
                 target_id: int | None = None, target_title: str = "",
                 detail: str = "") -> int:
    """Record an activity for the timeline. Returns the new log ID."""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO activity_log (actor, action, target_type, target_id, "
            "target_title, detail) VALUES (?, ?, ?, ?, ?, ?)",
            (actor, action, target_type, target_id, target_title, detail),
        )
        conn.commit()
        return cur.lastrowid


def get_activity_feed(limit: int = 20) -> list[dict]:
    """Get recent activity, newest first."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_activity_summary() -> dict:
    """Get today's activity counts."""
    with get_db() as conn:
        today_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE date(created_at) = date('now', 'localtime') "
            "AND action = '上报问题'"
        ).fetchone()
        today_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE date(created_at) = date('now', 'localtime') "
            "AND action = '解决问题'"
        ).fetchone()
        today_proposals = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE date(created_at) = date('now', 'localtime') "
            "AND action = '提交提案'"
        ).fetchone()
        return {
            "today_issues": today_issues["cnt"] if today_issues else 0,
            "today_resolved": today_resolved["cnt"] if today_resolved else 0,
            "today_proposals": today_proposals["cnt"] if today_proposals else 0,
        }


def seed_activity_from_existing() -> dict:
    """Backfill activity_log from existing campus_issues and proposals.

    Idempotent — skips entries that already have corresponding log records.
    Returns counts of what was created.
    """
    result = {"issues": 0, "resolutions": 0, "proposals": 0}

    with get_db() as conn:
        # ── Issue reports ──
        issues = conn.execute(
            "SELECT id, title, author, category, location, status, "
            "reported_at, resolved_at FROM campus_issues "
            "WHERE author IS NOT NULL AND author != '' AND author != '系统感知'"
        ).fetchall()

        for issue in issues:
            iid = issue["id"]
            author = issue["author"] or "同学"
            title = issue["title"] or ""
            detail = f'{issue["category"]} · {issue["location"]}' if issue["location"] else issue["category"]

            # Check if activity already logged
            existing = conn.execute(
                "SELECT COUNT(*) as cnt FROM activity_log "
                "WHERE target_type = 'issue' AND target_id = ? AND action = '上报问题'",
                (iid,),
            ).fetchone()
            if not existing or existing["cnt"] == 0:
                reported_at = issue["reported_at"] or ""
                conn.execute(
                    "INSERT INTO activity_log (actor, action, target_type, target_id, "
                    "target_title, detail, created_at) VALUES (?, '上报问题', 'issue', ?, ?, ?, ?)",
                    (author, iid, title, detail, reported_at),
                )
                result["issues"] += 1

            # ── Resolutions ──
            if issue["status"] == "已解决" and issue["resolved_at"]:
                existing_res = conn.execute(
                    "SELECT COUNT(*) as cnt FROM activity_log "
                    "WHERE target_type = 'issue' AND target_id = ? AND action = '解决问题'",
                    (iid,),
                ).fetchone()
                if not existing_res or existing_res["cnt"] == 0:
                    conn.execute(
                        "INSERT INTO activity_log (actor, action, target_type, target_id, "
                        "target_title, detail, created_at) VALUES (?, '解决问题', 'issue', ?, ?, ?, ?)",
                        ("后勤维修组", iid, title, detail, issue["resolved_at"]),
                    )
                    result["resolutions"] += 1

        conn.commit()

        # ── Proposals ──
        proposals = conn.execute(
            "SELECT id, title, author, category, status, response_text, created_at "
            "FROM proposals WHERE author IS NOT NULL AND author != ''"
        ).fetchall()

        for prop in proposals:
            pid = prop["id"]
            author = prop["author"] or "同学"
            title = prop["title"] or ""
            cat = prop["category"] or ""

            existing = conn.execute(
                "SELECT COUNT(*) as cnt FROM activity_log "
                "WHERE target_type = 'proposal' AND target_id = ? AND action = '提交提案'",
                (pid,),
            ).fetchone()
            if not existing or existing["cnt"] == 0:
                created_at = prop["created_at"] or ""
                conn.execute(
                    "INSERT INTO activity_log (actor, action, target_type, target_id, "
                    "target_title, detail, created_at) VALUES (?, '提交提案', 'proposal', ?, ?, ?, ?)",
                    (author, pid, title, cat, created_at),
                )
                result["proposals"] += 1

            # ── Proposal responses ──
            if prop["status"] in ("已回应", "已采纳") and prop["response_text"]:
                action = "采纳提案" if prop["status"] == "已采纳" else "回复提案"
                existing_resp = conn.execute(
                    "SELECT COUNT(*) as cnt FROM activity_log "
                    "WHERE target_type = 'proposal' AND target_id = ? AND action = ?",
                    (pid, action),
                ).fetchone()
                if not existing_resp or existing_resp["cnt"] == 0:
                    conn.execute(
                        "INSERT INTO activity_log (actor, action, target_type, target_id, "
                        "target_title, detail, created_at) VALUES (?, ?, 'proposal', ?, ?, ?, "
                        "datetime(?, '+1 day'))",
                        ("校方", action, pid, title, cat, prop["created_at"]),
                    )
                    result["proposals"] += 1

        conn.commit()

    return result
