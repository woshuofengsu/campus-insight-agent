# scripts/mobile_gallery.py — 生成「手机端画廊」网页：真机视口逐页截图 + 设备边框画廊
# -*- coding: utf-8 -*-
"""用途：让**人**直观看到移动端适配效果（我读不了图，但你能）。

产出（默认 `.shots/mobile/`）：
  *.png          以 iPhone 视口（390×844，DPR3，触屏 UA）渲染的逐页截图
  index.html     画廊页：手机边框里逐张展示 + 标注页面路径；顶部给真机访问地址
  galaxy-*.png   另附一档安卓小屏（360×800）用于对比

用法：python scripts/mobile_gallery.py
     python scripts/mobile_gallery.py --base http://10.101.177.33:8000   # 换地址
"""
import argparse
import os
import socket
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = "http://127.0.0.1:8000"
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
ANDROID_UA = ("Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/122.0 Mobile Safari/537.36")
ROLE_BTN = {"resident": "居民", "elderly": "老年", "grid": "网格员"}

# (文件名, 角色, 路径, 说明, 是否安卓小屏再拍一张)
PAGES = [
    ("01-login", None, "/login", "登录页（桌面双栏在手机上是单栏：品牌面板在上）", True),
    ("02-resident-home", "resident", "/resident/home", "居民端首页：渐变横幅 + 天气 + 6 个彩色磁贴", True),
    ("03-resident-issues", "resident", "/resident/work-orders", "居民端报修列表（工单状态标签）", False),
    ("04-resident-notices", "resident", "/resident/notices", "居民端通知（**本次新增演示数据**，此前为空）", False),
    ("05-resident-qa", "resident", "/resident/qa", "居民端政策问答（混合检索命中）", False),
    ("06-resident-profile", "resident", "/resident/profile", "居民端「我的」", False),
    ("07-elderly-home", "elderly", "/elderly/home", "老年端首页：大字 + 暖色面板 + SOS 呼吸（长按 3 秒）", True),
    ("08-elderly-notices", "elderly", "/elderly/notices", "老年端「听通知」（点击语音播报；字号已修到 ≥20px）", False),
    ("09-elderly-medication", "elderly", "/elderly/medication", "老年端用药提醒", False),
    ("10-elderly-agent", "elderly", "/elderly/agent", "老年端语音小助手", False),
    ("11-grid-dashboard", "grid", "/grid/dashboard", "网格员端工作台（手机顶部 ☰ 打开抽屉导航）", True),
    ("12-screen-mobile", "grid", "/screen", "治理大屏的**手机降级提示**（本次新增）", False),
]


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def capture(browser, base, out_dir, role, path, name, viewport, ua, scale=3):
    ctx = browser.new_context(viewport=viewport, user_agent=ua,
                              device_scale_factor=scale, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.goto(f"{base}/login", wait_until="networkidle", timeout=30000)
    if role:
        page.get_by_text(ROLE_BTN[role], exact=True).first.click()
        page.wait_for_url(lambda u: "/login" not in u, timeout=20000)
        page.wait_for_timeout(600)
    if path != "/login":
        page.goto(f"{base}{path}", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2600)
    target = os.path.join(out_dir, f"{name}.png")
    page.screenshot(path=target)
    # 顺带记录页面高度，画廊里能标注「可滚动」
    h = page.evaluate("() => document.documentElement.scrollHeight")
    ctx.close()
    return target, h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--out", default=".shots/mobile")
    args = ap.parse_args()
    base = args.base            # 局部变量传递，避免 global（踩过「声明在使用之后」的坑）
    os.makedirs(args.out, exist_ok=True)

    from playwright.sync_api import sync_playwright

    iphone = {"width": 390, "height": 844}
    galaxy = {"width": 360, "height": 800}
    rows = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, role, path, desc, also_android in PAGES:
            try:
                f, h = capture(b, base, args.out, role, path, name, iphone, IPHONE_UA)
                print(f"  ✅ {name:22s} iPhone 390×844  页高 {h}px")
                extra = ""
                if also_android:
                    f2, h2 = capture(b, base, args.out, role, path, f"{name}-galaxy",
                                     galaxy, ANDROID_UA, scale=2)
                    extra = f"{name}-galaxy.png"
                    print(f"  ✅ {name + '-galaxy':22s} 安卓 360×800   页高 {h2}px")
                rows.append((name, path, desc, h, extra))
            except Exception as e:  # noqa: BLE001
                print(f"  ❌ {name}: {type(e).__name__}: {e}")
        b.close()

    lan = _lan_ip()
    # 有公网隧道地址就优先给公网（手机不限网络、且 https 下语音/添加到主屏幕可用）；
    # 否则退回局域网 IP（需同一 Wi-Fi，且 http 无语音）。地址由 scripts/serve_public.py 维护。
    pub_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            ".shots", "当前公网地址.txt")
    pub = ""
    if os.path.exists(pub_file):
        try:
            pub = open(pub_file, encoding="utf-8").read().strip()
        except Exception:  # noqa: BLE001
            pub = ""
    phone_addr = (pub + "/login") if pub else f"http://{lan}:8000/login"
    addr_hint = ("公网 HTTPS（任意网络，语音/添加到主屏幕可用）" if pub
                 else "局域网（需手机连同一个 Wi-Fi；http 无语音）")
    # ---- 画廊页（本地打开即可看） ----
    cards = []
    for name, path, desc, h, extra in rows:
        shots = [f"{name}.png"] + ([extra] if extra else [])
        imgs = "".join(
            f'<figure class="phone"><img src="{s}" alt="{s}" loading="lazy" />'
            f'<figcaption>{"安卓 360×800" if "galaxy" in s else "iPhone 390×844"}'
            f'{"（整页 " + str(h) + "px，可滚动）" if "galaxy" not in s else ""}</figcaption></figure>'
            for s in shots)
        cards.append(f"""
    <section class="card">
      <div class="meta"><h2>{name}</h2><code>{path}</code></div>
      <p class="desc">{desc}</p>
      <div class="row">{imgs}</div>
    </section>""")

    html = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>社区先知 · 手机端适配画廊</title>
