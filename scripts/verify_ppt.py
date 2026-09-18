# scripts/verify_ppt.py — 校验生成的 PPT（文字溢出 / 出画 / 被图片遮挡）
# -*- coding: utf-8 -*-
"""为什么需要它：2026-09-15 实测踩到过一次"封面标题看起来被切掉"——
真正原因不是字太长，而是**右侧截图后画、盖在了标题上**（文本框一直伸到 12.1 英寸）。
纯肉眼看缩略图很容易漏，所以把三类几何问题做成可复算的检查：

  ① 文字比文本框宽（会折行或溢出）→ 阈值 2pt
  ② 文本框右边界/下边界超出幻灯片
  ③ **文本框与图片/其他文本框重叠**（后画的会盖住先画的 —— 就是上面那个坑）

实现：用 PowerPoint COM 打开真实文件读取每个形状的坐标与文字边界（只读，不改文件）。
Windows 专用；无 PowerPoint 时自动跳过并提示。

用法：
    python scripts/verify_ppt.py                 # 默认检查 docs/competition/*.pptx
    python scripts/verify_ppt.py --file x.pptx
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

# 纯 ASCII 的 PowerShell 检查脚本：PowerShell 5.1 会把无 BOM 的 UTF-8 .ps1 当 ANSI 读，
# 中文会乱码（项目里踩过），所以这里只输出 ASCII 标签。
PS_TEMPLATE = r"""
$ErrorActionPreference = 'Stop'
$path = $env:VERIFY_PPT_PATH
$app = New-Object -ComObject PowerPoint.Application
$deck = $app.Presentations.Open($path, $true, $false, $false)
$sw = $deck.PageSetup.SlideWidth
$sh_ = $deck.PageSetup.SlideHeight
"SLIDE {0} x {1}" -f $sw, $sh_
foreach ($i in 1..$deck.Slides.Count) {
  $s = $deck.Slides.Item($i)
  "PAGE $i"
  $boxes = @()
  foreach ($sh in $s.Shapes) {
    $hasText = $false; $txt = ""
    try { if ($sh.HasTextFrame -eq -1) { if ($sh.TextFrame2.HasText -eq -1) { $hasText = $true; $txt = $sh.TextFrame2.TextRange.Text } } } catch {}
    $isPic = $false
    try { if ($sh.Type -eq 13) { $isPic = $true } } catch {}
    if (-not $hasText -and -not $isPic) { continue }
    $L = [math]::Round($sh.Left,1); $T = [math]::Round($sh.Top,1)
    $W = [math]::Round($sh.Width,1); $H = [math]::Round($sh.Height,1)
    $tw = 0.0; $th = 0.0
    if ($hasText) { try { $tw = [math]::Round($sh.TextFrame2.TextRange.BoundWidth,1); $th = [math]::Round($sh.TextFrame2.TextRange.BoundHeight,1) } catch {} }
    $kind = if ($isPic) { "PIC" } else { "TXT" }
    $short = ($txt -replace "`r", " | ")
    if ($short.Length -gt 26) { $short = $short.Substring(0,26) }
    $warn = ""
    if ($hasText -and $tw -gt ($W + 2)) { $warn = $warn + " [TEXT_WIDER_THAN_BOX tw=$tw w=$W]" }
    if (($L + $W) -gt ($sw + 1)) { $warn = $warn + " [OFF_SLIDE_RIGHT]" }
    if (($T + $H) -gt ($sh_ + 1)) { $warn = $warn + " [OFF_SLIDE_BOTTOM]" }
    # 记录矩形用于重叠检测（图片优先标记，便于判断"谁盖住谁"）
    $boxes += [pscustomobject]@{ kind=$kind; L=$L; T=$T; R=($L+$W); B=($T+$H); label=$short }
    "  {0} L={1,7:F1} T={2,7:F1} W={3,7:F1} H={4,7:F1} tw={5,7:F1} {6}{7}" -f $kind, $L, $T, $W, $H, $tw, $short, $warn
  }
  # 重叠检测：文字框 vs 图片（图片后画会盖住文字）
  foreach ($a in $boxes) {
    foreach ($b in $boxes) {
      if ($a -eq $b) { continue }
      if ($a.kind -ne "TXT" -or $b.kind -ne "PIC") { continue }
      $ox = [math]::Min($a.R, $b.R) - [math]::Max($a.L, $b.L)
      $oy = [math]::Min($a.B, $b.B) - [math]::Max($a.T, $b.T)
      if ($ox -gt 2 -and $oy -gt 2) {
        "  [TEXT_UNDER_PICTURE] txt='$($a.label)' ovlp={0:F0}x{1:F0}pt" -f $ox, $oy
      }
    }
  }
}
$deck.Close()
$app.Quit()
[System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
"END"
"""


def check(path: str) -> int:
    env = dict(os.environ, VERIFY_PPT_PATH=os.path.abspath(path))
    p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", PS_TEMPLATE],
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env=env, cwd=ROOT)
    out = (p.stdout or "") + (p.stderr or "")
    print(f"== {os.path.basename(path)}")
    bad = 0
    for ln in out.splitlines():
        if ln.strip().startswith(("SLIDE", "PAGE")) or "!!" in ln:
            print("  " + ln.strip())
        if "[TEXT_WIDER_THAN_BOX" in ln or "[TEXT_UNDER_PICTURE" in ln or "[OFF_SLIDE" in ln:
            bad += 1
            print("  ⚠️ " + ln.strip())
    if "END" not in out:
        print("  ⚠️ COM 未正常结束（可能没装 PowerPoint）：", out.strip()[-160:])
        return -1
    print(f"  → 问题条目：{bad}" + ("  ✅ 通过" if bad == 0 else "  ❌ 需要修"))
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="校验 PPT 的文字溢出/出画/被图片遮挡")
    ap.add_argument("--file", default="")
    args = ap.parse_args()
    files = [args.file] if args.file else \
        [f for f in glob.glob(os.path.join(ROOT, "docs", "competition", "*.pptx"))
         if not os.path.basename(f).startswith("~$")]
    if not files:
        print("没有找到 pptx")
        return 1
    total = 0
    for f in files:
        r = check(f)
        total += max(0, r)
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
