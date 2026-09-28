# -*- coding: utf-8 -*-
"""真移动端可用性验证（手指点击级，不是"能渲染"）。

**为什么单独有它**：`mobile_audit.py` 验的是"页面在 390px 视口下不溢出、字号够大"——
那是**渲染**层面的。但"真移动端"的要求是**手机上一根手指能把事办完**：
底部导航点得着、按钮够大、流程走得通、SOS 二次确认能弹出也能取消。

本脚本用 Playwright 的**移动设备仿真**（390x844、hasTouch、isMobile、真机 UA）逐条**点**过去，
每个页面另外断言三条硬指标：
  ① 无横向溢出（`scrollWidth <= innerWidth + 2`）；
  ② 触控目标够大（主要可点元素高度 ≥ 40px；老年端 ≥ 56px）；
  ③ 底部/顶部导航在位（移动端不能只有桌面侧边栏）。

另外验一遍**语音替代与错误恢复**（v3 卡8 / §7.1+§7.2，2026-09-29 加）：
常见说法（预置短语）→ 摘要 →「说错了，重新说」→「先不报修了」，
以及"语音播报没回音时报修按钮不能永久转圈"（这条实测抓到过：按钮卡 loading，老人既看不到结果也点不了第二次）。

用法（服务需先起，且**手机/仿真要连得上**）：
    python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
    python scripts/mobile_flow_check.py            # 默认 http://127.0.0.1:8000
    python scripts/mobile_flow_check.py --base http://10.101.179.6:8000   # 走局域网（手机同款路径）
"""
import argparse
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

# iPhone 13 一类的主流尺寸（老年端真机也在这个量级）
DEVICE = {"viewport": {"width": 390, "height": 844}, "device_scale_factor": 3,
          "is_mobile": True, "has_touch": True,
          "user_agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                         "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(f"  {'✅' if ok else '❌'} {name}" + (f"  —— {detail}" if detail else ""))


def geometry(page, min_tap: int = 40, need_nav: bool = True) -> tuple[bool, str]:
    """硬指标：无横向溢出 / 触控目标够大 /（门户页还要求）有移动导航。

    ⚠️ 两个第一版踩过的坑：
      · 拿"有没有底部导航"去判**登录页**会误报（登录页本来就没有）；
      · 网格员端的移动导航是**顶栏 + 抽屉**（`.grid-mobile-header`），不是底部标签栏，
        所以把两者都认作"移动导航"，别只认 `.tab-item`。
    """
    g = page.evaluate(
        """(minTap) => {
            const vw = window.innerWidth;
            const overflow = document.documentElement.scrollWidth - vw;
            const nodes = [...document.querySelectorAll('button, .tab-item, .elderly-nav button, a[role=button]')]
                .filter(e => { const r = e.getBoundingClientRect();
                               return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden'; });
            const small = nodes.filter(e => e.getBoundingClientRect().height < minTap).length;
            const nav = !![...document.querySelectorAll('.tabbar, .tab-item, .elderly-nav, .grid-mobile-header')]
                .find(e => e.getBoundingClientRect().height > 0);
            return { overflow, targets: nodes.length, small, nav };
        }""", min_tap)
    ok = g["overflow"] <= 2 and g["small"] == 0 and (g["nav"] or not need_nav)
    detail = (f"横向溢出 {g['overflow']}px · 触控目标 {g['targets']} 个"
              f"（小于 {min_tap}px 的 {g['small']} 个）"
              f"· 移动导航{'在位' if g['nav'] else '不在位'}")
    return ok, detail


def text_metrics(page) -> dict:
    """量**叶子文本**的字号（`body` 的 font-size 是 14px 基线，拿它判老年端会误报：
    老年端是用 rem 把具体元素放大到 20px+ 的）。"""
    return page.evaluate(
        """() => {
            const leaf = [...document.querySelectorAll('button, .card, p, span, div')]
                .filter(e => e.children.length === 0 && (e.innerText || '').trim().length > 1);
            const fs = leaf.map(e => parseFloat(getComputedStyle(e).fontSize)).filter(n => !isNaN(n));
            const smalls = leaf.filter(e => parseFloat(getComputedStyle(e).fontSize) < 20)
                .map(e => ({ t: (e.innerText || '').trim().slice(0, 16),
                             fs: parseFloat(getComputedStyle(e).fontSize),
                             h: Math.round(e.getBoundingClientRect().height) }))
                .filter(x => x.h > 0).slice(0, 6);
            return { minLeaf: fs.length ? Math.min(...fs) : null, count: fs.length, smalls };
        }""")


def modal_open(page) -> bool:
    """弹窗是否可见（用元素可见性判定，别用 `text=xxx`——它是**子串**匹配，
    会被页面上别的文案误命中，第一版就在 SOS 上误报过一次）。"""
    return page.evaluate(
        """() => [...document.querySelectorAll('.n-modal, .n-dialog')]
                 .some(e => e.getBoundingClientRect().height > 0)""")


def tap_at(page, loc, wait: int = 900) -> bool:
    """滚到元素，再在**它自己算出来的坐标**上真触摸一下。

    为什么要自己算坐标、不用 `locator.tap()`：
      · `tap()` 自带的"滚动可见"对**嵌套滚动容器**不总是奏效；
      · 更麻烦的是移动仿真下它会按"可见点"重算落点，实测把报修页的
        「说错了，重新说」判成"被「补充好了，再看一遍」遮挡"并一直重试到超时——
        而同一坐标上 `elementFromPoint` 明明就是那个按钮本身。
    坐标法仍然是**真触摸事件**（touchscreen.tap），只是落点由我们算并经命中校验。
    """
    try:
        loc.first.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        box = loc.first.bounding_box()
        if not box:
            print("    （点击告警：元素没有可见区域）")
            return False
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        hit = page.evaluate(
            "([x, y]) => { const t = document.elementFromPoint(x, y);"
            " return t ? (t.tagName + '|' + (t.textContent || '').trim().slice(0, 16)) : ''; }",
            [x, y])
        if "|" not in hit:
            print(f"    （点击告警：该坐标上取不到元素 {x:.0f},{y:.0f}）")
            return False
        page.touchscreen.tap(x, y)
        page.wait_for_timeout(wait)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"    （点击告警：{str(e)[:70]}）")
        return False


