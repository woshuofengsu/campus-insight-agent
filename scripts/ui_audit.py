# scripts/ui_audit.py — 用真实浏览器做「客观视觉审计」（对比度 / 溢出 / 热区 / 字号 / 暗色 / 动效）
# -*- coding: utf-8 -*-
"""替代「肉眼看图」的可复算检查：把视觉问题变成可断言的数字。

为什么需要它：写 CSS 的人（包括 AI）常常看不到渲染结果，最常翻车的是
「对比度不够」「320px 溢出」「按钮热区 < 44px」「暗色模式下白块刺眼」「动效没生效」。
这些都能量化，所以不靠感觉，靠数字。

检查项（每页每视口）：
  1. 横向溢出：documentElement.scrollWidth 超出视口像素 + 未被祖先裁剪的越界元素清单
  2. 文字对比度：WCAG AA（普通 4.5 / 大字 3.0）；渐变与透明文字自动跳过，避免误报
  3. 触屏热区：手机视口下可点元素 < 44×44 的清单
  4. 字号下限：常规 < 12px；适老模式（--elderly）< 20px
  5. 断图：img.naturalWidth === 0
  6. 暗色亮度：关键面板在 body.dark 下的背景亮度必须低于阈值（不是刺眼白块）
  7. 动效真实生效：关键类的 animationName / ::after 伪元素不为 none
  8. reduced-motion：模拟 prefers-reduced-motion: reduce 后循环动效应被关闭

用法：
  python scripts/ui_audit.py                # 全站页面（需服务已在 :8000 运行 + 前端已 build）
  python scripts/ui_audit.py --only grid    # 只审名字含该子串的页面（调试用）
  python scripts/ui_audit.py --json         # 机器可读
退出码：0 = 无 HIGH 问题；1 = 有 HIGH（可当门禁）
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

AUDIT_JS = r"""
(cfg) => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const res = { url: location.pathname, vw, overflowX: 0, overs: [], contrast: [], targets: [],
                fonts: [], broken: [], panels: [], anim: {}, notes: [] };

  const de = document.documentElement;
  res.overflowX = Math.max(0, de.scrollWidth - vw);

  const vis = (el) => {
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  };
  const sel = (el) => {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    const c = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 3).join('.');
    if (c) s += '.' + c;
    return s;
  };
  // 是否被某个祖先裁剪（忽略 html/body —— 那正是「被掩盖的溢出」）
  const clipped = (el) => {
    for (let n = el.parentElement; n && n !== document.body && n !== de; n = n.parentElement) {
      const cs = getComputedStyle(n);
      if (['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowX) ||
          ['hidden', 'clip', 'auto', 'scroll'].includes(cs.overflowY)) return true;
    }
    return false;
  };

  // ---- 1. 未被裁剪的横向越界元素 ----
  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right > vw + 2 || r.left < -2) {
      if (clipped(el)) continue;
      res.overs.push({ sel: sel(el), left: Math.round(r.left), right: Math.round(r.right),
                       w: Math.round(r.width), text: (el.textContent || '').trim().slice(0, 24) });
      if (res.overs.length >= 12) break;
    }
  }

  // ---- 2/4. 对比度 + 字号 ----
  const parseRGB = (s) => {
    const m = (s || '').match(/rgba?\(([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\)/);
    return m ? [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : +m[4]] : null;
  };
  const effBg = (el) => {                       // 自上而下合成父链背景；遇到渐变返回 null（跳过）
    const chain = [];
    for (let n = el; n; n = n.parentElement) chain.unshift(n);
    let [r, g, b] = [255, 255, 255];
    for (const n of chain) {
      const cs = getComputedStyle(n);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') return null;
      const c = parseRGB(cs.backgroundColor);
      if (!c || c[3] === 0) continue;
      const a = c[3];
      r = c[0] * a + r * (1 - a); g = c[1] * a + g * (1 - a); b = c[2] * a + b * (1 - a);
    }
    return [r, g, b];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05); };

  for (const el of document.querySelectorAll('body *')) {
    if (!vis(el)) continue;
    const direct = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim().length > 0);
    if (!direct) continue;
    const cs = getComputedStyle(el);
    const fs = parseFloat(cs.fontSize);
    const fw = parseInt(cs.fontWeight, 10) || 400;
    const txt = (el.textContent || '').trim().slice(0, 20);

    // 字号
    const minFont = cfg.elderly ? 20 : 12;
    if (fs < minFont && txt) {
      res.fonts.push({ sel: sel(el), px: +fs.toFixed(1), text: txt, need: minFont });
    }

    // 对比度
    const fg = parseRGB(cs.color);
    if (!fg || fg[3] === 0) continue;            // 渐变文字（color:transparent）跳过
    const bg = effBg(el);
    if (!bg) continue;
    let f = [fg[0], fg[1], fg[2]];
    if (fg[3] < 1) f = f.map((v, i) => v * fg[3] + bg[i] * (1 - fg[3]));
    const cr = ratio(f, bg);
    const large = fs >= 24 || (fs >= 18.66 && fw >= 700);
    const need = large ? 3.0 : 4.5;
    if (cr < need) {
      res.contrast.push({ sel: sel(el), ratio: +cr.toFixed(2), need, px: +fs.toFixed(1),
                          text: txt, color: cs.color });
    }
  }
  res.contrast.sort((a, b) => a.ratio - b.ratio);
  res.contrast = res.contrast.slice(0, 15);

  // ---- 3. 触屏热区（仅手机视口） ----
  if (cfg.touch) {
    for (const el of document.querySelectorAll('button, a, [role="button"], .entry-tile, .tab-item, .elderly-btn')) {
      if (!vis(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.height < 44 || r.width < 24) {
        res.targets.push({ sel: sel(el), w: Math.round(r.width), h: Math.round(r.height),
                           text: (el.textContent || '').trim().slice(0, 18) });
      }
    }
    res.targets = res.targets.slice(0, 15);
  }

  // ---- 5. 断图 ----
  for (const im of document.querySelectorAll('img')) {
    if (im.complete && im.naturalWidth === 0) res.broken.push(im.currentSrc || im.src);
  }

  // ---- 6. 暗色亮度 ----
  if (cfg.dark) {
    for (const s of ['--card-bg', '--bg']) {
      const v = getComputedStyle(de).getPropertyValue(s).trim();
      res.panels.push({ name: s, value: v });
    }
    for (const cls of ['.card', '.panel-warm', '.panel-sky', '.panel-lemon', '.panel-mint',
                       '.glass', '.topbar', '.tabbar', '.page']) {
      const el = document.querySelector(cls);
      if (!el) continue;
      const bg = parseRGB(getComputedStyle(el).backgroundColor);
      const l = bg && bg[3] > 0.05 ? +lum([bg[0], bg[1], bg[2]]).toFixed(3) : null;
      res.panels.push({ name: cls, value: getComputedStyle(el).backgroundColor, lum: l,
                        bgImage: getComputedStyle(el).backgroundImage.slice(0, 60) });
    }
  }

  // ---- 7. 动效确实生效 ----
  for (const cls of ['.btn-shimmer', '.breathe', '.title-sheen', '.mesh-particles i', '.sos-breathe', '.fade-up']) {
    const el = document.querySelector(cls);
    if (!el) { res.anim[cls] = 'absent'; continue; }
    const cs = getComputedStyle(el);
    const after = getComputedStyle(el, '::after');
    res.anim[cls] = {
      name: cs.animationName, dur: cs.animationDuration,
      afterName: after.animationName, afterDur: after.animationDuration,
      bgImage: cs.backgroundImage !== 'none' ? 'gradient' : 'none',
    };
  }
  // ---- 9. 渲染后残缺文本扫描（数据层绑定错误：字段对不上会渲染出空值拼接） ----
  // 结构层检查（对比度/溢出）查不出「后端少返回一个字段」这类 bug，只能扫渲染后的文本。
  // 例：老年端天气 `{{ temp_low }}°~{{ temp_high }}°` 在后端缺 temp_high 时渲染成 "17°~°"。
  const RESIDUE = [
    { name: 'undefined', re: /undefined/ },
    { name: 'NaN', re: /\bNaN\b/ },
    { name: '对象未展开', re: /\[object Object\]/ },
    { name: '模板未渲染', re: /\{\{|\}\}/ },
    { name: '温度缺失占位', re: /°\s*~\s*°/ },
    { name: 'Infinity', re: /Infinity/ },
  ];
  const SOFT = [
    { name: '空括号', re: /（\s*）|\(\s*\)/ },
    // 注意：**不把中点（·/・）算作尾部分隔符** —— 它是本项目的装饰性分隔符，
    // 「基层治理 ·」这类被元素文本边界截断的正常文案会被误报（复审 nit）。
    { name: '尾部分隔符', re: /[、，,]\s*$/ },
  ];
  res.residue = [];
  res.residueSoft = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    const t = (node.textContent || '').trim();
    if (!t || t.length > 200) continue;
    const host = node.parentElement;
    if (!host) continue;
    const cs = getComputedStyle(host);
    if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) continue;
    for (const p of RESIDUE) {
      if (p.re.test(t)) res.residue.push({ kind: p.name, text: t.slice(0, 60), sel: sel(host) });
    }
    for (const p of SOFT) {
      if (p.re.test(t)) res.residueSoft.push({ kind: p.name, text: t.slice(0, 60), sel: sel(host) });
    }
    if (res.residue.length > 12) break;
  }
  return res;
}
"""

REDUCED_JS = r"""
() => {
  const out = {};
  for (const cls of ['.breathe', '.mesh-particles i', '.sos-breathe', '.btn-shimmer']) {
    const el = document.querySelector(cls);
    if (!el) { out[cls] = 'absent'; continue; }
    const cs = getComputedStyle(el);
    out[cls] = { name: cs.animationName, dur: cs.animationDuration };
  }
  return out;
}
"""

# 需要审计的页面：(名称, 角色, 路由, 视口, 适老阈值, 手机热区, 暗色)
# 覆盖策略（第九轮扩面）：**router 里有几页就审几页**——列表页、表单页、详情页、
# 消息中心、天气、隐私政策、/stability 全都要过一遍；暗色再抽各端代表页做回归。
# 详情页的 id 用 `{issue}` / `{proposal}` 占位，运行时从接口取真实数据（见 _resolve_ids）。
PAGES = [
    ("login-desktop", None, "/login", (1440, 900), False, False, False),
    # 1366×768：答辩投影仪/老笔记本的常见分辨率（外部评审建）
    ("login-1366", None, "/login", (1366, 768), False, False, False),
    ("login-mobile", None, "/login", (390, 844), False, True, False),
    ("login-320", None, "/login", (320, 720), False, True, False),
    ("login-dark", None, "/login", (1440, 900), False, False, True),
    # 大屏的指标端点 grid 锁定 → 审计也要以 grid 身份进入（这才是答辩真实路径）
    ("screen", "grid", "/screen", (1920, 1080), False, False, False),
    ("screen-1366", "grid", "/screen", (1366, 768), False, False, False),
    ("stability", "grid", "/stability", (1440, 900), False, False, False),
    ("grid-dashboard", "grid", "/grid/dashboard", (1440, 900), False, False, False),
    ("grid-dashboard-1366", "grid", "/grid/dashboard", (1366, 768), False, False, False),
    ("grid-workorders", "grid", "/grid/work-orders", (1440, 900), False, False, False),
    ("grid-proposals", "grid", "/grid/proposals", (1440, 900), False, False, False),
    ("grid-notices", "grid", "/grid/notices", (1440, 900), False, False, False),
    ("grid-qa", "grid", "/grid/qa", (1440, 900), False, False, False),
    ("grid-weather", "grid", "/grid/weather", (1440, 900), False, False, False),
    ("grid-health", "grid", "/grid/health", (1440, 900), False, False, False),
    ("grid-messages", "grid", "/grid/messages", (1440, 900), False, False, False),
    ("grid-elderly-care", "grid", "/grid/elderly-care", (1440, 900), False, False, False),
    ("grid-dashboard-dark", "grid", "/grid/dashboard", (1440, 900), False, False, True),
    ("grid-workorders-dark", "grid", "/grid/work-orders", (1440, 900), False, False, True),
    ("grid-elderly-care-dark", "grid", "/grid/elderly-care", (1440, 900), False, False, True),
    ("resident-home", "resident", "/resident/home", (390, 844), False, True, False),
    ("resident-home-320", "resident", "/resident/home", (320, 720), False, True, False),
    ("resident-orders", "resident", "/resident/work-orders", (390, 844), False, True, False),
    ("resident-order-detail", "resident", "/resident/work-orders/{issue}", (390, 844), False, True, False),
    ("resident-order-new", "resident", "/resident/work-orders/new", (390, 844), False, True, False),
    ("resident-proposals", "resident", "/resident/proposals", (390, 844), False, True, False),
    ("resident-proposal-detail", "resident", "/resident/proposals/{proposal}", (390, 844), False, True, False),
    ("resident-proposal-new", "resident", "/resident/proposals/new", (390, 844), False, True, False),
    ("resident-notices", "resident", "/resident/notices", (390, 844), False, True, False),
    ("resident-qa", "resident", "/resident/qa", (390, 844), False, True, False),
    ("resident-health", "resident", "/resident/health", (390, 844), False, True, False),
    ("resident-weather", "resident", "/resident/weather", (390, 844), False, True, False),
    ("resident-profile", "resident", "/resident/profile", (390, 844), False, True, False),
    ("resident-messages", "resident", "/resident/messages", (390, 844), False, True, False),
    ("resident-privacy", "resident", "/resident/privacy", (390, 844), False, True, False),
    ("resident-home-dark", "resident", "/resident/home", (390, 844), False, True, True),
    ("resident-notices-dark", "resident", "/resident/notices", (390, 844), False, True, True),
    ("resident-qa-dark", "resident", "/resident/qa", (390, 844), False, True, True),
    ("resident-weather-dark", "resident", "/resident/weather", (390, 844), False, True, True),
    ("resident-profile-dark", "resident", "/resident/profile", (390, 844), False, True, True),
    ("elderly-home", "elderly", "/elderly/home", (390, 844), True, True, False),
    ("elderly-home-1366", "elderly", "/elderly/home", (1366, 768), True, False, False),
    ("elderly-agent", "elderly", "/elderly/agent", (390, 844), True, True, False),
    ("elderly-report", "elderly", "/elderly/report", (390, 844), True, True, False),
    ("elderly-medication", "elderly", "/elderly/medication", (390, 844), True, True, False),
    ("elderly-notices", "elderly", "/elderly/notices", (390, 844), True, True, False),
    ("elderly-contacts", "elderly", "/elderly/contacts", (390, 844), True, True, False),
    ("elderly-orders", "elderly", "/elderly/orders", (390, 844), True, True, False),
    ("elderly-qa", "elderly", "/elderly/qa", (390, 844), True, True, False),
    ("elderly-health", "elderly", "/elderly/health", (390, 844), True, True, False),
    # 暗色覆盖扩面：内联写死色在暗色下翻车是这批问题的共同根因，多抽几页暗色做回归
    ("elderly-health-dark", "elderly", "/elderly/health", (390, 844), True, True, True),
    ("elderly-notices-dark", "elderly", "/elderly/notices", (390, 844), True, True, True),
    ("elderly-medication-dark", "elderly", "/elderly/medication", (390, 844), True, True, True),
    ("elderly-contacts-dark", "elderly", "/elderly/contacts", (390, 844), True, True, True),
    ("elderly-report-dark", "elderly", "/elderly/report", (390, 844), True, True, True),
]

ROLE_BTN = {"resident": "居民", "elderly": "老年", "grid": "网格员"}


def audit(browser, name, role, path, vp, elderly, touch, dark):
    ctx = browser.new_context(viewport={"width": vp[0], "height": vp[1]},
                              device_scale_factor=1, has_touch=touch)
    if dark:
        ctx.add_init_script("localStorage.setItem('ci_theme','dark')")
    page = ctx.new_page()
    errs = []
    page.on("pageerror", lambda e, box=errs: box.append("pageerror: " + str(e)))
    # 控制台 error 也要收（CSP 违规、Vue 警告等只出现在 console，不抛 pageerror）
    page.on("console", lambda m, box=errs: box.append("console: " + m.text[:150])
            if m.type == "error" else None)
    page.goto(f"{BASE}/login", wait_until="networkidle", timeout=30000)
    if role:
        page.get_by_text(ROLE_BTN[role], exact=True).first.click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        page.wait_for_timeout(500)
    if path != "/login":
        page.goto(f"{BASE}{path}", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2600)  # 等数字滚动/入场动效结束
    r = page.evaluate(AUDIT_JS, {"elderly": elderly, "touch": touch, "dark": dark})

    # reduced-motion 复检
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_timeout(400)
    r["reduced"] = page.evaluate(REDUCED_JS)
    r["jsErrors"] = errs[:3]
    ctx.close()
    return r


def _dist_stale_check() -> str:
    """dist 新鲜度校验（复审 F4）：测的必须是**当前源码**构建出来的包。

    为什么需要：`web/dist` 在 gitignore 里、由 `npm run build` 生成，改完 `web/src` 忘记 build
    时，审计/演示测的是旧包 —— 第九轮复审就真实踩到（dist 落后 42 分钟，旧包里还带着已修掉的
    写死颜色，导致"报了 6 处、其实源码早修了"的错觉）。这里从工具层面直接拦住。

    返回空串 = 新鲜；否则返回一行红字建议（调用方决定是退出还是警告）。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist_index = os.path.join(root, "web", "dist", "index.html")
    src = os.path.join(root, "web", "src")
    if not os.path.exists(dist_index):
        return ("❌ web/dist 不存在 —— 先构建：cd web && npm run build\n"
                "   （审计要跑的是构建产物，不是源码）")
    if not os.path.isdir(src):
        return ""
    dist_m = os.path.getmtime(dist_index)
    newest, newest_f = 0.0, ""
    for dirpath, _dirs, files in os.walk(src):
        for fn in files:
            p = os.path.join(dirpath, fn)
            try:
                m = os.path.getmtime(p)
            except OSError:
                continue
            if m > newest:
                newest, newest_f = m, os.path.relpath(p, root).replace("\\", "/")
    if newest > dist_m:
        lag = int((newest - dist_m) / 60)
        return (f"❌ web/dist 落后于源码（约 {lag} 分钟）：{newest_f}\n"
                "   先构建再审计：cd web && npm run build")
    return ""


