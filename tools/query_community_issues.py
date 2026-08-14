# tools/query_community_issues.py
"""社区治理查询工具 — 诉求查询、统计、意见收集与聚合。

基层治理核心：透明、可追溯的诉求处理 + 民意收集。
"""
from langchain.tools import tool
from data.database import (
    get_issues, get_issues_stats,
    add_feedback, aggregate_feedback,
)

_CATEGORY_LABELS = {
    "设施维修": "🔧 设施维修",
    "环境卫生": "🧹 环境卫生",
    "安全隐患": "⚠️ 安全隐患",
    "停车管理": "🅿️ 停车管理",
    "噪音扰民": "🔊 噪音扰民",
    "物业服务": "🏢 物业服务",
    "邻里矛盾": "🤝 邻里矛盾",
    "社区事务": "📋 社区事务",
}

_STATUS_LABELS = {
    "待处理": "⏳ 待处理",
    "处理中": "🏗️ 处理中",
    "已解决": "✅ 已解决",
}


@tool
def query_issues(category: str = "", status: str = "", limit: int = 10) -> str:
    """查询社区诉求上报列表 — 基层治理透明化。

    可查看小区中已上报的各类诉求及处理状态。
    参数均可选：
    - category: 诉求分类（设施维修/环境卫生/安全隐患/停车管理/噪音扰民/物业服务/邻里矛盾/社区事务）
    - status: 处理状态（待处理/处理中/已解决）
    - limit: 返回条数（默认10条）
    """
    cat = category.strip() if category else None
    st = status.strip() if status else None
    issues = get_issues(category=cat, status=st, limit=limit)

    if not issues:
        filter_desc = f"（分类={category}）" if category else ""
        filter_desc += f"（状态={status}）" if status else ""
        return f"📋 暂无匹配的诉求记录{filter_desc}。小区一切安好~"

    lines = ["📋 社区诉求治理清单："]
    if category:
        lines.append(f"   筛选分类：{category}")
    if status:
        lines.append(f"   筛选状态：{status}")
    lines.append("")

    for issue in issues:
        cat_label = _CATEGORY_LABELS.get(issue["category"], issue["category"])
        st_label = _STATUS_LABELS.get(issue["status"], issue["status"])
        urgency_mark = {"普通": "", "紧急": " 🔥", "极急": " 🚨"}
        um = urgency_mark.get(issue["urgency"], "")

        lines.append(
            f"  #{issue['id']} {cat_label} {st_label}{um}\n"
            f"     📝 {issue['title']}\n"
            f"     📍 {issue.get('location', '未指定')}  |  "
            f"{issue.get('reported_at', '')[:10]}"
        )
        if issue.get("description"):
            lines.append(f"     💬 {issue['description'][:60]}")
        if issue.get("processing_note"):
            lines.append(f"     📝 处理回复：{issue['processing_note'][:80]}")

    return "\n".join(lines)


@tool
def get_governance_stats() -> str:
    """获取社区治理统计数据 — 诉求上报总览。

    返回各分类诉求数量、处理状态分布，用于感知小区运行状况。
    """
    stats = get_issues_stats()

    if stats["total"] == 0:
        return "📊 社区治理统计：暂无上报诉求。小区运行良好！"

    lines = [
        "📊 社区治理数据总览",
        f"",
        f"  📝 诉求总数：{stats['total']}",
        f"  ⏳ 待处理：{stats['by_status'].get('待处理', 0)}",
        f"  🏗️ 处理中：{stats['by_status'].get('处理中', 0)}",
        f"  ✅ 已解决：{stats['by_status'].get('已解决', 0)}",
        f"",
        f"  📂 分类分布：",
    ]

    for cat, cnt in sorted(stats["by_category"].items(),
                           key=lambda x: x[1], reverse=True):
        cat_label = _CATEGORY_LABELS.get(cat, cat)
        bar = "█" * min(cnt, 20)
        lines.append(f"     {cat_label}：{cnt} {bar}")

    # 治理健康度指标
    total = stats["total"]
    resolved = stats["by_status"].get("已解决", 0)
    if total > 0:
        rate = resolved / total * 100
        if rate >= 80:
            health = "🟢 优"
        elif rate >= 50:
            health = "🟡 良"
        else:
            health = "🔴 需改进"
        lines.append(f"")
        lines.append(f"  🏥 治理健康度：{health}（解决率 {rate:.0f}%）")

    return "\n".join(lines)


