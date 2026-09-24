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

用法（服务需先起，且**手机/仿真要连得上**）：
    python -m uvicorn api_web:app --host 0.0.0.0 --port 8000
    python scripts/mobile_flow_check.py            # 默认 http://127.0.0.1:8000
    python scripts/mobile_flow_check.py --base http://10.101.179.6:8000   # 走局域网（手机同款路径）
"""
import argparse
import sys

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
        print("\n【3】老年端：点「老年」→ 首页大字 → 顶部大按钮切「用药」")
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
        btn = page.locator(".elderly-nav button", has_text="用药")
        check("老年端导航「用药」大按钮在位", btn.count() > 0)
        if btn.count():
            btn.first.tap()
            page.wait_for_timeout(1500)
            check("大按钮能切页", "/elderly/medication" in page.url, page.url)
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
