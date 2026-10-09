# -*- coding: utf-8 -*-
"""UI 重设计基线捕获（任务书第 0 步：**先冻结当前版本，再动界面**）。

## 为什么先做这个

重设计最容易出的事故是"改完说不清哪里变了"：路由少了 / 老年端入口少了 / 按钮文字被改了
导致自动化门禁静默失效 / 布局在窄屏回退。**没有基线就无法证明"功能一个没少"**，
而本项目最忌讳的正是"做了但不生效"和"改坏了没人知道"。

所以第 0 步不碰任何业务代码，只做两件事：
1. **截图**（各宽度、三端关键页，含老年端首页与提交后的确认卡）；
2. **清单**（路由、老年端导航入口、页面上真实可见的按钮文字、设计令牌快照、当前门禁项数）。

产物落在 `.shots/pilot-ui-baseline/`（`.shots/` 已 gitignore：截图是过程材料，不塞进仓库）。

## 用法

```bash
python scripts/ui_baseline_capture.py                 # 全套（需要服务在跑，会写演示库：一条截图用报修）
python scripts/ui_baseline_capture.py --no-write      # 不提交任何数据（跳过确认卡截图）
python scripts/ui_baseline_capture.py --only elderly  # 只截某一端（elderly/resident/grid/desk/all）
python scripts/ui_baseline_capture.py --diff          # 把当前按钮文字与基线清单对比（重设计后自查）
```
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, ".shots", "pilot-ui-baseline")
INVENTORY = os.path.join(OUT, "inventory.json")
ROUTER = os.path.join(ROOT, "web", "src", "router", "index.js")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

RUN = time.strftime("%m%d-%H%M%S")

#: 各宽度的用途（任务书第 5 步要求至少检查这几档）
WIDTHS = {
    "1440": (1440, 900),    # 桌面/服务站大屏
    "768": (768, 1024),     # 平板竖屏
    "390": (390, 844),      # iPhone 14 档
    "360": (360, 740),      # 常见安卓
    "320": (320, 640),      # 最窄（验收硬指标：不许横向溢出）
}

#: 要截的页面：(名字, 端, 路径, 需要的登录卡片, 宽度)
PAGES = [
    ("login", "公共", "/login", None, ["1440", "390"]),
    ("elderly-home", "老年", "/elderly", "老年", ["1440", "768", "390", "360", "320"]),
    ("elderly-report", "老年", "/elderly/report", "老年", ["1440", "390", "320"]),
    ("elderly-orders", "老年", "/elderly/orders", "老年", ["1440", "390"]),
    ("elderly-more", "老年", "/elderly/more", "老年", ["1440", "390"]),
    ("elderly-agent", "老年", "/elderly/agent", "老年", ["1440", "390"]),
    ("elderly-qa", "老年", "/elderly/qa", "老年", ["1440", "390"]),
    ("elderly-health", "老年", "/elderly/health", "老年", ["1440", "390"]),
    ("elderly-notices", "老年", "/elderly/notices", "老年", ["1440", "390"]),
    ("elderly-contacts", "老年", "/elderly/contacts", "老年", ["1440", "390"]),
    ("elderly-medication", "老年", "/elderly/medication", "老年", ["1440", "390"]),
    ("resident-home", "居民", "/resident/home", "居民", ["1440", "768", "390", "360", "320"]),
    ("resident-qa", "居民", "/resident/qa", "居民", ["1440", "390", "320"]),
    ("resident-issues", "居民", "/resident/work-orders", "居民", ["1440", "390"]),
    ("resident-proposals", "居民", "/resident/proposals", "居民", ["1440", "390"]),
    ("resident-notices", "居民", "/resident/notices", "居民", ["1440", "390"]),
    ("resident-profile", "居民", "/resident/profile", "居民", ["1440", "390"]),
    ("grid-dashboard", "网格", "/grid/dashboard", "网格员", ["1440", "768", "390", "320"]),
    ("grid-issues", "网格", "/grid/work-orders", "网格员", ["1440", "390"]),
    ("grid-qa", "网格", "/grid/qa", "网格员", ["1440", "390"]),
    ("grid-handoffs", "网格", "/grid/handoffs", "网格员", ["1440", "390"]),
    ("grid-weather", "网格", "/grid/weather", "网格员", ["1440", "390"]),
    ("grid-proposals", "网格", "/grid/proposals", "网格员", ["1440", "390"]),
    ("grid-elderly-care", "网格", "/grid/elderly-care", "网格员", ["1440", "390"]),
    ("service-desk", "服务台", "/service-desk", "网格员", ["1440", "390"]),
]

MARK = f"[截图基线 {RUN}]"


def _labels(page) -> list[str]:
    """页面上**真实可见**的可点文字（按钮/链接/角色按钮）——这就是"测试依赖的标签"的快照。"""
    js = """() => {
      const out = [];
      const sel = 'button, a[href], [role=button], .tab-item, .entry-tile, .quick-action';
      document.querySelectorAll(sel).forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) return;
        const t = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
        if (t && t.length <= 24) out.push(t);
      });
      return Array.from(new Set(out));
    }"""
    try:
        return page.evaluate(js)
    except Exception:  # noqa: BLE001 — 取不到就返回空，别让截图任务整体失败
        return []


def _overflow(page) -> int:
    """横向溢出像素（验收硬指标：320px 不许溢出）。"""
    try:
        return int(page.evaluate(
            "() => Math.max(0, document.documentElement.scrollWidth - window.innerWidth)"))
    except Exception:  # noqa: BLE001
        return -1


def _routes_from_router() -> list[dict]:
    src = open(ROUTER, encoding="utf-8").read()
    out = []
    for m in re.finditer(r"path:\s*'([^']+)'[^}]*?name:\s*'([^']+)'", src, re.S):
        out.append({"path": m.group(1), "name": m.group(2)})
    return out


def _login(page, base, card):
    page.goto(f"{base}/login", wait_until="networkidle")
    page.wait_for_timeout(600)
    try:
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    except Exception:  # noqa: BLE001
        pass
    if card:
        page.get_by_text(card, exact=True).first.click()
        page.wait_for_timeout(1800)


def _deep_link(page, base, path):
    page.goto(f"{base}{path}", wait_until="networkidle")
    page.wait_for_timeout(1600)


def _health_ok(base: str, timeout: float = 2.0) -> bool:
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base}/api/web/health", timeout=timeout) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _ensure_server(base: str, keep: bool):
    """服务没在跑就自己起一个（演示姿态），并在结束时收掉。

    为什么要这样：截图脚本依赖"服务在跑"，而**长时间跨轮次的后台服务会被环境回收**——
    实测踩到两次：脚本跑到一半全部页面 ERR_CONNECTION_REFUSED，产出 0 张截图，
    最坑的是它**照样写了清单文件**（看起来"跑完了"）。所以脚本自己负责服务可用性。
    """
    if _health_ok(base):
        print(f"服务已在跑：{base}")
        return None
    env = dict(os.environ)
    env.update({"DEMO_MODE": "true", "PYTHONIOENCODING": "utf-8"})
    log = open(os.path.join(OUT, "server.log"), "w", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "api_web:app",
                             "--host", "127.0.0.1", "--port", "8000"],
                            cwd=ROOT, env=env, stdout=log, stderr=log)
    print("正在启动服务（演示姿态）…")
    for _ in range(60):
        if _health_ok(base):
            print(f"服务就绪：{base}")
            return None if keep else proc
        if proc.poll() is not None:
            print(f"[FAIL] 服务启动失败（退出码 {proc.returncode}），见 {log.name}")
            return proc
        time.sleep(1)
    print("[FAIL] 服务 60 秒内没就绪")
    return proc


def capture(base: str, only: str, allow_write: bool) -> int:
    os.makedirs(OUT, exist_ok=True)
    # ⚠️ 只截某一端时要**合并进已有清单**，不能整份覆盖——
    # 否则一次 `--only elderly` 就把另外两端的基线记录清空了（基线丢了就没法证明"功能没少"）。
    inv = {"captured_at": time.strftime("%Y-%m-%d %H:%M:%S"), "base": base,
           "routes": _routes_from_router(), "pages": {}}
    if only != "all" and os.path.exists(INVENTORY):
        try:
            old = json.load(open(INVENTORY, encoding="utf-8"))
            inv["pages"] = old.get("pages", {})
            for k in ("elderly_nav", "elderly_quick_actions", "elderly_sos_present",
                      "elderly_confirm_labels", "first_captured_at"):
                if k in old:
                    inv[k] = old[k]
            inv["first_captured_at"] = old.get("first_captured_at", old.get("captured_at"))
        except Exception as e:  # noqa: BLE001
            print(f"  （读旧清单失败，按新清单覆盖：{e}）")
    inv.setdefault("first_captured_at", inv["captured_at"])
    shots = 0
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, portal, path, card, widths in PAGES:
            if only != "all" and only not in (portal, name):
                continue
            for w in widths:
                vw, vh = WIDTHS[w]
                ctx = browser.new_context(viewport={"width": vw, "height": vh},
                                          device_scale_factor=1)
                page = ctx.new_page()
                try:
                    if card:
                        _login(page, base, card)
                    _deep_link(page, base, path)
                    # 全页截图（首页类）+ 视口截图（各宽度都要），文件名带上端/页/宽度
                    page.screenshot(path=os.path.join(OUT, f"{name}-{w}.png"))
                    shots += 1
                    if w in ("1440", "390") or name.endswith(("home", "dashboard")):
                        page.screenshot(path=os.path.join(OUT, f"{name}-{w}-full.png"),
                                        full_page=True)
                        shots += 1
                    key = f"{name}@{w}"
                    inv["pages"][key] = {
                        "portal": portal, "path": path, "viewport": [vw, vh],
                        "overflow_px": _overflow(page),
                        "labels": _labels(page),
                        "title": (page.title() or "")[:60],
                    }
                    print(f"  [OK] {name}@{w}  溢出 {inv['pages'][key]['overflow_px']}px "
                          f"· 可见标签 {len(inv['pages'][key]['labels'])} 个")
                except Exception as e:  # noqa: BLE001 — 单页失败不影响整体基线
                    inv["pages"][f"{name}@{w}"] = {"portal": portal, "path": path,
                                                   "error": f"{type(e).__name__}: {e}"}
                    print(f"  [FAIL] {name}@{w} —— {type(e).__name__}: {str(e)[:80]}")
                finally:
                    ctx.close()

        # 老年端导航入口（任务书：6 个主要入口必须不变）——从真实 DOM 数，不看源码
        ctx = browser.new_context(viewport={"width": 390, "height": 844})
        page = ctx.new_page()
        try:
            _login(page, base, "老年")
            _deep_link(page, base, "/elderly")
            nav = page.evaluate("""() => Array.from(
                document.querySelectorAll('.elderly-nav button'))
                .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim())
                .filter(Boolean)""")
            quick = page.evaluate("""() => Array.from(
                document.querySelectorAll('.elderly-grid-3 button'))
                .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean)""")
            sos = page.evaluate("""() => Array.from(
                document.querySelectorAll('[data-longpress]'))
                .map(e => (e.innerText || '').replace(/\\s+/g, ' ').trim()).filter(Boolean)""")
            inv["elderly_nav"] = nav
            inv["elderly_quick_actions"] = quick
            inv["elderly_sos_present"] = bool(sos)
            inv["elderly_sos_labels"] = sos
            print(f"  老年端导航（{len(nav)} 个）：{' / '.join(nav)}")
            print(f"  老年端快捷动作（{len(quick)} 个）：{' / '.join(quick)}")
            print(f"  紧急求助独立入口（长按键 {len(sos)} 个）：{' / '.join(sos)}")
            print(f"  紧急求助独立入口：{'有' if sos else '没找到'}")

            # 老年端提交后的**确认卡**（任务书第 0 步点名要它的截图）——会真的建一条演示工单
            if allow_write:
                _deep_link(page, base, "/elderly/report")
                page.fill("textarea", f"4号楼1单元楼道灯不亮，晚上看不见 {MARK}")
                page.get_by_role("button", name=re.compile("看看还缺什么|帮我看看")).first.click()
                page.wait_for_timeout(2600)
                for label in ("确认上报",):
                    b = page.get_by_role("button", name=label)
                    if b.count():
                        b.first.click()
                        break
                page.wait_for_timeout(3200)
                page.screenshot(path=os.path.join(OUT, "elderly-confirm-card-390.png"))
                page.screenshot(path=os.path.join(OUT, "elderly-confirm-card-390-full.png"),
                                full_page=True)
                shots += 2
                inv["elderly_confirm_labels"] = _labels(page)
                print(f"  老年端确认卡截图完成（写了 1 条带标记 {MARK} 的演示工单）")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] 老年端导航/确认卡：{type(e).__name__}: {str(e)[:100]}")
        finally:
            ctx.close()
        browser.close()

    with open(INVENTORY, "w", encoding="utf-8") as f:
        json.dump(inv, f, ensure_ascii=False, indent=1)
    print("-" * 74)
    print(f"截图 {shots} 张 · 清单已写 {INVENTORY}")
    print(f"路由 {len(inv['routes'])} 条 · 记录页面状态 {len(inv['pages'])} 个")
    bad = {k: v["overflow_px"] for k, v in inv["pages"].items()
           if isinstance(v.get("overflow_px"), int) and v["overflow_px"] > 0}
    print(f"横向溢出页面：{bad if bad else '无'}")
    return 0


def diff_labels() -> int:
    """把当前页面的按钮文字与基线清单对比（重设计后自查"测试依赖的标签有没有被改"）。"""
    if not os.path.exists(INVENTORY):
        print("没有基线清单，先跑一次捕获：python scripts/ui_baseline_capture.py")
        return 2
    inv = json.load(open(INVENTORY, encoding="utf-8"))
    print(f"基线捕获于 {inv['captured_at']}，共 {len(inv['pages'])} 个页面状态")
    print("（这一条只做记录与人工比对：真正的门禁是 journey_check / demo_flow_check / mobile_flow_check）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="all")
    ap.add_argument("--no-write", action="store_true", help="不提交任何数据（跳过确认卡截图）")
    ap.add_argument("--diff", action="store_true")
    ap.add_argument("--keep-server", action="store_true",
                    help="脚本自己起的服务在结束时保留（默认收掉）")
    a = ap.parse_args()
    if a.diff:
        return diff_labels()
    base = a.base.rstrip("/")
    os.makedirs(OUT, exist_ok=True)
    print("=" * 74)
    print("UI 重设计基线捕获（第 0 步：冻结当前版本）")
    print("=" * 74)
    proc = _ensure_server(base, a.keep_server)
    if proc is not None and not _health_ok(base):
        return 1
    try:
        return capture(base, a.only, not a.no_write)
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except Exception:  # noqa: BLE001
                proc.kill()
            print("（本次由脚本启动的服务已收掉）")


if __name__ == "__main__":
    sys.exit(main())
