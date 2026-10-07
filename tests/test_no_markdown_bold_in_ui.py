# -*- coding: utf-8 -*-
"""界面文案门禁：Vue 模板里**渲染出来的文字**不许出现 Markdown 粗体标记 `**…**`。

为什么要有这条（2026-10-06 实测踩到，属于"看不出来但用户一眼就看见"的那类）：
  · 我在写注释时习惯用 `**重点**` 标粗，结果**写进了模板的文本节点**——
    `**` 在 Vue 模板里只是普通字符，页面会把星号**原样显示**（"这是一台**共享设备**"）；
  · 这类问题 `ui_audit` 测不出（它测对比度/字号/热区，不判断"这两个星号是不是笔误"），
    `mobile_audit` 同样测不出，`npm run build` 也不报错；
  · 同一次扫描在**旧代码**里也扫出 3 处（`Dashboard.vue` 治理指标说明、`Weather.vue`
    超时升级名单、`QA.vue` 演示数据免责），说明这不是一次性手误，而是**会反复长回来**的习惯问题
    —— 所以必须做成门禁。

判据（只查"会显示给用户"的文本，注释里的 `**` 是正常的书写习惯，不查）：
  1. `.vue`：只看 `<template>` 块（先剥掉 HTML 注释 `<!-- … -->`）；
  2. `.js` / `.ts`：跳过纯注释行（`//` `/*` `*` 开头）——这些文件里的字符串可能进界面，
     但注释不会；
  3. 自检：扫描器对坏样例必须报出来，且不能把"手机号掩码 `****`"这类正常文本误判。
"""
import io
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "src")

#: 粗体标记：两个星号 + 至少一个非星号字符 + 两个星号。
#: ⚠️ 故意写成 `[^*\n]+`：手机号掩码 `'****'`（`Profile.vue`）与 `idempotency **` 之类的
#: 连续星号**不该**被判成粗体，写成 `\*\*.+\*\*` 会把它们一起抓进来（误报比漏报更糟：
#: 一条会误报的门禁，最后一定会被人加进豁免名单然后失效）。
BOLD = re.compile(r"\*\*[^*\n]+\*\*")

#: 豁免：**空**。模板文案里没有任何"必须写两个星号"的正当理由。
#: （如果哪天真需要显示 `**`，正确做法是写 `&#42;&#42;` 之类的转义，而不是豁免整个文件。）
ALLOW: dict[str, str] = {}


def _sources() -> list[tuple[str, str]]:
    out = []
    for dirpath, _dirs, files in os.walk(WEB):
        for fn in sorted(files):
            if not fn.endswith((".vue", ".js", ".ts")):
                continue
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, WEB).replace("\\", "/")
            out.append((rel, io.open(p, encoding="utf-8").read()))
    return out


def _template_body(text: str) -> str:
    """取 `<template>` 块（`.vue`）；没有模板块（纯 js/ts）就返回空串。

    ⚠️ 返回值的**行号必须与源文件对齐**：模板块从 `<template>` 那一行才开始，
    如果直接返回块内容，报出来的行号会整体前移（实测：报 `Report.vue:209`，
    而那一行其实是 `}`）—— 行号错位的门禁等于让人去错误的地方找问题。
    所以这里用等量空行把块前面那部分补上。
    """
    if "<template" not in text:
        return ""
    start = text.index("<template")
    end = text.rfind("</template>")
    body = text[start:] if end < start else text[start:end]
    return "\n" * text[:start].count("\n") + body


def _strip_html_comments(text: str) -> str:
    """剥掉 `<!-- … -->`（**跨行**注释里的 `**` 是书写习惯，不是文案）。

    ⚠️ 换成**等量换行**而不是删空：直接删掉多行注释会让后面所有行的行号前移，
    报出来的位置就是错的（实测踩到：报 `Report.vue:562`，那一行其实没有 `**`）。
    """
    def _repl(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n")

    return re.sub(r"<!--.*?-->", _repl, text, flags=re.S)


def _rendered_text(rel: str, text: str) -> str:
    """返回"可能会显示给用户"的那部分文本（行号按原文件算，所以这里保留换行结构）。"""
    if rel.endswith(".vue"):
        return _strip_html_comments(_template_body(text))
    # .js / .ts：逐行剔除注释行，其余保留（行号不会错位）
    kept = []
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith(("//", "/*", "*", "*/")):
            kept.append("")
        else:
            kept.append(line)
    return "\n".join(kept)


def _violations() -> list[str]:
    bad = []
    for rel, text in _sources():
        if rel in ALLOW:
            continue
        body = _rendered_text(rel, text)
        for m in BOLD.finditer(body):
            line = body[: m.start()].count("\n") + 1
            bad.append(f"{rel}:{line} → {m.group(0)[:60]}")
    return bad


def test_no_markdown_bold_in_rendered_text():
    bad = _violations()
    assert not bad, (
        "界面文案里出现了 Markdown 粗体标记 `**…**`（页面上会把星号**原样显示**出来的）：\n  "
        + "\n  ".join(bad)
        + "\n（改法：模板文本节点里用 `<b>…</b>`；注释里怎么写都行，本门禁不查注释）")


def test_allowlist_is_documented():
    """豁免必须写明理由（现在是空的；一旦有人加，就必须写清为什么非写星号不可）。"""
    for rel, why in ALLOW.items():
        assert len(why) >= 8, f"{rel} 的豁免理由太短（等于没写）"
        assert os.path.isfile(os.path.join(WEB, rel)), f"豁免的文件不存在：{rel}"


def test_scanner_self_check():
    assert BOLD.search("这是一台**共享设备**："), "自检失效：认不出模板里的粗体标记"
    # 误报检查：这两类是**正常文本**，不许被抓
    assert not BOLD.search("手机号 138****8888"), "自检失效：把手机号掩码当成粗体"
    assert not BOLD.search("return p.slice(0, 3) + '****' + p.slice(-4)"), "自检失效：把掩码拼接当成粗体"
    # 注释必须被剥掉：模板里的 HTML 注释、js 行注释里的 `**` 都不算文案
    assert not BOLD.search(_strip_html_comments("<!-- 注意：**这里不渲染** -->")), \
        "自检失效：没剥掉 HTML 注释"
    assert not BOLD.search(_rendered_text("a.js", "// 说明：**这只是注释**\nconst x = 1")), \
        "自检失效：没跳过 js 行注释"
    # 反过来：模板文本节点里的必须留下
    assert BOLD.search(_rendered_text("a.vue", "<template>\n<div>**要点**</div>\n</template>")), \
        "自检失效：模板文本没被扫到"
    # 真实文件必须至少扫到过一次模板内容（否则说明 `<template>` 提取坏了，门禁静默失效）
    vue = [(rel, t) for rel, t in _sources() if rel.endswith(".vue")]
    assert len(vue) >= 20, f"扫到的 .vue 文件太少（{len(vue)} 个），目录是不是不对？"
    assert any("<div" in _template_body(t) for _rel, t in vue), "自检失效：一个模板块都没取到"
