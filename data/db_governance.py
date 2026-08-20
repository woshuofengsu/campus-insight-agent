"""治理相关表 — 社区工单、提案、话题讨论、话题意见。"""
import hashlib
import logging
from data.db_core import get_db

_log = logging.getLogger(__name__)

# 匿名上报的伪名盐值——与密码盐无关，仅用于生成稳定的匿名标识
_ANON_SALT = "community-insight-anon-2026"


def anonymized_author(identity: str) -> str:
    """给匿名上报生成一个稳定的伪名标签。

    把上报人身份（reporter_id / resident_id）哈希一下，公开的 author 字段
    就不会泄露真实身份；同一个人的匿名上报又能共用同一个标签——闭环能追踪，
    别的居民对不上号。
    """
    if not identity:
        return "匿名居民"
    digest = hashlib.sha256(f"{_ANON_SALT}:{identity}".encode("utf-8")).hexdigest()[:8]
    return f"匿名居民#{digest}"


def _resolve_author(author: str = "") -> str:
    """author 为空时，从当前用户资料自动填。

    优先级: resident_id → community+building → name → login_id 兜底 → "匿名"
    必须和 ui.components.resolve_author() 的逻辑保持一致，否则 Agent 上报的
    工单在「我的」页面看不到。
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
        # 最后兜底：直接用用户 ID，至少每人唯一
        uid = profile.get("id")
        if uid:
            return f"user_{uid}"
    except Exception:  # 记个日志跳过
        _log.warning(
            "_resolve_author: 解析用户资料失败，退回用 ID 兜底"
        )
        # 最后的兜底：直接读 session_state
        try:
            import streamlit as st
            uid = st.session_state.get("_login_user_id")
            if uid:
                return f"user_{uid}"
        except Exception:  # 尽力而为，失败就算了
            _log.debug("从 session_state 兜底解析 author 也失败", exc_info=True)
            pass
    return "匿名"


# 社区工单

def _resolve_reporter_id() -> int | None:
    """解析当前用户的 ID，用于记录上报人（不泄露隐私）。

    和展示用的 author 分开存：author 被匿名化之后，reporter_id 还能用来发
    闭环通知。
    """
    try:
        from data.db_user import get_current_user
        profile = get_current_user()
        return profile.get("id")
    except Exception:  # 记个日志跳过
        _log.debug("_resolve_reporter_id: 解析当前用户失败", exc_info=True)
        return None


def report_issue(title: str, category: str, location: str = "",
                 description: str = "", urgency: str = "普通",
                 author: str = "", suggested_category: str = "",
                 reporter_id: int | None = None,
                 anonymous: bool = False) -> int:
    """上报一条社区工单，返回新工单 ID。

    Args:
        suggested_category: AI 的原始分类结果（存下来给网格员复核用）
        reporter_id: 上报人的用户 ID — 不传就自动解析
        anonymous: 为 True 时，公开的 author 字段存稳定伪名（anonymized_author）
            而不是真实身份；reporter_id 仍然单独存一份，用于闭环通知。
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
    _log.info("report_issue 已创建工单 #%d (reporter_id=%s, category=%s, suggested=%s)",
              iid, reporter_id, category, suggested_category or category)
    # 记一条活动日志
    try:
        from data.db_notifications import log_activity
        log_activity(author, "上报问题", "issue", iid, title,
                     f"{category} · {location}" if location else category)
    except Exception:  # 记个日志跳过
        _log.debug("report_issue #%d 记活动日志失败（不影响）", iid)
    # 记到跨会话事件记忆（个性化用）
    try:
        from data.db_memory import remember_event
        remember_event(reporter_id, "report_issue", f"上报了工单 #{iid}「{title[:20]}」")
    except Exception:
        _log.debug("report_issue #%d 记事件记忆失败", iid)
    return iid


def get_issues(category: str | None = None, status: str | None = None,
               urgency: str | None = None, limit: int = 20) -> list[dict]:
    """按条件查社区工单，条件都可选。"""
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
    """给看板查工单统计：按分类和状态计数。

    状态字段已升级为报修 11 状态机，这里同时保留原始新状态键和
    聚合旧键（待处理/处理中/已解决），让老看板不感知也能正常统计。
    """
    # 新状态 → 旧三态聚合（兼容老看板）
    _AGG = {
        "待审核": "待处理", "退回补充信息": "待处理", "已审核待派单": "待处理",
        "已派单": "处理中", "处理中": "处理中", "待协商": "处理中",
        "处理结束": "已解决", "已关闭": "已解决", "已转出": "已解决", "已撤回": "已解决",
    }
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
        raw = {r["status"]: r["cnt"] for r in by_status}
        agg = {"待处理": 0, "处理中": 0, "已解决": 0}
        for s, cnt in raw.items():
            agg[s] = cnt  # 保留原始新状态键
            key = _AGG.get(s)
            if key:
                agg[key] = agg.get(key, 0) + cnt
        return {
            "total": total["cnt"] if total else 0,
            "by_category": {r["category"]: r["cnt"] for r in by_category},
            "by_status": agg,
            "today_new": today_new["cnt"] if today_new else 0,
        }


