"""数据库核心 — 连接管理和公共小工具。"""
import hashlib
import hmac as _hmac
import os
import sqlite3
from contextlib import contextmanager

_DB_PATH: str = ""


_PBKDF2_ITERATIONS = 100_000


def _hash_password(password: str) -> str:
    """用 PBKDF2-SHA256 + 随机 16 字节盐给密码加盐哈希。

    格式:  pbkdf2:sha256:100000$<salt_hex>$<hash_hex>

    每个密码的盐都是随机生成的，源码里不写死任何密钥。
    """
    if not password:
        return ""
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return f"pbkdf2:sha256:{_PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    """校验密码和存储的 hash 是否匹配。

    兼容迁移：老版 SHA-256 hash（没有 '$' 分隔符）按旧的固定盐方案校验，
    下次写入时会重新哈希成新格式。
    """
    if not stored:
        return not password

    # 老格式：纯 SHA-256 hex（没有 '$'）
    if "$" not in stored:
        old = hashlib.sha256(f"campus-insight-salt-2026:{password}".encode()).hexdigest()
        return _hmac.compare_digest(old, stored) if old and stored else old == stored

    # 新格式：pbkdf2:sha256:<iter>$<salt_hex>$<hash_hex>
    try:
        _, salt_hex, hash_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
        return _hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


# 表结构版本管理
_SCHEMA_CURRENT_VERSION = 26


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


# 迁移步骤（按顺序执行；真失败会抛异常，不会悄悄跳过）

def _m1_rename_issues_table(conn):
    """v1：老表 `campus_issues` → `community_issues`（可重复执行）。"""
    has_old = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='campus_issues'"
    ).fetchone()
    has_new = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='community_issues'"
    ).fetchone()
    if has_old and not has_new:
        conn.execute("ALTER TABLE campus_issues RENAME TO community_issues")


def _m2_rename_profile_fields(conn):
    """v2：user_profile 里校园时代的字段名改成社区命名（可重复执行）。"""
    renames = [("student_id", "resident_id"), ("school", "community"),
               ("grade", "building"), ("major", "unit")]
    cols = [r[1] for r in conn.execute("PRAGMA table_info(user_profile)")]
    for old, new in renames:
        if old in cols and new not in cols:
            conn.execute(f"ALTER TABLE user_profile RENAME COLUMN {old} TO {new}")


def _m3_add_missing_columns(conn):
    """v3：老库里可能缺的列补上（用 PRAGMA 查，可重复执行）。"""
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
    """v4：旧角色值迁移 student→resident、teacher→grid（顺带改 demo 用户名）。"""
    conn.execute("UPDATE user_profile SET role='resident' WHERE role='student'")
    conn.execute("UPDATE user_profile SET role='grid' WHERE role='teacher'")
    conn.execute("UPDATE user_profile SET username='demo_resident' WHERE username='demo_student'")
    conn.execute("UPDATE user_profile SET username='demo_grid' WHERE username='demo_teacher'")


def _m5_legacy_single_user_username(conn):
    """v5：给老的单用户库（id=1 没用户名）补一个用户名。"""
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
    """v6：community_issues 加 assignee_id（按用户 ID 派单，不再用名字）。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(community_issues)")]
    if "assignee_id" not in cols:
        conn.execute("ALTER TABLE community_issues ADD COLUMN assignee_id INTEGER")


