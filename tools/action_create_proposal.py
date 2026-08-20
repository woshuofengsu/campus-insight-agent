# tools/action_create_proposal.py
"""邻里议事 — 创建社区提案（对接新提案数据层：强制类别五选一、公开/私有、电话校验）。"""
from langchain.tools import tool
from data.db_proposal import (
    submit_proposal as _db_submit_proposal,
    get_proposals as _db_get_proposals,
    VALID_CATEGORIES,
)


def _check_duplicate(title: str) -> list[dict]:
    """看看是不是已经有过类似提案（简单算关键词重叠）。"""
    existing = _db_get_proposals(limit=50)
    title_keywords = set(title)
    duplicates = []
    for p in existing:
        p_keywords = set(p["title"])
        overlap = len(title_keywords & p_keywords) / max(len(title_keywords | p_keywords), 1)
        if overlap > 0.4:
            duplicates.append(p)
    return duplicates


@tool
def create_proposal(title: str, description: str, category: str = "",
                    is_public: bool | None = None, reporter_name: str = "",
                    reporter_phone: str = "", community_building: str = "",
                    agent_report: bool = False, agent_name: str = "",
                    agent_phone: str = "", agent_relation: str = "") -> str:
    """创建一个社区治理提案（必须先从居民处问清全部必填信息）。

    参数：
    - title: 提案标题（必填，≤50 字），如"建议在小区空地加装电动车充电桩"
    - description: 提案内容（必填，10~1000 字），说明为什么提、怎么做
    - category: 提案类别（必填，五选一）：公共设施/环境卫生/文化活动/安全治理/其他
    - is_public: 是否公开（必填）：True 公开（公示 7 天 + 居民匿名评分）/ False 私有（不公示不投票）
    - reporter_name: 提案人姓名（必填）
    - reporter_phone: 联系电话（必填，11 位手机号）
    - community_building: 所属小区/楼栋（选填）
    - agent_report: 是否代报（选填，默认 False）
    - agent_name / agent_phone / agent_relation: 代报人信息（选填）

    注意：类别和公开方式必须由居民本人选择，AI 不能代替选；信息不全必须先追问，
    不能替居民拍板。提交后进入负责人审核（状态：待审核）。
    """
    if not title or not description:
        return "⚠️ 创建提案失败：标题和内容不能为空。"
    if category not in VALID_CATEGORIES:
        return f"⚠️ 请选择提案类别（五选一）：{'/'.join(VALID_CATEGORIES)}。类别必须由居民本人选择。"
    if is_public is None:
        return "⚠️ 请先向居民确认提案公开方式：公开（公示投票）还是私有（不公示）。"
    if not reporter_name:
        return "⚠️ 请填写提案人姓名。"
    if not reporter_phone:
        return "⚠️ 请填写联系电话（11 位手机号）。"

    # 查重：有相似提案就提醒一下，但不拦着创建。
    duplicates = _check_duplicate(title)
    dup_note = ""
    if duplicates:
        dup_titles = "、".join(f"「{d['title'][:20]}」" for d in duplicates[:3])
        dup_note = f"\n已有相似提案：{dup_titles}。建议看看是否重复提交。"

    pid, msg = _db_submit_proposal(
        title=title, description=description, category=category,
        reporter_name=reporter_name, reporter_phone=reporter_phone,
        is_public=1 if is_public else 0,
        community_building=community_building,
        is_agent_report=1 if agent_report else 0,
        agent_name=agent_name, agent_phone=agent_phone, agent_relation=agent_relation,
    )
    if not pid:
        return f"⚠️ 创建提案失败：{msg}"

    # 清缓存，网格员端和「我的」页立刻能看到新提案
    try:
        from ui.cache import invalidate_proposals
        invalidate_proposals()
    except Exception:
        pass

    public_note = "公开（公示 7 天，全体居民评分）" if is_public else "私有（不公示不投票）"
    return (
        f"✅ 提案已提交！\n"
        f"📝 编号 P{pid:05d} **{title}**\n"
        f"📂 类别：{category} · 🔓 {public_note}\n"
        f"⏳ 当前状态：待审核，负责人审核通过后您需确认公开/私有并进入公示。{dup_note}"
    )
