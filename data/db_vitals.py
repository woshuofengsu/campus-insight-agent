# data/db_vitals.py
"""老年健康记录（血压 / 血糖）数据层 —— 录入、查询、趋势。

为什么单独一张表而不是塞进 `elderly_profile.health_info` JSON：
那个 JSON 是**整块覆盖写**（`data/db_elderly.set_health_info`），并发录入会互相覆盖丢记录，
也无法按时间分页/排序。健康记录是"只增不改"的流水，天然适合独立表。

口径：分级与文案一律走 `data/_vitals_logic.py`（提醒级，不做诊断）。
"""
import logging

from data._vitals_logic import LEVELS, classify, hint_of, to_number, trend_label
from data.db_core import get_db

_log = logging.getLogger(__name__)

KINDS = ("bp", "glucose")
MEASURE_WHEN = ("fasting", "postprandial", "random")


def add_vital(user_id: int, kind: str, sys_: int | float | None = None,
              dia: int | float | None = None, glucose: float | None = None,
              measure_when: str = "random", measured_at: str = "",
              recorder_id: int | None = None, source: str = "self",
              note: str = "") -> tuple[int, str, dict]:
    """录入一条健康记录。返回 `(id, level, {hint, ...})`；`id=0` 表示校验失败。

    校验从紧（这是健康数据）：kind 必须合法；血压必须给收缩压或舒张压之一；
    血糖必须给值；数值范围做**荒谬值拦截**（不是医学判断，是防手滑）。
    """
    uid = int(user_id or 0)
    if uid <= 0:
        return 0, "", {"error": "缺少用户"}
    if kind not in KINDS:
        return 0, "", {"error": "类型只支持血压(bp)或血糖(glucose)"}

    if kind == "bp":
        if str(sys_ or "").strip() == "" and str(dia or "").strip() == "":
            return 0, "", {"error": "请填写收缩压或舒张压"}
        s, d = to_number(sys_), to_number(dia)
        if (str(sys_ or "").strip() and s is None) or (str(dia or "").strip() and d is None):
            return 0, "", {"error": "血压请填数字"}
        if (s is not None and not 40 <= s <= 300) or (d is not None and not 20 <= d <= 200):
            return 0, "", {"error": "血压数值看起来不对，请核对后重填"}
    else:
        if str(glucose or "").strip() == "":
            return 0, "", {"error": "请填写血糖值"}
        g = to_number(glucose)
        if g is None:
            return 0, "", {"error": "血糖请填数字"}
        if not 1.0 <= g <= 40.0:
            return 0, "", {"error": "血糖数值看起来不对，请核对后重填"}

    if measure_when not in MEASURE_WHEN:
        measure_when = "random"

    level, hint = classify(kind, sys_, dia, glucose, measure_when)
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO elderly_vitals (user_id, kind, sys, dia, glucose, measure_when, "
            "measured_at, recorder_id, source, note) "
            "VALUES (?, ?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP), ?, ?, ?)",
            (uid, kind, sys_ if sys_ not in (None, "") else None,
             dia if dia not in (None, "") else None,
             glucose if glucose not in (None, "") else None,
             measure_when, measured_at, recorder_id or uid, source, (note or "")[:200]),
        )
        vid = cur.lastrowid
        conn.commit()
    return vid, level, {"hint": hint, "kind": kind}


def list_vitals(user_id: int, kind: str = "", limit: int = 20) -> list[dict]:
    """按时间倒序列出记录（默认全部类型）。"""
    q = "SELECT * FROM elderly_vitals WHERE user_id=?"
    args: list = [int(user_id or 0)]
    if kind in KINDS:
        q += " AND kind=?"
        args.append(kind)
    q += " ORDER BY measured_at DESC, id DESC LIMIT ?"
    args.append(max(1, min(int(limit or 20), 200)))
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
    return [_decorate(dict(r)) for r in rows]


def latest_vital(user_id: int, kind: str) -> dict | None:
    rows = list_vitals(user_id, kind, limit=1)
    return rows[0] if rows else None


def vitals_summary(user_id: int, limit: int = 7) -> dict:
    """给老年端首页/网格员端用的一页摘要：最新血压、最新血糖、各自趋势与一句话。"""
    bp = list_vitals(user_id, "bp", limit=limit)
    glu = list_vitals(user_id, "glucose", limit=limit)
    return {
        "latest_bp": bp[0] if bp else None,
        "latest_glucose": glu[0] if glu else None,
        "bp_trend": [{"measured_at": r["measured_at"], "sys": r["sys"], "dia": r["dia"]} for r in bp],
        "glucose_trend": [{"measured_at": r["measured_at"], "glucose": r["glucose"]} for r in glu],
        "bp_trend_label": trend_label([r["sys"] for r in bp if r.get("sys") is not None]),
        "glucose_trend_label": trend_label([r["glucose"] for r in glu if r.get("glucose") is not None]),
    }


