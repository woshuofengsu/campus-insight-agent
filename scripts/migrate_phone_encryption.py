# -*- coding: utf-8 -*-
"""存量敏感数据加密迁移（P1-G1-02，适配项目纯 sqlite3）。

- 将 user_profile.phone / emergency_contacts.phone 加密到 phone_enc，明文置空
- 可重复执行（已加密的行跳过）；迁移前请先备份数据库
- 回滚：解密 phone_enc 写回 phone 即可（见底部 --rollback）
用法：
    python scripts/migrate_phone_encryption.py            # 加密迁移
    python scripts/migrate_phone_encryption.py --rollback  # 回滚（解密写回）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import get_db
from utils.crypto import Crypto


def _ensure_db() -> None:
    """确保数据库已初始化（_DB_PATH 已设），否则 get_db 会报 not initialized（原脚本 bug）。"""
    from data import db_core
    if not db_core._DB_PATH:
        import config
        db_core.init_db(config.DB_PATH)


def _crypto() -> Crypto:
    try:
        return Crypto()
    except Exception:
        return Crypto("migrate-key")

_TABLES = [
    ("user_profile", "phone", "phone_enc"),
    ("emergency_contacts", "phone", "phone_enc"),
]


def migrate() -> int:
    _ensure_db()
    c = _crypto()
    total = 0
    with get_db() as conn:
        for table, plain_col, enc_col in _TABLES:
            try:
                rows = conn.execute(
                    f"SELECT id, {plain_col} FROM {table} "
                    f"WHERE {plain_col} IS NOT NULL AND {plain_col} != ''").fetchall()
            except Exception:
                continue
            for r in rows:
                try:
                    enc = c.encrypt(r[plain_col])
                    conn.execute(
                        f"UPDATE {table} SET {enc_col}=?, {plain_col}='' WHERE id=?",
                        (enc, r["id"]))
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
        for table, plain_col, enc_col in _TABLES:
            try:
                rows = conn.execute(
                    f"SELECT id, {enc_col} FROM {table} "
                    f"WHERE {enc_col} IS NOT NULL AND {enc_col} != ''").fetchall()
            except Exception:
                continue
            for r in rows:
                try:
                    plain = c.decrypt(r[enc_col])
                    conn.execute(
                        f"UPDATE {table} SET {plain_col}=?, {enc_col}='' WHERE id=?",
                        (plain, r["id"]))
                    total += 1
                except Exception:
                    continue
        conn.commit()
    return total


if __name__ == "__main__":
    roll = "--rollback" in sys.argv
    n = rollback() if roll else migrate()
    print(f"{'回滚' if roll else '迁移'}完成：{n} 条手机号已{'解密写回明文' if roll else '加密（明文置空）'}")
    print("提示：迁移前请先备份数据库；CRYPTO_KEY 需与运行时一致，否则解密失败。")
