# data/db_proposal.py
"""提案模块数据层 —— 按《02-提案.md》实现完整状态机与匿名投票闭环。

状态机（status 字段，中文状态字符串）：
待审核 → 退回修改（可重新提交回待审核）→ 待确认公示/私有 → 公示中 / 待执行
      → 执行中 → 待提案人反馈 → 已完成 / 重新执行 / 不予执行 / 违规下架 / 已关闭
      ↘ 已撤回（可重新打开回待审核）
      ↳ 已结束（提案人 7 天未反馈满意度，系统自动标记，视为满意）

投票匿名铁律：
- proposal_votes 只存 score + created_at，绝无 user_id；
- proposal_vote_dedup 只存 user_id 防重复，绝无 score；
- 任何统计/排名/导出只聚合 proposal_votes，绝不 JOIN 两张表；
- 留痕只记「有居民评分」，不记个体、不记分数。

schema v18 之外、本模块补齐的列（幂等 ALTER，只加不删，见 _EXTRA_COLS）：
- audited_at         审核通过时间（7 天确认窗口起点）
- community_building 所属小区/楼栋（选填）
- resolved_at        执行完成时间（7 天反馈窗口起点）
- feedback_at        满意度反馈时间
- feedback_reason    不满意原因
- satisfaction       满意/不满意（用于导出与列表展示）
"""
import re
import sqlite3
from datetime import datetime

from data.db_core import get_db
from data.db_notifications import log_activity, notify_proposal_status_change

MODULE = "提案"

# 提案类别（强制五选一）
VALID_CATEGORIES = ["公共设施", "环境卫生", "文化活动", "安全治理", "其他"]

# 负责人转部门时的可选部门
EXECUTOR_DEPTS = ["物业维修班", "环境卫生组", "安全治理组", "文化活动组", "社区服务中心", "综合办公室"]

# 全部合法状态
STATUS_ALL = [
    "待审核", "退回修改", "待确认公示/私有", "公示中", "待执行", "执行中",
    "待提案人反馈", "已完成", "重新执行", "不予执行", "违规下架", "已撤回",
    "已关闭", "已结束",
]

# 第七节标准输出：状态颜色（黄/红/蓝/绿/橙/灰）
STATUS_COLORS = {
    "待审核": "黄", "退回修改": "红", "待确认公示/私有": "蓝", "公示中": "蓝",
    "待执行": "蓝", "执行中": "绿", "待提案人反馈": "橙", "已完成": "灰",
    "重新执行": "橙", "不予执行": "灰", "违规下架": "灰", "已撤回": "灰",
    "已关闭": "灰", "已结束": "灰",
}

# 终点状态：不再有任何流转
TERMINAL_STATUSES = {"已完成", "不予执行", "违规下架", "已关闭", "已撤回", "已结束"}

# 公示与投票窗口
PUBLIC_EXPECT_DAYS = 7          # 首次公示期
REOPEN_EXPECT_DAYS = 3          # 重新执行公示期
CONFIRM_WINDOW_DAYS = 7         # 审核通过后确认公开/私有的窗口
FEEDBACK_WINDOW_DAYS = 7        # 执行完成后的满意度反馈窗口
MAX_REOPEN = 2                  # 最多重新执行次数

_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")

# schema v18 之外本模块补齐的列（幂等）
_EXTRA_COLS = [
    ("audited_at", "TIMESTAMP"),
    ("community_building", "TEXT DEFAULT ''"),
    ("resolved_at", "TIMESTAMP"),
    ("feedback_at", "TIMESTAMP"),
    ("feedback_reason", "TEXT DEFAULT ''"),
    ("satisfaction", "TEXT DEFAULT ''"),
]
_extra_checked = False


def _ensure_schema(conn) -> None:
    """给 proposals 补本模块需要的列（幂等，只加不删）。"""
    global _extra_checked
    if _extra_checked:
        return
    cols = {r[1] for r in conn.execute("PRAGMA table_info(proposals)")}
    for name, decl in _EXTRA_COLS:
        if name not in cols:
            conn.execute(f"ALTER TABLE proposals ADD COLUMN {name} {decl}")
    conn.commit()
    _extra_checked = True


def _validate_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match((phone or "").strip()))


def _now_str() -> str:
    """当前 UTC 时间，与 SQLite CURRENT_TIMESTAMP 同格式（比较用）。"""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")


def _status_color(status: str) -> str:
    """状态 → 颜色（负责人端/居民端一致，见文档第七节）。"""
    return STATUS_COLORS.get(status or "", "灰")


def _resolve_current_user_id() -> int | None:
    """解析当前登录用户 ID（UI/Agent 场景），拿不到返回 None。"""
    try:
        from data.db_user import get_current_user
        profile = get_current_user()
        uid = profile.get("id")
        return uid or None
    except Exception:
        return None


def proposal_no(pid: int) -> str:
    """展示用提案编号：P + 五位补零。"""
    return f"P{pid:05d}"


def mask_name(name: str) -> str:
    """姓名脱敏：保留首字，其余打码。"""
    name = (name or "").strip()
    if not name:
        return ""
    if len(name) == 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


def mask_phone(phone: str) -> str:
    """电话脱敏：保留前 3 后 4。"""
    phone = (phone or "").strip()
    if len(phone) == 11:
        return phone[:3] + "****" + phone[-4:]
    return "****"


# ---------------------------------------------------------------------------
# 草稿
# ---------------------------------------------------------------------------

