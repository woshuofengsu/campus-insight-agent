# api_routes/agent.py
"""Agent 统一入口 + 留痕/处理包/用量/分析路由（从 api_web.py 拆出，P2-04）。"""
import logging
import time

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role, _resolve_elder_uid

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/agent", tags=["agent"])

_MAX_AGENT_SESSIONS = 500

# N5：Agent 对话每用户限流（内存版滑动窗口；接口可为后续 Redis 实现复用）
_CHAT_LIMIT = 60  # 每分钟最多 60 次
_RATE_WINDOW = 60
_chat_rate: dict[str, list] = {}


def _rate_limited(key: str) -> bool:
    now = time.time()
    bucket = _chat_rate.setdefault(key, [])
    while bucket and now - bucket[0] > _RATE_WINDOW:
        bucket.pop(0)
    if len(bucket) >= _CHAT_LIMIT:
        return True
    bucket.append(now)
    return False


def _get_orchestrator(request: Request, key: str):
    """取/建用户 Orchestrator，超上限时淘汰最久未活动的会话（LRU，P1-1）。"""
    from agent.orchestrator import Orchestrator
    orchs = getattr(request.app.state, "_agent_orchs", None)
    if orchs is None:
        orchs = request.app.state._agent_orchs = {}
    if key not in orchs:
        if len(orchs) >= _MAX_AGENT_SESSIONS:
            oldest = min(orchs, key=lambda k: getattr(orchs[k], "last_active", 0))
            orchs.pop(oldest, None)
        orchs[key] = Orchestrator()
    return orchs[key]


class AgentChat(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)


@router.post("/chat")
def agent_chat(req: AgentChat, request: Request):
    """居民端 / 负责人端 Agent 对话（多 Agent 编排：接待员→业务Agent→合规审计→执行链）。"""
    u = _user(request)
    role = u.get("role")
    if role not in ("resident", "grid"):
        return _fail(1003, "当前角色暂不支持 Agent 对话")
    if _rate_limited(f"chat:{u.get('uid')}"):  # N5 限流
        return _fail(1002, "您说得有点快，我喘口气，稍等几秒再说")
    try:
        key = f"{role}:{u.get('uid')}"
        orch = _get_orchestrator(request, key)
        return _ok(orch.run(role, u.get("uid"), u.get("name") or "居民", req.text))
    except Exception as e:  # noqa: BLE001
        _log.warning("对话异常：%s", e)
        return _fail(2001, "服务暂时不可用，请稍后再试")


@router.post("/elderly/chat")
def agent_elderly_chat(req: AgentChat, request: Request):
    """老年端 Agent 对话（语音转写文本或文字输入，多 Agent 编排）。"""
    u = _user(request)
    role = u.get("role")
    if role not in ("elderly", "resident"):
        return _fail(1003, "无权限")
    if _rate_limited(f"chat:{u.get('uid')}"):  # N5 限流
        return _fail(1002, "您说得有点快，我喘口气，稍等几秒再说")
    try:
        uid = _resolve_elder_uid(request) or u.get("uid")
        key = f"elderly:{uid}"
        orch = _get_orchestrator(request, key)
        return _ok(orch.run("elderly", uid, u.get("name") or "老人", req.text, elder_uid=uid))
    except Exception as e:  # noqa: BLE001
        _log.warning("老年端对话异常：%s", e)
        return _fail(2001, "服务暂时不可用，请稍后再试")


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
    limit = min(limit, 500)
    """负责人查 Agent 留痕。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_agent_logs
    return _ok(get_agent_logs(role=role, intent=intent, status=status,
                              keyword=keyword, limit=limit))


@router.get("/handoffs")
def agent_handoffs(request: Request, status: str = "", limit: int = 50):
    limit = min(limit, 500)
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


@router.get("/care-metrics")
def agent_care_metrics(request: Request, days: int = 7):
    """关怀量化（U4）：情绪识别 / 关怀触达率 / 情绪→转人工率 / 场景分布（grid 专属）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_care_metrics import get_care_metrics
    return _ok(get_care_metrics(days=days))


@router.get("/kb-health")
def agent_kb_health(request: Request, days: int = 7, top_n: int = 10):
    """知识库健康度（U3）：命中率 / 零命中问题 top / 检索路线 / 语料规模（grid 专属）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_kb_metrics import get_kb_health
    return _ok(get_kb_health(days=days, top_n=top_n))


@router.get("/traces/{trace_id}")
def agent_trace_chain(trace_id: str, request: Request):
    """链路追踪：按 trace_id 查同一次操作的全部留痕（P2-F4-01）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_trace_chain
    return _ok(get_trace_chain(trace_id))


@router.get("/kg/entity")
def agent_kg_entity(request: Request, name: str = "", limit: int = 20):
    """轻量知识图谱（U6）：按实体反查关联工单/政策/提案/关联实体（grid 专属）。

    例：`?name=3号楼` → 该楼栋历史工单 + 相关设施 + 相关政策；
    `?name=3号楼电梯` → 复合查询取交集（同时提到两者的工单）。
    """
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    if not (name or "").strip():
        return _fail(1003, "请提供实体名 name（如 3号楼 / 电梯 / 加装电梯）")
    from data.db_kg import query_entity
    return _ok(query_entity(name, limit=limit))


@router.get("/kg/stats")
def agent_kg_stats(request: Request):
    """图谱规模统计（U6）：实体/关系/引用数、类型分布、关系强度 top、工单覆盖率（grid 专属）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_kg import graph_stats
    return _ok(graph_stats())


@router.post("/kg/rebuild")
def agent_kg_rebuild(request: Request, limit: int = 500):
    """重建知识图谱（U6，grid 专属）：从工单/已发布政策/提案重抽实体与关系，幂等。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_kg import build_graph
    try:
        return _ok(build_graph(limit=limit), "图谱重建完成")
    except Exception as e:  # noqa: BLE001
        _log.warning("图谱重建失败：%s", e)
        return _fail(2001, "图谱重建失败，请稍后再试")
