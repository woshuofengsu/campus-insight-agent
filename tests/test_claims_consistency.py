# -*- coding: utf-8 -*-
"""对外数字与材料措辞一致性（CI 友好版，秒级）。

背景：评委最容易查的就是数字。历史上有过「材料写 328 测试 / schema v41，代码已是别的版本」这类漂移，
第七轮复审也见过「登录页自转率 62% 与后端口径对不上」。这里把三件事钉进 CI：

  1. 登录页 `web/src/config/meta.js` 的数字必须是正整数，且 agent/知识集等**可核对项**与实测一致；
  2. 「当前状态文档」不得出现已过时的表述（旧版本号/旧测试数/旧架构词）；
  3. 历史文档（原型阶段）必须带「历史实现」标注，避免误导评委。

完整的实时核对（含 pytest 收集数、路由数、表数）由 `python scripts/check_claims.py` 承担，
并在 `demo_preflight` 的演示前自检里跑。
"""
import io
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import check_claims as C

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_current_docs_have_no_stale_wording():
    """当前状态文档不得含过时表述（旧 schema 版本 / 旧测试数 / 旧架构词）。"""
    hits = []
    for doc in C.CURRENT_DOCS:
        p = os.path.join(PROJ, doc)
        if not os.path.exists(p):
            continue
        for i, ln in enumerate(io.open(p, encoding="utf-8").read().splitlines(), 1):
            for s in C.STALE:
                if s in ln:
                    hits.append(f"{doc}:{i} 「{s}」")
                    break
    assert not hits, "当前状态文档出现过时表述：\n  " + "\n  ".join(hits)


def test_legacy_docs_are_banner_labeled():
    """历史实现文档必须标注，否则读者会拿原型阶段数字当现状。"""
    for doc, banner in C.LEGACY_BANNER_DOCS.items():
        p = os.path.join(PROJ, doc)
        if not os.path.exists(p):
            continue
        assert banner in io.open(p, encoding="utf-8").read()[:1500], \
            f"{doc} 缺少「{banner}」标注"


def test_meta_js_is_wellformed_and_matches_checkable_facts():
    """登录页数字来源可解析，且可核对项与实测一致（rag_golden / agents）。"""
    from scripts import demo_preflight as P
    declared = P.parse_brand_metrics()
    assert declared, "meta.js 应至少声明一项指标"

    from scripts.rag_eval import load_golden
    assert declared["rag_golden"] == len(load_golden()), \
        f"登录页写 {declared['rag_golden']} 条评测集，实测 {len(load_golden())} 条"

    from agent.roles import AGENT_CLASSES
    assert declared["agents"] == len(AGENT_CLASSES), \
        f"登录页写 {declared['agents']} 个角色，实测 {len(AGENT_CLASSES)} 个"

    # tests 必须是正整数（其精确值由 demo_preflight / check_claims 用 --collect-only 核对）
    assert isinstance(declared["tests"], int) and declared["tests"] > 0


def test_doc_test_numbers_match_single_source():
    """**主文档**里的测试数必须与其口径匹配（不是"落在某个集合里"就算过）。

    只查「评委当成现状来读」的四份主文档（README / AGENTS / 最终版交付说明 / 创意说明书-提交版）；
    CHANGELOG、HANDOFF、dev-log、技术报告正文等属于历史或日志，其中的旧数字是当时事实，不应改写。

    为什么按口径分别校验：实测踩过两次坑——① 批量改总数后正文仍写「571 通过」；
    ② 同步脚本把「N passed」也替换成可运行数，产出「577 passed（可运行 576）」这种**互换**。
    """
    from scripts import demo_preflight as P
    runnable = P.parse_brand_metrics()["tests"]
    primary = [
        "README.md", "AGENTS.md",
        "docs/competition/最终版交付说明.md", "docs/competition/创意说明书-提交版.md",
    ]
    RULES = [
        (re.compile(r"\b(\d{3})\s*passed"), runnable - 1, "passed 应=可运行数−1"),
        (re.compile(r"\b(\d{3})\s*通过"), runnable - 1, "「N 通过」应=可运行数−1"),
        (re.compile(r"可运行\s*(\d{3})"), runnable, "「可运行 N」应=可运行数"),
        (re.compile(r"\b(\d{3})\s*(?:项\s*)?(?:自动化\s*)?测试"), runnable, "「N 项测试」应=可运行数"),
    ]
    bad = []
    for doc in primary:
        p = os.path.join(PROJ, doc)
        if not os.path.exists(p):
            continue
        for i, ln in enumerate(io.open(p, encoding="utf-8").read().splitlines(), 1):
            for pat, want, why in RULES:
                for m in pat.finditer(ln):
                    if int(m.group(1)) != want:
                        bad.append(f"{doc}:{i} 出现 {m.group(1)}，应为 {want}（{why}）→ {ln.strip()[:60]}")
    assert not bad, "主文档测试数与口径不一致：\n  " + "\n  ".join(bad)


def test_final_delivery_doc_exists_and_covers_key_gates():
    """最终版交付说明必须存在，且覆盖「怎么跑 / 怎么验 / 怎么讲」三类信息。"""
    p = os.path.join(PROJ, "docs", "competition", "最终版交付说明.md")
    assert os.path.exists(p), "缺少 docs/competition/最终版交付说明.md"
    text = io.open(p, encoding="utf-8").read()
    for needle in ("uvicorn api_web:app", "demo_preflight.py", "ui_audit.py",
                   "check_claims.py", "demo_resident", "已知边界"):
        assert needle in text, f"交付说明缺少关键信息：{needle}"
    # 文档里的测试数字必须与 meta.js 口径一致（防交付说明自己写漂）
    m = re.search(r"(\d+)\s*(?:项)?\s*(?:自动化)?测试", text)
    assert m, "交付说明应写明测试规模"
