# data/db_elderly.py
"""老年关怀档案 — 健康信息、用药提醒、紧急联系人、平安打卡、SOS 求助。

面向 `elderly` 角色（独居/高龄老人的无障碍视图）。健康与联系方式按 JSON 字段
存储；安全闭环（平安打卡 / SOS）由感知引擎与网格员工作台消费。
"""
import json
import logging
from datetime import datetime

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 平安打卡默认阈值（小时）；超时未互动视为「需要留意」（提醒级，非警报）
INACTIVE_HOURS = 24


def _ensure_profile(conn, user_id: int) -> None:
    conn.execute("INSERT OR IGNORE INTO elderly_profile (user_id) VALUES (?)", (user_id,))


def get_profile(user_id: int) -> dict:
    """Return a user's elderly profile (JSON fields parsed). Empty dict if none."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM elderly_profile WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return {}
    d = dict(row)
    for key in ("health_info", "medication_reminders", "emergency_contact"):
        try:
            d[key] = json.loads(d.get(key) or ("{}" if key == "health_info" else "[]"))
        except (json.JSONDecodeError, TypeError):
            d[key] = {} if key == "health_info" else []
    return d


def set_health_info(user_id: int, health_info: dict) -> None:
    with get_db() as conn:
        _ensure_profile(conn, user_id)
        conn.execute(
            "UPDATE elderly_profile SET health_info = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (json.dumps(health_info, ensure_ascii=False), user_id),
        )
        conn.commit()


def set_medication_reminders(user_id: int, reminders: list) -> None:
    with get_db() as conn:
        _ensure_profile(conn, user_id)
        conn.execute(
            "UPDATE elderly_profile SET medication_reminders = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (json.dumps(reminders, ensure_ascii=False), user_id),
        )
        conn.commit()


def set_emergency_contact(user_id: int, contacts: list) -> None:
    with get_db() as conn:
        _ensure_profile(conn, user_id)
        conn.execute(
            "UPDATE elderly_profile SET emergency_contact = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (json.dumps(contacts, ensure_ascii=False), user_id),
        )
        conn.commit()


def set_living_alone(user_id: int, is_alone: bool) -> None:
    with get_db() as conn:
        _ensure_profile(conn, user_id)
        conn.execute(
            "UPDATE elderly_profile SET is_living_alone = ? WHERE user_id = ?",
            (1 if is_alone else 0, user_id),
        )
        conn.commit()


# ── 平安打卡 ──

def touch_active(user_id: int) -> None:
    """Mark the elderly user as active right now (any interaction counts)."""
    with get_db() as conn:
        _ensure_profile(conn, user_id)
        conn.execute(
            "UPDATE elderly_profile SET last_active_at = CURRENT_TIMESTAMP WHERE user_id = ?",
            (user_id,),
        )
        conn.commit()


def get_inactive_elders(hours: int = INACTIVE_HOURS) -> list[dict]:
    """Return elderly users inactive beyond `hours` (for the safety check)."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT e.user_id, u.name, e.last_active_at, e.is_living_alone, e.emergency_contact "
            "FROM elderly_profile e JOIN user_profile u ON u.id = e.user_id "
            "WHERE u.is_active = 1 AND (e.last_active_at IS NULL "
            "  OR julianday('now') - julianday(e.last_active_at) > ?/24.0)",
            (hours,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["emergency_contact"] = json.loads(d.get("emergency_contact") or "[]")
        except Exception:
            d["emergency_contact"] = []
        result.append(d)
    return result


def notify_inactive_elders(hours: int = INACTIVE_HOURS) -> int:
    """Notify grid workers about elderly users inactive beyond `hours`.

    24h 去重（同一天内不重复通知同一老人）。返回本次通知的老人数。
    """
    inactive = get_inactive_elders(hours)
    if not inactive:
        return 0
    try:
        from data.db_notifications import create_notification
        from data.db_user import list_users
        grids = list_users(role="grid")
        if not grids:
            return 0
        notified = 0
        for elder in inactive:
            uid = elder.get("user_id")
            with get_db() as conn:
                dup = conn.execute(
                    "SELECT COUNT(*) as cnt FROM notifications "
                    "WHERE type = 'elderly_safety' AND related_id = ? "
                    "AND created_at > datetime('now', '-1 day')",
                    (uid,),
                ).fetchone()
            if dup and dup["cnt"] > 0:
                continue
            for g in grids:
                create_notification(
                    g["id"], "elderly_safety",
                    f"👴 老人安全留意：{elder.get('name', '')}",
                    f"已 {hours} 小时未互动，请电话或上门确认。",
                    related_id=uid,
                )
            notified += 1
        return notified
    except Exception:
        _log.warning("notify_inactive_elders failed", exc_info=True)
        return 0


# ── SOS 求助 ──

def sos_request(user_id: int) -> int:
    """Create a new SOS request. Returns the sos_log id."""
    with get_db() as conn:
        cur = conn.execute("INSERT INTO sos_log (user_id) VALUES (?)", (user_id,))
        conn.commit()
        return cur.lastrowid


def get_pending_sos() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT s.id, s.user_id, u.name, s.created_at FROM sos_log s "
            "JOIN user_profile u ON u.id = s.user_id "
            "WHERE s.status = 'pending' ORDER BY s.created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_sos_done(sos_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE sos_log SET status = 'done', handled_at = CURRENT_TIMESTAMP WHERE id = ?",
            (sos_id,),
        )
        conn.commit()