def save_draft(user_id: int, title: str = "", description: str = "",
               category: str = "", is_public: int = 1, reporter_name: str = "",
               reporter_phone: str = "", attachment_public: int = 0,
               is_agent_report: int = 0, agent_name: str = "",
               agent_phone: str = "", agent_relation: str = "") -> int:
    """保存/更新提案草稿（每人一份，7 天有效）。返回草稿 ID。"""
    with get_db() as conn:
        _ensure_schema(conn)
        existing = conn.execute(
            "SELECT id FROM proposal_drafts WHERE user_id=?", (user_id,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE proposal_drafts SET title=?, description=?, category=?, is_public=?, "
                "reporter_name=?, reporter_phone=?, attachment_public=?, is_agent_report=?, "
                "agent_name=?, agent_phone=?, agent_relation=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE id=?",
                (title, description, category, is_public, reporter_name, reporter_phone,
                 attachment_public, is_agent_report, agent_name, agent_phone, agent_relation,
                 existing["id"]),
            )
            conn.commit()
            return existing["id"]
        cur = conn.execute(
            "INSERT INTO proposal_drafts (user_id, title, description, category, is_public, "
            "reporter_name, reporter_phone, attachment_public, is_agent_report, "
            "agent_name, agent_phone, agent_relation) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (user_id, title, description, category, is_public, reporter_name,
             reporter_phone, attachment_public, is_agent_report, agent_name,
             agent_phone, agent_relation),
        )
        conn.commit()
        return cur.lastrowid


def get_drafts(user_id: int) -> list[dict]:
    """查当前用户草稿（顺带清掉超过 7 天的过期草稿）。"""
    with get_db() as conn:
        _ensure_schema(conn)
        conn.execute(
            "DELETE FROM proposal_drafts WHERE user_id=? AND "
            "updated_at < datetime('now', '-7 days')", (user_id,)
        )
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM proposal_drafts WHERE user_id=? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_draft(draft_id: int, user_id: int | None = None) -> dict | None:
    """查单条草稿（给 user_id 时校验归属）。"""
    with get_db() as conn:
        if user_id:
            row = conn.execute(
                "SELECT * FROM proposal_drafts WHERE id=? AND user_id=?", (draft_id, user_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM proposal_drafts WHERE id=?", (draft_id,)
            ).fetchone()
        return dict(row) if row else None


def delete_draft(draft_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM proposal_drafts WHERE id=?", (draft_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# 提交 / 重新提交
# ---------------------------------------------------------------------------

def submit_proposal(title: str, description: str, category: str,
                    reporter_name: str, reporter_phone: str, is_public: int,
                    reporter_id: int | None = None,
                    community_building: str = "", attachment_public: int = 0,
                    is_agent_report: int = 0, agent_name: str = "",
                    agent_phone: str = "", agent_relation: str = "",
                    draft_id: int | None = None, author: str = "") -> tuple[int, str]:
    """居民/家属/负责人提交提案。返回 (提案 ID, 提示语)。

    校验：标题 ≤50 字、内容 10~1000 字、类别五选一、电话格式、公开/私有必选。
    生成状态「待审核」。draft_id 给定时提交成功自动删除草稿。
    """
    title = (title or "").strip()
    description = (description or "").strip()
    reporter_name = (reporter_name or "").strip()
    reporter_phone = (reporter_phone or "").strip()

    if not title:
        return 0, "提案标题不能为空。"
    if len(title) > 50:
        return 0, "提案标题过长，请控制在 50 字以内。"
    if not description:
        return 0, "提案内容不能为空。"
    if len(description) < 10:
        return 0, "提案内容太少，请至少写 10 个字。"
    if len(description) > 1000:
        return 0, "提案内容过长，请控制在 1000 字以内。"
    if category not in VALID_CATEGORIES:
        return 0, "请选择提案类别（公共设施/环境卫生/文化活动/安全治理/其他）。"
    if not reporter_name:
        return 0, "请填写提案人姓名。"
    if not _validate_phone(reporter_phone):
        return 0, "请输入正确的手机号。"
    if is_public not in (0, 1):
        return 0, "请选择提案公开方式（公开/私有）。"

    if reporter_id is None:
        reporter_id = _resolve_current_user_id()

    with get_db() as conn:
        _ensure_schema(conn)
        cur = conn.execute(
            "INSERT INTO proposals (title, description, category, author, supporter_count, "
            "status, is_public, audit_status, attachment_public, reporter_id, reporter_name, "
            "reporter_phone, is_agent_report, agent_name, agent_phone, agent_relation, "
            "community_building) VALUES (?,?,?,?,0,'待审核',?,'待审核',?,?,?,?,?,?,?,?,?)",
            (title, description, category, author or reporter_name, is_public,
             attachment_public, reporter_id, reporter_name, reporter_phone,
             is_agent_report, agent_name, agent_phone, agent_relation, community_building),
        )
        pid = cur.lastrowid
        if draft_id:
            conn.execute("DELETE FROM proposal_drafts WHERE id=?", (draft_id,))
        conn.commit()

    log_activity(author or reporter_name, "提交提案", "proposal", pid, title,
                 module=MODULE, after_value="待审核",
                 detail=f"类别：{category}；公开方式：{'公开' if is_public else '私有'}")
    return pid, "ok"


def resubmit_proposal(pid: int, title: str = "", description: str = "",
                      category: str = "", is_public: int | None = None,
                      community_building: str = "", attachment_public: int | None = None,
                      actor: str = "居民") -> tuple[bool, str]:
    """被退回 / 已撤回的提案修改后重新提交，回到「待审核」重新审核。"""
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, description, category, is_public, community_building, "
            "attachment_public FROM proposals WHERE id=?", (pid,)
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] not in ("退回修改", "已撤回"):
            return False, f"当前状态「{row['status']}」不支持重新提交"
        old = row["status"]
        new_title = (title or row["title"]).strip()
        new_desc = (description or row["description"]).strip()
        new_cat = category or row["category"]
        if not new_title:
            return False, "提案标题不能为空。"
        if len(new_title) > 50:
            return False, "提案标题过长，请控制在 50 字以内。"
        if not new_desc:
            return False, "提案内容不能为空。"
        if len(new_desc) < 10:
            return False, "提案内容太少，请至少写 10 个字。"
        if len(new_desc) > 1000:
            return False, "提案内容过长，请控制在 1000 字以内。"
        if new_cat not in VALID_CATEGORIES:
            return False, "请选择提案类别（公共设施/环境卫生/文化活动/安全治理/其他）。"
        new_public = row["is_public"] if is_public is None else is_public
        new_attach = row["attachment_public"] if attachment_public is None else attachment_public
        new_building = community_building if community_building is not None else row["community_building"]
        conn.execute(
            "UPDATE proposals SET title=?, description=?, category=?, is_public=?, "
            "community_building=?, attachment_public=?, status='待审核', audit_status='待审核', "
            "audit_opinion='' WHERE id=?",
            (new_title, new_desc, new_cat, new_public, new_building, new_attach, pid),
        )
        conn.commit()
    log_activity(actor, "修改后重新提交" if old == "退回修改" else "撤回后重新打开提交",
                 "proposal", pid, new_title, module=MODULE,
                 before_value=old, after_value="待审核")
    return True, ""


# ---------------------------------------------------------------------------
# 审核（含附件公开审核）
# ---------------------------------------------------------------------------

def audit_proposal(pid: int, approve: bool, opinion: str = "",
                   attachment_public_ok: bool | None = None,
                   actor: str = "负责人") -> tuple[bool, str]:
    """负责人审核。通过 → 待确认公示/私有；退回 → 退回修改（必须填意见）。

    attachment_public_ok: 提案人选择公开附件时，负责人审核附件是否含隐私。
      False → 附件不公开（不影响提案本身通过），审核意见注明附件处理结果；
      True / None → 维持提案人选择。
    """
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, attachment_public, audit_opinion FROM proposals WHERE id=?",
            (pid,),
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] not in ("待审核", "退回修改"):
            return False, f"当前状态「{row['status']}」不支持审核"
        old = row["status"]
        opinion = (opinion or "").strip()
        if not approve and not opinion:
            return False, "退回必须填写审核意见"

        new_status = "待确认公示/私有" if approve else "退回修改"
        attach_note = ""
        new_attach = row["attachment_public"]
        if approve and attachment_public_ok is False and row["attachment_public"]:
            new_attach = 0
            attach_note = "；附件含隐私，附件不公开（不影响提案通过）"
        conn.execute(
            "UPDATE proposals SET status=?, audit_status=?, audit_opinion=?, "
            "audited_at=CASE WHEN ?=1 THEN CURRENT_TIMESTAMP ELSE audited_at END, "
            "attachment_public=? WHERE id=?",
            (new_status, "通过" if approve else "退回",
             f"{opinion}{attach_note}", 1 if approve else 0, new_attach, pid),
        )
        conn.commit()
    log_activity(actor, "审核通过" if approve else "退回修改", "proposal", pid,
                 row["title"] or "", module=MODULE,
                 before_value=old, after_value=new_status,
                 detail=f"{opinion}{attach_note}")
    try:
        notify_proposal_status_change(pid, new_status, opinion or "")
    except Exception:
        pass
    return True, ""


