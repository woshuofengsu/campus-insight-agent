# agent/eval/eval_suite.py
"""Agent 竞争力评测 — 意图路由命中率（关键词 vs LLM 泛化）+ 幻觉检出率。

三组场景：
  1. standard 常见说法（关键词表内，验证保底）
  2. unseen   变体说法（部分在表内，验证覆盖）
  3. generic  关键词表外的全新说法（只有 LLM 语义能判，验证真实泛化）

运行：
  python -m agent.eval.eval_suite                 # 关键词版（离线，零成本）
  python -m agent.eval.eval_suite --mode llm      # LLM 版（有 key，测真实泛化）
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


SCENARIOS: list[tuple[str, str, str]] = [
    # ── standard：常见说法（关键词表内） ──
    ("standard", "3号楼电梯困人了", "report_issue"),
    ("standard", "社区脉搏", "get_community_pulse"),
    ("standard", "今天天气怎么样", "get_weather"),
    ("standard", "看看有哪些提案", "get_proposals"),
    ("standard", "我的工单进展如何", "query_my_issues"),
    ("standard", "统计一下解决率", "get_governance_stats"),
    # ── unseen：变体说法（部分在表内） ──
    ("unseen", "我家楼道灯忽闪忽闪的", "report_issue"),
    ("unseen", "车轱辘陷坑里了", "report_issue"),
    ("unseen", "电梯一开一合吱吱响", "report_issue"),
    ("unseen", "水龙头拧不紧了", "report_issue"),
    ("unseen", "想看看最近小区有啥新鲜事", "get_community_pulse"),
    # ── generic：关键词表外的全新说法（只有 LLM 语义能判） ──
    ("generic", "我家门口地砖翘起来了", "report_issue"),
    ("generic", "楼道里老有股难闻的味", "report_issue"),
    ("generic", "小区喷水池不喷了", "report_issue"),
    ("generic", "单元门锁舌卡住开不了", "report_issue"),
    ("generic", "绿化带被人搭了棚子", "report_issue"),
    ("generic", "消防通道被一辆车堵死了", "report_issue"),
    ("generic", "活动室乒乓球桌腿断了", "report_issue"),
    ("generic", "想看看大家最近都在聊什么", "get_topics"),
]


def _fact_check_cases() -> list[tuple[str, list[int]]]:
    """(response, expected_bad_ids)"""
    return [
        ("已为你生成工单 #12345，请留意处理。", [12345]),
        ("你的工单 #1 进展正常。", []),
        ("提案 #99999 已采纳。", [99999]),
    ]


def run_eval(mode: str = "keyword") -> dict:
    """Run intent-routing evaluation.

    mode="keyword" 只走关键词层（离线，零成本）；
    mode="llm" 走完整 route_intent（LLM 主决策 + 关键词兜底）。
    """
    from agent.router import _keyword_route, route_intent

    results = []
    for category, text, expected in SCENARIOS:
        kw_tool, _ = _keyword_route(text)
        kw_hit = kw_tool == expected
        if mode == "llm":
            full = route_intent(text)
            full_tool, method = full["tool"], full["method"]
        else:
            full_tool, method = kw_tool, ("keyword" if kw_tool else "none")
        full_hit = full_tool == expected
        results.append({
            "category": category, "text": text, "expected": expected,
            "keyword_hit": kw_hit, "full_hit": full_hit, "method": method,
        })

    def _rate(cat: str, field: str) -> float:
        rows = [r for r in results if r["category"] == cat]
        if not rows:
            return 0.0
        return round(sum(1 for r in rows if r[field]) / len(rows) * 100, 1)

    total = len(results)
    return {
        "total": total,
        "keyword_hit_rate": round(sum(1 for r in results if r["keyword_hit"]) / total * 100, 1),
        "full_hit_rate": round(sum(1 for r in results if r["full_hit"]) / total * 100, 1),
        "by_category": {
            cat: {"keyword": _rate(cat, "keyword_hit"), "full": _rate(cat, "full_hit")}
            for cat in ("standard", "unseen", "generic")
        },
        "results": results,
    }


def run_fact_check_eval() -> dict:
    """Run fact-verification evaluation against a temp DB seeded with issue #1."""
    import tempfile
    from data.db_core import init_db
    from data.db_governance import report_issue
    from agent.verifier import verify_facts

    db_path = tempfile.mktemp(suffix=".db")
    init_db(db_path)
    real_id = report_issue("真实工单", "设施维修", urgency="普通", reporter_id=1)

    detected = 0
    total_bad = 0
    for response, expected_bad in _fact_check_cases():
        out = verify_facts(response)
        total_bad += len(expected_bad)
        for bad_id in expected_bad:
            if f"#{bad_id}" in out and "核对提示" in out:
                detected += 1

    false_positive = "核对提示" in verify_facts(f"工单 #{real_id} 已处理。")
    os.unlink(db_path)
    return {
        "bad_cases": total_bad,
        "detected": detected,
        "detection_rate": round(detected / total_bad * 100, 1) if total_bad else None,
        "false_positive_on_real_id": false_positive,
    }


def _render_report(eval_result: dict, fact_result: dict) -> str:
    lines = ["# Agent 竞争力评测报告", ""]
    lines.append(f"- 场景总数：{eval_result['total']}（standard / unseen / generic）")
    lines.append(f"- 关键词兜底命中率：{eval_result['keyword_hit_rate']}%")
    lines.append(f"- 完整路由命中率：{eval_result['full_hit_rate']}%")
    lines.append("")
    lines.append("| 分组 | 关键词命中 | 完整命中 |")
    lines.append("|---|---|---|")
    for cat in ("standard", "unseen", "generic"):
        c = eval_result["by_category"][cat]
        lines.append(f"| {cat} | {c['keyword']}% | {c['full']}% |")
    lines.append("")
    lines.append(f"- 幻觉编号检出率：{fact_result['detection_rate']}%"
                 f"（{fact_result['detected']}/{fact_result['bad_cases']}）")
    lines.append(f"- 真实编号误判：{'是 [WARN]' if fact_result['false_positive_on_real_id'] else '否 [OK]'}")
    lines.append("")
    lines.append("| 分类 | 输入 | 期望 | 关键词 | 完整 |")
    lines.append("|---|---|---|---|---|")
    for r in eval_result["results"]:
        lines.append(
            f"| {r['category']} | {r['text']} | {r['expected']} "
            f"| {'OK' if r['keyword_hit'] else 'MISS'} "
            f"| {'OK' if r['full_hit'] else 'MISS'} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mode = "llm" if "--mode" in sys.argv and "llm" in sys.argv else "keyword"
    e = run_eval(mode=mode)
    f = run_fact_check_eval()
    print(_render_report(e, f))