def cancel_sos(sos_id: int) -> None:
    with get_db() as conn:
        conn.execute("UPDATE sos_log SET status = 'cancelled' WHERE id = ?", (sos_id,))
        conn.commit()


def notify_sos_targeted(user_name: str, sos_id: int) -> int | None:
    """SOS 定向通知（不广播）：优先网格办/居委会网格员，fallback 任一网格员。

    避免多网格员场景下 SOS 广播轰炸所有网格员。返回被通知的网格员 id。
    """
    try:
        from data.db_user import list_users
        from data.db_notifications import create_notification
        grids = list_users(role="grid")
        if not grids:
            return None
        target = None
        for dept in ("网格办", "居委会", "网格一组"):
            for g in grids:
                if (g.get("building") or "").strip() == dept:
                    target = g
                    break
            if target:
                break
        if not target:
            target = grids[0]
        create_notification(
            target["id"], "sos",
            f"⚠️ SOS 紧急求助：{user_name}",
            "老年关怀版用户发出紧急求助，请立即联系/上门查看。",
            related_id=sos_id,
        )
        return target["id"]
    except Exception:
        _log.warning("notify_sos_targeted failed", exc_info=True)
        return None


# ── 用药提醒 ──

def due_reminders(user_id: int, now: datetime | None = None) -> list[dict]:
    """Return medication reminders due within ±30 min of now."""
    now = now or datetime.now()
    profile = get_profile(user_id)
    reminders = profile.get("medication_reminders", [])
    due: list[dict] = []
    for r in reminders:
        for t in r.get("times", []):
            try:
                hh, mm = map(int, str(t).split(":"))
                target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
                if abs((now - target).total_seconds()) <= 30 * 60:
                    due.append({"name": r.get("name", ""), "dosage": r.get("dosage", ""), "time": t})
            except (ValueError, AttributeError):
                continue
    return due


# ── 关怀提醒 ──

def get_care_reminders(user_id: int) -> list[dict]:
    """Aggregate care reminders: weather + health risk + meal point + anti-fraud."""
    items: list[dict] = []

    # 恶劣天气出行提醒（雨雪/大风/高温，防滑倒）
    try:
        from tools.query_weather import get_today_weather
        days, _, _ = get_today_weather()
        if days:
            today = days[0]
            if today.get("rain_prob", 0) >= 60 or today.get("condition", "") in (
                "暴雨", "雷阵雨", "大雪", "沙尘暴", "大风",
            ):
                items.append({"icon": "🌧️", "type": "weather",
                              "text": f"今天{today.get('condition', '')}，尽量别出门；买菜/取药可联系网格员"})
    except Exception:
        _log.debug("care reminder weather check skipped", exc_info=True)

    try:
        from data.db_health_alerts import HealthRiskEngine
        report = HealthRiskEngine().evaluate()
        if report.get("overall_level") in ("high", "critical"):
            items.append({"icon": "🏥", "type": "health",
                          "text": f"当前健康风险偏高（{report.get('overall_score', '')}分），注意保暖与防护"})
    except Exception:
        _log.debug("care reminder health check skipped", exc_info=True)

    items.append({"icon": "🍚", "type": "meal", "text": "助餐点：中心花园东侧 11:00-13:00（可送餐上门）"})
    items.append({"icon": "🛡️", "type": "safety",
                  "text": "谨防保健品/冒充公检法诈骗：不转账、不透露验证码、不点陌生链接"})
    return items


# ── 网格员关怀视图 ──

def get_medication_adherence(user_id: int, days: int = 7) -> list[dict]:
    """Return the user's medication-taken confirmations from the last `days` days."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT summary, created_at FROM event_memory "
            "WHERE user_id = ? AND event_type = 'medication_taken' "
            "AND created_at > datetime('now', ?) "
            "ORDER BY created_at DESC",
            (user_id, f'-{days} days'),
        ).fetchall()
        return [dict(r) for r in rows]


def get_elderly_overview() -> list[dict]:
    """Aggregate all elderly users for the grid care panel: blood pressure + adherence."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT e.user_id, u.name, e.is_living_alone, e.last_active_at, "
            "e.health_info, e.medication_reminders "
            "FROM elderly_profile e JOIN user_profile u ON u.id = e.user_id "
            "WHERE u.is_active = 1 ORDER BY e.is_living_alone DESC, e.last_active_at ASC"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["health_info"] = json.loads(d.get("health_info") or "{}")
        except Exception:
            d["health_info"] = {}
        bp = d["health_info"].get("blood_pressure", [])
        d["latest_bp"] = bp[-1] if bp else None
        d["bp_trend"] = bp[-7:]
        d["adherence"] = get_medication_adherence(d["user_id"], 7)
        result.append(d)
    return result
