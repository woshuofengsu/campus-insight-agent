# scripts/shots.py — 自检用：真实浏览器渲染截图（不参与 pytest，不影响业务）
# -*- coding: utf-8 -*-
"""用 Playwright 打开本机运行的 Web 服务，逐角色/逐页面截图，供「我看着调」的视觉复核。

用法：
  python scripts/shots.py                 # 默认截到 .shots/（临时目录）
  python scripts/shots.py --out D:\\tmp\\s --base http://127.0.0.1:8000

说明：本脚本只读页面、只写 PNG，不改任何数据；需要 DEMO_MODE=true 的演示账号。
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROLE_BTN = {"resident": "居民", "elderly": "老年", "grid": "网格员"}


def shot_role(browser, base, out, name, role, path, viewport, wait=3200, dark=False):
    ctx = browser.new_context(viewport=viewport, device_scale_factor=1)
    # 暗色必须用 localStorage 预置主题（ci_theme），不能靠点「🌙 夜间」按钮：
    # 老年端布局压根没有这个按钮，点击会超时 → 截出的浅色图被命名成 -dark（评审 B3 抓到的正是这个）。
    if dark:
        ctx.add_init_script("localStorage.setItem('ci_theme','dark')")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.on("console", lambda m: errs.append("console.error: " + m.text) if m.type == "error" else None)

    page.goto(f"{base}/login", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1400)  # 等入场动效与数字滚动稳定
    if name == "login":
        page.screenshot(path=os.path.join(out, f"{name}.png"))
    else:
        page.get_by_text(ROLE_BTN[role], exact=True).first.click()
        # 演示登录后会先跳到该角色的首页，再导航到目标路由
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        page.wait_for_timeout(600)
        page.goto(f"{base}{path}", wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(wait)
        # 主题已由 add_init_script 预置；这里只做一次断言式自检，防止再出现
        # 「文件名叫 -dark、内容其实是浅色」的假截图
        if dark:
            cls = page.evaluate("() => document.body.className")
            if "dark" not in cls:
                errs.append(f"dark 未生效：body.className={cls!r}")
        page.screenshot(path=os.path.join(out, f"{name}.png"))
    ctx.close()
    return errs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".shots"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    from playwright.sync_api import sync_playwright

    desk = {"width": 1440, "height": 900}
    wide = {"width": 1920, "height": 1080}
    phone = {"width": 390, "height": 844}

    plan = [
        ("login", None, None, desk, False),
        ("screen", None, "/screen", wide, False),
        ("grid-dashboard", "grid", "/grid/dashboard", desk, False),
        ("grid-workorders", "grid", "/grid/work-orders", desk, False),
        ("resident-home", "resident", "/resident/home", phone, False),
        ("resident-orders", "resident", "/resident/work-orders", phone, False),
        ("elderly-home", "elderly", "/elderly/home", phone, False),
        ("elderly-home-dark", "elderly", "/elderly/home", phone, True),
    ]

    problems = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, role, path, vp, dark in plan:
            if name == "screen":
                # 大屏无需登录（公开路由）
                ctx = browser.new_context(viewport=vp)
                pg = ctx.new_page()
                errs = []
                pg.on("pageerror", lambda e, box=errs: box.append(str(e)))
                pg.goto(f"{args.base}{path}", wait_until="networkidle", timeout=30000)
                pg.wait_for_timeout(4000)
                pg.screenshot(path=os.path.join(args.out, f"{name}.png"))
                ctx.close()
            else:
                errs = shot_role(browser, args.base, args.out, name, role, path, vp, dark=dark)
            if errs:
                problems[name] = errs[:4]
            print(f"[shot] {name} -> {os.path.join(args.out, name + '.png')}" + (f"  ⚠ {errs[:2]}" if errs else ""))
        browser.close()

    print("\n页面 JS 报错：", problems if problems else "无")
    return 0


if __name__ == "__main__":
    sys.exit(main())
