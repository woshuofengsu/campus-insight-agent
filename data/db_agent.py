# -*- coding: utf-8 -*-
"""Agent 统一入口模块数据层：历史对话 + Agent 留痕。

- agent_dialogs：三端用户与 Agent 的对话历史（居民最近 5 条可删；老年 5 条大字不可删；负责人不保留）。
- agent_logs：Agent 留痕（模块来源=Agent，保存 7 天；负责人可查可导出，居民/老人不可见）。
"""
import logging
from datetime import datetime, timedelta

from data.database import get_db

MODULE = "Agent"

_log = logging.getLogger(__name__)

RETENTION_DAYS = 7


def _now() -> datetime:
    return datetime.now()


# ---------------------------------------------------------------------------
# 历史对话
# ---------------------------------------------------------------------------

def add_dialog(user_id: int, role: str, text: str, is_bot: int = 0,
               intent: str = "", related_id: int | None = None) -> int:
    """记录一条对话（用户消息或 Agent 回复）。返回 id。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO agent_dialogs (user_id, role, text, is_bot, intent, related_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, role, (text or "")[:500], is_bot, intent or "", related_id),
        )
        conn.commit()
        return cur.lastrowid


def get_dialogs(user_id: int, role: str, limit: int = 5) -> list[dict]:
    """查用户最近对话（居民/老年端用）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM agent_dialogs WHERE user_id=? AND role=? "
            "ORDER BY id DESC LIMIT ?", (user_id, role, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]  # 时间正序


def delete_dialog(dialog_id: int, user_id: int) -> bool:
    """居民删除自己的历史对话（归属校验）。"""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM agent_dialogs WHERE id=? AND user_id=?", (dialog_id, user_id))
        conn.commit()
        return cur.rowcount > 0


def clear_dialogs(user_id: int, role: str) -> int:
    """清空某用户历史（居民端删除全部）。"""
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM agent_dialogs WHERE user_id=? AND role=?", (user_id, role))
        conn.commit()
        return cur.rowcount


def clean_dialogs(days: int = 30) -> int:
    """清理超过 N 天的对话（调度器调用）。"""
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM agent_dialogs WHERE created_at < datetime('now', '-{days} days')")
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Agent 留痕
# ---------------------------------------------------------------------------

def log_agent(user_id: int | None, role: str, user_input: str, intent: str,
              routed: str = "", status: str = "成功", error: str = "",
              corrected: str = "", related_id: int | None = None) -> int:
    """Agent 留痕（模块来源=Agent，保存 7 天）。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO agent_logs (user_id, role, user_input, corrected, intent, routed, "
            "status, error, related_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, role, (user_input or "")[:500], (corrected or "")[:500],
             (intent or "")[:100], (routed or "")[:200], status, (error or "")[:500],
             related_id),
        )
        conn.commit()
        return cur.lastrowid


def get_agent_logs(role: str = "", intent: str = "", status: str = "",
                   keyword: str = "", limit: int = 200) -> list[dict]:
    """负责人查 Agent 留痕（按模块来源=Agent、时间、状态筛选）。"""
    q = "SELECT * FROM agent_logs WHERE 1=1"
    args: list = []
    if role:
        q += " AND role=?"
        args.append(role)
    if intent:
        q += " AND intent=?"
        args.append(intent)
    if status:
        q += " AND status=?"
        args.append(status)
    if keyword:
        q += " AND (user_input LIKE ? OR routed LIKE ? OR error LIKE ?)"
        kw = f"%{keyword}%"
        args += [kw, kw, kw]
    q += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with get_db() as conn:
        rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]


def clean_agent_logs(days: int = RETENTION_DAYS) -> int:
    """清理超过 7 天的 Agent 留痕（调度器调用）。"""
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM agent_logs WHERE created_at < datetime('now', '-{days} days')")
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# Agent 会话落库（v31：重启不丢、多实例不串线）
# ---------------------------------------------------------------------------

def save_session(session_id: str, user_id: int, role: str, state: dict) -> None:
    """保存会话状态（upsert）。state 为可 JSON 序列化 dict。"""
    import json as _json
    with get_db() as conn:
        conn.execute(
            "INSERT INTO agent_sessions (session_id, user_id, role, state_json) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET state_json=excluded.state_json, "
            "user_id=excluded.user_id, role=excluded.role, updated_at=CURRENT_TIMESTAMP",
            (session_id, user_id, role, _json.dumps(state or {}, ensure_ascii=False)),
        )
        conn.commit()


def load_session(session_id: str) -> dict | None:
    """读取会话状态；不存在返回 None。"""
    import json as _json
    with get_db() as conn:
        row = conn.execute(
            "SELECT state_json FROM agent_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    if not row or not row["state_json"]:
        return None
    try:
        return _json.loads(row["state_json"])
    except (ValueError, TypeError):
        return None


def delete_session(session_id: str) -> None:
    """删除会话（取消/结束）。"""
    with get_db() as conn:
        conn.execute("DELETE FROM agent_sessions WHERE session_id=?", (session_id,))
        conn.commit()


def clean_sessions(days: int = 30) -> int:
    """清理超过 N 天的会话（调度器调用）。"""
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM agent_sessions WHERE updated_at < datetime('now', '-{days} days')")
        conn.commit()
        return cur.rowcount


# ---------------------------------------------------------------------------
# 人工处理包（无缝转人工，v32）
# ---------------------------------------------------------------------------

def create_handoff(session_id: str, user_id: int, role: str, intent: str,
                   reason: str, package: dict) -> int:
    """创建人工处理包（转人工待办）。"""
    import json as _json
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO agent_handoffs (session_id, user_id, role, intent, reason, package_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, user_id, role, intent, reason or "",
             _json.dumps(package or {}, ensure_ascii=False)),
        )
        conn.commit()
        return cur.lastrowid


def list_handoffs(status: str = "", limit: int = 50) -> list[dict]:
    """负责人端人工处理包列表（含上下文摘要）。"""
    import json as _json
    with get_db() as conn:
        q = "SELECT * FROM agent_handoffs WHERE 1=1"
        args: list = []
        if status:
            q += " AND status=?"
            args.append(status)
        q += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = conn.execute(q, args).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                pkg = _json.loads(d.get("package_json") or "{}")
            except (ValueError, TypeError):
                pkg = {}
            d["package"] = pkg
            d["original_input"] = pkg.get("original_input", "")
            out.append(d)
        return out


def resolve_handoff(handoff_id: int, actor: str = "负责人") -> bool:
    """负责人处理完成（关闭处理包）。"""
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE agent_handoffs SET status='已处理' WHERE id=? AND status='待处理'",
            (handoff_id,))
        conn.commit()
        return cur.rowcount > 0
