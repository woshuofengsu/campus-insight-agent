# -*- coding: utf-8 -*-
"""老年端图标门禁（v4 方案 §3：统一单色线性图标，替换 emoji）。

**为什么只守"布局层"**：老年端正文里还有一批 emoji（约 170 处，跨 10 个页面），
全量替换会动到所有页面与截图基线 —— 这一条不假装"全站已换"，只守两件事：

1. **顶部导航与标题栏**（每个页面都会看到的那些图形）必须用 `components/EIcon.vue`
   的单色线性图标，不许再用 emoji；
2. 老年端 emoji **总数只能减少**（棘轮）：新写页面时不许再往老人端堆 emoji。

配套要求：图标必须**单色**（`stroke="currentColor"`）——写死颜色的图标在暗色/高对比下不会跟着变，
那正是 `ui_audit` 抓到过的那类问题。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "src")
LAYOUT = os.path.join(WEB, "layouts", "ElderlyLayout.vue")
ICON = os.path.join(WEB, "components", "EIcon.vue")
ELDERLY_VIEWS = os.path.join(WEB, "views", "elderly")

# emoji 区段（图形符号 + 表情 + 常用符号变体）
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
# 棘轮基线：2026-09-29 把**布局层**（每个页面都看得到的那一排）清零后，views/elderly 里
# 仍有 176 处正文 emoji（跨 10 个页面）。全量替换会动到所有截图基线 → 列为赛后项，
# 这里只要求"不再增加"（新页面用 EIcon）。
BASELINE = 176


def _read(p: str) -> str:
    return io.open(p, encoding="utf-8").read()


def test_layout_has_no_emoji():
    bad = [(i, l.strip()) for i, l in enumerate(_read(LAYOUT).split("\n"), 1) if EMOJI.search(l)]
    assert not bad, (
        "老年端布局里又有 emoji 了（顶部导航/标题栏必须用 EIcon 的单色线性图标）：\n  "
        + "\n  ".join(f"{i}: {t}" for i, t in bad))


def test_layout_uses_the_icon_component():
    src = _read(LAYOUT)
    assert "components/EIcon.vue" in src, "老年端布局没有用 components/EIcon.vue"
    navs = re.search(r"const navs = \[(.*?)\]", src, re.S)
    assert navs, "找不到 navs 定义（导航结构变了？）"
    entries = re.findall(r"icon:\s*'([a-z]+)'", navs.group(1))
    assert len(entries) >= 6, f"导航图标没配全（拿到 {entries}）"
    known = set(re.findall(r"^\s{2}(\w+):", _read(ICON), re.M))
    missing = [e for e in entries if e not in known]
    assert not missing, f"EIcon 里没有这些图标：{missing}（先补路径，再改导航）"


def test_icon_is_monochrome():
    src = _read(ICON)
    assert 'stroke="currentColor"' in src, "图标不是 currentColor（写死色在暗色下不会跟着变）"
    assert not re.search(r"fill=\"#[0-9A-Fa-f]{3,6}\"", src), "图标里出现了写死的填充色"


def test_elderly_emoji_is_ratcheted():
    total = 0
    per_file: dict[str, int] = {}
    for dirpath, _dirs, files in os.walk(ELDERLY_VIEWS):
        for fn in files:
            if not fn.endswith(".vue"):
                continue
            p = os.path.join(dirpath, fn)
            n = len(EMOJI.findall(_read(p)))
            if n:
                rel = os.path.relpath(p, WEB).replace("\\", "/")
                per_file[rel] = n
                total += n
    layout_n = len(EMOJI.findall(_read(LAYOUT)))
    assert layout_n == 0, "布局层还有 emoji（上面的用例应已失败）"
    assert total <= BASELINE, (
        f"老年端 emoji 增多了：{total} > 基线 {BASELINE}。"
        f"新页面请用 EIcon（单色线性图标），不要再加 emoji。当前分布：{per_file}")


def test_scanner_self_check():
    """**门禁自检**：扫描器对已知样例必须给出正确判定（防止门禁本身失效而静默通过）。"""
    assert EMOJI.search("🏠 首页"), "自检失效：认不出 emoji"
    assert EMOJI.search("更多服务 🧰"), "自检失效：认不出行尾 emoji"
    assert not EMOJI.search("首页/我要报修/看进度"), "自检失效：把普通中文当成 emoji"
    assert not EMOJI.search('<EIcon name="home" :size="28" />'), "自检失效：把图标组件当成 emoji"
    # 布局层必须真的已经被改过（否则这组用例等于没测东西）
    assert "EIcon" in _read(LAYOUT), "自检失效：布局层根本没接图标组件"
