# scripts/sync_test_count.py — 测试数变化时的一键同步（保持对外数字唯一来源）
# -*- coding: utf-8 -*-
"""为什么需要它：登录页 `meta.js`、README、AGENTS、交付说明、创意说明书-提交版、技术报告里都写了测试数，
加一条测试就要改 6~8 份文档，极易出现「总数改了、明细没改」或「某份漏改」的自相矛盾
（`scripts/check_claims.py` 与 `tests/test_claims_consistency.py` 会拦住，但需要一条命令修好）。

用法：
  python scripts/sync_test_count.py            # 自动探测 pytest 可运行用例数并同步
  python scripts/sync_test_count.py 577        # 或显式指定
  python scripts/sync_test_count.py --check    # 只检查不修改（CI 用）

口径说明：**可运行 = passed + skipped**（`pytest -q` 的 "577 tests collected" 含 3 项按标记排除，
对外统一报「可运行」，与登录页一致）。
"""
import io
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
META = os.path.join(ROOT, "web", "src", "config", "meta.js")

# 会写测试数的文档（当前状态文档；历史日志如 dev-log/CHANGELOG 历史条目不动）
DOCS = [
    "README.md", "AGENTS.md", "开发约定.md",
    "docs/competition/最终版交付说明.md",
    "docs/competition/创意说明书-提交版.md",
    "docs/competition/技术实现报告.md",
    "docs/scaling.md", "docs/mobile-deploy.md",
]


def detect_runnable() -> int:
    """跑 pytest --collect-only 取「可运行」用例数（selected，不含按标记排除的）。"""
    try:
        p = subprocess.run([sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q"],
                           cwd=ROOT, capture_output=True, text=True, timeout=300, check=False)
        out = (p.stdout or "") + (p.stderr or "")
    except Exception as e:  # noqa: BLE001
        print("无法探测用例数：", e)
        return -1
    m = re.search(r"(\d+)/(\d+)\s+tests?\s+collected", out)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s+tests?\s+collected", out)
    return int(m.group(1)) if m else -1


def current_meta() -> int:
    m = re.search(r"key:\s*'tests',\s*value:\s*(\d+)", io.open(META, encoding="utf-8").read())
    return int(m.group(1)) if m else -1


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check_only = "--check" in sys.argv

    new = int(args[0]) if args else detect_runnable()
    if new <= 0:
        print("❌ 未能得到有效用例数（先确认 pytest 可跑）")
        return 1
    old = current_meta()
    passed = new - 1          # 1 项需外部服务默认跳过
    detail = f"{passed} passed / 1 skipped"

    print(f"可运行用例数：{new}（{detail}）｜登录页 meta.js 现值：{old}")
    if check_only:
        if old != new:
            print(f"❌ 不一致：请跑 `python scripts/sync_test_count.py {new}`")
            return 1
        print("✅ meta.js 与实测一致")
        return 0
    if old == new and "--force" not in sys.argv:
        print("✅ 已一致，无需修改（要强制重写正文数字可加 --force）")

    # 1) meta.js（唯一来源）
    src = io.open(META, encoding="utf-8").read()
    src2 = re.sub(r"(key:\s*'tests',\s*value:\s*)\d+", rf"\g<1>{new}", src)
    src2 = re.sub(r"（= \d+ 通过 \+ 1 需外部服务默认跳过）", f"（= {detail}）", src2)
    if src2 != src:
        io.open(META, "w", encoding="utf-8", newline="").write(src2)
        print(f"  meta.js → {new}")

    # 2) 文档：把「NNN 项测试 / NNN 测试 / NNN passed / NNN 通过」里的旧数字换成新值
    for doc in DOCS:
        p = os.path.join(ROOT, doc)
        if not os.path.exists(p):
            continue
        s = orig = io.open(p, encoding="utf-8").read()
        s = re.sub(r"\b\d{3}(\s*项\s*自动化\s*测试|\s*项\s*测试|\s*测试|\s*项\b)",
                   lambda m: f"{new}{m.group(1)}", s)
        s = re.sub(r"\b\d{3}(\s*passed|\s*通过)", lambda m: f"{new - 1 if '通过' in m.group(1) else new}{m.group(1)}", s)
        if s != orig:
            io.open(p, "w", encoding="utf-8", newline="").write(s)
            print(f"  {doc} 已同步")

    print("\n提示：同步后跑 `python scripts/check_claims.py` 与 "
          "`python -m pytest tests/test_claims_consistency.py -q` 复核。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