# ---------------------------------------------------------------------------
# 公开/私有确认（审核通过后 7 天内可改一次）
# ---------------------------------------------------------------------------

def confirm_visibility(pid: int, is_public: int, actor: str = "居民") -> tuple[bool, str]:
    """居民确认公开/私有。公开 → 公示中（7 天公示+投票）；私有 → 待执行。"""
    if is_public not in (0, 1):
        return False, "请选择公开或私有。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, is_public FROM proposals WHERE id=?", (pid,)
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "待确认公示/私有":
            return False, f"当前状态「{row['status']}」不支持确认公开/私有"
        old = row["status"]
        if is_public:
            new_status = "公示中"
            conn.execute(
                "UPDATE proposals SET is_public=1, status='公示中', visibility_confirmed=1, "
                "published_at=CURRENT_TIMESTAMP, voting_started_at=CURRENT_TIMESTAMP, "
                "voting_ended_at=datetime('now', '+7 days') WHERE id=?",
                (pid,),
            )
            action = "确认公开并开始公示"
        else:
            new_status = "待执行"
            conn.execute(
                "UPDATE proposals SET is_public=0, status='待执行', visibility_confirmed=1 "
                "WHERE id=?", (pid,),
            )
            action = "确认私有"
        conn.commit()
    log_activity(actor, action, "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value=new_status,
                 detail="公开（公示7天+居民投票）" if is_public else "私有（不公示不投票）")
    return True, ""


