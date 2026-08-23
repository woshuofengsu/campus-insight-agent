# api_routes/deps.py
"""路由共享依赖：统一响应 / 用户上下文 / 角色校验（从 api_web.py 抽出，P2-04/P1-F2-01）。"""
from fastapi import Request
from fastapi.responses import JSONResponse


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
