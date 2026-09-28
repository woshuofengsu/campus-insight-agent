# -*- coding: utf-8 -*-
"""幂等键（卡8 / v3 卡4）：同一个"提交意图"重复请求只产生一个结果。

**为什么需要**：网络重试、用户连点、"点了没反应又点一次"都会让同一件事走两遍提交
—— 结果就是**重复工单**（老人那边看到两条一样的报修，网格员那边派两次单）。
前端无法可靠判断"上一次到底成没成"，所以这个判断必须落在服务端：
客户端在**准备提交时生成一次 token**，重试沿用同一个 token，服务端据此认出重复请求。

设计取舍：
  · 表只存**结果摘要**（`result_json`，如 `{"issue_id": 123}`），不存业务正文 ——
    不把幂等表变成第二个业务库，也就不存在"两份数据不一致"的问题；
  · 记的是"这个 key 已经做成了什么"，所以**重复请求直接复用上次的结果**（而不是报错）；
  · `scope` 区分业务，避免不同业务的 key 撞车；调用方传进来的 token 长度/字符有上限校验；
  · 查不到就是"没做过"，调用方正常执行。
"""
import json
import logging
import re

from data.database import get_db

_log = logging.getLogger(__name__)

MAX_KEY_LEN = 64
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,%d}$" % MAX_KEY_LEN)


def valid_key(key: str) -> bool:
    """token 是否合法（长度 8–64，只允许字母数字下划线短横 —— 避免把任意字符串写进主键）。"""
    return bool(key) and bool(_KEY_RE.match(str(key)))


def recall(scope: str, key: str, user_id: int | None = None) -> dict | None:
    """查这个 key 是否已经做成过；返回上次的结果摘要（dict），没做过返回 None。

    `user_id` 给了就校验归属：**别人不能拿你的 key 来探测/复用你的结果**（越权防护）。
    """
    if not scope or not valid_key(key):
        return None
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT user_id, result_json FROM idempotency_keys WHERE scope=? AND key=?",
                (scope, str(key))).fetchone()
    except Exception as e:  # noqa: BLE001 — 查不动就当作"没做过"，但必须留痕
        _log.warning("幂等键查询失败 scope=%s key=%s：%s", scope, key, e)
        return None
    if not row:
        return None
    if user_id is not None and int(row["user_id"] or 0) not in (0, int(user_id)):
        _log.warning("幂等键 %s/%s 属于用户 %s，被用户 %s 请求 —— 拒绝复用",
                     scope, key, row["user_id"], user_id)
        return None
    try:
        return json.loads(row["result_json"] or "{}")
    except (ValueError, TypeError):
        return {}


def remember(scope: str, key: str, user_id: int | None, result: dict) -> None:
    """记下"这个 key 做成了什么"。重复写同一个 key 不会覆盖已有结果（先到先得）。"""
    if not scope or not valid_key(key):
        return
    try:
        with get_db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys (scope, key, user_id, result_json) "
                "VALUES (?, ?, ?, ?)",
                (scope, str(key), int(user_id or 0),
                 json.dumps(result or {}, ensure_ascii=False)))
            conn.commit()
    except Exception as e:  # noqa: BLE001 — 记不上不影响本次结果，但必须留痕（否则重试会重复建单）
        _log.warning("幂等键写入失败（重试可能重复提交）scope=%s key=%s：%s", scope, key, e)


def clean_keys(days: int = 7) -> int:
    """清理过期幂等键（调度器调用）。"""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "DELETE FROM idempotency_keys WHERE created_at < datetime('now', ?)",
                (f"-{int(days)} days",))
            conn.commit()
            return cur.rowcount or 0
    except Exception as e:  # noqa: BLE001
        _log.warning("幂等键清理失败：%s", e)
        return 0