def change_visibility(pid: int, is_public: int, actor: str = "居民") -> tuple[bool, str]:
    """审核通过后 7 天内、公示开始前，居民可修改一次公开/私有。"""
    if is_public not in (0, 1):
        return False, "请选择公开或私有。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, is_public, audited_at FROM proposals WHERE id=?", (pid,)
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        # 已确认私有的（待执行）可改为公开；未最终确认前也允许改
        if row["status"] not in ("待执行", "待确认公示/私有"):
            return False, "公示已开始或当前状态不支持修改公开/私有"
        if row["status"] == "待执行" and row["is_public"] == 0 and is_public == 0:
            return False, "当前已是私有，无需重复修改"
        if row["status"] == "待执行" and row["is_public"] == 1:
            return False, "当前已是公开，无需重复修改"
        # 7 天窗口
        if row["audited_at"]:
            deadline = _parse_ts(row["audited_at"]).timestamp() + CONFIRM_WINDOW_DAYS * 86400
            if datetime.utcnow().timestamp() > deadline:
                return False, "已超过审核通过后 7 天，不能再修改公开/私有"
        # 只能改一次
        cnt = conn.execute(
            "SELECT COUNT(*) c FROM activity_log WHERE target_type='proposal' AND target_id=? "
            "AND action='修改公开/私有'", (pid,)
        ).fetchone()["c"]
        if cnt >= 1:
            return False, "公开/私有只能修改一次"
        old = row["status"]
        if row["status"] == "待确认公示/私有":
            # 确认前调整选择，不真正发布
            conn.execute("UPDATE proposals SET is_public=? WHERE id=?", (is_public, pid))
            conn.commit()
            new_status = old
        else:
            # 待执行（私有）→ 改为公开，立即开始公示
            conn.execute(
                "UPDATE proposals SET is_public=1, status='公示中', visibility_confirmed=1, "
                "published_at=CURRENT_TIMESTAMP, voting_started_at=CURRENT_TIMESTAMP, "
                "voting_ended_at=datetime('now', '+7 days') WHERE id=?",
                (pid,),
            )
            conn.commit()
            new_status = "公示中"
    log_activity(actor, "修改公开/私有", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value=new_status,
                 detail=f"改为{'公开' if is_public else '私有'}")
    return True, ""


def remind_confirm(pid: int, actor: str = "负责人") -> tuple[bool, str]:
    """负责人提醒居民确认公开/私有。"""
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title FROM proposals WHERE id=?", (pid,)
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "待确认公示/私有":
            return False, f"当前状态「{row['status']}」无需确认"
    log_activity(actor, "提醒确认公开/私有", "proposal", pid, row["title"] or "",
                 module=MODULE, after_value=row["status"])
    try:
        notify_proposal_status_change(pid, "待确认公示/私有", "请尽快在审核通过后 7 天内确认公开/私有，逾期将按提交时选择执行。")
    except Exception:
        pass
    return True, ""


def auto_confirm_overdue(actor: str = "系统") -> list[int]:
    """逾期未确认公开/私有：按提交时选择执行，留痕并通知（A 类自动触发）。"""
    done: list[int] = []
    with get_db() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, title, is_public FROM proposals WHERE status='待确认公示/私有' "
            "AND audited_at IS NOT NULL AND audited_at < datetime('now', '-7 days')"
        ).fetchall()
        for r in rows:
            if r["is_public"]:
                conn.execute(
                    "UPDATE proposals SET visibility_confirmed=1, status='公示中', "
                    "published_at=CURRENT_TIMESTAMP, voting_started_at=CURRENT_TIMESTAMP, "
                    "voting_ended_at=datetime('now', '+7 days') WHERE id=?",
                    (r["id"],),
                )
                new_status = "公示中"
            else:
                conn.execute(
                    "UPDATE proposals SET visibility_confirmed=1, status='待执行' WHERE id=?",
                    (r["id"],),
                )
                new_status = "待执行"
            conn.commit()
            log_activity(actor, "逾期默认确认", "proposal", r["id"], r["title"] or "",
                         module=MODULE, before_value="待确认公示/私有",
                         after_value=new_status,
                         detail=f"逾期未确认，按提交时选择（{'公开' if r['is_public'] else '私有'}）执行")
            try:
                notify_proposal_status_change(r["id"], new_status,
                                              f"您的提案已按{'公开' if r['is_public'] else '私有'}执行。")
            except Exception:
                pass
            done.append(r["id"])
    return done


# ---------------------------------------------------------------------------
# 匿名投票（1~5 星，一票制）
# ---------------------------------------------------------------------------

def vote_proposal(pid: int, user_id: int, score: int, actor: str = "居民") -> tuple[bool, str]:
    """给公示中的公开提案匿名评分（1~5 星）。

    匿名存储：评分只进 proposal_votes（proposal_id + score + 时间），
    防重复只进 proposal_vote_dedup（proposal_id + user_id），两表永不相联。
    """
    try:
        score = int(score)
    except (TypeError, ValueError):
        return False, "评分无效，请选择 1~5 星。"
    if score < 1 or score > 5:
        return False, "评分无效，请选择 1~5 星。"
    if not user_id:
        return False, "请先登录后再投票。"

    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, voting_ended_at, reporter_id, title FROM proposals WHERE id=?",
            (pid,),
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "公示中":
            return False, f"当前不在公示投票期（状态「{row['status']}」），无法投票"
        if row["voting_ended_at"] and row["voting_ended_at"] <= _now_str():
            return False, "公示投票已结束"
        if row["reporter_id"] and user_id == row["reporter_id"]:
            return False, "不能给自己提案投票"
        dup = conn.execute(
            "SELECT 1 FROM proposal_vote_dedup WHERE proposal_id=? AND user_id=?",
            (pid, user_id),
        ).fetchone()
        if dup:
            return False, "您已经投过票了，每人每提案限投一票"
        try:
            conn.execute(
                "INSERT INTO proposal_votes (proposal_id, score) VALUES (?, ?)", (pid, score)
            )
            conn.execute(
                "INSERT INTO proposal_vote_dedup (proposal_id, user_id) VALUES (?, ?)",
                (pid, user_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            return False, "您已经投过票了，每人每提案限投一票"

    # 留痕：只记「有居民评分」，不记个体、不记分数
    log_activity(actor, "投票", "proposal", pid, row["title"] or "",
                 module=MODULE, detail="收到居民匿名评分（不记录个体与分数）",
                 after_value="公示中")
    return True, ""


def has_voted(pid: int, user_id: int) -> bool:
    """是否已投过票（仅防重复判断，不暴露任何评分信息）。"""
    if not user_id:
        return False
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM proposal_vote_dedup WHERE proposal_id=? AND user_id=?",
            (pid, user_id),
        ).fetchone()
        return bool(row)


def get_proposal_vote_stats(pid: int) -> dict:
    """投票汇总：人数 / 平均分 / 排名。绝不 JOIN 出个体投票明细。

    排名：平均分高者在前，同分按票数多者在前；无评分的提案排在有评分提案之后。
    """
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT COUNT(*) c, AVG(score) a FROM proposal_votes WHERE proposal_id=?",
            (pid,),
        ).fetchone()
        count = row["c"] or 0
        avg = round(row["a"], 1) if row["a"] is not None else None

        ranked = conn.execute(
            "SELECT proposal_id, COUNT(*) c, AVG(score) a FROM proposal_votes "
            "GROUP BY proposal_id HAVING COUNT(*) > 0"
        ).fetchall()
        scored = sorted(ranked, key=lambda r: (-(r["a"] or 0), -(r["c"] or 0)))
        rank = None
        for i, r in enumerate(scored, 1):
            if r["proposal_id"] == pid:
                rank = i
                break
        total_public = conn.execute(
            "SELECT COUNT(*) c FROM proposals WHERE is_public=1 "
            "AND status NOT IN ('待审核','退回修改','已撤回')"
        ).fetchone()["c"]
    return {
        "vote_count": count,
        "avg_score": avg,
        "rank": rank,
        "scored_count": len(scored),
        "total_public": total_public or 0,
    }


