"""数据库核心 — 连接管理和公共小工具。"""
import hashlib
import hmac as _hmac
import logging
import os
import sqlite3
from contextlib import contextmanager

log = logging.getLogger("db_core")

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
        "scope_target_json TEXT DEFAULT '[]', pinned_at TIMESTAMP, "
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


def _m32_agent_handoffs(conn):
    """v32：人工处理包（无缝转人工：上下文打包给负责人，免重复询问）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_handoffs ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT DEFAULT '', "
        "user_id INTEGER NOT NULL, role TEXT DEFAULT 'resident', "
        "intent TEXT DEFAULT '', reason TEXT DEFAULT '', package_json TEXT DEFAULT '{}', "
        "status TEXT DEFAULT '待处理', assigned_to INTEGER, "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m33_llm_usage(conn):
    """v33：LLM 用量统计（P2-05：费用可预测、预算告警、规则优先可验证）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS llm_usage ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, module TEXT DEFAULT '', "
        "tokens_in INTEGER DEFAULT 0, tokens_out INTEGER DEFAULT 0, "
        "cost_yuan REAL DEFAULT 0, duration_ms INTEGER DEFAULT 0, "
        "cache_hit INTEGER DEFAULT 0, input_preview TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m34_public_opinion(conn):
    """v34：舆情监测（P3-01：12345/媒体/手动录入 → 分级 → 一键转工单）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS public_opinion ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT DEFAULT '手动录入', "
        "content TEXT DEFAULT '', keywords TEXT DEFAULT '', level TEXT DEFAULT '黄色', "
        "status TEXT DEFAULT '待关注', related_issue_id INTEGER, "
        "created_by TEXT DEFAULT '', note TEXT DEFAULT '', "
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )


def _m35_draft_contents(conn):
    """v35：草稿内容持久化（P1-A5-02：报修/提案草稿完整落库，重启恢复）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS draft_contents ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, "
        "draft_type TEXT NOT NULL, content_json TEXT DEFAULT '{}', "
        "current_step TEXT DEFAULT '', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, "
        "UNIQUE(user_id, draft_type))"
    )


def _add_column(conn, table: str, column: str, ddl: str) -> None:
    """SQLite 兼容加列（列已存在则跳过）。"""
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")


def _m36_phone_enc(conn):
    """v36：敏感字段加密列（P1-G1-02：手机号迁移到密文，明文置空）。"""
    _add_column(conn, "user_profile", "phone_enc", "phone_enc TEXT DEFAULT ''")
    _add_column(conn, "emergency_contacts", "phone_enc", "phone_enc TEXT DEFAULT ''")


def _m37_trace_id(conn):
    """v37：链路追踪 trace_id 列（activity_log / agent_logs / exception_log，P2-F4-01）。"""
    _add_column(conn, "activity_log", "trace_id", "trace_id TEXT DEFAULT ''")
    _add_column(conn, "agent_logs", "trace_id", "trace_id TEXT DEFAULT ''")
    _add_column(conn, "exception_log", "trace_id", "trace_id TEXT DEFAULT ''")


def _m38_issue_phone_enc(conn):
    """v38：工单手机号加密列（P0：reporter/agent/assignee 手机号落库加密，明文置空）。"""
    _add_column(conn, "community_issues", "reporter_phone_enc", "reporter_phone_enc TEXT DEFAULT ''")
    _add_column(conn, "community_issues", "agent_phone_enc", "agent_phone_enc TEXT DEFAULT ''")
    _add_column(conn, "community_issues", "assignee_phone_enc", "assignee_phone_enc TEXT DEFAULT ''")


def _m39_phone_enc_more(conn):
    """v39：health_consults + emergency_calls 手机号加密列（P0 收口遗漏面）。"""
    _add_column(conn, "health_consults", "phone_enc", "phone_enc TEXT DEFAULT ''")
    _add_column(conn, "health_consults", "agent_phone_enc", "agent_phone_enc TEXT DEFAULT ''")
    _add_column(conn, "emergency_calls", "target_phone_enc", "target_phone_enc TEXT DEFAULT ''")