def _m7_add_escalated_at(conn):
    """v7：community_issues 加 escalated_at（SLA 升级时间戳）。"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(community_issues)")]
    if "escalated_at" not in cols:
        conn.execute("ALTER TABLE community_issues ADD COLUMN escalated_at TIMESTAMP")


def _m8_create_event_memory(conn):
    """v8：建 event_memory 表（跨会话事件日志，供个性化用）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS event_memory ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "event_type TEXT NOT NULL, summary TEXT NOT NULL, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m9_create_elderly_profile(conn):
    """v9：建 elderly_profile 表（健康/用药/联系人 + 安全打卡状态）。"""
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
    """v10：建 sos_log 表（老人紧急 SOS 求助）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS sos_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "status TEXT DEFAULT 'pending', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "handled_at TIMESTAMP)"
    )


def _add_column_if_missing(conn, table: str, col: str, decl: str):
    """给表补一列（幂等，用 PRAGMA 检查，避免 ALTER 重复报错）。"""
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _m11_activity_log_audit_fields(conn):
    """v11：activity_log 扩展留痕字段（模块来源 + 前值/后值）。"""
    _add_column_if_missing(conn, "activity_log", "module", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "activity_log", "before_value", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "activity_log", "after_value", "TEXT DEFAULT ''")


def _m12_issue_tables(conn):
    """v12：报修模块 — community_issues 扩展 + 草稿/安全提醒/补充信息表。"""
    issue_cols = [
        ("issue_type", "TEXT DEFAULT '室内'"),
        ("reporter_name", "TEXT DEFAULT ''"),
        ("reporter_phone", "TEXT DEFAULT ''"),
        ("audit_status", "TEXT DEFAULT ''"),
        ("approved_at", "TIMESTAMP"),
        ("assignee_name", "TEXT DEFAULT ''"),
        ("assignee_phone", "TEXT DEFAULT ''"),
        ("resolve_note", "TEXT DEFAULT ''"),
        ("photo_before", "TEXT DEFAULT '[]'"),
        ("photo_after", "TEXT DEFAULT '[]'"),
        ("no_photo_reason", "TEXT DEFAULT ''"),
        ("is_agent_report", "INTEGER DEFAULT 0"),
        ("agent_name", "TEXT DEFAULT ''"),
        ("agent_phone", "TEXT DEFAULT ''"),
        ("agent_relation", "TEXT DEFAULT ''"),
        ("is_violation", "INTEGER DEFAULT 0"),
        ("non_community_responsibility", "INTEGER DEFAULT 0"),
        ("supplement_count", "INTEGER DEFAULT 0"),
        ("supplemented_at", "TIMESTAMP"),
    ]
    for col, decl in issue_cols:
        _add_column_if_missing(conn, "community_issues", col, decl)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS issue_drafts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "title TEXT DEFAULT '', category TEXT DEFAULT '', issue_type TEXT DEFAULT '室内', "
        "location TEXT DEFAULT '', description TEXT DEFAULT '', urgency TEXT DEFAULT '普通', "
        "reporter_name TEXT DEFAULT '', reporter_phone TEXT DEFAULT '', "
        "photo_before TEXT DEFAULT '[]', is_agent_report INTEGER DEFAULT 0, "
        "agent_name TEXT DEFAULT '', agent_phone TEXT DEFAULT '', agent_relation TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS safety_reminders ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "description TEXT DEFAULT '', location TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS issue_supplements ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, issue_id INTEGER NOT NULL, "
        "content TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "FOREIGN KEY (issue_id) REFERENCES community_issues(id))"
    )


def _m13_proposal_tables(conn):
    """v13：提案模块 — proposals 扩展 + 匿名投票/防重复/草稿表。"""
    prop_cols = [
        ("is_public", "INTEGER DEFAULT 1"),
        ("audit_status", "TEXT DEFAULT ''"),
        ("audit_opinion", "TEXT DEFAULT ''"),
        ("visibility_confirmed", "INTEGER DEFAULT 0"),
        ("published_at", "TIMESTAMP"),
        ("voting_started_at", "TIMESTAMP"),
        ("voting_ended_at", "TIMESTAMP"),
        ("reopen_count", "INTEGER DEFAULT 0"),
        ("executor_dept", "TEXT DEFAULT ''"),
        ("execution_result", "TEXT DEFAULT ''"),
        ("decision_reason", "TEXT DEFAULT ''"),
        ("attachment_public", "INTEGER DEFAULT 0"),
        ("reporter_name", "TEXT DEFAULT ''"),
        ("reporter_phone", "TEXT DEFAULT ''"),
        ("is_agent_report", "INTEGER DEFAULT 0"),
        ("agent_name", "TEXT DEFAULT ''"),
        ("agent_phone", "TEXT DEFAULT ''"),
        ("agent_relation", "TEXT DEFAULT ''"),
    ]
    for col, decl in prop_cols:
        _add_column_if_missing(conn, "proposals", col, decl)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS proposal_votes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id INTEGER NOT NULL, "
        "score INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS proposal_vote_dedup ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id INTEGER NOT NULL, "
        "user_id INTEGER NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(proposal_id, user_id))"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS proposal_drafts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "title TEXT DEFAULT '', description TEXT DEFAULT '', category TEXT DEFAULT '', "
        "is_public INTEGER DEFAULT 1, reporter_name TEXT DEFAULT '', reporter_phone TEXT DEFAULT '', "
        "attachment_public INTEGER DEFAULT 0, is_agent_report INTEGER DEFAULT 0, "
        "agent_name TEXT DEFAULT '', agent_phone TEXT DEFAULT '', agent_relation TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m14_weather_tables(conn):
    """v14：天气模块 — 缓存/预警/检查任务表。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_cache ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, city TEXT DEFAULT '', "
        "data_json TEXT DEFAULT '{}', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id TEXT DEFAULT '', "
        "alert_type TEXT DEFAULT '', level TEXT DEFAULT '', "
        "effective_time TIMESTAMP, expire_time TIMESTAMP, "
        "status TEXT DEFAULT 'active', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS weather_check_tasks ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, alert_id TEXT DEFAULT '', "
        "alert_type TEXT DEFAULT '', level TEXT DEFAULT '', checklist_json TEXT DEFAULT '[]', "
        "status TEXT DEFAULT '待检查', checker TEXT DEFAULT '', "
        "result TEXT DEFAULT '', note TEXT DEFAULT '', checked_at TIMESTAMP, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m15_health_tables(conn):
    """v15：疾病预防 — 内容发布 + 健康咨询表。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS health_contents ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', "
        "content_type TEXT DEFAULT '', body TEXT DEFAULT '', source TEXT DEFAULT '', "
        "publisher TEXT DEFAULT '', auditor TEXT DEFAULT '', audit_opinion TEXT DEFAULT '', "
        "status TEXT DEFAULT '草稿', is_pinned INTEGER DEFAULT 0, pinned_at TIMESTAMP, "
        "weather_link_json TEXT DEFAULT '[]', elderly_reminder_text TEXT DEFAULT '', "
        "info_updated_at TEXT DEFAULT '', expire_at TEXT DEFAULT '', "
        "published_at TIMESTAMP, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS health_consults ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "name TEXT DEFAULT '', phone TEXT DEFAULT '', consult_type TEXT DEFAULT '', "
        "content TEXT DEFAULT '', building TEXT DEFAULT '', attachment_json TEXT DEFAULT '[]', "
        "is_agent_report INTEGER DEFAULT 0, agent_name TEXT DEFAULT '', "
        "agent_phone TEXT DEFAULT '', agent_relation TEXT DEFAULT '', "
        "status TEXT DEFAULT '待回复', reply TEXT DEFAULT '', reply_doctor_guide TEXT DEFAULT '', "
        "reply_need_offline INTEGER DEFAULT 0, reply_at TIMESTAMP, "
        "feedback TEXT DEFAULT '', feedback_reason TEXT DEFAULT '', feedback_at TIMESTAMP, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m16_notice_tables(conn):
    """v16：通知发布 — 广播通知 + 已读记录表。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notices ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT DEFAULT '', "
        "notice_type TEXT DEFAULT '社区公告', publish_scope TEXT DEFAULT '全体居民', "
        "body TEXT DEFAULT '', elderly_summary TEXT DEFAULT '', publisher TEXT DEFAULT '', "
        "scheduled_at TIMESTAMP, published_at TIMESTAMP, expire_at TIMESTAMP, "
        "is_pinned INTEGER DEFAULT 0, is_urgent INTEGER DEFAULT 0, "
        "attachment_json TEXT DEFAULT '[]', status TEXT DEFAULT '草稿', "
        "down_reason TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notice_reads ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, notice_id INTEGER NOT NULL, "
        "client_type TEXT DEFAULT 'resident', user_id INTEGER NOT NULL, "
        "read_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(notice_id, client_type, user_id))"
    )