def get_vote_stats_batch(pids: list[int]) -> dict[int, dict]:
    """批量投票汇总（避免列表页 N+1）。只返回人数与平均分。"""
    if not pids:
        return {}
    with get_db() as conn:
        ph = ",".join("?" * len(pids))
        rows = conn.execute(
            f"SELECT proposal_id, COUNT(*) c, AVG(score) a FROM proposal_votes "
            f"WHERE proposal_id IN ({ph}) GROUP BY proposal_id",
            pids,
        ).fetchall()
    return {
        r["proposal_id"]: {
            "vote_count": r["c"] or 0,
            "avg_score": round(r["a"], 1) if r["a"] is not None else None,
        }
        for r in rows
    }


def is_voting_ended(pid: int) -> bool:
    """公示期是否已结束。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT voting_ended_at FROM proposals WHERE id=?", (pid,)
        ).fetchone()
    if not row or not row["voting_ended_at"]:
        return False
    return _parse_ts(row["voting_ended_at"]) <= datetime.utcnow()


def get_voting_remaining_days(pid: int) -> int | None:
    """公示中提案的剩余天数（向上取整），非公示中返回 None。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT status, voting_ended_at FROM proposals WHERE id=?", (pid,)
        ).fetchone()
    if not row or row["status"] != "公示中" or not row["voting_ended_at"]:
        return None
    end = _parse_ts(row["voting_ended_at"])
    days = (end - datetime.utcnow()).total_seconds() / 86400.0
    return max(0, int(-(-days // 1)))


def extend_voting(pid: int, minutes: int, actor: str = "系统") -> tuple[bool, str]:
    """投票功能故障顺延：公示期顺延 N 分钟，通知受影响居民。"""
    if minutes <= 0:
        return False, "顺延时长必须大于 0 分钟。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, voting_ended_at, title FROM proposals WHERE id=?", (pid,)
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "公示中":
            return False, f"当前状态「{row['status']}」不在公示期"
        old_end = row["voting_ended_at"] or _now_str()
        conn.execute(
            "UPDATE proposals SET voting_ended_at=datetime(voting_ended_at, ?) WHERE id=?",
            (f"+{minutes} minutes", pid),
        )
        conn.commit()
        new_end = conn.execute(
            "SELECT voting_ended_at FROM proposals WHERE id=?", (pid,)
        ).fetchone()["voting_ended_at"]
    log_activity(actor, "公示期顺延", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old_end, after_value=new_end,
                 detail=f"投票功能故障顺延 {minutes} 分钟")
    try:
        from data.db_notifications import broadcast_notification
        broadcast_notification("proposal_update", "⏳ 公示顺延",
                               f"「{row['title'][:30]}」投票功能故障已恢复，公示期顺延 {minutes} 分钟。")
    except Exception:
        pass
    return True, ""


# ---------------------------------------------------------------------------
# 执行决定 / 转部门 / 填结果
# ---------------------------------------------------------------------------

def decide_execute(pid: int, execute: bool, reason: str = "",
                   actor: str = "负责人") -> tuple[bool, str]:
    """负责人决定执行/不执行（公开提案需公示结束后；私有提案在待执行状态）。

    决定理由必填，留痕。
    """
    reason = (reason or "").strip()
    if not reason:
        return False, "决定理由必填。"
    decided = ""  # 记录本次流转，用于日志
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, voting_ended_at, is_public FROM proposals WHERE id=?",
            (pid,),
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] == "公示中":
            if row["voting_ended_at"] and row["voting_ended_at"] > _now_str():
                return False, "公示期内不能提前决定，请等待公示结束"
            if execute:
                # 决定执行：公示结束 → 待执行（等待转部门）
                conn.execute(
                    "UPDATE proposals SET status='待执行', decision_reason=? WHERE id=?",
                    (reason, pid),
                )
                conn.commit()
                decided = "公示中→待执行"
        elif row["status"] == "待执行":
            if execute:
                # 私有提案确认执行：停留在待执行，等转部门
                conn.execute(
                    "UPDATE proposals SET decision_reason=? WHERE id=?", (reason, pid)
                )
                conn.commit()
                decided = "待执行→待执行"
        else:
            return False, f"当前状态「{row['status']}」不支持决定执行/不执行"

    if decided:
        log_activity(actor, "决定执行", "proposal", pid, row["title"] or "", module=MODULE,
                     before_value=decided.split("→")[0], after_value=decided.split("→")[1],
                     detail=reason)
        return True, ""

    # 不予执行
    with get_db() as conn:
        _ensure_schema(conn)
        conn.execute(
            "UPDATE proposals SET status='不予执行', decision_reason=? WHERE id=?",
            (reason, pid),
        )
        conn.commit()
    log_activity(actor, "决定不予执行", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=row["status"], after_value="不予执行", detail=reason)
    try:
        notify_proposal_status_change(pid, "不予执行", reason)
    except Exception:
        pass
    return True, ""


def start_execute(pid: int, dept: str, actor: str = "负责人") -> tuple[bool, str]:
    """转部门执行。待执行 → 执行中。"""
    dept = (dept or "").strip()
    if not dept:
        return False, "请选择执行部门。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "待执行":
            return False, f"当前状态「{row['status']}」不支持转部门执行"
        old = row["status"]
        conn.execute(
            "UPDATE proposals SET status='执行中', executor_dept=? WHERE id=?",
            (dept, pid),
        )
        conn.commit()
    log_activity(actor, "转部门执行", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value="执行中", detail=f"执行部门：{dept}")
    return True, ""


def resolve_proposal(pid: int, result: str, actor: str = "负责人") -> tuple[bool, str]:
    """填写执行结果。执行中 → 待提案人反馈。"""
    result = (result or "").strip()
    if not result:
        return False, "执行结果不能为空。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "执行中":
            return False, f"当前状态「{row['status']}」不支持填写执行结果"
        old = row["status"]
        conn.execute(
            "UPDATE proposals SET status='待提案人反馈', execution_result=?, "
            "resolved_at=CURRENT_TIMESTAMP WHERE id=?",
            (result, pid),
        )
        conn.commit()
    log_activity(actor, "填写执行结果", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value="待提案人反馈", detail=result)
    try:
        notify_proposal_status_change(pid, "待提案人反馈", result)
    except Exception:
        pass
    return True, ""


# ---------------------------------------------------------------------------
# 满意度反馈 / 重新执行
# ---------------------------------------------------------------------------

def feedback_proposal(pid: int, satisfied: bool, reason: str = "",
                      actor: str = "居民") -> tuple[bool, str]:
    """提案人反馈满意度。满意 → 已完成；不满意 → 重新执行（最多 2 次）。"""
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, reopen_count FROM proposals WHERE id=?", (pid,)
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "待提案人反馈":
            return False, f"当前状态「{row['status']}」不支持反馈"
        old = row["status"]
        reopen_count = row["reopen_count"] or 0
        if satisfied:
            conn.execute(
                "UPDATE proposals SET status='已完成', satisfaction='满意', feedback_reason='', "
                "feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                (pid,),
            )
            conn.commit()
            new_status = "已完成"
        else:
            reason = (reason or "").strip()
            if not reason:
                return False, "不满意必须填写原因。"
            if reopen_count < MAX_REOPEN:
                reopen_count += 1
                conn.execute(
                    "UPDATE proposals SET status='重新执行', reopen_count=?, satisfaction='不满意', "
                    "feedback_reason=?, feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reopen_count, reason, pid),
                )
                conn.commit()
                new_status = "重新执行"
                action = f"反馈不满意，进入第 {reopen_count} 次重新执行"
            else:
                conn.execute(
                    "UPDATE proposals SET status='重新执行', satisfaction='不满意', "
                    "feedback_reason=?, feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reason, pid),
                )
                conn.commit()
                new_status = "重新执行"
                action = "反馈不满意（重新执行已超过 2 次，等待负责人决定关闭或继续）"
    log_activity(actor, action if not satisfied else "反馈满意", "proposal", pid,
                 row["title"] or "", module=MODULE,
                 before_value=old, after_value=new_status, detail=reason)
    return True, ""


def handle_reopen(pid: int, close: bool = False, reason: str = "",
                  dept: str = "", actor: str = "负责人") -> tuple[bool, str]:
    """处理重新执行。

    公开提案 → 重新公示 3 天并重新投票（投票数据清零、防重复表清空）；
    私有提案 → 负责人重新选择部门，状态直接回到执行中；
    重新执行超过 2 次时，负责人必须先选择「关闭」或「继续」（留痕）。
    """
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT status, title, is_public, reopen_count, executor_dept FROM proposals WHERE id=?",
            (pid,),
        ).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "重新执行":
            return False, f"当前状态「{row['status']}」不支持重新执行处理"
        old = row["status"]
        reopen_count = row["reopen_count"] or 0

        if close:
            reason = (reason or "").strip()
            if not reason:
                return False, "关闭原因必填。"
            conn.execute("UPDATE proposals SET status='已关闭' WHERE id=?", (pid,))
            conn.commit()
            log_activity(actor, "关闭重新执行", "proposal", pid, row["title"] or "",
                         module=MODULE, before_value=old, after_value="已关闭", detail=reason)
            try:
                notify_proposal_status_change(pid, "已关闭", reason)
            except Exception:
                pass
            return True, ""

        # 继续重新执行
        if reopen_count >= MAX_REOPEN:
            reopen_count += 1  # 超过 2 次仍继续：次数继续累加并留痕
            conn.execute("UPDATE proposals SET reopen_count=? WHERE id=?", (reopen_count, pid))
        if row["is_public"]:
            # 投票数据清零 + 防重复表清空（重新投票）
            conn.execute("DELETE FROM proposal_votes WHERE proposal_id=?", (pid,))
            conn.execute("DELETE FROM proposal_vote_dedup WHERE proposal_id=?", (pid,))
            conn.execute(
                "UPDATE proposals SET status='公示中', "
                "voting_started_at=CURRENT_TIMESTAMP, voting_ended_at=datetime('now', '+3 days') "
                "WHERE id=?",
                (pid,),
            )
            conn.commit()
            new_status = "公示中"
            log_activity(actor, "重新公示（3 天）", "proposal", pid, row["title"] or "",
                         module=MODULE, before_value=old, after_value=new_status,
                         detail=f"第 {reopen_count} 次重新执行：重新公示 3 天，投票数据已清零")
        else:
            dept = (dept or "").strip() or row["executor_dept"]
            conn.execute(
                "UPDATE proposals SET status='执行中', executor_dept=? WHERE id=?",
                (dept, pid),
            )
            conn.commit()
            new_status = "执行中"
            log_activity(actor, "私有提案重新执行", "proposal", pid, row["title"] or "",
                         module=MODULE, before_value=old, after_value=new_status,
                         detail=f"重新选择部门执行：{dept}")
    return True, ""


def auto_end_unfeedback(actor: str = "系统") -> list[int]:
    """提案人 7 天未反馈满意度：自动标记已结束，视为满意（A 类自动触发）。"""
    done: list[int] = []
    with get_db() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT id, title FROM proposals WHERE status='待提案人反馈' "
            "AND resolved_at IS NOT NULL AND resolved_at < datetime('now', '-7 days')"
        ).fetchall()
        for r in rows:
            conn.execute(
                "UPDATE proposals SET status='已结束', satisfaction='满意', "
                "feedback_at=CURRENT_TIMESTAMP WHERE id=?",
                (r["id"],),
            )
            conn.commit()
            log_activity(actor, "逾期未反馈自动结束", "proposal", r["id"], r["title"] or "",
                         module=MODULE, before_value="待提案人反馈", after_value="已结束",
                         detail="7 天未反馈满意度，视为满意")
            try:
                notify_proposal_status_change(r["id"], "已结束", "7 天未反馈，系统自动视为满意，提案已结束。")
            except Exception:
                pass
            done.append(r["id"])
    return done


