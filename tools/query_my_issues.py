# tools/query_my_issues.py
"""个人工单查询工具 — 让学生查询自己上报的问题及处理进度。

解决之前 AI 无法按作者过滤工单的问题：
- query_issues 只能按 category/status 过滤，不含 author 参数
- LLM 无从得知当前用户的 author 标识，无法在回复中手动过滤
- 学生问"我的工单怎么样了"→ AI 只能返回全部工单或说"没有"

此工具自动从 session 解析当前用户身份，直接调用 get_my_issues，
让学生侧 AI 对话能准确返回"我的工单"。
"""
import logging
from langchain.tools import tool
from data.database import get_my_issues, get_my_proposals, get_my_stats

_log = logging.getLogger(__name__)


def _resolve_current_author() -> str:
    """Auto-resolve the current user's author identifier from session state.

    Delegates to _resolve_author() in data/db_governance.py — the single
    source of truth for author identity resolution.
    """
    from data.db_governance import _resolve_author
    author = _resolve_author("")
    return "" if author == "匿名" else author


_STATUS_LABELS = {
    "待处理": "⏳ 待处理",
    "处理中": "🏗️ 处理中",
    "已解决": "✅ 已解决",
}


@tool
def query_my_issues() -> str:
    """查询我上报的所有问题工单及其处理进度。

    无需参数——自动识别当前登录用户，返回该用户上报的全部工单。
    当学生问"我的工单""我报修的问题""我上报的XX修好了吗"时调用此工具。
    """
    author = _resolve_current_author()
    if not author:
        return (
            "⚠️ 无法识别当前用户身份。请先在「我的」页面完善个人信息（学号或姓名），"
            "或联系管理员绑定账号。"
        )

    issues = get_my_issues(author, limit=50)

    if not issues:
        return (
            f"📋 你（{author}）还没有上报过任何问题。\n\n"
            "发现校园里的问题？直接描述，我帮你秒速上报！比如「教三楼二楼水龙头漏水」。"
        )

    # ── Stats summary ──
    stats = get_my_stats(author)
    total = stats["total_issues"]
    resolved = stats["resolved_issues"]
    pending = total - resolved

    lines = [
        f"📋 **你的工单总览**（{author}）",
        f"",
        f"📊 共 {total} 件：⏳ 待处理/处理中 {pending} 件 · ✅ 已解决 {resolved} 件",
        f"",
        f"---",
        f"",
    ]

    for issue in issues:
        st_label = _STATUS_LABELS.get(issue["status"], issue["status"])
        urgency_mark = {"普通": "", "紧急": " 🔥", "极急": " 🚨"}
        um = urgency_mark.get(issue["urgency"], "")

        lines.append(
            f"  **#{issue['id']}** {st_label}{um}"
        )
        lines.append(f"  📝 {issue['title']}")
        lines.append(
            f"  📂 {issue.get('category', '')} · "
            f"📍 {issue.get('location', '未指定')} · "
            f"🕐 {issue.get('reported_at', '')[:10]}"
        )
        if issue.get("resolved_at"):
            lines.append(f"  ✅ 解决时间：{issue['resolved_at'][:10]}")
        if issue.get("description"):
            lines.append(f"  💬 {issue['description'][:80]}")
        if issue.get("processing_note"):
            lines.append(f"  📝 处理回复：{issue['processing_note'][:100]}")
        lines.append("")

    # ── Governance encouragement ──
    if pending == 0 and resolved > 0:
        lines.append("🎉 你上报的所有问题都已解决！感谢你对校园治理的贡献~")
    elif pending > 0:
        lines.append(
            f"💡 还有 {pending} 件工单在处理中。输入「查看工单 #编号」了解具体进度，"
            "或切换到「📊 治理透明窗」查看全校治理态势。"
        )

    return "\n".join(lines)


@tool
def query_my_proposals() -> str:
    """查询我提交的所有提案及其状态。

    无需参数——自动识别当前登录用户。
    当学生问"我的提案""我提的建议""我的提案有回复吗"时调用此工具。
    """
    author = _resolve_current_author()
    if not author:
        return (
            "⚠️ 无法识别当前用户身份。请先在「我的」页面完善个人信息（学号或姓名）。"
        )

    proposals = get_my_proposals(author, limit=50)

    if not proposals:
        return (
            f"📋 你（{author}）还没有提交过任何提案。\n\n"
            "有好的校园改进建议？直接告诉我，比如「建议在宿舍楼下增设快递柜」~"
        )

    lines = [
        f"📋 **你的提案列表**（{author}）",
        f"",
    ]

    for p in proposals:
        status_emoji = {
            "讨论中": "💬", "已回应": "📢", "已采纳": "✅", "已实施": "🚀",
        }
        se = status_emoji.get(p["status"], "📌")
        lines.append(
            f"  **#{p['id']}** {se} {p['status']} · 👍 {p.get('supporter_count', 0)} 人附议"
        )
        lines.append(f"  📝 {p['title'][:60]}")
        if p.get("response_text"):
            lines.append(f"  💬 官方回复：{p['response_text'][:80]}")
        lines.append("")

    return "\n".join(lines)