<style>
  :root {{ --primary:#2D5BFF; --text:#16233B; --muted:#5B6B80; --bg:#F6F8FB; --card:#fff; --border:#E7ECF3; }}
  body.dark {{ --text:#E2E8F0; --muted:#94A3B8; --bg:#0F172A; --card:#1E293B; --border:#334155; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:28px; font-family:"PingFang SC","Microsoft YaHei",system-ui,sans-serif;
         background:var(--bg); color:var(--text); }}
  header {{ max-width:1200px; margin:0 auto 26px; }}
  h1 {{ font-size:1.5rem; margin:0 0 8px; }}
  .hint {{ background:var(--card); border:1px solid var(--border); border-radius:14px; padding:14px 16px;
           font-size:.9rem; line-height:1.9; }}
  .hint b {{ color:var(--primary); }}
  .hint code {{ background:rgba(45,91,255,.10); padding:1px 6px; border-radius:6px; }}
  .card {{ max-width:1200px; margin:18px auto; background:var(--card); border:1px solid var(--border);
           border-radius:16px; padding:16px 18px; box-shadow:0 6px 16px rgba(18,35,59,.06); }}
  .meta {{ display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; }}
  .meta h2 {{ font-size:1.05rem; margin:0; }}
  .meta code {{ color:var(--muted); font-size:.82rem; }}
  .desc {{ color:var(--muted); font-size:.85rem; margin:6px 0 14px; }}
  .row {{ display:flex; gap:18px; flex-wrap:wrap; align-items:flex-start; }}
  figure.phone {{ margin:0; }}
  figure.phone img {{ width:290px; border-radius:22px; border:7px solid #111827;
                      box-shadow:0 12px 28px rgba(0,0,0,.28); background:#111827; display:block; }}
  figcaption {{ text-align:center; color:var(--muted); font-size:.75rem; margin-top:6px; }}
  footer {{ max-width:1200px; margin:30px auto 0; color:var(--muted); font-size:.82rem; line-height:1.9; }}
</style></head>
<body>
  <header>
    <h1>📱 社区先知 · 手机端适配画廊</h1>
    <div class="hint">
      <div><b>真机访问（{addr_hint}）：</b>
        <code>{phone_addr}</code> —— 三个演示账号：居民点「居民」、老年点「老年」、网格员点「网格员」（demo_grid / demo123）</div>
      <div><b>语音功能（老年端按住说话/播报）在浏览器里要求 HTTPS</b>：{"当前是 https 公网地址，语音可直接用。" if pub else "局域网 http 下麦克风会被浏览器禁用（页面会给出大字降级引导，可打字）；跑 <code>python scripts/serve_public.py</code> 会得到 https 公网地址，并自动刷新本页地址。"}</div>
      <div><b>本页是怎么生成的：</b>Playwright 以真机 UA（iPhone Safari 17）+ DPR3 + 触屏事件渲染每页后截图，
           与 <code>scripts/mobile_audit.py</code> 同一套环境；如需重跑：<code>python scripts/mobile_gallery.py</code></div>
    </div>
  </header>
  {"".join(cards)}
  <footer>
    提示：老年端刻意「几乎不动」——只保留 SOS 呼吸与淡入，这是适老降噪的设计取舍；
    顶部状态栏/刘海区域已用 <code>env(safe-area-inset-*)</code> 留白。<br />
    底部固定标签栏（居民端）在真实设备上会避开 Home Indicator；手机端还有独立门禁：
    <code>python scripts/mobile_audit.py</code>（21 页 × 7 类检查，当前 0 违规）。
  </footer>
</body></html>
"""
    idx = os.path.join(args.out, "index.html")
    with open(idx, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n画廊已生成：{os.path.abspath(idx)}")
    print(f"真机地址：{phone_addr}（{addr_hint}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
