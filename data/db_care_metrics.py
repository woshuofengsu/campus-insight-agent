# data/db_care_metrics.py
"""关怀量化（U4）：把「人情味」变成可统计的数字。

指标口径（近 days 天）：
  - 情绪识别：`care_event_log` 中含 emotion_tag 的事件数 + 标签分布
  - 关怀触达：有安抚句或场景共情句的事件数（触达率 = 触达 / 有情绪）
  - 情绪 → 转人工率：情绪事件中 status 落到 transferred_to_human/needs_human 的占比
  - 情绪 → 闭环率：情绪事件中 status == 成功 的占比
  - 场景分布：repair_ok / sos / fail
数据来源：`care_event_log`（v44），由 orchestrator._finish 在拼装关怀句时写入。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)


def log_care_event(user_id: int | None, role: str = "resident", emotion_tag: str = "",
                   comfort_used: bool = False, scene: str = "",
                   scene_line_used: bool = False, intent: str = "",
                   status: str = "") -> None:
    """记录一次关怀动作（U4）。失败只记日志，绝不影响业务主流程。"""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO care_event_log (user_id, role, emotion_tag, comfort_used, "
                "scene, scene_line_used, intent, status) VALUES (?,?,?,?,?,?,?,?)",
                (user_id, role, emotion_tag or "", 1 if comfort_used else 0,
                 scene or "", 1 if scene_line_used else 0,
                 (intent or "")[:50], (status or "")[:50]),
            )
            # 多租户（B6 补漏）：关怀事件要盖租户章——否则网格端关怀量化/事件列表
            # （已按 tenant 过滤）看不到这些记录，指标会恒为 0（"做了但页面上没有"）。
            from utils.tenant import stamp_tenant
            stamp_tenant(conn, "care_event_log", cur.lastrowid, user_id)
            conn.commit()
    except Exception:
        _log.debug("记录关怀事件失败（已忽略）", exc_info=True)


def get_care_metrics(days: int = 7) -> dict:
    """关怀量化指标（近 days 天）。任何异常返回零值结构，不影响页面。"""
    out = {
        "days": days, "care_events": 0, "emotion_events": 0,
        "touch_events": 0, "touch_rate": 0.0, "scene_line_events": 0,
        "emotion_to_human": 0, "emotion_to_human_rate": 0.0,
        "emotion_closed": 0, "emotion_closed_rate": 0.0,
        "by_emotion": {}, "by_scene": {},
    }
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c, "
                "SUM(CASE WHEN emotion_tag != '' THEN 1 ELSE 0 END) emo, "
                # 触达数只在「识别到情绪」的事件里统计 → 触达率恒 ≤100%（分母=情绪事件数）
                "SUM(CASE WHEN emotion_tag != '' AND (comfort_used=1 OR scene_line_used=1) "
                "    THEN 1 ELSE 0 END) touch, "
                "SUM(CASE WHEN scene_line_used=1 THEN 1 ELSE 0 END) scene_line, "
                "SUM(CASE WHEN emotion_tag != '' AND status IN "
                "    ('transferred_to_human','needs_human') THEN 1 ELSE 0 END) to_human, "
                "SUM(CASE WHEN emotion_tag != '' AND status='成功' THEN 1 ELSE 0 END) closed "
                "FROM care_event_log WHERE created_at >= datetime('now', ?)",
                (f"-{days} days",)).fetchone()
            out["care_events"] = row["c"] or 0
            out["emotion_events"] = row["emo"] or 0
            out["touch_events"] = row["touch"] or 0
            out["scene_line_events"] = row["scene_line"] or 0
            out["emotion_to_human"] = row["to_human"] or 0
            out["emotion_closed"] = row["closed"] or 0
            if out["emotion_events"]:
                out["touch_rate"] = round(out["touch_events"] * 100.0 / out["emotion_events"], 1)
                out["emotion_to_human_rate"] = round(
                    out["emotion_to_human"] * 100.0 / out["emotion_events"], 1)
                out["emotion_closed_rate"] = round(
                    out["emotion_closed"] * 100.0 / out["emotion_events"], 1)
            for r in conn.execute(
                "SELECT emotion_tag, COUNT(*) c FROM care_event_log "
                "WHERE emotion_tag != '' AND created_at >= datetime('now', ?) "
                "GROUP BY emotion_tag ORDER BY c DESC", (f"-{days} days",)):
                out["by_emotion"][r["emotion_tag"]] = r["c"]
            for r in conn.execute(
                "SELECT scene, COUNT(*) c FROM care_event_log "
                "WHERE scene != '' AND created_at >= datetime('now', ?) "
                "GROUP BY scene ORDER BY c DESC", (f"-{days} days",)):
                out["by_scene"][r["scene"]] = r["c"]
    except Exception:
        _log.warning("get_care_metrics 统计失败", exc_info=True)
    return out


def clean_care_event_log(days: int = 180) -> int:
    """清理超期关怀事件（调度器调用）。"""
    try:
        with get_db() as conn:
            cur = conn.execute(
                f"DELETE FROM care_event_log WHERE created_at < datetime('now', '-{days} days')")
            conn.commit()
            return cur.rowcount
    except Exception:
        _log.warning("清理关怀事件失败", exc_info=True)
        return 0
