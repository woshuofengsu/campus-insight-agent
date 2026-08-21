# data/db_notice.py
"""通知发布模块数据层 —— 广播通知（notices 表）+ 已读统计（notice_reads 表）。

按《05-通知发布.md》实现 6 类型 / 定时发布 / 紧急通知二次确认 / 发布范围 /
已读未读统计 / 草稿 / 下架 / 置顶 的完整闭环。

⚠️ 与 data/db_notifications.py（私信 notifications 表）严格区分、互不混用：
  - notifications 表：系统定向私信（工单/提案状态反馈、健康告警），保留不动；
  - notices / notice_reads：广播通知（本模块专管）。

关键约定：
  - 时间戳统一存本地时间字符串 "YYYY-MM-DD HH:MM:SS"，与 seed 数据口径一致；
    SQL 侧用 datetime('now','localtime') 对比。
  - 状态机：草稿 →（立即发布）→ 已发布；草稿 →（定时发布）→ 待发布 →（到点）→ 已发布；
    已发布 →（手动下架）→ 已下架；待发布 →（撤回）→ 草稿；发布失败 → 发布失败。
  - 紧急通知：发布/定时前必须二次确认（confirm_urgent=True）+ 发布人白名单校验，
    默认有效期 7 天，自动置顶；到期由 process_expired() 自动取消置顶（保留列表）。
  - 已读统计只算总量，不追踪具体谁；下架后统计保留（本模块不再刷新，由 UI 决定是否展示）。
"""
import json
import logging
from datetime import date, datetime, timedelta

from data.db_core import get_db
from data.db_notifications import log_activity

_log = logging.getLogger(__name__)

MODULE = "通知"

# ---- 常量：类型 / 范围 / 状态 ----

NOTICE_TYPES = ["社区公告", "活动通知", "停水停电通知", "紧急通知", "政策通知", "其他"]

PUBLISH_SCOPES = ["全体居民", "指定小区", "指定楼栋", "仅老年端"]

STATUS_DRAFT = "草稿"
STATUS_PENDING = "待发布"
STATUS_PUBLISHED = "已发布"
STATUS_DOWN = "已下架"
STATUS_FAILED = "发布失败"

STATUS_ALL = [STATUS_DRAFT, STATUS_PENDING, STATUS_PUBLISHED, STATUS_DOWN, STATUS_FAILED]

# 紧急通知默认有效期（天）
URGENT_DEFAULT_EXPIRE_DAYS = 7
# 普通通知置顶默认有效天数（超期自动取消）
PIN_EXPIRE_DAYS = 7
# 普通通知最多置顶条数（紧急置顶不受限）
MAX_PIN_COUNT = 3

# 可发布紧急通知的负责人白名单（用户名）。demo 里只有刘网格员（demo_grid）是社区负责人；
# 需要扩展时把用户名加进来即可。修改需留痕（修改白名单本身不属于本模块职责，见交付说明）。
URGENT_PUBLISHER_USERNAMES = {"demo_grid"}

# 通知类型 → 允许发布角色。当前系统角色体系只有 grid（负责人）一类，
# 细分角色（活动负责人/物业负责人/应急负责人）待角色体系扩展后启用。
NOTICE_TYPE_ROLES = {
    "社区公告": {"grid"},
    "活动通知": {"grid"},
    "停水停电通知": {"grid"},
    "紧急通知": {"grid"},   # 另需 URGENT_PUBLISHER_USERNAMES 白名单
    "政策通知": {"grid"},
    "其他": {"grid"},
}

# 附件限制（UI 侧同步校验）
ATTACHMENT_ALLOWED_EXTS = {"jpg", "jpeg", "png", "pdf"}
ATTACHMENT_MAX_SIZE = 5 * 1024 * 1024   # 单张 ≤ 5MB
ATTACHMENT_MAX_COUNT = 3

# ---- 小工具 ----

_TS_FMT = "%Y-%m-%d %H:%M:%S"


def _now() -> str:
    return datetime.now().strftime(_TS_FMT)


def _ts(v) -> str:
    """把 datetime / date / str 归一化成时间字符串；空值返回 ''。

    date（如 st.date_input 的下架时间）视为当天 23:59:59，
    避免「2026-08-20」和「2026-08-20 10:00:00」这种前缀比较误判。
    """
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.strftime(_TS_FMT)
    if isinstance(v, date):
        return datetime.combine(v, datetime.min.time().replace(hour=23, minute=59, second=59)).strftime(_TS_FMT)
    return str(v)[:19]


def _ensure_columns() -> None:
    """补齐 db_core v16 建表之外的列（幂等，不影响其他模块）。"""
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(notices)")]
        if "scope_target_json" not in cols:
            conn.execute("ALTER TABLE notices ADD COLUMN scope_target_json TEXT DEFAULT '[]'")
        if "pinned_at" not in cols:
            conn.execute("ALTER TABLE notices ADD COLUMN pinned_at TIMESTAMP")
        conn.commit()


