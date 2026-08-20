# data/db_repair.py
"""报修模块数据层 —— 按《01-报修.md》实现完整状态机与审核派单闭环。

状态机（status 字段）：
待审核 → 退回补充信息 → 已审核待派单 → 已派单 → 处理中 → 待居民反馈 → 处理结束
  ↘ 已撤回 / 已关闭 / 待协商 / 已转出
安全隐患走 safety_reminders 表，不进工单状态机。
"""
import json
import re
from data.db_core import get_db
from data.db_notifications import log_activity

MODULE = "报修"

# 全部合法状态（顺序即流转主线）
STATUS_ALL = [
    "待审核", "退回补充信息", "已审核待派单", "已派单", "处理中",
    "待居民反馈", "处理结束", "已撤回", "已关闭", "待协商", "已转出",
]

# 特殊情况关键词
_SAFETY_KEYWORDS = ["燃气泄漏", "煤气泄漏", "电线起火", "着火", "漏电", "冒烟", "起火", "爆炸"]
_VIOLATION_KEYWORDS = ["违规搭建", "违建", "违法改造", "私搭乱建"]
_THIRD_PARTY_KEYWORDS = ["施工方", "施工损坏", "第三方施工", "外面施工"]

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def _validate_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match(phone or ""))


def _status_color(status: str) -> str:
    """状态 → 颜色标签（居民端/负责人端一致）。"""
    colors = {
        "待审核": "黄", "已审核待派单": "蓝", "已派单": "蓝", "处理中": "绿",
        "待居民反馈": "橙", "处理结束": "灰", "已撤回": "灰", "退回补充信息": "红",
        "已关闭": "灰", "待协商": "橙", "已转出": "灰",
    }
    return colors.get(status, "灰")


def detect_special_case(description: str, location: str) -> str:
    """识别特殊情况。返回 'safety' / 'violation' / 'third_party' / ''。"""
    text = (description or "") + (location or "")
    if any(k in text for k in _SAFETY_KEYWORDS):
        return "safety"
    if any(k in text for k in _VIOLATION_KEYWORDS):
        return "violation"
    if any(k in text for k in _THIRD_PARTY_KEYWORDS):
        return "third_party"
    return ""


def create_draft(user_id: int, title: str, category: str, issue_type: str,
                 location: str, description: str, urgency: str,
                 reporter_name: str = "", reporter_phone: str = "",
                 photo_before: str = "[]", is_agent_report: int = 0,
                 agent_name: str = "", agent_phone: str = "", agent_relation: str = "") -> int:
    """保存/更新报修草稿。返回草稿 ID。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO issue_drafts (user_id, title, category, issue_type, location, "
            "description, urgency, reporter_name, reporter_phone, photo_before, "
            "is_agent_report, agent_name, agent_phone, agent_relation) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, title, category, issue_type, location, description, urgency,
             reporter_name, reporter_phone, photo_before, is_agent_report,
             agent_name, agent_phone, agent_relation),
        )
        conn.commit()
        return cur.lastrowid


def get_drafts(user_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM issue_drafts WHERE user_id=? ORDER BY updated_at DESC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_draft(draft_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM issue_drafts WHERE id=?", (draft_id,))
        conn.commit()


def submit_issue(title: str, category: str, issue_type: str, location: str,
                 description: str, urgency: str, reporter_name: str,
                 reporter_phone: str, reporter_id: int | None = None,
                 photo_before: str = "[]", is_agent_report: int = 0,
                 agent_name: str = "", agent_phone: str = "", agent_relation: str = "",
                 draft_id: int | None = None) -> tuple[int, str]:
    """提交报修。返回 (工单 ID, 提示语)。

    校验必填项、手机号格式；识别特殊情况；信息齐全生成工单（状态待审核）。
    """
    # 校验
    if not title or not description or not location:
        return 0, "报修标题、地址和问题描述都不能为空，请补充完整。"
    if len(description.strip()) < 5:
        return 0, "问题描述太短，请至少写 5 个字。"
    if len(description.strip()) > 200:
        return 0, "问题描述过长，请控制在 200 字以内。"
    if not _validate_phone(reporter_phone):
        return 0, "请输入正确的手机号。"
    if issue_type not in ("室内", "室外"):
        return 0, "请选择分类（室内/室外）。"

    special = detect_special_case(description, location)

    # 安全隐患：只记安全提醒，不生成工单
    if special == "safety":
        with get_db() as conn:
            conn.execute(
                "INSERT INTO safety_reminders (user_id, description, location) VALUES (?, ?, ?)",
                (reporter_id or 0, description, location),
            )
            conn.commit()
        log_activity(reporter_name or "居民", "记录安全提醒", "safety_reminder",
                     module=MODULE, detail=description)
        return 0, "safety"

    # 违规搭建：生成工单并标记
    is_violation = 1 if special == "violation" else 0
    # 第三方施工：标记非社区责任
    non_resp = 1 if special == "third_party" else 0

    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO community_issues (title, category, issue_type, location, "
            "description, urgency, status, reporter_id, reporter_name, reporter_phone, "
            "photo_before, is_agent_report, agent_name, agent_phone, agent_relation, "
            "is_violation, non_community_responsibility) "
            "VALUES (?, ?, ?, ?, ?, ?, '待审核', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title, category, issue_type, location, description, urgency, reporter_id,
             reporter_name, reporter_phone, photo_before, is_agent_report,
             agent_name, agent_phone, agent_relation, is_violation, non_resp),
        )
        issue_id = cur.lastrowid
        if draft_id:
            conn.execute("DELETE FROM issue_drafts WHERE id=?", (draft_id,))
        conn.commit()

    log_activity(reporter_name or "居民", "提交报修", "issue", issue_id, title,
                 module=MODULE, after_value="待审核")
    if non_resp:
        return issue_id, "third_party"
    if is_violation:
        return issue_id, "violation"
    return issue_id, "ok"


def audit_issue(issue_id: int, approve: bool, opinion: str = "", actor: str = "负责人") -> tuple[bool, str]:
    """负责人审核。approve=True 通过 → 已审核待派单；False 退回 → 退回补充信息。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM community_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] not in ("待审核", "退回补充信息"):
            return False, f"当前状态「{row['status']}」不支持审核"
        if not approve and not opinion:
            return False, "退回必须填写审核意见"
        new_status = "已审核待派单" if approve else "退回补充信息"
        conn.execute(
            "UPDATE community_issues SET status=?, audit_status=?, "
            "approved_at=CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE approved_at END WHERE id=?",
            (new_status, new_status, 1 if approve else 0, issue_id),
        )
        conn.commit()

    log_activity(actor, "审核通过" if approve else "退回补充信息", "issue", issue_id,
                 module=MODULE, before_value=row["status"], after_value=new_status, detail=opinion)
    return True, ""


