# api_routes/batch.py
"""批量操作路由模块（P2-E2-01）：批量派单 / 批量关闭 / 批量回复。

负责人专用；逐条调用既有数据层函数，返回每条的成败明细（不中断整体）。
"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _tenant

import logging
_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/batch", tags=["batch"])


class BatchDispatch(BaseModel):
    issue_ids: list[int] = Field(..., min_length=1, max_length=50)
    assignee_name: str = Field(..., min_length=1)
    assignee_phone: str = Field(default="")


class BatchClose(BaseModel):
    issue_ids: list[int] = Field(..., min_length=1, max_length=50)
    reason: str = Field(default="批量关闭")


class BatchReply(BaseModel):
    question_ids: list[int] = Field(..., min_length=1, max_length=50)
    reply: str = Field(..., min_length=1, max_length=500)


def _owned_ids(table: str, ids: list[int], tenant: str) -> set[int]:
    """返回 ids 中属于本租户（tenant_id=tenant）的 id 集合。

    tenant 空串 → 空集（fail-closed：无社区归属的负责人不能批量操作任何数据）。
    """
    if not ids or not tenant:
        return set()
    from data.db_core import get_db
    ph = ",".join("?" * len(ids))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT id FROM {table} WHERE id IN ({ph}) AND tenant_id=?",
            (*ids, tenant),
        ).fetchall()
    return {r["id"] for r in rows}


def _run_batch(ids, fn, actor, allowed=None):
    """逐条执行，返回 {success, failed, results:[{id, ok, msg}]}。

    `allowed`：本租户允许操作的 id 集合；不在集合内的 id 直接判失败（租户隔离），
    不调用 fn、不越权修改他社区数据。
    """
    results, ok_n = [], 0
    for iid in ids:
        if allowed is not None and iid not in allowed:
            results.append({"id": iid, "ok": False, "msg": "不属于当前社区（租户隔离），已拒绝"})
            continue
        try:
            ok_, msg = fn(iid, actor)
        except Exception as e:  # noqa: BLE001
            _log.warning("批量操作异常：%s", e)
            ok_, msg = False, "操作失败"
        results.append({"id": iid, "ok": bool(ok_), "msg": msg or "ok"})
        if ok_:
            ok_n += 1
    return {"success": ok_n, "failed": len(ids) - ok_n, "results": results}


@router.post("/dispatch")
def batch_dispatch(req: BatchDispatch, request: Request):
    """批量派单：一组工单分派给同一维修人员（跳过非待派单状态）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_repair import dispatch_issue
    actor = _user(request).get("name") or "负责人"
    tenant = _tenant(request)
    allowed = _owned_ids("community_issues", req.issue_ids, tenant)
    out = _run_batch(req.issue_ids,
                     lambda iid, a: dispatch_issue(iid, req.assignee_name, req.assignee_phone, actor=a),
                     actor, allowed=allowed)
    return _ok(out, f"批量派单完成：成功 {out['success']}，失败 {out['failed']}")


@router.post("/close")
def batch_close(req: BatchClose, request: Request):
    """批量关闭：一组工单关闭（跳过状态不允许的）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_repair import close_issue
    actor = _user(request).get("name") or "负责人"
    tenant = _tenant(request)
    allowed = _owned_ids("community_issues", req.issue_ids, tenant)
    out = _run_batch(req.issue_ids,
                     lambda iid, a: close_issue(iid, req.reason, actor=a),
                     actor, allowed=allowed)
    return _ok(out, f"批量关闭完成：成功 {out['success']}，失败 {out['failed']}")


@router.post("/reply")
def batch_reply(req: BatchReply, request: Request):
    """批量回复政策提问：同一回复发到一组提问（跳过非待回复状态）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import reply_question
    actor = _user(request).get("name") or "负责人"
    tenant = _tenant(request)
    allowed = _owned_ids("policy_questions", req.question_ids, tenant)
    out = _run_batch(req.question_ids,
                     lambda qid, a: reply_question(qid, req.reply, actor=a),
                     actor, allowed=allowed)
    return _ok(out, f"批量回复完成：成功 {out['success']}，失败 {out['failed']}")