def _m40_performance_indexes(conn):
    """v40：高频查询索引（P1-3）。列名已对照真实表结构核实。可重复执行（IF NOT EXISTS）。"""
    stmts = [
        "CREATE INDEX IF NOT EXISTS idx_issues_status ON community_issues(status)",
        "CREATE INDEX IF NOT EXISTS idx_issues_reported ON community_issues(reported_at)",
        "CREATE INDEX IF NOT EXISTS idx_issues_assignee ON community_issues(assignee_name)",
        "CREATE INDEX IF NOT EXISTS idx_issues_satisfaction ON community_issues(satisfaction)",
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_intent ON agent_logs(intent)",
        "CREATE INDEX IF NOT EXISTS idx_agent_logs_created ON agent_logs(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_agent_dialogs_user ON agent_dialogs(user_id, role, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_activity_target ON activity_log(target_type, target_id)",
        "CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_health_consults_status ON health_consults(status)",
        "CREATE INDEX IF NOT EXISTS idx_health_consults_user ON health_consults(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_emergency_calls_user ON emergency_calls(user_id)",
    ]
    for s in stmts:
        conn.execute(s)
    conn.commit()


def _m41_tenant_column(conn):
    """v41：多租户字段（P2-1 演示级）——给 3 张主表加 tenant_id，默认取 config.DEFAULT_TENANT。

    仅预留字段（不改各查询函数），支撑"数据模型可演进"叙事；未来接多社区时
    按写入方传入租户并加查询过滤。
    """
    import config
    default_tenant = getattr(config, "DEFAULT_TENANT", "") or "default"
    for table in ("community_issues", "proposals", "notices"):
        _add_column(conn, table, "tenant_id", "tenant_id TEXT DEFAULT ''")
        # 回填默认租户（对已存在且空的行）
        conn.execute(f"UPDATE {table} SET tenant_id=? WHERE tenant_id='' OR tenant_id IS NULL",
                     (default_tenant,))
    conn.commit()


def _m42_medication_intake(conn):
    """M3/v42：用药打卡记录（人情味闭环：我吃了 / 稍后提醒 + 连续天数）。

    幂等（IF NOT EXISTS）；intake_date 为本地日期，UNIQUE 挡住同一天同一提醒重复打卡。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS medication_intake_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            reminder_id INTEGER NOT NULL,
            intake_date TEXT NOT NULL,            -- 本地日期 YYYY-MM-DD
            taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            action TEXT DEFAULT 'taken',          -- taken / snooze
            UNIQUE(user_id, reminder_id, intake_date)
        );
        CREATE INDEX IF NOT EXISTS idx_intake_user ON medication_intake_log(user_id, taken_at);
    """)


def _m47_elderly_vitals(conn):
    """v47：老年健康记录表（血压 / 血糖）——P4「深化老年端」。

    为什么新建表而不是往 `elderly_profile.health_info` JSON 里塞：那个 JSON 是整块覆盖写
    （`set_health_info`），并发录入会互相覆盖丢记录，也无法按时间分页/排序。

    幂等：建表用 IF NOT EXISTS；回填走 `db_vitals.backfill_from_profile`（自身带去重守卫）。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS elderly_vitals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,                   -- bp / glucose
            sys INTEGER,                          -- 收缩压 mmHg
            dia INTEGER,                          -- 舒张压 mmHg
            glucose REAL,                         -- 血糖 mmol/L
            measure_when TEXT DEFAULT 'random',   -- fasting / postprandial / random
            measured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            recorder_id INTEGER,                  -- 谁录的（老人自己 / 家属代录）
            source TEXT DEFAULT 'self',           -- self / family / grid / backfill
            note TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_vitals_user_kind
            ON elderly_vitals(user_id, kind, measured_at);
    """)
    # 历史血压（health_info.blood_pressure）搬进新表，避免"以前有记录、现在一开新页是空的"
    try:
        import os
        import sys as _sys
        _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from data.db_vitals import backfill_from_profile
        backfill_from_profile(conn)
    except Exception as e:  # noqa: BLE001
        log.warning("v47 健康记录回填失败（不影响建表）：%s", e)


