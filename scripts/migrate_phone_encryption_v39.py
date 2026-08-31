# -*- coding: utf-8 -*-
"""手机号加密遗漏面存量迁移（P0 收口 v39）。可重复执行（明文置空即跳过）。

加密目标列（_m39 已建）：
  - health_consults.phone / agent_phone      → phone_enc / agent_phone_enc
  - emergency_calls.target_phone             → target_phone_enc
  - emergency_contacts.phone                 → phone_enc （兜底：防止 v36 后新增明文）

KEY：需与运行时 CRYPTO_KEY 一致，否则解密失败。加密前请先备份数据库。

用法：
    python scripts/migrate_phone_encryption_v39.py            # 加密迁移
    python scripts/migrate_phone_encryption_v39.py --rollback  # 回滚（解密写回明文）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.database import get_db  # noqa: E402
from utils.crypto import Crypto  # noqa: E402


def _ensure_db() -> None:
    from data import db_core
    if not db_core._DB_PATH:
        import config
        db_core.init_db(config.DB_PATH)


def _crypto() -> Crypto:
    try:
        return Crypto()
    except Exception:
        return Crypto("migrate-key")


# (表, 明文字段, 加密字段)
_TARGETS = [
    ("health_consults", "phone", "phone_enc"),
    ("health_consults", "agent_phone", "agent_phone_enc"),
    ("emergency_calls", "target_phone", "target_phone_enc"),
    ("emergency_contacts", "phone", "phone_enc"),
]


def migrate() -> int:
    _ensure_db()
    c = _crypto()
    total = 0
    with get_db() as conn:
        for table, plain_col, enc_col in _TARGETS:
            try:
                rows = conn.execute(
                    f"SELECT id, {plain_col} FROM {table} "
                    f"WHERE {plain_col} IS NOT NULL AND {plain_col} != ''").fetchall()
            except Exception:
                continue  # 表无该列（v39 未跑）则跳过
            for r in rows:
                try:
                    conn.execute(
                        f"UPDATE {table} SET {enc_col}=?, {plain_col}='' WHERE id=?",
                        (c.encrypt(r[plain_col]), r["id"]))
                    total += 1
                except Exception:
                    continue
        conn.commit()
    return total


def rollback() -> int:
    """回滚：把 *_enc 解密写回明文列，清空 *_enc。破坏性低优先级（仅应急）。"""
    _ensure_db()
    c = _crypto()
    total = 0
    with get_db() as conn:
        for table, plain_col, enc_col in _TARGETS:
            try:
                rows = conn.execute(
                    f"SELECT id, {enc_col} FROM {table} "
                    f"WHERE {enc_col} IS NOT NULL AND {enc_col} != ''").fetchall()
            except Exception:
                continue
            for r in rows:
                try:
                    conn.execute(
                        f"UPDATE {table} SET {plain_col}=?, {enc_col}='' WHERE id=?",
                        (c.decrypt(r[enc_col]), r["id"]))
                    total += 1
                except Exception:
                    continue
        conn.commit()
    return total


if __name__ == "__main__":
    roll = "--rollback" in sys.argv
    n = rollback() if roll else migrate()
    print(f"{'回滚' if roll else '迁移'}完成：{n} 个手机号字段已"
          f"{'解密写回明文' if roll else '加密（明文置空）'}")
    print("提示：迁移前请先备份数据库；CRYPTO_KEY 需与运行时一致，否则解密失败。")
