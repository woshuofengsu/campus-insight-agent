# scripts/mobile_audit.py — 移动端适配客观审计（真机 UA + DPR + 触屏事件）
# -*- coding: utf-8 -*-
"""为什么单独做这个：`ui_audit.py` 关注视觉/无障碍，移动端还有几类它查不到的坑——

  1. **输入框字号 <16px** → iOS 聚焦时会自动放大页面（体验灾难，很多人不知道）
  2. **底部固定栏遮挡内容** → 滚到底部时最后一屏的元素被标签栏盖住（用 elementFromPoint 真测）
  3. **横屏提示层** → 老年端横屏时应有「请竖屏使用」遮罩
  4. **触摸热区** → 手指点击目标 ≥44×44
  5. **横向溢出** → 小屏最常见的问题（320/360 宽）

用法：
  python scripts/mobile_audit.py             # 全部页面（需服务在 :8000）
  python scripts/mobile_audit.py --json
退出码：0 = 无违规；1 = 有违规
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

AUDIT_JS = r"""
(cfg) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const out = { url: location.pathname, vw, vh, overflowX: 0, overs: [], targets: [], fonts: [],
                inputs: [], covered: [], rotateMask: null, viewport: '', safeAreaPadding: {} };

  out.viewport = (document.querySelector('meta[name=viewport]') || {}).content || '';
  out.overflowX = Math.max(0, document.documentElement.scrollWidth - vw);

  const vis = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const sel = (el) => {
    let s = el.tagName.toLowerCase();
    const c = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.');
    return c ? s + '.' + c : s;
  };
  const clipped = (el) => {
    for (let n = el.parentElement; n && n !== document.body; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowX)) return true;
    }
    return false;
  };

  // ① 横向溢出（未被祖先裁剪的越界元素）
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el) || clipped(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 1 || r.left < -1) {
      out.overs.push({ sel: sel(el), right: Math.round(r.right), left: Math.round(r.left),
                       text: (el.textContent || '').trim().slice(0, 18) });
      if (out.overs.length >= 8) break;
    }
  }

  // ② 热区 <44×44（可点元素）
  for (const el of document.querySelectorAll('button, a, [role="button"], .entry-tile, .tab-item, .elderly-btn, .svc')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.height < 44 || r.width < 24) {
      out.targets.push({ sel: sel(el), w: Math.round(r.width), h: Math.round(r.height),
                         text: (el.textContent || '').trim().slice(0, 16) });
      if (out.targets.length >= 10) break;
    }
  }

  // ③ 输入框字号 <16px（iOS 聚焦会缩放）
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (!vis(el)) continue;
    const px = parseFloat(getComputedStyle(el).fontSize);
    if (px < 16) {
      out.inputs.push({ sel: sel(el), px: +px.toFixed(1),
                        ph: (el.placeholder || '').slice(0, 16) });
    }
  }

  // ④ 字号下限（常规 <12px；老年端 <20px）
  const minFont = cfg.elderly ? 20 : 12;
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const direct = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (!direct) continue;
    const px = parseFloat(getComputedStyle(el).fontSize);
    if (px < minFont) {
      out.fonts.push({ sel: sel(el), px: +px.toFixed(1), text: (el.textContent || '').trim().slice(0, 16) });
      if (out.fonts.length >= 8) break;
    }
  }

  // ⑤ 滚动到底部后，内容是否被**底部固定栏**遮挡（真测 elementFromPoint）
  //    ⚠ 识别"底栏"必须严格：position:fixed + 贴底 + **高度很小**（底栏不可能占 1/4 屏高）。
  //    第一版判据太松，把全屏 fixed 背景（.mesh-bg）与老年端横屏遮罩当成底栏 → 假阳性。
  const maskEl = document.querySelector('.elderly-rotate-mask');
  const maskShown = !!maskEl && getComputedStyle(maskEl).display !== 'none';
  const bar = maskShown ? null : [...document.querySelectorAll('body *')].find((el) => {
    const cs = getComputedStyle(el);
    if (cs.position !== 'fixed') return false;
    if (parseFloat(cs.bottom || '99') > 1) return false;
    const r = el.getBoundingClientRect();
    if (r.height < 30 || r.height > vh * 0.25) return false;
    if (r.width < vw * 0.6) return false;
    const cls = (el.className || '').toString();
    if (cls.includes('rotate-mask') || cls.includes('mesh')) return false;
    return true;
  });
  if (bar) {
    const br = bar.getBoundingClientRect();
    out.safeAreaPadding = { barHeight: Math.round(br.height), barTop: Math.round(br.top) };
    const cands = [...document.querySelectorAll('button, a, input, [role="button"], .entry-tile, .card b')]
      .filter((el) => vis(el) && !bar.contains(el));
    let checked = 0;
    for (const el of cands) {
      const r = el.getBoundingClientRect();
      if (r.top < vh - br.height - 4 || r.top > vh) continue;   // 只看贴着底栏那一带
      if (checked++ >= 6) break;
      const hit = document.elementFromPoint(Math.round(r.left + r.width / 2), Math.round(r.top + r.height / 2));
      if (hit && (hit === bar || bar.contains(hit))) {
        out.covered.push({ sel: sel(el), top: Math.round(r.top), barTop: Math.round(br.top),
                           text: (el.textContent || '').trim().slice(0, 18) });
      }
    }
  }

  // ⑥ 横屏提示层（老年端）
  const mask = document.querySelector('.elderly-rotate-mask');
  out.rotateMask = mask ? getComputedStyle(mask).display : null;

  // ⑦ 治理大屏的移动端降级层（P1-G3）：手机宽度下必须可见
  const fb = document.querySelector('.screen-mobile-only');
  out.screenFallback = fb ? getComputedStyle(fb).display : null;
  return out;
}
"""

# (名称, 角色, 路径, 视口, 是否老年端阈值)
PAGES = [
    ("login", None, "/login", (390, 844), False),
    ("login-360", None, "/login", (360, 640), False),
    ("resident-home", "resident", "/resident/home", (390, 844), False),
    ("resident-issues", "resident", "/resident/work-orders", (390, 844), False),
    ("resident-new", "resident", "/resident/work-orders/new", (390, 844), False),
    ("resident-proposals", "resident", "/resident/proposals", (390, 844), False),
    ("resident-notices", "resident", "/resident/notices", (390, 844), False),
    ("resident-qa", "resident", "/resident/qa", (390, 844), False),
    ("resident-health", "resident", "/resident/health", (390, 844), False),
    ("resident-profile", "resident", "/resident/profile", (390, 844), False),
    ("grid-workorders", "grid", "/grid/work-orders", (390, 844), False),
    ("grid-dashboard", "grid", "/grid/dashboard", (390, 844), False),
    ("screen-mobile", "grid", "/screen", (390, 844), False),
    ("elderly-home", "elderly", "/elderly/home", (390, 844), True),
    ("elderly-agent", "elderly", "/elderly/agent", (390, 844), True),
    ("elderly-medication", "elderly", "/elderly/medication", (390, 844), True),
    ("elderly-notices", "elderly", "/elderly/notices", (390, 844), True),
    ("elderly-contacts", "elderly", "/elderly/contacts", (390, 844), True),
    ("elderly-orders", "elderly", "/elderly/orders", (390, 844), True),
    ("elderly-qa", "elderly", "/elderly/qa", (390, 844), True),
    ("elderly-landscape", "elderly", "/elderly/home", (844, 390), True),
]

ROLE_BTN = {"resident": "居民", "elderly": "老年", "grid": "网格员"}


def audit(browser, name, role, path, vp, elderly):
    ctx = browser.new_context(viewport={"width": vp[0], "height": vp[1]}, user_agent=IPHONE_UA,
                              device_scale_factor=3, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e, box=errs: box.append(str(e)[:100]))
    page.goto(f"{BASE}/login", wait_until="networkidle", timeout=30000)
    if role:
        page.get_by_text(ROLE_BTN[role], exact=True).first.click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        page.wait_for_timeout(500)
    if path != "/login":
        page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2200)
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(900)
    res = page.evaluate(AUDIT_JS, {"elderly": elderly})
    res["jsErrors"] = errs[:2]
    ctx.close()
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=".shots/mobile-audit.json")
    args = ap.parse_args()

    # dist 新鲜度校验（复审 F4，与 ui_audit 同一道闸）：测的必须是当前源码构建的包，
    # 否则"改完 src 忘了 build"会让我们测旧包、得出假结论。
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ui_audit import _dist_stale_check
        stale = _dist_stale_check()
        if stale:
            print(stale)
            return 1
    except ImportError:
        pass

    from playwright.sync_api import sync_playwright

    report, bad = {}, 0
    with sync_playwright() as p:
        b = p.chromium.launch()
        for spec in PAGES:
            name = spec[0]
            try:
                report[name] = audit(b, *spec)
            except Exception as e:  # noqa: BLE001
                report[name] = {"error": f"{type(e).__name__}: {e}"}
        b.close()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print("=== 移动端适配审计（iPhone UA / DPR3 / 触屏）===\n")
    for name, r in report.items():
        if "error" in r:
            print(f"❌ {name}: {r['error']}")
            bad += 1
            continue
        issues = []
        if r["overflowX"] > 0 or r["overs"]:
            issues.append(f"横向溢出 {r['overflowX']}px/{len(r['overs'])} 元素")
        if r["targets"]:
            issues.append(f"热区<44px {len(r['targets'])}")
        if r["inputs"]:
            issues.append(f"输入框<16px {len(r['inputs'])}")
        if r["fonts"]:
            issues.append(f"字号不足 {len(r['fonts'])}")
        if r["covered"]:
            issues.append(f"被底栏遮挡 {len(r['covered'])}")
        if r["jsErrors"]:
            issues.append(f"JS 报错 {len(r['jsErrors'])}")
        if r["url"].startswith("/elderly") and r["rotateMask"] is not None and name != "elderly-landscape":
            # 竖屏下遮罩必须隐藏
            if r["rotateMask"] == "flex":
                issues.append("竖屏却显示了横屏遮罩")
        if name == "screen-mobile" and r.get("screenFallback") != "flex":
            issues.append(f"大屏手机降级层未显示（display={r.get('screenFallback')}）")
        mark = "✅" if not issues else "⚠️"
        extra = ""
        if "barHeight" in r.get("safeAreaPadding", {}):
            extra = f" [底栏 {r['safeAreaPadding']['barHeight']}px]"
        print(f"{mark} {name:22s} {r['url']:26s} {r['vw']}x{r['vh']}{extra}"
              + ("  → " + "；".join(issues) if issues else ""))
        for key, label in (("overs", "溢出"), ("targets", "热区"), ("inputs", "输入框"),
                           ("fonts", "字号"), ("covered", "遮挡")):
            for it in r[key][:3]:
                print(f"      {label}: {it}")
        if issues:
            bad += 1

    # 横屏专项
    ls = report.get("elderly-landscape", {})
    if ls.get("rotateMask"):
        ok = ls["rotateMask"] == "flex"
        print(f"\n{'✅' if ok else '⚠️'} 老年端横屏提示层：display={ls['rotateMask']}"
              f"（横屏应显示 flex）")
        if not ok:
            bad += 1

    print(f"\n结果：{'全部通过' if not bad else f'{bad} 个页面待改进'}")
    print(f"明细：{args.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