def can_publish_urgent(user_id: int) -> bool:
    """是否指定紧急通知负责人（白名单 + 必须是负责人角色）。"""
    if not user_id:
        return False
    with get_db() as conn:
        row = conn.execute(
            "SELECT username, role FROM user_profile WHERE id=? AND is_active=1", (user_id,)
        ).fetchone()
    if not row or row["role"] != "grid":
        return False
    return (row["username"] or "") in URGENT_PUBLISHER_USERNAMES


def _validate(title: str, notice_type: str, publish_scope: str, body: str,
              elderly_summary: str, is_urgent: int, publish_time: str,
              expire_at: str) -> str:
    """字段校验（发布/定时前调用）。返回错误信息，空串表示通过。"""
    if not (title or "").strip():
        return "通知标题不能为空"
    if len(title.strip()) > 50:
        return "通知标题最多 50 字"
    if notice_type not in NOTICE_TYPES:
        return "通知类型不合法"
    if publish_scope not in PUBLISH_SCOPES:
        return "发布范围不合法"
    if not (body or "").strip():
        return "通知正文不能为空"
    if len(body.strip()) > 5000:
        return "通知正文最多 5000 字"
    if is_urgent and not (elderly_summary or "").strip():
        return "紧急通知必须填写老年端播报摘要"
    if (elderly_summary or "").strip() and len(elderly_summary.strip()) > 30:
        return "老年端播报摘要最多 30 字"
    if publish_time and expire_at and expire_at < publish_time:
        return "下架时间不能早于发布时间"
    # 敏感词拦截（标题 + 正文 + 老年摘要）
    try:
        from utils.text import check_sensitive
        for _f in (title, body, elderly_summary):
            hit, word = check_sensitive(_f or "")
            if hit:
                return f"内容包含敏感词「{word}」，请修改后重试"
    except Exception:
        pass
    return ""


def _check_pin_quota(conn, notice_id: int) -> bool:
    """普通置顶是否还有名额（最多 3 条）。"""
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM notices WHERE status=? AND is_pinned=1 "
        "AND is_urgent=0 AND id != ?",
        (STATUS_PUBLISHED, notice_id),
    ).fetchone()
    return (row["c"] if row else 0) < MAX_PIN_COUNT


def _scope_user_ids(conn, n: dict) -> tuple[list[int], list[int]]:
    """按发布范围算该通知覆盖的（居民 id 列表, 老年用户 id 列表）。

    范围规则：
      全体居民 → 所有启用的居民 + 老年用户（所有端可见）；
      指定小区 → community 命中 targets 的居民/老年用户；
      指定楼栋 → community|building 命中 targets 的居民/老年用户；
      仅老年端 → 只有老年用户。
    """
    scope = n.get("publish_scope") or "全体居民"
    targets = set(json.loads(n.get("scope_target_json") or "[]"))
    rows = conn.execute(
        "SELECT id, community, building, role FROM user_profile "
        "WHERE is_active=1 AND role IN ('resident','elderly')"
    ).fetchall()
    residents: list[int] = []
    elderly: list[int] = []
    for r in rows:
        community = (r["community"] or "").strip()
        building = (r["building"] or "").strip()
        if scope == "全体居民":
            ok = True
        elif scope == "仅老年端":
            ok = r["role"] == "elderly"
        elif scope == "指定小区":
            ok = community in targets
        elif scope == "指定楼栋":
            ok = f"{community}|{building}" in targets
        else:
            ok = True
        if not ok:
            continue
        (residents if r["role"] == "resident" else elderly).append(r["id"])
    return residents, elderly


def _notice_visible_to_user(n: dict, me: dict) -> bool:
    """单条通知对某个用户（id/community/building/role）是否可见。"""
    scope = n.get("publish_scope") or "全体居民"
    role = me.get("role", "resident")
    if scope == "仅老年端":
        return role == "elderly"
    if scope == "全体居民":
        return role in ("resident", "elderly")
    targets = set(json.loads(n.get("scope_target_json") or "[]"))
    community = (me.get("community") or "").strip()
    building = (me.get("building") or "").strip()
    if scope == "指定小区":
        return community in targets
    if scope == "指定楼栋":
        return f"{community}|{building}" in targets
    return True


# ---- 创建 / 修改 / 删除草稿 ----

def create_notice(title: str, notice_type: str, publish_scope: str, body: str,
                  elderly_summary: str = "", publisher: str = "",
                  is_pinned: int = 0, is_urgent: int = 0,
                  expire_at: str = "", attachment_json: str = "[]",
                  scope_target_json: str = "[]", actor: str = "负责人") -> int:
    """新建通知（保存为草稿）。返回通知 ID。非法类型/敏感词创建时即拦截（0 表示拒绝）。"""
    _ensure_columns()
    if not (title or "").strip():
        raise ValueError("通知标题不能为空")
    # 创建时即校验类型与敏感词（spec：发布前检测，创建草稿早拦避免垃圾数据）
    if notice_type not in NOTICE_TYPES:
        return 0
    if publish_scope not in PUBLISH_SCOPES:
        return 0
    try:
        from utils.text import check_sensitive
        for _f in (title, body, elderly_summary):
            _hit, _w = check_sensitive(_f or "")
            if _hit:
                return 0
    except Exception:
        pass
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO notices (title, notice_type, publish_scope, body, elderly_summary, "
            "publisher, is_pinned, is_urgent, expire_at, attachment_json, "
            "scope_target_json, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (title.strip(), notice_type, publish_scope, body, elderly_summary,
             publisher, 1 if is_pinned else 0, 1 if is_urgent else 0,
             _ts(expire_at), attachment_json or "[]", scope_target_json or "[]",
             STATUS_DRAFT),
        )
        notice_id = cur.lastrowid
        conn.commit()
    log_activity(actor, "新建通知", "notice", notice_id, title.strip(),
                 module=MODULE, after_value=STATUS_DRAFT,
                 detail=f"类型：{notice_type}；范围：{publish_scope}")
    return notice_id


