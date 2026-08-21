# data/db_elderly_care.py
"""老年端数据层（schema v18 新表）—— 用药提醒 / 紧急联系人 / 紧急求助 / 联系拨打。

对应《06-老年端.md》：
- 用药提醒：提交待审核 → 负责人审核 → 通过按时语音提醒；暂停/恢复；修改后重新审核，
  审核期间原规则继续播报，通过后切换新规则，不通过原规则继续生效；到期自动改「已结束」。
- 紧急联系人：设置待审核 → 审核通过后生效；删除需二次确认，删除最后一个拦截
  「至少保留一个紧急联系人」；最多 3 个。
- 紧急求助：长按触发（确认弹窗防误触）→ 按顺序拨打紧急联系人 → 负责人确认响应 →
  结束求助（二次确认 + 处理结果）；10 分钟未响应自动升级通知所有负责人。
- 联系拨打：家属/社区一键拨打，确认/取消/超时均留痕。

所有关键操作统一 log_activity(module="老年端") 留痕（操作人/时间/类型/前值/后值/关联编号）。

旧 JSON 存储（db_elderly.get_profile 的 medication_reminders / emergency_contact）
由 migrate_legacy_profile() 一次性迁移到新表，db_elderly.py 保持不动。
"""
import json
import re
from datetime import date, datetime

from data.db_core import get_db
from data.db_notifications import create_notification, log_activity

MODULE = "老年端"

# ---------- 常量 ----------
_PHONE_RE = re.compile(r"^1[3-9]\d{9}$")          # 手机号校验
_DOSAGE_RE = re.compile(r"^\d+(\.\d+)?\s*[A-Za-z\u4e00-\u9fa5]+$")  # 剂量：数字+单位，如 1片/10ml/0.5g
_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")              # HH:MM
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")      # YYYY-MM-DD
_PHOTO_EXT_RE = re.compile(r"\.(jpg|jpeg|png)$", re.IGNORECASE)

# 社区负责人联系电话（系统预置，见 spec「联系社区」）
COMMUNITY_PHONE = "62319876"
COMMUNITY_NAME = "社区负责人"

MED_STATUS = ("待审核", "审核通过", "审核不通过", "已暂停", "已结束")
CONTACT_STATUS = ("待审核", "审核通过", "审核不通过")
CALL_STATUS = ("求助中", "已响应", "已结束", "已取消")

REPEAT_RULES = ("每天", "每周固定几天", "每月固定几号", "仅一次")

# 状态 → 颜色（spec 第七节：待审核黄、审核通过绿、审核不通过红、已暂停/已结束灰）
_STATUS_COLORS = {
    "待审核": "黄", "审核通过": "绿", "审核不通过": "红",
    "已暂停": "灰", "已结束": "灰",
    "求助中": "红", "已响应": "橙", "已取消": "灰",
}

# 语音帮助默认内容（spec：未配置播放默认帮助语）
DEFAULT_HELP_TEXT = "您可以点天气看天气，点报修说问题，长按紧急求助呼叫联系人。"

# 语音播报模板（spec：固定模板）
MEDICATION_SPEECH_TEMPLATE = "{patient}您好，该吃药了：{drug}，{dosage}。{note}"


def status_color(status: str) -> str:
    """状态 → 颜色标签（页面统一用）。"""
    return _STATUS_COLORS.get(status or "", "灰")


# ---------- 校验 ----------
def _validate_phone(phone: str) -> bool:
    return bool(_PHONE_RE.match((phone or "").strip()))


def _validate_dosage(dosage: str) -> bool:
    return bool(_DOSAGE_RE.match((dosage or "").strip()))


def _parse_times(times) -> tuple[list, str]:
    """解析用药时间：list 或逗号分隔字符串 → 规范化 HH:MM 列表（1~5 个）。"""
    if isinstance(times, str):
        parts = [p.strip() for p in (times or "").replace("，", ",").split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in (times or []) if str(p).strip()]
    if not parts:
        return [], "请填写至少 1 个用药时间。"
    if len(parts) > 5:
        return [], "用药时间最多 5 个。"
    result: list[str] = []
    for p in parts:
        m = _TIME_RE.match(p)
        if not m:
            return [], f"用药时间「{p}」格式不正确，请用 08:00 这样的格式。"
        hh, mm = int(m.group(1)), int(m.group(2))
        norm = f"{hh:02d}:{mm:02d}"
        if norm not in result:
            result.append(norm)
    result.sort()
    return result, ""


def _parse_date(value, name: str) -> tuple[str, str]:
    """解析日期（date 对象或 YYYY-MM-DD 字符串），返回 (YYYY-MM-DD, err)。"""
    if value is None or value == "":
        return "", ""
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d"), ""
    s = str(value).strip()
    if not _DATE_RE.match(s):
        return "", f"{name}格式不正确，请用 YYYY-MM-DD。"
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return "", f"{name}不是有效日期。"
    return s, ""


def _parse_num_list(s: str) -> list[int]:
    """解析逗号分隔数字列表（去重、排序、过滤非法值）。"""
    nums: list[int] = []
    for p in re.split(r"[,\s，、]+", s or ""):
        p = p.strip()
        if p.isdigit():
            nums.append(int(p))
    return sorted(set(nums))


def _validate_repeat_rule(rule: str) -> tuple[str, str]:
    """校验并规范化重复周期。每周/每月支持「每周固定几天:1,3,5」后缀。"""
    rule = (rule or "").strip()
    if rule in ("每天", "仅一次"):
        return rule, ""
    if rule.startswith("每周固定几天"):
        suffix = rule.split(":", 1)[1] if ":" in rule else ""
        days = _parse_num_list(suffix)
        if not days or any(d < 1 or d > 7 for d in days):
            return "", "每周固定几天需指定星期，如「每周固定几天:1,3,5」（1=周一，7=周日）。"
        return f"每周固定几天:{','.join(map(str, days))}", ""
    if rule.startswith("每月固定几号"):
        suffix = rule.split(":", 1)[1] if ":" in rule else ""
        days = _parse_num_list(suffix)
        if not days or any(d < 1 or d > 31 for d in days):
            return "", "每月固定几号需指定日期，如「每月固定几号:1,15」。"
        return f"每月固定几号:{','.join(map(str, days))}", ""
    return "", "请选择正确的重复周期（每天/每周固定几天/每月固定几号/仅一次）。"


