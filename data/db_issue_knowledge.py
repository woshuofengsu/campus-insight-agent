# -*- coding: utf-8 -*-
"""工单知识沉淀（v4 §5 壁垒层二的"下一步"）：**字段来源**与**处置结果**变成可查询结构。

两个问题，之前都答不上来：

  ① **"这条位置是老人自己说的，还是我们替他填的？"**
     提交时 `utils/elderly_report` 算过"每个字段的来源"，也展示给老人核对过，但**没落库**——
     刷新即失，事后只能翻对话留痕猜。现在 v52 把它存进 `community_issues.field_sources`，
     本模块负责把它读成结构化 dict（`issue_field_sources`）。
  ② **"这类问题以前一般是谁办、办多久、怎么解决的？"**
     处置结果散在 `resolve_note`（自由文本）与 `assignee_name` 里，没人能按分类查。
     本模块给出**同类问题处置画像**（`category_profile`）：条数 / 办结率 / 平均时长 / 超时率 /
     第三方责任占比 / 常见责任方 / 常见处置关键词——**全部来自真实库内记录**，
     并给每条画像附上"样本量"，样本太少时明确标注"样本不足"，不让人拿 2 条样本下结论。

口径纪律（材料里照抄）：
  · 时长 = `resolved_at - reported_at`（小时，保留 1 位），只统计**两端都有时间**的工单；
  · 超时 = `escalated_at` 非空（那是 SLA 超时留痕，不是我们另算一套）；
  · "常见处置关键词"是从 `resolve_note` 里按 **2–4 字词组**统计的高频词，**最多取前 5 个**，
    且**先掩码手机号**（留痕/统计里不许出现完整手机号）；
  · 一切按 `tenant` 收口（`tenant_clause` fail-closed）：空租户返回空结构，绝不查全库。
"""
import logging
import re
from collections import Counter
from datetime import datetime, timedelta

from data.db_core import get_db
from utils.pii import scrub_text
from utils.tenant import tenant_clause

_log = logging.getLogger(__name__)

MODULE = "工单知识"
#: 低于这个样本量就明确标注"样本不足"（避免拿 2 条记录当规律讲）
MIN_SAMPLE = 5
#: 处置关键词的最小/最大长度（中文词组）
_WORD_MIN, _WORD_MAX = 2, 4
_STOP = ("已经", "我们", "他们", "这个", "那个", "就是", "可以", "进行", "处理", "结果",
         "居民", "问题", "情况", "然后", "因为", "所以", "已经处理", "已处理", "完成")


def _parse_sources(raw: str) -> dict:
    import json
    if not raw:
        return {}
    try:
        d = json.loads(raw)
    except (TypeError, ValueError) as e:
        _log.warning("field_sources 解析失败（按空处理）：%s", e)
        return {}
    return d if isinstance(d, dict) else {}


def issue_field_sources(issue_id: int, tenant: str = "") -> dict:
    """单条工单的**字段来源**（`{字段: 来源}`）+ 说明。

    返回 `{"issue_id":…, "sources": {...}, "note": "…"}`；查不到或没记录时 `sources` 为空 dict，
    并如实说明"这张单没有字段来源记录（可能是网页表单直接填写或 v52 之前的单）"。
    """
    args: list = [issue_id]
    tc = tenant_clause(tenant, args)
    if tc is None:
        return {"issue_id": issue_id, "sources": {}, "note": "缺少社区归属，已按空返回"}
    with get_db() as conn:
        row = conn.execute(
            f"SELECT field_sources, title, location, category FROM community_issues "
            f"WHERE id=?{tc}", tuple(args)).fetchone()
    if row is None:
        return {"issue_id": issue_id, "sources": {}, "note": "工单不存在或不属于本社区"}
    src = _parse_sources(row["field_sources"] or "")
    return {"issue_id": issue_id, "sources": src,
            "note": "" if src else "这张单没有字段来源记录（网页表单直接填写，或 v52 之前的单）"}


