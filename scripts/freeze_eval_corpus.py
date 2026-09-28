# scripts/freeze_eval_corpus.py — 固定评测语料快照（任务卡 13）
# -*- coding: utf-8 -*-
"""把**评测用的知识库语料**冻结成快照（含每条的正文指纹 + 整批指纹）。

为什么要冻结：命中率是"检索质量"的指标，**分母是语料**。语料边跑边改（有人往知识库加了条目），
命中率自然会变，但谁也算不清"是检索变好了还是语料变多了"。所以每次评测前先对快照：

  python scripts/freeze_eval_corpus.py            # 生成/更新快照（写 tests/llm_eval/corpus_snapshot.json）
  python scripts/freeze_eval_corpus.py --check    # 只检查当前库与快照是否一致（CI/评测前用）

漂移检查会明确列出**新增/删除/内容被改**的条目 id 与标题 —— 评测报告据此标注
"本次数字是在哪批语料上测的"。
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
from utils.eval_split import corpus_digest, corpus_rows, diff_corpus  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAPSHOT = os.path.join(ROOT, "tests", "llm_eval", "corpus_snapshot.json")


def load_snapshot() -> dict:
    if not os.path.isfile(SNAPSHOT):
        return {}
    with open(SNAPSHOT, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description="固定评测语料快照")
    ap.add_argument("--check", action="store_true", help="只检查漂移，不写文件")
    args = ap.parse_args()

    init_db(config.DB_PATH)
    rows = corpus_rows()
    digest = corpus_digest(rows)
    snap = load_snapshot()

    print(f"当前语料：{len(rows)} 条（指纹 {digest}）")
    if snap:
        print(f"快照语料：{len(snap.get('rows') or [])} 条（指纹 {snap.get('digest')}）")
        d = diff_corpus(snap.get("rows") or [], rows)
        if d["same"] and snap.get("digest") == digest:
            print("✅ 语料与快照一致（本次评测数字与快照可比）")
            return 0
        print("⚠️ 语料与快照不一致：")
        if d["added"]:
            print(f"  新增 {len(d['added'])} 条：{d['added'][:10]}")
        if d["removed"]:
            print(f"  删除 {len(d['removed'])} 条：{d['removed'][:10]}")
        if d["changed"]:
            print(f"  内容被改 {len(d['changed'])} 条：" +
                  "、".join(f"#{c['id']} {c['title'][:16]}" for c in d["changed"][:10]))
        print("  → 评测报告里必须标注这一点：**数字变了可能只是语料变了**。")
        if args.check:
            return 1

    if args.check:
        print("（没有快照文件：先跑一次 `python scripts/freeze_eval_corpus.py` 生成）")
        return 1

    payload = {"digest": digest, "frozen_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "count": len(rows), "rows": rows}
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    with open(SNAPSHOT, "w", encoding="utf-8", newline="") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"✅ 已写入快照：{os.path.relpath(SNAPSHOT, ROOT)}（{len(rows)} 条，指纹 {digest}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
