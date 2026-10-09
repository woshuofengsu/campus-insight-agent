# -*- coding: utf-8 -*-
"""前端"AI 展示感"客观审计 —— 把任务书里的**审美要求**变成可复现的数字。

## 为什么需要它（很实在的原因）

任务书要求"去掉渐变/发光/过度动画、页面里不许散落大量 hex、老年端默认页面不许出现技术术语"。
这些听起来是"看着办"，但**看着办的东西没法验收**：改完谁都能说"我觉得少多了"。
本项目的一贯做法是把要求变成判据 —— 这里也一样：

| 任务书要求 | 本脚本的判据 |
|---|---|
| 取消大面积渐变 | `linear-gradient / radial-gradient / conic-gradient` 出现次数（棘轮：只减不增） |
| 取消发光边框 | `box-shadow` 里的**光环/大模糊**、`filter: blur/drop-shadow`、`backdrop-filter` 次数 |
| 减少过度动画 | `animation` 中含 `infinite` 的次数、`@keyframes` 条数、页面入场动画 |
| 页面不许散落 hex | `.vue` 文件**内联样式**里的 hex 颜色数量 |
| 老年端默认页面无技术术语 | 老年端模板文本里出现 Agent/RAG/Verifier/多智能体/智能研判… 的次数（**必须为 0**） |

## 棘轮（只减不增）

`BASELINE` 记的是**当前实测值**；审计要求 `当前 <= 基线`，否则红。
重设计推进一步就用 `--update` 把新值写回（**脚本拒绝把数字改大**，除非 `--force` 并写明原因）。

⚠️ 诚实的边界：本脚本量的是"用了多少视觉特效"，**不等于"好不好看"**。
好不好看要人看截图（`.shots/pilot-ui-baseline/` 与 `.shots/pilot-ui-after/`）。
一条审计能防的是"改回去/又长回来"，防不了"审美跑偏"。

用法：
    python scripts/ui_style_audit.py              # 审计（与基线比）
    python scripts/ui_style_audit.py --detail     # 附每个文件的明细（定位改哪）
    python scripts/ui_style_audit.py --update     # 把当前值写回基线（只允许变小）
"""
import argparse
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web", "src")
ELDERLY_DIR = os.path.join(WEB, "views", "elderly")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

#: 基线（2026-10-06 第 0 步实测，**重设计前**的原值）。棘轮：当前值不得大于它。
BASELINE = {
    "gradient_sites": 28,
    "glow_sites": 16,
    "infinite_animations": 11,
    "keyframes": 17,
    "inline_hex": 87,
    "page_enter_animation": 2,
    "tech_terms_elderly": 0,
}

#: 老年端（老人看得见的页面 + 布局）不许出现的技术术语。
#: 判据只看**模板里会渲染的文字**（注释不算），这与 `test_no_markdown_bold_in_ui.py` 同口径。
TECH_TERMS = [
    "多智能体", "智能体", "Agent", "agent", "RAG", "Verifier", "Arbiter", "LLM",
    "大模型", "智能研判", "检索增强", "向量检索", "知识图谱", "编排", "黑板",
    "幻觉", "仲裁", "协作中", "正在分析", "推理",
    # 任务书 §四.2 点名的几句"要避免"的原话
    "智能服务中心", "AI 生活助手", "AI生活助手", "多智能体协作", "Agent 正在分析",
]

GRADIENT = re.compile(r"(linear|radial|conic)-gradient\s*\(")
GLOW = re.compile(r"(box-shadow\s*:[^;}]*(0\s+0[^;}]*(rgba?\(|#))"
                  r"|filter\s*:\s*(blur|drop-shadow)|backdrop-filter\s*:)")
INFINITE = re.compile(r"animation[^;}]*(infinite)")
KEYFRAMES = re.compile(r"@keyframes\s+[\w-]+")
INLINE_HEX = re.compile(r"(?:style|:style)\s*=\s*\"[^\"]*#[0-9a-fA-F]{3,8}")
PAGE_ENTER = re.compile(r"\.(page|elderly-page)[^{]*\{[^}]*animation\s*:")


