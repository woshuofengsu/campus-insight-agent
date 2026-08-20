"""通知系统 — 闭环反馈用的持久化站内通知。

触发点:
  - 网格员更新工单状态 → 通知上报人
  - 网格员回复/采纳提案 → 通知提案人
  - 健康告警 → 通知所有用户（以后做）

侧边栏角标 + 通知中心页面展示。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)


def create_notification(user_id: int, type_: str, title: str,
                        content: str = "", related_id: int | None = None) -> int:
    """给某个用户发一条通知，返回新通知的 ID。"""
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
    """广播给所有启用的居民用户，返回收件人数。"""
    with get_db() as conn:
        residents = conn.execute(
            "SELECT id FROM user_profile WHERE role = 'resident' AND is_active = 1"
        ).fetchall()
        count = 0
        for s in residents:
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
    """网格员改工单状态时，通知上报人。

    先按工单的 author/reporter_id 字段找到上报人，再查用户表拿到通知对象。
    """
    with get_db() as conn:
        issue = conn.execute(
            "SELECT title, author, reporter_id FROM community_issues WHERE id = ?", (issue_id,)
        ).fetchone()
        if not issue:
            return

        issue_title = issue["title"] or f"工单 #{issue_id}"
        author = (issue["author"] or "").strip()
        reporter_id = issue["reporter_id"]

        # 找上报人：优先用 reporter_id（匿名上报也稳、不泄露隐私），
        # 老数据没有就用 author 字符串去匹配。
        reporter = None
        if reporter_id:
            reporter = conn.execute(
                "SELECT id, username, name FROM user_profile "
                "WHERE id = ? AND is_active = 1 LIMIT 1",
                (reporter_id,),
            ).fetchone()
        if not reporter and author:
            reporter = conn.execute(
                "SELECT id, username, name FROM user_profile "
                "WHERE (resident_id = ? OR name = ? OR username = ?) AND is_active = 1 "
                "LIMIT 1",
                (author, author, author),
            ).fetchone()

        if not reporter:
            _log.debug("notify_issue_status_change: 工单 #%d 找不到上报人", issue_id)
            return  # 找不到上报人，跳过通知

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
    """网格员回复/采纳提案时，通知提案人。"""
    with get_db() as conn:
        prop = conn.execute(
            "SELECT title, author, reporter_id FROM proposals WHERE id = ?", (proposal_id,)
        ).fetchone()
        if not prop:
            return

        prop_title = prop["title"] or f"提案 #{proposal_id}"
        author = (prop["author"] or "").strip()
        reporter_id = prop["reporter_id"]

        proposer = None
        if reporter_id:
            proposer = conn.execute(
                "SELECT id FROM user_profile WHERE id = ? AND is_active = 1 LIMIT 1",
                (reporter_id,),
            ).fetchone()
        if not proposer and author:
            proposer = conn.execute(
                "SELECT id FROM user_profile "
                "WHERE (resident_id = ? OR name = ? OR username = ?) AND is_active = 1 "
                "LIMIT 1",
                (author, author, author),
            ).fetchone()

        if not proposer:
            _log.debug("notify_proposal_status_change: 提案 #%d 找不到提案人", proposal_id)
            return

        status_config = {
            "已回应": (
                "💬 收到回复",
                f"你的提案「{prop_title}」收到了网格员回复"
                + (f"：{response_text[:100]}" if response_text else "。"),
            ),
            "已采纳": (
                "✅ 已被采纳",
                f"你的提案「{prop_title}」已被社区采纳！"
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


def get_notifications(user_id: int, unread_only: bool = False,
                      limit: int = 50) -> list[dict]:
    """查用户的通知，新的在前。"""
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
    """查用户未读通知数。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM notifications "
            "WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
        return row["cnt"] if row else 0


