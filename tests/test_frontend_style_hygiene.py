# -*- coding: utf-8 -*-
"""前端样式卫生门禁（外部评审 P3：暗色补丁靠精确字符串匹配，是脆弱技术债）。

背景：`style.css` 用 `body.dark [style*="background:#fef2f2"]` 这类选择器去补内联浅色块。
这类选择器要求**写法完全一致**（小写、无空格、hex 而非 rgb()）——以后谁写个
`background: #fff`（带空格）或 `rgb(255,255,255)`，暗色模式就会静默漏掉一块刺眼白。

本文件把两条要求变成可执行门禁：
  1. Ratchet（只减不增）：内联浅色背景总数不得超过基线。新页面一律用令牌/class。
  2. 写法规范：仍在使用内联浅色背景的地方，必须写成 `background:#rrggbb`（小写无空格），
     否则暗色补丁匹配不到 → 直接判失败（附文件:行号）。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

WEB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "src")

# 内联 background 的候选（hex / 3 位 hex / rgb()），随后用亮度判断是否算「浅色」
CAND = re.compile(r"background:\s*(#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\))")
# 目前 style.css 暗色补丁能匹配的唯一规范写法（小写、无空格、6 位 hex）
CANON = re.compile(r"background:#[0-9a-f]{6}\b")

# 基线：本轮把老年端聊天气泡/布局写死白底收口后的实测值（21 处）。数字只能变小。
BASELINE = 21


def _luminance(rgb: tuple[int, int, int]) -> float:
    def f(v: int) -> float:
        s = v / 255
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _parse_color(raw: str) -> tuple[tuple[int, int, int], float] | None:
    """解析 #rgb / #rrggbb / rgb()/rgba() → ((r,g,b), alpha)。

    返回 None 的情况：全透明、无法解析、或**半透明蒙层**（alpha < 0.6）——
    后者是品牌渐变上的玻璃质感（如 rgba(255,255,255,0.10)），亮/暗两种模式下都成立，
    不需要暗色补丁，不能算「内联浅色块」。
    """
    raw = raw.strip()
    alpha = 1.0
    if raw.startswith("#"):
        h = raw[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        if len(h) < 6:
            return None
        rgb = (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    else:
        m = re.match(r"rgba?\(([^)]*)\)", raw)
        if not m:
            return None
        parts = [p.strip() for p in re.split(r"[,\s/]+", m.group(1)) if p.strip()]
        if len(parts) < 3:
            return None
        if len(parts) >= 4:
            try:
                alpha = float(parts[3])
            except ValueError:
                alpha = 1.0
        try:
            rgb = (int(float(parts[0])), int(float(parts[1])), int(float(parts[2])))
        except ValueError:
            return None
    if alpha < 0.6:
        return None
    return rgb, alpha


def _is_light_block(rgb: tuple[int, int, int]) -> bool:
    """「浅色块」判据：亮度 > 0.5 且**接近中性/淡彩**（饱和度 < 0.35）。

    只按亮度会把 #4ade80 这类亮饱和色也算进来（大屏上的状态色，两侧模式都成立，不需补丁）。
    """
    mx, mn = max(rgb), min(rgb)
    sat = 0 if mx == 0 else (mx - mn) / mx
    return _luminance(rgb) > 0.5 and sat < 0.35


def scan_inline_light_bg() -> tuple[list[tuple[str, int, str]], list[tuple[str, int, str]]]:
    """返回 (全部内联浅色背景, 其中写法不规范者)。"""
    hits: list[tuple[str, int, str]] = []
    bad: list[tuple[str, int, str]] = []
    for dirpath, _dirs, files in os.walk(WEB):
        for fn in files:
            if not fn.endswith(".vue"):
                continue
            p = os.path.join(dirpath, fn)
            text = open(p, encoding="utf-8").read()
            rel = os.path.relpath(p, os.path.dirname(WEB)).replace("\\", "/")
            for m in CAND.finditer(text):
                parsed = _parse_color(m.group(1))
                if parsed is None:
                    continue
                rgb, _alpha = parsed
                if not _is_light_block(rgb):
                    continue
                line = text[:m.start()].count("\n") + 1
                hits.append((rel, line, m.group(0).strip()))
                if not CANON.match(text, m.start()):
                    bad.append((rel, line, m.group(0).strip()))
    return hits, bad


def test_inline_light_bg_is_ratcheted():
    """内联浅色背景只能变少（评审 P3：暗色补丁块只减不增）。"""
    hits, _bad = scan_inline_light_bg()
    per_file: dict[str, int] = {}
    for rel, _line, _raw in hits:
        per_file[rel] = per_file.get(rel, 0) + 1
    assert len(hits) <= BASELINE, (
        f"内联浅色背景新增了：{len(hits)} > 基线 {BASELINE}。"
        f"新页面请用令牌/class（如 var(--card-bg)、.panel-sky），不要再加 "
        f"body.dark [style*=...] 补丁。当前分布：{per_file}")


def test_inline_light_bg_uses_canonical_form():
    """仍在用的内联浅色背景必须能被暗色补丁匹配到（小写 #rrggbb、无空格）。"""
    _hits, bad = scan_inline_light_bg()
    assert not bad, (
        "以下内联浅色背景写法暗色模式会漏（style.css 只匹配 background:#rrggbb）："
        + "；".join(f"{rel}:{line} → {raw}" for rel, line, raw in bad))


