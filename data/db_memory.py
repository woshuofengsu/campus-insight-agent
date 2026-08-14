"""跨会话事件记忆 — 记录用户关键动作，供系统提示词注入个性化上下文。

与 working memory（会话内）和 user_profile（画像）互补：event_memory 记录
「用户做过什么」（上报/评价/附议…），让 Agent 在下次对话时能引用「你最近…」。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)


def remember_event(user_id: int, event_type: str, summary: str) -> None:
    """记一条跨会话事件。尽力而为，写失败也不影响主流程。"""
    if not user_id:
        return
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT INTO event_memory (user_id, event_type, summary) VALUES (?,?,?)",
                (user_id, event_type, summary),
            )
            conn.commit()
    except Exception:
        _log.warning("remember_event 写入失败", exc_info=True)


def get_recent_events(user_id: int, limit: int = 10) -> list[dict]:
    """查用户最近的事件，新的在前。"""
    if not user_id:
        return []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT event_type, summary, created_at FROM event_memory "
                "WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        _log.warning("get_recent_events 查询失败", exc_info=True)
        return []


def get_event_summary(user_id: int, limit: int = 5) -> str:
    """把最近事件拼成一段简短中文，给系统提示词注入用。"""
    events = get_recent_events(user_id, limit)
    if not events:
        return ""
    parts = [f"{e['summary']}" for e in events]
    return "；".join(parts)
