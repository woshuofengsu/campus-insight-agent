#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""清理 `activity_log` 里**存量的完整手机号**（2026-10-12）。

## 为什么需要它

项目的数据安全约定写得很死：**留痕（`activity_log.detail`）不得含完整手机号**（用 `_mask_phone`）。
2026-10-06 的审查修掉了**写入侧**（备线"查看完整手机号"原来把号码本身写进了 detail），
但**历史记录**里还留着那些行——本项目自己的原则是"**改了写入侧不等于旧数据就干净了**"，
所以补一个一次性清理脚本，而不是当它不存在。

## 怎么用

```bash
python scripts/clean_activity_log_phones.py            # 只看（dry-run，默认）
python scripts/clean_activity_log_phones.py --apply    # 就地脱敏（先自动备份一份 .db.bak）
```

- 只动 `activity_log.detail` 一个字段，把 11 位手机号替换成 `138****0000`；
- **幂等**：跑第二遍不会再有命中（脱敏后的号码不再匹配 11 位规则）；
- 默认 dry-run，`--apply` 会自动把当前库复制成 `备份目录/activity_phone_mask_<时间戳>.db.bak`；
- 找不到库 / 表不存在 → 明确报错退出，不静默成功。
"""
import argparse
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Windows 控制台默认不是 UTF-8：不设的话中文/符号会乱码（门禁 test_no_emoji_ui 会红）
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: 11 位手机号（前后不能再是数字，避免把订单号里的 11 位数字误伤）
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")


def _mask(phone: str) -> str:
    return f"{phone[:3]}****{phone[-4:]}"


def mask_text(text: str) -> str:
    """把一段文本里的完整手机号脱敏。纯函数，便于单测。"""
    if not text:
        return text or ""
    return _PHONE.sub(lambda m: _mask(m.group(0)), text)


def _open():
    """打开主库（与其它脚本同一口径：先让服务把库/迁移准备好）。"""
    import api_web                      # noqa: F401  触发 DB_PATH / 迁移初始化
    api_web._ensure_db()
    from data.db_core import get_db
    import config
    return get_db, getattr(config, "DB_PATH", "")


def scan(get_db) -> list[tuple[int, str, str]]:
    """返回 [(id, 原 detail, 脱敏后 detail)]，只含**真的有完整号码**的行。"""
    out = []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, detail FROM activity_log WHERE detail IS NOT NULL AND detail <> ''"
        ).fetchall()
    for r in rows:
        old = r["detail"] or ""
        new = mask_text(old)
        if new != old:
            out.append((r["id"], old, new))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="清理 activity_log 里的存量完整手机号")
    ap.add_argument("--apply", action="store_true", help="就地脱敏（默认只 dry-run 看命中）")
    a = ap.parse_args()

    get_db, db_path = _open()
    hits = scan(get_db)
    print(f"库：{db_path}")
    print(f"命中（detail 里含完整手机号）：{len(hits)} 行")
    for i, old, new in hits[:5]:
        print(f"  #{i}  {old[:70]}  →  {new[:70]}")
    if len(hits) > 5:
        print(f"  …另有 {len(hits) - 5} 行")

    if not hits:
        print("✓ 已经是干净的（写入侧 2026-10-06 已修，存量也已清）")
        return 0
    if not a.apply:
        print("\n这是 dry-run。要落地请加 --apply（会先自动备份）。")
        return 0

    # 就地脱敏：先备份，再逐行更新（同一事务）
    bak_dir = os.path.join(ROOT, "backups")
    os.makedirs(bak_dir, exist_ok=True)
    bak = os.path.join(bak_dir, f"activity_phone_mask_{time.strftime('%Y%m%d-%H%M%S')}.db.bak")
    if db_path and os.path.exists(db_path):
        shutil.copy2(db_path, bak)
        print(f"已备份：{bak}")
    else:
        print("⚠️ 找不到库文件，跳过备份（请自行确认可回滚）")

    with get_db() as conn:
        for i, _old, new in hits:
            conn.execute("UPDATE activity_log SET detail=? WHERE id=?", (new, i))
        conn.commit()

    left = scan(get_db)
    print(f"完成：已脱敏 {len(hits)} 行；复查剩余命中 {len(left)} 行")
    return 0 if not left else 1


if __name__ == "__main__":
    sys.exit(main())