def _keywords(texts: list[str], top: int = 5) -> list[tuple[str, int]]:
    """从处置说明里统计高频 2–4 字词组（先掩码手机号，再去停用词）。

    这不是"摘要算法"，只是**词频**——所以对外只说"常见处置关键词"，不说"AI 总结"。
    """
    counter: Counter = Counter()
    for t in texts:
        clean, _n = scrub_text(t or "")   # 先把手机号等信息抹掉再统计（留痕/统计里不许出现完整手机号）
        for n in range(_WORD_MIN, _WORD_MAX + 1):
            for i in range(0, max(0, len(clean) - n + 1)):
                w = clean[i:i + n]
                if re.search(r"[0-9A-Za-z#\-\s]", w):
                    continue
                if w in _STOP:
                    continue
                counter[w] += 1
    return [(w, c) for w, c in counter.most_common(top * 3) if c >= 2][:top]


def category_profile(category: str = "", days: int = 180, tenant: str = "") -> dict:
    """**同类问题处置画像**（按分类聚合，全部来自真实记录；样本不足会如实标注）。"""
    since = (datetime.now() - timedelta(days=max(1, min(days, 1095)))).strftime("%Y-%m-%d %H:%M:%S")
    args: list = [since]
    tc = tenant_clause(tenant, args)
    empty = {"category": category, "days": days, "total": 0, "resolved": 0,
             "resolved_rate": 0.0, "avg_hours": None, "overdue": 0, "overdue_rate": 0.0,
             "third_party": 0, "third_party_rate": 0.0, "top_assignees": [],
             "top_keywords": [], "sample_enough": False,
             "note": "缺少社区归属或没有样本，已按空返回"}
    if tc is None:
        return empty
    where = [f"reported_at>=?{tc}"]
    if category:
        where.append("category=?")
    w = " AND ".join(where)
    # 明细与"分类分布"用各自的参数：分类分布**不带** category 条件（否则只剩当前分类一行，没有对比意义）
    cat_args: list = [since]
    cat_tc = tenant_clause(tenant, cat_args)
    with get_db() as conn:
        detail_args: list = [datetime.fromisoformat(since).strftime("%Y-%m-%d %H:%M:%S")]
        tc2 = tenant_clause(tenant, detail_args)
        if category:
            detail_args.append(category)
        rows = conn.execute(
            f"SELECT id, status, reported_at, resolved_at, escalated_at, assignee_name, "
            f"non_community_responsibility, resolve_note FROM community_issues "
            f"WHERE {w}", tuple(detail_args)).fetchall()
        cats = [] if cat_tc is None else conn.execute(
            f"SELECT category, COUNT(*) c FROM community_issues WHERE reported_at>=?{cat_tc} "
            f"GROUP BY category ORDER BY c DESC LIMIT 12", tuple(cat_args)).fetchall()
    total = len(rows)
    resolved = [r for r in rows if (r["resolved_at"] or "")]
    hours = []
    for r in resolved:
        try:
            a = datetime.fromisoformat(str(r["reported_at"]).replace("Z", ""))
            b = datetime.fromisoformat(str(r["resolved_at"]).replace("Z", ""))
            h = (b - a).total_seconds() / 3600
            if h >= 0:
                hours.append(h)
        except (TypeError, ValueError):
            continue
    overdue = sum(1 for r in rows if (r["escalated_at"] or ""))
    third = sum(1 for r in rows if int(r["non_community_responsibility"] or 0))
    assignees = Counter([(r["assignee_name"] or "").strip() for r in resolved if (r["assignee_name"] or "").strip()])
    notes = [(r["resolve_note"] or "") for r in resolved]
    return {
        "category": category or "全部",
        "days": days,
        "total": total,
        "resolved": len(resolved),
        "resolved_rate": round(len(resolved) / total * 100, 1) if total else 0.0,
        "avg_hours": round(sum(hours) / len(hours), 1) if hours else None,
        "overdue": overdue,
        "overdue_rate": round(overdue / total * 100, 1) if total else 0.0,
        "third_party": third,
        "third_party_rate": round(third / total * 100, 1) if total else 0.0,
        "top_assignees": [{"name": n, "count": c} for n, c in assignees.most_common(5)],
        "top_keywords": _keywords(notes, top=5),
        "sample_enough": total >= MIN_SAMPLE,
        "categories": [{"category": c["category"], "count": int(c["c"] or 0)} for c in cats],
        "note": "" if total >= MIN_SAMPLE else f"样本不足（{total} 条 < {MIN_SAMPLE} 条）：只作参考，别当规律",
    }
