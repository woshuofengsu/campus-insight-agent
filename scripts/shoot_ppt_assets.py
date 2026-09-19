# scripts/shoot_ppt_assets.py — 抓路演 PPT 需要的真实界面截图
# -*- coding: utf-8 -*-
"""为什么需要它：PPT 上"字少图多"才好看，但现场临时截图容易漏、容易糊、容易带调试痕迹。
本脚本用 Playwright 按固定动线把三端界面一次抓齐，命名规范、尺寸统一，直接放进 PPT。

分组（供"三端各两页"的正文结构使用）：
    居民端  01(登录) 02 首页+小助手 / 03 政策问答 / 05 工单详情留痕 / 09 报修列表 / 10 提交报修
            + 11 邻里议事 / 12 通知
    网格员端 06 工作台 + 13 工单管理 / 14 老年关怀管理
    老年端  07 大字首页 / 08 长按求助确认框 + 15 社区小助手 / 16 用药提醒

用法：
    python scripts/shoot_ppt_assets.py            # 默认输出 docs/competition/ppt-assets/
    python scripts/shoot_ppt_assets.py --out D:\\素材

前置：服务已在 http://127.0.0.1:8000 运行（python -m uvicorn api_web:app --port 8000）。
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
        # 注意：居民端对话输入框在 components/AgentChat.vue 里，是 <input>（不是 textarea），
        # placeholder 为「请输入您的问题（如：我家水管漏水了）」。定位器写错会静默失败、用旧图。
        page.goto(f"{BASE}/resident/home", wait_until="networkidle")
        page.wait_for_timeout(1500)
        try:
            inp = page.get_by_placeholder("请输入您的问题", exact=False).first
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

        # ---------- 4b) 居民端：AI 聊天里的「一句话报修」----------
        # 真实流程（已实测，且有状态）：说一句话 → 识别报修意图 → 只追问关键项
        # （如"是您家里还是公共区域？"）→ 回一张「请您确认报修信息：问题/分类/紧急程度」
        # 卡片 + 【确认提交】【取消】。所以抓两帧：①AI 整理好、等人确认（18）
        # ②点确认后生成工单（19）。注意 18/19 是**居民端**；网格员端的处理画面是 17。
        try:
            page.goto(f"{BASE}/resident/home", wait_until="networkidle")
            page.wait_for_timeout(1500)
            box = page.get_by_placeholder("请输入您的问题", exact=False).first
            box.click()
            box.fill("我家厨房水管漏水了")
            page.keyboard.press("Enter")
            page.wait_for_timeout(8000)
            chat = page.locator(".agent-chat").first
            confirm = chat.get_by_text("确认提交", exact=True)
            # 追问补全可能还有 1–2 轮：优先点"家里/公共区域/一般/紧急"这类选项
            for _ in range(3):
                if confirm.count():
                    break
                labels = [t.strip() for t in chat.locator("button").all_inner_texts() if t.strip()]
                pick = next((p for p in ("家里", "公共区域", "一般", "紧急", "是") if p in labels), None)
                if not pick:
                    break
                chat.get_by_text(pick, exact=True).first.click()
                page.wait_for_timeout(6000)
            if confirm.count():
                confirm.first.scroll_into_view_if_needed()
                page.wait_for_timeout(500)
                page.mouse.wheel(0, -150)        # 往上一点，让提问与信息卡同框
                page.wait_for_timeout(400)
                shot(page, "18-居民端-一句话报修.png")
                print("     一句话 → AI 整理出报修单，等居民确认")
                confirm.first.click()            # 真的确认一次，抓"已生成工单"那一帧
                page.wait_for_timeout(5000)
                shot(page, "19-居民端-报修已生成.png")
                print("     确认后：" + " ".join(chat.inner_text().split())[-100:])
            else:
                print("     ⚠️ 没走到「确认提交」：一句话报修的流程可能变了，18/19 未更新")
                print("        当前对话：" + " ".join(chat.inner_text().split())[:160])
        except Exception as e:  # noqa: BLE001
            print(f"   （一句话报修截图降级：{type(e).__name__}）")

        # ---------- 5) 报修列表 + 工单详情（居民视角）----------
        # 坑：居民端列表不是表格，是 `div.card` 卡片（v-for），用 tbody tr 永远点不进去，
        # 会静默产出"两张一样的列表图"。这里改成点卡片标题进详情。
        try:
            page.goto(f"{BASE}/resident/work-orders", wait_until="networkidle")
            page.wait_for_timeout(1800)
            shot(page, "09-报修列表与状态.png")          # 列表页（点进详情前先抓）
            title_link = page.locator("div.card b").first
            if title_link.count():
                title_link.click()
                page.wait_for_timeout(2000)
                shot(page, "05-工单详情与处理留痕.png")
            else:
                print("     ⚠️ 报修列表没有卡片，05 未更新")
        except Exception as e:  # noqa: BLE001
            print(f"   （工单详情截图降级：{type(e).__name__}）")

        # ---------- 5a) 提交报修表单 ----------
        try:
            page.goto(f"{BASE}/resident/work-orders/new", wait_until="networkidle")
            page.wait_for_timeout(1800)
            shot(page, "10-提交报修表单.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （提交报修表单截图降级：{type(e).__name__}）")

        # ---------- 5b) 邻里议事（提案）----------
        try:
            page.goto(f"{BASE}/resident/proposals", wait_until="networkidle")
            page.wait_for_timeout(1800)
            shot(page, "11-居民端-邻里议事.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （邻里议事截图降级：{type(e).__name__}）")

        # ---------- 5c) 通知（四类 + 已读回执）----------
        try:
            page.goto(f"{BASE}/resident/notices", wait_until="networkidle")
            page.wait_for_timeout(1800)
            shot(page, "12-居民端-通知.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （通知截图降级：{type(e).__name__}）")
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

        # ---------- 6b) 网格员端：工单管理（处理与流转）----------
        try:
            page.goto(f"{BASE}/grid/work-orders", wait_until="networkidle")
            page.wait_for_timeout(1800)
            shot(page, "13-网格员端-工单管理.png")
            # 展开第一行 → 露出审核/派单/处理操作区。
            # PPT 第 9 页要的是"网格员端正在处理"的画面，不能用居民端视角的工单详情（05 是居民视角）。
            toggle = page.get_by_text("展开", exact=False).first
            if toggle.count():
                toggle.click()
                page.wait_for_timeout(1200)
                anchor = page.get_by_text("审核意见", exact=False).first
                if anchor.count():
                    anchor.scroll_into_view_if_needed()
                    page.wait_for_timeout(600)
                shot(page, "17-网格员端-工单处理.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （工单管理截图降级：{type(e).__name__}）")

        # ---------- 6c) 网格员端：老年关怀管理 ----------
        try:
            page.goto(f"{BASE}/grid/elderly-care", wait_until="networkidle")
            page.wait_for_timeout(1800)
            shot(page, "14-网格员端-老年关怀.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （老年关怀截图降级：{type(e).__name__}）")
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
            # 注意：按钮文案是「🆘 紧急求助（长按 3 秒）」，**没有 "SOS" 字样**（旧定位器写 "SOS" 会静默失败）；
            # 用 data-longpress 属性定位，并先滚进视口（按钮在长页面下方）。
            btn = page.locator("[data-longpress]").first
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(600)
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
            else:
                print("   （没找到紧急求助按钮，跳过确认框截图）")
        except Exception as e:  # noqa: BLE001
            print(f"   （老年端截图降级：{type(e).__name__}）")

        # ---------- 7b) 老年端：社区小助手（快捷问题大按钮）----------
        try:
            page.goto(f"{BASE}/elderly/agent", wait_until="networkidle")
            page.wait_for_timeout(2200)
            shot(page, "15-老年端-社区小助手.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （老人端小助手截图降级：{type(e).__name__}）")

        # ---------- 7c) 老年端：用药提醒（我吃了 / 10 分钟后再说）----------
        try:
            page.goto(f"{BASE}/elderly/medication", wait_until="networkidle")
            page.wait_for_timeout(2200)
            shot(page, "16-老年端-用药提醒.png")
        except Exception as e:  # noqa: BLE001
            print(f"   （用药提醒截图降级：{type(e).__name__}）")
        ctx.close()
        browser.close()

    print(f"\n截图目录：{args.out}")
    print("提示：把这几张图按顺序拖进 PPT 对应页即可；勿用带调试面板/控制台的截图。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