def _decorate(row: dict) -> dict:
    """补上分级与固定文案（前端只负责显示，不自己判级）。"""
    level, hint = classify(row.get("kind", ""), row.get("sys"), row.get("dia"),
                           row.get("glucose"), row.get("measure_when") or "")
    row["level"] = level
    row["level_hint"] = hint
    row["uphold"] = level in LEVELS[1:]
    return row


def backfill_from_profile(conn=None) -> int:
    """把 `elderly_profile.health_info.blood_pressure` 的历史条目搬进新表（幂等）。

    v47 迁移里调用一次；单独跑也安全（同一条记录不会重复插入）。
    """
    import json
    own = conn is None
    ctx = get_db() if own else None
    c = ctx.__enter__() if own else conn
    moved = 0
    try:
        rows = c.execute("SELECT user_id, health_info FROM elderly_profile").fetchall()
        for r in rows:
            try:
                info = json.loads(r["health_info"] or "{}")
            except Exception:  # noqa: BLE001
                continue
            for item in (info.get("blood_pressure") or []):
                if not isinstance(item, dict):
                    continue
                date = str(item.get("date") or "").strip()
                s, d = item.get("sys"), item.get("dia")
                if s in (None, "") and d in (None, ""):
                    continue
                dup = c.execute(
                    "SELECT 1 FROM elderly_vitals WHERE user_id=? AND kind='bp' "
                    "AND IFNULL(sys,-1)=IFNULL(?,-1) AND IFNULL(dia,-1)=IFNULL(?,-1) "
                    "AND substr(measured_at,1,10)=?", (r["user_id"], s, d, date or "0000-00-00"),
                ).fetchone()
                if dup:
                    continue
                c.execute(
                    "INSERT INTO elderly_vitals (user_id, kind, sys, dia, measure_when, "
                    "measured_at, recorder_id, source, note) "
                    "VALUES (?, 'bp', ?, ?, 'random', ?, ?, 'backfill', '迁移自 health_info')",
                    (r["user_id"], s, d, (date + " 08:00:00") if date else None,
                     r["user_id"]),
                )
                moved += 1
        if own:
            c.commit()
    finally:
        if own and ctx is not None:
            ctx.__exit__(None, None, None)
    if moved:
        _log.info("健康记录回填：从 health_info 搬入 %d 条血压", moved)
    return moved


def notify_abnormal_vital(user_id: int, kind: str, level: str, hint: str,
                          value_text: str = "") -> int:
    """数值明显偏离时提醒网格员与家属（P4 的"异常提醒"）。

    三条口径：
    1. **只提醒、不下结论**：正文用 `_vitals_logic` 的固定文案，绝不写医学结论；
    2. **只对 alert 级提醒**（attention 级在页面里显示颜色即可，避免天天弹）；
    3. **每人每天每种指标最多一条**：按 **UTC 日期**去重（库内时间列都是 UTC，
       与 2026-09-24 修的时区 bug 同口径——这里两边都用 UTC，不会再错配）。
    """
    if level != "alert":
        return 0
    uid = int(user_id or 0)
    if uid <= 0:
        return 0
    from utils.timeutil import utcnow
    today_utc = utcnow().strftime("%Y-%m-%d")
    try:
        from data.db_notifications import create_notification
        from data.db_user import list_guardians_of, list_users
        from data.db_core import get_db as _gdb

        with _gdb() as conn:
            elder = conn.execute("SELECT name FROM user_profile WHERE id=?", (uid,)).fetchone()
            dup = conn.execute(
                "SELECT 1 FROM notifications WHERE type='elderly_health' AND related_id=? "
                "AND substr(created_at,1,10)=? AND content LIKE ? LIMIT 1",
                (uid, today_utc, f"%{kind}%")).fetchone()
        if dup:
            return 0
        name = (elder["name"] if elder else "") or "老人"
        label = "血压" if kind == "bp" else "血糖"
        title = f"🩺 健康提醒：{name}的{label}"
        body = f"最近一次{label}记录：{value_text}。{hint}" if value_text else hint

        sent = 0
        for g in list_users(role="grid"):
            create_notification(g["id"], "elderly_health", title, body, related_id=uid)
            sent += 1
        for guardian in list_guardians_of(uid):
            create_notification(guardian["id"], "elderly_health", title,
                                f"{body}（社区网格员也收到了这条提醒）", related_id=uid)
            sent += 1
        return sent
    except Exception:  # noqa: BLE001
        _log.warning("健康异常提醒发送失败 uid=%s kind=%s", uid, kind, exc_info=True)
        return 0


__all__ = ["KINDS", "MEASURE_WHEN", "add_vital", "list_vitals", "latest_vital",
           "vitals_summary", "backfill_from_profile", "notify_abnormal_vital", "hint_of"]
