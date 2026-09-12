# scripts/_check_crypto_consistency.py — 关键校验：迁移写入的密文能否被当前密钥解开
# -*- coding: utf-8 -*-
"""v46 迁移用 `utils.crypto.get_crypto()` 加密；如果迁移时与运行期的密钥不同，
存量密文就会变成「解不开的数据」——这是加密类改动的头号事故，必须显式验证。"""
import os
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

sys.path.insert(0, ".")
from utils.crypto import get_crypto

KEY = os.environ.get("CRYPTO_KEY", "")
print("环境变量 CRYPTO_KEY：", "已设置(len=%d)" % len(KEY) if KEY else "未设置（用演示默认密钥）")

c = get_crypto()
db = sqlite3.connect("data/community_insight.db")
db.row_factory = sqlite3.Row

checks = [
    ("community_issues", "reporter_phone_enc"),
    ("proposals", "reporter_phone_enc"),
    ("proposal_drafts", "reporter_phone_enc"),
    ("issue_drafts", "reporter_phone_enc"),
    ("user_profile", "phone_enc"),
    ("emergency_contacts", "phone_enc"),
    ("health_consults", "phone_enc"),
]
bad = 0
for table, col in checks:
    rows = db.execute(
        f"SELECT {col} AS e FROM {table} WHERE length(COALESCE({col},''))>0 LIMIT 3").fetchall()
    if not rows:
        print(f"  {table:20s} 无密文（跳过）")
        continue
    ok = 0
    sample = ""
    for r in rows:
        try:
            v = c.decrypt(r["e"])
            ok += 1
            if not sample and len(v) >= 7:
                sample = v[:3] + "****" + v[-4:]
        except Exception as e:  # noqa: BLE001
            print(f"  {table:20s} ✗ 解密失败：{type(e).__name__}")
            bad += 1
    print(f"  {table:20s} {ok}/{len(rows)} 条解密成功  样例(脱敏)={sample}")

print("\n结论：" + ("✓ 密文与当前密钥一致，可正常解密" if bad == 0 else f"✗ 有 {bad} 张表解密失败，密钥不一致！"))
sys.exit(1 if bad else 0)
