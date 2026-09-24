# utils/tenant.py
"""租户（社区）解析统一入口 —— 多租户真隔离的地基。

**租户键 = 社区名**（`user_profile.community` 的真值，如「海淀小区」「朝阳试点社区」）。
为什么不用行政区：同区两个社区会互相看见——这是否决行政区当租户键的硬理由。

三条硬约定（对应 `docs/spec/多租户改造清单-明细.md`）：
1. **写入侧必须落租户**：v41 的教训是"只加列 + 回填，业务代码从不写入"，结果新数据租户为空、
   隔离静默退化成"空租户"。所有社区范围数据的 INSERT 都要带 `tenant_id`；
2. **读取侧 fail-closed**：拿着空租户去查，**返回空集**，绝不回落成"查全部"；
3. **租户只从服务端身份来**：绝不接受前端传的 tenant/community 作为过滤依据
   （前端 `store.user.community` 只用于显示）。

本模块只做解析与归一化，不碰具体表的 SQL——表的过滤在各 `data/db_*.py` 里，
由调用方显式传 `tenant=`（**不给默认值**，忘了传会直接 TypeError 而不是悄悄返回全量）。
"""
import logging
import threading

_log = logging.getLogger(__name__)

# 历史遗留的"伪租户值"（v41 回填成了行政区，与社区名不同域）——迁移时要归一化掉
LEGACY_TENANT_VALUES = {"海淀区", "朝阳区", "北京市", "default", "campus", "社区"}

_cache_lock = threading.Lock()
_user_tenant_cache: dict[int, str] = {}


def normalize_tenant(value) -> str:
    """归一化租户值：去空白；历史行政区值视为无效（返回空串）。

    无效值**不报错**，只回落成空串——由调用方按 fail-closed 处理（空租户 → 查不到数据），
    这样"数据归档错了"表现为"看不见"，而不是"看见别人的"。
    """
    text = str(value or "").strip()
    if not text or text in LEGACY_TENANT_VALUES:
        return ""
    return text


def is_valid_tenant(value) -> bool:
    return bool(normalize_tenant(value))


def tenant_of_user(uid) -> str:
    """按用户 id 查其社区（租户）。查不到/无社区 → 空串（fail-closed）。"""
    try:
        key = int(uid or 0)
    except (TypeError, ValueError):
        return ""
    if key <= 0:
        return ""
    with _cache_lock:
        if key in _user_tenant_cache:
            return _user_tenant_cache[key]
    tenant = ""
    try:
        from data.db_core import get_db
        with get_db() as conn:
            row = conn.execute("SELECT community FROM user_profile WHERE id=?", (key,)).fetchone()
        if row:
            tenant = normalize_tenant(row["community"])
    except Exception:  # noqa: BLE001 — 查不到不等于放行，返回空串（fail-closed）
        _log.warning("解析用户租户失败 uid=%s（按空租户处理，不会放行全量）", key, exc_info=True)
    with _cache_lock:
        if len(_user_tenant_cache) > 500:
            _user_tenant_cache.clear()
        _user_tenant_cache[key] = tenant
    return tenant


def tenant_of_user_uncached(uid) -> str:
    """不走缓存（迁移/测试用；避免缓存掩盖刚写入的社区变更）。"""
    try:
        key = int(uid or 0)
    except (TypeError, ValueError):
        return ""
    if key <= 0:
        return ""
    from data.db_core import get_db
    with get_db() as conn:
        row = conn.execute("SELECT community FROM user_profile WHERE id=?", (key,)).fetchone()
    return normalize_tenant(row["community"]) if row else ""


def clear_cache() -> None:
    """清租户缓存（用户社区变更、测试隔离用）。"""
    with _cache_lock:
        _user_tenant_cache.clear()