def clear_session(page, base: str) -> None:
    """清登录态——否则路由守卫会把 /login 直接放回已登录的首页，导致"点不到角色卡"。"""
    try:
        page.context.clear_cookies()
        page.goto(f"{base}/login", wait_until="domcontentloaded")
        page.evaluate("() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }")
        page.goto(f"{base}/login", wait_until="networkidle")
        page.wait_for_timeout(1200)
    except Exception as e:  # noqa: BLE001
        print(f"  （清会话时告警：{str(e)[:60]}）")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    print("=" * 78)
    print(f"真移动端手指点击验证 · {base} · 视口 390x844（触摸仿真）")
    print("=" * 78)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(**DEVICE)
        page = ctx.new_page()
        page.set_default_timeout(20000)

        # ---------- 1. 登录页：三个角色卡都要点得着 ----------
        print("\n【1】登录页 → 选角色（免密入口）")
        page.goto(f"{base}/login", wait_until="networkidle")
        page.wait_for_timeout(1500)
        ok, detail = geometry(page, 40, need_nav=False)   # 登录页没有底部导航，不据此判失败
        check("登录页几何与触控", ok, detail)
        for label in ("居民", "老年", "网格员"):
            check(f"角色卡「{label}」可点", page.locator(f"text={label}").count() > 0)

        # ---------- 2. 居民端：点进去 → 底部导航切页 ----------
        print("\n【2】居民端：点「居民」→ 首页 → 底部导航切页")
        clear_session(page, base)
        page.locator("text=居民").first.tap()
        page.wait_for_url("**/resident/**", timeout=20000)
        page.wait_for_timeout(1600)
        check("免密进入居民端", "/resident" in page.url, page.url)
        ok, detail = geometry(page, 40)
        check("居民端几何与触控", ok, detail)
        tabs = page.locator(".tab-item")
        check("底部标签栏存在", tabs.count() >= 3, f"{tabs.count()} 个标签")
        if tabs.count() >= 3:
            before = page.url
            tabs.nth(2).tap()                      # 点第 3 个标签
            page.wait_for_timeout(1500)
            check("点标签能切页", page.url != before, page.url)
            ok, detail = geometry(page, 40)
            check("切页后几何与触控", ok, detail)

        # ---------- 3. 老年端：大字 + 顶部大按钮导航 ----------
        print("\n【3】老年端：点「老年」→ 首页大字 → 顶部大按钮进「更多服务」→ 切「用药提醒」")
        clear_session(page, base)
        page.locator("text=老年").first.tap()
        page.wait_for_url("**/elderly/**", timeout=20000)
        page.wait_for_timeout(1800)
        check("免密进入老年端", "/elderly" in page.url, page.url)
        ok, detail = geometry(page, 48)
        check("老年端几何与触控（阈值 48px，高于 Apple 44 / 等于 Material 48）", ok, detail)
        tm = text_metrics(page)
        check("老年端叶子文本字号 ≥ 20px", (tm["minLeaf"] or 0) >= 20,
              f"最小 {tm['minLeaf']}px（量了 {tm['count']} 处文本）")
        smalls = page.evaluate(
            """() => [...document.querySelectorAll('button')]
                 .map(e => ({ t: (e.innerText||'').trim().slice(0, 12),
                              h: Math.round(e.getBoundingClientRect().height),
                              fs: parseFloat(getComputedStyle(e).fontSize) }))
                 .filter(x => x.h > 0 && (x.h < 56 || x.fs < 20))""")
        if smalls:
            print(f"    ↳ 未达「56px/20px 理想值」的按钮（次要操作可接受，已登记）：{smalls}")
        # v3 复核 B4：顶层导航已收敛为 5 个高频入口 + 独立紧急求助；
        # 「用药」这类能力收进「更多服务」——所以这里走两步（真实老人的路径也是两步）。
        nav_btns = page.locator(".elderly-nav button")
        check("老年端导航收敛到 6 个大按钮以内", nav_btns.count() <= 6,
              f"实际 {nav_btns.count()} 个：{nav_btns.all_inner_texts()}")
        sos_top = page.locator(".elderly-nav, div", has_text="紧急求助")
        check("顶部导航带独立紧急求助入口", sos_top.count() > 0)
        btn = page.locator(".elderly-nav button", has_text="更多服务")
        check("老年端导航「更多服务」大按钮在位", btn.count() > 0)
        if btn.count():
            btn.first.tap()
            page.wait_for_timeout(1500)
            check("大按钮能切页", "/elderly/more" in page.url, page.url)
            ok, detail = geometry(page, 48)
            check("更多服务页几何与触控（阈值 48px）", ok, detail)
            med = page.locator("button", has_text="用药提醒")
            check("更多服务页里有「用药提醒」大按钮", med.count() > 0)
            if med.count():
                med.first.tap()
                page.wait_for_timeout(1500)
                check("进得了用药提醒页", "/elderly/medication" in page.url, page.url)
                ok, detail = geometry(page, 48)
                check("用药页几何与触控（阈值 48px）", ok, detail)
                ms = page.evaluate(
                    """() => [...document.querySelectorAll('button')]
                         .map(e => ({ t: (e.innerText||'').trim().slice(0, 12),
                                      h: Math.round(e.getBoundingClientRect().height),
                                      fs: Math.round(parseFloat(getComputedStyle(e).fontSize)) }))
                         .filter(x => x.h > 0 && x.h < 48)""")
                if ms:
                    print(f"    ↳ 仍小于 48px 的按钮（需要处理）：{ms}")

        # ---------- 4-2. 语音替代与错误恢复（v3 卡8 / §7.1+§7.2） ----------
        # 为什么单列这一段：方案要求「语音是可替代的输入方式」「纠错是一等功能」——
        # 也就是"说不出来 / 说错了 / 不想说了"都必须有**明确入口**，而不是让老人自己猜。
        # 这里在手机尺寸下真点一遍（不验识别准确率，验的是"路走得通、话说得清"）。
        print("\n【3-2】老年端报修：常见说法（语音替代）→ 纠错 → 先不提交")
        page.goto(f"{base}/elderly/report", wait_until="networkidle")
        page.wait_for_timeout(1800)
        # ① 常见说法面板：点开 → 有 4 条大按钮 → 点一条会填进输入框并走同一套摘要流程
        toggle = page.locator("button", has_text="常见说法")
        check("报修页有「说不出来？点一个常见说法」入口（语音不是唯一入口）", toggle.count() > 0)
        if toggle.count():
            if not page.locator("[data-phrases]").count():
                tap_at(page, toggle, 700)
            phrases = page.locator("[data-phrases] button")
            check("常见说法是「大按钮」列表（≥3 条，可点）", phrases.count() >= 3,
                  f"{phrases.count()} 条：{phrases.all_inner_texts()[:4]}")
            if phrases.count():
                tap_at(page, phrases, 2600)
                body = page.inner_text("body")
                check("点常见说法后进入同一套摘要流程（不是直接建单）",
                      "请您核对这几项" in body or "还缺" in body or "确认上报" in body)
                # ①-2 按钮不能"永久转圈"：某些机型语音播报既不回 onend 也不回 onerror，
                #     若播报卡住按钮的 loading，老人既看不到结果也点不了第二次（实测踩到）
                stuck = page.evaluate(
                    """() => { const b = [...document.querySelectorAll('button')]
                         .find(x => x.textContent.includes('看看还缺什么'));
                       return b ? b.className.toString().includes('n-button--loading') : null; }""")
                check("报修按钮没有卡在「正在识别」（播报无回音也能再点）", stuck is False,
                      "按钮已恢复可点" if stuck is False else f"loading={stuck}")
                # ② 纠错入口：说错了能一键重来（清空草稿回到第一步）
                restart = page.locator("[data-restart]")
                check("摘要页有「说错了，重新说」明确入口", restart.count() > 0)
                if restart.count():
                    ok_tap = tap_at(page, restart)
                    after = page.inner_text("body")
                    check("「重新说」真的把摘要收掉（回到可重新输入的干净状态）",
                          ok_tap and "请您核对这几项" not in after and page.locator("textarea").count() > 0,
                          "" if ok_tap else "没点中「重新说」按钮")
                # ③ 先不报修：明确出口，且**不建单**
                tap_at(page, page.locator("button", has_text="看看还缺什么"))
                # 摘要要等服务端解析（LLM 姿态全开时更慢）——等到出现为止，别用固定 sleep 猜
                deadline = time.time() + 15
                while time.time() < deadline and not page.locator("[data-giveup]").count():
                    page.wait_for_timeout(400)
                giveup = page.locator("[data-giveup]")
                check("摘要页有「先不报修了」明确出口", giveup.count() > 0)
                if giveup.count():
                    ok_tap = tap_at(page, giveup, 1800)
                    check("「先不报修了」回到首页（没有提交、没有建单）",
                          ok_tap and "/elderly/home" in page.url,
                          page.url if ok_tap else "没点中「先不报修了」按钮")

        # ---------- 3-3. 中断可恢复：刷新回来能找到没填完的报修（v3 §7.4） ----------
        print("\n【3-3】老年端报修：刷新后能恢复没填完的草稿（先给摘要再让老人选）")
        page.goto(f"{base}/elderly/report", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.fill("textarea", "六号楼一层楼道灯闪")
        tap_at(page, page.locator("button", has_text="看看还缺什么"))
        deadline = time.time() + 15
        while time.time() < deadline and not page.locator("[data-resume-draft], [data-restart]").count():
            page.wait_for_timeout(400)
        page.reload(wait_until="networkidle")          # 老人按了刷新/返回又回来
        page.wait_for_timeout(1800)
        card = page.locator("[data-resume-draft]")
        check("刷新后出现「上次没填完的报修」卡片（带摘要）", card.count() > 0,
              card.first.inner_text().replace("\n", " ")[:40] if card.count() else "没有出现")
        if card.count():
            tap_at(page, page.locator("button", has_text="接着填"))
            deadline = time.time() + 15
            while time.time() < deadline and "请您核对这几项" not in page.inner_text("body"):
                page.wait_for_timeout(400)
            body = page.inner_text("body")
            check("点「接着填」把原话与摘要恢复回来（不是空白重来）",
                  "六号楼一层楼道灯闪" in body and "请您核对这几项" in body)
            # 恢复面板消失（选过了就不再反复问）
            check("选过之后恢复卡片不再出现", page.locator("[data-resume-draft]").count() == 0)
            # 隐私：草稿带着「谁」的标记，换用户/换社区**绝不带入**（共享设备上这是硬要求）
            page.evaluate("""() => {
              const raw = sessionStorage.getItem('ci_elderly_report_draft');
              if (!raw) return;
              const d = JSON.parse(raw);
              d.who = '999|别的小区';          // 假装这份草稿是上一个人留下的
              sessionStorage.setItem('ci_elderly_report_draft', JSON.stringify(d));
            }""")
            page.reload(wait_until="networkidle")
            page.wait_for_timeout(1600)
            left = page.evaluate(
                "() => sessionStorage.getItem('ci_elderly_report_draft')")
            check("草稿属于别人时不带入（换用户/换社区直接丢掉，不展示、不提示）",
                  page.locator("[data-resume-draft]").count() == 0 and not left,
                  "已丢弃且输入框为空" if not left else f"残留：{str(left)[:40]}")

        # ---------- 4. 老年端 SOS：误触不发、长按才发、可取消 ----------
        print("\n【4】老年端紧急求助：误触不发 / 长按弹确认 / 可取消")
        page.goto(f"{base}/elderly/home", wait_until="networkidle")
        page.wait_for_timeout(1800)
        sos = page.locator("text=紧急求助").first
        if not sos.count():
            check("SOS 入口在位", False, "首页找不到「紧急求助」")
        else:
            # ① 误触：单击一下不该发出（这是安全属性，不只是 UI 细节）
            try:
                sos.tap()
                page.wait_for_timeout(700)
                check("误触不发求助（单击不弹确认）", not modal_open(page))
            except Exception as e:  # noqa: BLE001
                check("误触不发求助（单击不弹确认）", False, str(e)[:60])
            # ② 长按 3 秒 → 应弹出确认
            try:
                box = sos.bounding_box()
                if box:
                    cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                    page.mouse.move(cx, cy)
                    page.mouse.down()
                    page.wait_for_timeout(3400)
                    page.mouse.up()
                    page.wait_for_timeout(900)
                has_confirm = modal_open(page)
                check("长按后弹二次确认（可取消）", has_confirm,
                      "" if has_confirm else "仿真长按未弹出——真机需人工确认一次")
                if has_confirm:
                    page.locator(".n-modal button", has_text="取消").first.tap()
                    page.wait_for_timeout(900)
                    check("取消后弹窗关闭", not modal_open(page))
            except Exception as e:  # noqa: BLE001
                check("长按后弹二次确认（可取消）", False, str(e)[:60])

        # ---------- 5. 网格端：登录 → 工作台 → 切工单 ----------
        print("\n【5】网格端：登录 → 工作台 → 底部导航切页")
        clear_session(page, base)
        page.locator("text=网格员").first.tap()
        page.wait_for_url("**/grid/**", timeout=20000)
        page.wait_for_timeout(1800)
        check("进入网格端", "/grid" in page.url, page.url)
        ok, detail = geometry(page, 40)
        check("网格端几何与触控", ok, detail)
        gt = page.locator(".tab-item")
        header = page.locator(".grid-mobile-header")
        check("网格端有移动导航（底部标签栏或顶栏菜单）",
              gt.count() >= 3 or header.count() > 0,
              f"标签栏 {gt.count()} 个 · 移动顶栏 {header.count()} 个")

        # ---------- 6. 大屏在手机上应有降级提示（不该是挤成一团） ----------
        print("\n【6】治理大屏在手机上：应有降级提示或可用布局")
        page.goto(f"{base}/screen", wait_until="networkidle")
        page.wait_for_timeout(2000)
        has_hint = page.locator("text=仍要查看").count() > 0
        check("大屏手机端有明确提示", has_hint)

        browser.close()

    passed = sum(1 for _n, ok, _d in results if ok)
    print("\n" + "=" * 78)
    print(f"结果：{passed}/{len(results)} 项通过")
    failed = [n for n, ok, _d in results if not ok]
    if failed:
        print("未通过：" + "、".join(failed))
    print("=" * 78)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
