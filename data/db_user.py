"""用户资料增删改查 — 支持多用户和登录鉴权。

所有函数都接受可选的 user_id 参数；不传时按下面的顺序找当前用户：

  1. 显式指定: set_active_user_id()（API / 非 UI 场景）
  2. Streamlit session_state._login_user_id（UI 场景）

都找不到就抛 RuntimeError。
"""
import json
import logging
from data.db_core import get_db, _hash_password, _verify_password

_log = logging.getLogger(__name__)

# 非 Streamlit 场景（比如 FastAPI）用的模块级用户覆盖
_explicit_user_id: int | None = None


def set_active_user_id(user_id: int | None) -> None:
    """给非 Streamlit 场景（如 FastAPI）设置当前 user_id。

    每个 API 请求开头调一次。传 None 表示清除，回到 Streamlit session_state。
    """
    global _explicit_user_id
    _explicit_user_id = user_id


def _get_active_user_id() -> int:
    """解析当前 user_id。

    优先级：
      1. 显式指定（set_active_user_id）— API 场景
      2. Streamlit session_state._login_user_id — UI 场景

    都拿不到就抛 RuntimeError。
    """
    # 1) 显式指定（API / 非 UI）
    if _explicit_user_id is not None:
        return _explicit_user_id

    # 2) Streamlit session_state（UI）
    try:
        import streamlit as st
        uid = st.session_state.get("_login_user_id")
        if uid is not None:
            return int(uid)
    except Exception:  # 尽力而为，拿不到就算了
        _log.debug("从 session_state 解析用户失败", exc_info=True)
        pass

    raise RuntimeError(
        "No active user session. Call set_active_user_id() from API contexts, "
        "or ensure st.session_state._login_user_id is set in Streamlit."
    )


def authenticate(username: str, password: str = "") -> dict | None:
    """校验登录。成功返回用户资料 dict，失败返回 None。

    居民（role='resident'）：密码可空，空密码直接放行。
    网格员（role='grid'）：必须有密码，且要和存库的 hash 对上。
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profile WHERE username = ? AND is_active = 1",
            (username.strip(),),
        ).fetchone()
        if not row:
            return None

        user = dict(row)
        stored_hash = user.get("password_hash", "")

        if user["role"] == "grid":
            # 网格员必须密码正确
            if not _verify_password(password, stored_hash):
                return None
        else:
            # 居民：设了密码就校验；没设密码就随便/空密码都能进
            if stored_hash and not _verify_password(password, stored_hash):
                return None

        # 登录成功后顺手把旧版 hash 格式迁移成 PBKDF2
        if stored_hash and "$" not in stored_hash:
            new_hash = _hash_password(password)
            conn.execute(
                "UPDATE user_profile SET password_hash = ? WHERE id = ?",
                (new_hash, user["id"]),
            )
            conn.commit()
            user["password_hash"] = new_hash

        return user


def get_current_user() -> dict:
    """拿当前登录用户的资料（session_state / 显式指定的 user_id）。

    拿不到活动用户时**回退到 id=1**（登录改造前的老库兜底）——这条回退是历史兼容，
    但它会"静默给出一个错误身份"：主服务（FastAPI）路径没人调 `set_active_user_id`，
    于是 `_get_active_user_id()` 抛 RuntimeError → 这里返回 id=1，
    调用方（`_resolve_reporter_id` 等）就会把操作**记到 id=1 名下**。
    所以回退时必须**打日志**：宁可日志里显眼，也不要出现"数据归错人还不知道为什么"。
    """
    try:
        uid = _get_active_user_id()
        profile = get_user_by_id(uid)
        if profile:
            return profile
        _log.warning("活动用户 id=%s 在库里不存在（session 可能过期），回退 id=1 兜底", uid)
    except RuntimeError:
        _log.warning("没有活动用户上下文（非 UI 场景需先 set_active_user_id()），"
                     "按历史兼容回退 id=1 —— 若这条出现在 API 日志里，说明该调用点应改为"
                     "显式传 user_id/tenant，别依赖这个回退")
    # 老逻辑兜底：返回 id=1 的用户（登录改造前的库）
    return get_user_by_id(1)


def get_user_by_id(user_id: int) -> dict:
    """按 ID 查用户资料，没有就返回空 dict。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profile WHERE id = ?", (user_id,)
        ).fetchone()
        if not row:
            # 兼容老数据：没有就回退到 id=1
            if user_id != 1:
                row = conn.execute(
                    "SELECT * FROM user_profile WHERE id = 1"
                ).fetchone()
        return dict(row) if row else {}


