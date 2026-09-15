# scripts/export_pdf.py — 把提交件导出为 PDF（评委会要求 PDF 时用）
# -*- coding: utf-8 -*-
"""为什么需要它：比赛提交系统通常要 PDF（Word/PDF 是通用要求），而我们的源文件是 Markdown。
`docs/competition/build_html.py` 已经能把 Markdown 转成适合打印的干净 HTML，本脚本再用
Playwright（项目已有依赖，ui_audit/mobile_audit 在用）把 HTML 打成 A4 PDF。

用法：
    python scripts/export_pdf.py                 # 导出全部提交件
    python scripts/export_pdf.py 创意说明书-提交版   # 只导出某一份（按文件名前缀匹配）

产物：docs/competition/pdf/*.pdf（页边距 16mm、保留背景色、无页眉页脚）
注意：先跑 build_html（本脚本会自动先跑一次），保证 PDF 与最新 Markdown 一致——
      这与"改完前端必须 rebuild"是同一类纪律：**导出物必须晚于源文件**。
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs", "competition")
OUT = os.path.join(DOCS, "pdf")

# 需要导出的提交件（顺序即提交顺序）
TARGETS = [
    "创意说明书-提交版",
    "诚信声明-提交版",
    "技术实现报告",
    "最终版交付说明",
    "答辩问答手册",
    "演示脚本",
    "评委评审报告",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="提交件 PDF 导出")
    ap.add_argument("only", nargs="*", default=None, help="只导出指定文件（文件名前缀）")
    args = ap.parse_args()

    # 1) 先用最新 Markdown 重新生成 HTML（保证 PDF 不落后于源文件）
    print("① 重新生成打印用 HTML …")
    p = subprocess.run([sys.executable, os.path.join(DOCS, "build_html.py")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        print("   ❌ build_html 失败：", (p.stderr or p.stdout)[-400:])
        return 1
    print("   ✅ 完成")

    picked = [t for t in TARGETS if not args.only or any(t.startswith(o) for o in args.only)]
    missing = [t for t in picked if not os.path.exists(os.path.join(DOCS, t + ".html"))]
    if missing:
        print("   ⚠️ 这些没有对应 HTML（先确认 build_html 的 TASKS 是否包含）：", missing)
    picked = [t for t in picked if t not in missing]

    os.makedirs(OUT, exist_ok=True)
    print(f"② 导出 PDF（{len(picked)} 份）→ {os.path.relpath(OUT, ROOT)}\\")
    from playwright.sync_api import sync_playwright

    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for name in picked:
            src = os.path.join(DOCS, name + ".html")
            dst = os.path.join(OUT, name + ".pdf")
            page.goto("file:///" + src.replace("\\", "/"), wait_until="load")
            page.emulate_media(media="print")
            page.pdf(path=dst, format="A4", print_background=True,
                     margin={"top": "16mm", "bottom": "16mm", "left": "14mm", "right": "14mm"})
            size = os.path.getsize(dst) / 1024
            rows.append((name, size))
            print(f"   ✅ {name}.pdf（{size:.0f} KB）")
        browser.close()

    # 3) 写一份清单（含生成时间，便于判断快照新鲜度）
    idx = os.path.join(OUT, "README.md")
    with open(idx, "w", encoding="utf-8", newline="\n") as f:
        f.write("# 提交件 PDF（自动导出）\n\n")
        f.write(f"> 生成时间：{datetime.now():%Y-%m-%d %H:%M}｜来源：`docs/competition/*.md` → HTML → PDF\n")
        f.write("> 重新生成：`python scripts/export_pdf.py`（会自动先刷新 HTML）\n\n")
        f.write("| 文件 | 大小 |\n|---|---|\n")
        for name, size in rows:
            f.write(f"| `{name}.pdf` | {size:.0f} KB |\n")
        f.write("\n**注意**：PDF 是**导出物**，内容以对应 `.md` 为准；改了 md 必须重跑本脚本"
                "（否则交上去的是旧版本——与前端 dist 同一条纪律）。\n")
    print(f"③ 清单：{os.path.relpath(idx, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
