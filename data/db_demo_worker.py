"""演示闭环机器人 — 自动把新工单走完「处理中→已解决→通知居民」。

让「接诉即办」的「办」在演示里真的转：居民上报后，机器人自动接单、处理、办结，
并走既有的 update_issue_status 通知链路（居民收到状态更新）。
开关：config.DEMO_AUTO_WORKER（默认开）；生产环境设 false 回到人工流程。
"""
import logging

from config import DEMO_AUTO_WORKER
from data.db_core import get_db

_log = logging.getLogger(__name__)


def process_new_issues(limit: int = 1, min_age_minutes: int = 3) -> int:
    """把最早的 N 条「待处理」工单推进为「已解决」（渐进，闭环可观察）。

    每次只推进少量工单，避免一次性清空待办；只处理已派单（assignee 非空）且
    上报超过 `min_age_minutes` 分钟的工单——让工单在「待处理」状态停留片刻，
    居民/评委能看到「待处理→处理中→已解决」的真实过程，而非秒办结。
    返回本次处理的工单数。
    """
    if not DEMO_AUTO_WORKER:
        return 0
    processed = 0
    try:
        from data.db_governance import update_issue_status
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id FROM community_issues "
                "WHERE status = '待处理' AND (assignee_id IS NOT NULL OR assignee != '') "
                "AND reported_at < datetime('now', ?) "
                "ORDER BY id ASC LIMIT ?",
                (f'-{min_age_minutes} minutes', limit),
            ).fetchall()
        for r in rows:
            iid = r["id"]
            update_issue_status(iid, "处理中", actor="演示网格员", processing_note="已接单，正在处理。")
            update_issue_status(iid, "已解决", actor="演示网格员", processing_note="已处理完成。")
            processed += 1
            _log.info("demo worker 已解决工单 #%d", iid)
    except Exception:
        _log.warning("demo worker 处理失败", exc_info=True)
    return processed
