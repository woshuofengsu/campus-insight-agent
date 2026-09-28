# -*- coding: utf-8 -*-
"""统一受控写入口（v2 升级方案任务卡 7）。

**为什么要有这个模块**：过去"授权 / 状态 / 租户 / 确认"这四件事是**散在每个写路由里手写的**，
漏一处就是一类越权或一类脏状态（本项目实测出现过：列表看不见但换个 id 就能改、
同社区任何人都能处置别人家老人的 SOS、草稿状态覆盖新意图）。手写检查的根问题是
**"记得写"不可靠**——所以把检查收敛成装饰器：路由作者**声明**这次写的对象是什么，
检查由框架统一执行；`tests/test_write_route_guard.py` 再静态拦住"没有声明的写路由"。

用法（顺序即执行顺序）：

    @router.post("/medications/{rid}/audit")
    @write_route(roles=("grid",), table="medication_reminders", id_param="rid",
                 require_state=("待审核",), note="负责人审核用药提醒")
    def web_manage_medication_audit(rid: int, req: MedicationAudit, request: Request):
        ...

装饰器依次执行：
  ① 登录 → ② 角色 → ③ **按 id 直取的租户闸门**（`_same_tenant`）→ ④ 状态机 →
  ⑤ 所有权（本人 / 已绑定家属）。
任一不满足就**就地拒绝**（fail-closed），业务函数根本不会被调用。

⚠️ 它**不替代**业务层的其它校验（例如"同一张单不能重复打卡"这类业务态规则仍写在业务函数里）；
这里只解决"**谁能对哪个对象做什么**"这一层，且必须每处都能被静态追溯到。
"""
import functools
import inspect
import logging
from typing import Callable, Sequence

from fastapi import Request

from api_routes.deps import _fail, _resolve_elder_uid, _same_tenant, _user

_log = logging.getLogger(__name__)

# 状态列的默认名（绝大多数表用 status；个别表用 audit_status）
_STATE_COLUMNS = {"knowledge_base": "audit_status", "health_contents": "audit_status"}


def _request_from(args, kwargs):
    """从路由参数里找出请求对象。

    既认真正的 `Request`，也认测试里常用的鸭子类型（带 `state.user` 的 SimpleNamespace）——
    否则单测直接调用路由函数时会被判成"接线错误"，而那其实只是测试替身。
    """
    for v in list(kwargs.values()) + list(args):
        if isinstance(v, Request):
            return v
        state = getattr(v, "state", None)
        if state is not None and hasattr(state, "user"):
            return v
    return None


def _row_field(table: str, row_id, column: str):
    """按 id 取某一列（表名由调用方在**装饰器里写死**，不接受请求参数拼 SQL）。"""
    from data.db_core import get_db
    with get_db() as conn:
        row = conn.execute(f"SELECT {column} FROM {table} WHERE id=?", (row_id,)).fetchone()
    if not row:
        return None
    return row[column]


def write_route(*, roles: Sequence[str] = (), table: str = "", id_param: str = "",
                require_state: Sequence[str] = (), owner_column: str = "",
                allow_family: bool = False, note: str = "") -> Callable:
    """统一写入口装饰器。参数都是**声明式**的，不传就不检查那一项。"""
    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            request = _request_from(args, kwargs)
            if request is None:
                # 装饰器必须能拿到请求对象才能做授权：这是接线错误，**直接报错**而不是放行
                raise RuntimeError(f"write_route 需要 Request 参数：{fn.__qualname__}")

            u = _user(request) or {}
            if not u:
                return _fail(1001, "请先登录")
            if roles and u.get("role") not in roles:
                return _fail(1003, f"无权限（需要 {'/'.join(roles)} 角色）")

            if table and id_param:
                # ⚠️ 路由函数被**直接调用**时（单测、内部复用）id 可能是位置参数，
                # 所以必须按签名绑定，而不是只看 kwargs —— 否则会误报"找不到 id 参数"。
                try:
                    bound = inspect.signature(fn).bind_partial(*args, **kwargs)
                    row_id = bound.arguments.get(id_param)
                except TypeError:
                    row_id = kwargs.get(id_param)
                if row_id is None:
                    raise RuntimeError(f"write_route 找不到 id 参数 {id_param}：{fn.__qualname__}")
                if not _same_tenant(request, table, row_id):
                    return _fail(1003, "无权限操作该记录（非本社区或记录不存在）")
                if require_state:
                    col = _STATE_COLUMNS.get(table, "status")
                    state = _row_field(table, row_id, col)
                    if state is None:
                        return _fail(1004, "记录不存在")
                    if state not in require_state:
                        return _fail(2001, f"当前状态「{state}」不支持该操作，请刷新后重试")
                if owner_column:
                    owner = _row_field(table, row_id, owner_column)
                    if owner is None:
                        return _fail(1004, "记录不存在")
                    acting = _resolve_elder_uid(request) if allow_family else None
                    acting = acting or u.get("uid")
                    try:
                        if int(owner or 0) != int(acting or 0):
                            return _fail(1003, "无权限操作该记录（只能操作本人或已绑定家属的数据）")
                    except (TypeError, ValueError):
                        return _fail(1003, "无权限操作该记录")
            return fn(*args, **kwargs)

        wrapper.__write_route__ = {          # 供静态门禁读取（声明即证据）
            "roles": list(roles), "table": table, "id_param": id_param,
            "require_state": list(require_state), "owner_column": owner_column,
            "allow_family": allow_family, "note": note,
        }
        return wrapper
    return deco
