# scripts/gen_dark_patch.py — 生成暗色补丁块（按 DOM 规范化后的 rgb() 形式匹配）
# -*- coding: utf-8 -*-
"""输出：web/src 下所有「内联浅色背景」的去重颜色 + 建议的暗色替换值。

用法：`python scripts/gen_dark_patch.py`（新增了内联浅色块、且测试提示缺暗色规则时跑一次）

关键发现：Vue 会把 `style="background:#fef2f2"` 规范化成 DOM 上的
`background: rgb(254, 242, 242);` —— 因此 style.css 里 `[style*="background:#fef2f2"]`
这类 hex 属性选择器**永远不会命中**（整套补丁曾是死代码）。这里按规范化形式生成。

配套门禁：tests/test_frontend_style_hygiene.py::test_every_inline_light_bg_has_dark_rule
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests.test_frontend_style_hygiene import scan_inline_light_bg, _parse_color  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 颜色 → 暗色替换（同一色系保持语义：红→深红、绿→深绿、黄→深黄、蓝→深蓝，中性→卡片色）
DARK = {
    (254, 242, 242): "#3D1F1F",   # 浅红
    (240, 253, 244): "#12241B",   # 浅绿
    (236, 253, 245): "#12241B",   # 浅绿(偏青)
    (254, 252, 232): "#2A2410",   # 浅黄
    (255, 251, 235): "#2A2410",   # 浅黄(暖)
    (255, 247, 237): "#2A2410",   # 浅橙
    (255, 244, 232): "#2A2410",   # 浅橙
    (240, 249, 255): "#10202E",   # 浅蓝
    (238, 242, 255): "#1B1E3A",   # 浅靛
    (240, 250, 240): "#12241B",   # 浅绿(中性)
    (248, 250, 252): "#1E293B",   # 近白灰 → 卡片色
    (245, 245, 245): "#1E293B",   # 灰 → 卡片色
    (255, 255, 255): "#1E293B",   # 纯白 → 卡片色
}

rows = scan_inline_light_bg()[0]
seen = {}
for rel, line, raw in rows:
    rgb = _parse_color(raw.split(":", 1)[1])
    if rgb:
        seen.setdefault(rgb[0], []).append(f"{rel}:{line}")

print(f"// 去重后 {len(seen)} 种内联浅色背景：")
missing = []
for rgb, where in sorted(seen.items(), key=lambda kv: -len(kv[1])):
    dark = DARK.get(rgb)
    flag = "" if dark else "   ← 缺暗色映射！"
    if not dark:
        missing.append(rgb)
    print(f"  rgb({rgb[0]}, {rgb[1]}, {rgb[2]})  ×{len(where):2d}  → {dark or '?':8s}{flag}   {where[0]}")

if missing:
    sys.exit(f"有 {len(missing)} 种颜色没有暗色映射，请先补 DARK 表：{missing}")

print("\n---- 可直接粘进 style.css 的补丁块 ----")
for rgb, _where in sorted(seen.items()):
    r, g, b = rgb
    print(f'body.dark [style*="rgb({r}, {g}, {b})"] {{ background: {DARK[rgb]} !important; }}')