# ---------------------------------------------------------------------------
# 撤回 / 重新打开 / 关闭 / 下架
# ---------------------------------------------------------------------------

def withdraw_proposal(pid: int, actor: str = "居民") -> tuple[bool, str]:
    """居民撤回提案（仅待审核）。→ 已撤回。"""
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "待审核":
            return False, f"当前状态「{row['status']}」不支持撤回"
        old = row["status"]
        conn.execute("UPDATE proposals SET status='已撤回' WHERE id=?", (pid,))
        conn.commit()
    log_activity(actor, "撤回提案", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value="已撤回")
    return True, ""


def reopen_proposal(pid: int, actor: str = "居民") -> tuple[bool, str]:
    """重新打开已撤回提案。→ 待审核（可修改一次后重新审核）。"""
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] != "已撤回":
            return False, f"当前状态「{row['status']}」不支持重新打开"
        old = row["status"]
        conn.execute(
            "UPDATE proposals SET status='待审核', audit_status='待审核', audit_opinion='' WHERE id=?",
            (pid,),
        )
        conn.commit()
    log_activity(actor, "重新打开提案", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value="待审核")
    return True, ""


def close_proposal(pid: int, reason: str, actor: str = "负责人") -> tuple[bool, str]:
    """特殊情况关闭（提案人放弃/重复提案/违法违规等，需二次确认）。"""
    reason = (reason or "").strip()
    if not reason:
        return False, "关闭原因必填。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] in TERMINAL_STATUSES:
            return False, f"当前状态「{row['status']}」已结束，不能关闭"
        old = row["status"]
        conn.execute("UPDATE proposals SET status='已关闭' WHERE id=?", (pid,))
        conn.commit()
    log_activity(actor, "特殊关闭", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value="已关闭", detail=reason)
    try:
        notify_proposal_status_change(pid, "已关闭", reason)
    except Exception:
        pass
    return True, ""