def _m48_tenant_isolation(conn):
    """v48：多租户真隔离（核心表）——加列 → 归一化 → 按归属人回填 → 索引。

    ⚠️ v41 的教训：当年只做了"给 3 张表加列 + 回填默认值"，业务代码**从不写入**，
    于是新数据租户为空、隔离静默退化成"空租户"（实测 community_issues 曾积压 128 行空租户）。
    所以本迁移只是**一半**，另一半是写入侧（所有社区范围数据 INSERT 带 tenant_id）与
    读取侧（显式传 tenant 过滤）——见 `utils/tenant.py` 头部说明与
    `docs/spec/多租户改造清单-明细.md`。

    归一化规则：租户键 = `user_profile.community` 的**社区名**；历史值 `'海淀区'` 这类行政区
    与社区名不同域，按归属人重算；无归属人的（如历史通知）落 `config.DEFAULT_COMMUNITY`
    并**计数告警**——绝不静默。
    """
    import os
    import sys as _sys
    _sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.tenant import normalize_tenant

    # (表, 归属人列 or None=无归属人)
    tables = [
        ("community_issues", "reporter_id"),
        ("proposals", "reporter_id"),
        ("notices", None),
        ("health_consults", "user_id"),
        ("policy_questions", "user_id"),
        ("medication_reminders", "user_id"),
        ("emergency_contacts", "user_id"),
        ("emergency_calls", "user_id"),
        ("agent_logs", "user_id"),
        ("agent_handoffs", "user_id"),
        ("agent_dialogs", "user_id"),
        ("care_event_log", "user_id"),
        ("weather_check_tasks", None),
    ]
    try:
        import config
        fallback = normalize_tenant(getattr(config, "DEFAULT_COMMUNITY", "") or "")
    except Exception:  # noqa: BLE001
        fallback = ""

    valid = ("SELECT community FROM user_profile "
             "WHERE community IS NOT NULL AND community != ''")
    for table, owner in tables:
        _add_column(conn, table, "tenant_id", "tenant_id TEXT DEFAULT ''")
        if owner:
            # ① 有归属人的：按归属人的社区重算（同时纠正历史行政区值）
            conn.execute(
                f"UPDATE {table} SET tenant_id = COALESCE(("
                f"  SELECT u.community FROM user_profile u "
                f"  WHERE u.id = {table}.{owner} AND u.community IS NOT NULL AND u.community != ''"
                f"), '') "
                f"WHERE tenant_id IS NULL OR tenant_id = '' OR tenant_id NOT IN ({valid})"
            )
        # ② 兜底：仍拿不到租户的行（无归属人 / 归属人不存在或没社区）落默认社区，并**计数告警**。
        #    实测这类行是压根没有归属人的历史与种子数据（reporter_id IS NULL、user_id=0），
        #    让它们对所有租户不可见没有意义，按默认社区归档更诚实——但必须让人看见归档了多少行。
        if fallback:
            cur = conn.execute(
                f"UPDATE {table} SET tenant_id=? WHERE tenant_id IS NULL OR tenant_id = '' "
                f"OR tenant_id NOT IN ({valid})", (fallback,))
            if cur.rowcount:
                log.info("v48：%s 有 %d 行无归属人（或归属人无社区），按默认社区「%s」归档",
                         table, cur.rowcount, fallback)
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table}(tenant_id)")

    # ③ 收尾核对：还剩多少行拿不到租户？这些行对所有租户都不可见（fail-closed），必须让人看见
    leftover = []
    for table, _owner in tables:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table} WHERE tenant_id IS NULL OR tenant_id = '' "
            f"OR tenant_id NOT IN ({valid})").fetchone()
        if row and row["c"]:
            leftover.append(f"{table}={row['c']}")
    if leftover:
        log.warning("v48：以下历史行无法归属到任何社区，将对所有租户不可见（fail-closed）：%s",
                    "、".join(leftover))


def _m43_kb_query_log(conn):
    """U3/v43：知识库查询日志（RAG 可观测：命中率 / 零命中问题 / 检索路线）。

    与 policy_questions 的区别：policy_questions 只记录已成立的问题（匹配失败不落库），
    本表**记录每一次检索尝试**（含未命中），才能算真实命中率与「零命中问题 top」。
    幂等（IF NOT EXISTS）；无 PII（只存问题文本与检索元数据，不存用户手机号等）。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kb_query_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT DEFAULT 'resident',
            question TEXT DEFAULT '',
            matched INTEGER DEFAULT 0,          -- 是否达到自动回答阈值
            reason TEXT DEFAULT '',             -- low_score / no_knowledge / manual / ok
            top_score REAL DEFAULT 0,           -- 最佳匹配分
            top_kb_id INTEGER,                  -- 最佳匹配条目 id
            retrieval TEXT DEFAULT '',          -- lexical / hybrid
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_kbq_created ON kb_query_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_kbq_matched ON kb_query_log(matched, created_at);
    """)


