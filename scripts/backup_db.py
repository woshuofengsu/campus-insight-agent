# -*- coding: utf-8 -*-
"""数据库备份（**可立即在 SQLite 上真跑**；PostgreSQL 走 pg_dump）。

三条纪律：
  ① **不做静默降级**：拿不到一致的备份就**报错退出**，绝不"备份了个空文件还返回成功"；
  ② 每次备份写 `manifest.json`（大小 / sha256 / schema 版本 / 关键表行数）——
     这样恢复演练才有**可比对的基准**，否则"恢复成功"只是句空话；
  ③ 保留周期是显式参数（`--keep`），过期备份连同清单一起清，不留孤儿文件。

用法：
    python scripts/backup_db.py                     # 备份到 backups/，保留 14 份
    python scripts/backup_db.py --keep 30
    python scripts/backup_db.py --include-uploads    # 连附件目录一起打包
"""
import argparse
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

#: manifest 里记录行数的关键表（恢复演练按同一份清单比对）
KEY_TABLES = ["user_profile", "community_issues", "notices", "proposals",
              "agent_logs", "activity_log", "agent_handoffs", "knowledge_base",
              "idempotency_keys", "settings"]


def _backend() -> str:
    """当前后端：`sqlite`（默认）或 `postgres`（由 DB_BACKEND 决定）。"""
    return (os.environ.get("DB_BACKEND") or "sqlite").strip().lower()


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sqlite_snapshot(src: str, dst: str) -> None:
    """用 SQLite 官方 backup API 做**一致性快照**（不是 copy 文件）。

    为什么不用 shutil.copy：WAL 模式下直接拷主库文件会**漏掉尚未 checkpoint 的页**，
    恢复出来的库可能少数据或损坏。`Connection.backup()` 会读一遍完整快照，
    是"备份"这件事在 SQLite 上唯一正确的做法。
    """
    src_conn = sqlite3.connect(src)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _table_counts(db_path: str) -> dict:
    out = {}
    conn = sqlite3.connect(db_path)
    try:
        for t in KEY_TABLES:
            try:
                out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                out[t] = None      # 表不存在 → 记 null（不假装是 0）
    finally:
        conn.close()
    return out


def _schema_version(db_path: str) -> int | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(version) v FROM schema_version").fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "backups"))
    ap.add_argument("--keep", type=int, default=14, help="保留最近 N 份（默认 14）")
    ap.add_argument("--include-uploads", action="store_true", help="附件目录一起打包")
    args = ap.parse_args()

    import config
    backend = _backend()
    os.makedirs(args.out, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    manifest = {"created_at": datetime.now().isoformat(timespec="seconds"),
                "backend": backend, "db_path": str(config.DB_PATH)}

    if backend == "sqlite":
        src = str(config.DB_PATH)
        if not os.path.exists(src):
            print(f"[备份失败] SQLite 库不存在：{src}")
            return 1
        name = f"community_insight-{stamp}.db"
        dst = os.path.join(args.out, name)
        _sqlite_snapshot(src, dst)
        # 快照必须能被独立打开且通过完整性检查，否则这个备份**不算数**
        conn = sqlite3.connect(dst)
        try:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            conn.close()
        if integrity != "ok":
            print(f"[备份失败] 快照未通过 integrity_check：{integrity}")
            os.remove(dst)
            return 1
        manifest.update({"file": name, "bytes": os.path.getsize(dst),
                         "sha256": _sha256(dst), "integrity_check": integrity,
                         "schema_version": _schema_version(dst),
                         "table_counts": _table_counts(dst)})
    else:
        # PostgreSQL：**必须有 pg_dump**，没有就明确失败（不退回 SQLite 备份冒充）
        if not shutil.which("pg_dump"):
            print("[备份失败] DB_BACKEND=postgres 但找不到 pg_dump —— 无法备份。")
            print("           （按纪律这里**不降级**：宁可失败，也不能交一个假的备份。）")
            return 1
        name = f"community_insight-{stamp}.sql"
        dst = os.path.join(args.out, name)
        url = os.environ.get("DATABASE_URL", "")
        if not url:
            print("[备份失败] DB_BACKEND=postgres 但未设置 DATABASE_URL")
            return 1
        r = subprocess.run(["pg_dump", "--no-owner", "--format=plain", "-f", dst, url],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"[备份失败] pg_dump 返回 {r.returncode}：{(r.stderr or '')[:300]}")
            return 1
        manifest.update({"file": name, "bytes": os.path.getsize(dst),
                         "sha256": _sha256(dst), "schema_version": None,
                         "table_counts": None})

    if args.include_uploads:
        up = os.path.join(ROOT, "uploads")
        if os.path.isdir(up):
            tname = f"uploads-{stamp}.tar.gz"
            with tarfile.open(os.path.join(args.out, tname), "w:gz") as tf:
                tf.add(up, arcname="uploads")
            manifest["uploads_file"] = tname
            manifest["uploads_bytes"] = os.path.getsize(os.path.join(args.out, tname))

    mpath = os.path.join(args.out, f"manifest-{stamp}.json")
    io.open(mpath, "w", encoding="utf-8").write(
        json.dumps(manifest, ensure_ascii=False, indent=2))

    # 保留周期：过期备份连同清单一起删（不留孤儿）
    backups = sorted(f for f in os.listdir(args.out)
                     if f.startswith("community_insight-") and f != os.path.basename(mpath))
    removed = 0
    for old in backups[:-args.keep] if len(backups) > args.keep else []:
        os.remove(os.path.join(args.out, old))
        old_stamp = old.rsplit("-", 1)[-1].split(".")[0]
        for f in os.listdir(args.out):
            if old_stamp and old_stamp in f and f != os.path.basename(mpath):
                os.remove(os.path.join(args.out, f))
        removed += 1

    mb = manifest["bytes"] / 1024 / 1024
    print(f"[备份成功] {manifest['file']}（{mb:.2f} MB，sha256 {manifest['sha256'][:12]}…）")
    print(f"           schema=v{manifest.get('schema_version')} "
          f"关键表行数={manifest.get('table_counts')}")
    print(f"           保留最近 {args.keep} 份，本次清理 {removed} 份过期备份")
    print(f"           清单：{os.path.relpath(mpath, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
