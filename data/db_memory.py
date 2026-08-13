# data/db_memory.py
"""跨会话事件记忆 — 记录用户关键动作，供系统提示词注入个性化上下文。

与 working memory（会话内）和 user_profile（画像）互补：event_memory 记录
「用户做过什么」（上报/评价/附议…），让 Agent 在下次对话时能引用「你最近…」。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)


def remember_event(user_id: int, event_type: str, summary: str) -> None:
    """Record a cross-session event for a user. Best-effort, never blocks."""
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
        _log.warning("remember_event failed", exc_info=True)


def get_recent_events(user_id: int, limit: int = 10) -> list[dict]:
    """Return a user's recent events, newest first."""
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
        _log.warning("get_recent_events failed", exc_info=True)
        return []


def get_event_summary(user_id: int, limit: int = 5) -> str:
    """Return a compact Chinese summary of recent events for prompt injection."""
    events = get_recent_events(user_id, limit)
    if not events:
        return ""
    parts = [f"{e['summary']}" for e in events]
    return "；".join(parts)