def update_notice(notice_id: int, actor: str, expected_updated_at: str = "",
                  **fields) -> tuple[bool, str]:
    """编辑通知（仅草稿 / 待发布可编辑）。fields 为可更新字段。

    已发布不能直接修改，只能下架重新发布。
    expected_updated_at：乐观锁（spec 十.13 并发冲突防护）——传入打开编辑时的
    更新时间，若已被他人修改则拒绝并提示刷新，避免覆盖。
    """
    _ensure_columns()
    allowed = {"title", "notice_type", "publish_scope", "scope_target_json", "body",
               "elderly_summary", "is_pinned", "is_urgent", "expire_at",
               "attachment_json", "publisher"}
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notices WHERE id=?", (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        n = dict(row)
        if n["status"] not in (STATUS_DRAFT, STATUS_PENDING):
            return False, f"当前状态「{n['status']}」不能编辑，请下架后重新发布"
        # 乐观锁：传入的 expected_updated_at 与当前不一致 → 并发冲突，拒绝覆盖
        if expected_updated_at and str(n.get("updated_at") or "") != str(expected_updated_at):
            return False, "该通知已被修改/操作，请刷新后重试"
        upd: dict = {k: v for k, v in fields.items() if k in allowed}
        if not upd:
            return False, "没有可更新的字段"
        # 合并后再校验（防止改坏必填项）
        merged = dict(n)
        for k, v in upd.items():
            merged[k] = v if k != "expire_at" else _ts(v)
        err = _validate(
            merged["title"], merged["notice_type"], merged["publish_scope"],
            merged["body"], merged["elderly_summary"], merged.get("is_urgent", 0),
            n.get("published_at") or n.get("scheduled_at") or _now(),
            merged.get("expire_at") or "",
        )
        if err:
            return False, err
        sets = ", ".join(f"{k}=?" for k in upd)
        args = [upd[k] for k in upd] + [notice_id]
        conn.execute(f"UPDATE notices SET {sets}, updated_at=CURRENT_TIMESTAMP WHERE id=?", args)
        conn.commit()
    changes = "；".join(f"{k}→{upd[k]}" for k in upd)
    log_activity(actor, "修改通知", "notice", notice_id, n["title"],
                 module=MODULE, before_value=n["status"], after_value=n["status"],
                 detail=changes)
    return True, ""


