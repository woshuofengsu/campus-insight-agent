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
    _orig_is_enabled = None
    if no_embedding:
        # 对比基线：临时关闭语义向量 → 只走词法（+同义词扩展），用于量化语义增益。
        # 注意必须在 finally 里恢复：直接改写模块函数会污染同进程内后续调用/测试。
        import utils.embedding as E
        _orig_is_enabled = E.is_enabled
        E.is_enabled = lambda: False
    try:
        return _run_cases(topk=topk, verbose=verbose)
    finally:
        if _orig_is_enabled is not None:
            import utils.embedding as E
            E.is_enabled = _orig_is_enabled


def _run_cases(topk: int = 3, verbose: bool = False) -> dict:
    from data.db_policy import search_published_knowledge
    from utils.embedding import describe

    cases = load_golden()
    hits, top1_hits, details = 0, 0, []
    region_cases = region_ok = 0
    for c in cases:
        q = c["query"]
        expects = c.get("expect_any") or []
        # 属地用例（地区识别 WS6）：case 里可选带 "region": "<社区名>"，
        # 用来证明"同一句话在给定属地下，本地条目优先、且全国条目仍可兜底"。
        region = None
        if c.get("region"):
            from utils.region import resolve_region
            region = resolve_region(c["region"])
        results = search_published_knowledge(q, top_k=topk, region=region)
        blob = " ".join(
            f"{r.get('title', '')} {r.get('keywords', '')} {r.get('content', '')}"
            for r in results)
        hit = any(k in blob for k in expects)
        # hit@1：更严格——只看第一条是否命中（Top-1 正确性，避免「靠后面的结果凑命中」）
        blob1 = ""
        if results:
            r0 = results[0]
            blob1 = f"{r0.get('title', '')} {r0.get('keywords', '')} {r0.get('content', '')}"
        hit1 = bool(results) and any(k in blob1 for k in expects) if expects else False
        # "expect_top1": true 的用例要求 Top-1 命中（属地用例用它来断言"本地优先"）
        if c.get("expect_top1"):
            region_cases += 1
            if hit1:
                region_ok += 1
        route = results[0].get("retrieval") if results else "none"
        hits += 1 if hit else 0
        top1_hits += 1 if hit1 else 0
        details.append({"query": q, "hit": hit, "hit_at_1": hit1, "route": route,
                        "region": c.get("region", ""),
                        "region_level": results[0].get("region_level", "") if results else "",
                        "top": [r.get("title") for r in results]})
        if verbose:
            mark = "✓" if hit1 else ("~" if hit else "✗")
            print(f"[{mark}] {q} → {route} | {details[-1]['top'][:2]}")
    n = len(cases)
    return {"cases": n, "hits": hits, "hit1": top1_hits,
            "hit_rate": round(hits * 100 / n, 1) if n else 0.0,
            "hit1_rate": round(top1_hits * 100 / n, 1) if n else 0.0,
            "region_cases": region_cases, "region_top1_ok": region_ok,
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
        print(f"模式：{mode} | 用例 {r['cases']} 条")
        print(f"  top-{r['topk']} 命中率：{r['hit_rate']}%（{r['hits']}/{r['cases']}）")
        print(f"  hit@1（Top-1 正确率）：{r['hit1_rate']}%（{r['hit1']}/{r['cases']}）")
        if r.get("region_cases"):
            print(f"  属地用例 Top-1 优先命中：{r['region_top1_ok']}/{r['region_cases']}"
                  "（同一句话在给定属地下本地条目优先）")
        if args.no_embedding:
            print("（对比基线：不加 --no-embedding 即混合检索模式，可量化语义向量增益）")
        else:
            print(f"阈值：top-k {threshold}% → {'✅ 达标' if r['hit_rate'] >= threshold else '❌ 未达标'}")
            if not emb.get("enabled"):
                print("提示：配置 EMBEDDING_PROVIDER=bailian + DASHSCOPE_API_KEY 可启用语义向量，命中率进一步提升。")
    if args.no_embedding:
        sys.exit(0)
    sys.exit(0 if r["hit_rate"] >= threshold else 1)


if __name__ == "__main__":
    main()
