# -*- coding: utf-8 -*-
"""WS7.2：离线金标评测（规则意图管线 + Verifier），纳入 pytest / CI。

真实分母 = golden JSONL 用例数（可随数据扩量自动增长）。规则引擎确定性，金标应全对；
阈值设 0.9 留裕量，防止在 pipeline 演进时脆断。
本测试只在离线规则层跑，不触发 LLM（避免 CI flaky）。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile  # noqa: E402
import config  # noqa: E402

config.DB_PATH = os.path.join(tempfile.mkdtemp(prefix="golden_"), "g.db")
from data.db_core import init_db  # noqa: E402
init_db(config.DB_PATH)

_GOLDEN_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent", "eval", "golden")
INTENT_ACC_THRESHOLD = 0.9
VERIFIER_ACC_THRESHOLD = 0.9


def _load(name):
    path = os.path.join(_GOLDEN_DIR, name)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_golden_intent_accuracy():
    """规则意图管线对金标的识别准确率 ≥ 阈值。分母为真实金标数。"""
    from agent import web_agent as A
    cases = _load("intent_rules.jsonl")
    assert cases, "缺少 intent_rules.jsonl 金标"
    def _expected(intent):
        return None if intent in ("unknown", "", None) else intent

    correct = sum(1 for c in cases if A.detect_intent(c["text"], "resident") == _expected(c["intent"]))
    acc = correct / len(cases)
    assert acc >= INTENT_ACC_THRESHOLD, f"意图准确率 {acc:.3f} < {INTENT_ACC_THRESHOLD}（{correct}/{len(cases)}）"


def test_golden_verifier_accuracy():
    """Verifier 对金标的 block/pass 判定准确率 ≥ 阈值。分母为真实金标数。"""
    from agent.verifier import Verifier
    v = Verifier()
    cases = _load("verifier_rules.jsonl")
    assert cases, "缺少 verifier_rules.jsonl 金标"
    correct = 0
    for c in cases:
        got = v.verify({"reply": c["reply"]}, c["biz"])["verdict"]
        if got == c["verdict"]:
            correct += 1
    acc = correct / len(cases)
    assert acc >= VERIFIER_ACC_THRESHOLD, f"Verifier 准确率 {acc:.3f} < {VERIFIER_ACC_THRESHOLD}（{correct}/{len(cases)}）"