def dispatch_issue(issue_id: int, assignee_name: str, assignee_phone: str,
                   actor: str = "系统") -> tuple[bool, str]:
    """分派/改派维修人员。状态 → 已派单。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM community_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] not in ("已审核待派单", "已派单", "处理中"):
            return False, f"当前状态「{row['status']}」不支持分派"
        old = row["status"]
        conn.execute(
            "UPDATE community_issues SET status='已派单', assignee_name=?, assignee_phone=? WHERE id=?",
            (assignee_name, assignee_phone, issue_id),
        )
        conn.commit()

    log_activity(actor, "分派维修人员", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="已派单",
                 detail=f"维修人员：{assignee_name} {assignee_phone}")
    return True, ""


def start_process(issue_id: int, actor: str = "负责人") -> tuple[bool, str]:
    """开始处理。状态 → 处理中。"""
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] not in ("已派单", "待协商"):
            return False, f"当前状态「{row['status']}」不支持开始处理"
        old = row["status"]
        conn.execute("UPDATE community_issues SET status='处理中' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "开始处理", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="处理中")
    return True, ""


def resolve_issue(issue_id: int, resolve_note: str, photo_after: str = "[]",
                  no_photo_reason: str = "", actor: str = "负责人") -> tuple[bool, str]:
    """填写处理结果。状态 → 待居民反馈。"""
    if not resolve_note:
        return False, "处理结果不能为空"
    if photo_after in ("", "[]") and not no_photo_reason:
        return False, "未上传照片时需填写原因"
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] not in ("处理中",):
            return False, f"当前状态「{row['status']}」不支持填写结果"
        old = row["status"]
        conn.execute(
            "UPDATE community_issues SET status='待居民反馈', resolve_note=?, "
            "photo_after=?, no_photo_reason=?, resolved_at=CURRENT_TIMESTAMP WHERE id=?",
            (resolve_note, photo_after, no_photo_reason, issue_id),
        )
        conn.commit()
    log_activity(actor, "填写处理结果", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="待居民反馈", detail=resolve_note)
    return True, ""


def feedback_issue(issue_id: int, satisfied: bool, reason: str = "",
                   actor: str = "居民") -> tuple[bool, str]:
    """居民满意度反馈。满意 → 处理结束；不满意 → 退回处理中（重新计时）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM community_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] != "待居民反馈":
            return False, f"当前状态「{row['status']}」不支持反馈"
        if not satisfied and not reason:
            return False, "不满意必须填写原因"
        old = row["status"]
        new_status = "处理结束" if satisfied else "处理中"
        conn.execute(
            "UPDATE community_issues SET status=?, satisfaction=?, satisfaction_reason=? WHERE id=?",
            (new_status, "满意" if satisfied else "不满意", reason, issue_id),
        )
        conn.commit()
    log_activity(actor, "满意" if satisfied else "不满意", "issue", issue_id, module=MODULE,
                 before_value=old, after_value=new_status, detail=reason)
    return True, ""


def withdraw_issue(issue_id: int, actor: str = "居民") -> tuple[bool, str]:
    """居民撤回（仅待审核）。→ 已撤回。"""
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] != "待审核":
            return False, f"当前状态「{row['status']}」不支持撤回"
        conn.execute("UPDATE community_issues SET status='已撤回' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "撤回工单", "issue", issue_id, module=MODULE,
                 before_value="待审核", after_value="已撤回")
    return True, ""


