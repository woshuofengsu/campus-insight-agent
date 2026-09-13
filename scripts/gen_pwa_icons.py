# scripts/gen_pwa_icons.py — 由 favicon.svg 生成 PWA 所需的 PNG 图标（192/512）
# -*- coding: utf-8 -*-
"""为什么不引入新依赖：项目已经依赖 Playwright（自检/审计/录屏都用它），
用它把 SVG 渲染成 PNG 最省事——不需要 Pillow、不需要 ImageMagick。

产物：web/public/icon-192.png、web/public/icon-512.png（512 带纯色底，作 maskable 用）

用法：python scripts/gen_pwa_icons.py
"""
import base64
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "web", "public")
SVG = os.path.join(PUBLIC, "favicon.svg")
BG = "#2D5BFF"          # maskable 图标需要纯色底（否则被裁成圆形时露白）
SIZES = {"icon-192.png": 192, "icon-512.png": 512}


def main() -> int:
    if not os.path.exists(SVG):
        print("找不到 web/public/favicon.svg")
        return 1
    from playwright.sync_api import sync_playwright

    svg = open(SVG, encoding="utf-8").read()
    # 去掉固定宽高，让它随容器缩放
    import re
    svg_scaled = re.sub(r'width="\d+"\s+height="\d+"', 'width="100%" height="100%"', svg, count=1)
    b64 = base64.b64encode(svg_scaled.encode("utf-8")).decode()

    with sync_playwright() as p:
        b = p.chromium.launch()
        for name, size in SIZES.items():
            ctx = b.new_context(viewport={"width": size, "height": size}, device_scale_factor=1)
            page = ctx.new_page()
            inner = int(size * 0.78)          # 四周留白，符合平台图标的安全区
            page.set_content(
                f"""<!doctype html><html><head><meta charset="utf-8"><style>
                html,body{{margin:0;padding:0;width:{size}px;height:{size}px;
                  background:{BG};display:flex;align-items:center;justify-content:center;}}
                .wrap{{width:{inner}px;height:{inner}px;display:block;}}
                </style></head><body><span class="wrap">
                <img src="data:image/svg+xml;base64,{b64}" style="width:100%;height:100%;display:block"/>
                </span></body></html>""",
                wait_until="load",
            )
            page.wait_for_timeout(300)
            out = os.path.join(PUBLIC, name)
            page.screenshot(path=out, omit_background=False)
            print(f"  {name}  {size}x{size}  {os.path.getsize(out) // 1024} KB")
            ctx.close()
        b.close()
    print("OK：图标已生成（manifest.json 引用它们）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