def _m17_elderly_tables(conn):
    """v17：老年端 — 用药提醒/紧急联系人/紧急求助表。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS medication_reminders ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "patient_name TEXT DEFAULT '', drug_name TEXT DEFAULT '', dosage TEXT DEFAULT '', "
        "times_json TEXT DEFAULT '[]', repeat_rule TEXT DEFAULT '每天', "
        "start_date TEXT DEFAULT '', end_date TEXT DEFAULT '', note TEXT DEFAULT '', "
        "photo TEXT DEFAULT '', setter_id INTEGER, status TEXT DEFAULT '待审核', "
        "audit_opinion TEXT DEFAULT '', audited_at TIMESTAMP, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS emergency_contacts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "name TEXT DEFAULT '', phone TEXT DEFAULT '', relation TEXT DEFAULT '', "
        "setter_id INTEGER, status TEXT DEFAULT '待审核', audit_opinion TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS emergency_calls ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "call_type TEXT DEFAULT 'contact', target_name TEXT DEFAULT '', target_phone TEXT DEFAULT '', "
        "result TEXT DEFAULT '', status TEXT DEFAULT '求助中', "
        "handle_note TEXT DEFAULT '', handled_at TIMESTAMP, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m18_knowledge_tables(conn):
    """v18：政策问答 — knowledge_base 扩展 + 版本/提问表。"""
    kb_cols = [
        ("audit_status", "TEXT DEFAULT '已发布'"),
        ("audit_opinion", "TEXT DEFAULT ''"),
        ("source", "TEXT DEFAULT ''"),
        ("effective_date", "TEXT DEFAULT ''"),
        ("expire_date", "TEXT DEFAULT ''"),
        ("version", "INTEGER DEFAULT 1"),
        ("cite_count", "INTEGER DEFAULT 0"),
        ("plain_interpretation", "TEXT DEFAULT ''"),
        ("summary", "TEXT DEFAULT ''"),
        ("publisher", "TEXT DEFAULT ''"),
        ("auditor", "TEXT DEFAULT ''"),
        ("policy_number", "TEXT DEFAULT ''"),
        ("applicable_area", "TEXT DEFAULT ''"),
        ("attachment", "TEXT DEFAULT ''"),
    ]
    for col, decl in kb_cols:
        _add_column_if_missing(conn, "knowledge_base", col, decl)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS knowledge_versions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, knowledge_id INTEGER NOT NULL, "
        "version INTEGER DEFAULT 1, title TEXT DEFAULT '', content TEXT DEFAULT '', "
        "plain_interpretation TEXT DEFAULT '', summary TEXT DEFAULT '', source TEXT DEFAULT '', "
        "effective_date TEXT DEFAULT '', expire_date TEXT DEFAULT '', "
        "snapshot_json TEXT DEFAULT '{}', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS policy_questions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "question TEXT DEFAULT '', summary TEXT DEFAULT '', q_type TEXT DEFAULT '', "
        "source TEXT DEFAULT '居民端', status TEXT DEFAULT '已自动回答', "
        "auto_answer TEXT DEFAULT '', answer TEXT DEFAULT '', cited_knowledge_id INTEGER, "
        "answered_by TEXT DEFAULT '', answered_at TIMESTAMP, "
        "feedback TEXT DEFAULT '', feedback_reason TEXT DEFAULT '', feedback_at TIMESTAMP, "
        "loop_count INTEGER DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m19_drop_dead_tables(conn):
    """v19：删除校园时代遗留的死表（无任何代码引用）。"""
    for t in ("club_activities", "courses", "events", "exams"):
        conn.execute(f"DROP TABLE IF EXISTS {t}")


def _m20_proposal_extra_cols(conn):
    """v20：proposals 补提案模块必需的 6 列（审核时间/楼栋/执行时间/反馈）。"""
    for col, decl in [
        ("audited_at", "TIMESTAMP"),
        ("community_building", "TEXT DEFAULT ''"),
        ("resolved_at", "TIMESTAMP"),
        ("feedback_at", "TIMESTAMP"),
        ("feedback_reason", "TEXT DEFAULT ''"),
        ("satisfaction", "TEXT DEFAULT ''"),
    ]:
        _add_column_if_missing(conn, "proposals", col, decl)


def _m21_user_phone(conn):
    """v21：user_profile 加 phone 字段（报修/提案/咨询的手机号从用户资料带出）。"""
    _add_column_if_missing(conn, "user_profile", "phone", "TEXT DEFAULT ''")


def _m22_exception_log(conn):
    """v22：建 exception_log 表（系统异常日志单独保存 7 天，不混入业务留痕）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS exception_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT DEFAULT '', "
        "error TEXT DEFAULT '', detail TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m23_guardian_binding(conn):
    """v23：user_profile 加 bound_elderly_id（家属绑定的老人，0=未绑定，用于老年免登录）。"""
    _add_column_if_missing(conn, "user_profile", "bound_elderly_id", "INTEGER DEFAULT 0")


