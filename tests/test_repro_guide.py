# -*- coding: utf-8 -*-
"""复现指南与现实一致性门禁（卡14：文档、演示和可复现交付）。

**为什么要有这个测试**：复现指南最容易"写完就过期"——文档里写着 819 项测试，
实际早就 900+；写着"跑 ui_audit 即可"，但没提"必须先 build / 服务必须在跑"。
这类文档比没有文档更坏：**别人照着做会得到相反结论**。所以把关键数字与关键陷阱都钉进测试。
"""
import io
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUIDE = os.path.join(ROOT, "docs", "复现指南.md")


def _guide() -> str:
    assert os.path.isfile(GUIDE), "缺少 docs/复现指南.md（卡14 要求：他人能按文档复现核心链路）"
    return io.open(GUIDE, encoding="utf-8").read()


def _meta_tests() -> int:
    src = io.open(os.path.join(ROOT, "web", "src", "config", "meta.js"), encoding="utf-8").read()
    m = re.search(r"key:\s*'tests',\s*value:\s*(\d+)", src)
    assert m, "meta.js 里读不到测试数（它是唯一来源）"
    return int(m.group(1))


def test_guide_documents_the_key_commands():
    """指南必须给出**真正能跑**的命令（不是"参考某某脚本"）。"""
    g = _guide()
    for cmd in ("python -m pytest tests/ -q", "python -m ruff check .",
                "python scripts/check_claims.py", "python scripts/demo_preflight.py --fast",
                "python scripts/ui_audit.py", "python scripts/mobile_flow_check.py",
                "python scripts/eval_all.py", "python scripts/freeze_eval_corpus.py --check"):
        assert cmd in g, f"复现指南缺少命令：{cmd}"


def test_guide_warns_about_the_two_traps():
    """两个「照着做会得出相反结论」的坑必须写清楚：服务开关与 dist 构建。"""
    g = _guide()
    assert "先停掉" in g and "pytest" in g, "没写「跑测试前要停服务」这个坑"
    assert "npm run build" in g and "旧包" in g, "没写「改前端必须先构建，否则审计测的是旧包」"


def test_guide_test_count_matches_reality():
    """指南里的测试数必须与 meta.js（唯一来源）一致。

    口径（与 `scripts/sync_test_count.py` 一致）：meta.js 存的是**可运行**总数，
    其中 1 项需要外部服务默认跳过，所以"通过数 = 可运行数 − 1"。
    """
    g = _guide()
    n = _meta_tests()
    assert f"{n - 1} passed" in g, f"复现指南里的通过数不是当前的 {n - 1}（文档会骗人）"
    assert f"{n}" in g, f"复现指南没写可运行总数 {n}"


def test_guide_eval_numbers_match_report():
    """指南里的评测数字必须与 `docs/eval/eval-report.md` 一致（别手抄一个旧的）。"""
    g = _guide()
    rp = os.path.join(ROOT, "docs", "eval", "eval-report.md")
    assert os.path.isfile(rp), "缺少评测报告（卡13 的留档）"
    report = io.open(rp, encoding="utf-8").read()
    # 报告里的语料指纹要出现在指南里（说明"数字是在哪批语料上测的"）
    m = re.search(r"指纹 `([0-9a-f]+)`", report)
    assert m, "评测报告里没有语料指纹"
    assert m.group(1) in g, "复现指南没写评测用的语料指纹（读者无法确认数字可比）"
    # 金标条数也要一致
    mc = re.search(r"用例：(\d+) 条", report)
    if mc:
        assert f"{mc.group(1)} 条" in g, f"指南里的金标条数不是报告里的 {mc.group(1)}"


def test_guide_mentions_tenant_probes_and_schema_version():
    """多租户探针与 schema 版本是"能不能信"的关键信息，必须在指南里。"""
    g = _guide()
    assert "probe_tenant_isolation.py" in g and "probe_tenant_settings.py" in g
    from data import db_core
    src = io.open(os.path.join(ROOT, "data", "db_core.py"), encoding="utf-8").read()
    versions = [int(v) for v in re.findall(r"\((\d+),\s*\"[a-z_]+\",\s*_m\d+", src)]
    latest = max(versions) if versions else 0
    assert f"schema v{latest}" in g, f"指南里的 schema 版本不是最新的 v{latest}"


def test_guide_covers_the_three_portals_walkthrough():
    """三端核心链路要能手动走一遍（卡14 的"他人可复现"要求）。"""
    g = _guide()
    for kw in ("居民", "网格员", "老年"):
        assert kw in g
    # 关键可信度行为也要写进复现步骤（缺位置不建单 / 结果未知 / 超时明说）
    assert "不建单" in g and "超时" in g


def test_eval_report_is_committed_with_negative_section():
    """评测报告要留档，且**必须带"负收益/变差"这一节**（只报涨的不算报告）。"""
    rp = os.path.join(ROOT, "docs", "eval", "eval-report.md")
    report = io.open(rp, encoding="utf-8").read()
    assert "负收益对照" in report or "变差" in report
    assert "holdout" in report, "报告必须单列留出集"
    js = os.path.join(ROOT, "docs", "eval", "eval-report.json")
    data = json.load(io.open(js, encoding="utf-8"))
    for key in ("corpus", "rag", "rag_lexical_only", "compare"):
        assert key in data, f"评测报告 JSON 缺字段：{key}"
