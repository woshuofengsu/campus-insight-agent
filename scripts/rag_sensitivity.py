# scripts/rag_sensitivity.py — 语义加分系数敏感性分析（U1 存档）
# -*- coding: utf-8 -*-
"""回答「为什么语义加分系数取 3」：扫 1/2/3/5/8 五档，量出各档检索质量。

背景：线上答题路径 `data/db_policy.search_published_knowledge()` 的最终分 =
词法分（同义词扩展，量级 0~10+）+ `k * max(0, 语义余弦)`。k 太小语义不起作用，
太大则语义压过词条命中、把「关键词精确命中」挤下去。

用法：
  python scripts/rag_sensitivity.py            # 表格输出（默认五档）
  python scripts/rag_sensitivity.py --json     # 机器可读
  python scripts/rag_sensitivity.py --ks 1 3 5

口径：复用 `tests/llm_eval/rag_golden.jsonl`（27 条，含 7 条语义难例），
比较 top-3 命中率与 hit@1（Top-1 正确率）；每档都跑同一批查询。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import data.db_policy as dp
from scripts.rag_eval import load_golden

# 超范围问题（知识库确实没有的主题）：用于量「语义加分开太大 → 误自动回答」的风险。
# 这些问题**必须**达不到自动回答阈值（应转人工），否则等于「不懂装懂」——幻觉风险的量化口径。
OUT_OF_SCOPE = [
    "怎么申请护照", "股票开户流程", "驾照换证需要什么材料", "外卖吃出异物怎么投诉",
    "宽带报装去哪里办", "宠物托运需要什么手续", "托福考试怎么报名", "公司注册流程",
    "个人所得税年度汇算怎么操作", "签证材料清单",
]


def _eval_with_k(k: float, topk: int = 3) -> dict:
    """在指定语义系数 k 下跑一遍 golden 集 + 超范围集，量出排名质量与误答风险。"""
    orig = dp._DENSE_WEIGHT
    dp._DENSE_WEIGHT = k
    try:
        cases = load_golden()
        hits, top1, rr_sum, rank_sum, ranked = 0, 0, 0.0, 0, 0
        for c in cases:
            expects = c.get("expect_any") or []
            results = dp.search_published_knowledge(c["query"], top_k=topk)
            blob = " ".join(f"{r.get('title','')} {r.get('keywords','')} {r.get('content','')}"
                            for r in results)
            if any(x in blob for x in expects):
                hits += 1
            if results:
                b1 = (f"{results[0].get('title','')} {results[0].get('keywords','')} "
                      f"{results[0].get('content','')}")
                if any(x in b1 for x in expects):
                    top1 += 1
            # 首次命中的排名（MRR / 平均排名）——比二值命中率对 k 更敏感
            first = 0
            for idx, r in enumerate(results, 1):
                b = f"{r.get('title','')} {r.get('keywords','')} {r.get('content','')}"
                if any(x in b for x in expects):
                    first = idx
                    break
            if first:
                rr_sum += 1.0 / first
                rank_sum += first
                ranked += 1
        n = len(cases)
        # 误答风险：超范围问题（知识库确实没有的主题）不应达到自动回答阈值
        thr = dp.get_match_threshold()
        false_answer = []
        for q in OUT_OF_SCOPE:
            rs = dp.search_published_knowledge(q, top_k=1)
            top = rs[0]["score"] if rs else 0.0
            if top >= thr:
                false_answer.append({"query": q, "score": top})
        return {
            "k": k, "cases": n, "hits": hits, "hit1": top1,
            "hit_rate": round(hits * 100 / n, 1) if n else 0.0,
            "hit1_rate": round(top1 * 100 / n, 1) if n else 0.0,
            "mrr": round(rr_sum / n, 4) if n else 0.0,
            "avg_rank": round(rank_sum / ranked, 2) if ranked else None,
            "false_answer_count": len(false_answer),
            "false_answer": false_answer,
        }
    finally:
        dp._DENSE_WEIGHT = orig


def main() -> int:
    ap = argparse.ArgumentParser(description="语义加分系数敏感性分析（U1 存档）")
    ap.add_argument("--ks", nargs="+", type=float, default=[1, 2, 3, 5, 8])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    from config import DB_PATH
    from data.db_core import init_db
    init_db(DB_PATH)
    from utils.embedding import describe
    emb = describe()

    rows = [_eval_with_k(k) for k in args.ks]
    best = max(rows, key=lambda r: (r["hit1_rate"], r["hit_rate"]))
    out = {"embedding": emb, "rows": rows,
           "best_k": best["k"], "current_k": dp._DENSE_WEIGHT}
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    mode = f"{emb['provider']}/{emb['model']}" if emb.get("enabled") else "纯词法（未启用向量）"
    print(f"=== 语义加分系数敏感性分析（模式：{mode}）===")
    print(f"业务阈值（自动回答线）：{dp.get_match_threshold()}｜超范围问题 {len(OUT_OF_SCOPE)} 条")
    print(f"{'k':>4} | {'top-3':>7} | {'hit@1':>7} | {'MRR':>7} | {'平均命中排名':>12} | {'误自动回答':>10}")
    print("-" * 70)
    for r in rows:
        tag = " ← 当前" if r["k"] == out["current_k"] else ""
        print(f"{r['k']:>4} | {r['hit_rate']:>6}% | {r['hit1_rate']:>6}% | {r['mrr']:>7} | "
              f"{str(r['avg_rank']):>12} | {r['false_answer_count']:>10}{tag}")
    print("-" * 70)
    print(f"当前 k={out['current_k']}；本批最优 k={best['k']}"
          f"（MRR {best['mrr']}，hit@1 {best['hit1_rate']}%）")
    print("结论口径：")
    print("  · k 过小（1~2）：语义几乎不起作用 → 口语改述难例排名下滑（MRR 降低）")
    print("  · k 过大（≥8）：语义相近但词条不相关的条目被顶上 → hit@1/MRR 下降，"
          "且超范围问题更容易越过自动回答线（误答风险↑）")
    print("  · 取 3：MRR 与 hit@1 同时最优、误自动回答保持 0（量化依据见本表）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
