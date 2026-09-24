# ui/_tenant.py
"""Streamlit 备线的租户适配（多租户 v48）。

主路线（FastAPI + Vue）从 JWT 的 `community` 取租户；备线是**旧版演示、非主路线**，
它的页面代码里散着 29 处"跨用户查询"调用（`get_issues()` / `get_sos_calls()` …）。
多租户契约要求这些调用必须带 `tenant=`，否则会**大声报错**（这是刻意的 fail-closed 设计）。

与其改 29 处调用点（多行 import 与嵌套括号很容易改坏——第一版就这么把 6 个文件改崩了），
备线改在**入口处统一注入**：`install_tenant_defaults()` 把 `data/` 里这些函数包一层
"默认带当前租户"的壳。必须在**页面模块被 import 之前**调用
（页面用的是 `from data.db_x import fn` 的名字绑定，晚于它就绑不到壳）。

⚠️ 边界：只影响 Streamlit 备线进程，主服务不走这里；备线不追求真多租户，
拿不到登录用户社区时用默认社区（`config.DEFAULT_COMMUNITY`），**绝不静默放行全量**。
"""
import logging

import streamlit as st

from utils.tenant import default_community, normalize_tenant

_log = logging.getLogger(__name__)

# (模块, 需要注入 tenant 的函数名)
_BINDINGS = {
    "data.db_repair": ["get_issues"],
    "data.db_proposal": ["get_proposals", "get_export_rows"],
    "data.db_notice": ["get_visible_notices", "get_notices", "get_notices_with_stats"],
    "data.db_health_content": ["list_consults"],
    "data.db_policy": ["get_questions", "get_pending_reply_questions", "get_common_questions"],
    "data.db_elderly_care": ["list_medication_reminders", "list_emergency_contacts", "get_sos_calls"],
    "data.db_care_proactive": ["list_inactive_elderly"],
    "data.db_board": ["get_red_black_board", "get_satisfaction_drilldown"],
    "data.db_agent": ["get_agent_logs"],
    "data.db_weather": ["list_check_tasks"],
}


def current_tenant() -> str:
    """当前登录用户的社区；取不到返回默认社区（备线降级，但绝不放行全量）。"""
    try:
        user = st.session_state.get("user") or st.session_state.get("auth_user") or {}
        t = normalize_tenant(user.get("community") if isinstance(user, dict) else "")
        if t:
            return t
    except Exception:  # noqa: BLE001 — 备线可能在没有 session 的脚本里被调用，回落默认社区
        _log.debug("备线取当前租户失败，回落默认社区", exc_info=True)
    return default_community()


def _bind(fn):
    def wrapper(*args, **kwargs):
        kwargs.setdefault("tenant", current_tenant())
        return fn(*args, **kwargs)
    wrapper.__name__ = getattr(fn, "__name__", "wrapped")
    wrapper._tenant_bound = True          # 幂等标记：重复 install 不会套多层
    return wrapper


def install_tenant_defaults() -> int:
    """给备线用到的跨用户查询函数注入 `tenant` 默认值。返回包装了几个函数。"""
    import importlib
    n = 0
    for mod_name, funcs in _BINDINGS.items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception:  # noqa: BLE001 — 允许部分模块缺失，但必须留下日志（不静默）
            _log.warning("备线租户注入：模块 %s 导入失败，跳过", mod_name, exc_info=True)
            continue
        for name in funcs:
            fn = getattr(mod, name, None)
            if fn is None or getattr(fn, "_tenant_bound", False):
                continue
            setattr(mod, name, _bind(fn))
            n += 1
    return n