def delete_notice(notice_id: int, actor: str) -> tuple[bool, str]:
    """删除草稿（仅草稿）。"""
    _ensure_columns()
    with get_db() as conn:
        row = conn.execute("SELECT status, title FROM notices WHERE id=?", (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        if row["status"] != STATUS_DRAFT:
            return False, "只有草稿可以删除"
        conn.execute("DELETE FROM notices WHERE id=?", (notice_id,))
        conn.execute("DELETE FROM notice_reads WHERE notice_id=?", (notice_id,))
        conn.commit()
    log_activity(actor, "删除草稿", "notice", notice_id, row["title"],
                 module=MODULE, before_value=STATUS_DRAFT, after_value="已删除")
    return True, ""


# ---- 立即发布 / 定时发布 ----

def publish_notice(notice_id: int, user_id: int, actor: str,
                   confirm_urgent: bool = False) -> tuple[bool, str]:
    """立即发布。紧急通知必须二次确认（confirm_urgent=True）且发布人有权限。"""
    _ensure_columns()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notices WHERE id=?", (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        n = dict(row)
        if n["status"] not in (STATUS_DRAFT, STATUS_PENDING):
            return False, f"当前状态「{n['status']}」不能发布"
        if n["is_urgent"]:
            if not can_publish_urgent(user_id):
                log_activity(actor, "发布紧急通知被拦截", "notice", notice_id, n["title"],
                             module=MODULE, detail="无紧急通知发布权限")
                return False, "您无权发布紧急通知"
            if not confirm_urgent:
                return False, "紧急通知必须二次确认后才能发布"
        now = _now()
        err = _validate(n["title"], n["notice_type"], n["publish_scope"], n["body"],
                        n["elderly_summary"], n["is_urgent"], now, n["expire_at"] or "")
        if err:
            return False, err
        # 发布前附件复检：附件路径必须真实存在，缺失则拒绝发布并提示（spec：附件保存失败不能静默发布）
        try:
            _att_missing = []
            for _a in json.loads(n.get("attachment_json") or "[]"):
                _p = (_a or {}).get("path") or ""
                if _p and not _resolve_upload_path(_p):
                    _att_missing.append((_a or {}).get("name") or _p)
            if _att_missing:
                return False, f"附件文件缺失（{'、'.join(_att_missing[:3])}），请重新上传附件后再发布"
        except Exception:
            pass
        # 紧急通知自动置顶（不受 3 条限制）；普通置顶要查名额
        is_pinned = 1 if n["is_urgent"] else n["is_pinned"]
        if is_pinned and not n["is_urgent"] and not _check_pin_quota(conn, notice_id):
            return False, f"普通置顶最多 {MAX_PIN_COUNT} 条，请先取消其他置顶"
        # 紧急通知默认有效期 7 天（未填时）
        expire_at = n["expire_at"] or ""
        if n["is_urgent"] and not expire_at:
            expire_at = (datetime.now() + timedelta(days=URGENT_DEFAULT_EXPIRE_DAYS)).strftime(_TS_FMT)
        conn.execute(
            "UPDATE notices SET status=?, published_at=?, is_pinned=?, "
            "pinned_at=CASE WHEN ?=1 THEN ? ELSE pinned_at END, "
            "expire_at=?, scheduled_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (STATUS_PUBLISHED, now, is_pinned, is_pinned, now if is_pinned else None,
             expire_at, notice_id),
        )
        conn.commit()

    action = "发布紧急通知" if n["is_urgent"] else "发布通知"
    log_activity(actor, action, "notice", notice_id, n["title"], module=MODULE,
                 before_value=n["status"], after_value=STATUS_PUBLISHED,
                 detail=f"类型：{n['notice_type']}；范围：{n['publish_scope']}；发布人：{actor}")
    return True, ""


def schedule_notice(notice_id: int, scheduled_at, user_id: int, actor: str,
                    confirm_urgent: bool = False) -> tuple[bool, str]:
    """定时发布：设 scheduled_at，状态 → 待发布，到点由 process_due_notices 自动发布。

    紧急通知定时同样需要二次确认 + 白名单权限（确认发生在定时那一刻）。
    """
    _ensure_columns()
    scheduled = _ts(scheduled_at)
    if not scheduled:
        return False, "请选择定时发布时间"
    if scheduled <= _now():
        return False, "定时发布时间必须晚于当前时间"
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notices WHERE id=?", (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        n = dict(row)
        if n["status"] not in (STATUS_DRAFT, STATUS_PENDING):
            return False, f"当前状态「{n['status']}」不能设置定时发布"
        if n["is_urgent"]:
            if not can_publish_urgent(user_id):
                log_activity(actor, "定时发布紧急通知被拦截", "notice", notice_id, n["title"],
                             module=MODULE, detail="无紧急通知发布权限")
                return False, "您无权发布紧急通知"
            if not confirm_urgent:
                return False, "紧急通知必须二次确认后才能定时发布"
        err = _validate(n["title"], n["notice_type"], n["publish_scope"], n["body"],
                        n["elderly_summary"], n["is_urgent"], scheduled, n["expire_at"] or "")
        if err:
            return False, err
        # 紧急定时：预约置顶（到点自动置顶）；普通定时置顶同样查名额（预约时占坑）
        is_pinned = 1 if n["is_urgent"] else n["is_pinned"]
        if is_pinned and not n["is_urgent"] and not _check_pin_quota(conn, notice_id):
            return False, f"普通置顶最多 {MAX_PIN_COUNT} 条，请先取消其他置顶"
        conn.execute(
            "UPDATE notices SET status=?, scheduled_at=?, is_pinned=?, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (STATUS_PENDING, scheduled, is_pinned, notice_id),
        )
        conn.commit()
    action = "定时发布紧急通知" if n["is_urgent"] else "定时发布"
    log_activity(actor, action, "notice", notice_id, n["title"], module=MODULE,
                 before_value=n["status"], after_value=STATUS_PENDING,
                 detail=f"定时时间：{scheduled}；类型：{n['notice_type']}")
    return True, ""


def withdraw_notice(notice_id: int, actor: str) -> tuple[bool, str]:
    """撤回待发布定时通知 → 草稿（不需二次确认，但必须留痕）。"""
    _ensure_columns()
    with get_db() as conn:
        row = conn.execute("SELECT status, title, scheduled_at FROM notices WHERE id=?",
                           (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        if row["status"] != STATUS_PENDING:
            return False, f"当前状态「{row['status']}」不支持撤回"
        conn.execute(
            "UPDATE notices SET status=?, scheduled_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (STATUS_DRAFT, notice_id),
        )
        conn.commit()
    log_activity(actor, "撤回定时发布", "notice", notice_id, row["title"], module=MODULE,
                 before_value=STATUS_PENDING, after_value=STATUS_DRAFT,
                 detail=f"原定时时间：{row['scheduled_at'] or ''}")
    return True, ""


def process_due_notices() -> int:
    """系统定时发布：到点的待发布通知自动发布。

    失败自动重试一次，仍失败标记「发布失败」并留痕（通知负责人手动处理）。
    返回本次成功发布条数。
    """
    _ensure_columns()
    with get_db() as conn:
        due = conn.execute(
            "SELECT * FROM notices WHERE status=? AND scheduled_at IS NOT NULL "
            "AND scheduled_at <= datetime('now','localtime')",
            (STATUS_PENDING,),
        ).fetchall()
    published = 0
    for row in due:
        n = dict(row)
        ok, msg = _auto_publish(n)
        if not ok:
            ok2, msg2 = _auto_publish(n)
            if ok2:
                ok, msg = True, msg2
            else:
                with get_db() as conn:
                    conn.execute("UPDATE notices SET status=? WHERE id=?",
                                 (STATUS_FAILED, n["id"]))
                    conn.commit()
                log_activity("系统", "定时发布失败", "notice", n["id"], n["title"],
                             module=MODULE, before_value=STATUS_PENDING,
                             after_value=STATUS_FAILED,
                             detail=f"自动重试仍失败：{msg or msg2}")
                _log.warning("定时发布失败（已标记）：notice #%s %s", n["id"], msg2)
        if ok:
            published += 1
    return published


def _auto_publish(n: dict) -> tuple[bool, str]:
    """把一条待发布通知置为已发布（系统自动执行）。"""
    now = _now()
    err = _validate(n["title"], n["notice_type"], n["publish_scope"], n["body"],
                    n["elderly_summary"], n["is_urgent"], n["scheduled_at"] or now,
                    n["expire_at"] or "")
    if err:
        return False, err
    # 发布范围失效校验（spec 十.10：定时到达时目标小区/楼栋已失效 → 阻止发布标记「范围失效」通知负责人）
    try:
        import json as _json
        targets = _json.loads(n.get("scope_target_json") or "[]")
        if n["publish_scope"] in ("指定小区", "指定楼栋") and targets:
            from data.db_core import get_db as _gdb
            with _gdb() as conn:
                _tbl = "communities" if n["publish_scope"] == "指定小区" else "buildings"
                _tbl_exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (_tbl,)
                ).fetchone()
                _exist = None
                if _tbl_exists:
                    _rows = conn.execute(f"SELECT name AS n FROM {_tbl}").fetchall()
                    _exist = {r["n"] for r in _rows}
            # 表不存在（未启用范围管理）→ 跳过校验；表存在才判失效
            if _exist is not None:
                _invalid = [t for t in targets if t not in _exist]
                if _invalid:
                    log_activity("系统", "定时发布范围失效", "notice", n["id"], n["title"],
                                 module=MODULE, before_value=STATUS_PENDING, after_value=STATUS_FAILED,
                                 detail=f"发布范围失效：{'、'.join(str(x) for x in _invalid[:5])}")
                    try:
                        from data.db_user import list_users
                        for u in list_users(role="grid"):
                            from data.db_notifications import create_notification
                            create_notification(u["id"], "notice",
                                                "⚠️ 定时通知发布范围失效",
                                                f"通知「{n['title'][:20]}」定时发布失败：发布范围（{'、'.join(str(x) for x in _invalid[:5])}）已失效。")
                    except Exception:
                        pass
                    return False, "发布范围失效"
    except Exception:
        pass
    is_pinned = 1 if n["is_urgent"] else n["is_pinned"]
    expire_at = n["expire_at"] or ""
    if n["is_urgent"] and not expire_at:
        expire_at = (datetime.now() + timedelta(days=URGENT_DEFAULT_EXPIRE_DAYS)).strftime(_TS_FMT)
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE notices SET status=?, published_at=?, is_pinned=?, "
                "pinned_at=CASE WHEN ?=1 THEN ? ELSE pinned_at END, "
                "expire_at=?, scheduled_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (STATUS_PUBLISHED, now, is_pinned, is_pinned,
                 now if is_pinned else None, expire_at, n["id"]),
            )
            conn.commit()
    except Exception as e:  # 数据库异常也走重试/失败标记
        _log.exception("定时发布 SQL 失败：notice #%s", n["id"])
        return False, str(e)
    log_activity("系统", "定时发布", "notice", n["id"], n["title"], module=MODULE,
                 before_value=STATUS_PENDING, after_value=STATUS_PUBLISHED,
                 detail=f"定时时间：{n['scheduled_at'] or ''}；类型：{n['notice_type']}")
    return True, ""


