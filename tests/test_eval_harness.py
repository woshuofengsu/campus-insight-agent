# -*- coding: utf-8 -*-
"""评测基础件（卡13）：语料指纹 / 确定性留出集 / **负收益对比**。

为什么值得单独测：这三个东西是"评测数字可不可信"的地基 ——
如果留出集每次切得不一样、或者对比函数只报涨不报跌，报告就会好看但没用。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.eval_split import (HOLDOUT_RATIO, compare, corpus_digest,  # noqa: E402
                              diff_corpus, metrics_for_split, rate, split_cases)


# ---------------------------------------------------------------- 语料指纹

def test_digest_is_order_insensitive():
    """指纹与顺序无关（同批语料换个顺序 → 同一指纹），否则"分母固定"就无从谈起。"""
    rows = [{"id": 1, "title": "A", "content_sha1": "x"},
            {"id": 2, "title": "B", "content_sha1": "y"}]
    assert corpus_digest(rows) == corpus_digest(list(reversed(rows)))


def test_digest_changes_when_content_changes():
    before = [{"id": 1, "title": "A", "content_sha1": "x"}]
    after = [{"id": 1, "title": "A", "content_sha1": "z"}]
    assert corpus_digest(before) != corpus_digest(after), "正文指纹变了，整批指纹必须变"


def test_diff_corpus_reports_all_three_kinds():
    """漂移要分清"新增 / 删除 / 内容被改"三类（评测数字变化的原因要能说清）。"""
    before = [{"id": 1, "title": "A", "keywords": "k"},
              {"id": 2, "title": "B", "keywords": "k"},
              {"id": 3, "title": "C", "keywords": "k"}]
    after = [{"id": 1, "title": "A", "keywords": "改了"},
             {"id": 3, "title": "C", "keywords": "k"},
             {"id": 4, "title": "D", "keywords": "k"}]
    d = diff_corpus(before, after)
    assert d["added"] == [4] and d["removed"] == [2]
    assert [c["id"] for c in d["changed"]] == [1] and d["same"] is False


def test_diff_corpus_same_corpus():
    rows = [{"id": 1, "title": "A"}]
    assert diff_corpus(rows, rows)["same"] is True


# ---------------------------------------------------------------- 留出集

def test_split_is_deterministic():
    """同一份数据每次切法必须一致（否则"留出集"会悄悄混进调参用过的句子）。"""
    cases = [{"query": f"问题{i}"} for i in range(50)]
    a = split_cases(cases)
    b = split_cases(cases)
    assert [c["query"] for c in a["dev"]] == [c["query"] for c in b["dev"]]
    assert [c["query"] for c in a["holdout"]] == [c["query"] for c in b["holdout"]]


def test_split_covers_all_cases_and_roughly_follows_ratio():
    cases = [{"query": f"查询{i}"} for i in range(200)]
    sp = split_cases(cases)
    assert sp["dev_n"] + sp["holdout_n"] == 200, "切分不能丢用例"
    assert 0.15 < sp["holdout_n"] / 200 < 0.5, f"留出集比例异常：{sp['holdout_n']}/200"


def test_split_stable_when_cases_are_inserted():
    """插入新用例**不该挪动**老用例的分区（按顺序切就会全挪）。"""
    base = [{"query": f"q{i}"} for i in range(60)]
    before_holdout = {c["query"] for c in split_cases(base)["holdout"]}
    grown = base + [{"query": "新增的问题"}]
    after_holdout = {c["query"] for c in split_cases(grown)["holdout"]}
    assert before_holdout <= after_holdout, "老用例的分区被挪动了：留出集不再可信"


def test_metrics_for_split_uses_two_denominators():
    """dev / holdout 必须是**两个分母**各自算，不能只报一个总命中率。"""
    cases = [{"query": f"q{i}"} for i in range(40)]
    sp = split_cases(cases)
    holdout_q = {c["query"] for c in sp["holdout"]}
    # 构造：holdout 全命中、dev 全不中 → 总命中率与 dev 应有明显差异
    details = [{"query": c["query"], "hit": c["query"] in holdout_q,
                "hit_at_1": c["query"] in holdout_q} for c in cases]
    m = metrics_for_split(details, cases)
    assert m["all"]["n"] == 40
    assert m["holdout"]["hit_rate"] == 100.0
    assert m["dev"]["hit_rate"] == 0.0
    assert m["dev"]["n"] + m["holdout"]["n"] == 40


# ---------------------------------------------------------------- 负收益

def _details(pairs):
    return {"details": [{"query": q, "hit": h, "hit_at_1": h} for q, h in pairs]}


def test_compare_reports_regressions_not_only_gains():
    """**核心**：变差的条目必须单独列出来（只报涨的那版就是自欺）。"""
    baseline = _details([("a", True), ("b", True), ("c", False)])
    variant = _details([("a", True), ("b", False), ("c", True), ("d", True)])
    r = compare(baseline, variant)
    assert r["better_n"] == 1 and r["worse_n"] == 1
    assert r["worse"][0]["query"] == "b"
    # 总体：2/3=66.7% → 3/4=75.0%（+8.3）—— 整体变好，但**必须同时说清有 1 条变差**
    assert r["delta"] == 8.3 and r["verdict"] == "变好"
    assert r["has_regressions"] is True and "变差" in r["note"]
    assert r["baseline_hit_rate"] == 66.7 and r["variant_hit_rate"] == 75.0


def test_compare_says_worse_when_it_is_worse():
    baseline = _details([("a", True), ("b", True)])
    variant = _details([("a", False), ("b", False)])
    r = compare(baseline, variant)
    assert r["delta"] == -100.0 and "变差" in r["verdict"]


def test_rate_handles_empty():
    assert rate([]) == 0.0 and rate([{"hit": True}]) == 100.0


def test_holdout_ratio_is_documented():
    """留出集比例是个**口径**，不能随便改（改了就得在报告里说明）。"""
    assert 0.2 <= HOLDOUT_RATIO <= 0.4


def test_snapshot_files_exist():
    """评测要用的两份固定输入必须在仓库里（金标用例 + 语料快照）。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in (os.path.join("tests", "llm_eval", "rag_golden.jsonl"),
                os.path.join("tests", "llm_eval", "corpus_snapshot.json")):
        assert os.path.isfile(os.path.join(root, rel)), f"缺少评测固定输入：{rel}"
