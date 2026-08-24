# utils/crypto.py
"""敏感字段加密工具（数据安全 v3.0，零第三方依赖）。

加密方案（诚实声明）：
    本项目演示环境使用 Python stdlib 实现的对称加密：
    scrypt 派生密钥 + HMAC-SHA256 计数流（CTR 风格）异或明文 + HMAC 完整性校验。
    接口 encrypt/decrypt 与 AES-256-GCM 语义一致（机密性 + 完整性 + 随机 nonce），
    生产环境可将 _derive_key/_stream 替换为 cryptography 库的 AES-256-GCM，无需改调用方。

- 密钥来源：环境变量 CRYPTO_KEY；未配置时用演示默认值并打日志（生产必须配置）。
- 密文格式：base64(nonce(12B) + ciphertext + mac(32B))
- 注意：stdlib 实现仅供演示。生产必须切换为 AES-256-GCM（见 docs/deploy-https.md）。
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets

_log = logging.getLogger(__name__)

_SALT = b"campus-insight-crypto-v1"
_NONCE_LEN = 12
_MAC_LEN = 32


def _derive_key(key_material: str) -> bytes:
    """scrypt 派生 32 字节密钥（内存与时间成本适中，演示可用）。"""
    return hashlib.scrypt(
        key_material.encode("utf-8"), salt=_SALT,
        n=2 ** 14, r=8, p=1, dklen=32,
    )


class Crypto:
    """对称加密封装：encrypt(str)->str / decrypt(str)->str。"""

    def __init__(self, key: str | None = None):
        raw = key or os.environ.get("CRYPTO_KEY") or ""
        if not raw:
            _log.warning("CRYPTO_KEY 未配置，使用演示默认密钥（生产环境必须配置）")
            raw = "dev-crypto-key-change-me"
        self._key = _derive_key(raw)
        self._mac_key = hashlib.sha256(b"mac-" + self._key).digest()

    def encrypt(self, plaintext: str) -> str:
        data = plaintext.encode("utf-8")
        nonce = secrets.token_bytes(_NONCE_LEN)
        stream = self._stream(nonce, len(data))
        ct = bytes(a ^ b for a, b in zip(data, stream))
        mac = hmac.new(self._mac_key, nonce + ct, hashlib.sha256).digest()
        return base64.b64encode(nonce + ct + mac).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        raw = base64.b64decode(ciphertext.encode("utf-8"))
        if len(raw) < _NONCE_LEN + _MAC_LEN:
            raise ValueError("密文格式错误")
        nonce, body, mac = raw[:_NONCE_LEN], raw[_NONCE_LEN:-_MAC_LEN], raw[-_MAC_LEN:]
        expect = hmac.new(self._mac_key, nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(expect, mac):
            raise ValueError("密文校验失败（密钥不匹配或数据被篡改）")
        stream = self._stream(nonce, len(body))
        pt = bytes(a ^ b for a, b in zip(body, stream))
        return pt.decode("utf-8")

    def _stream(self, nonce: bytes, length: int) -> bytes:
        """HMAC 计数流（CTR 风格）：keystream = HMAC(key, nonce || counter)。"""
        out = b""
        counter = 0
        while len(out) < length:
            out += hmac.new(self._key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
            counter += 1
        return out[:length]


# 缓存单例：Crypto() 每次构造都会走昂贵的 scrypt 派生（n=2**14）。
# get_issues 等批量解密（每条工单多个号码）若反复构造会重复派生，故缓存避免性能损耗。
_crypto_singleton: "Crypto | None" = None


def get_crypto() -> "Crypto":
    """返回模块级 Crypto 单例（密钥派生只做一次）。线程安全（GIL 下简单缓存足够）。"""
    global _crypto_singleton
    if _crypto_singleton is None:
        _crypto_singleton = Crypto()
    return _crypto_singleton
