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


def get_draft(draft_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM issue_drafts WHERE id=?", (draft_id,)).fetchone()
        return dict(row) if row else None


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
    if not (reporter_name or "").strip():
        return 0, "请填写报修人姓名。"
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
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试审核"
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
            "SELECT status, assignee_name, assignee_phone, title FROM community_issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] not in ("已审核待派单", "已派单", "处理中"):
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试分派"
        old = row["status"]
        old_name = row["assignee_name"] or ""
        conn.execute(
            "UPDATE community_issues SET status='已派单', assignee_name=?, assignee_phone=? WHERE id=?",
            (assignee_name, assignee_phone, issue_id),
        )
        conn.commit()

    # 改派（原维修人员存在且不同）：通知原人员取消任务 + 新人员接手（R42，失败自动重试一次 R43）
    is_reassign = bool(old_name) and old_name != assignee_name
    detail = f"维修人员：{assignee_name} {assignee_phone}"
    if is_reassign:
        _notify_worker(old_name, old_name, "取消任务", f"工单 #{issue_id}（{row['title'][:20]}）已改派他人，您无需再处理。", issue_id)
        _notify_worker(assignee_name, assignee_phone, "接手任务", f"工单 #{issue_id}（{row['title'][:20]}）已分派给您，请及时处理。", issue_id)
        detail += f"；原维修人员：{old_name}（已通知取消任务）"

    log_activity(actor, "分派维修人员", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="已派单", detail=detail)
    return True, ""


def _notify_worker(worker_name: str, worker_phone: str, action: str,
                   text: str, issue_id: int) -> None:
    """通知维修人员（改派场景：原人员取消 / 新人员接手）。失败自动重试一次，仍失败记异常。"""
    for attempt in range(2):
        try:
            # 维修人员若有系统账号（按姓名/电话匹配）则站内通知，否则留痕即可
            from data.db_user import list_users
            notified = False
            for u in list_users(role="grid"):
                if (u.get("name") and u["name"] == worker_name) or (
                    u.get("phone") and u["phone"] == worker_phone
                ):
                    from data.db_notifications import create_notification
                    create_notification(u["id"], "dispatch", f"工单 #{issue_id} {action}", text)
                    notified = True
            return
        except Exception as e:  # noqa: BLE001
            if attempt == 1:
                try:
                    from data.db_notifications import log_exception
                    log_exception("报修", f"改派通知失败（{worker_name} {action}）：{e}")
                except Exception:
                    pass
                return
            continue


def update_issue_category(issue_id: int, category: str, actor: str = "负责人") -> tuple[bool, str]:
    """负责人修改工单分类（R27）。

    已分派/处理中的工单改分类后，原维修人员可能不匹配 → 强制重新分派（R28）：
    清空维修人员、状态回「已审核待派单」，留痕记录原因，由系统重新派单。
    """
    category = (category or "").strip()
    if not category:
        return False, "请选择分类"
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, category, assignee_name FROM community_issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        old_cat = row["category"] or ""
        old_status = row["status"]
        if category == old_cat:
            return False, "分类未变化"
        if old_status in ("已派单", "处理中"):
            # 强制重新分派：清空维修人员 + 回待派单
            conn.execute(
                "UPDATE community_issues SET category=?, assignee_name='', assignee_phone='', "
                "status='已审核待派单' WHERE id=?",
                (category, issue_id),
            )
            conn.commit()
            log_activity(actor, "修改工单分类（强制重新分派）", "issue", issue_id,
                         module=MODULE, before_value=f"{old_status}·{old_cat}",
                         after_value=f"已审核待派单·{category}",
                         detail=f"分类由「{old_cat}」改为「{category}」，原维修人员 {row['assignee_name'] or ''} 不匹配，系统将重新派单")
            return True, "分类已修改，工单已回到待派单（原维修人员不匹配，系统将重新分派）。"
        conn.execute("UPDATE community_issues SET category=? WHERE id=?", (category, issue_id))
        conn.commit()
    log_activity(actor, "修改工单分类", "issue", issue_id, module=MODULE,
                 before_value=old_cat, after_value=category)
    return True, ""


def start_process(issue_id: int, actor: str = "负责人") -> tuple[bool, str]:
    """开始处理。状态 → 处理中。"""
    with get_db() as conn:
        row = conn.execute("SELECT status FROM community_issues WHERE id=?", (issue_id,)).fetchone()
        if row is None:
            return False, "工单不存在"
        if row["status"] not in ("已派单", "待协商"):
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试开始处理"
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
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试填写结果"
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
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试反馈"
        if not satisfied and not reason:
            return False, "不满意必须填写原因"
        old = row["status"]
        new_status = "处理结束" if satisfied else "处理中"
        if satisfied:
            conn.execute(
                "UPDATE community_issues SET status=?, satisfaction=?, satisfaction_reason=? WHERE id=?",
                (new_status, "满意", reason, issue_id),
            )
        else:
            # 不满意退回处理中：时限从退回时刻重新计算（R39）
            conn.execute(
                "UPDATE community_issues SET status=?, satisfaction=?, satisfaction_reason=?, "
                "approved_at=CURRENT_TIMESTAMP WHERE id=?",
                (new_status, "不满意", reason, issue_id),
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
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试撤回"
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
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试重新打开"
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
        row = conn.execute(
            "SELECT status, reporter_id, title FROM community_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        old = row["status"]
        conn.execute("UPDATE community_issues SET status='已关闭' WHERE id=?", (issue_id,))
        conn.commit()
    log_activity(actor, "关闭工单", "issue", issue_id, module=MODULE,
                 before_value=old, after_value="已关闭", detail=reason)
    # 自动通知居民关闭原因（spec 17）
    try:
        if row["reporter_id"]:
            from data.db_notifications import create_notification
            create_notification(row["reporter_id"], "issue",
                                "工单已关闭",
                                f"工单 #{issue_id}（{row['title'][:20]}）已关闭，原因：{reason}")
    except Exception:
        pass  # 通知不是硬依赖
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
    """居民补充信息（24 小时内最多 2 次）。

    补充后自动通知负责人，提示确认是否影响紧急程度/分类（若影响，计时重算或重新分派）。
    """
    if not content:
        return False, "补充内容不能为空"
    new_count = 0
    with get_db() as conn:
        row = conn.execute(
            "SELECT supplement_count, supplemented_at, status, title FROM community_issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        # 24 小时窗口（spec 15）：距上次补充超过 24 小时重置计数
        if row["supplemented_at"]:
            try:
                from datetime import datetime
                last = datetime.strptime(str(row["supplemented_at"])[:19], "%Y-%m-%d %H:%M:%S")
                if (datetime.utcnow() - last).total_seconds() > 86400:
                    conn.execute(
                        "UPDATE community_issues SET supplement_count=0 WHERE id=?", (issue_id,)
                    )
            except Exception:
                pass
        fresh = conn.execute(
            "SELECT supplement_count FROM community_issues WHERE id=?", (issue_id,)
        ).fetchone()
        if fresh["supplement_count"] >= 2:
            return False, "操作过于频繁，请稍后再试"
        new_count = fresh["supplement_count"] + 1
        conn.execute(
            "UPDATE community_issues SET supplement_count=supplement_count+1, "
            "supplemented_at=CURRENT_TIMESTAMP, supplement_pending=1 WHERE id=?",
            (issue_id,),
        )
        conn.execute(
            "INSERT INTO issue_supplements (issue_id, content) VALUES (?, ?)", (issue_id, content)
        )
        conn.commit()
    log_activity(actor, "补充信息", "issue", issue_id, module=MODULE, detail=content,
                 after_value=f"第 {new_count} 次补充（24小时窗口）")
    # 自动通知负责人重评估（spec 16：补充后自动通知负责人，标记"有补充信息"，负责人需确认）
    try:
        from data.db_user import list_users
        for u in list_users(role="grid"):
            from data.db_notifications import create_notification
            create_notification(
                u["id"], "supplement",
                f"工单 #{issue_id} 有补充信息",
                f"{row['title'][:20]}：居民补充了信息，请确认是否影响紧急程度/分类（影响则重新计时或重新分派）。",
                related_id=issue_id,
            )
    except Exception:
        pass  # 通知不是硬依赖
    return True, ""


def confirm_supplement(issue_id: int, affects_timing: bool = False,
                       actor: str = "负责人") -> tuple[bool, str]:
    """负责人确认补充信息（R34/R35）。

    affects_timing=True：补充影响紧急程度/分类 → 计时从确认时刻重新计算。
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, title, supplement_pending FROM community_issues WHERE id=?",
            (issue_id,),
        ).fetchone()
        if row is None:
            return False, "工单不存在"
        if not row["supplement_pending"]:
            return False, "该工单没有待确认的补充信息"
        if affects_timing:
            # 计时重算：以确认时间为新的计时起点（spec：补充影响紧急程度 → 重新计算时限）
            conn.execute(
                "UPDATE community_issues SET supplement_pending=0, approved_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (issue_id,),
            )
            after = "已确认（计时重算）"
        else:
            conn.execute(
                "UPDATE community_issues SET supplement_pending=0 WHERE id=?", (issue_id,)
            )
            after = "已确认"
        conn.commit()
    log_activity(actor, "确认补充信息", "issue", issue_id, row["title"] or "",
                 module=MODULE, before_value="待确认", after_value=after,
                 detail="补充信息不影响紧急程度/分类" if not affects_timing else "补充信息影响紧急程度/分类，时限已重新计算")
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
            return False, f"状态已变更（当前「{row['status']}」），请刷新后重试重新提交"
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
               category: str | None = None, reporter_id: int | None = None,
               urgency: str | None = None, keyword: str | None = None,
               limit: int = 50) -> list[dict]:
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
    if urgency:
        q += " AND urgency=?"
        args.append(urgency)
    if keyword:
        q += " AND (title LIKE ? OR location LIKE ? OR description LIKE ?)"
        kw = f"%{keyword}%"
        args += [kw, kw, kw]
    if reporter_id is not None:
        q += " AND reporter_id=?"
        args.append(reporter_id)
    q += " ORDER BY reported_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_safety_reminders(limit: int = 100) -> list[dict]:
    """安全提醒记录（负责人端查看，spec 四：安全隐患强制提示+生成记录）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM safety_reminders ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def find_duplicate_issue(location: str, description: str, days: int = 7,
                         exclude_id: int | None = None) -> dict | None:
    """重复上报检测（P2-02）：7 天内、同楼栋（地址前 5 字）、关键词重合 ≥2 的同类工单。

    返回原工单 dict（含 reporter 信息），无则 None。exclude_id 排除自身（创建后检测用）。
    降级：地址空或描述过短不检测。
    """
    loc = (location or "").strip()
    desc = (description or "").strip()
    if not loc or len(desc) < 4:
        return None
    try:
        with get_db() as conn:
            q = ("SELECT * FROM community_issues WHERE status NOT IN ('已关闭', '已撤回', '已转出') "
                 "AND reported_at >= datetime('now', ? || ' days') "
                 "AND substr(location, 1, 5) = substr(?, 1, 5)")
            args: list = [f"-{days}", loc]
            if exclude_id:
                q += " AND id != ?"
                args.append(exclude_id)
            q += " ORDER BY reported_at DESC LIMIT 20"
            rows = conn.execute(q, args).fetchall()
    except Exception:
        return None
    def _bigrams(s):
        return {s[i:i + 2] for i in range(max(0, len(s) - 1))}

    kw = _bigrams(desc)
    for r in rows:
        old = (r["description"] or "") + (r["title"] or "")
        old_kw = _bigrams(old)
        overlap = len(kw & old_kw)
        if overlap >= 2:
            return dict(r)
    return None


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


# 报修超时时限（从审核通过时间 approved_at 计时）
_URGENCY_DEADLINE_HOURS = {"紧急": 1, "中等": 4, "一般": 24, "普通": 48}


def get_overdue_issues() -> list[dict]:
    """查超时工单（spec 二、时限规则：审核通过后紧急1h/中等4h/一般24h/普通48h）。

    未结束的状态都算（已审核待派单/已派单/处理中/待居民反馈）。
    """
    clauses = " OR ".join(
        f"(urgency='{u}' AND approved_at < datetime('now', '-{h} hours'))"
        for u, h in _URGENCY_DEADLINE_HOURS.items()
    )
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM community_issues WHERE approved_at IS NOT NULL "
            "AND status IN ('已审核待派单','已派单','处理中','待居民反馈') "
            f"AND ({clauses}) ORDER BY approved_at"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_issue_overdue_notice(actor: str = "系统") -> list[dict]:
    """报修超时自动升级（scheduler 调用）：超时工单留痕 + 通知负责人。"""
    overdue = get_overdue_issues()
    for i in overdue:
        log_activity(actor, "工单超时升级", "issue", i["id"], i.get("title", ""),
                     module=MODULE, detail=f"{i.get('urgency', '')}级工单超时，请尽快处理")
        try:
            from data.db_user import list_users
            for u in list_users(role="grid"):
                from data.db_notifications import create_notification
                create_notification(u["id"], "sla", "工单超时提醒",
                                    f"工单 #{i['id']}（{i.get('title', '')[:20]}）已超时，请尽快处理。")
        except Exception:
            pass  # 通知不是硬依赖
    return overdue


def clean_issue_drafts(days: int = 7) -> int:
    """清理超过 N 天的报修草稿（spec：草稿保存 7 天，超期删除）。"""
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM issue_drafts WHERE created_at < datetime('now', '-{days} days')"
        )
        conn.commit()
        return cur.rowcount
