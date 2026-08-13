# agent/eval/eval_suite.py
"""Agent 竞争力评测 — 意图路由命中率 + 幻觉率（默认离线，不依赖 LLM）。

三分类场景：
  1. standard  常见说法的意图路由
  2. unseen    未写进触发词的变体说法（验证语义路由覆盖长尾）
  3. 事实校验  回复里引用不存在的 #编号（验证 verify_facts 兜底）

运行：python -m agent.eval.eval_suite
指标：工具命中率（期望工具 == 路由工具）、幻觉检出率。
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))


# (category, input, expected_tool)
SCENARIOS: list[tuple[str, str, str]] = [
    # ── standard：常见说法 ──
    ("standard", "3号楼电梯困人了", "report_issue"),
    ("standard", "社区脉搏", "get_community_pulse"),
    ("standard", "今天天气怎么样", "get_weather"),
    ("standard", "看看有哪些提案", "get_proposals"),
    ("standard", "我建议加装充电桩", "create_proposal"),
    ("standard", "我的工单进展如何", "query_my_issues"),
    ("standard", "统计一下解决率", "get_governance_stats"),
    # ── unseen：变体说法（触发词表里没有的字面） ──
    ("unseen", "我家楼道灯忽闪忽闪的", "report_issue"),
    ("unseen", "车轱辘陷坑里了", "report_issue"),
    ("unseen", "电梯一开一合吱吱响", "report_issue"),
    ("unseen", "楼下的井盖松了", "report_issue"),
    ("unseen", "小区晚上有只狗一直叫", "report_issue"),
    ("unseen", "水龙头拧不紧了", "report_issue"),
    ("unseen", "隔壁装修吵得睡不着", "report_issue"),
    ("unseen", "想看看最近小区有啥新鲜事", "get_community_pulse"),
]


def _fact_check_cases() -> list[tuple[str, list[int]]]:
    """(response, expected_bad_ids)"""
    return [
        ("已为你生成工单 #12345，请留意处理。", [12345]),      # 幻觉号
        ("你的工单 #1 进展正常。", []),                        # 假设 #1 存在
        ("提案 #99999 已采纳。", [99999]),
    ]


def run_eval(offline: bool = True) -> dict:
    """Run intent-routing evaluation. offline=True 只走关键词层，不调 LLM。"""
    from agent.router import _keyword_route, route_intent

    results = []
    keyword_hits = 0
    full_hits = 0
    for category, text, expected in SCENARIOS:
        kw_tool, kw_conf = _keyword_route(text)
        kw_hit = kw_tool == expected
        if offline:
            full_tool, method = kw_tool, ("keyword" if kw_tool else "none")
        else:
            full = route_intent(text)
            full_tool, method = full["tool"], full["method"]
        full_hit = full_tool == expected
        keyword_hits += int(kw_hit)
        full_hits += int(full_hit)
        results.append({
            "category": category, "text": text, "expected": expected,
            "keyword_tool": kw_tool, "keyword_hit": kw_hit,
            "full_tool": full_tool, "full_hit": full_hit, "method": method,
        })

    total = len(SCENARIOS)
    return {
        "total": total,
        "keyword_hit_rate": round(keyword_hits / total * 100, 1),
        "full_hit_rate": round(full_hits / total * 100, 1),
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
    cases = _fact_check_cases()
    for response, expected_bad in cases:
        out = verify_facts(response)
        total_bad += len(expected_bad)
        for bad_id in expected_bad:
            if f"#{bad_id}" in out and "核对提示" in out:
                detected += 1

    # 真实 id 不应被误判
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
    lines.append(f"- 场景总数：{eval_result['total']}")
    lines.append(f"- 关键词路由命中率：{eval_result['keyword_hit_rate']}%")
    lines.append(f"- 完整路由命中率：{eval_result['full_hit_rate']}%")
    lines.append(f"- 幻觉编号检出率：{fact_result['detection_rate']}%"
                 f"（{fact_result['detected']}/{fact_result['bad_cases']}）")
    lines.append(f"- 真实编号误判：{'是 [WARN]' if fact_result['false_positive_on_real_id'] else '否 [OK]'}")
    lines.append("")
    lines.append("| 分类 | 输入 | 期望 | 关键词命中 | 完整命中 |")
    lines.append("|---|---|---|---|---|")
    for r in eval_result["results"]:
        lines.append(
            f"| {r['category']} | {r['text']} | {r['expected']} "
            f"| {'OK' if r['keyword_hit'] else 'MISS'} "
            f"| {'OK' if r['full_hit'] else 'MISS'} |"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    e = run_eval(offline=True)
    f = run_fact_check_eval()
    print(_render_report(e, f))
