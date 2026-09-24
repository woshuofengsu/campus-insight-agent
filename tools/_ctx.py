# tools/_ctx.py
"""Agent 工具的租户解析入口（多租户 B7）。

**为什么需要这个文件**：`tools/*.py` 是被 LangChain 引擎/插件/备线调用的**普通函数**，
它们拿不到 FastAPI 的 `Request`，却又要按租户过滤数据。历史写法是
`tenant=default_community()`——等于"永远看成默认社区"：朝阳用户问"有哪些提案"会看到
海淀的提案。这属于**对话文本里的跨租户泄漏**，页面审计抓不到。

解析顺序（都不猜社区，末位返回空串由调用方 fail-closed）：
  1. `utils.tenant.ctx_tenant()`——入口处 `with tenant_context(...)` 显式声明的**请求级上下文**
     （主服务会话处理、插件入口都这么设；用 contextvars，并发不串味）；
  2. Streamlit 备线的登录用户社区（`ui._tenant.current_tenant`，仅备线进程存在）；
  3. 返回 `""`（**不返回默认社区**）——调用方要么给出"无法确定所在社区"的明确提示，
     要么显式声明自己按默认社区运行（见 `api.py` 的插件入口）。
"""
import logging

_log = logging.getLogger(__name__)


def tool_tenant() -> str:
    """解析工具应使用的租户；解析不到返回空串（**绝不猜社区**）。"""
    from utils.tenant import ctx_tenant
    t = ctx_tenant()
    if t:
        return t
    try:
        # 备线（Streamlit）走**严格版**：只认登录会话里的真实社区。
        # 不能用 ui._tenant.current_tenant()——它拿不到就回落默认社区，
        # 那正是"朝阳用户看到海淀数据"的来源（实测踩到）。
        from ui._tenant import session_tenant_or_empty as _ui_tenant
        t = _ui_tenant()
        if t:
            return t
    except Exception:  # noqa: BLE001 — 主服务里没有 streamlit/ui，属正常情况
        _log.debug("无备线租户上下文（主服务正常情况）", exc_info=True)
    _log.warning("工具拿不到租户上下文（未登录/未声明社区）→ 按 fail-closed 处理，"
                 "调用方应给出明确提示而不是展示其它社区的数据")
    return ""


__all__ = ["tool_tenant"]
