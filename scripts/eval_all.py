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


def _rag_once(topk: int, no_embedding: bool, path: str = "threshold") -> dict:
    from scripts.rag_eval import run
    return run(topk=topk, verbose=False, no_embedding=no_embedding, path=path)


def _adversarial_eval() -> dict:
    """对抗集（相似但错误 / 口语错别字 / 敏感医疗法律 / 跨社区）：正面回答"100% 是不是过拟合"。"""
    try:
        from scripts.rag_eval import run_adversarial
        return run_adversarial(db_path=config.DB_PATH)
    except Exception as e:  # noqa: BLE001
        return {"cases": 0, "error": f"对抗集评测不可用：{str(e)[:120]}"}


def _refusal_eval() -> dict:
    """无证据不许编（v2 §11.4）：走产品入口 `ask_question`，在**临时副本**上判"该不该答"。

    显式把评测库传进去（`config.DB_PATH`）：它是模块级全局，测试里可能被改过，
    不校验就可能悄悄测到"另一个库"上并给出看似正常的数字。
    返回值里带 `kb_published`（本次测的库里有几条已发布知识）——**数字可比性的前提**，
    报告与门禁都会核对它。
    """
    try:
        from scripts.rag_eval import run_refusal
        return run_refusal(db_path=config.DB_PATH)
    except Exception as e:  # noqa: BLE001 — 评测不可用要如实说明，不许悄悄给 0
        return {"error": f"拒答评测不可用：{str(e)[:120]}"}


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
    L.append("> **每条数字都要看它来自哪条检索入口**（v2 §11.2）：两条线上路径客观并存、用途不同——"
             "`阈值判定路径`是居民端政策问答作答用的（词法分+语义加分 vs 业务阈值），"
             "`RRF 融合路径`是 Agent 侧注入 LLM 上下文用的。只报一条就等于「评测测 A、产品用 B」。\n")
    L.append("| 版本 | 检索入口 | 分母 | 条数 | top-k 命中率 | hit@1 |")
    L.append("|---|---|---|---:|---:|---:|")
    hyb = report.get("rag_agent_path") or {}
    for name, m, path_label in (("混合检索", rag["splits"], "阈值判定路径（居民端问答）"),
                                ("混合检索", (hyb.get("splits") or {}), "RRF 融合路径（Agent 上下文）"),
                                ("纯词法（对比基线）", lex["splits"], "阈值判定路径（关向量）")):
        for split in ("all", "dev", "holdout"):
            s = m.get(split)
            if not s:
                continue
            L.append(f"| {name} | {path_label} | {split} | {s['n']} | {s['hit_rate']}% | {s['hit1_rate']}% |")
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
    rf = report.get("refusal") or {}
    L.append("\n## 拒答口径：无证据不许编（v2 §11.4）\n")
    if rf.get("error"):
        L.append(f"- ⚠️ 本次没跑成：{rf['error']}")
    elif not rf.get("cases"):
        L.append("- ⚠️ 评测集为空（tests/llm_eval/refusal_set.jsonl）")
    else:
        L.append(f"- 走**产品入口** `ask_question`（阈值按社区取、敏感/医疗法律先转人工、弱证据转人工），"
                 f"在数据库**临时副本**上跑（不污染库里的真实提问记录）")
        L.append(f"- 评测库：`{rf.get('db', '')}`，已发布知识 **{rf.get('kb_published')} 条**"
                 f"（数字可比性的前提：换了库/换了语料，本节的百分比不可直接沿用）")
        L.append(f"- 样本指纹：`{rf.get('set_digest', '')}`（`tests/llm_eval/refusal_set.jsonl`，"
                 f"{rf.get('cases')} 条 —— 加注释/调序不改指纹，改用例必变）")
        L.append(f"- 无依据问题（{rf['refuse_total']} 条）：**{rf['refused']} 条没有自动回答**"
                 f"（{rf['refusal_rate']}%，要求 100%）")
        L.append(f"- 控制组（{rf['answer_total']} 条，库里明确有依据）：**{rf['answered']} 条答上来了**"
                 f"（{rf['answer_rate']}%，要求 100% —— 防止「为了拒答把能答的也拒了」）")
        if rf.get("fabricated"):
            L.append(f"- ❌ **编造/张冠李戴（红线）**：{'、'.join(rf['fabricated'])}")
        else:
            L.append("- ✅ 无「无依据却自动回答」的条目")
        if rf.get("over_refused"):
            L.append(f"- ❌ **误拒**：{'、'.join(rf['over_refused'])}")
    adv = report.get("adversarial") or {}
    L.append("\n## 对抗集：100% 是不是过拟合（外部评审第十一轮）\n")
    if adv.get("error"):
        L.append(f"- ⚠️ 本次没跑成：{adv['error']}")
    elif not adv.get("cases"):
        L.append("- ⚠️ 评测集为空（tests/llm_eval/adversarial_set.jsonl）")
    else:
        L.append(f"- 样本指纹 `{adv.get('set_digest', '')}`（{adv['cases']} 条）· 评测库 `{adv.get('db', '')}`"
                 f"（已发布知识 {adv.get('kb_published')} 条）· 检索姿态 "
                 f"`{(adv.get('embedding') or {}).get('provider', '?')}`")
        L.append("")
        L.append("| 类别 | 判据 | 通过 | 说明 |")
        L.append("|---|---|---:|---|")
        _desc = {
            "confusable": "库里没有该业务，字面像某条 → **不许拿别的当答案**（张冠李戴红线）",
            "colloquial": "库里有依据，只是口语/错别字 → 应当答上（**允许掉分**，掉了就是结论）",
            "sensitive": "医疗/法律/敏感 → **必须转人工**（安全红线，硬门禁）",
            "cross_region": "别的社区居民问属地专属问题 → 可答，但**引用地区里不许出现「海淀」**",
        }
        for k, v in (adv.get("by_kind") or {}).items():
            L.append(f"| {k} | {_desc.get(k, '')} | {v['ok']}/{v['n']} = {v['rate']}% | "
                     + ("全部通过" if not v["failed"] else "未通过：" + "、".join(f"`{q}`" for q in v["failed"]))
                     + " |")
        L.append("")
        L.append("> 这张表**不是**效果证明，而是「过拟合压力测试」：它把 48 条金标上 100% 的结论压到真实噪声下看。"
                 "`confusable` 与 `colloquial` 的失分如实列在上面，不做调参掩盖；"
                 "`sensitive` 与 `cross_region` 是安全口径，必须 100%（由 `tests/test_rag_adversarial.py` 守着）。"
                 "2026-09-29 把对抗集从 21 条扩到 60 条（四类各 15）——分母太小的话百分比没有意义。")
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
    # **另一条线上检索入口**（Agent 侧 LLM 上下文用 RRF 融合）：必须单独测，
    # 否则"100%"会被误当成"产品整条链路都 100%"（§11.2：评测测 A、产品用 B 是明确要避免的）
    rag_hybrid = _rag_once(args.topk, no_embedding=False, path="hybrid")
    rag["splits"] = metrics_for_split(rag["details"], cases)
    lex["splits"] = metrics_for_split(lex["details"], cases)
    rag_hybrid["splits"] = metrics_for_split(rag_hybrid["details"], cases)

    from utils.eval_split import compare
    cmp_ = compare(lex, rag)   # baseline=纯词法，variant=混合检索

    intent = {"skipped": True, "reason": "fast 模式"} if args.fast else _intent_eval()
    refusal = _refusal_eval()
    adversarial = _adversarial_eval()

    report = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
              "corpus": corpus, "cases": len(cases),
              "rag": rag, "rag_lexical_only": lex, "rag_agent_path": rag_hybrid,
              "compare": cmp_, "intent": intent, "refusal": refusal,
              "adversarial": adversarial}

    print(f"\nRAG（阈值判定路径·居民端问答） 全部 {rag['splits']['all']['hit_rate']}% | "
          f"dev {rag['splits']['dev']['hit_rate']}% | holdout {rag['splits']['holdout']['hit_rate']}%")
    print(f"RAG（RRF 融合路径·Agent 上下文） 全部 {rag_hybrid['splits']['all']['hit_rate']}% | "
          f"dev {rag_hybrid['splits']['dev']['hit_rate']}% | "
          f"holdout {rag_hybrid['splits']['holdout']['hit_rate']}%")
    print(f"RAG（纯词法·对比基线） 全部 {lex['splits']['all']['hit_rate']}% | "
          f"dev {lex['splits']['dev']['hit_rate']}% | holdout {lex['splits']['holdout']['hit_rate']}%")
    if adversarial.get("error"):
        print(f"对抗集：{adversarial['error']}")
    else:
        bk = adversarial.get("by_kind") or {}
        print("对抗集（回\"100% 是否过拟合\"）："
              + " | ".join(f"{k} {v['ok']}/{v['n']}={v['rate']}%" for k, v in bk.items())
              + f" · 姿态 {adversarial.get('embedding', {}).get('provider', '?')}")
        if adversarial.get("failed"):
            print(f"  对抗集未通过（如实列出）：{adversarial['failed']}")
    if refusal.get("error"):
        print(f"拒答口径：{refusal['error']}")
    else:
        print(f"拒答口径（无证据不许编，评测库已发布知识 {refusal.get('kb_published')} 条）："
              f"无依据 {refusal['refused']}/{refusal['refuse_total']}"
              f" = {refusal['refusal_rate']}% 不自动回答 | 控制组 {refusal['answered']}/"
              f"{refusal['answer_total']} = {refusal['answer_rate']}% 能答上"
              + (f" | ⚠️ 编造 {refusal['fabricated']}" if refusal.get("fabricated") else ""))
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
