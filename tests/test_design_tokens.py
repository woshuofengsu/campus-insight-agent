# -*- coding: utf-8 -*-
"""设计令牌同源门禁（v2 方案 §12.3 设计令牌 v3 / §12.7-1「style.css 与 Naive 主题同源映射」）。

**为什么需要这个门禁**：`style.css` 的 CSS 变量与 `App.vue` 的 Naive `themeOverrides`
原来是**两份各自维护的 hex**。同一块品牌蓝在两处各改一半，就会出现
"页面里是新的、组件里是旧的"——正是本项目最忌讳的"做了但不生效"，
而且它在页面上看着只是"有点不协调"，没人会去查，直到评审当场指出。

现在两边共用的颜色集中在 `web/src/config/tokens.js`（键 → [CSS 变量名, 取值]），
本文件解析 `style.css` 的 `:root` / `body.dark` 逐条**核对取值一致**：
任何一边单独改动，这里立刻红。

反向自检（这条门禁是不是摆设）：把 `tokens.js` 里任意一个值改掉再跑本文件，必须失败——
见 `test_gate_actually_detects_drift`（它就是干这个的）。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = os.path.join(ROOT, "web", "src", "style.css")
TOKENS = os.path.join(ROOT, "web", "src", "config", "tokens.js")
APP = os.path.join(ROOT, "web", "src", "App.vue")


def _css_block(css: str, selector: str) -> dict:
    """取某个选择器块里的 `--变量: 值;` 映射（只取第一个块，够用且确定）。"""
    m = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S)
    assert m, f"style.css 里找不到 {selector} 区块"
    return {k: v.strip() for k, v in re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+);", m.group(1))}


def _js_table(name: str) -> dict:
    """从 tokens.js 里读出一张令牌表（键 → [CSS 变量名, 取值]）。"""
    src = io.open(TOKENS, encoding="utf-8").read()
    m = re.search(rf"export const {name} = \{{(.*?)\n\}}", src, re.S)
    assert m, f"tokens.js 里找不到 {name}"
    out = {}
    for key, cssvar, value in re.findall(r"(\w+):\s*\['(--[a-z0-9-]+)',\s*'([^']+)'\]", m.group(1)):
        out[key] = (cssvar, value)
    assert out, f"{name} 解析为空（格式变了？）"
    return out


def test_tokens_file_exists_and_is_the_only_source():
    assert os.path.isfile(TOKENS), "缺少 web/src/config/tokens.js（设计令牌的单一来源）"
    app = io.open(APP, encoding="utf-8").read()
    assert "from './config/tokens'" in app, "App.vue 没有从 tokens.js 取令牌"


def test_light_tokens_match_stylesheet():
    css = _css_block(io.open(CSS, encoding="utf-8").read(), ":root")
    table = _js_table("LIGHT_CSS_TOKENS")
    bad = []
    for key, (cssvar, value) in table.items():
        got = (css.get(cssvar) or "").strip()
        if got.upper() != value.upper():
            bad.append(f"{key}: tokens.js={value} vs style.css {cssvar}={got or '（没有这个变量）'}")
    assert not bad, "亮色令牌两边不一致（改了一边没改另一边）：\n  " + "\n  ".join(bad)


def test_dark_tokens_match_stylesheet():
    css = _css_block(io.open(CSS, encoding="utf-8").read(), "body.dark")
    table = _js_table("DARK_CSS_TOKENS")
    bad = []
    for key, (cssvar, value) in table.items():
        got = (css.get(cssvar) or "").strip()
        if got.upper() != value.upper():
            bad.append(f"{key}: tokens.js={value} vs style.css body.dark {cssvar}={got or '（没有这个变量）'}")
    assert not bad, "暗色令牌两边不一致：\n  " + "\n  ".join(bad)


def test_app_theme_uses_tokens_not_raw_hex():
    """共用色必须走令牌——`themeOverrides` 里再出现裸 hex 就是又要开始各写一份了。

    允许保留的裸 hex：纯主题色（hover/pressed/占位符等，`THEME_ONLY` 里有名字的除外，
    它们本就不该被"令牌化"成 CSS 变量）+ 两处历史注释里带的无障碍说明色。
    """
    app = io.open(APP, encoding="utf-8").read()
    # 去掉注释后再找裸 hex（注释里出现的色值是说明文字，不算代码里的硬编码色）
    code = re.sub(r"//.*", "", app)
    raw = set(h.upper() for h in re.findall(r"#[0-9A-Fa-f]{6}", code))
    allowed = {  # 仍允许内联的少量值：中性文本色 + 空态图标 + 半透明底
        "#CBD5E1", "#334155", "#64748B", "#66738A", "#475569", "#0A6B39", "#1E40AF", "#92400E",
    }
    leftover = sorted(raw - allowed)
    assert not leftover, (
        "App.vue 的主题里又出现了裸 hex（应放进 web/src/config/tokens.js）：" + "、".join(leftover))


def test_gate_actually_detects_drift():
    """**门禁自检**：把 tokens.js 里一个值改掉，核对逻辑必须报错（证明它不是摆设）。"""
    src = io.open(TOKENS, encoding="utf-8").read()
    broken = src.replace("primary: ['--primary', '#2D5BFF']", "primary: ['--primary', '#123456']")
    assert broken != src, "自检失效：tokens.js 里的主色写法变了，请同步更新本用例"
    css = _css_block(io.open(CSS, encoding="utf-8").read(), ":root")
    # 复现核对逻辑（不落盘改文件）
    key, (cssvar, value) = "primary", ("--primary", "#123456")
    assert (css.get(cssvar) or "").upper() != value.upper(), "自检失效：漂移竟然没被比出来"


# ---------------------------------------------------------------- 语义文字色
# 这些令牌是给**图形/淡底**用的亮色，直接当文字色用在白底上只有 2.0–2.31:1
# （ui_audit 在 /resident/proposals/:id 的「匿名居民#xxxx」上实测抓到 2.31:1）。
# 文字必须换成成对的 `-ink` 令牌（亮色深、暗色亮）。
FIG = re.compile(
    r"color:\s*var\(--(accent|primary|success|danger|warning|info"
    r"|st-pending|st-doing|st-feedback|st-done|st-danger|st-info|st-success)\)")
INK = re.compile(r"--[a-z-]*ink[a-z-]*$|^--muted$")


def _scan_figure_text_colors() -> list[str]:
    """扫 web/src 下的 `.vue` 与 `style.css`，找出「拿图形色当文字色」的地方。"""
    out = []
    targets = [CSS]
    for dirpath, _dirs, files in os.walk(os.path.dirname(CSS)):
        targets += [os.path.join(dirpath, f) for f in files if f.endswith(".vue")]
    for p in targets:
        text = io.open(p, encoding="utf-8").read()
        for m in FIG.finditer(text):
            var = m.group(1)
            if INK.search("--" + var):
                continue
            line = text[:m.start()].count("\n") + 1
            rel = os.path.relpath(p, os.path.dirname(os.path.dirname(CSS))).replace("\\", "/")
            out.append(f"{rel}:{line} → {m.group(0).strip()}")
    return out


def test_semantic_text_colors_use_ink_tokens():
    bad = _scan_figure_text_colors()
    assert not bad, (
        "语义文字色用了「图形色」令牌（暗色/亮色下对比度不达标），请换成 -ink 成对令牌"
        "（--primary-ink / --ink-danger / --st-feedback-ink / --success-ink / --muted）：\n  "
        + "\n  ".join(bad))


def test_ink_gate_would_catch_the_old_style():
    """**门禁自检**：拿修之前真出现过的那种写法，核对逻辑必须报出来（证明它不是摆设）。"""
    sample = '<span style="color:var(--accent);font-weight:600;">匿名居民#8c6433</span>'
    hits = [m.group(1) for m in FIG.finditer(sample)]
    assert hits == ["accent"], f"自检失效：扫描器认不出历史写法（hits={hits}）"
    assert not INK.search("--accent"), "自检失效：--accent 被误判成 ink 令牌"
    # 反向：换成 ink 令牌后不该再报
    fixed = sample.replace("var(--accent)", "var(--st-feedback-ink)")
    assert not FIG.search(fixed), "自检失效：改成 ink 令牌后仍被判违规"
    assert _scan_figure_text_colors() == [], "扫描器在仓库里仍有命中（上面的用例应已失败）"

