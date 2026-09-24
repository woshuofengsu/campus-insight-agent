# -*- coding: utf-8 -*-
"""清理演示库里的**压测/测试残留**（现场数据体面用）。

**为什么需要**：`stress_test.py` / `smoke_test.py` 跑过之后会在真库里留下大量
「压测工单NN」「压测提案NN」。实测（2026-09-24）污染面：
    工单 354 条里 179 条是压测残留（占 51%）
    提案 201 条里 177 条是压测残留（占 88%，且**最新 12 条全是**，公示链里还有 2 条）
    健康咨询 180 条里 177 条 · 政策提问 122 条里 53 条
后果：网格员打开工单管理、居民打开提案页，**第一屏就是"压测提案37"**——评委当场就看出库是脏的；
而且"工单 352 条"这种数字是被垃圾撑起来的，被追问会很难看。

**安全设计（务必遵守）**：
  1. **默认只预演**（`--dry-run` 隐含）：只统计、不写库；
  2. **真删之前先整库备份**到 `.shots/db-backup-before-purge-<时间戳>.db`（可整库回滚）；
  3. 只删**匹配压测命名模板**的行（`压测`/`测试`/`smoke`/`stress` + 编号后缀），
     不碰任何其它数据；同时清掉这些行的从属记录（投票/已读），避免留下孤儿行；
  4. 删除后打印各表前后条数，便于与 PPT/稿子重新对齐。

用法：
    python scripts/demo_purge_stress.py                # 预演（推荐先跑）
    python scripts/demo_purge_stress.py --apply        # 真删（先自动备份）
    python scripts/demo_purge_stress.py --apply --no-backup   # 不备份（不建议）
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(ROOT, "data", "community_insight.db")

# (表, 判据列, 附带的从属清理) —— 判据只认"压测/测试 + 命名"的行
TARGETS = [
    ("proposals", "title", [("proposal_votes", "proposal_id", "id")]),
    ("community_issues", "title", [("issue_supplements", "issue_id", "id")]),
    ("health_consults", "content", []),
    ("policy_questions", "question", []),
    ("medication_reminders", "drug_name", []),
]
PATTERNS = ["压测%", "%压测工单%", "%压测提案%", "stress%", "smoke%", "测试工单%", "测试提案%"]


def _match_clause(col: str) -> tuple[str, list]:
    parts = [f"{col} LIKE ?" for _ in PATTERNS]
    return "(" + " OR ".join(parts) + ")", list(PATTERNS)


def count(conn, table: str, where: str, args: list) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", args).fetchone()[0]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="真正删除（默认只预演）")
    ap.add_argument("--no-backup", action="store_true", help="跳过备份（不建议）")
    args = ap.parse_args()

    if not os.path.exists(DB):
        print(f"❌ 找不到数据库：{DB}")
        return 2

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    print("=" * 78)
    print("压测残留清理" + ("　【真删模式】" if args.apply else "　【预演模式，不写库】"))
    print("=" * 78)

    plan: list[tuple[str, str, list, int, list]] = []
    for table, col, deps in TARGETS:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if col not in cols:
            print(f"  （跳过 {table}：没有列 {col}）")
            continue
        where, wargs = _match_clause(col)
        n = count(conn, table, where, wargs)
        total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        plan.append((table, where, wargs, n, deps))
        print(f"  {table:<20} {n:>4} / {total:<4} 命中清理模板")

    total_hits = sum(p[3] for p in plan)
    if not total_hits:
        print("\n✅ 没有匹配的压测残留，无需清理。")
        return 0

    if not args.apply:
        print(f"\n预演结论：将删除 {total_hits} 行。真删请加 --apply（会先整库备份）。")
        return 1

    if not args.no_backup:
        ts = time.strftime("%Y%m%d-%H%M%S")
        backup = os.path.join(ROOT, ".shots", f"db-backup-before-purge-{ts}.db")
        os.makedirs(os.path.dirname(backup), exist_ok=True)
        shutil.copy2(DB, backup)
        print(f"\n已整库备份 → {backup}（回滚：直接拷回 data/community_insight.db）")

    deleted = 0
    for table, where, wargs, _n, deps in plan:
        ids = [r[0] for r in conn.execute(f"SELECT id FROM {table} WHERE {where}", wargs)]
        for dep_table, dep_col, ref_col in deps:
            try:
                dcols = [r[1] for r in conn.execute(f"PRAGMA table_info({dep_table})")]
                if dep_col in dcols and ids:
                    ph = ",".join("?" * len(ids))
                    conn.execute(f"DELETE FROM {dep_table} WHERE {dep_col} IN ({ph})", ids)
            except sqlite3.Error as e:
                print(f"    （{dep_table} 从属清理跳过：{e}）")
        cur = conn.execute(f"DELETE FROM {table} WHERE {where}", wargs)
        deleted += cur.rowcount
        print(f"  已删 {table}：{cur.rowcount} 行")
    conn.commit()

    print("\n清理后各表条数：")
    for table, _c, _d in ((t, c, d) for t, c, d in TARGETS):
        n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<20} {n}")
    print(f"\n✅ 共删除 {deleted} 行。**接下来必须重新核对演示脚本/PPT 里的数字**"
          f"（跑 `python scripts/check_claims.py` 与 `python scripts/demo_reset.py`）。")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