def test_every_inline_light_bg_has_dark_rule():
    """每个在用内联浅色块都必须有对应暗色规则（否则暗色下就是一块刺眼亮块）。

    为什么必须按 rgb() 校验：Vue 渲染时会把 style 经 CSSOM 规范化，DOM 上是
    `background: rgb(254, 242, 242);`——原先 style.css 用 hex 形式
    `[style*="background:#fef2f2"]`，**从来没命中过任何元素**（整套补丁是死代码）。
    本条把它们钉在一起：新增内联浅色块而忘了补暗色规则 → 直接失败。
    """
    css = open(os.path.join(WEB, "style.css"), encoding="utf-8").read()
    dark_part = css.split("body.dark [style*=", 1)[1] if "body.dark [style*=" in css else ""
    hits, _bad = scan_inline_light_bg()
    missing = []
    checked = set()
    for rel, line, raw in hits:
        parsed = _parse_color(raw.split(":", 1)[1])
        if parsed is None:
            continue
        rgb, _a = parsed
        if rgb in checked:
            continue
        checked.add(rgb)
        needle = f'rgb({rgb[0]}, {rgb[1]}, {rgb[2]})'
        if needle not in dark_part:
            missing.append(f"{needle}（{rel}:{line}）")
    assert not missing, (
        "以下内联浅色块没有暗色规则，暗色模式会露出刺眼亮块：" + "；".join(missing)
        + "。两种修法：① 跑 `python scripts/gen_dark_patch.py` 生成规则并粘进 style.css 的 "
          "'body.dark [style*=\"rgb(...)\"]' 区；② 更推荐——把该元素改成令牌/class（如 .panel-*）")


def test_scan_counts_known_case():
    """自检：扫描器对已知样例给出正确判定（防止门禁本身失效而静默通过）。"""
    assert _luminance((254, 242, 242)) > 0.5, "浅色应判为浅色"
    assert not _is_light_block((255, 140, 66)), "饱和橙（登录页光斑）不应算浅色块"
    assert not _is_light_block((74, 222, 128)), "亮饱和绿（大屏状态色）不应算浅色块"
    assert _is_light_block((254, 242, 242)), "#fef2f2 是典型浅色块"
    assert _parse_color("rgba(0, 0, 0, 0)") is None, "全透明不算背景块"
    assert _parse_color("rgba(255, 255, 255, 0.1)") is None, "半透明玻璃蒙层不算浅色块"
    assert _parse_color("#fff") == ((255, 255, 255), 1.0)
    assert _parse_color("#fef2f2") is not None
    hits, _bad = scan_inline_light_bg()
    assert hits, "扫描器应能在仓库里找到内联浅色背景（否则说明扫描失效）"
