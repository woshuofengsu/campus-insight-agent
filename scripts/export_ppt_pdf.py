# scripts/export_ppt_pdf.py — 把路演 PPT 导出成兜底 PDF（投影/PPT 打不开时用）
# -*- coding: utf-8 -*-
"""为什么需要它：`docs/competition/pdf/9月22日路演-PPT预览.pdf` 是台上的兜底件
（"PPT 打不开就用 PDF 放一遍，内容一样"）。它必须是**从当前 pptx 现导**的，
否则改了 PPT 忘了重导，台上放的就是旧版——这类"交旧版"是本项目反复踩过的坑。
之前这份 PDF 是手敲 COM 命令导的，不可复算；这个脚本把它固定下来。

实现：PowerPoint COM 打开 pptx → SaveAs 成 PDF（只读打开，不改 pptx）。
Windows 专用；没装 PowerPoint 就明确报错退出（不要静默跳过，否则以为导好了）。

用法：
    python scripts/export_ppt_pdf.py                # 默认导 docs/competition/9月22日路演-社区先知.pptx
    python scripts/export_ppt_pdf.py --file x.pptx --out y.pdf
"""
import argparse
import glob
import os
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 纯 ASCII 的 PowerShell：PowerShell 5.1 会把无 BOM 的 UTF-8 当 ANSI 读，中文会乱码（项目里踩过）。
# 路径通过环境变量传入；ppSaveAsPDF = 32。
PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$src = $env:PPT_SRC
$dst = $env:PPT_DST
$app = New-Object -ComObject PowerPoint.Application
$deck = $app.Presentations.Open($src, $true, $false, $false)
"PAGES {0}" -f $deck.Slides.Count
$deck.SaveAs($dst, 32)
$deck.Close()
$app.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
"DONE"
"""


def default_pptx() -> str:
    files = [f for f in glob.glob(os.path.join(ROOT, "docs", "competition", "*.pptx"))
             if not os.path.basename(f).startswith("~$")]
    if not files:
        return ""
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="导出路演 PPT 的兜底 PDF")
    ap.add_argument("--file", default="", help="源 pptx（默认取 docs/competition 下最新的）")
    ap.add_argument("--out", default="", help="目标 pdf（默认 docs/competition/pdf/9月22日路演-PPT预览.pdf）")
    args = ap.parse_args()

    src = os.path.abspath(args.file) if args.file else default_pptx()
    if not src or not os.path.exists(src):
        print("❌ 找不到源 pptx")
        return 1
    dst = os.path.abspath(args.out) if args.out else \
        os.path.join(ROOT, "docs", "competition", "pdf", "9月22日路演-PPT预览.pdf")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)

    env = dict(os.environ, PPT_SRC=src, PPT_DST=dst)
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_TEMPLATE],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, cwd=ROOT)
    out = (p.stdout or "") + (p.stderr or "")
    pages = [ln for ln in out.splitlines() if ln.startswith("PAGES")]

    if "DONE" not in out or not os.path.exists(dst):
        print("❌ 导出失败（可能没装 PowerPoint 或被占用）：", out.strip()[-300:])
        return 1

    print(f"✅ {os.path.relpath(dst, ROOT)}（{os.path.getsize(dst) // 1024} KB）")
    if pages:
        print(f"   源文件页数：{pages[0].split()[-1]}")
    # 兜底件必须比源 pptx 新，否则台上放的是旧版
    if os.path.getmtime(dst) < os.path.getmtime(src):
        print("⚠️ PDF 比 PPT 旧，请重新导出")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