def reopen_issue(issue_id: int, actor: str = "居民") -> tuple[bool, str]:
    """重新打开已撤回工单。→ 待审核（可修改一次）。"""
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] != "已撤回":
            return False, f"当前状态「{row['status']}」不支持重新打开"
        conn.execute("UPDATE community_issues SET status='待审核' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "重新打开工单", "issue", issue_id, module=MODULE,
                 before_value="已撤回", after_value="待审核")
    return True, ""


def close_issue(issue_id: int, reason: str, actor: str = "负责人") -> tuple[bool, str]:
    """特殊关闭工单（需二次确认）。→ 已关闭。"""
    if not reason:
        return False, "关闭原因必填"
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        old = row["status"]
        conn.execute("UPDATE community_issues SET status='已关闭' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "关闭工单", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="已关闭", detail=reason)
    return True, ""


def transfer_issue(issue_id: int, actor: str = "负责人") -> tuple[bool, str]:
    """违规搭建转出（需手动批准）。→ 已转出。"""
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        old = row["status"]
        conn.execute("UPDATE community_issues SET status='已转出' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "转出违规搭建", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="已转出")
    return True, ""


def negotiate_issue(issue_id: int, reason: str, actor: str = "负责人") -> tuple[bool, str]:
    """室内费用协商。→ 待协商。"""
    if not reason:
        return False, "协商原因必填"
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        old = row["status"]
        conn.execute("UPDATE community_issues SET status='待协商' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "转待协商", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="待协商", detail=reason)
    return True, ""


def supplement_issue(issue_id: int, content: str, actor: str = "居民") -> tuple[bool, str]:
    """居民补充信息（24 小时内最多 2 次）。"""
    if not content:
        return False, "补充内容不能为空"
    with get_db() as conn:
        row = conn.execute(
            "SELECT supplement_count, supplemented_at, status FROM community_issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["supplement_count"] >= 2:
            return False, "操作过于频繁，请稍后再试"
        conn.execute(
            "UPDATE community_issues SET supplement_count=supplement_count+1, "
            "supplemented_at=CURRENT_TIMESTAMP WHERE id=?",
            (issue_id,),
        )
        conn.execute(
            "INSERT INTO issue_supplements (issue_id, content) VALUES (?, ?)", (issue_id, content)
        )
        conn.commit()
    log_activity(actor, "补充信息", "issue", issue_id, module=MODULE, detail=content)
    return True, ""


def resubmit_issue(issue_id: int, actor: str = "居民") -> tuple[bool, str]:
    """居民把「退回补充信息」的工单重新提交回「待审核」（可修改一次）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM community_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] != "退回补充信息":
            return False, f"当前状态「{row['status']}」不支持重新提交"
        conn.execute("UPDATE community_issues SET status='待审核' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "重新提交工单", "issue", issue_id, module=MODULE,
                 before_value="退回补充信息", after_value="待审核")
    return True, ""


def edit_issue(issue_id: int, actor: str = "居民",
               title: str = "", location: str = "", description: str = "",
               urgency: str = "") -> tuple[bool, str]:
    """居民修改工单内容（仅「待审核」状态，全流程最多一次）。

    spec：撤回/退回后重新打开，居民可修改一次，负责人需重新核实。
    用 activity_log 里「修改工单」的条数做次数限制。
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, title, location, description, urgency FROM community_issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] != "待审核":
            return False, f"仅「待审核」状态可修改工单内容（当前：{row['status']}）"
        cnt = conn.execute(
            "SELECT COUNT(*) AS c FROM activity_log WHERE target_type='issue' "
            "AND target_id=? AND action='修改工单'", (issue_id,),
        ).fetchone()["c"]
        if cnt >= 1:
            return False, "工单内容仅可修改一次，如需补充请使用「补充信息」"
        new_title = (title or row["title"]).strip()
        new_loc = (location or row["location"]).strip()
        new_desc = (description or row["description"]).strip()
        new_urg = (urgency or row["urgency"]).strip()
        conn.execute(
            "UPDATE community_issues SET title=?, location=?, description=?, urgency=? WHERE id=?",
            (new_title, new_loc, new_desc, new_urg, issue_id),
        )
        conn.commit()
    log_activity(actor, "修改工单", "issue", issue_id, module=MODULE,
                 before_value=row["title"], after_value=new_title,
                 detail=f"地址/描述/紧急度已更新（仅一次机会）")
    return True, ""


def get_issue(issue_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        return dict(row) if row else None


def get_issues(status: str | None = None, issue_type: str | None = None,
               category: str | None = None, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM community_issues WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if issue_type:
        q += " AND issue_type=?"
        args.append(issue_type)
    if category:
        q += " AND category=?"
        args.append(category)
    q += " ORDER BY reported_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_issue_timeline(issue_id: int) -> list[dict]:
    """工单留痕时间线（最近在前）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE target_type='issue' AND target_id=? "
            "ORDER BY created_at DESC", (issue_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_review_issues(limit: int = 50) -> list[dict]:
    """负责人待审核列表。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM community_issues WHERE status IN ('待审核','退回补充信息') "
            "ORDER BY reported_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