@tool
def collect_feedback(topic: str) -> str:
    """收集某个话题的社区意见反馈并进行聚合分析。

    用于了解居民对某个社区议题的态度和建议。
    参数：
    - topic: 话题关键词（如"停车难""电梯年检""广场舞噪音"）
    """
    if not topic.strip():
        return "❌ 请指定一个话题，例如：'停车难'、'广场舞噪音'"

    topic = topic.strip()
    agg = aggregate_feedback(topic)

    if agg["total"] == 0:
        # 没有真实数据：给个演示预览（只读，不落库）
        demo_opinions = {
            "停车": [
                ("小区车位太少，晚上回来根本停不下", "负面"),
                ("新建的立体车库不错，缓解了停车难", "正面"),
                ("建议推行错峰共享车位", "中性"),
                ("总有外来车辆占用固定车位", "负面"),
                ("物业重新划线后好多了", "正面"),
            ],
            "电梯": [
                ("3号楼电梯经常坏，修了又坏", "负面"),
                ("新换的电梯很稳当", "正面"),
                ("希望能加快电梯年检", "中性"),
                ("电梯里装了监控，安心多了", "正面"),
                ("高峰期电梯太难等了", "负面"),
            ],
            "广场舞": [
                ("晚上广场舞音响太吵，影响休息", "负面"),
                ("阿姨们跳舞也是锻炼身体，理解", "中性"),
                ("建议规定跳舞时间段和音量", "中性"),
                ("协调后声音小了不少", "正面"),
                ("希望有专门的活动场地", "中性"),
            ],
            "default": [
                ("整体不错，小区越来越好了", "正面"),
                ("有些地方还需要改进", "中性"),
                ("最近改善了不少", "正面"),
                ("希望物业和网格员多听听居民意见", "中性"),
                ("比以前好多了", "正面"),
            ],
        }

        matched_key = "default"
        for key in demo_opinions:
            if key in topic:
                matched_key = key
                break

        demos = demo_opinions[matched_key]
        total = len(demos)
        pos_n = sum(1 for _, s in demos if s == "正面")
        neg_n = sum(1 for _, s in demos if s == "负面")
        neu_n = sum(1 for _, s in demos if s == "中性")

        lines = [
            f"⚠️ 「{topic}」暂无真实反馈数据。",
            "",
            f"📊 **演示数据预览**（共 {total} 条，非真实数据）：",
        ]
        for opinion, sentiment in demos:
            emoji = {"正面": "😊", "负面": "😟", "中性": "😐"}.get(sentiment, "❓")
            lines.append(f"  {emoji} [{sentiment}] {opinion}")
        lines.extend([
            "",
            "💡 **如何获取真实数据？**",
            "- 使用「邻里议事」→「民意征集」发起真实话题讨论",
            "- 居民提交的意见会自动聚合到这里",
            f"- 当前反馈总数：{total} 条（演示数据）",
        ])
        return "\n".join(lines)

    # 有真实数据就拼报告
    total = agg["total"]
    pos_pct = agg["positive"] / total * 100 if total > 0 else 0
    neg_pct = agg["negative"] / total * 100 if total > 0 else 0
    neu_pct = agg["neutral"] / total * 100 if total > 0 else 0

    # 总体情绪
    if pos_pct >= 60:
        overall = "😊 总体正面"
    elif neg_pct >= 60:
        overall = "😟 总体负面"
    elif pos_pct > neg_pct:
        overall = "🙂 偏向正面"
    elif neg_pct > pos_pct:
        overall = "😐 偏向负面"
    else:
        overall = "😐 意见分歧"

    lines = [
        f"📊 「{topic}」意见收集报告",
        f"",
        f"  📋 共收集 {total} 条反馈",
        f"  👍 正面：{agg['positive']} 条（{pos_pct:.0f}%）",
        f"  👎 负面：{agg['negative']} 条（{neg_pct:.0f}%）",
        f"  😐 中性：{agg['neutral']} 条（{neu_pct:.0f}%）",
        f"",
        f"  🏷️ 总体评价：{overall}",
        f"",
        f"  📌 近期反馈摘要：",
    ]

    for item in agg["recent_items"]:
        sent_emoji = {"正面": "👍", "负面": "👎", "中性": "😐"}
        se = sent_emoji.get(item["sentiment"], "😐")
        lines.append(f"     {se} {item['opinion']}")

    # 治理建议
    if neg_pct >= 50:
        lines.append(f"\n⚠️ 该话题负面意见较多，建议相关部门关注并回复。")
    elif pos_pct >= 70:
        lines.append(f"\n✅ 该话题反馈积极，可作为优秀案例推广。")

    return "\n".join(lines)
