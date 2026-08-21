# -*- coding: utf-8 -*-
"""前端页面冒烟：所有 SPA 路由 + 关键静态资源可访问（HTTP 200），验证渲染无异常。"""
import json
import sys
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"

# 三端全部路由（SPA history fallback）
ROUTES = [
    "/login", "/screen",
    "/resident/home", "/resident/work-orders", "/resident/work-orders/1",
    "/resident/work-orders/new", "/resident/proposals", "/resident/proposals/1",
    "/resident/proposals/new", "/resident/notices", "/resident/qa", "/resident/health",
    "/resident/weather", "/resident/messages",
    "/grid/dashboard", "/grid/work-orders", "/grid/proposals", "/grid/notices",
    "/grid/qa", "/grid/weather", "/grid/health", "/grid/elderly-care",
    "/elderly/home", "/elderly/report", "/elderly/medication", "/elderly/notices",
    "/elderly/contacts", "/elderly/orders", "/elderly/qa",
]
ASSETS = ["/", "/index.html", "/src/main.js", "/favicon.svg"]

fails = []
oks = 0
for path in ROUTES + ASSETS:
    url = BASE + path
    try:
        req = urllib.request.Request(url)
        req.add_header("Accept", "text/html,application/xhtml+xml,application/javascript,*/*")
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", "ignore")
            ok = resp.status == 200 and 'id="app"' in body
            if ok:
                oks += 1
            else:
                fails.append(f"{path}: status={resp.status} 无app挂载点" if resp.status == 200 else f"{path}: status={resp.status}")
    except Exception as e:  # noqa: BLE001
        fails.append(f"{path}: {e}")

print(f"页面冒烟：{oks}/{len(ROUTES) + len(ASSETS)} 通过")
for f in fails:
    print("  FAIL:", f)
print("结论：", "PASS" if not fails else f"{len(fails)} 个失败")
