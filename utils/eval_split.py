# -*- coding: utf-8 -*-
"""评测的可复算基础件（v2 升级方案任务卡 13）：**语料快照 + 留出集 + 负收益对比**。

**为什么需要它们**：评测数字只有在"分母固定、语料固定、调参没用过的数据也算一遍"时才有意义。
否则很容易出现三种自欺：
  ① 语料边跑边改（知识库被人加了条目，命中率自然变好，但没人说得清是哪来的）；
  ② 拿调参用过的同一批数据报成绩（**留出集**才是诚实的分母）；
  ③ 只报涨的那一版，跌的那一版不提（"能报负收益"是评审最看重的可信度信号）。

本模块是**纯函数**（无 IO、无网络），可单测：
  · `corpus_digest(rows)`  —— 语料指纹（同一批语料 → 同一串），用来钉住"分母"；
  · `split_cases(cases)`   —— 按查询文本哈希**确定性**切 dev / holdout（同一份数据每次切法一致）；
  · `compare(baseline, variant)` —— 逐条对比两版结果，**把退步单独列出来**。
"""
import hashlib
import json

HOLDOUT_RATIO = 0.3


def _sha1(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def corpus_rows(conn=None) -> list[dict]:
    """评测语料的快照行（只取判定条件需要的字段，便于比对漂移）。"""
    own = conn is None
    if own:
        from data.db_core import get_db
        ctx = get_db()
        conn = ctx.__enter__()
    try:
        rows = conn.execute(
            "SELECT id, title, category, applicable_area, keywords, audit_status, "
            "content FROM knowledge_base ORDER BY id").fetchall()
    finally:
        if own:
            ctx.__exit__(None, None, None)
    out = []
    for r in rows:
        d = dict(r)
        out.append({
            "id": d.get("id"), "title": d.get("title") or "",
            "category": d.get("category") or "",
            "applicable_area": d.get("applicable_area") or "",
            "keywords": d.get("keywords") or "",
            "audit_status": d.get("audit_status") or "",
            # 只存正文指纹：既能发现"内容被改了"，又不把整库正文塞进快照文件
            "content_sha1": _sha1(d.get("content") or "")[:12],
        })
    return out


def corpus_digest(rows: list[dict]) -> str:
    """整批语料的指纹（与顺序无关：按 id 排序后再算）。"""
    canon = json.dumps(sorted(rows, key=lambda r: r.get("id") or 0),
                       ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def diff_corpus(before: list[dict], after: list[dict]) -> dict:
    """语料漂移：新增 / 删除 / 内容改了 各有哪些 id。

    评测报告必须带上这个 —— 否则"命中率变了"到底是**改进了检索**还是**改了语料**，
    谁也说不清（这正是卡13 要求"固定语料快照与文档 id"的原因）。
    """
    b = {r["id"]: r for r in before}
    a = {r["id"]: r for r in after}
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed = []
    for i in sorted(set(a) & set(b)):
        if {k: v for k, v in a[i].items() if k != "id"} != {k: v for k, v in b[i].items() if k != "id"}:
            changed.append({"id": i, "title": a[i].get("title", "")})
    return {"added": added, "removed": removed, "changed": changed,
            "same": not (added or removed or changed)}


def split_cases(cases: list[dict], holdout_ratio: float = HOLDOUT_RATIO,
                key: str = "query") -> dict:
    """按查询文本哈希把用例切成 dev / holdout（**确定性**：同一份数据每次切法一致）。

    为什么按哈希而不是按顺序切：顺序切片在用例被插入/删除时会整体错位，
    于是"留出集"悄悄混进了调参用过的句子 —— 那留出集就白留了。
    """
    dev, holdout = [], []
    threshold = int(holdout_ratio * 100)
    for c in cases:
        bucket = int(_sha1(str(c.get(key, "")))[:8], 16) % 100
        (holdout if bucket < threshold else dev).append(c)
    return {"dev": dev, "holdout": holdout,
            "dev_n": len(dev), "holdout_n": len(holdout),
            "holdout_ratio": holdout_ratio}


def rate(details: list[dict], field: str = "hit") -> float:
    """命中率（百分比，一位小数）；空集返回 0.0。"""
    if not details:
        return 0.0
    return round(sum(1 for d in details if d.get(field)) * 100 / len(details), 1)


def metrics_for_split(details: list[dict], cases: list[dict]) -> dict:
    """把逐条结果按 dev / holdout 归并，给出**两个分母各自**的指标。"""
    sp = split_cases(cases)
    holdout_q = {str(c.get("query", "")) for c in sp["holdout"]}
    dev_d = [d for d in details if str(d.get("query", "")) not in holdout_q]
    hold_d = [d for d in details if str(d.get("query", "")) in holdout_q]
    return {
        "all": {"n": len(details), "hit_rate": rate(details),
                "hit1_rate": rate(details, "hit_at_1")},
        "dev": {"n": len(dev_d), "hit_rate": rate(dev_d), "hit1_rate": rate(dev_d, "hit_at_1")},
        "holdout": {"n": len(hold_d), "hit_rate": rate(hold_d),
                    "hit1_rate": rate(hold_d, "hit_at_1")},
    }


def compare(baseline: dict, variant: dict) -> dict:
    """逐条对比两版评测结果，**把退步单独列出来**（"能报负收益"）。

    `baseline` / `variant` 都是 `{"details": [{query, hit, hit_at_1}, ...]}`。
    返回：整体差值 + 变好的条目 + **变差的条目**（含各自的前几条结果，便于复盘）。
    """
    b = {str(d.get("query", "")): d for d in (baseline.get("details") or [])}
    v = {str(d.get("query", "")): d for d in (variant.get("details") or [])}
    shared = [q for q in v if q in b]
    better, worse = [], []
    for q in shared:
        bh, vh = bool(b[q].get("hit")), bool(v[q].get("hit"))
        if vh and not bh:
            better.append({"query": q, "variant_top": (v[q].get("top") or [])[:2]})
        elif bh and not vh:
            worse.append({"query": q, "baseline_top": (b[q].get("top") or [])[:2],
                          "variant_top": (v[q].get("top") or [])[:2]})
    delta = round(rate(list(v.values())) - rate(list(b.values())), 1)
    return {
        "shared_n": len(shared),
        "baseline_hit_rate": rate(list(b.values())),
        "variant_hit_rate": rate(list(v.values())),
        "delta": delta,
        "better": better, "worse": worse,
        "better_n": len(better), "worse_n": len(worse),
        # 结论按**命中率差值**给（这是报告的头条数字）；条目级增减单独列，
        # 并显式标出"整体变好但有条目变差"——这种最容易被只报总数的人藏掉。
        "verdict": ("变好" if delta > 0 else
                    "变差（必须如实报告）" if delta < 0 else "持平"),
        "has_regressions": bool(worse),
        "note": ("整体变好，但有 %d 条变差（已逐条列出）" % len(worse) if delta > 0 and worse
                 else "整体变差：不要只报涨的那一版" if delta < 0
                 else "整体持平"),
    }
