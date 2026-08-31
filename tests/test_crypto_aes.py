# -*- coding: utf-8 -*-
"""WS6：AES-256-GCM 加密正名测试 —— 新密文 g1$ 前缀 + 后端兼容旧密文 + 篡改检测 + 重加密幂等。"""
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.crypto import Crypto, _AES_GCM_PREFIX  # noqa: E402


def test_new_encrypt_prefix_and_roundtrip():
    c = Crypto("test-key")
    ct = c.encrypt("13912345678")
    assert ct.startswith(_AES_GCM_PREFIX)
    assert ct != "13912345678"
    assert c.decrypt(ct) == "13912345678"


def test_tampered_gcm_raises():
    c = Crypto("test-key")
    ct = c.encrypt("13912345678")
    # 篡改密文最后一个字节（tag）→ GCM 认证失败抛异常
    import base64
    raw = bytearray(base64.b64decode(ct[len(_AES_GCM_PREFIX):]))
    raw[-1] ^= 0xFF
    tampered = _AES_GCM_PREFIX + base64.b64encode(bytes(raw)).decode()
    import pytest
    with pytest.raises(Exception):
        c.decrypt(tampered)


def test_legacy_ciphertext_still_readable():
    """向后兼容：用旧 HMAC-CTR 算法造一条无前缀密文，新 Crypto 能解。"""
    import hashlib
    import hmac as _hmac

    # 复刻旧算法（scrypt + HMAC-Counter stream + HMAC 完整性）
    key_material = "legacy-key"
    key = hashlib.scrypt(key_material.encode(), salt=b"campus-insight-crypto-v1",
                         n=2 ** 14, r=8, p=1, dklen=32)
    mac_key = hashlib.sha256(b"mac-" + key).digest()
    nonce = b"\x01" * 12
    data = "13987654321".encode()
    stream = b""
    counter = 0
    while len(stream) < len(data):
        stream += _hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    ct = bytes(a ^ b for a, b in zip(data, stream[:len(data)]))
    mac = _hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    legacy_token = __import__("base64").b64encode(nonce + ct + mac).decode()

    c = Crypto("legacy-key")
    assert c.decrypt(legacy_token) == "13987654321"  # 旧密文可读


def test_enc_dec_phone_full_chain():
    """_enc_phone/_dec_phone 全链路（模拟 db_repair 路径）。"""
    from utils.crypto import get_crypto
    import importlib
    rep = importlib.import_module("data.db_repair")
    enc = rep._enc_phone("13812345678")
    assert enc.startswith(_AES_GCM_PREFIX)
    assert rep._dec_phone(enc, "") == "13812345678"
    # 解密失败回退明文
    assert rep._dec_phone("bad_token", "fallback") == "fallback"


def test_reencrypt_script_idempotent(monkeypatch):
    """重加密脚本在临时库上跑两次结果一致（已是 g1$ 跳过）。

    用 monkeypatch 固定 get_crypto 返回同一 key 的 Crypto，避免模块级单例/环境变量污染。
    """
    KEY = "e2e-key-1234567890"
    monkeypatch.setattr("utils.crypto.get_crypto", lambda: Crypto(KEY))
    import config
    tmp = os.path.join(tempfile.mkdtemp(prefix="reenc_"), "t.db")
    config.DB_PATH = tmp
    from data.db_core import init_db
    init_db(tmp)
    c = Crypto(KEY)
    # 用旧算法加密固化为旧密文（无前缀）
    import hashlib, hmac as _hmac, base64
    def _old(phone):
        key = hashlib.scrypt(KEY.encode(), salt=b"campus-insight-crypto-v1",
                             n=2 ** 14, r=8, p=1, dklen=32)
        mk = hashlib.sha256(b"mac-" + key).digest()
        nonce = b"\x02" * 12
        data = phone.encode()
        s = b""; i = 0
        while len(s) < len(data):
            s += _hmac.new(key, nonce + i.to_bytes(8, "big"), hashlib.sha256).digest(); i += 1
        ct = bytes(a ^ b for a, b in zip(data, s[:len(data)]))
        mac = _hmac.new(mk, nonce + ct, hashlib.sha256).digest()
        return base64.b64encode(nonce + ct + mac).decode()
    con = sqlite3.connect(tmp)
    con.row_factory = sqlite3.Row
    con.execute("INSERT INTO user_profile (username, role, name, phone, phone_enc, is_active) "
                "VALUES ('u1','resident','a','',?,1)", (_old("13800000001"),))
    con.execute("INSERT INTO user_profile (username, role, name, phone, phone_enc, is_active) "
                "VALUES ('u2','resident','b','',?,1)", (c.encrypt("13800000002"),))
    con.commit()
    con.close()

    import importlib.util
    spec = importlib.util.spec_from_file_location("reenc", "scripts/reencrypt_phones.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    s1 = mod.reencrypt(tmp, do_backup=False)
    s2 = mod.reencrypt(tmp, do_backup=False)
    assert s1["reencrypted"] == 1       # 仅 1 条旧格式被重加密
    assert s2["reencrypted"] == 0       # 第二次全跳过（幂等）
    # 全部变为 g1$ 且可解
    con = sqlite3.connect(tmp)
    rows = [r[0] for r in con.execute("SELECT phone_enc FROM user_profile ORDER BY id")]
    con.close()
    assert all(r.startswith(_AES_GCM_PREFIX) for r in rows)
    assert Crypto(KEY).decrypt(rows[1]) == "13800000002"
