# scripts/shoot_ppt_assets.py — 抓路演 PPT 需要的真实界面截图
# -*- coding: utf-8 -*-
"""为什么需要它：PPT 上"字少图多"才好看，但现场临时截图容易漏、容易糊、容易带调试痕迹。
本脚本用 Playwright 按固定动线把 8 张图一次抓齐，命名规范、尺寸统一，直接放进 PPT。

用法：
    python scripts/shoot_ppt_assets.py            # 默认输出 docs/competition/ppt-assets/
    python scripts/shoot_ppt_assets.py --out D:\\素材

前置：服务已在 http://127.0.0.1:8000 运行（python scripts/serve_public.py --no-tunnel --no-open）。
注意：本脚本只读页面；老年端长按 SOS 后**点取消**，不真发求助。
"""
import argparse
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

BASE = "http://127.0.0.1:8000"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DESK = {"width": 1440, "height": 900}     # 桌面端（居民/网格/登录）
PHONE = {"width": 390, "height": 844}     # 手机端（老年）


def main() -> int:
    ap = argparse.ArgumentParser(description="抓路演 PPT 用截图")
    ap.add_argument("--out", default=os.path.join(ROOT, "docs", "competition", "ppt-assets"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    from playwright.sync_api import sync_playwright

    def shot(page, name):
        path = os.path.join(args.out, name)
        page.screenshot(path=path, full_page=False)
        print(f"   ✅ {name}  ({os.path.getsize(path)//1024} KB)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()

        # ---------- 1) 登录页 ----------
        ctx = browser.new_context(viewport=DESK)
        page = ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_timeout(2500)                     # 等数字滚动动画走完
        shot(page, "01-登录页.png")
        ctx.close()

        # ---------- 2) 居民端（免密）----------
        ctx = browser.new_context(viewport=DESK)
        page = ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_timeout(600)
        page.get_by_text("居民", exact=True).first.click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        page.wait_for_timeout(2200)
        shot(page, "02-居民首页与社区小助手.png")

        # ---------- 3) 政策问答（看依据与属地）----------
        page.goto(f"{BASE}/resident/qa", wait_until="networkidle")
        page.wait_for_timeout(1200)
        try:
            page.get_by_placeholder("输入您想问的政策问题", exact=False).first.fill("高龄老人有什么补贴")
            page.get_by_text("提问", exact=False).last.click()
            page.wait_for_timeout(3500)
            shot(page, "03-政策问答带依据与属地.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （政策问答截图降级：{type(e).__name__}）")

        # ---------- 4) 天气联动 → 执行链 ----------
        page.goto(f"{BASE}/resident/home", wait_until="networkidle")
        page.wait_for_timeout(1500)
        try:
            inp = page.locator("textarea").first
            inp.click()
            inp.fill("明天高温，老人要注意什么")
            page.keyboard.press("Enter")
            page.wait_for_timeout(4500)
            chain = page.get_by_text("多智能体执行链", exact=False).first
            if chain.count():
                chain.click()
                page.wait_for_timeout(1200)
            shot(page, "04-多智能体执行链.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （执行链截图降级：{type(e).__name__}）")

        # ---------- 5) 报修工单详情（处理留痕）----------
        try:
            page.goto(f"{BASE}/resident/work-orders", wait_until="networkidle")
            page.wait_for_timeout(1500)
            first_row = page.locator("tbody tr").first
            if first_row.count():
                first_row.click()
                page.wait_for_timeout(1800)
            shot(page, "05-工单详情与处理留痕.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （工单详情截图降级：{type(e).__name__}）")
        ctx.close()

        # ---------- 6) 网格员工作台 ----------
        ctx = browser.new_context(viewport=DESK)
        page = ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_timeout(600)
        try:
            page.get_by_placeholder("如 demo_grid").first.fill("demo_grid")
            page.get_by_placeholder("demo_grid / demo123").first.fill("demo123")
            page.get_by_text("登 录", exact=False).first.click()
            page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
            page.wait_for_timeout(2200)
            shot(page, "06-网格员工作台.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （网格员端截图降级：{type(e).__name__}）")
        ctx.close()

        # ---------- 7) 老年端（手机视口）+ SOS 确认框 ----------
        ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
        page = ctx.new_page()
        page.goto(f"{BASE}/login", wait_until="networkidle")
        page.wait_for_timeout(600)
        try:
            page.get_by_text("老年", exact=True).first.click()
            page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
            page.wait_for_timeout(2200)
            shot(page, "07-老年端大字首页.png")
            # 长按 SOS 3 秒 → 出确认框 → 截图 → 点取消
            btn = page.get_by_text("SOS", exact=False).first
            box = btn.bounding_box()
            if box:
                page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                page.mouse.down()
                page.wait_for_timeout(3400)
                page.mouse.up()
                page.wait_for_timeout(900)
                shot(page, "08-老年端长按求助确认框.png")
                cancel = page.get_by_text("取消", exact=True)
                if cancel.count():
                    cancel.first.click()          # 绝不真发求助
                    page.wait_for_timeout(500)
        except Exception as e:  # noqa: BLE001
            print(f"   （老年端截图降级：{type(e).__name__}）")
        ctx.close()
        browser.close()

    print(f"\n截图目录：{args.out}")
    print("提示：把这几张图按顺序拖进 PPT 对应页即可；勿用带调试面板/控制台的截图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
