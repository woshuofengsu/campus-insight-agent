# data/db_settings.py
"""`settings` 表的**按租户读写入口**（多租户 B7）。

**为什么需要**：`settings` 是一张 key/value 表，历史上所有键都是**全局一份**——
两个社区共用同一套联动阈值/政策匹配阈值。多租户真隔离到业务数据之后，
"配置"这层还留着跨社区共用的尾巴：朝阳把高温联动阈值调低，海淀的提醒也跟着变。

**键的约定**：`<键>@<社区名>` 为**社区专属值**，裸键 `<键>` 为**全局默认值**。
读取顺序：社区专属 → 全局默认；都没有 → 调用方给的默认值。
    get_setting("match_threshold", tenant="朝阳试点社区")
      ├─ 先找 "match_threshold@朝阳试点社区"
      └─ 没有 → 找 "match_threshold"（全局）→ 再没有 → default
写入只写社区专属键（不污染全局），这样"某个社区改配置"永远不会影响别的社区。

**fail-closed 的口径**：`tenant` 传空（身份没解析出社区）时**只读全局默认**，不报错——
因为"读全局默认"是一个明确、可解释的行为，而"猜一个社区"不是。
"""
import json
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 社区键分隔符：社区名是中文，`@` 不会与之冲突（社区名里出现 `@` 会在下面被拒绝）
_SEP = "@"


def setting_key(key: str, tenant: str | None = None) -> str:
    """把逻辑键解析成实际的 `settings.key`（社区专属 → `键@社区`；否则裸键）。"""
    k = (key or "").strip()
    if not k:
        raise ValueError("settings 键不能为空")
    from utils.tenant import normalize_tenant
    t = normalize_tenant(tenant)
    if not t:
        return k
    if _SEP in t:
        # 社区名里带分隔符会让键解析产生歧义（"a@b@c" 归属不明）→ 明确拒绝，不猜
        raise ValueError(f"社区名 {t!r} 含分隔符 {_SEP!r}，无法用作设置键后缀")
    return f"{k}{_SEP}{t}"


def get_setting(key: str, tenant: str | None = None, default: str | None = None) -> str | None:
    """读设置：**社区专属值优先，缺省回落全局值**，再缺省返回 `default`。"""
    tkey = setting_key(key, tenant)
    gkey = setting_key(key, None)
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT key, value FROM settings WHERE key IN (?, ?)", (tkey, gkey)).fetchall()
        got = {r["key"]: r["value"] for r in rows}
        if tkey in got and got[tkey] is not None:
            return got[tkey]
        if gkey in got and got[gkey] is not None:
            return got[gkey]
    except Exception as e:  # noqa: BLE001 — 读不到就回落默认值，绝不因此中断业务
        _log.warning("读取设置失败 key=%s tenant=%s（回落默认值）：%s", key, tenant, e)
    return default


def set_setting(key: str, value: str, tenant: str | None = None) -> str:
    """写设置：upsert 到**社区专属键**（`tenant` 为空则写全局键）。返回实际写入的键。"""
    tkey = setting_key(key, tenant)
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM settings WHERE key=?", (tkey,)).fetchone()
        if exists:
            conn.execute("UPDATE settings SET value=? WHERE key=?", (value, tkey))
        else:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (tkey, value))
        conn.commit()
    return tkey


def get_setting_json(key: str, tenant: str | None = None, default=None):
    """读 JSON 设置（社区优先 → 全局 → default）。解析失败按默认值处理并 warning。"""
    raw = get_setting(key, tenant=tenant, default=None)
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (ValueError, TypeError) as e:
        _log.warning("设置 %s（tenant=%s）不是合法 JSON，按默认值处理：%s", key, tenant, e)
        return default


def set_setting_json(key: str, value, tenant: str | None = None) -> str:
    return set_setting(key, json.dumps(value, ensure_ascii=False), tenant=tenant)


def list_setting_keys(prefix: str = "") -> list[str]:
    """列出设置的键（排查/审计用）：能看到"哪些社区覆盖了哪些键"。"""
    try:
        with get_db() as conn:
            rows = conn.execute("SELECT key FROM settings ORDER BY key").fetchall()
    except Exception as e:  # noqa: BLE001
        _log.warning("列举设置键失败：%s", e)
        return []
    return [r["key"] for r in rows if r["key"].startswith(prefix)]


__all__ = ["setting_key", "get_setting", "set_setting", "get_setting_json",
           "set_setting_json", "list_setting_keys"]
