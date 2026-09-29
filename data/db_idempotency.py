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

⚠️ **顺序调用通过 ≠ 并发安全**（2026-09-29 首批八条浏览器旅程第 4 条实测踩到）：
原来只有"先查 `recall`、后写 `remember`"两步，两个**并发**请求会**同时查不到**，
于是各建一张工单（实测：连点两下 → 库里两张单、两个工单号）。
所以现在多了一步**原子占位**（`begin`）：`idempotency_keys` 有 `PRIMARY KEY (scope, key)`，
`INSERT OR IGNORE` 在同一时刻只有一个线程能成功，另一个必然拿到"正在提交中"——
只能等结果或如实告知，**绝不再执行一次业务**。
"""
import json
import logging
import re
import time

from data.database import get_db

_log = logging.getLogger(__name__)

MAX_KEY_LEN = 64
_KEY_RE = re.compile(r"^[A-Za-z0-9_\-]{8,%d}$" % MAX_KEY_LEN)

# 占位标记：result_json 为空串 = "这个 key 已经被领走，但还没有结果"
_PENDING = ""
# 占位多久算"上一次崩在中间"（超过就允许重新领，避免一个坏请求把编号永久锁死）
STALE_SECONDS = 90


def valid_key(key: str) -> bool:
    """token 是否合法（长度 8–64，只允许字母数字下划线短横 —— 避免把任意字符串写进主键）。"""
    return bool(key) and bool(_KEY_RE.match(str(key)))


def _result_of(raw) -> dict | None:
    """解析结果摘要；**空串/空对象都算"还没有结果"**（占位不是结果）。"""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "{}":
        return None
    try:
        d = json.loads(text)
    except (ValueError, TypeError):
        return None
    return d if isinstance(d, dict) and d else None


def _row(scope: str, key: str):
    try:
        with get_db() as conn:
            return conn.execute(
                "SELECT user_id, result_json FROM idempotency_keys WHERE scope=? AND key=?",
                (scope, str(key))).fetchone()
    except Exception as e:  # noqa: BLE001 — 查不动就当作"没做过"，但必须留痕
        _log.warning("幂等键查询失败 scope=%s key=%s：%s", scope, key, e)
        return None


def state(scope: str, key: str, user_id: int | None = None) -> tuple[str, dict | None]:
    """**只读**地看这个 key 现在什么状态：`("done", 结果)` / `("pending", None)` / `("none", None)`。

    「正在提交中」必须能被如实区分出来（并**不是**"没做过"）：
    否则老人在并发提交的窗口里点「查一下」，会被告知"这次没有提交成功，可以再点一次"——
    而那一下很可能建出第二张单。
    """
    if not scope or not valid_key(key):
        return "none", None
    row = _row(scope, key)
    if not row:
        return "none", None
    if user_id is not None and int(row["user_id"] or 0) not in (0, int(user_id)):
        _log.warning("幂等键 %s/%s 属于用户 %s，被用户 %s 请求 —— 不暴露结果",
                     scope, key, row["user_id"], user_id)
        return "none", None
    d = _result_of(row["result_json"])
    return ("done", d) if d else ("pending", None)


def recall(scope: str, key: str, user_id: int | None = None) -> dict | None:
    """查这个 key 是否已经做成过；返回上次的结果摘要（dict），**没做成/正在做**都返回 None。

    `user_id` 给了就校验归属：**别人不能拿你的 key 来探测/复用你的结果**（越权防护）。
    """
    return state(scope, key, user_id)[1]


def begin(scope: str, key: str, user_id: int | None = None,
          stale_seconds: int = STALE_SECONDS) -> tuple[str, dict | None]:
    """**原子地**开始一次幂等操作。

    返回：
      · `("done", 结果)`    —— 之前已经做成过，直接复用结果（**不要再执行一次业务**）；
      · `("pending", None)` —— 另一个请求正在做同一件事，等它的结果，**不要再执行一次业务**；
      · `("new", None)`     —— 这件事归你办，办完调 `remember`，办不成调 `release`；
      · `("unknown", None)` —— **占位没能做成（数据库忙/锁/异常）**，无法确认这件事是否已被别人领走。
        调用方**必须停止业务写入**，如实告诉用户"提交状态未知，可以按编号核对"，并且**不许**再建对象。

    ⚠️ 2026-09-29（外部评审第十一轮指出，确认属实并已修）：原来占位抛异常时返回 `("new", None)`
    —— 注释写着"宁可重复也不能阻断报修"。这个取舍是**错的**：
    占位失败恰恰最容易发生在"库忙/锁冲突"这种**并发场景**，而那正是幂等要保护的时刻；
    此时放行 = 在最需要保护的时候把它关掉（实测可复现：让占位语句抛异常，同编号能建出两张单）。
    现在改成 fail-closed：拿不到"这件事归我办"的结论，就不办。
    """
    if not scope or not valid_key(key):
        return "new", None
    plain = str(key)
    st, d = state(scope, plain, user_id)
    if st != "none":
        return st, d
    row = _row(scope, plain)
    if row and user_id is not None and int(row["user_id"] or 0) not in (0, int(user_id)):
        # 别人的编号（但已经有结果）：不复用也不动别人的行 —— 由调用方按新事处理
        return "new", None
    try:
        with get_db() as conn:
            # 上一次崩在中间的占位要能自愈：过期就放掉，否则这个编号永远"正在提交中"
            conn.execute(
                "DELETE FROM idempotency_keys WHERE scope=? AND key=? "
                "AND (result_json IS NULL OR TRIM(result_json)='') "
                "AND created_at < datetime('now', ?)",
                (scope, plain, f"-{int(stale_seconds)} seconds"))
            cur = conn.execute(
                "INSERT OR IGNORE INTO idempotency_keys (scope, key, user_id, result_json) "
                "VALUES (?, ?, ?, ?)",
                (scope, plain, int(user_id or 0), _PENDING))
            conn.commit()
        if (cur.rowcount or 0) == 1:
            return "new", None
    except Exception as e:  # noqa: BLE001 — **fail-closed**：占位没做成就不许往下办（见 docstring）
        _log.warning("幂等键占位失败（已按 fail-closed 拒绝继续办理）scope=%s key=%s：%s",
                     scope, plain, e)
        return "unknown", None
    # 被别的线程/进程抢先占位了：读它的结果，读不到就是"正在做"
    return state(scope, plain, user_id)


def wait_result(scope: str, key: str, user_id: int | None = None,
                timeout: float = 8.0, interval: float = 0.2) -> dict | None:
    """等另一个请求把结果写出来（并发提交时用）；超时返回 None（**不代替它执行**）。"""
    deadline = time.time() + max(0.0, float(timeout))
    while True:
        r = recall(scope, key, user_id)
        if r is not None:
            return r
        if time.time() >= deadline:
            return None
        time.sleep(interval)


def remember(scope: str, key: str, user_id: int | None, result: dict) -> None:
    """记下"这个 key 做成了什么"。

    两条规矩：① 只填**空占位**（把 `begin` 领的那一格写上结果）；
    ② 已经有了结果的 key **不被覆盖**（先到先得，避免后来的请求改写既有事实）。
    """
    if not scope or not valid_key(key):
        return
    payload = json.dumps(result or {}, ensure_ascii=False)
    plain = str(key)
    try:
        with get_db() as conn:
            cur = conn.execute(
                "UPDATE idempotency_keys SET result_json=?, user_id=? WHERE scope=? AND key=? "
                "AND (result_json IS NULL OR TRIM(result_json)='')",
                (payload, int(user_id or 0), scope, plain))
            if not (cur.rowcount or 0):
                conn.execute(
                    "INSERT OR IGNORE INTO idempotency_keys (scope, key, user_id, result_json) "
                    "VALUES (?, ?, ?, ?)",
                    (scope, plain, int(user_id or 0), payload))
            conn.commit()
    except Exception as e:  # noqa: BLE001 — 记不上不影响本次结果，但必须留痕（否则重试会重复建单）
        _log.warning("幂等键写入失败（重试可能重复提交）scope=%s key=%s：%s", scope, plain, e)


def release(scope: str, key: str, user_id: int | None = None) -> None:
    """放弃占位：业务**没做成**时调用，让用户能用同一个编号重试（成功过的结果不动）。"""
    if not scope or not valid_key(key):
        return
    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM idempotency_keys WHERE scope=? AND key=? AND user_id=? "
                "AND (result_json IS NULL OR TRIM(result_json)='')",
                (scope, str(key), int(user_id or 0)))
            conn.commit()
    except Exception as e:  # noqa: BLE001
        _log.warning("幂等键释放失败（该编号可能暂时不可重试）scope=%s key=%s：%s", scope, key, e)


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
