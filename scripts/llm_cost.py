# scripts/llm_cost.py — LLM 用量与成本实况（对外成本口径的唯一来源）
# -*- coding: utf-8 -*-
"""为什么需要它：材料里写的"LLM 花了多少钱"是一个**会随使用变化**的数字。
以前靠人工抄一次（20 次 ¥0.0053 / 30 次 ¥0.0069 两个口径同时出现在不同文档里，评审一看就矛盾）。
现在统一口径为「库内记账快照」，并用这条命令随时复核：

    python scripts/llm_cost.py            # 打印总账 + 分模块 + 单次均价
    python scripts/llm_cost.py --json     # 机器可读（供文档/CI 引用）

口径说明：
- 数据源是 `llm_usage` 表（`agent/llm_client._record` 逐笔写入），**不是估算**；
- 含评测脚本（llm_eval）与真实业务链路（协商/政策生成/意图兜底）两类调用；
- 材料里引用时应写成「截至 <日期> 快照：N 次 / ¥X」，并注明可用本命令复核。
"""
import argparse
import json
import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def collect() -> dict:
    import config
    from data.database import init_db
    init_db(config.DB_PATH)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(cost_yuan),0) s, "
            "COALESCE(SUM(tokens_in),0) ti, COALESCE(SUM(tokens_out),0) to_, "
            "MAX(created_at) last FROM llm_usage").fetchone()
    except sqlite3.OperationalError as e:
        return {"error": f"llm_usage 表不可读：{e}"}
    by_module = [dict(r) for r in conn.execute(
        "SELECT module, COUNT(*) n, ROUND(COALESCE(SUM(cost_yuan),0),6) s "
        "FROM llm_usage GROUP BY module ORDER BY n DESC")]
    n = row["n"] or 0
    return {
        "calls": n,
        "cost_yuan": round(row["s"] or 0.0, 6),
        "tokens_in": int(row["ti"] or 0),
        "tokens_out": int(row["to_"] or 0),
        "avg_cost_yuan": round((row["s"] or 0.0) / n, 6) if n else 0.0,
        "last_call_at": row["last"] or "",
        "by_module": by_module,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM 用量与成本实况（材料引用口径的唯一来源）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()
    data = collect()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0
    if data.get("error"):
        print("❌", data["error"])
        return 1
    print("=== LLM 用量与成本（库内记账，非估算）===")
    print(f"  调用次数：{data['calls']} 次")
    print(f"  合计成本：¥{data['cost_yuan']}")
    print(f"  单次均价：¥{data['avg_cost_yuan']}")
    print(f"  tokens  ：输入 {data['tokens_in']} / 输出 {data['tokens_out']}")
    print(f"  最近一次：{data['last_call_at'] or '（无记录）'}")
    print("  分模块：")
    for m in data["by_module"]:
        print(f"    {m['module']:<24} {m['n']:>4} 次  ¥{m['s']}")
    print("\n提示：材料里引用请写成「截至 <日期> 快照：N 次 / ¥X」，并用本命令复核。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
