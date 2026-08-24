# -*- coding: utf-8 -*-
"""评测方法论回归测试：评分脚本可复算 + 历史对照不变（防基线被破坏）。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.review_score import compute, HISTORY


def test_v3_score_recomputable():
    """V3 总分可复算 = 8.35 / A-（LLM 实测闭环后 L 风险 -0.2）。"""
    total, grade = compute(HISTORY["V3"]["scores"], HISTORY["V3"]["risk"])
    assert total == 8.35
    assert grade == "A-"


def test_score_progression():
    """V1 < V2 < V3 单调上升（评审闭环的证据链）。"""
    totals = [compute(h["scores"], h["risk"])[0] for h in HISTORY.values()]
    assert totals[0] < totals[1] < totals[2]


def test_dimension_count():
    """A-K 共 11 维 + L 风险扣分，权重合计 100%。"""
    from scripts.review_score import DIMENSIONS
    assert len(DIMENSIONS) == 11
    assert abs(sum(w for _, w in DIMENSIONS) - 1.0) < 1e-9