def _files(exts=(".vue", ".js", ".ts", ".css")):
    out = []
    for dirpath, _dirs, files in os.walk(WEB):
        for fn in sorted(files):
            if fn.endswith(exts):
                out.append(os.path.join(dirpath, fn))
    return out


def _template_text(src: str) -> str:
    """取 `.vue` 里**会渲染的文本节点**（剥 HTML 注释、属性表达式、插值）。

    ⚠️ 判据必须只看"老人眼睛能看到什么"：
    第一版把整段 `<template>`（含属性）都算进来，于是 `@click="router.push('/elderly/agent')"`
    里的 **路径**被判成"页面上出现了 Agent 字样"——那是**假阳性**，
    而假阳性会让我去改一个根本没问题的东西（本项目第五次同类教训：
    判据要断言真正被保证的事）。所以这里：剥标签（含属性）→ 剥 `{{ … }}`（渲染的是数据不是字面量）。
    """
    if "<template" not in src:
        return ""
    start = src.index("<template")
    end = src.rfind("</template>")
    body = src[start:] if end < start else src[start:end]
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)     # HTML 注释
    body = re.sub(r"\{\{.*?\}\}", " ", body, flags=re.S)   # 插值（渲染的是数据）
    return re.sub(r"<[^>]*>", " ", body, flags=re.S)       # 标签与属性


def _defined_vars() -> set[str]:
    """style.css 里声明过的全部 CSS 变量名（含 :root / body.dark / 任何局部块）。"""
    css = io.open(os.path.join(WEB, "style.css"), encoding="utf-8").read()
    return set(re.findall(r"(--[a-zA-Z0-9-]+)\s*:", css))


def _strip_comments(src: str) -> str:
    """去掉 HTML 注释与 /* */ 块注释（保留行数，便于报准确行号）。

    ⚠️ 必须去注释：修完后我在注释里写了「原来写的是 var(--panel-lemon)」作为说明，
    第一版扫描器把**注释里的说明**也当成"引用了未定义变量"（3 处假红）。
    注释不是代码 —— 这一点在 emoji 门禁那边是反的（那里连注释也不许有 emoji），
    所以只能按判据本身的性质来定，不能一刀切。
    """
    def _repl(m: re.Match) -> str:
        return "\n" * m.group(0).count("\n")

    src = re.sub(r"<!--.*?-->", _repl, src, flags=re.S)
    return re.sub(r"/\*.*?\*/", _repl, src, flags=re.S)


def undefined_var_sites() -> list[str]:
    """**引用了但没定义**的 CSS 变量（`var(--x)`，且没写兜底值）。

    ⚠️ 为什么专门加这一条（2026-10-06 实测踩到，而且是**我自己造的**）：
    v3 重设计删掉了 `--primary-gradient` / `--primary-gradient-2`（品牌渐变不该再用），
    但**有 4 个页面还在引用它们**（登录页左栏、居民首页横幅、小助手表头、个人页头像卡）。
    `background: var(--primary-gradient-2)` 会整条声明失效 → 白字落在白底上，
    对比度变成 1:1（`ui_audit` 报了 8 处 HIGH）。**删一个变量，等于悄悄删掉别人的背景色。**
    这类问题的特点是"静态看代码完全正常、页面上直接不可读"，所以必须由门禁兜住。
    """
    defined = _defined_vars()
    bad = []
    for path in _files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        src = _strip_comments(io.open(path, encoding="utf-8").read())
        for m in re.finditer(r"var\(\s*(--[a-zA-Z0-9-]+)\s*(,)?", src):
            name, has_fallback = m.group(1), bool(m.group(2))
            if name.startswith("--n-"):          # Naive 运行时自带的变量，不归我们管
                continue
            if has_fallback:                      # 写了兜底值 → 没定义也能降级，不算问题
                continue
            if name not in defined:
                line = src[: m.start()].count("\n") + 1
                bad.append(f"{rel}:{line} → var({name}) 未定义（style.css 里没有这个变量）")
    return bad


