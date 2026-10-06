# -*- coding: utf-8 -*-
"""SQL 方言审计：找出**只在 SQLite 上能跑**的 SQL 写法（PostgreSQL 迁移的前置盘点）。

为什么需要它：`docs/scaling.md` 一直写着"可演进 PostgreSQL"，但**没人量过到底要改多少**。
实测结论很硬：`data/` 与 `agent/` 里有 **153 处** SQLite 专属写法
（`julianday` / `datetime('now', …)` / `date('now')` / `strftime` / `INSERT OR REPLACE` …），
所以"改个连接串就能上 Postgres"是**不成立的**。

用法：
    python scripts/audit_sql_dialect.py            # 分组汇总 + 清单
    python scripts/audit_sql_dialect.py --json      # 机器可读（给迁移计划用）

⚠️ 本脚本只**报告**，不改代码；它是"迁移前先量清楚"的那把尺子。
"""
import argparse
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: SQLite 专属写法 → 说明（Postgres 上必须改写的）
#: `conf` 是**置信度**：high = 字符串里出现就一定得改；low = 静态判断可能误报（需人工确认），
#: 单独统计、不混进标题数字——**把不确定的也算成"要改"，等于虚报工作量**。
PATTERNS = [
    ("julianday", r"julianday\s*\(", "high",
     "Postgres 没有；时间差用 `EXTRACT(EPOCH FROM (a - b))` 或 `a - b`（interval）"),
    ("datetime_now", r"datetime\s*\(\s*'now'", "high",
     "Postgres 用 `NOW()` / `CURRENT_TIMESTAMP`；带偏移要 `NOW() - INTERVAL '3 days'`"),
    ("date_now", r"date\s*\(\s*'now'", "high",
     "Postgres 用 `CURRENT_DATE`"),
    ("strftime", r"strftime\s*\(", "high",
     "Postgres 用 `to_char(...)`"),
    ("insert_or_replace", r"INSERT\s+OR\s+REPLACE", "high",
     "Postgres 用 `INSERT ... ON CONFLICT (...) DO UPDATE`（需要唯一约束）"),
    ("insert_or_ignore", r"INSERT\s+OR\s+IGNORE", "high",
     "Postgres 用 `INSERT ... ON CONFLICT DO NOTHING`"),
    ("pragma", r"PRAGMA\s+", "high",
     "Postgres 无 PRAGMA（表结构查 `information_schema`）"),
    ("rowid", r"\browid\b", "high",
     "Postgres 无隐式 rowid（用主键或 `ctid`）"),
    ("date_fn_on_column", r"date\s*\(\s*[a-z_]+\s*\)", "low",
     "对列取日期：Postgres 用 `CAST(col AS date)` 或 `col::date`（需人工确认不是普通函数调用）"),
    ("qmark_params", r"\?\s*(?:,|\)|$)", "low",
     "占位符 `?` → Postgres 用 `%s`（只在 SQL 字符串里才算，静态统计易误报）"),
]

#: 「这行像不像 SQL」——用于**去噪**：
#:   · `?` 占位符：正则、URL、字典里到处都是，必须限定在 SQL 行里；
#:   · `date(col)`：可能是普通函数调用；
#:   · `strftime(...)`：**Python 的 `datetime.strftime` 也是这个名字**！
#:     实测踩到：第一版把 57 处 `datetime.now().strftime(...)` 全算成"要改"，
#:     其实那些是纯 Python、跟 Postgres 一点关系都没有 —— **把不用改的算成要改，等于虚报工作量**。
_SQL_HINT = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|FROM|WHERE|VALUES|GROUP\s+BY|ORDER\s+BY|CREATE|ALTER)\b",
    re.I)

#: 这些写法出现即 SQL（不会与 Python 同名 API 混淆），无需再过滤
_ALWAYS_SQL = {"julianday", "datetime_now", "date_now", "insert_or_replace",
               "insert_or_ignore", "pragma", "rowid"}

#: 扫描范围（业务与数据层；脚本/测试不算在内——它们不跑在生产路径）
SCAN_DIRS = ["data", "agent", "api_routes", "tools", "utils"]


def _iter_py():
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for fn in sorted(files):
                if fn.endswith(".py"):
                    yield os.path.join(dirpath, fn)


def scan() -> dict:
    """按模式分组统计命中（含文件:行号，便于排期）；high/low 置信度分开统计。"""
    groups: dict[str, dict] = {k: {"why": w, "conf": c, "hits": []} for k, _p, c, w in PATTERNS}
    for path in _iter_py():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        try:
            text = io.open(path, encoding="utf-8").read()
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            # 跳过纯注释行：注释里提到 `datetime('now')` 是在解释口径，不是真在跑
            if stripped.startswith("#"):
                continue
            for key, pat, conf, _why in PATTERNS:
                if not re.search(pat, line, re.I):
                    continue
                # 去噪：非"必然 SQL"的写法，要求这一行看起来像 SQL
                # （挡掉 Python 的 strftime、正则里的 ?、普通 date(...) 调用）
                if key not in _ALWAYS_SQL and not _SQL_HINT.search(line):
                    continue
                groups[key]["hits"].append({"file": rel, "line": i, "code": stripped[:110]})
    high = sum(len(g["hits"]) for g in groups.values() if g["conf"] == "high")
    low = sum(len(g["hits"]) for g in groups.values() if g["conf"] == "low")
    return {
        "high_confidence": high,
        "low_confidence": low,
        "total": high + low,
        "files": len({h["file"] for g in groups.values() for h in g["hits"]}),
        "groups": {k: {"why": v["why"], "conf": v["conf"], "count": len(v["hits"]),
                       "hits": v["hits"]}
                   for k, v in groups.items() if v["hits"]},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="输出 JSON（给迁移计划用）")
    ap.add_argument("--top", type=int, default=5, help="每组打印前 N 条（默认 5）")
    args = ap.parse_args()

    data = scan()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    print("=" * 78)
    print("SQL 方言审计（PostgreSQL 迁移前置盘点）")
    print("=" * 78)
    print(f"高置信度命中：{data['high_confidence']} 处（一定得改）")
    print(f"低置信度命中：{data['low_confidence']} 处（静态判断可能误报，需人工确认）")
    print(f"涉及文件：{data['files']} 个\n")
    print("[注意] 结论：**这不是「改个连接串」**——下列写法在 Postgres 上都必须改写。\n")
    for key, g in sorted(data["groups"].items(), key=lambda kv: -kv[1]["count"]):
        print(f"[{g['count']:>3}] {key}（{g['conf']}）")
        print(f"      → {g['why']}")
        for h in g["hits"][:args.top]:
            print(f"      {h['file']}:{h['line']}  {h['code']}")
        if g["count"] > args.top:
            print(f"      …（其余 {g['count'] - args.top} 处见 --json）")
        print()
    print("建议的迁移顺序（按收益/风险）：")
    print("  ① 先把这些写法**收敛到少数几个辅助函数**（时间差、当前时间、按天分组、upsert），")
    print("     让方言只出现在一处；② 再给辅助函数写两套实现（sqlite / postgres）；")
    print("  ③ 用同一套测试跑两遍（`DB_BACKEND=sqlite|postgres`）才算真迁移。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