def _m44_care_event_log(conn):
    """U4/v44：关怀事件日志（人情味可量化：情绪识别 / 安抚触达 / 场景共情）。

    一行 = 一次「关怀动作」（有情绪安抚句或场景共情句时记录），用于统计：
      - 情绪识别次数与分布（emotion_tag）
      - 关怀触达数与场景分布（scene：repair_ok / sos / fail）
      - 情绪 → 转人工率 / 情绪 → 闭环率（配合 status/intent）
    无 PII（不存原文，只存情绪标签与场景）。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS care_event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT DEFAULT 'resident',
            emotion_tag TEXT DEFAULT '',        -- 焦虑/着急/不满…（tone.EMOTION 的 key）
            comfort_used INTEGER DEFAULT 0,     -- 是否用了情绪安抚句
            scene TEXT DEFAULT '',              -- repair_ok / sos / fail
            scene_line_used INTEGER DEFAULT 0,  -- 是否用了场景共情句
            intent TEXT DEFAULT '',
            status TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_care_created ON care_event_log(created_at);
        CREATE INDEX IF NOT EXISTS idx_care_emotion ON care_event_log(emotion_tag, created_at);
    """)


def _m45_knowledge_graph(conn):
    """U6/v45：轻量知识图谱三表（只做「能查得出东西」的图谱，不做可视化花架子）。

    - `kg_entity`：实体（楼栋 / 设施 / 政策事项 / 人群 / 工单类别），`name` 全局唯一，
      带 `etype` 与来源计数 `attrs_json`。
    - `kg_relation`：实体间关系（located_in / has_facility / applies_to / mentions /
      related_issue），`UNIQUE(src_id, rel, dst_id)` 保证重复建图不产生重复边，
      `weight` 为共现强度，`source` 记录边来自哪类业务对象（issue/knowledge/proposal）。
    - `kg_mention`：实体 ↔ 业务对象的引用（ref_type ∈ issue/knowledge/proposal），
      是「按实体反查历史工单 / 相关政策」的落地依据。

    幂等（IF NOT EXISTS）；实体由 `data/db_kg.extract_entities` 规则抽取，不依赖 LLM、
    无 PII（不存原文，只存实体名与引用 id）。
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kg_entity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,          -- 实体名（归一化后，如「3号楼」「电梯」）
            etype TEXT NOT NULL DEFAULT '',     -- building/facility/topic/group/category
            community TEXT DEFAULT '',          -- 所属社区（预留，当前多为空）
            attrs_json TEXT DEFAULT '{}',       -- 来源计数等附加属性
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS kg_relation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_id INTEGER NOT NULL,
            rel TEXT NOT NULL,                  -- 关系类型（见 RELS）
            dst_id INTEGER NOT NULL,
            weight REAL DEFAULT 1,              -- 共现强度（次数）
            source TEXT DEFAULT '',             -- issue / knowledge / proposal
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(src_id, rel, dst_id)
        );
        CREATE TABLE IF NOT EXISTS kg_mention (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id INTEGER NOT NULL,
            ref_type TEXT NOT NULL,             -- issue / knowledge / proposal
            ref_id INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(entity_id, ref_type, ref_id)
        );
        CREATE INDEX IF NOT EXISTS idx_kg_rel_src ON kg_relation(src_id, rel);
        CREATE INDEX IF NOT EXISTS idx_kg_rel_dst ON kg_relation(dst_id, rel);
        CREATE INDEX IF NOT EXISTS idx_kg_mention_entity ON kg_mention(entity_id, ref_type);
        CREATE INDEX IF NOT EXISTS idx_kg_mention_ref ON kg_mention(ref_type, ref_id);
    """)


def _enc_text(value: str) -> str:
    """迁移期文本加密（与 data 层 `_enc_phone` 同源：`utils.crypto` 单例）。

    失败时返回空串 —— 调用方**只在拿到非空密文时才清空明文列**，避免「加密失败 + 已清空」丢数据。
    """
    if not value:
        return ""
    try:
        from utils.crypto import get_crypto
        return get_crypto().encrypt(value)
    except Exception:  # noqa: BLE001
        log.warning("v46 迁移：加密失败，保留明文待下次重试（不丢数据）")
        return ""


# v46 需要补加密列的表 → 明文列（与 `scripts/audit_phone_encryption.py` 的体检口径一致）
_PHONE_ENC_TARGETS = (
    ("proposals", ("reporter_phone", "agent_phone")),
    ("proposal_drafts", ("reporter_phone", "agent_phone")),
    ("issue_drafts", ("reporter_phone", "agent_phone")),
)


