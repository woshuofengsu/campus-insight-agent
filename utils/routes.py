# utils/routes.py
"""路由收集工具：把 FastAPI 的惰性 _IncludedRouter 递归展开，得到真实 (path, methods) 列表。

FastAPI 较新版本用 _IncludedRouter 延迟挂载子路由，app.routes 在 import 时只返回一层包装对象，
不能直接用来统计/查重。本模块递归展开，兼兼容（展开失败时退回原始项）。
"""
from collections.abc import Iterable


def collect_http_routes(app) -> list[tuple[str, tuple[str, ...]]]:
    """返回 [(full_path, (methods,))]，仅含真实 HTTP 端点（排除 WS / 静态 mount / sentinel）。"""
    from fastapi.routing import APIRoute
    from starlette.routing import Route

    out: list[tuple[str, tuple[str, ...]]] = []

    def _walk(routes: Iterable, prefix: str = ""):
        for r in routes:
            t = type(r).__name__
            path = getattr(r, "path", "") or ""
            methods = tuple(sorted(m for m in (getattr(r, "methods", frozenset()) or frozenset()) if m))
            if t == "_IncludedRouter":
                include_prefix = getattr(getattr(r, "include_context", None), "prefix", "") or ""
                target = getattr(r, "original_router", None)
                if target is not None:
                    _walk(getattr(target, "routes", []), prefix + include_prefix)
            elif isinstance(r, (APIRoute, Route)):
                full = prefix + path
                if full and methods:
                    out.append((full, methods))
            elif path and methods:
                full = prefix + path
                out.append((full, methods))
            # 其余（WebSocketRoute / Mount / 空 path）忽略

    _walk(app.routes)
    return out
