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


# ── Schema versioning ──
_SCHEMA_CURRENT_VERSION = 10


def _create_schema_version_table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL DEFAULT 0)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, version INTEGER NOT NULL, "
        "name TEXT NOT NULL, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _get_schema_version(conn) -> int:
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (0)")
        return 0
    return row["version"]


def _set_schema_version(conn, version: int, name: str):
    conn.execute("UPDATE schema_version SET version = ?", (version,))
    conn.execute(
        "INSERT INTO schema_migrations (version, name) VALUES (?, ?)", (version, name)
    )


# ── Migration steps (ordered; each raises on real failure instead of silently passing) ──

def _m1_rename_issues_table(conn):
    """v1: legacy `campus_issues` → `community_issues` (idempotent)."""
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campus_issues'"
    ).fetchone()
    has_new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='community_issues'"
    ).fetchone()
    if has_old and not has_new:
        conn.execute("ALTER TABLE campus_issues RENAME TO community_issues")


def _m2_rename_profile_fields(conn):
    """v2: user_profile campus-era fields → community naming (idempotent)."""
    renames = [("student_id", "resident_id"), ("school", "community"),
               ("grade", "building"), ("major", "unit")]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(user_profile)")]
    for old, new in renames:
        if old in cols and new not in cols:
            conn.execute(f"ALTER TABLE user_profile RENAME COLUMN {old} TO {new}")


def _m3_add_missing_columns(conn):
    """v3: add columns that may not exist in older DBs (idempotent via PRAGMA)."""
    wanted = [
        ("community_issues", "author", "TEXT DEFAULT ''"),
        ("proposals", "author", "TEXT DEFAULT ''"),
        ("user_profile", "resident_id", "TEXT DEFAULT ''"),
        ("user_profile", "role", "TEXT DEFAULT 'resident'"),
        ("user_profile", "name", "TEXT DEFAULT ''"),
        ("user_profile", "username", "TEXT UNIQUE NOT NULL DEFAULT ''"),
        ("user_profile", "password_hash", "TEXT DEFAULT ''"),
        ("user_profile", "is_active", "INTEGER DEFAULT 1"),
        ("community_issues", "processing_note", "TEXT DEFAULT ''"),
        ("community_issues", "assignee", "TEXT DEFAULT ''"),
        ("community_issues", "suggested_category", "TEXT DEFAULT ''"),
        ("community_issues", "reporter_id", "INTEGER"),
        ("community_issues", "satisfaction", "TEXT DEFAULT ''"),
        ("community_issues", "satisfaction_reason", "TEXT DEFAULT ''"),
        ("proposals", "reporter_id", "INTEGER"),
    ]
    for table, col, decl in wanted:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _m4_migrate_role_values(conn):
    """v4: legacy role values student→resident, teacher→grid (+ demo usernames)."""
    conn.execute("UPDATE user_profile SET role='resident' WHERE role='student'")
    conn.execute("UPDATE user_profile SET role='grid' WHERE role='teacher'")
    conn.execute("UPDATE user_profile SET username='demo_resident' WHERE username='demo_student'")
    conn.execute("UPDATE user_profile SET username='demo_grid' WHERE username='demo_teacher'")


def _m5_legacy_single_user_username(conn):
    """v5: backfill a username for legacy single-user DB (id=1, no username)."""
    legacy = conn.execute(
        "SELECT id, username, name, resident_id, role FROM user_profile WHERE id = 1"
    ).fetchone()
    if legacy and (not legacy["username"] or legacy["username"] == ""):
        fallback = (
            legacy["resident_id"]
            or legacy["name"]
            or f"user_{legacy['role'] or 'resident'}"
        )
        existing = conn.execute(
            "SELECT id FROM user_profile WHERE username = ? AND id != 1", (fallback,)
        ).fetchone()
        if existing:
            fallback = f"{fallback}_1"
        conn.execute(
            "UPDATE user_profile SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE id = 1",
            (fallback,),
        )


def _m6_add_assignee_id(conn):
    """v6: add assignee_id to community_issues (dispatch by user id, not name)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(community_issues)")]
    if "assignee_id" not in cols:
        conn.execute("ALTER TABLE community_issues ADD COLUMN assignee_id INTEGER")


def _m7_add_escalated_at(conn):
    """v7: add escalated_at to community_issues (SLA escalation timestamp)."""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(community_issues)")]
    if "escalated_at" not in cols:
        conn.execute("ALTER TABLE community_issues ADD COLUMN escalated_at TIMESTAMP")


def _m8_create_event_memory(conn):
    """v8: create event_memory (cross-session event log for personalization)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS event_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "event_type TEXT NOT NULL, summary TEXT NOT NULL, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m9_create_elderly_profile(conn):
    """v9: create elderly_profile (health/meds/contacts + safety-checkin state)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS elderly_profile ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL UNIQUE, "
        "health_info TEXT DEFAULT '{}', medication_reminders TEXT DEFAULT '[]', "
        "emergency_contact TEXT DEFAULT '[]', is_living_alone INTEGER DEFAULT 0, "
        "is_managed_by_family INTEGER DEFAULT 0, last_active_at TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (user_id) REFERENCES user_profile(id))"
    )


def _m10_create_sos_log(conn):
    """v10: create sos_log (emergency SOS requests from elderly users)."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sos_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "handled_at TIMESTAMP)"
    )


def _apply_base_schema(conn):
    """Create the base tables (idempotent). Always runs after pre-base migration."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS user_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL DEFAULT '',
            password_hash TEXT DEFAULT '',
            role TEXT DEFAULT 'resident',
            community TEXT DEFAULT '',
            building TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            name TEXT DEFAULT '',
            resident_id TEXT DEFAULT '',
            preferences TEXT DEFAULT '[]',
            onboarding_done INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS knowledge_base (
            id INTEGER PRIMARY KEY,
            category TEXT DEFAULT '',
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            keywords TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS community_issues (
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
            author TEXT DEFAULT '',
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
            participant_label TEXT DEFAULT '匿名居民',
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


def init_db(db_path: str):
    """Initialize the database — create tables and apply versioned migrations.

    Schema changes are tracked in `schema_version` (current version) and
    `schema_migrations` (audit log). Migrations run in order and, on a real
    failure, raise instead of silently passing — so a mid-state upgrade is
    visible in the logs rather than guessed at.
    """
    global _DB_PATH
    _DB_PATH = db_path
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    _create_schema_version_table(conn)
    current = _get_schema_version(conn)

    # Pre-base migration (must run before CREATE TABLE so the table rename wins
    # over a fresh community_issues created by the base schema).
    pre = [(1, "rename_campus_issues_to_community_issues", _m1_rename_issues_table)]
    for version, name, fn in pre:
        if version <= current:
            continue
        fn(conn)
        _set_schema_version(conn, version, name)
        conn.commit()

    _apply_base_schema(conn)
    conn.commit()

    post = [
        (2, "rename_user_profile_fields", _m2_rename_profile_fields),
        (3, "add_missing_columns", _m3_add_missing_columns),
        (4, "migrate_role_values", _m4_migrate_role_values),
        (5, "legacy_single_user_username", _m5_legacy_single_user_username),
        (6, "add_assignee_id", _m6_add_assignee_id),
        (7, "add_escalated_at", _m7_add_escalated_at),
        (8, "create_event_memory", _m8_create_event_memory),
        (9, "create_elderly_profile", _m9_create_elderly_profile),
        (10, "create_sos_log", _m10_create_sos_log),
    ]
    for version, name, fn in post:
        if version <= current:
            continue
        fn(conn)
        _set_schema_version(conn, version, name)
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
