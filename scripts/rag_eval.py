# scripts/rag_eval.py — RAG 检索命中率评测（U1 混合检索）
# -*- coding: utf-8 -*-
"""RAG 检索质量量化：用 golden 查询集测「同义/口语查询」的召回命中率。

用法：
  python scripts/rag_eval.py                 # 用当前配置（EMBEDDING_PROVIDER）
  python scripts/rag_eval.py --verbose       # 打印每条命中情况
  python scripts/rag_eval.py --json          # 输出 JSON（CI/报告用）
  python scripts/rag_eval.py --topk 3        # 指定 top-k（默认 3）

评测口径：
  - 每条 case 给「居民口语查询」+「期望命中的关键词集合」（命中任一即算命中该 case）
  - 命中率 = top-k 结果中含期望关键词的 case 数 / 总 case 数
  - 基线要求：无 provider（纯词法+同义词扩展）≥ 70%；有 provider（混合）≥ 85%

数据来源：tests/llm_eval/rag_golden.jsonl（与本脚本一并维护）
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

GOLDEN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tests", "llm_eval", "rag_golden.jsonl")


def load_golden(path: str = GOLDEN) -> list[dict]:
    cases = []
    if not os.path.isfile(path):
        return cases
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            cases.append(json.loads(line))
    return cases


def run(topk: int = 3, verbose: bool = False, no_embedding: bool = False) -> dict:
    from config import DB_PATH
    from data.db_core import init_db
    init_db(DB_PATH)
    if no_embedding:
        # 对比基线：强制关闭语义向量 → 只走词法（+同义词扩展），用于量化语义增益
        import utils.embedding as E
        E.is_enabled = lambda: False
    from data.db_policy import search_published_knowledge
    from utils.embedding import describe

    cases = load_golden()
    hits, details = 0, []
    for c in cases:
        q = c["query"]
        expects = c.get("expect_any") or []
        results = search_published_knowledge(q, top_k=topk)
        blob = " ".join(
            f"{r.get('title', '')} {r.get('keywords', '')} {r.get('content', '')}"
            for r in results)
        hit = any(k in blob for k in expects)
        route = results[0].get("retrieval") if results else "none"
        hits += 1 if hit else 0
        details.append({"query": q, "hit": hit, "route": route,
                        "top": [r.get("title") for r in results]})
        if verbose:
            mark = "✓" if hit else "✗"
            print(f"[{mark}] {q} → {route} | {details[-1]['top'][:2]}")
    n = len(cases)
    return {"cases": n, "hits": hits,
            "hit_rate": round(hits * 100 / n, 1) if n else 0.0,
            "topk": topk, "embedding": describe(), "details": details}


def main():
    ap = argparse.ArgumentParser(description="RAG 检索命中率评测（U1）")
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--json", action="store_true")
    # 对比基线：强制关闭语义向量（量化「混合检索」相对「纯词法」的增益）
    ap.add_argument("--no-embedding", action="store_true",
                    help="强制纯词法（关闭语义向量），用于对比实验")
    # 阈值：无 provider 走纯词法（含同义词扩展）基线较低；有 provider 要求更高
    ap.add_argument("--threshold", type=float, default=None)
    args = ap.parse_args()

    r = run(topk=args.topk, verbose=args.verbose, no_embedding=args.no_embedding)
    emb = r["embedding"]
    threshold = args.threshold
    if threshold is None and not args.no_embedding:
        threshold = 85.0 if emb.get("enabled") else 70.0

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        if args.no_embedding:
            mode = "纯词法（同义词扩展，语义向量已强制关闭）"
        else:
            mode = f"混合检索（{emb['provider']}/{emb['model']}）" if emb.get("enabled") else "纯词法（同义词扩展）"
        print("=== RAG 检索命中率评测（U1）===")
        print(f"模式：{mode} | 用例 {r['cases']} 条 | top-{r['topk']} 命中 {r['hits']} 条 → 命中率 {r['hit_rate']}%")
        if args.no_embedding:
            print("（对比基线：不加 --no-embedding 即混合检索模式，可量化语义向量增益）")
        else:
            print(f"阈值：{threshold}% → {'✅ 达标' if r['hit_rate'] >= threshold else '❌ 未达标'}")
            if not emb.get("enabled"):
                print("提示：配置 EMBEDDING_PROVIDER=bailian + DASHSCOPE_API_KEY 可启用语义向量，命中率进一步提升。")
    if args.no_embedding:
        sys.exit(0)
    sys.exit(0 if r["hit_rate"] >= threshold else 1)


if __name__ == "__main__":
    main()