def _matches_repeat_rule(rule: str, d: date, start_date: str) -> bool:
    """判断某天是否落在重复周期内（d 为当天日期）。"""
    if rule == "仅一次":
        return d.strftime("%Y-%m-%d") == start_date
    if rule.startswith("每周固定几天"):
        suffix = rule.split(":", 1)[1] if ":" in rule else ""
        days = _parse_num_list(suffix)
        return (d.weekday() + 1) in days if days else True
    if rule.startswith("每月固定几号"):
        suffix = rule.split(":", 1)[1] if ":" in rule else ""
        days = _parse_num_list(suffix)
        return d.day in days if days else True
    return True  # 每天


def format_repeat_rule(rule: str) -> str:
    """把规则字符串转成人话，如「每周固定几天:1,3,5」→「每周一、周三、周五」。"""
    rule = (rule or "").strip()
    if rule.startswith("每周固定几天"):
        days = _parse_num_list(rule.split(":", 1)[1] if ":" in rule else "")
        wd = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return "每周" + "、".join(wd[d - 1] for d in days if 1 <= d <= 7)
    if rule.startswith("每月固定几号"):
        days = _parse_num_list(rule.split(":", 1)[1] if ":" in rule else "")
        return "每月" + "、".join(f"{d}号" for d in days)
    return rule or "每天"


# ---------- 小工具 ----------
def _ensure_pending_table(conn) -> None:
    """修改用药提醒的「待审核暂存表」：存原规则快照，审核期间原规则继续播报。

    惰性建表（幂等），避免在 db_core 里加迁移版本。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS medication_pending ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, reminder_id INTEGER NOT NULL UNIQUE, "
        "pending_json TEXT DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _notify_user(user_id: int | None, type_: str, title: str, content: str = "",
                 related_id: int | None = None) -> None:
    if not user_id:
        return
    try:
        create_notification(user_id, type_, title, content, related_id)
    except Exception:
        pass


def _notify_grids(title: str, content: str = "", related_id: int | None = None) -> int:
    """通知所有负责人（grid 角色）。返回收件人数。

    发送失败自动重试一次（spec：升级通知发送失败 → 记录失败日志再尝试一次，
    仍失败通知负责人手动处理）。
    """
    for attempt in range(2):
        try:
            from data.db_user import list_users
            grids = list_users(role="grid")
            sent = 0
            for g in grids:
                try:
                    _notify_user(g["id"], "sos", title, content, related_id)
                    sent += 1
                except Exception:
                    pass
            if sent >= len(grids):
                return sent
            # 部分失败：重试一次
            if attempt == 1:
                try:
                    from data.db_notifications import log_exception
                    log_exception("老年端", f"紧急求助通知负责人失败（{title[:30]}）：{sent}/{len(grids)} 送达")
                except Exception:
                    pass
                return sent
        except Exception:
            if attempt == 1:
                try:
                    from data.db_notifications import log_exception
                    log_exception("老年端", f"紧急求助通知负责人异常（{title[:30]}）")
                except Exception:
                    pass
                return 0
    return 0


# =====================================================================
# 一、用药提醒
# =====================================================================

def add_medication_reminder(user_id: int, patient_name: str, drug_name: str,
                            dosage: str, times, repeat_rule: str = "每天",
                            start_date="", end_date="", note: str = "",
                            photo: str = "", setter_id: int | None = None,
                            actor: str = "") -> tuple[int, str]:
    """新增用药提醒（状态：待审核）。返回 (id, 错误提示)。"""
    patient_name = (patient_name or "").strip()
    drug_name = (drug_name or "").strip()
    dosage = (dosage or "").strip()
    note = (note or "").strip()
    if not patient_name:
        return 0, "请填写用药人姓名。"
    if not drug_name:
        return 0, "请填写药品名称。"
    if not _validate_dosage(dosage):
        return 0, "剂量格式不正确，请填如「1片」「10ml」。"
    times_list, err = _parse_times(times)
    if err:
        return 0, err
    rule, err = _validate_repeat_rule(repeat_rule)
    if err:
        return 0, err
    start_date, err = _parse_date(start_date, "开始日期")
    if err:
        return 0, err
    if not start_date:
        return 0, "请填写开始日期。"
    end_date = (end_date or "").strip()
    if end_date:
        end_date, err = _parse_date(end_date, "结束日期")
        if err:
            return 0, err
        if end_date < start_date:
            return 0, "结束日期必须晚于开始日期。"
    if photo and not _PHOTO_EXT_RE.search(photo):
        return 0, "药品照片仅支持 jpg/png 格式。"

    actor = actor or patient_name
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO medication_reminders (user_id, patient_name, drug_name, dosage, "
            "times_json, repeat_rule, start_date, end_date, note, photo, setter_id, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,'待审核')",
            (user_id, patient_name, drug_name, dosage,
             json.dumps(times_list, ensure_ascii=False), rule, start_date, end_date,
             note, photo, setter_id),
        )
        rid = cur.lastrowid
        conn.commit()

    log_activity(actor, "提交用药提醒", "medication_reminder", rid,
                 f"{patient_name} - {drug_name}", module=MODULE, after_value="待审核",
                 detail=f"剂量：{dosage}；时间：{'、'.join(times_list)}；周期：{format_repeat_rule(rule)}"
                        + (f"；备注：{note}" if note else ""))
    return rid, ""


def _apply_pending_values(conn, reminder_id: int, pending: dict) -> None:
    """把待审核的新规则落到提醒行（审核通过时切换新规则）。"""
    conn.execute(
        "UPDATE medication_reminders SET patient_name=?, drug_name=?, dosage=?, "
        "times_json=?, repeat_rule=?, start_date=?, end_date=?, note=?, photo=?, "
        "status='审核通过', audit_opinion='', audited_at=CURRENT_TIMESTAMP, "
        "updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (pending.get("patient_name", ""), pending.get("drug_name", ""),
         pending.get("dosage", ""),
         json.dumps(pending.get("times", []), ensure_ascii=False),
         pending.get("repeat_rule", "每天"), pending.get("start_date", ""),
         pending.get("end_date", ""), pending.get("note", ""), pending.get("photo", ""),
         reminder_id),
    )
    conn.execute("DELETE FROM medication_pending WHERE reminder_id=?", (reminder_id,))


def audit_medication(reminder_id: int, approve: bool, opinion: str = "",
                     actor: str = "负责人") -> tuple[bool, str]:
    """负责人审核用药提醒。

    approve=True → 审核通过（有待审核修改时切换新规则）；
    approve=False → 审核不通过（必填意见）。修改被退回时原规则继续生效（回审核通过）。
    """
    opinion = (opinion or "").strip()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM medication_reminders WHERE id=?", (reminder_id,)
        ).fetchone()
        if row is None:
            return False, "用药提醒不存在"
        if row["status"] != "待审核":
            return False, f"当前状态「{row['status']}」不支持审核"
        if not approve and not opinion:
            return False, "审核不通过必须填写审核意见"

        _ensure_pending_table(conn)
        pending = conn.execute(
            "SELECT pending_json FROM medication_pending WHERE reminder_id=?",
            (reminder_id,),
        ).fetchone()
        has_pending = pending is not None
        old_status = row["status"]

        if approve:
            if has_pending:
                _apply_pending_values(conn, reminder_id, json.loads(pending["pending_json"] or "{}"))
                after_value = "审核通过（新规则生效）"
            else:
                conn.execute(
                    "UPDATE medication_reminders SET status='审核通过', audit_opinion='', "
                    "audited_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reminder_id,),
                )
                after_value = "审核通过"
        else:
            if has_pending:
                # 修改被退回：原规则继续生效，退回审核通过并保留意见
                conn.execute(
                    "UPDATE medication_reminders SET status='审核通过', audit_opinion=?, "
                    "audited_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (opinion, reminder_id),
                )
                conn.execute("DELETE FROM medication_pending WHERE reminder_id=?", (reminder_id,))
                after_value = "审核通过（修改未通过，原规则继续）"
            else:
                conn.execute(
                    "UPDATE medication_reminders SET status='审核不通过', audit_opinion=?, "
                    "audited_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (opinion, reminder_id),
                )
                after_value = "审核不通过"
        conn.commit()

    title = f"{row['patient_name']} - {row['drug_name']}"
    log_activity(actor, "审核通过" if approve else "审核不通过",
                 "medication_reminder", reminder_id, title, module=MODULE,
                 before_value=old_status, after_value=after_value, detail=opinion)

    # 通过后通知设置人开始生效；不通过通知修改重新提交
    target_uid = row["setter_id"] or row["user_id"]
    if approve:
        _notify_user(target_uid, "medication_audit", "✅ 用药提醒审核通过",
                     f"{row['patient_name']}的「{row['drug_name']}」提醒已生效，将按时语音提醒。",
                     related_id=reminder_id)
    else:
        _notify_user(target_uid, "medication_audit", "❌ 用药提醒审核不通过",
                     f"「{row['drug_name']}」提醒未通过：{opinion}，可修改后重新提交。",
                     related_id=reminder_id)
    return True, ""


def pause_medication(reminder_id: int, actor: str = "") -> tuple[bool, str]:
    """暂停用药提醒（仅审核通过）。→ 已暂停。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM medication_reminders WHERE id=?", (reminder_id,)
        ).fetchone()
        if row is None:
            return False, "用药提醒不存在"
        if row["status"] != "审核通过":
            return False, f"当前状态「{row['status']}」不支持暂停"
        conn.execute(
            "UPDATE medication_reminders SET status='已暂停', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reminder_id,),
        )
        conn.commit()
    log_activity(actor or row["patient_name"], "暂停用药提醒", "medication_reminder",
                 reminder_id, f"{row['patient_name']} - {row['drug_name']}",
                 module=MODULE, before_value="审核通过", after_value="已暂停")
    return True, ""