def take_down_proposal(pid: int, reason: str, actor: str = "负责人") -> tuple[bool, str]:
    """违规下架（需二次确认）。"""
    reason = (reason or "").strip()
    if not reason:
        return False, "下架原因必填。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["status"] in TERMINAL_STATUSES:
            return False, f"当前状态「{row['status']}」已结束，不能下架"
        old = row["status"]
        conn.execute("UPDATE proposals SET status='违规下架' WHERE id=?", (pid,))
        conn.commit()
    log_activity(actor, "违规下架", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old, after_value="违规下架", detail=reason)
    try:
        notify_proposal_status_change(pid, "违规下架", reason)
    except Exception:
        pass
    return True, ""


# ---------------------------------------------------------------------------
# 类别修改 / 查看完整手机号
# ---------------------------------------------------------------------------

def update_category(pid: int, category: str, actor: str = "负责人") -> tuple[bool, str]:
    """修改提案类别（留痕；不影响已产生的公示数据，影响后续筛选）。"""
    if category not in VALID_CATEGORIES:
        return False, "请选择提案类别（公共设施/环境卫生/文化活动/安全治理/其他）。"
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT status, title, category FROM proposals WHERE id=?", (pid,)).fetchone()
        if row is None:
            return False, "提案不存在"
        if row["category"] == category:
            return False, "类别没有变化。"
        old_cat = row["category"]
        conn.execute("UPDATE proposals SET category=? WHERE id=?", (category, pid))
        conn.commit()
    log_activity(actor, "修改类别", "proposal", pid, row["title"] or "", module=MODULE,
                 before_value=old_cat, after_value=category)
    return True, ""


