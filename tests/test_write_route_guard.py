# -*- coding: utf-8 -*-
"""统一受控写入口的**故障注入**测试（卡7）：越权/状态不符/非本人必须被拒。

为什么要单独测装饰器：它是"授权 + 状态 + 所有权"的唯一执行点，
一旦它自己在某个分支上放行，前面所有迁移都会静默失效。
"""
import os
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from data import db_core  # noqa: E402

A = "海淀小区"
B = "朝阳试点社区"
OWNER = 99101
OTHER = 99102
FAMILY = 99103
GRID = 99111
GRID_B = 99112


@pytest.fixture(scope="module", autouse=True)
def _fresh_db():
    orig = db_core._DB_PATH
    tmp = tempfile.mkdtemp(prefix="write_guard_")
    db_core._DB_PATH = ""
    db_core.init_db(os.path.join(tmp, "wg.db"))
    with db_core.get_db() as conn:
        for uid, role, com in ((OWNER, "elderly", A), (OTHER, "resident", A),
                               (FAMILY, "resident", A), (GRID, "grid", A), (GRID_B, "grid", B)):
            conn.execute(
                "INSERT OR REPLACE INTO user_profile (id, username, role, name, is_active, community) "
                "VALUES (?, ?, ?, ?, 1, ?)", (uid, f"u{uid}", role, f"n{uid}", com))
        cols = [r[1] for r in conn.execute("PRAGMA table_info(user_profile)")]
        if "bound_elderly_id" in cols:
            conn.execute("UPDATE user_profile SET bound_elderly_id=? WHERE id=?", (OWNER, FAMILY))
        # 一条属于 OWNER 的用药提醒（状态「待审核」，便于测状态机）
        conn.execute(
            "INSERT INTO medication_reminders (id, user_id, patient_name, drug_name, dosage, "
            "times_json, status, tenant_id) "
            "VALUES (1, ?, 'A老人', '降压药', '1片', '[\"08:00\"]', '待审核', ?)",
            (OWNER, A))
        conn.commit()
    from utils.tenant import clear_cache
    clear_cache()
    yield
    db_core._DB_PATH = orig
    clear_cache()


def _req(uid, role, community, elder_id=None):
    qp = {"elder_id": str(elder_id)} if elder_id else {}
    return SimpleNamespace(state=SimpleNamespace(user={
        "uid": uid, "role": role, "name": f"u{uid}", "community": community,
    }), query_params=qp, client=SimpleNamespace(host="127.0.0.1"))


def _denied(res) -> bool:
    if isinstance(res, dict):
        return not res.get("success")
    import json as _json
    return not _json.loads(bytes(res.body).decode("utf-8")).get("success")


def _err(res) -> str:
    if isinstance(res, dict):
        return res.get("error") or ""
    import json as _json
    return _json.loads(bytes(res.body).decode("utf-8")).get("error") or ""


@pytest.fixture()
def route():
    """一个最小的、只挂在装饰器上的写路由（不碰业务数据）。"""
    from api_routes.guards import write_route

    @write_route(roles=("grid",), table="medication_reminders", id_param="rid",
                 require_state=("待审核",))
    def audit(rid: int, request):
        return {"success": True, "data": {"rid": rid}, "error": None}

    @write_route(table="medication_reminders", id_param="rid", owner_column="user_id",
                 allow_family=True)
    def by_owner(rid: int, request):
        return {"success": True, "data": {"rid": rid}, "error": None}

    @write_route(table="medication_reminders", id_param="rid", owner_column="user_id",
                 allow_family=False)
    def self_only(rid: int, request):
        return {"success": True, "data": {"rid": rid}, "error": None}

    return SimpleNamespace(audit=audit, by_owner=by_owner, self_only=self_only)


# ---------------------------------------------------------------- 角色

def test_role_denied(route):
    assert _denied(route.audit(1, _req(OTHER, "resident", A))), "居民不该能审用药提醒"
    assert _denied(route.audit(1, _req(GRID_B, "grid", B))), "跨社区网格员不该能审"


def test_role_allowed(route):
    assert not _denied(route.audit(1, _req(GRID, "grid", A))), "本社区网格员必须可用（别误伤）"


# ---------------------------------------------------------------- 状态机

def test_state_mismatch_denied(route):
    """状态不符必须拒绝（这是"状态"这一层的执行点）。"""
    with db_core.get_db() as conn:
        conn.execute("UPDATE medication_reminders SET status='审核通过' WHERE id=1")
        conn.commit()
    try:
        res = route.audit(1, _req(GRID, "grid", A))
        assert _denied(res) and "状态" in _err(res), f"状态不符应拒绝并说明：{res}"
    finally:
        with db_core.get_db() as conn:
            conn.execute("UPDATE medication_reminders SET status='待审核' WHERE id=1")
            conn.commit()


def test_missing_row_denied(route):
    assert _denied(route.audit(999999, _req(GRID, "grid", A))), "行不存在必须拒绝（不是放行）"


# ---------------------------------------------------------------- 所有权

def test_owner_and_family(route):
    assert _denied(route.by_owner(1, _req(OTHER, "resident", A))), "同社区他人不该能改"
    assert not _denied(route.by_owner(1, _req(OWNER, "elderly", A))), "本人必须可用（别误伤）"
    assert not _denied(
        route.by_owner(1, _req(FAMILY, "resident", A, elder_id=OWNER))), "绑定家属递代操作必须可用"
    assert _denied(route.by_owner(1, _req(FAMILY, "resident", A))), \
        "家属**不带 elder_id** 时不应被当成老人本人（否则绑定关系形同虚设）"


def test_self_only_denies_family(route):
    """`allow_family=False`：打卡这类事只能本人（家属代打卡等于伪造服药记录）。"""
    assert _denied(route.self_only(1, _req(FAMILY, "resident", A, elder_id=OWNER)))
    assert not _denied(route.self_only(1, _req(OWNER, "elderly", A)))


# ---------------------------------------------------------------- 接线错误

def test_missing_request_is_a_loud_error(route):
    """拿不到 Request 必须**报错**而不是放行（接线错误要立刻暴露）。"""
    with pytest.raises(RuntimeError):
        route.audit(1, None)


def test_wrong_id_param_is_a_loud_error():
    """声明了 id_param 但路由签名里没有 → 报错（而不是跳过租户闸门）。"""
    from api_routes.guards import write_route

    @write_route(roles=("grid",), table="medication_reminders", id_param="nope")
    def bad(request):
        return {"success": True}

    with pytest.raises(RuntimeError):
        bad(_req(GRID, "grid", A))


def test_declaration_is_introspectable():
    """声明信息要能被静态门禁读到（`__write_route__`），否则闸门没法判断"有没有声明"。"""
    from api_routes.guards import write_route

    @write_route(roles=("grid",), table="medication_reminders", id_param="rid", note="x")
    def f(rid: int, request):
        return None

    meta = getattr(f, "__write_route__", None)
    assert meta and meta["table"] == "medication_reminders" and meta["roles"] == ["grid"]