def get_user_by_username(username: str) -> dict | None:
    """按用户名查用户资料，没有就返回 None。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM user_profile WHERE username = ?", (username.strip(),)
        ).fetchone()
        return dict(row) if row else None


def list_users(role: str | None = None, community: str | None = None) -> list[dict]:
    """列所有启用中的用户，可按角色过滤。

    `community`（多租户 · 限收件人用）：**只列该社区的用户**。
    为什么必须能按社区过滤：转人工、健康异常这类通知原来遍历"所有 grid" → **跨社区投递**，
    A 社区网格员会收到 B 社区老人的姓名与健康读数（Codex 评审 I2：
    消息中心只让本人看自己的消息，但敏感内容**已经投递给错误收件人**）。
    传 None/空串 = 不限社区（保持老调用方行为）；**通知类调用必须传具体社区**。
    """
    from utils.tenant import normalize_tenant
    # ⚠️ fail-closed：`community` **传了就一定要过滤**——归一化后为空（历史行政区值/空串）
    # 意味着"这个身份没有合法社区"，此时返回**空表**，绝不能退化成"不过滤=返回所有人"
    # （第一版就是这么错的：managers_of("海淀区") 返回了全部网格员）。
    if community is not None:
        t = normalize_tenant(community)
        if not t:
            return []
    else:
        t = None
    with get_db() as conn:
        q = ("SELECT id, username, role, name, community, resident_id, building, unit "
             "FROM user_profile WHERE is_active = 1")
        args: list = []
        if role:
            q += " AND role = ?"
            args.append(role)
        if t:
            q += " AND community = ?"
            args.append(t)
        rows = conn.execute(q + " ORDER BY role, id", args).fetchall()
        return [dict(r) for r in rows]


def managers_of(tenant: str) -> list[dict]:
    """**某个社区的事件该通知哪些网格员**（结构化收件人入口，多租户 Codex 评审 I2）。

    为什么需要这个函数：项目里曾有 19 处 `list_users(role="grid")` 直接把"所有网格员"
    当收件人 → 跨社区投递（A 社区的事投给 B 社区的网格员，内容常含居民诉求、老人健康读数）。
    根因不是"忘了加 WHERE"，而是**收件人选择没有统一入口**。
    今后凡是"社区内发生的事要通知负责人"，一律走本函数；`tenant` 为空返回空表（fail-closed）。
    """
    from utils.tenant import normalize_tenant
    t = normalize_tenant(tenant)
    if not t:
        return []
    return list_users(role="grid", community=t)


def create_user(username: str, password: str = "", role: str = "resident",
                community: str = "", building: str = "", unit: str = "",
                name: str = "", resident_id: str = "") -> int:
    """新建用户，返回新用户 ID；用户名重复抛 ValueError。"""
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM user_profile WHERE username = ?", (username.strip(),)
        ).fetchone()
        if existing:
            raise ValueError(f"Username '{username}' already taken")
        pw_hash = _hash_password(password) if password else ""
        cur = conn.execute(
            """INSERT INTO user_profile
               (username, password_hash, role, community, building, unit, name, resident_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (username.strip(), pw_hash, role, community, building, unit, name, resident_id),
        )
        conn.commit()
        return cur.lastrowid


def update_user_profile(community: str | None = None, building: str | None = None,
                        unit: str | None = None, resident_id: str | None = None,
                        role: str | None = None, name: str | None = None,
                        preferences: list[str] | None = None,
                        user_id: int | None = None,
                        password: str | None = None) -> None:
    """更新用户资料。

    传字符串（包括空串）表示要设置；传 None 表示跳过不更新。
    user_id 不传就更新当前登录用户。
    password 传新密码就改密码；传空串表示清空密码。
    """
    if user_id is None:
        user_id = _get_active_user_id()
    with get_db() as conn:
        parts = []
        params: list = []
        if community is not None:
            parts.append("community = ?")
            params.append(community)
        if building is not None:
            parts.append("building = ?")
            params.append(building)
        if resident_id is not None:
            parts.append("resident_id = ?")
            params.append(resident_id)
        if unit is not None:
            parts.append("unit = ?")
            params.append(unit)
        if role is not None:
            parts.append("role = ?")
            params.append(role)
        if name is not None:
            parts.append("name = ?")
            params.append(name)
        if preferences is not None:
            parts.append("preferences = ?")
            params.append(json.dumps(preferences, ensure_ascii=False))
        if password is not None:
            parts.append("password_hash = ?")
            params.append(_hash_password(password) if password else "")
        if parts:
            conn.execute(
                f"UPDATE user_profile SET {', '.join(parts)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                params + [user_id],
            )
            conn.commit()


