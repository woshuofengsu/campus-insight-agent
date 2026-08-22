# utils/password.py
"""密码强度策略（数据安全 v3.0）。

- 最小 8 位；必须含字母和数字
- 禁止连续重复字符（如 aaa、111）
- 禁止常见弱密码（123456、password、demo123、admin 等）
- 强度分级：weak / medium / strong（前端实时显示用）
"""
import re

_WEAK_PASSWORDS = {
    "123456", "12345678", "123456789", "password", "password123",
    "admin", "admin123", "demo123", "qwerty", "abc123", "111111", "666666", "888888",
}

_REPEAT_RE = re.compile(r"(.)\1{2,}")


def password_strength(password: str) -> str:
    """返回 weak / medium / strong。"""
    if not password or len(password) < 8:
        return "weak"
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_symbol = any(not c.isalnum() for c in password)
    if has_letter and has_digit and has_symbol and len(password) >= 10:
        return "strong"
    if has_letter and has_digit:
        return "medium"
    return "weak"


def validate_password(password: str) -> tuple[bool, str]:
    """校验新密码。返回 (是否通过, 错误信息)。"""
    if not password or len(password) < 8:
        return False, "密码至少 8 位"
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        return False, "密码必须同时包含字母和数字"
    if _REPEAT_RE.search(password):
        return False, "密码不能包含连续重复字符（如 aaa、111）"
    if password.lower() in _WEAK_PASSWORDS:
        return False, "密码过于简单，请更换"
    return True, ""
