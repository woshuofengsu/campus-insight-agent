# -*- coding: utf-8 -*-
"""数字口径工具的门禁：**别让"报数字"这件事本身出错**。

**为什么要这条门禁**（2026-09-29 实测踩到，代价是 8 份对外材料同时写错）：
项目里有两个脚本专门维护/核对"可运行用例数"这个口径——
`scripts/sync_test_count.py`（把新数字写进文档）与 `scripts/check_claims.py`（核对文档与实测一致）。
它们的正则都写成了**固定三位**（`\\d{3}`）。套件从 999 涨到 **1000** 的那一次：
  · 写入侧把 "1000" 里的前三位 "100" 替换成 "1000" → 文档被写成 **10000**（8 份材料同时错）；
  · 核对侧的读取正则也读不出四位数字 → 它**看不出**这个错，还指望别人手动核对。
两边一起"看起来正常"，正是本项目最忌讳的那类问题：**门禁自己坏了，却仍然报绿**。

本文件用纯函数把这两件事钉住：
  ① 写入侧：三位→四位增长不得产生重复数字（1000 → 1001，而不是 10010）；
  ② 核对侧：源码里不许再出现"固定三位"式的取数正则（用源码断言，附理由）；
  ③ 反向自检：用旧写法（固定三位）跑同一个输入，必须**复现**出错误结果（证明这条门禁不是摆设）。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_rewrite_counts_handles_four_digit_growth():
    """三位 → 四位不得产成 "10010" 这类重复数字（这就是当时的真实事故）。"""
    from scripts.sync_test_count import rewrite_counts
    assert rewrite_counts("可运行 1000 项（999 通过）", 1001) == "可运行 1001 项（1000 通过）"
    assert rewrite_counts("可运行用例 999", 1000) == "可运行用例 1000"
    # 通过数必须是「可运行数 − 1」：这条是历史上真实踩过的坑（出现过「577 passed（可运行 576）」）
    assert rewrite_counts("**999 passed / 1 skipped**（可运行 1000 项）", 1001) == \
        "**1000 passed / 1 skipped**（可运行 1001 项）"
    # 常见几种写法都要覆盖（历史上漏一种就会出现自相矛盾的数字）
    for text in ("999 项测试", "999 项可运行", "999 = 998 通过", "可运行 999"):
        out = rewrite_counts(text, 1000)
        assert "9999" not in out and "10000" not in out, f"{text} → {out}"
        assert "1000" in out, f"{text} → {out}"


def test_rewrite_counts_is_idempotent():
    """同一个数字再写一遍不该变形（幂等，避免"跑两次数字翻倍"）。"""
    from scripts.sync_test_count import rewrite_counts
    once = rewrite_counts("可运行 1000 项（999 通过）", 1000)
    twice = rewrite_counts(once, 1000)
    assert once == twice == "可运行 1000 项（999 通过）"


def test_rewrite_counts_covers_repro_guide_phrasing():
    """**「可运行总数 = N」这种写法也必须被同步覆盖**（复现指南就是这么写的）。

    实测踩到：`docs/复现指南.md` 里写的是「可运行总数 = 1098」，
    而旧正则要求"可运行"后面**紧跟**数字，于是跑完同步它**没被改**，
    只剩 `test_repro_guide.py` 报红——那是"工具没覆盖到"，不是文档写错了。
    """
    from scripts.sync_test_count import rewrite_counts
    out = rewrite_counts("可运行总数 = 1098，与登录页 meta.js 一致", 1099)
    assert "1099" in out and "1098" not in out, out
    # 全角等号也要认（中文文档里很常见）
    out2 = rewrite_counts("可运行总数＝1098", 1099)
    assert "1099" in out2, out2
    # 同句里的 passed 仍按「可运行 − 1」走
    out3 = rewrite_counts("可运行总数 = 1098（1097 passed）", 1099)
    assert "1099" in out3 and "1098 passed" in out3, out3


def test_gate_selfcheck_old_regex_really_corrupts():
    """**门禁自检**：用旧的固定三位写法跑同一输入，必须复现"10000"这个错误。

    没有这条自检，上面那些断言可能是"换了写法之后顺手写的、和事故无关"的巧合；
    这里明确证明：错的写法确实会产出错数字。
    """
    text = "可运行用例 1000"
    old = re.sub(r"(可运行用例[\s|*]*)\d{3}", lambda m: f"{m.group(1)}{1000}", text)
    assert old == "可运行用例 10000", f"旧写法没复现事故，说明自检无效：{old}"
    from scripts.sync_test_count import rewrite_counts
    assert rewrite_counts(text, 1000) == "可运行用例 1000"


def test_no_fixed_three_digit_number_regex_left():
    """计数链路上**不许**再有固定三位的取数正则（源码级防回归）。

    三个地方都栽过同一跤（999 → 1000 那次）：写入侧 `scripts/sync_test_count.py`、
    核对侧 `scripts/check_claims.py`、以及 `tests/test_claims_consistency.py` 自己的核对表。
    所以这里三处一起守——数字口径的"维护者"和"检查者"同时坏掉时，门禁会照绿，
    那才是最危险的情况。
    """
    for name in ("scripts/sync_test_count.py", "scripts/check_claims.py",
                 "tests/test_claims_consistency.py"):
        src = io.open(os.path.join(ROOT, name), encoding="utf-8").read()
        bad = [ln.strip() for ln in src.splitlines()
               if re.search(r"d\{3\}(?!\s*,)", ln) and not ln.strip().startswith("#")]
        assert not bad, (f"{name} 里还有固定三位的取数正则（套件跨过 999 条就会写错/读不出数字）：\n  "
                         + "\n  ".join(bad))