def set_onboarding_done(user_id: int | None = None) -> None:
    """把某用户的引导流程标记为已完成。"""
    if user_id is None:
        user_id = _get_active_user_id()
    with get_db() as conn:
        conn.execute(
            "UPDATE user_profile SET onboarding_done = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user_id,),
        )
        conn.commit()


def reset_onboarding(user_id: int | None = None) -> None:
    """重置某用户的引导标记。"""
    if user_id is None:
        user_id = _get_active_user_id()
    with get_db() as conn:
        conn.execute(
            "UPDATE user_profile SET onboarding_done = 0 WHERE id = ?",
            (user_id,),
        )
        conn.commit()


# 给老代码用的兼容包装（旧接口不传 user_id）

def get_or_create_user() -> dict:
    """旧接口：拿当前用户资料。新代码直接用 get_current_user()。"""
    return get_current_user()


# ---------- 家属绑定（老年免登录，spec 06） ----------

def bind_elderly(guardian_id: int, elderly_id: int) -> tuple[bool, str]:
    """家属绑定老人（一个家属最多绑定一位老人）。返回 (ok, msg)。"""
    with get_db() as conn:
        g = conn.execute("SELECT id, name FROM user_profile WHERE id=?", (guardian_id,)).fetchone()
        if g is None:
            return False, "家属账号不存在"
        e = conn.execute("SELECT id, name, role FROM user_profile WHERE id=?", (elderly_id,)).fetchone()
        if e is None:
            return False, "老人账号不存在"
        if e["role"] != "elderly":
            return False, "被绑定账号不是老年关怀账号"
        conn.execute("UPDATE user_profile SET bound_elderly_id=? WHERE id=?",
                     (elderly_id, guardian_id))
        conn.commit()
    try:
        from data.db_notifications import log_activity
        _e_name = e["name"] if e["name"] else "（无姓名）"
        log_activity(g["name"] or "家属", "绑定老人", "elderly_binding", elderly_id,
                     _e_name, module="老年端", after_value=str(elderly_id))
    except Exception as _e:  # noqa: BLE001
        # 绑定本身已提交，但**审计留痕失败**必须可见（涉 PII 的授权关系变更）
        _log.warning("绑定老人的留痕写入失败（绑定已生效）：%s", _e)
    return True, f"已绑定老人：{e['name'] if e['name'] else '（无姓名）'}"


def unbind_elderly(guardian_id: int) -> tuple[bool, str]:
    """家属解除绑定。"""
    with get_db() as conn:
        conn.execute("UPDATE user_profile SET bound_elderly_id=0 WHERE id=?", (guardian_id,))
        conn.commit()
    return True, "已解除绑定"


def get_bound_elderly(guardian_id: int) -> dict | None:
    """查家属绑定的老人资料（老年免登录时用老人身份渲染）。"""
    if not guardian_id:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT e.* FROM user_profile g JOIN user_profile e ON g.bound_elderly_id=e.id "
            "WHERE g.id=? AND g.bound_elderly_id>0", (guardian_id,),
        ).fetchone()
        return dict(row) if row else None


def list_guardians_of(elderly_id: int) -> list[dict]:
    """反向查：谁把这位老人绑定为「我的老人」（家属/子女）。

    P3 安全闭环要用它把"老人久未互动"的通知**同时发给家属**——`get_bound_elderly` 是
    「家属 → 老人」方向，这里是反方向（老人 → 家属），原来是缺的。
    """
    if not elderly_id:
        return []
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name FROM user_profile WHERE bound_elderly_id=? AND is_active=1 "
            "ORDER BY id", (elderly_id,),
        ).fetchall()
    return [dict(r) for r in rows]
