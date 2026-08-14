"""主动派单 — Agent 主动发现问题、按类别自动派单给网格员。

战线二「主动发现 + 主动派单」的实现：感知引擎在 Observe 阶段扫描未派单的
开放工单，按「类别 → 责任部门 → 网格员」的映射自动指派处理人，并写入
assignee_id（用户主键）供「我的待办」按 ID 过滤，同时下发站内通知。
"""
import logging

from data.db_core import get_db

_log = logging.getLogger(__name__)

# 诉求类别 → 责任部门（用于自动派单；部门名与 onboarding 的网格员部门选项一致）
CATEGORY_DEPT_MAP = {
    "设施维修": "物业",
    "环境卫生": "物业",
    "安全隐患": "网格办",
    "停车管理": "物业",
    "噪音扰民": "居委会",
    "物业服务": "物业",
    "邻里矛盾": "居委会",
    "社区事务": "居委会",
    "其他": "网格办",
}


def _grid_worker_for(dept: str) -> dict | None:
    """按部门找一个网格员，返回整行 dict。"""
    try:
        from data.db_user import list_users
        for u in list_users(role="grid"):
            if (u.get("building") or "").strip() == dept:
                return u
    except Exception:
        _log.warning("_grid_worker_for 在 dept=%r 下没找到网格员", dept, exc_info=True)
    return None


def _any_grid_worker() -> dict | None:
    """兜底：随便返回一个网格员。"""
    try:
        from data.db_user import list_users
        grids = list_users(role="grid")
        if grids:
            return grids[0]
    except Exception:
        _log.warning("_any_grid_worker 兜底也找不到网格员", exc_info=True)
    return None


def _worker_display_name(u: dict) -> str:
    return (u.get("name") or "").strip() or (u.get("username") or "").strip()


def auto_dispatch(issue_id: int) -> dict | None:
    """按「类别→部门」映射，给一个还没派单的工单指派网格员。

    同时写 `assignee`（显示名）和 `assignee_id`（用户 ID），再给被派单人发
    一条站内通知。已经派过的直接返回，不重复处理。返回
    {issue_id, assignee, assignee_id}，找不到人就返回 None。
    """
    with get_db() as conn:
        issue = conn.execute(
            "SELECT id, title, category, assignee, assignee_id "
            "FROM community_issues WHERE id = ?",
            (issue_id,),
        ).fetchone()
    if not issue:
        return None
    if (issue["assignee_id"] is not None) or (issue["assignee"] or "").strip():
        return {"issue_id": issue_id, "assignee": issue["assignee"],
                "assignee_id": issue["assignee_id"]}

    dept = CATEGORY_DEPT_MAP.get(issue["category"], "网格办")
    worker = _grid_worker_for(dept) or _grid_worker_for("网格办") or _any_grid_worker()
    if not worker:
        return None

    name = _worker_display_name(worker)
    uid = worker.get("id")
    with get_db() as conn:
        conn.execute(
            "UPDATE community_issues SET assignee = ?, assignee_id = ? WHERE id = ?",
            (name, uid, issue_id),
        )
        conn.commit()
    _log.info("auto_dispatch 已派单 #%d -> %s (id=%s, dept=%s)", issue_id, name, uid, dept)

    # 站内通知：让网格员感知到被派了新单
    try:
        from data.db_notifications import create_notification
        create_notification(
            uid, "new_dispatch",
            f"新工单派发：#{issue_id}「{issue['title'][:20]}」",
            f"类别：{issue['category']}。请前往「工单管理」处理。",
            related_id=issue_id,
        )
    except Exception:
        _log.warning("auto_dispatch 发通知失败（工单 #%d，不影响）", issue_id, exc_info=True)

    return {"issue_id": issue_id, "assignee": name, "assignee_id": uid}


def discover_and_dispatch(limit: int = 20) -> list[dict]:
    """主动扫描未派单的开放工单并自动派单（战线二）。

    极急/紧急的排前面先派。返回本次自动派出的列表，每项
    {issue_id, title, category, assignee, assignee_id}。
    """
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, title, category, urgency, assignee, assignee_id "
            "FROM community_issues "
            "WHERE status IN ('待处理', '处理中') AND (assignee_id IS NULL OR assignee = '') "
            "ORDER BY (urgency IN ('极急', '紧急')) DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()

    dispatched: list[dict] = []
    for r in rows:
        result = auto_dispatch(r["id"])
        if result:
            dispatched.append({
                "issue_id": r["id"],
                "title": r["title"],
                "category": r["category"],
                "assignee": result["assignee"],
                "assignee_id": result["assignee_id"],
            })
    return dispatched
