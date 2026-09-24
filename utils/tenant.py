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


__all__ = ["LEGACY_TENANT_VALUES", "normalize_tenant", "is_valid_tenant", "tenant_of_user",
           "tenant_of_user_uncached", "clear_cache", "default_community", "stamp_tenant",
           "tenant_clause"]
