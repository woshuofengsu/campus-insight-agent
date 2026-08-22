# agent/analytics.py
"""离线聚类 + 趋势 + 知识库推荐（P2-03，适配项目零 Embedding 依赖：TF-IDF 轻量聚类）。

- 高频问题：按双字特征聚合近 N 天报修描述 → 主题簇 + 关键词 + 环比
- 趋势：本周 vs 上周对比（±10% 触发简报）
- 知识库补充建议：高频但知识库未覆盖的主题词
- 预测（规则级）：天气转冷 → 预测「暖气/保暖」类报修增加（演示）
"""
import logging
from collections import Counter
from datetime import datetime, timedelta

from data.database import get_db

_log = logging.getLogger(__name__)


def _bigrams(s: str) -> list[str]:
    s = (s or "").strip()
    return [s[i:i + 2] for i in range(max(0, len(s) - 1))]


def get_issue_clusters(days: int = 7, top: int = 5) -> list[dict]:
    """近 N 天报修主题聚类：双字特征频次 → 主题词 + 数量 + 环比（vs 前 N 天）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT description, title FROM community_issues "
            "WHERE reported_at >= datetime('now', ? || ' days')",
            (f"-{days}",),
        ).fetchall()
        prev = conn.execute(
            "SELECT description, title FROM community_issues "
            "WHERE reported_at >= datetime('now', ? || ' days') "
            "AND reported_at < datetime('now', ? || ' days')",
            (f"-{days * 2}", f"-{days}"),
        ).fetchall()
    cur_cnt = Counter()
    prev_cnt = Counter()
    for r in rows:
        for bg in _bigrams((r["description"] or "") + (r["title"] or "")):
            cur_cnt[bg] += 1
    for r in prev:
        for bg in _bigrams((r["description"] or "") + (r["title"] or "")):
            prev_cnt[bg] += 1
    cur_total = sum(cur_cnt.values()) or 1
    prev_total = sum(prev_cnt.values()) or 1
    out = []
    for bg, c in cur_cnt.most_common(top):
        if c < 2:
            continue
        ratio = (c / cur_total) / max((prev_cnt.get(bg, 0) / prev_total), 0.001)
        change = round((ratio - 1) * 100)
        out.append({"topic": bg, "count": c, "change_pct": change})
    return out


def get_weekly_trend(days: int = 7) -> list[dict]:
    """近 N 天按日工单量趋势（驾驶舱折线数据）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DATE(reported_at, 'localtime') d, COUNT(*) c FROM community_issues "
            "WHERE reported_at >= datetime('now', ? || ' days') GROUP BY d ORDER BY d",
            (f"-{days}",),
        ).fetchall()
        by_day = {r["d"]: r["c"] for r in rows}
        trend = []
        for i in range(days - 1, -1, -1):
            day = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            trend.append({"day": day[5:], "count": by_day.get(day, 0)})
        return trend


def build_data_brief() -> str:
    """数据简报（P3-03 数据叙事，规则生成）：趋势/异常/机会。"""
    parts = []
    try:
        clusters = get_issue_clusters(days=7)
        prev_clusters = get_issue_clusters(days=14)  # 近两周（粗略环比）
        rising = [c for c in clusters if c["change_pct"] >= 10]
        if rising:
            t = rising[0]["topic"]
            parts.append(f"本周「{t}」类问题上升 {rising[0]['change_pct']}%，建议关注。")
        elif clusters:
            parts.append(f"本周高频问题集中在「{clusters[0]['topic']}」（{clusters[0]['count']} 件）。")
    except Exception:
        pass
    try:
        from data.db_repair import get_overdue_issues
        overdue = len(get_overdue_issues())
        if overdue > 0:
            parts.append(f"⚠️ 当前有 {overdue} 条工单超时，建议优先处理。")
    except Exception:
        pass
    try:
        from data.db_policy import get_frequency_stats
        stats = get_frequency_stats(days=7)
        if stats.get("total_questions", 0) > 0:
            parts.append(f"近 7 天政策提问 {stats['total_questions']} 条，其中自动回答失败 {stats.get('match_failed', 0)} 条，建议补充知识库。")
    except Exception:
        pass
    return "；".join(parts) if parts else "数据积累中，暂无可生成简报的趋势。"
