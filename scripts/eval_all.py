# scripts/eval_all.py — 评测统一入口（任务卡 13）
# -*- coding: utf-8 -*-
"""一条命令跑完所有评测，并给出**可复算**的报告（含留出集与负收益）。

用法：
  python scripts/eval_all.py                 # 全量：语料对快照 → RAG（混合/纯词法）→ 意图评测
  python scripts/eval_all.py --fast          # 只跑 RAG（两版对比），跳过意图评测（不需要 LLM key）
  python scripts/eval_all.py --out .shots/eval-report   # 报告落盘（.json + .md 各一份）

报告里必须出现的东西（卡13 的验收点）：
  ① **语料指纹与漂移**：本次数字是在哪批语料上测的；语料变了会明确列出变了哪些条目；
  ② **留出集单列**：dev / holdout 两个分母各自的命中率（holdout 是"没拿来调参"的那部分）；
  ③ **逐条输出**：每条查询命中了什么、走的是哪条检索路径；
  ④ **负收益如实报**：混合检索相对纯词法**变差的条目**会单独列出（只报涨的那版 = 自欺）。
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:  # Windows 控制台默认 GBK，✅/⚠️ 这类符号会直接抛 UnicodeEncodeError
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import config  # noqa: E402
from data.db_core import init_db  # noqa: E402
from utils.eval_split import (corpus_digest, corpus_rows, diff_corpus,  # noqa: E402
                              metrics_for_split)
from scripts.rag_eval import load_golden  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(ROOT, "tests", "llm_eval", "corpus_snapshot.json")


def _corpus_report() -> dict:
    """语料指纹 + 与快照的漂移（评测数字的"分母"是否变了）。"""
    rows = corpus_rows()
    digest = corpus_digest(rows)
    out = {"count": len(rows), "digest": digest, "snapshot": {}, "drift": None}
    try:
        with open(SNAPSHOT, encoding="utf-8") as f:
            snap = json.load(f)
        out["snapshot"] = {"count": snap.get("count"), "digest": snap.get("digest"),
                           "frozen_at": snap.get("frozen_at")}
        out["drift"] = diff_corpus(snap.get("rows") or [], rows)
    except Exception as e:  # noqa: BLE001 — 没有快照不影响评测，但要说明
        out["snapshot"] = {"error": f"没有语料快照（{str(e)[:60]}）"}
    return out


def _rag_once(topk: int, no_embedding: bool) -> dict:
    from scripts.rag_eval import run
    return run(topk=topk, verbose=False, no_embedding=no_embedding)


def _intent_eval() -> dict:
    """意图/文案评测（需要 LLM key；没有就如实跳过，不许假装跑过）。"""
    try:
        from scripts.llm_eval import run as llm_run  # noqa: F401
    except Exception as e:  # noqa: BLE001
        return {"skipped": True, "reason": f"评测脚本不可用：{str(e)[:80]}"}
    try:
        r = llm_run()
        return {"skipped": False, **(r if isinstance(r, dict) else {"result": r})}
    except Exception as e:  # noqa: BLE001 — 缺 key/网络不通都算"跳过"，并写清原因
        return {"skipped": True, "reason": str(e)[:120]}


def _write_md(path: str, report: dict) -> None:
    c = report["corpus"]
    rag = report["rag"]
    lex = report["rag_lexical_only"]
    cmp_ = report["compare"]
    L = []
    L.append("# 评测报告（可复算）\n")
    L.append(f"- 生成时间：{report['generated_at']}")
    L.append(f"- 语料：{c['count']} 条，指纹 `{c['digest']}`"
             + (f"，快照指纹 `{c['snapshot'].get('digest')}`（{c['snapshot'].get('frozen_at')}）"
                if c.get("snapshot", {}).get("digest") else "，**没有语料快照**"))
    if c.get("drift") and not c["drift"]["same"]:
        d = c["drift"]
        L.append(f"- ⚠️ **语料相对快照有漂移**：新增 {len(d['added'])} / 删除 {len(d['removed'])} /"
                 f" 内容改动 {len(d['changed'])} —— 数字变化可能来自语料，不全是检索改进")
    else:
        L.append("- 语料与快照一致（本次数字与快照可比）")
    L.append(f"- 用例：{rag['cases']} 条（top-{rag['topk']}）\n")
    L.append("## 指标（dev / holdout 分开报）\n")
    L.append("| 版本 | 分母 | 条数 | top-k 命中率 | hit@1 |")
    L.append("|---|---|---:|---:|---:|")
    for name, m in (("混合检索", rag["splits"]), ("纯词法（对比基线）", lex["splits"])):
        for split in ("all", "dev", "holdout"):
            s = m[split]
            L.append(f"| {name} | {split} | {s['n']} | {s['hit_rate']}% | {s['hit1_rate']}% |")
    L.append("")
    L.append("## 负收益对照（混合检索 vs 纯词法）\n")
    L.append(f"- 整体：{cmp_['baseline_hit_rate']}% → {cmp_['variant_hit_rate']}%"
             f"（差 {cmp_['delta']:+}）→ 结论：**{cmp_['verdict']}**")
    L.append(f"- 变好 {cmp_['better_n']} 条 / **变差 {cmp_['worse_n']} 条**")
    if cmp_["worse"]:
        L.append("\n变差的条目（必须如实列出，不藏）：\n")
        for w in cmp_["worse"][:20]:
            L.append(f"- `{w['query']}`：纯词法命中 `{w['baseline_top']}`，混合后 `{w['variant_top']}`")
    L.append("\n## 逐条结果（混合检索）\n")
    for d in rag["details"]:
        L.append(f"- {'✅' if d['hit_at_1'] else ('~' if d['hit'] else '❌')} `{d['query']}`"
                 f" → 路径 {d['route']} | top1: {(d['top'] or ['—'])[0]}")
    ie = report["intent"]
    L.append("\n## 意图/文案评测\n")
    L.append(f"- {'已跳过：' + str(ie.get('reason')) if ie.get('skipped') else json.dumps(ie, ensure_ascii=False)[:400]}")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(L) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="评测统一入口（卡13）")
    ap.add_argument("--topk", type=int, default=3)
    ap.add_argument("--fast", action="store_true", help="跳过意图评测（不需要 LLM key）")
    ap.add_argument("--out", default="", help="报告前缀（会生成 .json 与 .md）")
    args = ap.parse_args()

    init_db(config.DB_PATH)
    cases = load_golden()
    if not cases:
        print("❌ 找不到金标用例（tests/llm_eval/rag_golden.jsonl）")
        return 1

    print("=" * 78)
    print("评测统一入口（卡13）：语料快照 → RAG 两版对比 → 留出集 → 负收益对照")
    print("=" * 78)

    corpus = _corpus_report()
    print(f"语料：{corpus['count']} 条，指纹 {corpus['digest']}")
    if corpus.get("drift") and not corpus["drift"]["same"]:
        d = corpus["drift"]
        print(f"  ⚠️ 与快照有漂移：新增 {len(d['added'])} / 删除 {len(d['removed'])} / 改动 {len(d['changed'])}")

    rag = _rag_once(args.topk, no_embedding=False)
    lex = _rag_once(args.topk, no_embedding=True)
    rag["splits"] = metrics_for_split(rag["details"], cases)
    lex["splits"] = metrics_for_split(lex["details"], cases)

    from utils.eval_split import compare
    cmp_ = compare(lex, rag)   # baseline=纯词法，variant=混合检索

    intent = {"skipped": True, "reason": "fast 模式"} if args.fast else _intent_eval()

    report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "corpus": corpus, "cases": len(cases),
              "rag": rag, "rag_lexical_only": lex, "compare": cmp_, "intent": intent}

    print(f"\nRAG（混合检索） 全部 {rag['splits']['all']['hit_rate']}% | "
          f"dev {rag['splits']['dev']['hit_rate']}% | holdout {rag['splits']['holdout']['hit_rate']}%")
    print(f"RAG（纯词法）   全部 {lex['splits']['all']['hit_rate']}% | "
          f"dev {lex['splits']['dev']['hit_rate']}% | holdout {lex['splits']['holdout']['hit_rate']}%")
    print(f"对照：{cmp_['baseline_hit_rate']}% → {cmp_['variant_hit_rate']}%（{cmp_['delta']:+}）"
          f"｜变好 {cmp_['better_n']} / 变差 {cmp_['worse_n']} → {cmp_['verdict']}")
    if cmp_["worse"]:
        print("  变差条目（如实列出）：")
        for w in cmp_["worse"][:5]:
            print(f"    - {w['query']}：纯词法 {w['baseline_top']} → 混合 {w['variant_top']}")

    if args.out:
        base = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
        os.makedirs(os.path.dirname(base), exist_ok=True)
        with open(base + ".json", "w", encoding="utf-8", newline="") as f:
            json.dump(report, f, ensure_ascii=False, indent=1)
        _write_md(base + ".md", report)
        print(f"\n报告已写入：{os.path.relpath(base, ROOT)}.json / .md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
