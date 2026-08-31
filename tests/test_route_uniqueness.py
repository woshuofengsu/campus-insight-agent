# -*- coding: utf-8 -*-
"""WS0.4：路由唯一性测试——防止重复注册导致死代码 / 覆盖（竞态可见）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import tempfile  # noqa: E402

config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="route_"), "route.db")


def test_no_duplicate_routes():
    import api_web
    from utils.routes import collect_http_routes
    seen = collect_http_routes(api_web.app)
    assert seen, "期望至少存在一些 HTTP 路由"
    dupes = [x for x in set(seen) if seen.count(x) > 1]
    assert not dupes, f"发现重复路由: {dupes}"
