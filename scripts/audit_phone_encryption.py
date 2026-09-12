# scripts/audit_phone_encryption.py — 手机号加密覆盖度体检（哪张表还有明文手机号列）
# -*- coding: utf-8 -*-
"""逐表枚举含 phone 的列，报告「有明文列但没有 *_enc 兄弟列」以及「明文列里还有多少条真数据」。

用法：
  python scripts/audit_phone_encryption.py              # 体检生产库 data/community_insight.db
  python scripts/audit_phone_encryption.py <db_path>
退出码：0 = 无缺口（所有 phone 列都有 enc 兄弟列且明文计数为 0）；1 = 有缺口
"""
import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 非 PII 的「phone」列（社区公开电话、紧急号码 120 等），不需要加密
ALLOW_PLAIN = {
    ("elderly_care_config", "community_phone"),
    ("emergency_contacts", "relation"),          # 无 phone 命中的历史噪音
}


def scan_gaps(db: str) -> tuple[list[str], list[str]]:
    """体检一张库：返回 (缺口列表, 明细行列表)。供 CLI 与 demo_preflight 共用。"""
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    tabs = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    gaps: list[str] = []
    lines: list[str] = []
    for t in sorted(tabs):
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
        ph = [c for c in cols if "phone" in c.lower()]
        if not ph:
            continue
        plain = [c for c in ph if not c.endswith("_enc")]
        enc = [c for c in ph if c.endswith("_enc")]
        parts = []
        for p in plain:
            if (t, p) in ALLOW_PLAIN:
                parts.append(f"{p}=豁免")
                continue
            try:
                n = conn.execute(
                    f"SELECT COUNT(*) FROM {t} WHERE length(COALESCE({p},''))>0").fetchone()[0]
            except sqlite3.Error as e:
                n = -1
                gaps.append(f"{t}.{p} 计数失败：{e}")
            parts.append(f"{p}={n}")
            has_enc = f"{p}_enc" in cols
            if not has_enc:
                gaps.append(f"{t}.{p} 无 {p}_enc 列（明文 {n} 条）")
            elif n > 0:
                gaps.append(f"{t}.{p} 仍有明文 {n} 条（应回填 {p}_enc 并清空）")
        lines.append(f"  {t:24s} 明文[{', '.join(parts)}]  加密列[{', '.join(enc) or '-'}]")
    conn.close()
    return gaps, lines


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data", "community_insight.db")
    if not os.path.exists(db):
        print(f"库不存在：{db}")
        return 1
    gaps, lines = scan_gaps(db)
    print(f"库：{db}\n")
    for ln in lines:
        print(ln)
    print(f"\n含 phone 列的表：{len(lines)}")
    if gaps:
        print("缺口：")
        for g in gaps:
            print("  ✗", g)
        return 1
    print("✓ 无缺口：所有手机号列都有加密兄弟列且明文计数为 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
