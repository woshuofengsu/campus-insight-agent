# scripts/reencrypt_phones.py
"""存量密文重加密为 AES-256-GCM（WS6.3）：对所有 *_enc 列做 decrypt→encrypt。

- 已带 `g1$` 前缀的密文：跳过（幂等）。
- 旧密文（无前缀）：解密→用新算法加密回写。
- 先备份 db（copy 为 *.bak.gz/timestamp），再逐行 try，失败计数并有输出。
- 用法：
    python scripts/reencrypt_phones.py [--db path]
"""
import argparse
import os
import sqlite3
import sys
from datetime import datetime

_PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJ)

import config

# 加密列（与 v36 / v38 / v39 迁移覆盖一致） -> 所属表
_ENCRYPTED_COLUMNS: dict[str, list[str]] = {
    "user_profile": ["phone_enc"],
    "emergency_contacts": ["phone_enc"],
    "community_issues": ["reporter_phone_enc", "agent_phone_enc", "assignee_phone_enc"],
    "health_consults": ["phone_enc", "agent_phone_enc"],
    "emergency_calls": ["target_phone_enc"],
}


def _ensure_db(path: str):
    import contextlib

    from data.db_core import init_db
    with contextlib.suppress(Exception):
        init_db(path)


def _backup(path: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    bak = f"{path}.bak.{stamp}"
    with open(path, "rb") as f:
        data = f.read()
    with open(bak, "wb") as f:
        f.write(data)
    return bak


def reencrypt(db_path: str, do_backup: bool = True, rollback: bool = False) -> dict:
    """对 db_path 的所有 *_enc 列做重加密。返回统计 {tables, rows, reencrypted, skipped, failed, backup}。"""
    if not os.path.exists(db_path):
        raise FileNotFoundError(db_path)
    _ensure_db(db_path)
    from utils.crypto import get_crypto
    crypto = get_crypto()
    prefix = "g1$"

    backup = _backup(db_path) if do_backup else ""
    if rollback:
        # 回滚说明见 --rollback：本脚本前缀化不可逆，回滚 = 恢复备份（由调用方选择）
        return {"rollback": backup}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    stats = {"tables": 0, "rows": 0, "reencrypted": 0, "skipped": 0, "failed": 0,
             "columns": 0, "backup": backup}
    failures: list[str] = []

    for table, cols in _ENCRYPTED_COLUMNS.items():
        try:
            exists = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if not exists:
                continue
        except Exception:
            continue
        for col in cols:
            try:
                cur = conn.execute(f"SELECT id, {col} AS val FROM {table} WHERE {col} != ''")
                rows = cur.fetchall()
            except sqlite3.Error:
                continue
            stats["tables"] += 1
            stats["columns"] += 1
            for row in rows:
                stats["rows"] += 1
                val = row["val"]
                if not val or val.startswith(prefix):
                    stats["skipped"] += 1
                    continue
                try:
                    plain = crypto.decrypt(val)
                    new_enc = crypto.encrypt(plain)
                    conn.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (new_enc, row["id"]))
                    stats["reencrypted"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    failures.append(f"{table}.{col}::id={row['id']} :: {str(e)[:60]}")
    conn.commit()
    conn.close()
    if failures:
        print("\n重加密失败记录（未提交？已提交但需人工核对）：")
        for f in failures[:20]:
            print("  -", f)
    return stats


def main():
    ap = argparse.ArgumentParser(description="存量手机号密文重加密为 AES-256-GCM")
    ap.add_argument("--db", default=config.DB_PATH, help="数据库路径")
    ap.add_argument("--no-backup", action="store_true", help="不备份")
    ap.add_argument("--rollback", action="store_true", help="不执行重加密，仅打印备份文件（回滚用）")
    args = ap.parse_args()

    if args.rollback:
        bak = f"{args.db}.bak.*"
        print("回滚说明：请用最近时间戳的备份文件覆盖原库，例：")
        print(f"   copy {bak} {args.db}")
        return

    stats = reencrypt(args.db, do_backup=not args.no_backup)
    print("重加密完成：")
    for k, v in stats.items():
        if k == "backup":
            continue
        print(f"  {k}: {v}")
    if stats.get("backup"):
        print(f"  backup: {stats['backup']}")
    if stats.get("failed", 0):
        print("有失败项，请人工核对上述记录。")
    else:
        print("全部成功（已是 g1$ 前缀的密文已跳过）。")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