# ---- 下架 / 置顶 / 有效期 ----

def take_down_notice(notice_id: int, reason: str, actor: str) -> tuple[bool, str]:
    """下架已发布通知。原因必填（二次确认由 UI 层弹窗完成）。

    下架后居民端/老年端不再显示，后台保留记录与统计；
    下架时立即从待弹窗队列移除（弹窗查询实时过滤状态，天然生效）。
    """
    _ensure_columns()
    if not (reason or "").strip():
        return False, "下架原因必填"
    with get_db() as conn:
        row = conn.execute("SELECT status, title FROM notices WHERE id=?", (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        if row["status"] != STATUS_PUBLISHED:
            return False, f"当前状态「{row['status']}」不支持下架"
        conn.execute(
            "UPDATE notices SET status=?, down_reason=?, is_pinned=0, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (STATUS_DOWN, reason.strip(), notice_id),
        )
        conn.commit()
    log_activity(actor, "下架通知", "notice", notice_id, row["title"], module=MODULE,
                 before_value=STATUS_PUBLISHED, after_value=STATUS_DOWN,
                 detail=f"下架原因：{reason.strip()}；操作人：{actor}")
    return True, ""


def set_pinned(notice_id: int, pinned: bool, actor: str) -> tuple[bool, str]:
    """普通通知手动置顶/取消置顶（最多 3 条；紧急通知置顶由系统管理）。"""
    _ensure_columns()
    with get_db() as conn:
        row = conn.execute("SELECT status, title, is_urgent FROM notices WHERE id=?",
                           (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        if row["status"] != STATUS_PUBLISHED:
            return False, "只有已发布通知可以置顶"
        if row["is_urgent"]:
            return False, "紧急通知自动置顶，无需手动操作"
        if pinned and not _check_pin_quota(conn, notice_id):
            return False, f"普通置顶最多 {MAX_PIN_COUNT} 条，请先取消其他置顶"
        now = _now()
        conn.execute(
            "UPDATE notices SET is_pinned=?, pinned_at=CASE WHEN ?=1 THEN ? ELSE pinned_at END, "
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (1 if pinned else 0, 1 if pinned else 0, now if pinned else None, notice_id),
        )
        conn.commit()
    action = "置顶通知" if pinned else "取消置顶"
    log_activity(actor, action, "notice", notice_id, row["title"], module=MODULE,
                 before_value="未置顶" if pinned else "置顶",
                 after_value="置顶" if pinned else "未置顶")
    return True, ""


def update_urgent_expire(notice_id: int, expire_at, user_id: int, actor: str) -> tuple[bool, str]:
    """修改紧急通知有效期（仅指定负责人；修改留痕；只影响修改后仍未读的用户）。"""
    _ensure_columns()
    exp = _ts(expire_at)
    if not exp:
        return False, "请选择有效期"
    if exp <= _now():
        return False, "有效期必须晚于当前时间"
    with get_db() as conn:
        row = conn.execute("SELECT status, title, is_urgent, expire_at FROM notices WHERE id=?",
                           (notice_id,)).fetchone()
        if row is None:
            return False, "通知不存在"
        if not row["is_urgent"]:
            return False, "只有紧急通知可以设置有效期"
        if row["status"] not in (STATUS_PUBLISHED, STATUS_PENDING):
            return False, f"当前状态「{row['status']}」不支持修改有效期"
        if not can_publish_urgent(user_id):
            log_activity(actor, "修改紧急通知有效期被拦截", "notice", notice_id, row["title"],
                         module=MODULE, detail="无紧急通知管理权限")
            return False, "您无权修改紧急通知有效期"
        conn.execute("UPDATE notices SET expire_at=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                     (exp, notice_id))
        conn.commit()
    log_activity(actor, "修改紧急通知有效期", "notice", notice_id, row["title"], module=MODULE,
                 before_value=row["expire_at"] or "", after_value=exp)
    return True, ""


def process_expired() -> dict:
    """系统自动处理：
      1. 普通置顶超 7 天自动取消（取消后需手动重新置顶留痕）；
      2. 紧急通知到期自动取消置顶和弹窗（状态仍「已发布」，保留列表）。
    返回 {"pins": n, "urgent": n}。
    """
    _ensure_columns()
    pins: list = []
    urgents: list = []
    with get_db() as conn:
        pins = conn.execute(
            "SELECT id, title FROM notices WHERE is_urgent=0 AND is_pinned=1 "
            "AND status=? AND pinned_at IS NOT NULL "
            "AND pinned_at <= datetime('now','localtime', ?)",
            (STATUS_PUBLISHED, f"-{PIN_EXPIRE_DAYS} days"),
        ).fetchall()
        urgents = conn.execute(
            "SELECT id, title FROM notices WHERE is_urgent=1 AND is_pinned=1 "
            "AND status=? AND expire_at IS NOT NULL "
            "AND expire_at <= datetime('now','localtime')",
            (STATUS_PUBLISHED,),
        ).fetchall()
        for r in list(pins) + list(urgents):
            try:
                conn.execute("UPDATE notices SET is_pinned=0 WHERE id=?", (r["id"],))
            except Exception:
                # 失败自动重试一次（spec 补充：仍失败标记「自动取消失败」通知负责人手动取消）
                try:
                    conn.execute("UPDATE notices SET is_pinned=0 WHERE id=?", (r["id"],))
                except Exception as e:  # noqa: BLE001
                    _log.warning("自动取消置顶失败（notice #%s）：%s", r["id"], e)
                    try:
                        conn.execute(
                            "INSERT INTO exception_log (module, error, detail) "
                            "VALUES ('通知', ?, ?)",
                            (f"自动取消置顶失败 notice#{r['id']}", str(e)[:200]),
                        )
                    except Exception:
                        pass
        conn.commit()
    for r in pins:
        log_activity("系统", "普通置顶超期自动取消", "notice", r["id"], r["title"],
                     module=MODULE, before_value="置顶", after_value="取消置顶")
    for r in urgents:
        log_activity("系统", "紧急通知到期自动取消置顶", "notice", r["id"], r["title"],
                     module=MODULE, before_value="置顶", after_value="取消置顶",
                     detail="到期自动取消置顶和弹窗，保留列表")
    return {"pins": len(pins), "urgent": len(urgents)}


def _resolve_upload_path(rel_path: str) -> str | None:
    """校验附件相对路径真实存在（发布前复检）。"""
    try:
        from utils.uploads import resolve_path
        return resolve_path(rel_path)
    except Exception:
        return None


def run_auto_tasks() -> dict:
    """一键跑定时发布 + 到期清理 + 草稿清理（供定时器/入口统一调用）。"""
    published = process_due_notices()
    expired = process_expired()
    cleaned = clean_notice_drafts(days=7)
    return {"published": published, **expired, "draft_cleaned": cleaned}


def clean_notice_drafts(days: int = 7) -> int:
    """清理超过 N 天的通知草稿（spec：草稿保存 7 天，超期删除）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title FROM notices WHERE status=? "
            "AND created_at < datetime('now', ?)",
            (STATUS_DRAFT, f"-{days} days"),
        ).fetchall()
        for r in rows:
            conn.execute("DELETE FROM notices WHERE id=?", (r["id"],))
        conn.commit()
    for r in rows:
        log_activity("系统", "通知草稿超期清理", "notice", r["id"], r["title"] or "",
                     module=MODULE, before_value="草稿", after_value="已删除(超期)",
                     detail=f"草稿超过 {days} 天未处理，系统自动清理")
    return len(rows)


# ---- 已读 / 统计 ----

def mark_notice_read(notice_id: int, client_type: str, user_id: int) -> bool:
    """标记已读（居民端 resident / 老年端 elderly 分开记；幂等）。

    已读判定口径：居民点详情或紧急弹窗点「我知道了」；老人点大字版详情或弹窗点「我知道了」。
    """
    if client_type not in ("resident", "elderly"):
        return False
    if not notice_id or not user_id:
        return False
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO notice_reads (notice_id, client_type, user_id) "
            "VALUES (?, ?, ?)",
            (notice_id, client_type, user_id),
        )
        conn.commit()
    return True


def get_notice_read_stats(notice_id: int) -> dict:
    """已读/未读统计（只显示总量，不追踪具体谁）。

    返回 {"resident_total", "resident_read", "resident_unread",
          "elderly_total", "elderly_read", "elderly_unread"}。
    范围外用户不计入；下架后本函数不再被 UI 调用即保持固化。
    统计异常时记录异常日志并返回全零（保留最近一次正确统计由调用方缓存）。
    """
    try:
        _ensure_columns()
        with get_db() as conn:
            row = conn.execute("SELECT * FROM notices WHERE id=?", (notice_id,)).fetchone()
            if row is None:
                return {}
            n = dict(row)
            residents, elderly = _scope_user_ids(conn, n)
            r_read = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM notice_reads "
                "WHERE notice_id=? AND client_type='resident'", (notice_id,),
            ).fetchone()["c"]
            e_read = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM notice_reads "
                "WHERE notice_id=? AND client_type='elderly'", (notice_id,),
            ).fetchone()["c"]
        r_total, e_total = len(residents), len(elderly)
        return {
            "resident_total": r_total,
            "resident_read": min(r_read, r_total),
            "resident_unread": max(r_total - r_read, 0),
            "elderly_total": e_total,
            "elderly_read": min(e_read, e_total),
            "elderly_unread": max(e_total - e_read, 0),
        }
    except Exception as e:  # noqa: BLE001
        # spec 十.9：统计异常时记录异常日志，返回零值（不阻塞页面）
        _log.warning("已读统计异常 notice#%s：%s", notice_id, e)
        try:
            from data.db_notifications import log_exception
            log_exception(MODULE, f"已读统计异常 notice#{notice_id}: {e}")
        except Exception:
            pass
        return {"resident_total": 0, "resident_read": 0, "resident_unread": 0,
                "elderly_total": 0, "elderly_read": 0, "elderly_unread": 0}


def get_notice_unread_count(client_type: str, user_id: int) -> int:
    """用户当前未读广播通知数（居民端/老年端分开）。"""
    try:
        return sum(1 for n in get_visible_notices(client_type, user_id, limit=1000)
                   if not n.get("is_read"))
    except Exception:
        _log.debug("计算未读广播通知数失败", exc_info=True)
        return 0


def get_active_urgent_notices(client_type: str, user_id: int) -> list[dict]:
    """当前对该用户有效的未读紧急通知（按发布时间倒序）。

    多条同时有效时 UI 只弹最新一条，点「我知道了」后自动弹下一条；
    下架/到期后自动从结果中消失。
    """
    now = _now()
    out = []
    for n in get_visible_notices(client_type, user_id, limit=1000):
        if not n.get("is_urgent") or n.get("is_read"):
            continue
        exp = n.get("expire_at") or ""
        if exp and exp <= now:
            continue
        out.append(n)
    # 多条紧急通知：按发布时间倒序（spec：新发的优先弹），无发布时间用创建时间
    out.sort(key=lambda x: ((x.get("published_at") or x.get("created_at") or ""), -(x.get("id") or 0)),
             reverse=True)
    return out


# ---- 查询 ----

def get_notice(notice_id: int) -> dict | None:
    _ensure_columns()
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notices WHERE id=?", (notice_id,)).fetchone()
        return dict(row) if row else None


def get_notices(notice_type: str | None = None, status: str | None = None,
                publish_scope: str | None = None, keyword: str | None = None,
                limit: int = 200) -> list[dict]:
    """负责人端查询：按类型/状态/范围/关键词筛选，紧急优先、新的在前。"""
    _ensure_columns()
    q = "SELECT * FROM notices WHERE 1=1"
    args: list = []
    if notice_type:
        q += " AND notice_type=?"
        args.append(notice_type)
    if status:
        q += " AND status=?"
        args.append(status)
    if publish_scope:
        q += " AND publish_scope=?"
        args.append(publish_scope)
    if keyword:
        q += " AND (title LIKE ? OR body LIKE ?)"
        like = f"%{keyword}%"
        args += [like, like]
    q += " ORDER BY is_urgent DESC, status='已发布' DESC, "
    q += "COALESCE(published_at, scheduled_at, created_at) DESC, id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def get_notices_with_stats(notice_type: str | None = None, status: str | None = None,
                           publish_scope: str | None = None, keyword: str | None = None,
                           limit: int = 200) -> list[dict]:
    """负责人端列表：每条通知附带已读统计。"""
    out = []
    for n in get_notices(notice_type, status, publish_scope, keyword, limit):
        n["stats"] = get_notice_read_stats(n["id"])
        out.append(n)
    return out


def get_visible_notices(client_type: str, user_id: int, notice_type: str | None = None,
                        keyword: str | None = None, limit: int = 100) -> list[dict]:
    """居民端/老年端可见的已发布广播通知（按发布范围过滤 + 已读标记）。

    排序：紧急置顶 → 普通置顶 → 普通，同级按发布时间倒序。
    """
    _ensure_columns()
    with get_db() as conn:
        me_row = conn.execute(
            "SELECT id, community, building, role FROM user_profile WHERE id=? AND is_active=1",
            (user_id,),
        ).fetchone()
        if not me_row:
            return []
        me = dict(me_row)
        read_ids = {r["notice_id"] for r in conn.execute(
            "SELECT notice_id FROM notice_reads WHERE client_type=? AND user_id=?",
            (client_type, user_id)).fetchall()}
        rows = conn.execute(
            "SELECT * FROM notices WHERE status=? ORDER BY id DESC LIMIT 500",
            (STATUS_PUBLISHED,),
        ).fetchall()
    out = []
    for r in rows:
        n = dict(r)
        if not _notice_visible_to_user(n, me):
            continue
        if notice_type and n.get("notice_type") != notice_type:
            continue
        if keyword and keyword not in (n.get("title") or "") and keyword not in (n.get("body") or ""):
            continue
        n["is_read"] = 1 if n["id"] in read_ids else 0
        out.append(n)
        if len(out) >= limit:
            break
    # 先按发布时间倒序（定时发布场景下，发布时间晚的新在前，不用创建 id）
    out.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)
    # 稳定排序：紧急置顶 > 普通置顶 > 其他（同优先级内保持时间倒序）
    out.sort(key=lambda x: (
        0 if (x.get("is_urgent") and x.get("is_pinned")) else
        1 if x.get("is_pinned") else 2,
    ))
    return out


def get_notice_timeline(notice_id: int) -> list[dict]:
    """通知留痕时间线（最近在前），供负责人详情页查看。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE target_type='notice' AND target_id=? "
            "ORDER BY created_at DESC LIMIT 50",
            (notice_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def export_notices_csv(notice_type: str | None = None, status: str | None = None,
                       publish_scope: str | None = None, keyword: str | None = None,
                       actor: str = "负责人") -> tuple[str, str]:
    """导出通知列表 + 已读统计（不含正文和附件）。返回 (csv 内容, 文件名)。

    导出异常时记异常日志并返回空（不中断页面）。
    """
    import csv
    import io

    try:
        notices = get_notices_with_stats(notice_type, status, publish_scope, keyword, limit=500)
    except Exception as e:  # noqa: BLE001
        _log.warning("通知导出数据查询失败：%s", e)
        try:
            from data.db_notifications import log_exception
            log_exception(MODULE, f"通知导出失败: {e}")
        except Exception:
            pass
        return "", ""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["通知编号", "标题", "类型", "发布范围", "发布时间", "状态",
                     "居民端已读", "居民端未读", "老年端已读", "老年端未读"])
    for n in notices:
        st_ = n.get("stats") or {}
        writer.writerow([
            n["id"], n.get("title", ""), n.get("notice_type", ""),
            n.get("publish_scope", ""),
            n.get("published_at") or n.get("scheduled_at") or "",
            n.get("status", ""),
            st_.get("resident_read", 0), st_.get("resident_unread", 0),
            st_.get("elderly_read", 0), st_.get("elderly_unread", 0),
        ])
    fname = f"通知列表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    log_activity(actor, "导出通知列表", "notice", None, "", module=MODULE,
                 detail=f"导出 {len(notices)} 条（不含正文附件）；操作人：{actor}")
    return buf.getvalue(), fname