def _preflight(base: str) -> str:
    """跑审计前先探活（第八轮终审 N3）。

    为什么必须做：审计要跑全站 54 个页面/视口 × 约 10 分钟，如果服务中途停了，会逐页报
    `ERR_CONNECTION_REFUSED`，看起来像"每个页面都有问题"——把「环境没起」误读成「页面缺陷」。
    这里先打一次健康检查，校验**服务身份**（不只 200），失败就明确说「服务未起」并给出启动命令。
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = f"{base}/api/web/health"
    try:
        with urllib.request.urlopen(url, timeout=8) as r:
            body = _json.loads(r.read().decode("utf-8"))
        svc = ((body or {}).get("data") or {}).get("service")
        if svc != "CommunityInsight Web":
            return (f"❌ {base} 有响应但不是本服务（service={svc!r}）——端口可能被别的程序占用。\n"
                    "   查看占用：netstat -ano | findstr :8000")
        return ""
    except urllib.error.HTTPError as e:
        return f"❌ 健康检查返回 HTTP {e.code}（{url}）"
    except Exception as e:  # noqa: BLE001
        return (f"❌ 服务未启动（{url} 不可达：{type(e).__name__}）。\n"
                "   先启动主服务：python -m uvicorn api_web:app --host 0.0.0.0 --port 8000\n"
                "   （启动约 15 秒，之后再跑本审计）")


def _resolve_ids(base: str) -> dict[str, str]:
    """取详情页要用的真实 id（工单 / 提案）。

    为什么要取真数据：详情页在"查不到记录"时会渲染成空壳，审计量到的是**空页面**，
    等于没审。这里用居民演示身份拿"自己看得到的那条"，保证详情页真有内容可量。
    取不到就返回空 dict，`{issue}` 这类页面会被跳过并明确打印原因（不静默）。
    """
    import json as _json
    import urllib.request

    def _post(path: str, body: dict) -> dict:
        r = urllib.request.Request(base + path, data=_json.dumps(body).encode(), method="POST")
        r.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(r, timeout=20) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    def _get(path: str, token: str):
        r = urllib.request.Request(base + path)
        r.add_header("Authorization", "Bearer " + token)
        with urllib.request.urlopen(r, timeout=20) as resp:
            return _json.loads(resp.read().decode("utf-8"))

    out: dict[str, str] = {}
    try:
        token = (_post("/api/web/auth/demo", {"role": "resident"}).get("data") or {}).get("token")
        if not token:
            return out
        issues = _get("/api/web/issues", token).get("data") or []
        if issues:
            out["issue"] = str(issues[0]["id"])
        props = _get("/api/web/proposals", token).get("data") or []
        mine = [x for x in props if x.get("mine")] or props
        if mine:
            out["proposal"] = str(mine[0]["id"])
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠ 详情页 id 解析失败（{type(e).__name__}），将跳过带占位符的页面")
    return out


def main() -> int:
    global BASE  # 允许 --base 覆盖，便于在别的端口/机器上审计（声明必须在任何使用之前）
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--out", default=".shots/ui-audit.json")
    ap.add_argument("--base", default=BASE, help="服务地址（默认 http://127.0.0.1:8000）")
    ap.add_argument("--only", default="", help="只审名字包含该子串的页面（调试用）")
    args = ap.parse_args()

    BASE = args.base

    stale = _dist_stale_check()
    if stale:
        print(stale)
        return 1

    problem = _preflight(BASE)
    if problem:
        print(problem)
        return 1

    ids = _resolve_ids(BASE)
    if ids:
        print(f"详情页数据：工单 #{ids.get('issue', '-')} · 提案 #{ids.get('proposal', '-')}")

    pages = []
    for spec in PAGES:
        path = spec[2]
        if "{" in path:
            try:
                path = path.format(**ids)
            except KeyError:
                print(f"  ⚠ 跳过 {spec[0]}：缺少详情页 id（{path}）")
                continue
        pages.append((spec[0], spec[1], path) + tuple(spec[3:]))
    if args.only:
        pages = [p for p in pages if args.only in p[0]]

    from playwright.sync_api import sync_playwright

    report = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        for spec in pages:
            name = spec[0]
            try:
                report[name] = audit(b, *spec)
                print(f"[ok] {name}")
            except Exception as e:
                report[name] = {"error": f"{type(e).__name__}: {e}"}
                print(f"[ERR] {name}: {e}")
        b.close()

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0

    high = 0
    print("\n================ 客观视觉审计 ================")
    for name, r in report.items():
        if "error" in r:
            print(f"\n## {name}  ✗ 审计失败：{r['error']}")
            high += 1
            continue
        print(f"\n## {name}  ·  {r['url']}  ·  {r['vw']}px")
        print(f"   横向溢出: {r['overflowX']}px")
        if r["overs"]:
            high += 1
            print(f"   ⚠ 未裁剪的越界元素 {len(r['overs'])}：")
            for o in r["overs"][:6]:
                print(f"      {o['sel']}  left={o['left']} right={o['right']} w={o['w']}  «{o['text']}»")
        if r["contrast"]:
            high += 1
            print(f"   ⚠ 对比度不足 {len(r['contrast'])}：")
            for c in r["contrast"][:6]:
                print(f"      {c['ratio']}:1 (需 {c['need']})  {c['px']}px  {c['sel']}  «{c['text']}»  {c['color']}")
        if r["targets"]:
            high += 1
            print(f"   ⚠ 热区 < 44px {len(r['targets'])}：")
            for t in r["targets"][:6]:
                print(f"      {t['w']}×{t['h']}  {t['sel']}  «{t['text']}»")
        if r["fonts"]:
            high += 1
            print(f"   ⚠ 字号 < 下限 {len(r['fonts'])}：")
            for f in r["fonts"][:6]:
                print(f"      {f['px']}px (需 ≥{f['need']})  {f['sel']}  «{f['text']}»")
        if r["broken"]:
            high += 1
            print(f"   ⚠ 断图: {r['broken'][:3]}")
        if r.get("residue"):
            high += 1
            print(f"   ⚠ 渲染残缺文本 {len(r['residue'])}（数据层字段对不上）:")
            for d in r["residue"][:6]:
                print(f"      [{d['kind']}] «{d['text']}»  {d['sel']}")
        if r.get("residueSoft"):
            print(f"   · 疑似残缺（人工确认）{len(r['residueSoft'])}: "
                  + "；".join(f"[{d['kind']}]«{d['text']}»" for d in r["residueSoft"][:3]))
        if r.get("panels"):
            print("   暗色取样: " + "; ".join(f"{p['name']}={p.get('value')}" + (f" lum={p['lum']}"
                                              if p.get("lum") is not None else "") for p in r["panels"]))
        if r.get("anim"):
            living = {k: v for k, v in r["anim"].items() if v != "absent"}
            absent = [k for k, v in r["anim"].items() if v == "absent"]
            print(f"   动效: {len(living)} 类存在" + (f"；本页无 {absent}" if absent else ""))
        if r.get("reduced"):
            # 注意：reduced-motion 下 duration 会变成 1e-06s（= 0.001ms），要按数值判断，
            # 不能拿字符串跟 "0.001ms" 比（会误报「仍在动」）
            def _stopped(dur: str) -> bool:
                try:
                    return float(str(dur).rstrip("ms").rstrip("s")) < 0.01 or str(dur) in ("0s", "0ms")
                except ValueError:
                    return False
            still = {k: v for k, v in r["reduced"].items()
                     if v != "absent" and not _stopped(v.get("dur", "0s"))}
            if still:
                high += 1
                print(f"   ⚠ reduced-motion 下仍在动: {still}")
            else:
                print("   reduced-motion: 循环动效已关闭 ✓")
        if r.get("jsErrors"):
            # 第九轮自查：控制台报错此前只打印、不计入违规 —— 于是「打开提案详情页就发 400
            # 并弹红色 toast」（复审 F2）在审计里是隐形的。前端门禁既然对外宣称"0 JS 报错"，
            # 就得让它真的能拦住：控制台 error（含 4xx/5xx 资源请求失败）算 HIGH。
            high += 1
            print(f"   ⚠ JS 报错 {len(r['jsErrors'])}：")
            for je in r["jsErrors"]:
                print(f"      {je}")
    print(f"\n结果：{'存在需修复项' if high else '无 HIGH 问题'}（{high} 处）")
    print(f"明细 JSON：{args.out}")
    return 1 if high else 0


if __name__ == "__main__":
    sys.exit(main())
