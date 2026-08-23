# api_routes/agent.py
"""Agent 统一入口 + 留痕/处理包/用量/分析路由（从 api_web.py 拆出，P2-04）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _resolve_elder_uid

router = APIRouter(prefix="/api/web/agent", tags=["agent"])


class AgentChat(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)


@router.post("/chat")
def agent_chat(req: AgentChat, request: Request):
    """居民端 / 负责人端 Agent 对话（多 Agent 编排：接待员→业务Agent→合规审计→执行链）。"""
    from agent.orchestrator import Orchestrator
    u = _user(request)
    role = u.get("role")
    if role not in ("resident", "grid"):
        return _fail(1003, "当前角色暂不支持 Agent 对话")
    try:
        orch = getattr(request.app.state, "_agent_orchs", None)
        if orch is None:
            orch = request.app.state._agent_orchs = {}
        key = f"{role}:{u.get('uid')}"
        if key not in orch:
            orch[key] = Orchestrator()
        return _ok(orch[key].run(role, u.get("uid"), u.get("name") or "居民", req.text))
    except Exception as e:  # noqa: BLE001
        return _fail(2001, f"服务暂时不可用，请稍后再试（{e}）")


@router.post("/elderly/chat")
def agent_elderly_chat(req: AgentChat, request: Request):
    """老年端 Agent 对话（语音转写文本或文字输入，多 Agent 编排）。"""
    from agent.orchestrator import Orchestrator
    u = _user(request)
    role = u.get("role")
    if role not in ("elderly", "resident"):
        return _fail(1003, "无权限")
    try:
        uid = _resolve_elder_uid(request) or u.get("uid")
        orch = getattr(request.app.state, "_agent_orchs", None)
        if orch is None:
            orch = request.app.state._agent_orchs = {}
        key = f"elderly:{uid}"
        if key not in orch:
            orch[key] = Orchestrator()
        return _ok(orch[key].run("elderly", uid, u.get("name") or "老人", req.text, elder_uid=uid))
    except Exception as e:  # noqa: BLE001
        return _fail(2001, f"服务暂时不可用，请稍后再试（{e}）")


@router.get("/history")
def agent_history(request: Request):
    """居民端最近 5 条对话（可查看详情，可删除）。"""
    from data.db_agent import get_dialogs
    u = _user(request)
    return _ok(get_dialogs(u.get("uid"), u.get("role") or "resident", limit=5))


@router.delete("/history/{did}")
def agent_history_delete(did: int, request: Request):
    """居民删除自己的对话（归属校验）。"""
    from data.db_agent import delete_dialog
    u = _user(request)
    if not delete_dialog(did, u.get("uid")):
        return _fail(1003, "无权限删除该记录")
    return _ok({"deleted": did}, "已删除")


@router.delete("/history")
def agent_history_clear(request: Request):
    """居民清空自己的历史对话。"""
    from data.db_agent import clear_dialogs
    u = _user(request)
    n = clear_dialogs(u.get("uid"), u.get("role") or "resident")
    return _ok({"cleared": n}, "已清空")


@router.get("/logs")
def agent_logs(request: Request, role: str = "", intent: str = "",
               status: str = "", keyword: str = "", limit: int = 200):
    """负责人查 Agent 留痕。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_agent_logs
    return _ok(get_agent_logs(role=role, intent=intent, status=status,
                              keyword=keyword, limit=limit))


@router.get("/handoffs")
def agent_handoffs(request: Request, status: str = "", limit: int = 50):
    """负责人端人工处理包列表（无缝转人工：AI 已整理上下文，可直接处理）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import list_handoffs
    return _ok(list_handoffs(status=status, limit=limit))


@router.post("/handoffs/{hid}/resolve")
def agent_handoff_resolve(hid: int, request: Request):
    """负责人处理完成（关闭人工处理包）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import resolve_handoff
    if not resolve_handoff(hid, _user(request).get("name") or "负责人"):
        return _fail(2001, "处理包不存在或已处理")
    return _ok({"handoff_id": hid}, "已处理完成")


@router.get("/llm-usage")
def agent_llm_usage(request: Request, days: int = 7):
    """LLM 用量统计（P2-05）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_llm_usage import get_usage_summary, get_usage_trend
    return _ok({"summary": get_usage_summary(days=days), "trend": get_usage_trend(days=days)})


@router.get("/self-resolution")
def agent_self_resolution(request: Request, days: int = 7):
    """AI 自转率统计（P3-B5-01：AI 直答 vs 转人工量化）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_self_resolution_stats
    return _ok(get_self_resolution_stats(days=days))


@router.get("/board")
def agent_red_black_board(request: Request, days: int = 30, limit: int = 5):
    """红黑榜（P2-B4-01：满意工单/高效网格员/完成提案 vs 不满意/超时/低效网格员）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_board import get_red_black_board
    return _ok(get_red_black_board(days=days, limit=limit))


@router.get("/satisfaction-drilldown")
def agent_satisfaction_drilldown(request: Request, category: str = "",
                                 assignee: str = "", satisfaction: str = "", limit: int = 50):
    """满意度下钻（P2-B4-01：按分类/网格员/评价筛选到单工单）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_board import get_satisfaction_drilldown
    return _ok(get_satisfaction_drilldown(category=category, assignee=assignee,
                                          satisfaction=satisfaction, limit=limit))


@router.get("/analytics")
def agent_analytics(request: Request, days: int = 7):
    """问题聚类 + 趋势 + 数据简报（P2-03 / P3-03）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from agent.analytics import get_issue_clusters, get_weekly_trend, build_data_brief
    return _ok({"clusters": get_issue_clusters(days=days),
                "trend": get_weekly_trend(days=days),
                "brief": build_data_brief()})


@router.get("/traces/{trace_id}")
def agent_trace_chain(trace_id: str, request: Request):
    """链路追踪：按 trace_id 查同一次操作的全部留痕（P2-F4-01）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_trace_chain
    return _ok(get_trace_chain(trace_id))
