# api_routes/auth.py
"""认证路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）：登录 / 演示登录 / 当前用户 / 改密 / PIPL 导出与注销。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, make_token

router = APIRouter(tags=["auth"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1)
    password: str = Field(default="")


class DemoLoginRequest(BaseModel):
    role: str = Field(..., pattern="^(resident|grid|elderly)$")


class ChangePassword(BaseModel):
    old_password: str = Field(default="")
    new_password: str = Field(..., min_length=8)


def _user_payload(u: dict) -> dict:
    """登录/演示登录统一返回体。"""
    return {
        "token": u.get("_token", ""),
        "role": u.get("role"),
        "user_id": u.get("id"),
        "name": u.get("name") or u.get("username"),
        "community": u.get("community") or "",
        "building": u.get("building") or "",
        "unit": u.get("unit") or "",
        "phone": u.get("phone") or "",
    }


@router.post("/api/web/auth/login")
def login(req: LoginRequest, request: Request):
    """居民/负责人/老人登录。

    WS0.3：登录失败计数（防爆破）。同一 username|ip 连续失败 ≥5 次锁定 5 分钟，
    锁定期间即便密码正确也拒绝；成功后清零。
    """
    from utils.login_guard import check, record_fail, reset
    ip = request.client.host if request.client else "unknown"
    if check(req.username, ip):
        return _fail(1002, "尝试次数过多，请稍后再试")
    from data.db_user import authenticate
    user = authenticate(req.username, req.password)
    if user is None:
        record_fail(req.username, ip)
        return _fail(1002, "用户名或密码错误")
    reset(req.username, ip)
    user["_token"] = make_token(user["id"], user["role"], user.get("name") or user.get("username") or "")
    return _ok(_user_payload(user))


@router.post("/api/web/auth/demo")
def demo_login(req: DemoLoginRequest):
    """演示快速登录：直接取该角色第一个演示账号。

    WS0.1 安全止血：生产（DEMO_MODE=false）硬关闭，杜绝无密领取任意角色 JWT 的越权。
    """
    import config
    if not getattr(config, "DEMO_MODE", True):
        return _fail(1003, "演示登录未开启")
    from data.db_user import list_users
    for u in list_users(role=req.role):
        u["_token"] = make_token(u["id"], u["role"], u.get("name") or u.get("username") or "")
        return _ok(_user_payload(u))
    return _fail(1004, "没有可用的演示账号")


@router.get("/api/web/auth/me")
def me(request: Request):
    """当前用户信息（phone_enc 解密，P1-G1-02）。"""
    u = _user(request)
    from data.db_user import get_user_by_id
    row = get_user_by_id(u.get("uid"))
    if not row:
        return _fail(1004, "用户不存在")
    if not row.get("is_active"):
        return _fail(1003, "账号已注销")
    phone = row.get("phone") or ""
    if not phone and row.get("phone_enc"):
        try:
            from utils.crypto import get_crypto
            phone = get_crypto().decrypt(row["phone_enc"])
        except Exception:
            phone = ""
    return _ok({
        "user_id": row["id"], "role": row["role"],
        "name": row.get("name") or row.get("username"),
        "community": row.get("community") or "", "building": row.get("building") or "",
        "unit": row.get("unit") or "", "phone": phone,
        "resident_id": row.get("resident_id") or "",
    })


@router.post("/api/web/auth/change-password")
def change_password(req: ChangePassword, request: Request):
    """修改密码（校验强度；演示账号居民/老人为空密码时免旧密码）。"""
    from data.db_core import get_db, _hash_password, _verify_password
    from utils.password import validate_password
    u = _user(request)
    uid = u.get("uid")
    okp, msg = validate_password(req.new_password)
    if not okp:
        return _fail(2001, msg)
    with get_db() as conn:
        row = conn.execute("SELECT password_hash FROM user_profile WHERE id=?", (uid,)).fetchone()
        if row is None:
            return _fail(1004, "用户不存在")
        stored = row["password_hash"] or ""
        if stored and not _verify_password(req.old_password, stored):
            return _fail(1001, "原密码不正确")
        conn.execute("UPDATE user_profile SET password_hash=? WHERE id=?",
                     (_hash_password(req.new_password), uid))
        conn.commit()
    from data.db_notifications import log_activity
    log_activity(u.get("name") or "用户", "修改密码", module="安全",
                 detail=f"用户 #{uid} 修改登录密码（留痕，不含明文）")
    return _ok({}, "密码已修改")


@router.get("/api/web/me/export")
def me_export(request: Request):
    """PIPL：导出本人数据（JSON，脱敏——不含完整手机号）。"""
    from data.db_core import get_db
    import json
    from io import StringIO
    u = _user(request)
    uid = u.get("uid")
    out = {"user_id": uid, "name": u.get("name") or "", "role": u.get("role") or ""}
    with get_db() as conn:
        for table, cols in (("community_issues", "reported_at"), ("proposals", "created_at"),
                            ("health_consults", "created_at"), ("agent_dialogs", "created_at")):
            try:
                rows = conn.execute(
                    f"SELECT * FROM {table} WHERE user_id=? ORDER BY {cols} DESC LIMIT 50",
                    (uid,)).fetchall()
            except Exception:
                continue
            out[table] = [dict(r) for r in rows]
    # 脱敏：手机号打码
    def mask(obj):
        if isinstance(obj, dict):
            for k in list(obj.keys()):
                if k == "phone" or k.endswith("_phone"):
                    v = str(obj[k] or "")
                    obj[k] = (v[:3] + "****" + v[-4:]) if len(v) == 11 else v
                elif isinstance(obj[k], (dict, list)):
                    mask(obj[k])
        elif isinstance(obj, list):
            for i in obj:
                mask(i)
    mask(out)
    from data.db_notifications import log_activity
    log_activity(u.get("name") or "用户", "导出本人数据", module="安全",
                 detail=f"用户 #{uid} 导出个人数据（脱敏）")
    from fastapi.responses import Response
    return Response(json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"),
                    media_type="application/json",
                    headers={"Content-Disposition": "attachment; filename=my-data.json"})


@router.post("/api/web/me/delete")
def me_delete(request: Request):
    """PIPL：注销账号（匿名化个人字段 + 停用；保留必要日志）。"""
    from data.db_core import get_db
    from data.db_notifications import log_activity
    u = _user(request)
    uid = u.get("uid")
    with get_db() as conn:
        conn.execute(
            "UPDATE user_profile SET is_active=0, username='已注销用户' || id, "
            "phone='', phone_enc='', name='', community='', building='', unit='' "
            "WHERE id=? AND role != 'grid'",
            (uid,))
        # N3：级联匿名化关联表 PII（保留 id / 统计 / 日志，仅清空可识别信息与密文）
        conn.execute(
            "UPDATE emergency_contacts SET name='', phone='', phone_enc='' WHERE user_id=?", (uid,))
        conn.execute(
            "UPDATE health_consults SET name='', phone='', phone_enc='', agent_name='', "
            "agent_phone='', agent_phone_enc='' WHERE user_id=?", (uid,))
        conn.execute(
            "UPDATE community_issues SET reporter_name='', reporter_phone='', reporter_phone_enc='' "
            "WHERE reporter_id=?", (uid,))
        # R1：提案表 PII 也级联清空（保留 id/统计；is_agent_report 的第三方 agent_* 一并清）
        conn.execute(
            "UPDATE proposals SET reporter_name='', reporter_phone='', agent_name='', agent_phone='' "
            "WHERE reporter_id=?", (uid,))
        conn.commit()
    log_activity(u.get("name") or "用户", "注销账号", module="安全",
                 detail=f"用户 #{uid} 注销（匿名化个人字段与关联表 PII，保留日志）")
    return _ok({}, "账号已注销（个人数据与关联表 PII 已匿名化，日志按法规保留）")