def _m24_proposal_attachment(conn):
    """v24：proposals 加 attachment 列（提案附件图片路径 JSON，spec 02）。"""
    _add_column_if_missing(conn, "proposals", "attachment", "TEXT DEFAULT '[]'")


def _m25_settings(conn):
    """v25：建 settings 表（key-value 配置，供匹配阈值/联动阈值等持久化）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings ("
        "key TEXT PRIMARY KEY, value TEXT DEFAULT '')"
    )


def _m26_knowledge_timestamps(conn):
    """v26：knowledge_base 加 created_at/updated_at（知识库列表更新时间列，spec 07）。

    SQLite ADD COLUMN 不支持 CURRENT_TIMESTAMP 默认值，用空串，写入时显式填时间。
    """
    _add_column_if_missing(conn, "knowledge_base", "created_at", "TEXT DEFAULT ''")
    _add_column_if_missing(conn, "knowledge_base", "updated_at", "TEXT DEFAULT ''")


def _m27_proposal_auditor(conn):
    """v27：proposals 加 auditor（最后审核人），支撑「退回修改后仍由原审核人审核」。"""
    _add_column_if_missing(conn, "proposals", "auditor", "TEXT DEFAULT ''")


def _m28_issue_supplement_pending(conn):
    """v28：community_issues 加 supplement_pending（居民补充信息待负责人确认标记）。"""
    _add_column_if_missing(conn, "community_issues", "supplement_pending", "INTEGER DEFAULT 0")


def _m29_proposal_comments(conn):
    """v29：proposal_comments 提案公示议论表（匿名：不存身份展示，user_id 仅用于防刷与伪名）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS proposal_comments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, proposal_id INTEGER NOT NULL, "
        "user_id INTEGER NOT NULL, content TEXT NOT NULL, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m30_agent(conn):
    """v30：Agent 统一入口模块 — 历史对话 + Agent 留痕表。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_dialogs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "role TEXT DEFAULT 'resident', text TEXT DEFAULT '', is_bot INTEGER DEFAULT 0, "
        "intent TEXT DEFAULT '', related_id INTEGER, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_logs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, "
        "role TEXT DEFAULT 'resident', user_input TEXT DEFAULT '', corrected TEXT DEFAULT '', "
        "intent TEXT DEFAULT '', routed TEXT DEFAULT '', status TEXT DEFAULT '成功', "
        "error TEXT DEFAULT '', related_id INTEGER, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m31_agent_sessions(conn):
    """v31：Agent 会话落库（重启不丢、多实例不串线）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_sessions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL UNIQUE, "
        "user_id INTEGER NOT NULL, role TEXT DEFAULT 'resident', "
        "state_json TEXT DEFAULT '{}', "
        "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _apply_base_schema(conn):
    """建基础表（可重复执行）。总是在 pre-base 迁移之后跑。"""
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
    """初始化数据库 — 建表并跑版本化迁移。

    结构变更记录在 `schema_version`（当前版本）和 `schema_migrations`（审计日志）
    两张表里。迁移按顺序执行，真失败会直接抛异常而不是悄悄跳过——升级到一半
    卡住也能从日志看出来，不用靠猜。
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

    # pre-base 迁移（必须在建表之前跑，否则重命名会被基础建表的新表盖掉）
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
        (11, "activity_log_audit_fields", _m11_activity_log_audit_fields),
        (12, "issue_tables", _m12_issue_tables),
        (13, "proposal_tables", _m13_proposal_tables),
        (14, "weather_tables", _m14_weather_tables),
        (15, "health_tables", _m15_health_tables),
        (16, "notice_tables", _m16_notice_tables),
        (17, "elderly_tables", _m17_elderly_tables),
        (18, "knowledge_tables", _m18_knowledge_tables),
        (19, "drop_dead_tables", _m19_drop_dead_tables),
        (20, "proposal_extra_cols", _m20_proposal_extra_cols),
        (21, "user_phone", _m21_user_phone),
        (22, "exception_log", _m22_exception_log),
        (23, "guardian_binding", _m23_guardian_binding),
        (24, "proposal_attachment", _m24_proposal_attachment),
        (25, "settings", _m25_settings),
        (26, "knowledge_timestamps", _m26_knowledge_timestamps),
        (27, "proposal_auditor", _m27_proposal_auditor),
        (28, "issue_supplement_pending", _m28_issue_supplement_pending),
        (29, "proposal_comments", _m29_proposal_comments),
        (30, "agent", _m30_agent),
        (31, "agent_sessions", _m31_agent_sessions),
    ]
    for version, name, fn in post:
        if version <= current:
            continue
        fn(conn)
        _set_schema_version(conn, version, name)
        conn.commit()

    conn.close()


def get_connection() -> sqlite3.Connection:
    """拿一个裸的 SQLite 连接。一般建议用 `with get_db() as conn:` 更安全。"""
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
    """上下文管理器，安全的数据库连接 — 用完自动关闭。

    用法:
        with get_db() as conn:
            rows = conn.execute("SELECT ...").fetchall()
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
