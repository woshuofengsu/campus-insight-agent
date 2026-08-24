# -*- coding: utf-8 -*-
"""P1-D3-01 LLM 评测集测试：golden 集完整性 + 规则引擎跑分达标 + LLM 跑分达标。

保证 tests/llm_eval/golden.jsonl 的每条 case 都能被规则引擎/真实 LLM 通过
（意图/引用/转人工/拦截/无幻觉红线），防止后续改动导致评分回退。

注意：LLM 侧测试消耗 API 额度，默认跳过；设 RUN_LLM_EVAL=1 且 .env 配好
DEEPSEEK_API_KEY 才跑。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import pytest

from scripts.llm_eval import load_golden, run_case


def test_golden_set_complete():
    """golden 集非空且每 case 结构合法（input/role/expect）。"""
    cases = load_golden()
    assert len(cases) >= 20, "评测集应不少于 20 条"
    for c in cases:
        assert c.get("input") and c.get("role") in ("resident", "elderly", "grid")
        assert isinstance(c.get("expect"), dict)
        expect = c["expect"]
        assert any(k in expect for k in ("intent", "contains", "handoff", "blocked"))


def test_rule_engine_pass_rate():
    """规则引擎跑分：满分通过率 ≥ 95%（接入 LLM 后此基线保护规则引擎质量）。"""
    cases = load_golden()
    full = sum(1 for c in cases if run_case(c)[0]["score"] >= 1.0)
    rate = full * 100 / len(cases)
    assert rate >= 95, f"规则引擎满分通过率 {rate:.1f}% < 95%（{full}/{len(cases)}）"


@pytest.mark.skipif(not os.environ.get("RUN_LLM_EVAL"),
                    reason="需显式设置 RUN_LLM_EVAL=1 才跑真实 LLM（消耗 API 额度）")
def test_llm_pass_rate():
    """真实 LLM 跑分（DeepSeek）：满分通过率 ≥ 90%（默认跳过）。"""
    import config
    if not config.DEEPSEEK_API_KEY:
        pytest.skip("未配置 DEEPSEEK_API_KEY")
    from scripts.llm_eval import run_case_llm
    cases = load_golden()
    full = sum(1 for c in cases if run_case_llm(c)[0]["score"] >= 1.0)
    rate = full * 100 / len(cases)
    assert rate >= 90, f"LLM 满分通过率 {rate:.1f}% < 90%（{full}/{len(cases)}）"
