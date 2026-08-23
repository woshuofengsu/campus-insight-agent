# api_routes/deps.py
"""路由共享依赖：统一响应 / 用户上下文 / 角色校验 / 老年端免登录 / JWT（从 api_web.py 抽出，P2-04/P1-F2-01）。"""
import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse

# ---------------- JWT（stdlib HMAC HS256，零第三方依赖） ----------------

_SECRET = os.getenv("WEB_JWT_SECRET", "community-insight-web-jwt-2026")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(user_id: int, role: str, name: str, expires_hours: int = 12) -> str:
    """签发 JWT（HS256）。"""
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(json.dumps({
        "uid": user_id, "role": role, "name": name,
        "exp": int(time.time()) + expires_hours * 3600,
    }, ensure_ascii=False).encode())
    sig = _b64(hmac.new(_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify_token(token: str) -> dict | None:
    """校验 JWT，返回 payload；失败返回 None。"""
    try:
        header, payload, sig = token.split(".")
        expect = _b64(hmac.new(_SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expect, sig):
            return None
        data = json.loads(_b64d(payload))
        if data.get("exp", 0) < time.time():
            return None
        return data
    except Exception:
        return None


def _ok(data=None, message: str = "ok") -> dict:
    """统一成功响应。"""
    return {"success": True, "data": data, "error": None, "code": 0, "message": message}


def _fail(code: int, error: str) -> JSONResponse:
    """统一失败响应（400，与 api_web.fail 保持一致）。"""
    return JSONResponse(status_code=400, content={
        "success": False, "data": None, "error": error, "code": code, "message": error,
    })


def _user(request: Request) -> dict:
    return getattr(request.state, "user", {})


def _require_role(request: Request, role: str):
    u = _user(request)
    if u.get("role") != role:
        return _fail(1003, "无权限")
    return None


def _resolve_elder_uid(request: Request) -> int | None:
    """老年端免登录：?elder_id=X 且当前 token 用户是该老人的绑定家属 → 返回老人 uid。"""
    u = _user(request)
    uid = u.get("uid")
    elder_id = request.query_params.get("elder_id")
    if not elder_id or not str(elder_id).isdigit():
        return None
    elder_id = int(elder_id)
    if u.get("role") == "elderly" and elder_id == uid:
        return uid
    try:
        from data.db_user import get_bound_elderly
        bound = get_bound_elderly(uid)
        if bound and bound.get("id") == elder_id:
            return elder_id
    except Exception:
        pass
    return None
