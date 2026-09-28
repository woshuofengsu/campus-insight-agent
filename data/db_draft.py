# data/db_draft.py
"""草稿内容持久化服务（P1-A5-02，适配项目零第三方依赖）。

报修/提案草稿完整落库：user_id + draft_type 唯一，重启后完整恢复，
提交成功/取消删除，7 天过期清理。复用 utils/crypto 可选加密。
"""
import json
import logging

from data.database import get_db

_log = logging.getLogger(__name__)

DRAFT_TYPES = ("work_order_draft", "proposal_draft")


def save_draft(user_id: int, draft_type: str, content: dict, step: str = "",
               source_session: str = "", source_text: str = "") -> None:
    """保存/更新草稿（upsert）。

    `source_session` / `source_text`（卡8 / v3 卡4）：这条草稿**是哪场对话、从哪句话来的**。
    为什么必须有：以前草稿只有内容，回填时无法判断"它属不属于当前这件事"，
    于是出现了"旧草稿顶替新报修"（老人新说一件事，确认卡里还带着上一件事的描述）。
    现在回填侧可以据此判断是否属于同一场对话，并把不匹配的旧草稿**如实展示成"上次没提交的"**。
    """
    if draft_type not in DRAFT_TYPES:
        return
    with get_db() as conn:
        conn.execute(
            "INSERT INTO draft_contents (user_id, draft_type, content_json, current_step, "
            "source_session, source_text) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, draft_type) DO UPDATE SET "
            "content_json=excluded.content_json, current_step=excluded.current_step, "
            "source_session=excluded.source_session, source_text=excluded.source_text, "
            "updated_at=CURRENT_TIMESTAMP",
            (user_id, draft_type, json.dumps(content or {}, ensure_ascii=False), step or "",
             source_session or "", (source_text or "")[:120]),
        )
        conn.commit()


def load_draft(user_id: int, draft_type: str) -> dict | None:
    """读取草稿；无则 None。返回 {content, step, updated_at, source_session, source_text}。"""
    if draft_type not in DRAFT_TYPES:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT content_json, current_step, updated_at, source_session, source_text "
            "FROM draft_contents WHERE user_id=? AND draft_type=?", (user_id, draft_type),
        ).fetchone()
    if not row:
        return None
    try:
        content = json.loads(row["content_json"] or "{}")
    except (ValueError, TypeError):
        content = {}
    return {"content": content, "step": row["current_step"] or "",
            "updated_at": row["updated_at"] or "",
            "source_session": (row["source_session"] if "source_session" in row.keys() else "") or "",
            "source_text": (row["source_text"] if "source_text" in row.keys() else "") or ""}


def delete_draft(user_id: int, draft_type: str) -> None:
    """删除草稿（提交成功/取消/主动清除）。"""
    with get_db() as conn:
        conn.execute("DELETE FROM draft_contents WHERE user_id=? AND draft_type=?",
                     (user_id, draft_type))
        conn.commit()


def clean_drafts(days: int = 7) -> int:
    """清理超过 N 天的草稿（调度器调用）。"""
    with get_db() as conn:
        cur = conn.execute(
            f"DELETE FROM draft_contents WHERE updated_at < datetime('now', '-{days} days')")
        conn.commit()
        return cur.rowcount