def resume_medication(reminder_id: int, actor: str = "") -> tuple[bool, str]:
    """恢复用药提醒（仅已暂停）。→ 审核通过。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM medication_reminders WHERE id=?", (reminder_id,)
        ).fetchone()
        if row is None:
            return False, "用药提醒不存在"
        if row["status"] != "已暂停":
            return False, f"当前状态「{row['status']}」不支持恢复"
        conn.execute(
            "UPDATE medication_reminders SET status='审核通过', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (reminder_id,),
        )
        conn.commit()
    log_activity(actor or row["patient_name"], "恢复用药提醒", "medication_reminder",
                 reminder_id, f"{row['patient_name']} - {row['drug_name']}",
                 module=MODULE, before_value="已暂停", after_value="审核通过")
    return True, ""


def modify_medication(reminder_id: int, patient_name: str, drug_name: str,
                      dosage: str, times, repeat_rule: str = "每天",
                      start_date="", end_date="", note: str = "",
                      photo: str = "", actor: str = "") -> tuple[bool, str]:
    """修改用药提醒 → 状态回「待审核」重新审核。

    - 原已审核通过/已暂停：原规则快照存 medication_pending，审核期间原规则继续播报，
      通过后切换新规则，不通过原规则继续生效。
    - 原审核不通过：直接覆盖（从未生效，无需保留原规则）。
    - 已结束：不允许修改。
    """
    patient_name = (patient_name or "").strip()
    drug_name = (drug_name or "").strip()
    dosage = (dosage or "").strip()
    note = (note or "").strip()
    if not patient_name:
        return False, "请填写用药人姓名。"
    if not drug_name:
        return False, "请填写药品名称。"
    if not _validate_dosage(dosage):
        return False, "剂量格式不正确，请填如「1片」「10ml」。"
    times_list, err = _parse_times(times)
    if err:
        return False, err
    rule, err = _validate_repeat_rule(repeat_rule)
    if err:
        return False, err
    start_date, err = _parse_date(start_date, "开始日期")
    if err:
        return False, err
    if not start_date:
        return False, "请填写开始日期。"
    end_date = (end_date or "").strip()
    if end_date:
        end_date, err = _parse_date(end_date, "结束日期")
        if err:
            return False, err
        if end_date < start_date:
            return False, "结束日期必须晚于开始日期。"
    if photo and not _PHOTO_EXT_RE.search(photo):
        return False, "药品照片仅支持 jpg/png 格式。"

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM medication_reminders WHERE id=?", (reminder_id,)
        ).fetchone()
        if row is None:
            return False, "用药提醒不存在"
        if row["status"] == "已结束":
            return False, "已结束的用药提醒不支持修改。"
        old_status = row["status"]

        _ensure_pending_table(conn)
        already_pending = conn.execute(
            "SELECT 1 FROM medication_pending WHERE reminder_id=?", (reminder_id,)
        ).fetchone()

        if old_status in ("审核通过", "已暂停") and not already_pending:
            # 原规则行内值保留（审核期间继续播报），新规则存 pending 表，通过后切换
            pending_new = {
                "patient_name": patient_name, "drug_name": drug_name,
                "dosage": dosage, "times": times_list, "repeat_rule": rule,
                "start_date": start_date, "end_date": end_date,
                "note": note, "photo": photo,
            }
            conn.execute(
                "INSERT INTO medication_pending (reminder_id, pending_json) VALUES (?, ?)",
                (reminder_id, json.dumps(pending_new, ensure_ascii=False)),
            )
            # 只回待审核，不覆盖行内原规则
            conn.execute(
                "UPDATE medication_reminders SET status='待审核', audit_opinion='', "
                "audited_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (reminder_id,),
            )
        elif old_status == "审核不通过":
            # 从未生效：直接覆盖为新值并回待审核
            conn.execute(
                "UPDATE medication_reminders SET patient_name=?, drug_name=?, dosage=?, "
                "times_json=?, repeat_rule=?, start_date=?, end_date=?, note=?, photo=?, "
                "status='待审核', audit_opinion='', audited_at=NULL, "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (patient_name, drug_name, dosage,
                 json.dumps(times_list, ensure_ascii=False), rule, start_date, end_date,
                 note, photo, reminder_id),
            )
        else:
            # 待审核（含已有 pending）：只更新新值进 pending，行内原规则继续保留
            if already_pending:
                pending_new = {
                    "patient_name": patient_name, "drug_name": drug_name,
                    "dosage": dosage, "times": times_list, "repeat_rule": rule,
                    "start_date": start_date, "end_date": end_date,
                    "note": note, "photo": photo,
                }
                conn.execute(
                    "UPDATE medication_pending SET pending_json=? WHERE reminder_id=?",
                    (json.dumps(pending_new, ensure_ascii=False), reminder_id),
                )
                conn.execute(
                    "UPDATE medication_reminders SET audit_opinion='', audited_at=NULL, "
                    "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (reminder_id,),
                )
        conn.commit()

    log_activity(actor or patient_name, "修改用药提醒并重新提交审核", "medication_reminder",
                 reminder_id, f"{patient_name} - {drug_name}", module=MODULE,
                 before_value=old_status, after_value="待审核",
                 detail=f"剂量：{dosage}；时间：{'、'.join(times_list)}；周期：{format_repeat_rule(rule)}")
    return True, ""


def get_due_medications(user_id: int | None = None, now: datetime | None = None,
                        minutes: int = 30) -> list[dict]:
    """查现在 ±minutes 分钟内到点的用药提醒（含播报内容）。

    只播报「审核通过」以及「待审核但有修改待批（原规则继续生效）」的提醒；
    过期（end_date 早于今天 / 仅一次已过）自动改「已结束」并留痕、通知设置人。
    """
    now = now or datetime.now()
    today = now.date()
    with get_db() as conn:
        _ensure_pending_table(conn)
        q = (
            "SELECT r.* FROM medication_reminders r WHERE r.status='审核通过' "
            "OR (r.status='待审核' AND r.id IN (SELECT reminder_id FROM medication_pending))"
        )
        args: list = []
        if user_id:
            q += " AND r.user_id=?"
            args.append(user_id)
        rows = conn.execute(q, args).fetchall()

        due: list[dict] = []
        for r in rows:
            end_date = (r["end_date"] or "").strip()
            start_date = (r["start_date"] or "").strip()
            rule = (r["repeat_rule"] or "每天").strip()

            # 到期自动停止
            expired = False
            if end_date and end_date < today.strftime("%Y-%m-%d"):
                expired = True
            elif rule == "仅一次" and start_date and today.strftime("%Y-%m-%d") > start_date:
                expired = True
            if expired:
                conn.execute(
                    "UPDATE medication_reminders SET status='已结束', updated_at=CURRENT_TIMESTAMP "
                    "WHERE id=? AND status IN ('审核通过','待审核')",
                    (r["id"],),
                )
                conn.commit()
                _notify_user(r["setter_id"] or r["user_id"], "medication_audit",
                             "⏰ 用药提醒已到期自动停止",
                             f"{r['patient_name']}的「{r['drug_name']}」提醒已结束。",
                             related_id=r["id"])
                log_activity("系统", "用药提醒到期自动停止", "medication_reminder", r["id"],
                             f"{r['patient_name']} - {r['drug_name']}", module=MODULE,
                             before_value="审核通过", after_value="已结束")
                continue

            if start_date and today.strftime("%Y-%m-%d") < start_date:
                continue  # 未到开始日期
            if not _matches_repeat_rule(rule, today, start_date):
                continue

            try:
                times = json.loads(r["times_json"] or "[]")
            except (json.JSONDecodeError, TypeError):
                times = []
            for t in times:
                try:
                    hh, mm = map(int, str(t).split(":"))
                    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                except (ValueError, AttributeError):
                    continue
                if abs((now - target).total_seconds()) <= minutes * 60:
                    note = (r["note"] or "").strip()
                    due.append({
                        "reminder_id": r["id"],
                        "patient_name": r["patient_name"],
                        "drug_name": r["drug_name"],
                        "dosage": r["dosage"],
                        "time": t,
                        "note": note,
                        "repeat_rule": rule,
                        "speech": MEDICATION_SPEECH_TEMPLATE.format(
                            patient=r["patient_name"], drug=r["drug_name"],
                            dosage=r["dosage"], note=f"备注：{note}。" if note else ""),
                    })
        return due


def _medication_row_to_dict(row, has_pending: bool = False) -> dict:
    d = dict(row)
    try:
        d["times"] = json.loads(d.get("times_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["times"] = []
    d["pending"] = bool(has_pending)
    return d


def get_medication_reminder(reminder_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM medication_reminders WHERE id=?", (reminder_id,)
        ).fetchone()
        if row is None:
            return None
        _ensure_pending_table(conn)
        has_pending = conn.execute(
            "SELECT 1 FROM medication_pending WHERE reminder_id=?", (reminder_id,)
        ).fetchone() is not None
        return _medication_row_to_dict(row, has_pending)


def list_medication_reminders(user_id: int | None = None,
                              status: str | None = None) -> list[dict]:
    """列表。排序：待审核/审核不通过最前，审核通过按用药时间，已暂停/已结束最后。"""
    q = "SELECT * FROM medication_reminders WHERE 1=1"
    args: list = []
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY created_at DESC"
    with get_db() as conn:
        _ensure_pending_table(conn)
        rows = conn.execute(q, args).fetchall()
        pending_ids = {
            r["reminder_id"] for r in conn.execute("SELECT reminder_id FROM medication_pending")
        }
        result = [_medication_row_to_dict(r, r["id"] in pending_ids) for r in rows]

    def _prio(m: dict) -> int:
        s = m["status"]
        if s in ("待审核", "审核不通过"):
            return 0
        if s == "审核通过":
            return 1
        return 2

    result.sort(key=lambda m: (_prio(m), m["times"][0] if m["times"] else "99:99"))
    return result


def remind_unreviewed_medications() -> list[dict]:
    """用药提醒审核超时提醒（scheduler 调用）：
      1. 待审核超 24 小时 → 通知负责人（每天一次幂等）；
      2. 审核不通过超 7 天未修改 → 通知设置人。
    """
    reminded: list[dict] = []
    today = datetime.utcnow().strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, drug_name, patient_name, status, created_at FROM medication_reminders "
            "WHERE status='待审核' AND created_at < datetime('now', '-1 day')"
        ).fetchall()
        for r in rows:
            done = conn.execute(
                "SELECT id FROM activity_log WHERE module='老年端' AND action='用药审核超时提醒' "
                "AND target_type='medication_reminder' AND target_id=? AND substr(created_at,1,10)=? LIMIT 1",
                (r["id"], today),
            ).fetchone()
            if done:
                continue
            reminded.append({"id": r["id"], "drug": r["drug_name"], "kind": "unreviewed"})
        rejected = conn.execute(
            "SELECT id, drug_name, patient_name, status, created_at FROM medication_reminders "
            "WHERE status='审核不通过' AND created_at < datetime('now', '-7 day')"
        ).fetchall()
        for r in rejected:
            done = conn.execute(
                "SELECT id FROM activity_log WHERE module='老年端' AND action='用药修改超期提醒' "
                "AND target_type='medication_reminder' AND target_id=? AND substr(created_at,1,10)=? LIMIT 1",
                (r["id"], today),
            ).fetchone()
            if done:
                continue
            reminded.append({"id": r["id"], "drug": r["drug_name"], "kind": "rejected"})
    for item in reminded:
        if item["kind"] == "unreviewed":
            log_activity("系统", "用药审核超时提醒", "medication_reminder", item["id"],
                         target_title=item["drug"], module=MODULE,
                         detail="用药提醒待审核超过 24 小时，请尽快审核")
            try:
                from data.db_user import list_users
                for u in list_users(role="grid"):
                    from data.db_notifications import create_notification
                    create_notification(u["id"], "medication",
                                        "⏰ 用药提醒待审核超时",
                                        f"「{item['drug']}」用药提醒待审核已超过 24 小时，请尽快处理。")
            except Exception:
                pass
        else:
            log_activity("系统", "用药修改超期提醒", "medication_reminder", item["id"],
                         target_title=item["drug"], module=MODULE,
                         detail="审核不通过已超过 7 天未修改，请提醒设置人补充")
    return reminded


def get_medication_timeline(reminder_id: int) -> list[dict]:
    """用药提醒审核/操作留痕时间线（最近在前）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE target_type='medication_reminder' "
            "AND target_id=? ORDER BY created_at DESC", (reminder_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# 二、紧急联系人
# =====================================================================

def add_emergency_contact(user_id: int, name: str, phone: str, relation: str,
                          setter_id: int | None = None, actor: str = "") -> tuple[int, str]:
    """新增紧急联系人（状态：待审核；最多 3 个）。返回 (id, 错误提示)。"""
    name = (name or "").strip()
    phone = (phone or "").strip()
    relation = (relation or "").strip()
    if not name:
        return 0, "请填写联系人姓名。"
    if not _validate_phone(phone):
        return 0, "手机号格式不正确（应为 11 位，如 13900001111）。"
    if not relation:
        return 0, "请填写与老人的关系。"
    with get_db() as conn:
        cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM emergency_contacts WHERE user_id=?", (user_id,)
        ).fetchone()["cnt"]
        if cnt >= 3:
            return 0, "紧急联系人最多 3 个，请先删除一个再添加。"
        cur = conn.execute(
            "INSERT INTO emergency_contacts (user_id, name, phone, relation, setter_id, status) "
            "VALUES (?,?,?,?,?,'待审核')",
            (user_id, name, phone, relation, setter_id),
        )
        cid = cur.lastrowid
        conn.commit()

    log_activity(actor or name, "提交紧急联系人", "emergency_contact", cid,
                 f"{relation} - {name}", module=MODULE, after_value="待审核",
                 detail=f"电话：{phone[:3]}****{phone[-4:]}")
    return cid, ""


