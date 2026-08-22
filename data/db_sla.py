"""SLA（服务时效）分级 — 接诉即办的办理时限与超时预警。

时效口径（评委问"紧急多久预警"时的标准答案）:
  - 极急: 6 小时   （人身安全 / 大面积影响）
  - 紧急: 24 小时  （影响较大需尽快处理）
  - 普通: 72 小时  （一般问题）

超过时限仍未解决的工单 = SLA 超时，进入网格员工作台预警清单。
统一由本模块提供，替代此前散落在 dashboard / issues_mgmt / reflector
三处的硬编码 `-7 days`。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 时限口径（小时）——单一事实来源，供 SLA 查询与「口径面板」共同引用
SLA_HOURS = {"极急": 6, "紧急": 24, "普通": 72}


def _urgent_breach_expr() -> str:
    """SQL 条件片段：判断各紧急度是否超时（单位：天）。"""
    return (
        "(urgency = '极急' AND julianday('now') - julianday(reported_at) > 0.25) "
        "OR (urgency = '紧急' AND julianday('now') - julianday(reported_at) > 1.0) "
        "OR (urgency NOT IN ('极急','紧急') AND julianday('now') - julianday(reported_at) > 3.0)"
    )


def get_sla_breaches(limit: int = 50) -> list[dict]:
    """返回已超 SLA 的工单（还在时限内没解决的）。

    每条: {id, title, category, location, urgency, status, hours_open, level}
      level: "critical"（极急/紧急超时）| "overdue"（普通超时）
    """
    rows: list[dict] = []
    try:
        with get_db() as conn:
            cur = conn.execute(
                "SELECT id, title, category, location, urgency, status, reported_at, "
                "CAST((julianday('now') - julianday(reported_at)) * 24 AS INTEGER) "
                "AS hours_open "
                "FROM community_issues "
                "WHERE status IN ('待处理','处理中') AND (" + _urgent_breach_expr() + ") "
                "ORDER BY (urgency IN ('极急','紧急')) DESC, hours_open DESC LIMIT ?",
                (limit,),
            )
            for r in cur.fetchall():
                d = dict(r)
                d["level"] = "critical" if d.get("urgency") in ("极急", "紧急") else "overdue"
                rows.append(d)
    except Exception:
        _log.warning("get_sla_breaches 查询失败", exc_info=True)
    return rows


def get_sla_summary() -> dict:
    """给看板/工作台汇总 SLA 超时的计数。"""
    try:
        with get_db() as conn:
            urgent_pending = conn.execute(
                "SELECT COUNT(*) as cnt FROM community_issues "
                "WHERE urgency IN ('极急','紧急') AND status != '已解决'"
            ).fetchone()
            total_overdue = conn.execute(
                "SELECT COUNT(*) as cnt FROM community_issues "
                "WHERE status IN ('待处理','处理中') AND (" + _urgent_breach_expr() + ")"
            ).fetchone()
            critical = conn.execute(
                "SELECT COUNT(*) as cnt FROM community_issues "
                "WHERE urgency IN ('极急','紧急') AND status IN ('待处理','处理中') "
                "AND ("
                "  (urgency = '极急' AND julianday('now') - julianday(reported_at) > 0.25) "
                "  OR (urgency = '紧急' AND julianday('now') - julianday(reported_at) > 1.0)"
                ")"
            ).fetchone()
        return {
            "urgent_pending": urgent_pending["cnt"] if urgent_pending else 0,
            "critical_overdue": critical["cnt"] if critical else 0,
            "normal_overdue": (total_overdue["cnt"] if total_overdue else 0) - (critical["cnt"] if critical else 0),
            "total_overdue": total_overdue["cnt"] if total_overdue else 0,
        }
    except Exception:
        _log.warning("get_sla_summary 统计失败", exc_info=True)
        return {"urgent_pending": 0, "critical_overdue": 0, "normal_overdue": 0, "total_overdue": 0}


def _escalation_expr() -> str:
    """SQL 条件片段：超时 2× 的升级阈值（极急 12h / 紧急 48h / 普通 144h）。"""
    return (
        "(urgency = '极急' AND julianday('now') - julianday(reported_at) > 0.5) "
        "OR (urgency = '紧急' AND julianday('now') - julianday(reported_at) > 2.0) "
        "OR (urgency NOT IN ('极急','紧急') AND julianday('now') - julianday(reported_at) > 6.0)"
    )


def escalate_overdue_issues(limit: int = 20) -> list[dict]:
    """将超时 2× 仍未解决的工单标记为「已升级」，并尽力发封邮件通知。

    幂等：只处理 escalated_at 为空的工单，重复调用不会重复升级/重复发信。
    返回本次新升级的工单列表 {id, title, category, urgency, hours_open}。
    """
    escalated: list[dict] = []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title, category, urgency, "
                "CAST((julianday('now') - julianday(reported_at)) * 24 AS INTEGER) AS hours_open "
                "FROM community_issues "
                "WHERE status IN ('待处理','处理中') AND escalated_at IS NULL "
                "AND (" + _escalation_expr() + ") "
                "ORDER BY hours_open DESC LIMIT ?",
                (limit,),
            ).fetchall()
            for r in rows:
                conn.execute(
                    "UPDATE community_issues SET escalated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (r["id"],),
                )
                escalated.append(dict(r))
            conn.commit()
    except Exception:
        _log.warning("escalate_overdue_issues 升级失败", exc_info=True)
        return []

    if escalated:
        try:
            from data.email_notify import send_email, is_configured
            if is_configured():
                body = "\n".join(
                    f"#{e['id']}「{(e.get('title') or '')[:30]}」"
                    f"（{e['urgency']}，已超时 {e['hours_open']} 小时）"
                    for e in escalated
                )
                # 按用户要求：SLA 升级提醒不再外发到 SMTP_TO（原 1803801843@qq.com），
                # 只发给自己留档；站内通知（messages）仍是主渠道。
                from config import SMTP_USER
                send_email("社区先知 SLA 升级提醒", body, to=SMTP_USER)
        except Exception:
            _log.warning("SLA 升级邮件发送失败", exc_info=True)
    return escalated


def get_escalated_issues(limit: int = 20) -> list[dict]:
    """查已升级的工单（escalated_at 有值），按升级时间新的在前。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, title, category, urgency, status, assignee, escalated_at, "
                "CAST((julianday('now') - julianday(reported_at)) * 24 AS INTEGER) AS hours_open "
                "FROM community_issues "
                "WHERE escalated_at IS NOT NULL AND status IN ('待处理','处理中') "
                "ORDER BY escalated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        _log.warning("get_escalated_issues 查询失败", exc_info=True)
        return []
