# tools/action_create_proposal.py
"""邻里议事 — 创建社区提案."""
from langchain.tools import tool
from data.database import create_proposal as _db_create_proposal, get_proposals


# Categories matching community_issues for consistency
_VALID_CATEGORIES = ["设施维修", "环境卫生", "安全隐患", "停车管理", "噪音扰民", "物业服务", "邻里矛盾", "社区事务"]


def _check_duplicate(title: str) -> list[dict]:
    """Check if a similar proposal already exists (simple keyword overlap)."""
    existing = get_proposals(limit=50)
    title_keywords = set(title)
    duplicates = []
    for p in existing:
        p_keywords = set(p["title"])
        overlap = len(title_keywords & p_keywords) / max(len(title_keywords | p_keywords), 1)
        if overlap > 0.4:
            duplicates.append(p)
    return duplicates


@tool
def create_proposal(title: str, description: str, category: str = "其他") -> str:
    """创建一个社区改进提案。

    参数：
    - title: 提案标题（必填），如"建议在小区空地加装电动车充电桩"
    - description: 提案详细描述（必填），说明为什么要这样做、怎么做
    - category: 提案分类（可选），可选值：设施维修/环境卫生/安全隐患/停车管理/噪音扰民/物业服务/邻里矛盾/社区事务

    你的提案会被其他居民看到，他们可以附议支持。附议量高的提案会被推送到治理看板。
    """
    if not title or not description:
        return "⚠️ 创建提案失败：标题和描述不能为空。"

    if category not in _VALID_CATEGORIES:
        cat_list = "/".join(_VALID_CATEGORIES)
        return f"⚠️ 分类'{category}'无效。可选：{cat_list}"

    # Check for duplicates — warn if similar proposals exist but don't block creation.
    # Character-level Jaccard is too coarse for Chinese; false positives are common.
    duplicates = _check_duplicate(title)
    dup_note = ""
    if duplicates:
        dup_titles = "、".join(f"「{d['title'][:20]}」({d['supporter_count']}人附议)" for d in duplicates[:3])
        dup_note = (
            f"\n已有相似提案：{dup_titles}"
            f"\n建议也去看看，帮忙附议。"
        )

    proposal_id = _db_create_proposal(title=title, description=description, category=category)

    # Invalidate caches so new proposal is visible immediately on grid side and "我的" page
    try:
        from ui.cache import invalidate_proposals
        invalidate_proposals()
    except Exception:
        pass

    return (
        f"✅ 提案已创建！\n"
        f"📝 #{proposal_id} **{title}**\n"
        f"📂 分类：{category}\n"
        f"👤 当前附议：1 人（含你）\n"
        f"附议量越高越容易被社区/物业关注。{dup_note}"
    )
