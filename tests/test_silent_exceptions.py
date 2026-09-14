# -*- coding: utf-8 -*-
"""静默吞异常门禁（本轮新增，源自"LLM 记账静默丢账"那个真 BUG）。

背景：`agent/llm_client._record()` 曾用 `_log.debug` 吞掉 `Database not initialized`，
于是"调用发生了、钱花了、账没记"——直接打穿"成本可现场复算"这个对外主张。
这类问题的共同形态是：**异常静默消失，而调用方以为成功了**。

两条门禁：
  1. 「静默假成功」必须为 0（吞异常之后紧接着返回成功标志 —— 最危险的一档）；
  2. 静默吞异常总数（HIGH/MID）不得超过 `scripts/audit_silent_exceptions.py` 里的基线（只减不增）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import audit_silent_exceptions as S  # noqa: E402


def test_no_silent_false_success():
    """吞掉异常后仍返回"成功"的地方必须为 0（有的话就是"用户以为成功、其实没落库"）。"""
    rows = S.scan()
    bad = [r for r in rows if r["false_success"]]
    assert not bad, "存在「静默假成功」（吞异常后返回成功）：\n  " + "\n  ".join(
        f"{r['file']}:{r['line']} → {r['body']}" for r in bad)


def test_silent_swallow_count_within_baseline():
    """静默吞异常总数只减不增（HIGH 多为刻意降级，不追求归零，但不能再涨）。"""
    rows = S.scan()
    high = [r for r in rows if r["grade"] == "high"]
    mid = [r for r in rows if r["grade"] == "mid"]
    assert len(high) <= S.BASELINE["high"], (
        f"HIGH 静默吞异常 {len(high)} > 基线 {S.BASELINE['high']}；"
        "新增处请补 `_log.warning(...)` 让失败可发现")
    assert len(mid) <= S.BASELINE["mid"], (
        f"MID 静默吞异常 {len(mid)} > 基线 {S.BASELINE['mid']}")


def test_scanner_detects_known_patterns():
    """扫描器自检：确认它真的能分辨"静默 / 有日志 / 假成功"，防止门禁本身失效。"""
    lines = [
        "def f():",
        "    try:",
        "        do()",
        "    except Exception:",     # 静默（索引 3）
        "        pass",
        "    return True,",
        "",
        "def g():",
        "    try:",
        "        do()",
        "    except Exception as e:",  # 有日志（索引 10）
        "        _log.warning('%s', e)",
        "    return True,",
    ]
    assert S._block_after(lines, 3) == "return True,"      # 吞异常后返回成功 → 假成功
    assert S._block_after(lines, 10) == "return True,"     # 有日志的块也能定位到后续语句
    assert S.SUCCESS_HINT.search(S._block_after(lines, 3))