def get_my_issues(author: str, limit: int = 50) -> list[dict]:
    """查某个上报人的工单。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM community_issues WHERE author = ? ORDER BY reported_at DESC LIMIT ?",
            (author, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_anonymous_issues(reporter_id: int, limit: int = 50) -> list[dict]:
    """按 reporter_id 查当前用户自己的匿名工单。

    匿名工单的 author 是伪名（匿名居民#hash），按作者名匹配找不到自己那份，
    所以改用 reporter_id 查——只返回自己的匿名工单，也不暴露别人的身份。
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
    """查某个作者创建的提案。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM proposals WHERE author = ? ORDER BY created_at DESC LIMIT ?",
            (author, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_my_stats(author: str) -> dict:
    """查某个作者的参与统计。"""
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
    """更新工单状态，并通知上报人 + 记活动日志。

    Args:
        issue_id: 要更新的工单
        status: 新状态（待处理/处理中/已解决）
        actor: 操作人（用于活动日志）
        processing_note: 网格员的处理备注（可选）
        assignee: 处理人显示名（可选）
        assignee_id: 处理人用户 ID（可选）——「我的待办」按这个稳定键过滤
    """
    with get_db() as conn:
        # 更新前先把工单信息取出来，通知和日志要用
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

    # 通知上报人 + 记日志（放在事务外面）
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
        except Exception:  # 记个日志跳过
            _log.debug("工单 #%d 状态变更时通知/记日志失败（不影响）", issue_id)


def set_satisfaction(issue_id: int, value: str, reason: str = "",
                     reopen_on_dissatisfied: bool = True) -> str:
    """记录居民对已解决工单的满意度评价。

    Args:
        value: "满意" | "不满意"
        reason: 自由填写的理由（尤其「不满意」时），存下来展示给网格员，
            让不满有处着手。
        reopen_on_dissatisfied: 「不满意」时把工单挪到「待复核」，由网格员
            确认是否重开（不再单方面自动重开）。

    返回最终状态（满意是「已解决」，不满意是「待复核」）。
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
    _log.info("set_satisfaction 工单 #%d -> %s (reason=%r, status=%s)",
              issue_id, value, reason, final_status)
    # 记到跨会话事件记忆（个性化用）
    try:
        from data.db_memory import remember_event
        with get_db() as conn:
            _row = conn.execute(
                "SELECT reporter_id FROM community_issues WHERE id = ?", (issue_id,)
            ).fetchone()
        if _row and _row["reporter_id"]:
            remember_event(_row["reporter_id"], "satisfaction", f"对工单 #{issue_id} 评价为{value}")
    except Exception:
        _log.debug("set_satisfaction 工单 #%d 记事件记忆失败", issue_id)
    return final_status


def review_dissatisfaction(issue_id: int, reopen: bool) -> str:
    """网格员复核居民的「不满意」评价。

    reopen=True  → 确认重开（status='待处理'，保留不满意原因供追踪）。
    reopen=False → 驳回（status='已解决'，保留评价但不重开）。

    返回最终状态。
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
    _log.info("review_dissatisfaction 工单 #%d -> %s (reopen=%s)", issue_id, new_status, reopen)
    try:
        from data.db_notifications import notify_issue_status_change, log_activity
        notify_issue_status_change(issue_id, new_status)
        log_activity("网格员", "复核满意度" if reopen else "驳回不满意",
                     "issue", issue_id, "", new_status)
    except Exception:
        _log.debug("review_dissatisfaction 工单 #%d 通知/记日志失败", issue_id)
    return new_status


def get_satisfaction_stats() -> dict:
    """汇总已解决工单的满意度（给网格员看板）。"""
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
        _log.warning("get_satisfaction_stats 统计失败", exc_info=True)
        return {"satisfied": 0, "dissatisfied": 0, "total": 0, "rate": None}


def get_dissatisfaction_reasons(limit: int = 10) -> list[dict]:
    """查最近被「不满意」的工单和理由（给网格员工作台）。

    把居民在「不满意」评价里填的自由文本理由展示出来，网格员能针对具体
    原因处理，而不是只看个数字。
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
        _log.warning("get_dissatisfaction_reasons 查询失败", exc_info=True)
        return []


