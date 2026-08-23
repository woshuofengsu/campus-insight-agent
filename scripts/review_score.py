# scripts/review_score.py — 全维度评测评分（可复用，P 级评审方法论）
# -*- coding: utf-8 -*-
"""12 维度加权评分：复算《项目质量检测报告》总分与等级。

用法：
  python scripts/review_score.py                          # 交互输入 12 维分数
  python scripts/review_score.py --scores 8.5 9.5 8.5 7.5 8.5 9.5 8.0 8.3 7.8 8.8 7.0 --risk -0.3
  python scripts/review_score.py --history                # 显示 V1/V2/V3 历史对照

评分方法论见 docs/review/评测方法论.md。
"""
import argparse
import json
import sys

# 12 维度（名称, 权重）；L 为风险扣分（-10~0，不进权重）
DIMENSIONS = [
    ("A. Agent 架构设计", 0.18),
    ("B. 业务闭环完整性", 0.18),
    ("C. Agent 能力质量", 0.15),
    ("D. 数据与智能", 0.10),
    ("E. 用户体验", 0.08),
    ("F. 工程质量与部署", 0.08),
    ("G. 安全与合规", 0.06),
    ("H. 成本与性能", 0.05),
    ("I. 产品价值与竞争力", 0.05),
    ("J. 演示与表达", 0.04),
    ("K. 团队与执行", 0.03),
]

# 历史对照（评审日期, 各维分数, 风险扣分, 总分）
HISTORY = {
    "V1": {"date": "2026-07", "scores": [6.5, 8.5, 7.0, 6.5, 8.0, 7.5, 6.0, 7.5, 7.0, 8.0, 6.0], "risk": -0.2},
    "V2": {"date": "2026-08", "scores": [8.0, 9.0, 7.5, 7.0, 8.3, 8.0, 7.0, 8.0, 7.5, 8.5, 6.5], "risk": -0.3},
    "V3": {"date": "2026-08", "scores": [8.5, 9.5, 8.5, 7.5, 8.5, 9.5, 8.0, 8.3, 7.8, 8.8, 7.0], "risk": -0.3},
}


def compute(scores: list[float], risk: float = 0.0) -> tuple[float, str]:
    """计算加权总分与等级。scores 长度须为 11（A-K），risk 为 L 扣分。"""
    if len(scores) != len(DIMENSIONS):
        raise ValueError(f"scores 需要 {len(DIMENSIONS)} 个（A-K），实际 {len(scores)}")
    total = sum(s * w for s, (_, w) in zip(scores, DIMENSIONS)) + risk
    if total >= 9.0:
        grade = "S"
    elif total >= 8.0:
        grade = "A-"
    elif total >= 7.5:
        grade = "B+"
    elif total >= 7.0:
        grade = "B"
    elif total >= 6.0:
        grade = "C"
    else:
        grade = "D"
    return round(total, 2), grade


def fmt_radar(scores: list[float]) -> str:
    """雷达图 ASCII（10 满）。"""
    names = ["业务", "工程", "演示", "Agent", "体验", "能力", "成本", "安全", "价值", "数据", "团队"]
    lines = []
    for n, s in zip(names, [scores[1], scores[5], scores[9], scores[0], scores[4], scores[2],
                            scores[7], scores[6], scores[8], scores[3], scores[10]]):
        bar = "█" * int(s) + ("▌" if s - int(s) >= 0.5 else "")
        lines.append(f"{n} {s} {bar}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="12 维度加权评分（A-K + L 风险扣分）")
    ap.add_argument("--scores", nargs="+", type=float, help="A-K 共 11 个维度分（0-10）")
    ap.add_argument("--risk", type=float, default=0.0, help="L 风险扣分（-10~0，默认 0）")
    ap.add_argument("--history", action="store_true", help="显示历史对照")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    args = ap.parse_args()

    if args.history:
        rows = []
        for ver, h in HISTORY.items():
            total, grade = compute(h["scores"], h["risk"])
            rows.append({"version": ver, "date": h["date"], "total": total, "grade": grade})
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print("=== 历次全维度评分对照 ===")
            for r in rows:
                print(f"  {r['version']}（{r['date']}）：{r['total']} / {r['grade']}")
        return

    scores = args.scores
    if not scores:
        scores = []
        for name, _w in DIMENSIONS:
            v = input(f"{name}（0-10，回车默认 7.0）：").strip()
            scores.append(float(v) if v else 7.0)
    try:
        total, grade = compute(scores, args.risk)
    except ValueError as e:
        print(f"错误：{e}")
        sys.exit(1)
    if args.json:
        print(json.dumps({"total": total, "grade": grade,
                          "scores": dict(zip([d[0] for d in DIMENSIONS], scores)),
                          "risk": args.risk}, ensure_ascii=False, indent=2))
    else:
        print("=== 全维度评分 ===")
        for (name, w), s in zip(DIMENSIONS, scores):
            print(f"  {name}: {s}（权重 {w*100:.0f}%）")
        print(f"  L. 风险扣分: {args.risk}")
        print(f"  总分: {total} / 10 —— {grade} 级")
        print("  雷达（10 满）：")
        print(fmt_radar(scores))


if __name__ == "__main__":
    main()
