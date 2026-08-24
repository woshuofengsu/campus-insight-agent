# -*- coding: utf-8 -*-
"""工单手机号存量加密迁移（P0）。可重复执行（已加密行 phone 已置空即跳过）。

将 community_issues 的 reporter_phone / agent_phone / assignee_phone 加密到 *_enc，明文置空。
KEY：需与运行时 CRYPTO_KEY 一致，否则解密失败。

用法：
    python scripts/migrate_issue_phone_encryption.py            # 加密迁移
    python scripts/migrate_issue_phone_encryption.py --rollback  # 回滚（解密写回明文）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import get_db  # noqa: E402
from utils.crypto import Crypto  # noqa: E402

_COLS = ["reporter_phone", "agent_phone", "assignee_phone"]


def _ensure_db() -> None:
    """确保数据库已初始化（_DB_PATH 已设），否则迁移脚本 get_db 会报 not initialized。"""
    from data import db_core
    if not db_core._DB_PATH:
        import config
        db_core.init_db(config.DB_PATH)


def _crypto() -> Crypto:
    try:
        return Crypto()
    except Exception:
        return Crypto("migrate-key")


def migrate() -> int:
    _ensure_db()
    c = _crypto()
    total = 0
    with get_db() as conn:
        for col in _COLS:
            enc_col = f"{col}_enc"
            rows = conn.execute(
                f"SELECT id, {col} FROM community_issues "
                f"WHERE {col} IS NOT NULL AND {col} != ''").fetchall()
            for r in rows:
                try:
                    conn.execute(
                        f"UPDATE community_issues SET {enc_col}=?, {col}='' WHERE id=?",
                        (c.encrypt(r[col]), r["id"]))
                    total += 1
                except Exception:
                    continue
        conn.commit()
    return total


def rollback() -> int:
    _ensure_db()
    c = _crypto()
    total = 0
    with get_db() as conn:
        for col in _COLS:
            enc_col = f"{col}_enc"
            rows = conn.execute(
                f"SELECT id, {enc_col} FROM community_issues "
                f"WHERE {enc_col} IS NOT NULL AND {enc_col} != ''").fetchall()
            for r in rows:
                try:
                    conn.execute(
                        f"UPDATE community_issues SET {col}=?, {enc_col}='' WHERE id=?",
                        (c.decrypt(r[enc_col]), r["id"]))
                    total += 1
                except Exception:
                    continue
        conn.commit()
    return total


if __name__ == "__main__":
    roll = "--rollback" in sys.argv
    n = rollback() if roll else migrate()
    print(f"{'回滚' if roll else '迁移'}完成：{n} 个工单手机号字段已"
          f"{'解密写回明文' if roll else '加密（明文置空）'}")
    print("提示：迁移前请先备份数据库；CRYPTO_KEY 需与运行时一致，否则解密失败。")
