# agent/closed_loop.py
"""Closed-loop integrity check — detect unresolved issues and stale proposals.

Extracted from CampusAgent._check_closed_loop().  After each agent response,
scans the database for the current user's open governance loops and appends
a gentle reminder note when applicable.
"""
import logging
from datetime import datetime

_log = logging.getLogger(__name__)


def check_closed_loop(memory, user_input: str, response: str) -> str:
    """Check for open governance loops and return a gentle reminder note.

    Detects:
      - User's pending/processing issues
      - Recently resolved issues (same-day)
      - User's unresponded proposals with ≥5 supporters
      - Campus-wide stale issues (>7 days)

    Args:
        memory: MemoryManager instance for author resolution.
        user_input: The original user message (unused, for future context).
        response: The agent's response text (unused, for future context).

    Returns:
        A markdown-formatted reminder string, or "" if nothing to report.
    """
    try:
        from data.database import get_issues, get_proposals, get_db
        from agent.helpers import get_author_identifier

        author = get_author_identifier(memory)
        if not author:
            return ""

        all_issues = get_issues(limit=200)
        my_pending = [
            i for i in all_issues
            if i.get("author") == author and i.get("status") in ("待处理", "处理中")
        ]
        my_resolved = [
            i for i in all_issues
            if i.get("author") == author and i.get("status") == "已解决"
        ]

        notes: list[str] = []

        if my_pending:
            pending_titles = "、".join(
                f"#{i['id']}「{i['title'][:15]}」({i['status']})"
                for i in my_pending[:3]
            )
            extra = f"等 {len(my_pending)} 件" if len(my_pending) > 3 else ""
            notes.append(
                f"📋 你还有 {len(my_pending)} 件待处理工单：{pending_titles}{extra}。"
                f"输入「查看我的工单」追踪进度"
            )

        if my_resolved and not my_pending:
            today = datetime.now().strftime("%Y-%m-%d")
            recent_resolved = [
                i for i in my_resolved
                if (i.get("resolved_at") or "")[:10] == today
            ]
            if recent_resolved:
                notes.append(
                    f"✅ 你上报的 {len(recent_resolved)} 个问题今天已解决！"
                    f"感谢你的参与 ✨"
                )

        all_props = get_proposals(limit=200)
        my_props_unresponded = [
            p for p in all_props
            if p.get("author") == author
            and p.get("status") in ("讨论中",)
            and p.get("supporter_count", 0) >= 5
        ]
        if my_props_unresponded:
            prop = my_props_unresponded[0]
            notes.append(
                f"💡 你的提案 #{prop['id']}「{prop['title'][:20]}」已有 "
                f"{prop['supporter_count']} 人附议，输入「查看我的提案」了解进展"
            )

        with get_db() as conn:
            stale = conn.execute(
                "SELECT COUNT(*) as cnt FROM campus_issues "
                "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
            ).fetchone()
        if stale and stale["cnt"] >= 3:
            notes.append(
                f"⚠️ 全校有 {stale['cnt']} 件工单超过 7 天未处理，建议关注积压问题"
            )

        if not notes:
            return ""

        return "\n\n---\n\n🔄 **闭环追踪**\n\n" + "\n\n".join(notes)

    except Exception as e:
        _log.warning("Closed-loop check failed (non-fatal): %s", e)
        return ""
