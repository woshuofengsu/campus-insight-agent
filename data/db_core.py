# data/db_core.py
"""Database core — connection management and shared helpers."""
import hashlib
import hmac as _hmac
import os
import sqlite3
from contextlib import contextmanager

_DB_PATH: str = ""


_PBKDF2_ITERATIONS = 100_000


def _hash_password(password: str) -> str:
    """Hash password with PBKDF2-SHA256 + random 16-byte salt.

    Format:  pbkdf2:sha256:100000$<salt_hex>$<hash_hex>

    The salt is random per-password — no static secret in source code.
    """
    if not password:
        return ""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2:sha256:{_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """Verify a password against the stored hash.

    Handles migration: old SHA-256 hashes (no '$' separator) are verified
    against the legacy static-salt scheme and should be re-hashed on next write.
    """
    if not stored:
        return not password

    # Legacy format: plain SHA-256 hex (no '$')
    if "$" not in stored:
        old = hashlib.sha256(f"campus-insight-salt-2026:{password}".encode()).hexdigest()
        return _hmac.compare_digest(old, stored) if old and stored else old == stored

    # New format: pbkdf2:sha256:<iter>$<salt_hex>$<hash_hex>
    try:
        _, salt_hex, hash_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return _hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def init_db(db_path: str):
    """Initialize the database — create tables if they don't exist."""
    global _DB_PATH
    _DB_PATH = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL DEFAULT '',
            password_hash TEXT DEFAULT '',
            role TEXT DEFAULT 'student',
            school TEXT DEFAULT '',
            grade TEXT DEFAULT '',
            major TEXT DEFAULT '',
            name TEXT DEFAULT '',
            student_id TEXT DEFAULT '',
            preferences TEXT DEFAULT '[]',
            onboarding_done INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS courses (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            day_of_week INTEGER,
            start_time TEXT,
            end_time TEXT,
            location TEXT DEFAULT '',
            week_range TEXT DEFAULT '',
            semester TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS exams (
            id INTEGER PRIMARY KEY,
            course_name TEXT NOT NULL,
            exam_date TEXT NOT NULL,
            exam_time TEXT DEFAULT '',
            location TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            event_date TEXT NOT NULL,
            start_time TEXT DEFAULT '',
            end_time TEXT DEFAULT '',
            location TEXT DEFAULT '',
            reminder INTEGER DEFAULT 0,
            reminder_time TEXT DEFAULT '',
            created_by_agent INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS club_activities (
            id INTEGER PRIMARY KEY,
            club_name TEXT NOT NULL,
            title TEXT NOT NULL,
            activity_date TEXT NOT NULL,
            start_time TEXT DEFAULT '',
            location TEXT DEFAULT '',
            description TEXT DEFAULT '',
            tags TEXT DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY,
            category TEXT DEFAULT '',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            keywords TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS campus_issues (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT '其他',
            location TEXT DEFAULT '',
            description TEXT DEFAULT '',
            urgency TEXT DEFAULT '普通',
            status TEXT DEFAULT '待处理',
            reported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS feedback_items (
            id INTEGER PRIMARY KEY,
            topic TEXT NOT NULL,
            opinion TEXT NOT NULL,
            source TEXT DEFAULT '用户反馈',
            sentiment TEXT DEFAULT '中性',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT DEFAULT '其他',
            supporter_count INTEGER DEFAULT 1,
            status TEXT DEFAULT '讨论中',
            response_text TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS discussion_topics (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            category TEXT DEFAULT '',
            created_by_agent INTEGER DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            participant_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS topic_opinions (
            id INTEGER PRIMARY KEY,
            topic_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            participant_label TEXT DEFAULT '匿名学生',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (topic_id) REFERENCES discussion_topics(id)
        );

        CREATE TABLE IF NOT EXISTS health_surveillance (
            id INTEGER PRIMARY KEY,
            disease TEXT NOT NULL,
            report_year INTEGER NOT NULL,
            report_month INTEGER NOT NULL,
            national_cases INTEGER NOT NULL DEFAULT 0,
            national_deaths INTEGER DEFAULT 0,
            region TEXT DEFAULT '全国',
            source TEXT DEFAULT '国家疾控局',
            data_level TEXT DEFAULT 'national',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(disease, report_year, report_month, region)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL DEFAULT 'system',
            title TEXT NOT NULL,
            content TEXT DEFAULT '',
            related_id INTEGER,
            is_read INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES user_profile(id)
        );

        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL DEFAULT '',
            action TEXT NOT NULL,
            target_type TEXT NOT NULL DEFAULT '',
            target_id INTEGER,
            target_title TEXT DEFAULT '',
            detail TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS perception_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            trigger TEXT DEFAULT 'auto',
            overall_summary TEXT DEFAULT '',
            trend_direction TEXT DEFAULT 'stable',
            anomaly_count INTEGER DEFAULT 0,
            key_findings TEXT DEFAULT '[]',
            details_json TEXT DEFAULT '{}',
            issues_total INTEGER DEFAULT 0,
            issues_pending INTEGER DEFAULT 0,
            issues_new_today INTEGER DEFAULT 0
        );
    """)
    # Migrations: add columns that may not exist in older DBs
    for table, col_def in [
        ("campus_issues", "author TEXT DEFAULT ''"),
        ("proposals", "author TEXT DEFAULT ''"),
        ("user_profile", "student_id TEXT DEFAULT ''"),
        ("user_profile", "role TEXT DEFAULT 'student'"),
        ("user_profile", "name TEXT DEFAULT ''"),
        ("user_profile", "username TEXT UNIQUE NOT NULL DEFAULT ''"),
        ("user_profile", "password_hash TEXT DEFAULT ''"),
        ("user_profile", "is_active INTEGER DEFAULT 1"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass  # column already exists — expected

    # ── Migrate legacy single-user DB (id=1, no username) ──
    legacy = conn.execute(
        "SELECT id, username, name, student_id, role FROM user_profile WHERE id = 1"
    ).fetchone()
    if legacy and (not legacy["username"] or legacy["username"] == ""):
        fallback_username = (
            legacy["student_id"]
            or legacy["name"]
            or f"user_{legacy['role'] or 'student'}"
        )
        existing = conn.execute(
            "SELECT id FROM user_profile WHERE username = ? AND id != 1",
            (fallback_username,),
        ).fetchone()
        if existing:
            fallback_username = f"{fallback_username}_1"
        conn.execute(
            "UPDATE user_profile SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (fallback_username,),
        )

    conn.commit()
    conn.close()


def get_connection() -> sqlite3.Connection:
    """Get a raw SQLite connection. Prefer `with get_db() as conn:` for safety."""
    if not _DB_PATH:
        raise RuntimeError(
            "Database not initialized. Call init_db(db_path) before any database operations."
        )
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_db():
    """Context manager for safe database connections — auto-closes on exit.

    Usage:
        with get_db() as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


def resolve_author(author: str = "", user_name: str = "", user_sid: str = "",
                   user_school: str = "", user_grade: str = "") -> str:
    """Resolve author identity — auto-fill from user profile fields if empty.

    Prefer passing user fields explicitly to avoid circular imports from db_user.
    """
    if author:
        return author
    if user_sid:
        return user_sid
    if user_school:
        return f"{user_school}{user_grade}" if user_grade else user_school
    if user_name:
        return user_name
    return "匿名"
