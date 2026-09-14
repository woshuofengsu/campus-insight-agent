# api_routes/deps.py
"""路由共享依赖：统一响应 / 用户上下文 / 角色校验 / 老年端免登录 / JWT（从 api_web.py 抽出，P2-04/P1-F2-01）。"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time

from fastapi import Request
from fastapi.responses import JSONResponse

_log = logging.getLogger(__name__)

# ---------------- JWT（stdlib HMAC HS256，零第三方依赖） ----------------

def _load_secret() -> str:
    """加载 JWT 密钥（N2：secure-by-default）。

    未配 WEB_JWT_SECRET 时，仅当**显式** DEMO_MODE=true（环境变量里真的写了 true/1/yes）才放行
    演示兜底密钥；否则一律拒绝启动——杜绝"默认 true + 忘配密钥 → 用公开密钥被伪造 JWT"。
    """
    secret = os.getenv("WEB_JWT_SECRET", "").strip()
    if secret:
        return secret
    demo = os.getenv("DEMO_MODE", "").strip().lower() in ("1", "true", "yes")
    if demo:
        _log.warning("WEB_JWT_SECRET 未配置，使用演示兜底密钥（仅供显式 DEMO_MODE=true 的本机演示，严禁生产）")
        return "demo-only-insecure-jwt-secret"
    raise RuntimeError(
        "WEB_JWT_SECRET 未配置且未显式开启 DEMO_MODE=true：安全默认要求配置 JWT 密钥，拒绝启动"
        "（本机/演示请在 .env 设 WEB_JWT_SECRET，或用 .env.demo 显式 DEMO_MODE=true）。"
    )


_SECRET = _load_secret()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(user_id: int, role: str, name: str, expires_hours: int = 12,
               community: str = "") -> str:
    """签发 JWT（HS256）。`community`：用户所属社区（属地化的来源，地区识别 WS2）。

    ⚠ 为什么必须带在 token 里：`_region(request)` 靠它解析属地；不带的话**所有用户都会回落到
    全局默认城市**（实测踩到：属地化功能"做了但不生效"）。老 token 没有该字段 → `_region` 会
    回退到按 uid 查库，保证兼容。
    """
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload_obj = {
        "uid": user_id, "role": role, "name": name,
        "exp": int(time.time()) + expires_hours * 3600,
    }
    if community:
        payload_obj["community"] = community
    payload = _b64(json.dumps(payload_obj, ensure_ascii=False).encode())
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


_COMMUNITY_CACHE: dict[int, str] = {}


def _community_of(uid) -> str:
    """按 uid 查社区（带缓存）。用于**老 token 不带 community** 的兼容路径。"""
    try:
        key = int(uid or 0)
    except (TypeError, ValueError) as e:
        _log.debug("uid 非法，跳过按 uid 查社区：%r（%s）", uid, e)
        return ""
    if not key:
        return ""
    if key in _COMMUNITY_CACHE:
        return _COMMUNITY_CACHE[key]
    community = ""
    try:
        from data.db_user import get_user_by_id
        community = ((get_user_by_id(key) or {}).get("community") or "").strip()
    except Exception as e:  # noqa: BLE001
        _log.warning("按 uid 查社区失败（属地将回落全局默认）：%s", e)
        community = ""
    if len(_COMMUNITY_CACHE) > 500:
        _COMMUNITY_CACHE.clear()
    _COMMUNITY_CACHE[key] = community
    return community


def _region(request: Request):
    """当前请求用户的属地（地区识别）：由 `community` 解析，未登录/未命中回落全局默认。

    两级来源：① JWT 里的 community（新 token）；② 老 token 没带 → 按 uid 查库（带缓存）。
    集中在这里的原因：居民端/老年端/网格端多处以同一口径取属地（天气、政策问答），
    避免各写一份、口径漂移。
    """
    try:
        from utils.region import resolve_region, Region
        u = _user(request) or {}
        community = (u.get("community") or "").strip() or _community_of(u.get("uid"))
        return resolve_region(community)
    except Exception as e:  # noqa: BLE001  属地解析失败绝不能影响业务
        _log.warning("属地解析失败，回落全局默认：%s", e)
        from utils.region import Region
        return Region()


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