def audit_emergency_contact(contact_id: int, approve: bool, opinion: str = "",
                            actor: str = "负责人") -> tuple[bool, str]:
    """负责人审核紧急联系人。通过后生效；不通过必填意见退回修改。"""
    opinion = (opinion or "").strip()
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_contacts WHERE id=?", (contact_id,)
        ).fetchone()
        if row is None:
            return False, "紧急联系人不存在"
        if row["status"] != "待审核":
            return False, f"当前状态「{row['status']}」不支持审核"
        if not approve and not opinion:
            return False, "审核不通过必须填写审核意见"
        new_status = "审核通过" if approve else "审核不通过"
        conn.execute(
            "UPDATE emergency_contacts SET status=?, audit_opinion=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (new_status, "" if approve else opinion, contact_id),
        )
        conn.commit()

    log_activity(actor, "审核通过" if approve else "审核不通过",
                 "emergency_contact", contact_id, f"{row['relation']} - {row['name']}",
                 module=MODULE, before_value="待审核", after_value=new_status, detail=opinion)
    if approve:
        _notify_user(row["user_id"], "emergency_contact", "✅ 紧急联系人已审核通过",
                     f"{row['name']}（{row['relation']}）已生效，可用于紧急求助拨打。",
                     related_id=contact_id)
    else:
        _notify_user(row["user_id"], "emergency_contact", "❌ 紧急联系人审核不通过",
                     f"{row['name']}（{row['relation']}）：{opinion}，可修改后重新提交。",
                     related_id=contact_id)
    return True, ""


