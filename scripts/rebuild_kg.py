# scripts/rebuild_kg.py — 重建轻量知识图谱（命令行入口）
# -*- coding: utf-8 -*-
"""为什么需要它：知识图谱（`kg_entity` / `kg_relation` / `kg_mention`）是**从业务表派生**的数据——
工单与政策新增/修改后，图谱需要重建才能反查得到。图形界面里可以点「重建」，但在命令行/自检脚本里也需要入口。

以前 `scripts/demo_acceptance.py` 的修复提示让人跑本脚本，而**本脚本并不存在**（终局核验时发现：
提示指向不存在的脚本 = 演示现场会白跑一趟）。这里补上真实入口，幂等可重复执行。

用法：
    python scripts/rebuild_kg.py            # 重建并打印统计
    python scripts/rebuild_kg.py --stats    # 只看当前统计，不重建

实现说明：重建逻辑在 `data/db_kg.py::build_graph`（会先清空 kg_relation / kg_mention 再按来源表重新抽取，
因此可重复执行）；本脚本只负责"初始化库 + 调用 + 打印"。
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main() -> int:
    ap = argparse.ArgumentParser(description="重建轻量知识图谱")
    ap.add_argument("--stats", action="store_true", help="只打印统计，不重建")
    ap.add_argument("--limit", type=int, default=500, help="单次参与抽取的记录上限（默认 500）")
    args = ap.parse_args()

    import config
    from data.database import init_db

    init_db(config.DB_PATH)
    from data.db_kg import build_graph, graph_stats

    if not args.stats:
        print("正在重建知识图谱 …")
        out = build_graph(limit=args.limit)
        print(f"  抽取结果：{out}")
    st = graph_stats()
    print("当前图谱统计：")
    for k, v in st.items():
        print(f"  {k}: {v}")
    print("\n提示：图形界面同样可重建（网格端知识图谱页），或调用 POST /api/web/agent/kg/rebuild")
    return 0


if __name__ == "__main__":
    sys.exit(main())
