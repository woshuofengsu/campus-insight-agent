# scripts/audit_silent_exceptions.py — 静默吞异常分诊（今天那个"记账丢账"BUG 的类型化防线）
# -*- coding: utf-8 -*-
"""为什么需要它（真实起因）：

`agent/llm_client._record()` 曾用 `_log.debug` 吞掉异常，于是**LLM 调用发生了、钱花了、
但 llm_usage 一条记录都没有** —— 直接打穿"成本可现场复算"这个对外主张。它不是能力问题，
而是"异常静默消失"这一类问题里的一个样本。

本脚本把这一类找出来并分档，防止它继续扩散：

- **HIGH（写路径 / 账务 / 安全）**：`utils/crypto.py`、`agent/llm_client.py`、`agent/verifier.py`、
  `agent/arbiter.py`、`agent/orchestrator.py`、`api_routes/**`、`data/db_*.py`
  （这些地方静默吞异常 = 用户看到"成功"但数据没落库 / 账没记 / 防线没生效）
- **MID**：`agent/**`、`data/**` 其余文件（多为刻意的降级：LLM 挂了回规则、外部 API 挂了用缓存）
- **LOW**：`ui/**`（Streamlit 旧备线）、`scripts/**`（工具）

判据：`except` 块体内 3 行里既没有 `log/print/raise/warn`，也没有 `traceback` → 视为静默。

用法：
    python scripts/audit_silent_exceptions.py            # 打印分档清单 + 与基线对比（门禁）
    python scripts/audit_silent_exceptions.py --list high # 只看 HIGH 明细
退出码：0 = HIGH/MID 未超基线；1 = 有新增静默吞异常
"""
import argparse
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCAN_DIRS = ("agent", "api_routes", "data", "utils", "tools", "perception", "ui", "scripts")
SKIP_DIRS = {"__pycache__", "node_modules", ".git", ".shots", "web", "tests"}

HIGH_FILES = (
    "utils/crypto.py", "agent/llm_client.py", "agent/verifier.py", "agent/arbiter.py",
    "agent/orchestrator.py", "agent/blackboard.py",
)
HIGH_PREFIXES = ("api_routes/", "data/db_")

# 打分档用的关键词：命中说明这段异常一旦被吞，后果是"看得见的假成功"
SUCCESS_HINT = re.compile(r"return\s+(True|ok|\(\s*True|1\b)")

LOGGY = ("log.", "_log.", "logger.", "logging.", "print(", "raise", "warn", "traceback",
         "logging.getLogger")

# 基线（本轮分诊修复后的实测值）：只减不增 —— 新增静默吞异常会让门禁变红。
# HIGH 大多数是**刻意的降级**（外部 API 挂了/LLM 挂了就用兜底），所以不追求归零；
# 真正要守死的是「静默假成功」（吞异常后仍返回成功）—— 现在实测为 0，由测试断言钉住。
BASELINE = {"high": 133, "mid": 29}


def _block_after(lines: list[str], exc_idx: int) -> str:
    """返回 except 块**结束后的第一条语句**（同缩进或更外层）。

    为什么要精确到这个粒度：早先版本用"往后 12 行里出现过 return True"来判"静默假成功"，
    结果把**别的分支**的 `return True` 也算进来，7 条里 6 条是误报 —— 会误报的检查工具
    本身不可信。现在只认"吞掉异常之后紧接着返回成功"。
    """
    exc_indent = len(lines[exc_idx]) - len(lines[exc_idx].lstrip())
    j = exc_idx + 1
    while j < len(lines):
        s = lines[j].strip()
        if not s:
            j += 1
            continue
        indent = len(lines[j]) - len(lines[j].lstrip())
        if indent <= exc_indent:      # 块结束
            return s
        j += 1
    return ""


def _grade(path: str) -> str:
    rel = path.replace("\\", "/")
    if rel in HIGH_FILES or rel.startswith(HIGH_PREFIXES):
        return "high"
    if rel.startswith(("agent/", "data/")):
        return "mid"
    return "low"


def scan() -> list[dict]:
    out: list[dict] = []
    for d in SCAN_DIRS:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, ROOT).replace("\\", "/")
                lines = open(full, encoding="utf-8", errors="replace").read().splitlines()
                for i, ln in enumerate(lines):
                    if not re.match(r"\s*except\b", ln) or not ln.rstrip().endswith(":"):
                        continue
                    body, j = [], i + 1
                    while j < len(lines) and len(body) < 4:
                        s = lines[j].strip()
                        if s and re.match(r"(except|else|finally|def |class |@)", s):
                            break
                        if s:
                            body.append(s)
                        j += 1
                    joined = " ".join(body)
                    if any(k in joined for k in LOGGY):
                        continue
                    after = _block_after(lines, i)
                    out.append({
                        "file": rel, "line": i + 1, "grade": _grade(rel),
                        "body": joined[:70],
                        "false_success": bool(SUCCESS_HINT.search(after)),
                    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", default="all", choices=("all", "high", "mid", "false-success"))
    ap.add_argument("--update-baseline", action="store_true", help="把当前计数写回 BASELINE（仅人工确认后使用）")
    args = ap.parse_args()

    rows = scan()
    by_grade = {"high": [], "mid": [], "low": []}
    for r in rows:
        by_grade[r["grade"]].append(r)
    false_ok = [r for r in rows if r["false_success"]]

    print("=== 静默吞异常分诊（except 块里既不记日志也不抛出）===")
    print(f"总计 {len(rows)} 处 = HIGH {len(by_grade['high'])} + MID {len(by_grade['mid'])} + LOW {len(by_grade['low'])}")
    print(f"其中「静默假成功」（吞异常后仍返回成功标志）{len(false_ok)} 处 —— 这一档最危险\n")

    def dump(title: str, items: list[dict], limit: int = 40) -> None:
        if not items:
            return
        print(f"—— {title}（{len(items)}）——")
        for r in items[:limit]:
            flag = " ⚠假成功" if r["false_success"] else ""
            print(f"  {r['file']}:{r['line']}{flag}  {r['body']}")
        if len(items) > limit:
            print(f"  …还有 {len(items) - limit} 处")
        print()

    if args.list in ("all", "false-success"):
        dump("静默假成功（优先修）", false_ok, 30)
    if args.list in ("all", "high"):
        dump("HIGH：写路径 / 账务 / 安全", by_grade["high"], 30)
    if args.list == "all":
        dump("MID：降级路径（多为刻意，但失败应留痕）", by_grade["mid"], 25)

    if args.update_baseline:
        print(f"请把 BASELINE 改为 {{'high': {len(by_grade['high'])}, 'mid': {len(by_grade['mid'])}}}")

    over = []
    if len(false_ok) > 0:
        over.append(f"静默假成功 {len(false_ok)} 处（必须为 0）")
    if BASELINE["high"] and len(by_grade["high"]) > BASELINE["high"]:
        over.append(f"HIGH {len(by_grade['high'])} > 基线 {BASELINE['high']}")
    if BASELINE["mid"] and len(by_grade["mid"]) > BASELINE["mid"]:
        over.append(f"MID {len(by_grade['mid'])} > 基线 {BASELINE['mid']}")

    if over:
        print("❌ 静默吞异常新增了：", "；".join(over))
        print("   处理：① 补 `_log.warning(...)` 让失败可发现；② 或收窄异常类型；③ 确属刻意的降级 → 加注释并放宽基线")
        return 1
    print("✅ 未超过基线（HIGH 必须保持 0）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