def modify_emergency_contact(contact_id: int, name: str, phone: str, relation: str,
                             actor: str = "") -> tuple[bool, str]:
    """修改紧急联系人（spec：老人/家属可修改，修改后需重新审核）。

    修改即置回「待审核」重新走审核；旧信息在审核意见中保留以便负责人核对。
    """
    name = (name or "").strip()
    phone = (phone or "").strip()
    relation = (relation or "").strip()
    if not name:
        return False, "联系人姓名不能为空"
    if len(phone) != 11 or not phone.isdigit() or not phone.startswith("1"):
        return False, "请输入正确的 11 位手机号"
    if not relation:
        return False, "请填写与老人关系"
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_contacts WHERE id=?", (contact_id,)
        ).fetchone()
        if row is None:
            return False, "紧急联系人不存在"
        old = f"{row['relation']} {row['name']} {row['phone'][:3]}****{row['phone'][-4:]}"
        conn.execute(
            "UPDATE emergency_contacts SET name=?, phone=?, relation=?, status='待审核', "
            "audit_opinion='', updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (name, phone, relation, contact_id),
        )
        conn.commit()
    log_activity(actor or name, "修改紧急联系人", "emergency_contact", contact_id,
                 f"{relation} - {name}", module=MODULE,
                 before_value=old, after_value=f"{relation} {name} {phone[:3]}****{phone[-4:]}",
                 detail="修改后需重新审核；修改前信息：{}".format(old))
    _notify_user(row["user_id"], "emergency_contact",
                 "📝 紧急联系人已修改，待重新审核",
                 f"{name}（{relation}）修改已提交，负责人审核通过后生效。",
                 related_id=contact_id)
    return True, ""


