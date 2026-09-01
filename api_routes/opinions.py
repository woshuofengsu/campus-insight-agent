# api_routes/opinions.py
"""舆情监测路由（P3-01，从 api_web.py 拆出）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role

router = APIRouter(prefix="/api/web/opinions", tags=["opinions"])


class OpinionCreate(BaseModel):
    content: str = Field(..., min_length=2, max_length=500)
    source: str = Field(default="手动录入")
    level: str = Field(default="", pattern="^(|红色|橙色|黄色|蓝色)$")


@router.post("")
def web_opinion_create(req: OpinionCreate, request: Request):
    """录入舆情（自动关键词分级）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_opinion import add_opinion
    oid = add_opinion(req.content, source=req.source,
                      created_by=_user(request).get("name") or "负责人", level=req.level)
    return _ok({"opinion_id": oid}, "已录入并分级")


@router.get("")
def web_opinion_list(request: Request, level: str = "", status: str = "", limit: int = 100):
    limit = min(limit, 500)
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_opinion import list_opinions
    return _ok(list_opinions(level=level, status=status, limit=limit))


@router.post("/{oid}/convert")
def web_opinion_convert(oid: int, request: Request):
    """舆情一键转工单（自动填充描述+来源，红色/橙色为紧急）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_opinion import convert_to_issue
    okp, msg, iid = convert_to_issue(oid, _user(request).get("name") or "负责人")
    if not okp:
        return _fail(2001, msg)
    return _ok({"issue_id": iid}, msg)


@router.get("/brief")
def web_opinion_brief(request: Request, days: int = 7):
    """舆情简报（分级统计 + 高优先级列表）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_opinion import build_brief
    return _ok(build_brief(days=days))
