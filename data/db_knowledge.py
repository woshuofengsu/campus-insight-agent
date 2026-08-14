"""知识库和反馈表。"""
from data.db_core import get_db


def search_knowledge(query: str, category: str | None = None) -> list[dict]:
    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM knowledge_base WHERE category = ? AND (title LIKE ? OR keywords LIKE ?) LIMIT 5",
                (category, f"%{query}%", f"%{query}%"),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_base WHERE title LIKE ? OR keywords LIKE ? OR content LIKE ? LIMIT 5",
                (f"%{query}%", f"%{query}%", f"%{query}%"),
            ).fetchall()
        return [dict(r) for r in rows]


def get_knowledge_base(category: str = "", limit: int = 20) -> list[dict]:
    """列知识库条目，可按分类过滤。"""
    with get_db() as conn:
        if category:
            rows = conn.execute(
                "SELECT * FROM knowledge_base WHERE category = ? ORDER BY id DESC LIMIT ?",
                (category, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM knowledge_base ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


def get_community_events(limit: int = 10) -> list[dict]:
    """从知识库拿社区活动，category 是 event/calendar/notice 的都算。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM knowledge_base WHERE category IN ('event', 'calendar', 'notice') ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_feedback_stats() -> dict:
    """整体情感统计 + 最近几条反馈。"""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) as cnt FROM feedback_items").fetchone()
        positive = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE sentiment = '正面'"
        ).fetchone()
        negative = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE sentiment = '负面'"
        ).fetchone()
        neutral = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE sentiment = '中性'"
        ).fetchone()
        top_topics = conn.execute(
            "SELECT topic, COUNT(*) as cnt FROM feedback_items GROUP BY topic ORDER BY cnt DESC LIMIT 5"
        ).fetchall()
        recent = conn.execute(
            "SELECT * FROM feedback_items ORDER BY created_at DESC LIMIT 8"
        ).fetchall()
        return {
            "total": total["cnt"] if total else 0,
            "positive": positive["cnt"] if positive else 0,
            "negative": negative["cnt"] if negative else 0,
            "neutral": neutral["cnt"] if neutral else 0,
            "top_topics": [dict(r) for r in top_topics],
            "recent": [dict(r) for r in recent],
        }


def add_feedback(topic: str, opinion: str, source: str = "用户反馈",
                 sentiment: str = "中性") -> int:
    """记一条反馈/意见，返回新记录的 ID。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO feedback_items (topic, opinion, source, sentiment) VALUES (?,?,?,?)",
            (topic, opinion, source, sentiment),
        )
        conn.commit()
        return cur.lastrowid


def get_feedback_by_topic(topic: str, limit: int = 20) -> list[dict]:
    """按主题查反馈。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM feedback_items WHERE topic LIKE ? ORDER BY created_at DESC LIMIT ?",
            (f"%{topic}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]


def aggregate_feedback(topic: str) -> dict:
    """汇总某个主题的情感分布。"""
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE topic LIKE ?",
            (f"%{topic}%",),
        ).fetchone()
        positive = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE topic LIKE ? AND sentiment = '正面'",
            (f"%{topic}%",),
        ).fetchone()
        negative = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE topic LIKE ? AND sentiment = '负面'",
            (f"%{topic}%",),
        ).fetchone()
        neutral = conn.execute(
            "SELECT COUNT(*) as cnt FROM feedback_items WHERE topic LIKE ? AND sentiment = '中性'",
            (f"%{topic}%",),
        ).fetchone()
        items = conn.execute(
            "SELECT * FROM feedback_items WHERE topic LIKE ? ORDER BY created_at DESC LIMIT 5",
            (f"%{topic}%",),
        ).fetchall()
        return {
            "topic": topic,
            "total": total["cnt"] if total else 0,
            "positive": positive["cnt"] if positive else 0,
            "negative": negative["cnt"] if negative else 0,
            "neutral": neutral["cnt"] if neutral else 0,
            "recent_items": [dict(r) for r in items],
        }