def delete_emergency_contact(contact_id: int, actor: str = "") -> tuple[bool, str]:
    """删除紧急联系人（二次确认由页面负责）。删除最后一个要拦截。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_contacts WHERE id=?", (contact_id,)
        ).fetchone()
        if row is None:
            return False, "紧急联系人不存在"
        cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM emergency_contacts WHERE user_id=?",
            (row["user_id"],),
        ).fetchone()["cnt"]
        if cnt <= 1:
            return False, "至少保留一个紧急联系人，不能删除最后一个。"
        conn.execute("DELETE FROM emergency_contacts WHERE id=?", (contact_id,))
        conn.commit()

    log_activity(actor or row["name"], "删除紧急联系人", "emergency_contact", contact_id,
                 f"{row['relation']} - {row['name']}", module=MODULE,
                 before_value=row["status"], after_value="已删除",
                 detail=f"电话：{row['phone'][:3]}****{row['phone'][-4:]}")
    _notify_user(row["user_id"], "emergency_contact", "📋 紧急联系人已删除",
                 f"{row['name']}（{row['relation']}）已删除。", related_id=contact_id)
    return True, ""


def get_emergency_contact(contact_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_contacts WHERE id=?", (contact_id,)
        ).fetchone()
        return dict(row) if row else None


def list_emergency_contacts(user_id: int | None = None) -> list[dict]:
    """列表。审核通过在前，其余按创建时间倒序。"""
    q = "SELECT * FROM emergency_contacts WHERE 1=1"
    args: list = []
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    q += " ORDER BY created_at DESC"
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        result = [dict(r) for r in rows]

    prio = {"审核通过": 0, "待审核": 1, "审核不通过": 2}
    result.sort(key=lambda c: (prio.get(c["status"], 3), c["created_at"] or ""))
    return result


def get_approved_contacts(user_id: int) -> list[dict]:
    """已审核通过的紧急联系人（紧急求助按此顺序拨打，最多 3 个）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM emergency_contacts WHERE user_id=? AND status='审核通过' "
            "ORDER BY created_at ASC", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_contact_timeline(contact_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE target_type='emergency_contact' "
            "AND target_id=? ORDER BY created_at DESC", (contact_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# 三、紧急求助（长按触发 → 拨打 → 响应 → 结束 / 升级）
# =====================================================================

def _latest_sos(conn, user_id: int | None = None, status: str | None = None):
    q = "SELECT * FROM emergency_calls WHERE call_type='sos'"
    args: list = []
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY id DESC LIMIT 1"
    return conn.execute(q, args).fetchone()


def trigger_sos(user_id: int, actor: str = "") -> tuple[int, str]:
    """触发紧急求助（老人长按 3 秒确认后调用）。

    校验：必须有已审核通过的紧急联系人；已有进行中的求助不重复触发。
    触发即通知所有负责人（最高优先级），并按顺序开始拨打。
    """
    approved = get_approved_contacts(user_id)
    if not approved:
        return 0, "还没有审核通过的紧急联系人，无法触发紧急求助。"
    with get_db() as conn:
        active = _latest_sos(conn, user_id=user_id, status="求助中")
        responded = _latest_sos(conn, user_id=user_id, status="已响应")
        if active is not None:
            return active["id"], "已有进行中的紧急求助，请等待处理。"
        if responded is not None:
            return responded["id"], "紧急求助已被响应，请等待处理。"

        first = approved[0]
        cur = conn.execute(
            "INSERT INTO emergency_calls (user_id, call_type, target_name, target_phone, "
            "result, status) VALUES (?, 'sos', ?, ?, '已触发，正在呼叫', '求助中')",
            (user_id, first["name"], first["phone"]),
        )
        call_id = cur.lastrowid
        conn.commit()

    actor = actor or "老人"
    names = "、".join(c["name"] for c in approved)
    log_activity(actor, "触发紧急求助", "emergency_call", call_id, "紧急求助",
                 module=MODULE, after_value="求助中",
                 detail=f"将依次呼叫：{names}；紧急联系人：{names}")

    from data.db_elderly import get_profile
    elder = get_profile(user_id)
    address = elder.get("address") or ""
    phone = ""
    try:
        from data.db_user import get_user_by_id
        u = get_user_by_id(user_id) or {}
        phone = u.get("phone") or ""
        address = address or f"{u.get('community') or ''}{u.get('building') or ''}{u.get('unit') or ''}"
    except Exception:
        pass
    content = (f"老人姓名：{actor}，电话：{phone}，住址：{address}；"
               f"紧急联系人：{names}；触发时间：{datetime.now().strftime('%H:%M')}；状态：紧急求助中。")
    _notify_grids(f"⚠️ 紧急求助：{actor}", content, call_id)
    return call_id, ""


def respond_sos(call_id: int, actor: str = "负责人") -> tuple[bool, str]:
    """负责人确认响应求助。→ 已响应。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_calls WHERE id=?", (call_id,)
        ).fetchone()
        if row is None:
            return False, "求助记录不存在"
        if row["status"] != "求助中":
            return False, f"当前状态「{row['status']}」不支持响应"
        conn.execute(
            "UPDATE emergency_calls SET status='已响应', handled_at=CURRENT_TIMESTAMP WHERE id=?",
            (call_id,),
        )
        conn.commit()
    log_activity(actor, "确认响应紧急求助", "emergency_call", call_id, "紧急求助",
                 module=MODULE, before_value="求助中", after_value="已响应")
    _notify_user(row["user_id"], "sos", "✅ 负责人已响应您的紧急求助",
                 "请保持电话畅通，工作人员正在赶来。", related_id=call_id)
    return True, ""


def end_sos(call_id: int, handle_note: str, actor: str = "负责人") -> tuple[bool, str]:
    """结束求助（负责人二次确认后，必填处理结果）。→ 已结束。"""
    handle_note = (handle_note or "").strip()
    if not handle_note:
        return False, "请填写处理结果和备注。"
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_calls WHERE id=?", (call_id,)
        ).fetchone()
        if row is None:
            return False, "求助记录不存在"
        if row["status"] not in ("求助中", "已响应"):
            return False, f"当前状态「{row['status']}」不支持结束"
        old = row["status"]
        conn.execute(
            "UPDATE emergency_calls SET status='已结束', handle_note=?, "
            "handled_at=CURRENT_TIMESTAMP WHERE id=?",
            (handle_note, call_id),
        )
        conn.commit()
    log_activity(actor, "结束紧急求助", "emergency_call", call_id, "紧急求助",
                 module=MODULE, before_value=old, after_value="已结束", detail=handle_note)
    _notify_user(row["user_id"], "sos", "✅ 您的紧急求助已处理",
                 f"处理结果：{handle_note}", related_id=call_id)
    return True, ""


def escalate_sos(call_id: int, actor: str = "系统", minutes: int | None = None) -> tuple[bool, str]:
    """负责人未响应升级：首次 10 分钟未响应升级，之后每 5 分钟提醒一次，最多 3 次（spec）。

    幂等：时间不足/已升级满 3 次返回 False 不重复通知。状态保持「求助中」。
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_calls WHERE id=?", (call_id,)
        ).fetchone()
        if row is None:
            return False, "求助记录不存在"
        if row["status"] != "求助中":
            return False, ""
        created = row["created_at"] or ""
        try:
            created_dt = datetime.strptime(str(created)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False, ""
        # 已升级次数：0 次 → 首升等 10 分钟；之后每 5 分钟提醒（spec）
        _prev_count = (row["result"] or "").count("已升级")
        if minutes is None:
            minutes = 10 if _prev_count == 0 else 5
        age_min = (datetime.utcnow() - created_dt).total_seconds() / 60.0
        if age_min < minutes:
            return False, ""
        result = row["result"] or ""
        count = result.count("已升级")
        if count >= 3:
            return False, "已升级 3 次，不再重复升级"
        count += 1
        if result:
            new_result = f"{result}；已升级{count}次（{minutes}分钟未响应）"
        else:
            new_result = f"已升级：负责人{minutes}分钟未响应（第{count}次）"
        conn.execute(
            "UPDATE emergency_calls SET result=? WHERE id=?", (new_result, call_id)
        )
        conn.commit()
    _notify_grids(f"🚨 紧急求助升级（{count}次）：尚未响应",
                  f"紧急求助已 {minutes} 分钟无人确认响应，请立即处理。", call_id)
    log_activity(actor, "紧急求助升级通知", "emergency_call", call_id, "紧急求助",
                 module=MODULE, detail=f"{minutes}分钟未响应，升级第{count}次")
    return True, ""


def cancel_sos(call_id: int, reason: str = "老人撤销", actor: str = "老人") -> tuple[bool, str]:
    """撤销/取消求助。→ 已取消。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_calls WHERE id=?", (call_id,)
        ).fetchone()
        if row is None:
            return False, "求助记录不存在"
        if row["status"] not in ("求助中", "已响应"):
            return False, f"当前状态「{row['status']}」不支持取消"
        old = row["status"]
        conn.execute(
            "UPDATE emergency_calls SET status='已取消', result=?, handled_at=CURRENT_TIMESTAMP "
            "WHERE id=?",
            (reason, call_id),
        )
        conn.commit()
    log_activity(actor, "取消紧急求助", "emergency_call", call_id, "紧急求助",
                 module=MODULE, before_value=old, after_value="已取消", detail=reason)
    return True, ""


def get_sos_call(call_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM emergency_calls WHERE id=?", (call_id,)).fetchone()
        return dict(row) if row else None


def get_latest_sos(user_id: int) -> dict | None:
    with get_db() as conn:
        row = _latest_sos(conn, user_id=user_id)
        return dict(row) if row else None


def get_sos_calls(user_id: int | None = None, status: str | None = None,
                  limit: int = 20) -> list[dict]:
    q = "SELECT * FROM emergency_calls WHERE call_type='sos'"
    args: list = []
    if user_id:
        q += " AND user_id=?"
        args.append(user_id)
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_sos_timeline(call_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE target_type='emergency_call' "
            "AND target_id=? ORDER BY created_at DESC", (call_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# 四、联系拨打记录（家属/社区一键拨打，简单留痕）
# =====================================================================

def log_emergency_call(user_id: int, call_type: str, target_name: str,
                       target_phone: str, result: str = "已拨打",
                       status: str = "已结束", actor: str = "") -> int:
    """记一条拨打记录（emergency_calls，call_type=contact/sos）。

    确认拨打 → result「已拨打」；取消 → result「已取消」；
    确认超时 → result「确认超时，已取消」。返回记录 ID。
    """
    if call_type not in ("sos", "contact"):
        call_type = "contact"
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO emergency_calls (user_id, call_type, target_name, target_phone, "
            "result, status) VALUES (?,?,?,?,?,?)",
            (user_id, call_type, target_name, target_phone, result, status),
        )
        call_id = cur.lastrowid
        conn.commit()
    log_activity(actor or target_name or "老人", "联系拨打", "emergency_call", call_id,
                 target_name or "", module=MODULE, after_value=result,
                 detail=f"类型：{'紧急求助' if call_type == 'sos' else '联系'}；对象：{target_name}；"
                        f"电话：{str(target_phone)[:3]}****{str(target_phone)[-4:]}")
    return call_id


def log_sos_dial(call_id: int, target_name: str, target_phone: str, result: str,
                 actor: str = "") -> None:
    """记一次紧急求助拨号留痕（activity_log，不占 emergency_calls 事件行）。

    emergency_calls 里 call_type='sos' 的行只存「求助事件」本身（状态机流转），
    每次拨号的时间/对象/结果统一走 activity_log，避免事件行被拨号记录污染。
    """
    log_activity(actor or target_name or "老人", "紧急求助拨号", "emergency_call", call_id,
                 target_name or "", module=MODULE, after_value=result,
                 detail=f"拨打：{target_name} {target_phone}；结果：{result}")


def get_latest_contact_call(user_id: int) -> dict | None:
    """最近一条联系拨打记录（首页「最近联系」）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM emergency_calls WHERE user_id=? AND call_type='contact' "
            "ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_recent_contact_calls(user_id: int, limit: int = 5) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM emergency_calls WHERE user_id=? AND call_type='contact' "
            "ORDER BY id DESC LIMIT ?", (user_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# =====================================================================
# 五、旧 JSON 数据迁移（db_elderly.py 保持不动）
# =====================================================================

def migrate_legacy_profile(user_id: int, actor: str = "系统") -> dict:
    """把 elderly_profile 里 JSON 存的用药提醒/紧急联系人迁移到新表（幂等）。

    旧数据是历史生效数据，直接按「审核通过」入库（免审核），仅迁移一次：
    新表里已有该用户的记录就不再迁移。返回 {"meds": n, "contacts": n}。
    """
    result = {"meds": 0, "contacts": 0}
    if not user_id:
        return result
    try:
        from data.db_elderly import get_profile
        from data.db_user import get_user_by_id
    except Exception:
        return result
    try:
        elder = get_profile(user_id) or {}
    except Exception:
        return result

    u = {}
    try:
        u = get_user_by_id(user_id) or {}
    except Exception:
        pass
    patient_name = (u.get("name") or elder.get("name") or "老人")

    migrated_meds: list[dict] = []
    migrated_contacts: list[dict] = []
    with get_db() as conn:
        med_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM medication_reminders WHERE user_id=?",
            (user_id,),
        ).fetchone()["cnt"]
        con_cnt = conn.execute(
            "SELECT COUNT(*) as cnt FROM emergency_contacts WHERE user_id=?",
            (user_id,),
        ).fetchone()["cnt"]
        today = date.today().strftime("%Y-%m-%d")

        if med_cnt == 0:
            legacy_meds = elder.get("medication_reminders") or []
            for m in legacy_meds:
                if not isinstance(m, dict):
                    continue
                times_list, _ = _parse_times(m.get("times") or [])
                drug = (m.get("name") or "").strip()
                dosage = (m.get("dosage") or "1片").strip()
                if not drug or not times_list:
                    continue
                conn.execute(
                    "INSERT INTO medication_reminders (user_id, patient_name, drug_name, "
                    "dosage, times_json, repeat_rule, start_date, status, setter_id) "
                    "VALUES (?,?,?,?,?,'每天',?,'审核通过',?)",
                    (user_id, patient_name, drug, dosage,
                     json.dumps(times_list, ensure_ascii=False), today, user_id),
                )
                result["meds"] += 1
                migrated_meds.append({"title": f"{patient_name} - {drug}",
                                      "detail": f"时间：{'、'.join(times_list)}"})

        if con_cnt == 0:
            legacy_contacts = elder.get("emergency_contact") or []
            for c in legacy_contacts:
                if not isinstance(c, dict):
                    continue
                name = (c.get("name") or "").strip()
                phone = (c.get("phone") or "").strip()
                relation = (c.get("relation") or "家属").strip()
                if not name or not _validate_phone(phone):
                    continue
                conn.execute(
                    "INSERT INTO emergency_contacts (user_id, name, phone, relation, "
                    "setter_id, status) VALUES (?,?,?,?,?,'审核通过')",
                    (user_id, name, phone, relation, user_id),
                )
                result["contacts"] += 1
                migrated_contacts.append({"title": f"{relation} - {name}",
                                          "detail": f"电话：{phone[:3]}****{phone[-4:]}"})
        conn.commit()

    # 留痕在事务提交后单独记录，避免连接互锁
    for item in migrated_meds:
        log_activity(actor, "迁移旧用药提醒到新表", "medication_reminder",
                     module=MODULE, target_title=item["title"], after_value="审核通过",
                     detail=item["detail"] + "（旧 JSON 数据迁移，免审核）")
    for item in migrated_contacts:
        log_activity(actor, "迁移旧紧急联系人到新表", "emergency_contact",
                     module=MODULE, target_title=item["title"], after_value="审核通过",
                     detail=item["detail"] + "（旧 JSON 数据迁移，免审核）")

    if result["meds"] or result["contacts"]:
        log_activity(actor, "迁移老年端旧数据", "elderly", user_id, module=MODULE,
                     after_value=str(result), detail="旧 JSON 存储迁移到新表（免审核）")
    return result