def mark_read(notification_id: int) -> None:
    """把单条通知标成已读。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,),
        )
        conn.commit()


def mark_all_read(user_id: int) -> int:
    """把用户所有通知标成已读，返回更新的行数。"""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (user_id,),
        )
        conn.commit()
        return cur.rowcount


def log_activity(actor: str, action: str, target_type: str = "",
                 target_id: int | None = None, target_title: str = "",
                 detail: str = "", module: str = "",
                 before_value: str = "", after_value: str = "") -> int:
    """记一条留痕。返回新日志 ID。

    文档要求全局留痕字段：操作人、时间、类型、前值、后值、关联编号、模块来源。
    before_value / after_value 记录变更前/后值（状态、分类、紧急程度等），
    module 记录模块来源（报修/提案/天气/疾病预防/通知/老年端/政策问答）。
    """
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO activity_log (actor, action, target_type, target_id, "
            "target_title, detail, module, before_value, after_value) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (actor, action, target_type, target_id, target_title, detail,
             module, before_value, after_value),
        )
        conn.commit()
        return cur.lastrowid


def log_exception(module: str, error: str, detail: str = "") -> int:
    """记录系统异常日志（单独保存 7 天，不混入业务留痕）。返回日志 ID。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO exception_log (module, error, detail) VALUES (?, ?, ?)",
            (module, (error or "")[:500], (detail or "")[:2000]),
        )
        conn.commit()
        return cur.lastrowid


def clean_exception_log(days: int = 7) -> int:
    """清理超过 N 天的异常日志（scheduler 定时调用）。返回删除条数。"""
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM exception_log WHERE created_at < datetime('now', '-{days} days')"
        )
        conn.commit()
        return cur.rowcount


def get_activity_feed(limit: int = 20) -> list[dict]:
    """查最近动态，新的在前。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_activity_summary() -> dict:
    """查今天的动态计数。"""
    with get_db() as conn:
        today_issues = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE date(created_at, 'localtime') = date('now', 'localtime') "
            "AND action = '上报问题'"
        ).fetchone()
        today_resolved = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE date(created_at, 'localtime') = date('now', 'localtime') "
            "AND action = '解决问题'"
        ).fetchone()
        today_proposals = conn.execute(
            "SELECT COUNT(*) as cnt FROM activity_log "
            "WHERE date(created_at, 'localtime') = date('now', 'localtime') "
            "AND action = '提交提案'"
        ).fetchone()
        return {
            "today_issues": today_issues["cnt"] if today_issues else 0,
            "today_resolved": today_resolved["cnt"] if today_resolved else 0,
            "today_proposals": today_proposals["cnt"] if today_proposals else 0,
        }


def seed_activity_from_existing() -> dict:
    """用现有的 community_issues 和 proposals 回填 activity_log。

    幂等——已有对应日志记录的条目会跳过。返回各类创建的数量。
    """
    result = {"issues": 0, "resolutions": 0, "proposals": 0}

    with get_db() as conn:
        # 工单上报
        issues = conn.execute(
            "SELECT id, title, author, category, location, status, "
            "reported_at, resolved_at FROM community_issues "
            "WHERE author IS NOT NULL AND author != '' AND author != '系统感知'"
        ).fetchall()

        for issue in issues:
            iid = issue["id"]
            author = issue["author"] or "居民"
            title = issue["title"] or ""
            detail = f'{issue["category"]} · {issue["location"]}' if issue["location"] else issue["category"]

            # 看这条是不是已经记过日志了
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

            # 工单解决
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
                        ("物业维修班", iid, title, detail, issue["resolved_at"]),
                    )
                    result["resolutions"] += 1

        conn.commit()

        # 提案
        proposals = conn.execute(
            "SELECT id, title, author, category, status, response_text, created_at "
            "FROM proposals WHERE author IS NOT NULL AND author != ''"
        ).fetchall()

        for prop in proposals:
            pid = prop["id"]
            author = prop["author"] or "居民"
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

            # 提案回复/采纳
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
                        ("网格员", action, pid, title, cat, prop["created_at"]),
                    )
                    result["proposals"] += 1

        conn.commit()

    return result
