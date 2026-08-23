# api_routes/messages.py
"""站内消息中心路由（通知/工单/提案等系统消息，从 api_web.py 拆出）。"""
from fastapi import APIRouter, Request

from api_routes.deps import _ok, _user

router = APIRouter(prefix="/api/web/messages", tags=["messages"])


@router.get("")
def web_messages(request: Request, limit: int = 50):
    """当前用户站内消息（type=notification/issue/sos/policy 等）。"""
    from data.db_core import get_db
    u = _user(request)
    uid = u.get("uid")
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, type AS ntype, title, content, is_read, related_id, created_at "
            "FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (uid, limit),
        ).fetchall()
    return _ok([dict(r) for r in rows])


@router.post("/{mid}/read")
def web_message_read(mid: int, request: Request):
    """标记消息已读。"""
    from data.db_core import get_db
    u = _user(request)
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?", (mid, u.get("uid")))
        conn.commit()
    return _ok({"message_id": mid}, "已读")
