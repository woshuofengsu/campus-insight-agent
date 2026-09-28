# -*- coding: utf-8 -*-
"""通知待重试队列（卡9：把通知**投递**与业务**提交**拆开）。

**要解决的问题**：通知是"现发现写"的，写失败就只能留一行 warning ——
"业务成功了、但该收到的人没收到"这种事**看不到、也补不回来**。
现在失败的投递进这张表排队，调度器定期补发；补发不了会标记"放弃"并记异常。

三条硬口径（与本项目"不许假装成功"一致）：
  ① 业务事实**永远不等**通知：`enqueue()` 只做"投递失败后登记"，绝不影响调用方；
  ② 补发保留**真实业务编号**（`related_id`），所以补发的通知仍指向同一张工单/提案；
  ③ 漏发**可观测**：`pending_count()` / `stats()` 能直接看出还欠多少条、失败原因是什么。
"""
import logging

from data.database import get_db

_log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
MODULE = "通知投递"


def enqueue(user_id: int, type_: str, title: str, content: str = "",
            related_id: int | None = None, error: str = "") -> int:
    """把一条发失败的通知放进待重试队列。返回队列 id（失败返回 0，但**不抛异常**）。"""
    if not user_id:
        return 0
    tenant = ""
    try:
        from utils.tenant import tenant_of_user
        tenant = tenant_of_user(user_id) or ""
    except Exception as e:  # noqa: BLE001 — 租户解析失败不影响入队
        _log.warning("待重试通知的社区解析失败（user=%s）：%s", user_id, e)
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO notification_outbox (user_id, type, title, content, related_id, "
                "status, attempts, last_error, next_try_at, tenant_id) "
                # next_try_at 立刻可发：**第一次补发由调度器下一个 tick 完成**（≤60 秒），
                # 只有"补发再失败"时才按指数退避推后（见 flush）
                "VALUES (?, ?, ?, ?, ?, '待发送', 0, ?, datetime('now'), ?)",
                (int(user_id), type_ or "", title or "", content or "", related_id,
                 (error or "")[:200], tenant))
            conn.commit()
            return cur.lastrowid or 0
    except Exception as e:  # noqa: BLE001 — 队列也写不进就只能记异常（绝不再往上抛）
        _log.warning("待重试通知入队失败（业务不受影响，但这条通知会丢）：user=%s %s", user_id, e)
        return 0


def pending_count() -> int:
    """还欠多少条没发出去（给健康检查/大屏观测用）。"""
    try:
        with get_db() as conn:
            row = conn.execute(
                "SELECT COUNT(*) c FROM notification_outbox WHERE status='待发送'").fetchone()
        return int(row["c"] or 0)
    except Exception as e:  # noqa: BLE001
        _log.warning("待重试通知计数失败：%s", e)
        return 0


def stats() -> dict:
    """队列概况：待发送 / 已发送 / 放弃 各多少条，最近一次失败原因。"""
    out = {"pending": 0, "sent": 0, "gave_up": 0, "last_error": ""}
    try:
        with get_db() as conn:
            for r in conn.execute(
                    "SELECT status, COUNT(*) c FROM notification_outbox GROUP BY status"):
                key = {"待发送": "pending", "已发送": "sent", "放弃": "gave_up"}.get(r["status"])
                if key:
                    out[key] = int(r["c"] or 0)
            row = conn.execute(
                "SELECT last_error FROM notification_outbox WHERE status='放弃' "
                "ORDER BY id DESC LIMIT 1").fetchone()
        out["last_error"] = (row["last_error"] if row else "") or ""
    except Exception as e:  # noqa: BLE001
        _log.warning("待重试通知统计失败：%s", e)
    return out


def _deliver(row: dict) -> None:
    """把队列里的一条写进 `notifications` 并标记已发送。

    ⚠️ 这是补发流程里**唯一的副作用点**，单独抽出来是为了能对它做**故障注入测试**
    （在它上面打桩就能验证"补发失败要退避、试满要放弃"，而不必去 mock 整个数据库连接）。
    """
    with get_db() as conn:
        conn.execute(
            "INSERT INTO notifications (user_id, type, title, content, related_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (row["user_id"], row["type"], row["title"], row["content"], row["related_id"]))
        conn.execute(
            "UPDATE notification_outbox SET status='已发送', attempts=attempts+1, "
            "last_error='' WHERE id=?", (row["id"],))
        conn.commit()


def flush(limit: int = 50) -> dict:
    """补发待重试通知（调度器调用）。

    · 成功 → 写入 `notifications` 并标记 `已发送`；
    · 失败 → `attempts += 1`，并把下次尝试推后（指数退避：1/2/4/8/16 分钟）；
    · 试满 `MAX_ATTEMPTS` → 标记 `放弃` 并写异常日志（让"漏发"留下证据，而不是消失）。
    返回 `{"sent": n, "failed": n, "gave_up": n}`。
    """
    res = {"sent": 0, "failed": 0, "gave_up": 0}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM notification_outbox WHERE status='待发送' "
                "AND (next_try_at IS NULL OR next_try_at <= datetime('now')) "
                "ORDER BY id LIMIT ?", (max(1, min(int(limit or 50), 500)),)).fetchall()
    except Exception as e:  # noqa: BLE001
        _log.warning("读取待重试通知失败：%s", e)
        return res

    for r in rows:
        row = dict(r)
        try:
            _deliver(row)
            res["sent"] += 1
        except Exception as e:  # noqa: BLE001 — 补发失败要退避重试，不能装作成功
            attempts = int(row.get("attempts") or 0) + 1
            give_up = attempts >= MAX_ATTEMPTS
            backoff = min(2 ** attempts, 16)
            try:
                with get_db() as conn:
                    if give_up:
                        conn.execute(
                            "UPDATE notification_outbox SET status='放弃', attempts=?, "
                            "last_error=? WHERE id=?", (attempts, str(e)[:200], row["id"]))
                    else:
                        conn.execute(
                            "UPDATE notification_outbox SET attempts=?, last_error=?, "
                            "next_try_at=datetime('now', ?) WHERE id=?",
                            (attempts, str(e)[:200], f"+{backoff} minutes", row["id"]))
                    conn.commit()
            except Exception as e2:  # noqa: BLE001
                _log.warning("待重试通知状态更新失败（会重复尝试）：outbox=%s %s", row["id"], e2)
            if give_up:
                res["gave_up"] += 1
                _log.warning("通知补发放弃（试满 %s 次）：outbox=%s user=%s title=%s",
                             MAX_ATTEMPTS, row["id"], row["user_id"], row["title"])
                try:
                    from data.db_notifications import log_exception
                    log_exception(MODULE, f"通知补发放弃 outbox#{row['id']}：{str(e)[:120]}")
                except Exception as e3:  # noqa: BLE001
                    _log.warning("补发放弃的异常留痕失败：%s", e3)
            else:
                res["failed"] += 1
    if res["sent"] or res["failed"] or res["gave_up"]:
        _log.info("通知补发：成功 %s / 失败 %s / 放弃 %s", res["sent"], res["failed"], res["gave_up"])
    return res


def clean_finished(days: int = 30) -> int:
    """清理已发送/放弃超过 N 天的队列行（调度器调用）。"""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "DELETE FROM notification_outbox WHERE status IN ('已发送','放弃') "
                "AND created_at < datetime('now', ?)", (f"-{int(days)} days",))
            conn.commit()
            return cur.rowcount or 0
    except Exception as e:  # noqa: BLE001
        _log.warning("清理通知队列失败：%s", e)
        return 0
