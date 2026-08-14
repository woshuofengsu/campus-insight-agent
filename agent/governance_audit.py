# agent/governance_audit.py
"""治理审计 —— 跨表体检报告卡。

审四个维度（工单管理、提案参与、公民参与、热点）。
评分规则：解决率基准 80%，紧急未处理每条扣 5 分（上限 25），
SLA 超时每条扣 3 分（上限 20），待回复提案每条扣 8 分（上限 40），
采纳率有加分，参与人数有下限。
"""
import logging
from data.database import get_db, compute_health_score

_log = logging.getLogger(__name__)


def run_governance_audit() -> str:
    """跨表跑一轮治理审计，返回 markdown 报告。"""
    try:
        health = compute_health_score()
        resolution_rate = health["resolution_rate"]
        avg_resolution_days = health["avg_days"]

        lines: list[str] = []
        grades: dict[str, dict] = {}

        with get_db() as conn:
            # 1. 工单管理
            issue_summary = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM community_issues GROUP BY status"
            ).fetchall()
            total_i = sum(r["cnt"] for r in issue_summary)
            by_status = {r["status"]: r["cnt"] for r in issue_summary}
            pending = by_status.get("待处理", 0)
            processing = by_status.get("处理中", 0)
            resolved = by_status.get("已解决", 0)

            from data.db_sla import get_sla_summary
            _sla = get_sla_summary()
            urgent_unresolved = _sla.get("urgent_pending", 0)
            stale_count = _sla.get("total_overdue", 0)

            issue_score = 100.0
            if total_i > 0:
                issue_score -= max(0, (1 - resolution_rate / 80) * 30)
            if urgent_unresolved > 0:
                issue_score -= min(urgent_unresolved * 5, 25)
            if stale_count > 0:
                issue_score -= min(stale_count * 3, 20)
            issue_score = max(0, issue_score)
            grades["\U0001f4dd 工单管理"] = {
                "score": round(issue_score),
                "detail": f"解决率 {resolution_rate:.0f}% · 紧急未处理 {urgent_unresolved} · 积压 {stale_count}",
                "trend": "↑" if resolution_rate >= 70 else "↓",
            }
            lines.append(f"**\U0001f4dd 工单管理**：{total_i} 件 · 待处理 {pending} · 处理中 {processing} · 已解决 {resolved}")
            if avg_resolution_days is not None:
                lines.append(f"   ⏱️ 平均解决时间：{avg_resolution_days} 天")
            if stale_count > 0:
                lines.append(f"   ⚠️ 积压 {stale_count} 件超时未处理")

            # 2. 提案参与
            prop_summary = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status"
            ).fetchall()
            total_p = sum(r["cnt"] for r in prop_summary)
            by_pstatus = {r["status"]: r["cnt"] for r in prop_summary}
            unresponded = by_pstatus.get("讨论中", 0)
            responded = by_pstatus.get("已回应", 0)
            adopted = by_pstatus.get("已采纳", 0) + by_pstatus.get("已实施", 0)
            adoption_rate = adopted / total_p * 100 if total_p > 0 else 0

            avg_sup_row = conn.execute(
                "SELECT ROUND(AVG(supporter_count), 1) as avg_sup FROM proposals"
            ).fetchone()
            avg_supporters = avg_sup_row["avg_sup"] if avg_sup_row else 0

            prop_score = 100.0
            if total_p > 0:
                if unresponded > 0:
                    prop_score -= min(unresponded * 8, 40)
                prop_score += min(adoption_rate / 50 * 20, 20)
            prop_score = max(0, min(100, prop_score))
            grades["\U0001f4a1 提案参与"] = {
                "score": round(prop_score),
                "detail": f"采纳率 {adoption_rate:.0f}% · 待回复 {unresponded} · 人均附议 {avg_supporters}",
                "trend": "↑" if adoption_rate >= 30 else "↓",
            }
            lines.append(f"\n**\U0001f4a1 提案参与**：{total_p} 件 · 待回复 {unresponded} · 已采纳/实施 {adopted}")
            lines.append(f"   人均附议：{avg_supporters} 人")

            # 3. 公民参与
            topic_rows = conn.execute(
                "SELECT COUNT(*) as cnt, SUM(participant_count) as total_parts FROM discussion_topics"
            ).fetchone()
            total_topics = topic_rows["cnt"] if topic_rows else 0
            total_participants = (topic_rows["total_parts"] or 0) if topic_rows else 0
            unique_authors_row = conn.execute(
                "SELECT COUNT(DISTINCT author) as cnt FROM community_issues"
            ).fetchone()
            unique_authors = unique_authors_row["cnt"] if unique_authors_row else 0

            eng_score = 100.0
            if unique_authors < 3:
                eng_score -= 30
            elif unique_authors < 5:
                eng_score -= 15
            if total_participants < 10:
                eng_score -= 20
            eng_score = max(0, eng_score)
            grades["\U0001f5e3️ 公民参与"] = {
                "score": round(eng_score),
                "detail": f"{unique_authors} 人上报 · {total_participants} 人次参与讨论 · {total_topics} 个议题",
                "trend": "↑" if unique_authors >= 5 else "→",
            }
            lines.append(f"\n**\U0001f5e3️ 公民参与**：{unique_authors} 位用户上报问题 · {total_participants} 人次参与议题讨论")

            # 4. 热点类别
            cat_rows = conn.execute(
                "SELECT category, COUNT(*) as cnt FROM community_issues "
                "WHERE status != '已解决' GROUP BY category ORDER BY cnt DESC LIMIT 3"
            ).fetchall()
            if cat_rows:
                cat_strs = [f"{r['category']}({r['cnt']}件)" for r in cat_rows]
                lines.append(f"\n**\U0001f525 热点类别**：{'、'.join(cat_strs)}")

        # 5. 整体健康度
        lines.append(f"\n**\U0001f3e5 治理健康度**：{health['grade']}（{health['score']} 分）")

        # 6. 分维度评分
        lines.append("\n### \U0001f4ca 分维度评分")
        for dim, g in grades.items():
            letter = "A" if g["score"] >= 85 else "B" if g["score"] >= 70 else "C" if g["score"] >= 50 else "D"
            lines.append(
                f"- {dim}：{letter} ({g['score']}分) {g['trend']} — {g['detail']}"
            )

        # 7. 行动建议
        actions: list[tuple[int, str]] = []
        if urgent_unresolved > 0:
            actions.append((10, f"\U0001f534 处理 {urgent_unresolved} 件紧急工单（最高优先）"))
        if unresponded > 0:
            actions.append((8, f"\U0001f4ac 回复 {unresponded} 件待回复提案"))
        if stale_count >= 3:
            actions.append((7, f"⚠️ 清理 {stale_count} 件超7天积压工单"))
        if resolution_rate < 50 and total_i > 5:
            actions.append((5, f"\U0001f4c8 提升解决率（当前仅 {resolution_rate:.0f}%）"))
        if cat_rows and cat_rows[0]["cnt"] >= 5:
            actions.append((4, f"\U0001f680 建议为「{cat_rows[0]['category']}」类问题发起系统性治理提案"))

        if actions:
            actions.sort(key=lambda x: -x[0])
            lines.append("\n### \U0001f3af 优先行动建议")
            for _, action_text in actions[:3]:
                lines.append(f"- {action_text}")

        return "\n".join(lines)

    except Exception as e:
        _log.warning("治理审计失败（非致命）：%s", e)
        return f"*治理体检暂时不可用：{e}*"