# 提案

def create_proposal(title: str, description: str, category: str = "其他",
                     author: str = "", reporter_id: int | None = None) -> int:
    """新建一条社区提案，返回新提案 ID。"""
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
    except Exception:  # 记个日志跳过
        _log.debug("create_proposal #%d 记活动日志失败（不影响）", pid)
    return pid


def get_proposals(category: str | None = None, status: str | None = None,
                  sort_by: str = "supporters", limit: int = 20) -> list[dict]:
    """按条件查提案，支持排序。"""
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
    """给提案加一个附议，返回新的附议人数。"""
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
    except Exception:  # 记个日志跳过
        _log.debug("support_proposal #%d 记活动日志失败（不影响）", proposal_id)
    return new_count


def update_proposal_status(proposal_id: int, status: str,
                           response_text: str = "", actor: str = "") -> None:
    """更新提案状态，可顺带写回复。通知提案人 + 记日志。"""
    with get_db() as conn:
        # 先取提案信息
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
        except Exception:  # 记个日志跳过
            _log.debug("提案 #%d 状态变更时通知/记日志失败（不影响）", proposal_id)


def get_proposals_stats() -> dict:
    """查提案统计。

    兼容新旧状态：保留原始新状态键，同时聚合成旧三态
    （讨论中/已回应/已采纳），老看板不感知也能正常统计。
    """
    _AGG = {
        "待审核": "讨论中", "退回修改": "讨论中", "待确认公示/私有": "讨论中",
        "公示中": "讨论中", "待执行": "讨论中", "执行中": "已回应",
        "待提案人反馈": "已回应", "已完成": "已采纳", "已结束": "已采纳",
        "重新执行": "已回应", "不予执行": "已关闭",
        "违规下架": "已关闭", "已关闭": "已关闭", "已撤回": "已关闭",
    }
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM proposals").fetchone()
        by_category = conn.execute(
            "SELECT category, COUNT(*) as cnt FROM proposals GROUP BY category"
        ).fetchall()
        by_status = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status"
        ).fetchall()
        raw = {r["status"]: r["cnt"] for r in by_status}
        agg = {"讨论中": 0, "已回应": 0, "已采纳": 0, "已关闭": 0}
        for s, cnt in raw.items():
            agg[s] = cnt  # 保留原始新状态键
            key = _AGG.get(s)
            if key:
                agg[key] = agg.get(key, 0) + cnt
        return {
            "total": total["cnt"] if total else 0,
            "by_category": {r["category"]: r["cnt"] for r in by_category},
            "by_status": agg,
        }


# 话题讨论

def create_topic(title: str, description: str, category: str = "",
                  created_by_agent: bool = True) -> int:
    """新建一个讨论话题，返回新话题 ID。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO discussion_topics (title, description, category, created_by_agent) VALUES (?,?,?,?)",
            (title, description, category, int(created_by_agent)),
        )
        conn.commit()
        return cur.lastrowid


def get_active_topics(limit: int = 10) -> list[dict]:
    """查当前进行中的讨论话题。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM discussion_topics WHERE is_active = 1 ORDER BY participant_count DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def close_topic(topic_id: int) -> None:
    """关闭/结束一个讨论话题。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE discussion_topics SET is_active = 0, ended_at = CURRENT_TIMESTAMP WHERE id = ?",
            (topic_id,),
        )
        conn.commit()


def increment_topic_participants(topic_id: int) -> int:
    """话题参与人数 +1。"""
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


# 话题意见

def add_opinion(topic_id: int, content: str, participant_label: str = "匿名居民") -> int:
    """往话题里加一条意见，返回意见 ID。"""
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
    """查某个话题下的意见。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM topic_opinions WHERE topic_id = ? ORDER BY created_at DESC LIMIT ?",
            (topic_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_opinion_summary(topic_id: int) -> dict:
    """查某个话题意见的汇总统计。"""
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
    """一次查询拿多个话题的意见数——避免 N+1。

    返回 {topic_id: {"total_opinions": int, "topic_title": str}, ...}
    """
    if not topic_ids:
        return {}
    with get_db() as conn:
        placeholders = ",".join("?" for _ in topic_ids)
        # 一条 SQL 把每个话题的意见数查出来
        count_rows = conn.execute(
            f"SELECT topic_id, COUNT(*) as cnt FROM topic_opinions "
            f"WHERE topic_id IN ({placeholders}) GROUP BY topic_id",
            topic_ids,
        ).fetchall()
        counts = {r["topic_id"]: r["cnt"] for r in count_rows}
        # 再一条 SQL 查话题标题
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
