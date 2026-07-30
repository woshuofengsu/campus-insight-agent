# data/db_academic.py
"""Academic-related tables — courses, exams, events, club activities."""
import json
from data.db_core import get_db


# ── Courses ──

def get_courses(day_of_week: int | None = None, semester: str | None = None) -> list[dict]:
    with get_db() as conn:
        query = "SELECT * FROM courses WHERE 1=1"
        params = []
        if day_of_week is not None:
            query += " AND day_of_week = ?"
            params.append(day_of_week)
        if semester:
            query += " AND semester = ?"
            params.append(semester)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]


def get_today_courses(day_of_week: int, semester: str) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM courses WHERE day_of_week = ? AND semester = ? ORDER BY start_time",
            (day_of_week, semester),
        ).fetchall()
        return [dict(r) for r in rows]


def add_course(name: str, day_of_week: int, start_time: str, end_time: str,
               location: str = "", week_range: str = "", semester: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO courses (name, day_of_week, start_time, end_time, location, week_range, semester) VALUES (?,?,?,?,?,?,?)",
            (name, day_of_week, start_time, end_time, location, week_range, semester),
        )
        conn.commit()
        return cur.lastrowid


def delete_course(course_id: int) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
        conn.commit()


# ── Exams ──

def get_exams() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM exams ORDER BY exam_date ASC").fetchall()
        return [dict(r) for r in rows]


def add_exam(course_name: str, exam_date: str, exam_time: str = "",
             location: str = "", notes: str = "") -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO exams (course_name, exam_date, exam_time, location, notes) VALUES (?,?,?,?,?)",
            (course_name, exam_date, exam_time, location, notes),
        )
        conn.commit()
        return cur.lastrowid


def get_upcoming_exams(days: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM exams WHERE exam_date <= date('now', '+' || ? || ' days') AND exam_date >= date('now') ORDER BY exam_date ASC",
            (days,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Events ──

def get_events(date: str | None = None) -> list[dict]:
    with get_db() as conn:
        if date:
            rows = conn.execute(
                "SELECT * FROM events WHERE event_date = ? ORDER BY start_time", (date,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY event_date ASC, start_time ASC"
            ).fetchall()
        return [dict(r) for r in rows]


def create_event(title: str, event_date: str, start_time: str = "", end_time: str = "",
                 location: str = "", reminder: bool = False, reminder_time: str = "",
                 created_by_agent: bool = False) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO events (title, event_date, start_time, end_time, location, reminder, reminder_time, created_by_agent) VALUES (?,?,?,?,?,?,?,?)",
            (title, event_date, start_time, end_time, location, int(reminder), reminder_time, int(created_by_agent)),
        )
        conn.commit()
        return cur.lastrowid


def get_overdue_reminders(now: str) -> list[dict]:
    """Get reminders whose time has passed but haven't been acknowledged."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE reminder = 1 AND reminder_time != '' AND reminder_time <= ? ORDER BY reminder_time DESC",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]


def check_conflict(event_date: str, start_time: str, end_time: str,
                   exclude_id: int | None = None) -> bool:
    """Check if a time slot conflicts with existing events."""
    with get_db() as conn:
        query = """
            SELECT COUNT(*) as cnt FROM events
            WHERE event_date = ?
            AND start_time < ? AND end_time > ?
        """
        params = [event_date, end_time, start_time]
        if exclude_id is not None:
            query += " AND id != ?"
            params.append(exclude_id)
        row = conn.execute(query, params).fetchone()
        return row["cnt"] > 0


# ── Club Activities ──

def get_club_activities(days_ahead: int = 14) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM club_activities WHERE activity_date BETWEEN date('now') AND date('now', '+' || ? || ' days') ORDER BY activity_date ASC, start_time ASC",
            (days_ahead,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_activities_by_tags(tags: list[str]) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM club_activities ORDER BY activity_date ASC").fetchall()
    results = []
    for r in rows:
        d = dict(r)
        try:
            activity_tags = json.loads(d.get("tags", "[]"))
        except (json.JSONDecodeError, TypeError):
            activity_tags = []
        if any(t in activity_tags for t in tags):
            results.append(d)
    return results