def _m46_phone_enc_and_schema_drift(conn):
    """v46：手机号加密全量收口 + 收回运行时裸 ALTER（第七轮复审 P2-A / P3-D）。

    **为什么一次做两件事**：P2-A（提案手机号明文 181 条）暴露的是「加密迁移漏表」这一类问题，
    同一类缺口还有两张草稿表（issue_drafts / proposal_drafts，无 `*_enc` 列）与
    `user_profile.phone` 在 v36 之后又被写回的 4 条明文 —— 一次性补齐，避免打地鼠。
    同时把「运行时裸 ALTER 补列」（notices.scope_target_json / notices.pinned_at /
    kb_embeddings 三列）收回迁移链，让「全新建库」与「存量升级」走同一条路径。

    幂等：列用 PRAGMA 检查后添加；回填只在明文列非空时执行，且**加密成功才清空明文**。
    """
    # ① 补加密列
    for table, cols in _PHONE_ENC_TARGETS:
        for c in cols:
            _add_column(conn, table, f"{c}_enc", f"{c}_enc TEXT DEFAULT ''")

    # ② 存量明文回填 + 清空（加密失败则保留明文，下次迁移重试）
    migrated = 0
    for table, cols in _PHONE_ENC_TARGETS:
        for c in cols:
            rows = conn.execute(
                f"SELECT id, {c} AS v FROM {table} WHERE length(COALESCE({c}, '')) > 0"
            ).fetchall()
            for r in rows:
                enc = _enc_text(r["v"])
                if not enc:
                    continue
                conn.execute(f"UPDATE {table} SET {c}_enc=?, {c}='' WHERE id=?", (enc, r["id"]))
                migrated += 1

    # ③ user_profile.phone 明文残留（有 phone_enc 就直接清空，没有则先加密）
    rows = conn.execute(
        "SELECT id, phone AS v, phone_enc AS e FROM user_profile "
        "WHERE length(COALESCE(phone, '')) > 0"
    ).fetchall()
    for r in rows:
        enc = r["e"] or _enc_text(r["v"])
        if not enc:
            continue
        conn.execute("UPDATE user_profile SET phone_enc=?, phone='' WHERE id=?", (enc, r["id"]))
        migrated += 1

    # ④ 收回运行时裸 ALTER：notices 两列（原先只靠 db_notice._ensure_columns 补）
    _add_column(conn, "notices", "scope_target_json", "scope_target_json TEXT DEFAULT '[]'")
    _add_column(conn, "notices", "pinned_at", "pinned_at TIMESTAMP")

    # ⑤ kb_embeddings 三列（原先只靠 agent/rag.py 惰性 ALTER；表可能尚未创建，存在才补）
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='kb_embeddings'"
    ).fetchone():
        _add_column(conn, "kb_embeddings", "dense_json", "dense_json TEXT DEFAULT ''")
        _add_column(conn, "kb_embeddings", "dim", "dim INTEGER DEFAULT 0")
        _add_column(conn, "kb_embeddings", "provider", "provider TEXT DEFAULT ''")
    conn.commit()
    if migrated:
        log.info("v46 迁移：%d 处手机号明文已加密并清空", migrated)


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
        (32, "agent_handoffs", _m32_agent_handoffs),
        (33, "llm_usage", _m33_llm_usage),
        (34, "public_opinion", _m34_public_opinion),
        (35, "draft_contents", _m35_draft_contents),
        (36, "phone_enc", _m36_phone_enc),
        (37, "trace_id", _m37_trace_id),
        (38, "issue_phone_enc", _m38_issue_phone_enc),
        (39, "phone_enc_more", _m39_phone_enc_more),
        (40, "performance_indexes", _m40_performance_indexes),
        (41, "tenant_column", _m41_tenant_column),
        (42, "medication_intake", _m42_medication_intake),
        (43, "kb_query_log", _m43_kb_query_log),
        (44, "care_event_log", _m44_care_event_log),
        (45, "knowledge_graph", _m45_knowledge_graph),
        (46, "phone_enc_all_and_schema_drift", _m46_phone_enc_and_schema_drift),
        (47, "elderly_vitals", _m47_elderly_vitals),
        (48, "tenant_isolation", _m48_tenant_isolation),
    ]
    for version, name, fn in post:
        if version <= current:
            continue
        fn(conn)
        _set_schema_version(conn, version, name)
        conn.commit()

    # v48 的租户归一化是"数据回填"而非一次性结构变更：每次 init_db 重跑以纠正漂移
    # （历史行政区值被人工写脏、归属人社区变更等）。幂等，只动 tenant_id 为 NULL/空/非法值的行。
    if current >= 48:
        _m48_tenant_isolation(conn)
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
    # N4：写并发时避免"database is locked"立刻失败（WAL 下两写碰撞让输家等待而不是抛错）；
    #      synchronous=NORMAL 为 WAL 推荐策略（fsync 次数减少，性能与安全平衡）
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
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