def default_community() -> str:
    """兜底社区（历史无归属数据归档用）。默认取 config.DEFAULT_COMMUNITY。"""
    try:
        import config
        return normalize_tenant(getattr(config, "DEFAULT_COMMUNITY", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def all_tenants() -> list[str]:
    """列出系统里**真实存在**的社区名（去重、已归一化）。

    用途：系统级定时任务（没有"当前用户"可依）要"按社区各跑一遍"时用它枚举——
    例如天气联动按每个社区自己的阈值判定（见 `data/db_health_content.trigger_weather_linkage`）。
    空值/历史行政区值一律不返回：拿空社区去查是 fail-closed（查不到数据），
    所以这里宁可少枚举，也不给调用方一个无法解释的空租户。
    """
    try:
        from data.db_core import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT community FROM user_profile "
                "WHERE community IS NOT NULL AND community != ''").fetchall()
    except Exception as e:  # noqa: BLE001 — 枚举失败返回空表，调用方按"没有社区"处理
        _log.warning("枚举社区失败（按空表处理）：%s", e)
        return []
    out, seen = [], set()
    for r in rows:
        t = normalize_tenant(r["community"])
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return sorted(out)


def tenant_clause(tenant, args: list, *, self_scoped: bool = False, column: str = "tenant_id"):
    """读取侧租户过滤的统一入口（fail-closed，三条硬约定）。

    返回：
      - `""`            → 不需要追加租户过滤（tenant 未给且已给自身范围）；
      - `" AND {column}=?"` → 需要过滤（args 已追加归一化后的合法租户）；
      - `None`          → 空租户，调用方应**直接返回空集**（绝不回落成全量）。

    三条硬约定：
      1. tenant 是合法社区名 → 只查该租户（AND tenant_id=?）；
      2. tenant 是空串 → 返回空集（None 信号）；
      3. tenant 未给（None）且没有自身范围（self_scoped=False）→ 抛 ValueError，
         绝不悄悄查全库。
    """
    if tenant is None:
        if self_scoped:
            return ""
        raise ValueError(
            "跨用户列表/聚合查询必须显式提供 tenant=（社区名）或自身范围参数"
            "（reporter_id/user_id），拒绝无范围的全量查询"
        )
    t = normalize_tenant(tenant)
    if not t:
        return None
    args.append(t)
    return f" AND {column}=?"


# v48 迁移里做了租户隔离的表（**白名单**）。按 id 直取时表名要拼进 SQL，
# 只允许取自这里，杜绝把请求参数当表名用的注入面。
TENANT_TABLES = frozenset({
    "community_issues", "proposals", "notices", "health_consults", "policy_questions",
    "medication_reminders", "emergency_contacts", "emergency_calls", "agent_logs",
    "agent_handoffs", "agent_dialogs", "care_event_log", "weather_check_tasks",
})

# 每张租户表的归属人列（None = 无归属人，如通知/巡查任务）。用于"按归属人补判"。
TENANT_OWNER_COLUMN = {
    "community_issues": "reporter_id", "proposals": "reporter_id", "notices": None,
    "health_consults": "user_id", "policy_questions": "user_id",
    "medication_reminders": "user_id", "emergency_contacts": "user_id",
    "emergency_calls": "user_id", "agent_logs": "user_id", "agent_handoffs": "user_id",
    "agent_dialogs": "user_id", "care_event_log": "user_id", "weather_check_tasks": None,
}


def row_in_tenant(table: str, row_id, tenant) -> bool:
    """「按 id 直取」的授权判定：该行是否属于 tenant 这个社区（**fail-closed**）。

    为什么单独有这个函数：列表/聚合走 `tenant_clause`（SQL 过滤），但**详情与操作接口是
    按 id 直取单行的**——那条路径上没有 WHERE 可加，于是只校验角色（"是网格员就放行"）就会
    出现"列表里看不见、换个 id 就能读到别的社区"的越权（B6 实测复现过：
    朝阳网格员读到了海淀工单 #352 的全文）。

    返回 False 的全部情形（一律拒绝，绝不放行）：
      - 表名不在白名单（调用方写错，抛 ValueError 而不是静默放行）；
      - tenant 归一化后为空（身份没解析出社区）；
      - 行不存在；
      - 行自己没租户（历史脏数据，无法证明归属）。

    注意：本函数只回答"在不在同一社区"，**不替代**自身范围校验
    （居民看自己的单还要 `reporter_id == uid`），两者是"与"关系。
    """
    if table not in TENANT_TABLES:
        raise ValueError(f"row_in_tenant 收到非租户表：{table!r}（表名必须取自 TENANT_TABLES）")
    t = normalize_tenant(tenant)
    if not t:
        return False
    try:
        row_id = int(row_id)
    except (TypeError, ValueError):
        return False
    if row_id <= 0:
        return False
    from data.db_core import get_db
    try:
        with get_db() as conn:
            row = conn.execute(
                f"SELECT tenant_id FROM {table} WHERE id=?", (row_id,)).fetchone()
    except Exception:  # noqa: BLE001 — 查不动不等于放行
        _log.warning("按 id 校验租户失败 table=%s id=%s（拒绝访问）", table, row_id, exc_info=True)
        return False
    if not row:
        return False
    return normalize_tenant(row["tenant_id"]) == t


def stamp_tenant_value(conn, table: str, row_id, tenant) -> str:
    """给**没有归属人**的行盖章（写入侧统一入口）。

    用在"行不属于某个具体用户"的场景：极端天气巡查任务（预警源本身没有社区维度）、
    系统级通知等。与 `stamp_tenant` 的区别是直接给租户值，而不是按 owner 反查。
    同样**不写默认值**：传空就是空（读取侧 fail-closed 会让它谁都看不见，而不是谁都看得见）。
    """
    t = normalize_tenant(tenant)
    if row_id:
        conn.execute(f"UPDATE {table} SET tenant_id=? WHERE id=?", (t, row_id))
    return t


def stamp_tenant(conn, table: str, row_id, owner_id) -> str:
    """给刚插入的行**盖上租户章**（写入侧统一入口）。

    为什么用"插入后 UPDATE"而不是改每条 INSERT 的列清单：INSERT 语句有十几处、
    列清单各不相同，逐个改容易漏改或改错位置；统一在插入后按归属人盖章更不容易出错，
    代价只是一次额外的 UPDATE（同事务内）。

    ⚠️ 空租户也会照写（不写默认值）：读取侧是 fail-closed，写错租户的后果是"看不见"，
    而不是"看见别人的"。返回写入的租户值，便于调用方断言/日志。
    """
    tenant = tenant_of_user(owner_id)
    if row_id:
        conn.execute(f"UPDATE {table} SET tenant_id=? WHERE id=?", (tenant, row_id))
    return tenant


__all__ = ["LEGACY_TENANT_VALUES", "TENANT_TABLES", "TENANT_OWNER_COLUMN", "normalize_tenant",
           "is_valid_tenant", "tenant_of_user", "tenant_of_user_uncached", "clear_cache",
           "default_community", "all_tenants", "stamp_tenant", "stamp_tenant_value",
           "tenant_clause", "row_in_tenant"]
