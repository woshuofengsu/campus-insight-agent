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


def category_corrections(days: int = 180, tenant: str = "", limit: int = 50) -> dict:
    """**「系统建议分类 vs 人工最终分类」对照清单**（收敛方案第 7 阶段）。

    回答的问题是："这套自动分类到底准不准，有多少条被网格员改过？"
    数据来源全部是库内真实字段：
      · `suggested_category` = **系统当初的建议**（提交时写死，之后不随人工修改而变）；
      · `category`           = **当前生效分类**（网格员可以用 `update_category` 改）；
      · 改动的人与时间从 `activity_log`（action 含"修改工单分类"）取。

    ⚠️ 三条口径纪律，**材料里必须一起写**：
      ① **覆盖率必须显示**：`suggested_category` 是第 6 阶段才补的写入侧，
         v52 之前的历史工单该字段为空 —— 所以"覆盖率"会明显小于 100%。
         只报"一致率"而不报覆盖率，等于拿一小撮样本冒充全体（这就是口径造假）。
         空建议的工单单独计数（`no_suggestion`），**不算**成"系统建议正确"。
      ② **样本不足要标**：有建议的条数 < 5 → 只作参考。
      ③ 这张表**不是模型训练数据**：不做回灌、不做调参，只是给人看的核查清单。
         （对外别写"用于训练模型"，本项目没有这条链路。）
      ④ **演示数据必须分开报**（v53 `is_demo`）：为了凑样本用 `seed_*.py` 造过演示工单，
         它们混进分母会把"自造数据"算成真实样本。所以这里分三个口径：
         `total` / `demo_*`（已标记演示）/ `real_*`（**未标记**：真实部署中即真实来源）。
         ⚠️ 不把"未标记"写成"真实居民"——演示库里未标记的同样来自演示/验证脚本。
    """
    since = (datetime.now() - timedelta(days=max(1, min(days, 1095)))).strftime("%Y-%m-%d %H:%M:%S")
    args: list = [since]
    tc = tenant_clause(tenant, args)
    empty = {
        "days": days, "total": 0, "with_suggestion": 0, "no_suggestion": 0,
        "corrected": 0, "agreed": 0, "coverage": 0.0, "agreement_rate": 0.0,
        "corrected_rate": 0.0, "pairs": [], "items": [], "unlogged_changes": 0,
        "sample_enough": False, "min_sample": MIN_SAMPLE,
        "demo": {"total": 0, "with_suggestion": 0, "corrected": 0, "agreed": 0},
        "real": {"total": 0, "with_suggestion": 0, "corrected": 0, "agreed": 0,
                 "coverage": 0.0, "agreement_rate": 0.0},
        "demo_note": "",
        "note": "缺少社区归属或没有样本，已按空返回",
        "disclaimer": "本清单仅供人工核查，不用于模型训练/调参。",
    }
    if tc is None:
        return empty
    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) c FROM community_issues WHERE reported_at>=?{tc}",
            tuple(args)).fetchone()["c"]
        rows = conn.execute(
            f"SELECT id, title, category, suggested_category, COALESCE(is_demo,0) AS is_demo "
            f"FROM community_issues "
            f"WHERE reported_at>=?{tc} AND COALESCE(suggested_category,'')<>'' "
            f"ORDER BY id DESC LIMIT 2000", tuple(args)).fetchall()
        # 改动留痕：一次查全部，避免按行 N+1
        ids = [int(r["id"]) for r in rows]
        log_map: dict[int, dict] = {}
        if ids:
            qmarks = ",".join("?" * len(ids))
            for a in conn.execute(
                    f"SELECT target_id, actor, created_at, before_value, after_value "
                    f"FROM activity_log WHERE target_type='issue' AND target_id IN ({qmarks}) "
                    f"AND action LIKE '%修改工单分类%' ORDER BY id", tuple(ids)).fetchall():
                # 取**最早一次**改动（那就是"人工第一次不认同系统建议"的那一刻）
                log_map.setdefault(int(a["target_id"]), dict(a))

    corrected, pairs, items, unlogged = 0, Counter(), [], 0
    demo = {"total": 0, "with_suggestion": 0, "corrected": 0, "agreed": 0}
    real = {"total": 0, "with_suggestion": 0, "corrected": 0, "agreed": 0}
    for r in rows:
        sug = str(r["suggested_category"] or "").strip()
        fin = str(r["category"] or "").strip()
        changed = sug != fin
        is_demo = int(r["is_demo"] or 0) == 1
        bucket = demo if is_demo else real
        bucket["with_suggestion"] += 1
        if changed:
            bucket["corrected"] += 1
        else:
            bucket["agreed"] += 1
        log = log_map.get(int(r["id"]))
        if changed:
            corrected += 1
            pairs[(sug, fin)] += 1
            if log is None:
                # 分类变了却没有留痕 → 说明有绕过 `update_issue_category` 的写入路径，
                # 这是真问题，要报出来而不是装作没看见
                unlogged += 1
        if len(items) < limit:
            clean, _n = scrub_text(r["title"] or "")
            items.append({
                "issue_id": int(r["id"]),
                "title": clean[:24],
                "suggested": sug,
                "final": fin,
                "changed": changed,
                "is_demo": is_demo,
                "changed_by": (log or {}).get("actor") or "",
                "changed_at": ((log or {}).get("created_at") or "")[:16],
            })
    real["total"] = 0
    # 「演示数据」总数要按**全部工单**数，不只是"有建议的"那些（否则分母对不上）
    with get_db() as conn:
        demo_total = conn.execute(
            f"SELECT COUNT(*) c FROM community_issues WHERE reported_at>=?{tc} "
            f"AND COALESCE(is_demo,0)=1", tuple(args)).fetchone()["c"]
    demo["total"] = int(demo_total or 0)
    real["total"] = max(0, int(total or 0) - demo["total"])
    for b in (demo, real):
        b["coverage"] = round(b["with_suggestion"] / b["total"] * 100, 1) if b["total"] else 0.0
        b["agreement_rate"] = (round(b["agreed"] / b["with_suggestion"] * 100, 1)
                               if b["with_suggestion"] else 0.0)
    demo_note = ""
    if demo["total"]:
        # 免责声明**由数据驱动**：只要分母里有演示数据，就必须跟着这段话。
        # ⚠️ 措辞刻意区分「已标记演示」与「未标记」，**不把未标记那部分叫"真实居民"**：
        # 在演示库里，未标记的工单同样来自演示/验证脚本（journey_check、demo_flow_check 等），
        # 把它们说成"真实来源"就是换一种方式编数字。真实试点开始后，未标记部分才是真实来源。
        demo_note = (f"其中**已标记**演示数据 {demo['total']} 条（走真实链路造，但不是真实居民诉求）："
                     "**不代表真实居民样本、不用于模型训练、不代表线上准确率**。"
                     f"未标记 {real['total']} 单（真实部署中即真实来源；"
                     f"本机演示库内这些工单同样由演示/验证脚本产生），"
                     f"其中带系统建议 {real['with_suggestion']} 条（覆盖率 {real['coverage']}%）")
    with_sug = len(rows)
    total = int(total or 0)
    enough = with_sug >= MIN_SAMPLE
    if enough:
        note = ""
    elif with_sug == 0:
        note = ("窗口期内没有带系统建议的工单：**清单为空是预期的**——"
                "建议写入侧是第 6 阶段才补的，此前的历史工单该字段为空")
    else:
        note = (f"样本不足（有系统建议的只有 {with_sug} 条 < {MIN_SAMPLE} 条）："
                "只作参考，别当准确率讲")
    return {
        **empty,
        "days": days,
        "total": total,
        "with_suggestion": with_sug,
        "no_suggestion": max(0, total - with_sug),
        "corrected": corrected,
        "agreed": with_sug - corrected,
        "coverage": round(with_sug / total * 100, 1) if total else 0.0,
        "agreement_rate": round((with_sug - corrected) / with_sug * 100, 1) if with_sug else 0.0,
        "corrected_rate": round(corrected / with_sug * 100, 1) if with_sug else 0.0,
        "pairs": [{"suggested": s, "final": f, "count": c}
                  for (s, f), c in pairs.most_common(10)],
        "items": items,
        "unlogged_changes": unlogged,
        "sample_enough": enough,
        "demo": demo,
        "real": real,
        "demo_note": demo_note,
        "note": note,
    }
