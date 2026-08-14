# agent/closed_loop.py
"""闭环完整性检查 —— 找出没解决的问题和搁置的提案。

从 CommunityAgent._check_closed_loop() 拆出来的。每次 Agent 回复后，
扫一遍数据库看当前用户有没有没闭环的治理事项，有就追加一句温和提醒。
"""
import logging
from datetime import datetime

_log = logging.getLogger(__name__)


def check_closed_loop(memory, user_input: str, response: str) -> str:
    """查当前用户有没有没闭环的治理事项，返回一句温和的提醒。

    检查这些：
      - 用户待处理/处理中的工单
      - 今天刚解决的问题
      - 用户没被回应的提案（附议 ≥5 人）
      - 全社区超过 7 天没处理的积压工单

    Args:
        memory: MemoryManager 实例，用来解析作者身份。
        user_input: 原始用户消息（暂时没用，留给以后扩展）。
        response: Agent 的回复文本（暂时没用，留给以后扩展）。

    Returns:
        markdown 格式的提醒字符串，没得提醒就返回 ""。
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
                    f"✅ 你上报的 {len(recent_resolved)} 个问题今天已解决。"
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
                f"你的提案 #{prop['id']}「{prop['title'][:20]}」已有 "
                f"{prop['supporter_count']} 人附议，输入「查看我的提案」了解进展"
            )

        from data.db_sla import get_sla_summary
        stale_cnt = get_sla_summary().get("total_overdue", 0)
        if stale_cnt >= 3:
            notes.append(
                f"⚠️ 社区有 {stale_cnt} 件工单超时未处理，建议关注积压问题"
            )

        if not notes:
            return ""

        return "\n\n---\n\n🔄 **闭环追踪**\n\n" + "\n\n".join(notes)

    except Exception as e:
        _log.warning("闭环检查失败（非致命）：%s", e)
        return ""
