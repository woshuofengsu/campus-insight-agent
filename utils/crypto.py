# utils/crypto.py
"""敏感字段加密工具（数据安全 WS6，真 AES-256-GCM + 密文版本前缀 + 旧密文兼容）。

方案（可对外如实声明）：
    - 新密文：`g1$<base64(nonce(12B) | ciphertext | tag)>`，AES-256-GCM 加密
      （SHA-256 将密钥材料派生为 32B，密钥来自环境变量 CRYPTO_KEY）。
    - 旧密文：无 `g1$` 前缀，来自早期 stdlib HMAC-CTR 自研方案，仍可解密（向后兼容），
      但不再用于新加密；可通过 scripts/reencrypt_phones.py 平滑轮换为 GCM。
    - 对外接口 encrypt/decrypt 不变，调用方零改动。

- 密钥来源：CRYPTO_KEY；未配置时用演示默认值并打日志（生产必须配置）。
"""
import base64
import hashlib
import hmac
import logging
import os
import secrets

_AES_GCM_PREFIX = "g1$"          # 密文版本前缀（算法轮换信号）
_NONCE_LEN = 12                  # GCM 推荐 12 字节 nonce
_TAG_LEN = 16                    # GCM 认证标签
_MAC_LEN = 32                    # 旧的 HMAC 校验长度
_SALT = b"campus-insight-crypto-v1"

_log = logging.getLogger(__name__)

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM as _AESGCM
    _HAS_GCM = True
except Exception:  # pragma: no cover - cryptography 未安装时降级
    _AESGCM = None
    _HAS_GCM = False
    _log.warning("cryptography 未安装，AES-256-GCM 不可用；将回退演示加密（生产务必 pip install cryptography）")


def _derive_aes_key(key_material: str) -> bytes:
    """SHA-256 派生 32 字节 = AES-256。"""
    return hashlib.sha256(key_material.encode("utf-8")).digest()


def _derive_legacy_key(key_material: str) -> bytes:
    """旧方案 scrypt 派生（仅用于解密历史密文）。"""
    return hashlib.scrypt(key_material.encode("utf-8"), salt=_SALT,
                          n=2 ** 14, r=8, p=1, dklen=32)


class _LegacyStream:
    """旧 stdlib HMAC-CTR + 完整性校验（只用于解密早期密文，不再用于新加密）。"""

    def __init__(self, key_material: str):
        self._key = _derive_legacy_key(key_material)
        self._mac_key = hashlib.sha256(b"mac-" + self._key).digest()

    @staticmethod
    def _stream(key: bytes, nonce: bytes, length: int) -> bytes:
        out = b""
        counter = 0
        while len(out) < length:
            out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
            counter += 1
        return out[:length]

    def decrypt(self, token: str) -> str:
        raw = base64.b64decode(token.encode("utf-8"))
        if len(raw) < 12 + _MAC_LEN:
            raise ValueError("旧密文格式错误")
        nonce, body, mac = raw[:12], raw[12:-_MAC_LEN], raw[-_MAC_LEN:]
        expect = hmac.new(self._mac_key, nonce + body, hashlib.sha256).digest()
        if not hmac.compare_digest(expect, mac):
            raise ValueError("旧密文校验失败（密钥不匹配或数据被篡改）")
        stream = self._stream(self._key, nonce, len(body))
        pt = bytes(a ^ b for a, b in zip(body, stream))
        return pt.decode("utf-8")


class Crypto:
    """加密封装：encrypt(str)->str / decrypt(str)->str。

    - 新加密用 AES-256-GCM（输出 g1$ 前缀）；旧密文（无前缀）走 _LegacyStream 解密。
    - 篡改/密钥不符 → 抛异常（调用方按"解不出=空"处理，见 db_repair._dec_phone）。
    """

    def __init__(self, key: str | None = None):
        raw = key or os.environ.get("CRYPTO_KEY") or ""
        if not raw:
            _log.warning("CRYPTO_KEY 未配置，使用演示默认密钥（生产环境必须配置）")
            raw = "dev-crypto-key-change-me"
        if _HAS_GCM:
            self._aes = _AESGCM(_derive_aes_key(raw))
        else:
            self._aes = None
        # 保留旧派生，仅用于解密历史密文
        self._legacy = _LegacyStream(raw)

    def encrypt(self, plaintext: str) -> str:
        data = plaintext.encode("utf-8")
        if self._aes is None:
            raise RuntimeError("AES-256-GCM 需要 cryptography 库，请先 pip install cryptography")
        nonce = secrets.token_bytes(_NONCE_LEN)
        ct = self._aes.encrypt(nonce, data, None)
        return _AES_GCM_PREFIX + base64.b64encode(nonce + ct).decode("utf-8")

    def decrypt(self, token: str) -> str:
        if not token:
            return ""
        if token.startswith(_AES_GCM_PREFIX):
            if self._aes is None:
                raise ValueError("cryptography 未安装，无法解密 GCM 密文")
            raw = base64.b64decode(token[len(_AES_GCM_PREFIX):].encode("utf-8"))
            nonce, ct = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
            return self._aes.decrypt(nonce, ct, None).decode("utf-8")
        # 旧密文（无前缀）：兼容解密
        return self._legacy.decrypt(token)


# 缓存单例：Crypto() 每次构造做派生，批量解密反复构造会重复派生，故缓存。
_crypto_singleton: "Crypto | None" = None


def get_crypto() -> "Crypto":
    """返回模块级 Crypto 单例（密钥派生只做一次）。线程安全（GIL 下简单缓存足够）。"""
    global _crypto_singleton
    if _crypto_singleton is None:
        _crypto_singleton = Crypto()
    return _crypto_singleton