def audit(detail: bool = False) -> tuple[dict, dict]:
    counts = {k: 0 for k in BASELINE}
    where: dict[str, list[str]] = {k: [] for k in BASELINE}
    for path in _files():
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        src = io.open(path, encoding="utf-8").read()
        # 注释也算：本项目明确禁止"注释里写特效示例"式的自欺（与 emoji 门禁同口径）
        for key, rx in (("gradient_sites", GRADIENT), ("glow_sites", GLOW),
                        ("infinite_animations", INFINITE), ("keyframes", KEYFRAMES),
                        ("inline_hex", INLINE_HEX if path.endswith(".vue") else None),
                        ("page_enter_animation", PAGE_ENTER if path.endswith(".css") else None)):
            if rx is None:
                continue
            n = len(rx.findall(src))
            if n:
                counts[key] += n
                where[key].append(f"{rel} × {n}")
        if path.startswith(ELDERLY_DIR) or rel.endswith("layouts/ElderlyLayout.vue"):
            body = _template_text(src)
            for term in TECH_TERMS:
                if term in body:
                    counts["tech_terms_elderly"] += body.count(term)
                    where["tech_terms_elderly"].append(f"{rel} → 「{term}」")
    if detail:
        for k in BASELINE:
            if where[k]:
                print(f"\n-- {k}（{counts[k]}）")
                for line in where[k][:40]:
                    print(f"     {line}")
    return counts, where


def _update_baseline(counts: dict, force: bool) -> int:
    path = os.path.abspath(__file__)
    src = io.open(path, encoding="utf-8").read()
    worse = {k: (BASELINE[k], counts[k]) for k in BASELINE if counts[k] > BASELINE[k]}
    if worse and not force:
        print("拒绝更新：以下计数**比基线更大**（这不是重设计，是把特效加回去了）：")
        for k, (old, new) in worse.items():
            print(f"  {k}: {old} → {new}")
        print("确实要更新（并在提交信息里写明原因）再加 --force。")
        return 1
    block = "BASELINE = {\n" + "".join(f'    "{k}": {counts[k]},\n' for k in BASELINE) + "}"
    src = re.sub(r"BASELINE = \{.*?\n\}", block, src, count=1, flags=re.S)
    io.open(path, "w", encoding="utf-8", newline="").write(src)
    print("基线已更新：" + " · ".join(f"{k}={counts[k]}" for k in BASELINE))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail", action="store_true")
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    counts, _where = audit(a.detail)
    undefined = undefined_var_sites()
    print("=" * 74)
    print("前端「AI 展示感」客观审计（棘轮：当前值不得大于基线）")
    print("=" * 74)
    bad = []
    for k in BASELINE:
        mark = "OK" if counts[k] <= BASELINE[k] else "FAIL"
        if counts[k] > BASELINE[k]:
            bad.append(k)
        print(f"  [{mark}] {k:<24} 当前 {counts[k]:>4} · 基线 {BASELINE[k]:>4}")
    print(f"  [{'OK' if not undefined else 'FAIL'}] {'undefined_css_vars':<24} "
          f"当前 {len(undefined):>4} · 基线    0")
    if undefined:
        print("-" * 74)
        print("以下位置引用了**没有定义**的 CSS 变量（整条样式会失效，通常表现为白字白底）：")
        for line in undefined[:20]:
            print("   " + line)
        return 1
    if a.update:
        return _update_baseline(counts, a.force)
    if bad:
        print("-" * 74)
        print(f"以下指标**比基线更大**（特效又长回来了）：{bad}")
        print("（重设计方向是减少，不是增加；若确属必要，加 --update --force 并写明原因）")
        return 1
    print("-" * 74)
    print("结论：全部不超过基线（老年端技术术语必须为 0 是硬判据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
