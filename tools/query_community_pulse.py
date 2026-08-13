# tools/query_community_pulse.py
"""社区脉搏 — 本周热点 + 即将发生的大事."""
import logging
from datetime import datetime, timedelta
from langchain.tools import tool
from data.database import get_community_events, get_issues, get_proposals, get_active_topics

_log = logging.getLogger(__name__)


def _generate_pulse_text() -> str:
    """Build the community pulse summary from multiple data sources."""
    now = datetime.now()
    weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

    lines = [f"🌊 **社区脉搏** — {now.strftime('%Y年%m月%d日')} {weekday}", ""]

    # ── Section 1: 本周热点 ──
    lines.append("### 📡 本周热点")

    # From community issues
    issues = get_issues(limit=100)
    if issues:
        # Count this week's issues
        this_week = [i for i in issues if i.get("reported_at", "")[:10] >= week_start]
        resolved_this_week = [i for i in this_week if i.get("status") == "已解决"]
        if this_week:
            lines.append(f"· 本周上报了 {len(this_week)} 个社区诉求，已解决 {len(resolved_this_week)} 个")
            # Hot categories
            cats: dict[str, int] = {}
            for i in this_week:
                cat = i.get("category", "其他")
                cats[cat] = cats.get(cat, 0) + 1
            if cats:
                top_cat = max(cats, key=cats.get)
                lines.append(f"· 热点类别：**{top_cat}**（{cats[top_cat]} 件）")
        else:
            lines.append("· 本周暂无新的社区诉求上报，小区运行平稳 🌿")
    else:
        lines.append("· 暂无社区诉求数据")

    # From proposals
    proposals = get_proposals(sort_by="supporters", limit=5)
    if proposals:
        top = proposals[0]
        lines.append(f"· 最热提案：**{top['title'][:25]}**（{top['supporter_count']} 人附议）")

    # From active topics
    topics = get_active_topics(limit=3)
    if topics:
        topic_names = "、".join(t["title"][:15] for t in topics)
        lines.append(f"· 正在热议：{topic_names}")

    lines.append("")

    # ── Section 2: 即将发生 ──
    lines.append("### 📅 即将发生")

    events = get_community_events(limit=10)
    upcoming = []
    for e in events:
        content = e.get("content", "")
        title = e.get("title", "")
        # Try to extract date info from content or title
        upcoming.append(f"· {title}：{content[:80]}{'...' if len(content) > 80 else ''}")

    if upcoming:
        for u in upcoming[:5]:
            lines.append(u)
    else:
        # Fallback: check knowledge base for calendar/notice
        lines.append("· 暂无待办事件。可以在知识库中添加社区活动安排获取提醒。")

    # ── Section 3: 治理快照 ──
    lines.append("")
    lines.append("### 📊 治理快照")
    all_issues = get_issues(limit=100)
    total = len(all_issues)
    pending = len([i for i in all_issues if i.get("status") == "待处理"])
    resolved = len([i for i in all_issues if i.get("status") == "已解决"])
    all_proposals = get_proposals(limit=100)
    prop_total = len(all_proposals)
    prop_implemented = len([p for p in all_proposals if p.get("status") == "已实施"])

    lines.append(f"· 累计上报 {total} 件，{resolved} 件已解决（{resolved * 100 // total if total else 0}%）")
    lines.append(f"· {pending} 件待处理")
    lines.append(f"· 累计提案 {prop_total} 件，{prop_implemented} 件已实施")

    return "\n".join(lines)


@tool
def get_community_pulse() -> str:
    """获取社区脉搏——本周热点事件、即将发生的大事、以及社区治理概况。

    返回一份综合简报，包含：
    - 本周上报的社区诉求数量和热点类别
    - 最受关注的提案和正在热议的话题
    - 即将发生的重要事件（活动安排、通知、议事等）
    - 社区治理整体数据快照

    适合居民打开应用时第一眼看到的内容。
    """
    try:
        return _generate_pulse_text()
    except Exception as e:
        _log.debug("get_community_pulse failed: %s", e, exc_info=True)
        return f"⚠️ 社区脉搏数据暂不可用：{e}\n请稍后重试。"