def view_full_phone(pid: int, actor: str = "负责人") -> str:
    """查看提案人完整手机号（需二次确认，留痕）。"""
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute(
            "SELECT title, reporter_name, reporter_phone FROM proposals WHERE id=?", (pid,)
        ).fetchone()
    if not row:
        return ""
    log_activity(actor, "查看完整手机号", "proposal", pid, row["title"] or "",
                 module=MODULE, detail=f"查看 {row['reporter_name'] or ''} 完整手机号")
    return row["reporter_phone"] or ""


# ---------------------------------------------------------------------------
# 查询 / 统计 / 导出
# ---------------------------------------------------------------------------

def get_proposal(pid: int) -> dict | None:
    with get_db() as conn:
        _ensure_schema(conn)
        row = conn.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        return dict(row) if row else None


def get_proposals(status: str | None = None, category: str | None = None,
                  is_public: int | None = None, keyword: str = "",
                  exclude_statuses: list[str] | None = None,
                  limit: int = 100) -> list[dict]:
    """按状态/类别/公开方式/关键词筛选提案，最新在前。"""
    q = "SELECT * FROM proposals WHERE 1=1"
    args: list = []
    if status:
        q += " AND status=?"
        args.append(status)
    if category:
        q += " AND category=?"
        args.append(category)
    if is_public is not None:
        q += " AND is_public=?"
        args.append(is_public)
    if exclude_statuses:
        q += f" AND status NOT IN ({','.join('?' * len(exclude_statuses))})"
        args.extend(exclude_statuses)
    kw = (keyword or "").strip()
    if kw:
        q += " AND (title LIKE ? OR description LIKE ?)"
        args.extend([f"%{kw}%", f"%{kw}%"])
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        _ensure_schema(conn)
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_my_proposals(user_id: int, limit: int = 50) -> list[dict]:
    """居民自己的提案（按 reporter_id 优先，兼容老数据的 author 匹配）。"""
    with get_db() as conn:
        _ensure_schema(conn)
        rows = conn.execute(
            "SELECT * FROM proposals WHERE reporter_id=? OR author=? OR author=? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, str(user_id), f"user_{user_id}", limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_pending_audit(limit: int = 100) -> list[dict]:
    """负责人待审核列表（待审核 + 退回修改）。"""
    return get_proposals(exclude_statuses=[s for s in STATUS_ALL if s not in ("待审核", "退回修改")],
                         limit=limit)


def get_pending_confirm(limit: int = 100) -> list[dict]:
    """待确认公示/私有列表。"""
    return get_proposals(status="待确认公示/私有", limit=limit)


def get_active_public(limit: int = 100) -> list[dict]:
    """居民可见的公开提案（公示中/待执行/执行中/待提案人反馈/已完成/重新执行/不予执行/违规下架/已结束）。"""
    return get_proposals(
        is_public=1,
        exclude_statuses=["待审核", "退回修改", "待确认公示/私有", "已撤回", "已关闭"],
        limit=limit,
    )


def get_proposals_stats() -> dict:
    with get_db() as conn:
        _ensure_schema(conn)
        total = conn.execute("SELECT COUNT(*) c FROM proposals").fetchone()["c"]
        by_status = {
            r["status"]: r["c"] for r in conn.execute(
                "SELECT status, COUNT(*) c FROM proposals GROUP BY status"
            ).fetchall()
        }
        by_category = {
            r["category"]: r["c"] for r in conn.execute(
                "SELECT category, COUNT(*) c FROM proposals GROUP BY category"
            ).fetchall()
        }
    return {
        "total": total or 0,
        "by_status": by_status,
        "by_category": by_category,
        "pending_audit": by_status.get("待审核", 0) + by_status.get("退回修改", 0),
        "pending_confirm": by_status.get("待确认公示/私有", 0),
        "voting": by_status.get("公示中", 0),
        "executing": by_status.get("执行中", 0),
        "completed": by_status.get("已完成", 0),
        "reopening": by_status.get("重新执行", 0),
    }


def get_proposal_timeline(pid: int, limit: int = 100) -> list[dict]:
    """提案留痕时间线（最近在前）。居民只看自己提案的状态变化。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE target_type='proposal' AND target_id=? "
            "ORDER BY id DESC LIMIT ?", (pid, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def get_export_rows() -> list[dict]:
    """导出数据（字段脱敏，不含个体投票明细、附件、其他隐私）。"""
    props = get_proposals(limit=1000)
    stats = get_vote_stats_batch([p["id"] for p in props])
    out = []
    for p in props:
        s = stats.get(p["id"], {})
        out.append({
            "提案编号": proposal_no(p["id"]),
            "标题": p["title"],
            "类别": p["category"],
            "公开/私有": "公开" if p.get("is_public") else "私有",
            "提案人（脱敏）": mask_name(p.get("reporter_name") or p.get("author") or ""),
            "电话（脱敏）": mask_phone(p.get("reporter_phone") or ""),
            "所属小区/楼栋": p.get("community_building") or "",
            "提交时间": (p.get("created_at") or "")[:16],
            "状态": p.get("status"),
            "投票人数": s.get("vote_count", 0),
            "平均分": s.get("avg_score", "") if s.get("avg_score") is not None else "",
            "执行部门": p.get("executor_dept") or "",
            "执行结果": p.get("execution_result") or "",
            "反馈状态": p.get("satisfaction") or "",
            "附件是否公开": "是" if p.get("attachment_public") else "否",
            "重新执行次数": p.get("reopen_count") or 0,
        })
    return out


def log_export(actor: str = "负责人") -> None:
    """导出动作留痕。"""
    log_activity(actor, "导出提案数据", module=MODULE,
                 detail="导出字段已脱敏，不含个体投票明细与附件")
