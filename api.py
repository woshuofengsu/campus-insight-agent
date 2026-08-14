# api.py — 对外 REST API
"""FastAPI 后端，把所有 Agent 工具暴露为 REST 端点。
扣子 AI 通过 OpenAPI 插件调用这些接口 → 读取社区治理数据 + 智能对话。

启动方式：
  pip install fastapi uvicorn
  python api.py                    # 默认 http://localhost:18800
  python api.py --port 18801       # 自定义端口

部署到公网（扣子必须能访问的 URL）：
  ngrok http 18800                 # 获得 https://xxx.ngrok-free.app
  或部署到云服务器
"""

import logging
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# 数据库懒初始化，保证不管走哪条路径都不会漏

_log = logging.getLogger(__name__)
_auth_warned = False


def _warn_no_auth():
    """API 在无密钥开放模式下运行时，只提醒一次。"""
    global _auth_warned
    if not _auth_warned:
        _log.warning(
            "COMMUNITY_API_KEY 未配置，API 处于开放模式（所有端点公开）。"
            "公网部署（ngrok/云服务器）请务必在 .env 设置密钥，否则任何人可调用 Agent 并消耗额度。"
        )
        _auth_warned = True


_db_initialized = False


def _ensure_db():
    """确保数据库已初始化，重复调用也安全（幂等）。"""
    global _db_initialized
    if _db_initialized:
        return
    from config import DB_PATH
    from data.db_core import init_db
    from data.seed import seed_all
    init_db(DB_PATH)
    seed_all(DB_PATH)
    _db_initialized = True


# FastAPI 应用

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """启动时初始化 DB 并灌种子数据；关停不用做什么。"""
    _ensure_db()
    yield


app = FastAPI(
    title="CommunityInsight Agent API",
    description="社区先知 CommunityInsight — 社区微治理平台对外 API。",
    version="2.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 公开端点（不需要鉴权）
_PUBLIC_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json", "/"}


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """API key 鉴权中间件。

    支持 Authorization: Bearer <key> 或 X-API-Key: <key> 两种头；
    健康检查、文档这类公开端点永远放行；
    没配 COMMUNITY_API_KEY 时所有端点都是公开的。
    """
    from config import COMMUNITY_API_KEY

    # 公开路径，直接放行
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/docs"):
        return await call_next(request)

    # 没配密钥，开放模式
    if not COMMUNITY_API_KEY:
        _warn_no_auth()
        return await call_next(request)

    # 检查鉴权头
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")

    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif api_key_header:
        token = api_key_header

    if token != COMMUNITY_API_KEY:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Invalid or missing API key"},
        )

    return await call_next(request)


@app.middleware("http")
async def _db_init_middleware(request: Request, call_next):
    """每次请求前都确保 DB 已初始化（幂等，开销约等于零）。"""
    _ensure_db()
    return await call_next(request)


# 请求模型

class ReportIssueRequest(BaseModel):
    title: str = Field(..., description="问题标题", min_length=2)
    category: str = Field(default="", description="分类，留空自动识别")
    location: str = Field(default="", description="具体地点")
    description: str = Field(default="", description="详细描述")
    urgency: str = Field(default="", description="紧急程度，留空自动评估")


class CreateProposalRequest(BaseModel):
    title: str = Field(..., description="提案标题", min_length=2)
    description: str = Field(..., description="提案详细描述", min_length=5)
    category: str = Field(default="其他", description="分类")


class ExpressOpinionRequest(BaseModel):
    content: str = Field(..., description="意见内容", min_length=2)


class ChatRequest(BaseModel):
    message: str = Field(..., description="用户消息", min_length=1)
    resident_id: str = Field(default="", description="门牌号/工号")


# 健康检查

@app.get("/api/health", tags=["系统"])
def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "service": "CommunityInsight Agent",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
    }


# 天气

@app.get("/api/weather", tags=["天气"])
def get_weather():
    """获取当日及未来2天天气"""
    try:
        from tools.query_weather import get_today_weather
        days, location_name, is_real = get_today_weather()
        return {
            "success": True,
            "location": location_name,
            "is_real": is_real,
            "forecast": days if days else [],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 社区脉搏

@app.get("/api/community-pulse", tags=["社区脉搏"])
def get_community_pulse():
    """社区脉搏——本周热点、提案、议题、治理快照"""
    try:
        from data.database import (
            get_issues, get_proposals, get_active_topics,
            get_community_events, compute_health_score,
        )
        from datetime import timedelta

        now = datetime.now()
        weekday_map = ["周一","周二","周三","周四","周五","周六","周日"]
        weekday = weekday_map[now.weekday()]
        week_start = (now - timedelta(days=now.weekday())).strftime("%Y-%m-%d")

        issues = get_issues(limit=100)
        this_week = [i for i in issues if i.get("reported_at", "")[:10] >= week_start]
        resolved_tw = [i for i in this_week if i.get("status") == "已解决"]

        cats: dict = {}
        for i in this_week:
            cat = i.get("category", "其他")
            cats[cat] = cats.get(cat, 0) + 1
        hot_cat = max(cats, key=cats.get) if cats else None

        proposals = get_proposals(sort_by="supporters", limit=5)
        top_p = [
            {"id": p["id"], "title": p["title"],
             "supporter_count": p["supporter_count"], "status": p["status"]}
            for p in proposals
        ]

        topics = get_active_topics(limit=3)
        hot_topics = [{"id": t["id"], "title": t["title"]} for t in topics]

        events = get_community_events(limit=5)
        upcoming = [
            {"title": e["title"], "content": e.get("content", "")[:100]}
            for e in events
        ]

        all_i = get_issues(limit=200)
        total_i = len(all_i)
        pending = len([i for i in all_i if i.get("status") == "待处理"])
        resolved = len([i for i in all_i if i.get("status") == "已解决"])
        health = compute_health_score()

        return {
            "success": True,
            "date": now.strftime("%Y年%m月%d日"),
            "weekday": weekday,
            "this_week": {
                "new_count": len(this_week),
                "resolved_count": len(resolved_tw),
                "hot_category": hot_cat,
                "hot_category_count": cats.get(hot_cat, 0) if hot_cat else 0,
            },
            "top_proposals": top_p,
            "hot_topics": hot_topics,
            "upcoming_events": upcoming,
            "governance_snapshot": {
                "total_issues": total_i,
                "pending": pending,
                "resolved": resolved,
                "resolution_rate": round(resolved/total_i*100, 1) if total_i else 0,
                "health_score": health["score"],
                "health_grade": health["grade"],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 工单

@app.get("/api/issues", tags=["工单"])
def list_issues(
    category: Optional[str] = Query(None, description="分类"),
    status: Optional[str] = Query(None, description="状态"),
    urgency: Optional[str] = Query(None, description="紧急程度"),
    limit: int = Query(20, ge=1, le=200),
):
    """查询社区诉求工单列表"""
    try:
        from data.database import get_issues
        issues = get_issues(category=category, status=status, limit=limit)
        if urgency:
            issues = [i for i in issues if i.get("urgency") == urgency]

        return {
            "success": True,
            "total": len(issues),
            "issues": [
                {
                    "id": i["id"],
                    "title": i["title"],
                    "category": i.get("category", ""),
                    "location": i.get("location", ""),
                    "description": i.get("description", ""),
                    "urgency": i.get("urgency", "普通"),
                    "status": i.get("status", "待处理"),
                    "author": i.get("author", ""),
                    "reported_at": i.get("reported_at", ""),
                    "resolved_at": i.get("resolved_at", ""),
                }
                for i in issues
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/issues/stats", tags=["工单"])
def get_issue_stats():
    """工单统计数据"""
    try:
        from data.database import get_issues_stats
        stats = get_issues_stats()
        return {
            "success": True,
            "data": {
                "total": stats["total"],
                "by_status": stats["by_status"],
                "by_category": stats["by_category"],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/issues", tags=["工单"])
def report_issue(req: ReportIssueRequest):
    """上报社区诉求"""
    try:
        from tools.action_report_issue import (
            _auto_classify, _auto_urgency, validate_location,
        )
        from data.database import report_issue as _db_report, get_issues_stats

        loc_err = validate_location(req.title, req.location)
        if loc_err:
            raise HTTPException(status_code=400, detail=loc_err)

        cat = req.category.strip() or _auto_classify(req.title, req.description)
        urg = req.urgency.strip() or _auto_urgency(req.title, req.description)

        issue_id = _db_report(
            title=req.title.strip(),
            category=cat,
            location=req.location.strip(),
            description=req.description.strip(),
            urgency=urg,
            author="",
        )

        stats = get_issues_stats()
        return {
            "success": True,
            "message": f"工单 #{issue_id} 已创建",
            "data": {
                "issue_id": issue_id,
                "category": cat,
                "urgency": urg,
                "total_issues": stats["total"],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 提案

@app.get("/api/proposals", tags=["提案"])
def list_proposals(
    category: Optional[str] = Query(None),
    sort_by: str = Query("supporters"),
    limit: int = Query(20, ge=1, le=200),
):
    """查询社区提案列表"""
    try:
        from data.database import get_proposals, get_proposals_stats
        proposals = get_proposals(category=category, sort_by=sort_by, limit=limit)
        stats = get_proposals_stats()

        return {
            "success": True,
            "total": stats["total"],
            "proposals": [
                {
                    "id": p["id"],
                    "title": p["title"],
                    "description": p.get("description", ""),
                    "category": p.get("category", "其他"),
                    "status": p.get("status", "讨论中"),
                    "supporter_count": p.get("supporter_count", 0),
                    "author": p.get("author", ""),
                    "response_text": p.get("response_text", ""),
                    "created_at": p.get("created_at", ""),
                }
                for p in proposals
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/proposals", tags=["提案"])
def create_proposal(req: CreateProposalRequest):
    """创建社区改进提案"""
    try:
        from data.database import create_proposal as _db_create, get_proposals

        existing = get_proposals(limit=50)
        title_kw = set(req.title)
        for p in existing:
            p_kw = set(p["title"])
            overlap = len(title_kw & p_kw) / max(len(title_kw | p_kw), 1)
            if overlap > 0.4:
                raise HTTPException(
                    status_code=409,
                    detail=f"与已有提案「{p['title'][:30]}」({p['supporter_count']}人附议)相似",
                )

        pid = _db_create(
            title=req.title.strip(),
            description=req.description.strip(),
            category=req.category.strip(),
        )
        return {
            "success": True,
            "message": f"提案 #{pid} 已创建",
            "data": {"proposal_id": pid},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/proposals/{proposal_id}/support", tags=["提案"])
def support_proposal(proposal_id: int):
    """附议一个提案"""
    try:
        from data.database import support_proposal as _db_support, get_db

        with get_db() as conn:
            row = conn.execute(
                "SELECT id, title FROM proposals WHERE id = ?", (proposal_id,)
            ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"提案 #{proposal_id} 不存在")

        new_count = _db_support(proposal_id)
        return {
            "success": True,
            "message": f"附议成功",
            "data": {"supporter_count": new_count},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 议题

@app.get("/api/topics", tags=["议题"])
def list_topics(limit: int = Query(10, ge=1, le=50)):
    """查看活跃的民意议题"""
    try:
        from data.database import get_active_topics, get_opinion_summaries_batch
        topics = get_active_topics(limit=limit)
        # 批量查询，一次 SQL 搞定，避免 1+N 次查询
        topic_ids = [t["id"] for t in topics]
        summaries = get_opinion_summaries_batch(topic_ids)
        result = []
        for t in topics:
            s = summaries.get(t["id"], {"total_opinions": 0})
            result.append({
                "id": t["id"],
                "title": t["title"],
                "description": t.get("description", ""),
                "created_by_agent": bool(t.get("created_by_agent")),
                "participant_count": s.get("total_opinions", 0),
                "category": t.get("category", ""),
            })
        return {"success": True, "total": len(result), "topics": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/topics/{topic_id}", tags=["议题"])
def get_topic_detail(topic_id: int):
    """议题详情和讨论内容"""
    try:
        from data.database import get_opinion_summary, get_opinions_by_topic
        summary = get_opinion_summary(topic_id)
        if not summary.get("topic"):
            raise HTTPException(status_code=404, detail=f"议题 #{topic_id} 不存在")

        t = summary["topic"]
        opinions = get_opinions_by_topic(topic_id, limit=30)
        return {
            "success": True,
            "data": {
                "id": t["id"],
                "title": t["title"],
                "description": t.get("description", ""),
                "created_by_agent": bool(t.get("created_by_agent")),
                "total_opinions": summary.get("total_opinions", 0),
                "opinions": [
                    {
                        "participant": op.get("participant_label", "匿名"),
                        "content": op.get("content", ""),
                        "created_at": op.get("created_at", ""),
                    }
                    for op in opinions
                ],
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/topics/{topic_id}/opinions", tags=["议题"])
def express_opinion(topic_id: int, req: ExpressOpinionRequest):
    """对议题发表意见"""
    try:
        from data.database import add_opinion, get_opinion_summary, get_active_topics

        topics = get_active_topics(limit=100)
        target = next((t for t in topics if t["id"] == topic_id), None)
        if not target:
            raise HTTPException(status_code=404, detail=f"议题 #{topic_id} 不存在")

        add_opinion(topic_id=topic_id, content=req.content.strip(),
                     participant_label="匿名居民")
        summary = get_opinion_summary(topic_id)

        return {
            "success": True,
            "message": "意见已发表",
            "data": {"participant_count": summary.get("total_opinions", 0)},
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 治理

@app.get("/api/governance/health", tags=["治理"])
def get_governance_health():
    """治理健康度评分"""
    try:
        from data.database import compute_health_score
        h = compute_health_score()
        return {
            "success": True,
            "data": {
                "score": h["score"],
                "grade": h["grade"],
                "resolution_rate": h["resolution_rate"],
                "avg_days": h.get("avg_days"),
                "trend": h["trend"],
                "speed_score": h["speed_score"],
                "backlog_score": h["backlog_score"],
                "new_recent": h["new_recent"],
                "resolved_recent": h["resolved_recent"],
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/governance/audit", tags=["治理"])
def get_governance_audit():
    """全面治理体检——分维度评分 + 行动建议"""
    try:
        from data.database import get_db, compute_health_score

        with get_db() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM community_issues GROUP BY status"
            ).fetchall()
            by_status = {r["status"]: r["cnt"] for r in rows}
            total_i = sum(by_status.values())
            resolved = by_status.get("已解决", 0)

            from data.db_sla import get_sla_summary
            _sla = get_sla_summary()
            urgent_u = _sla.get("urgent_pending", 0)
            stale_n = _sla.get("total_overdue", 0)

            p_rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM proposals GROUP BY status"
            ).fetchall()
            by_ps = {r["status"]: r["cnt"] for r in p_rows}
            total_p = sum(by_ps.values())
            unresponded = by_ps.get("讨论中", 0)
            adopted = by_ps.get("已采纳", 0) + by_ps.get("已实施", 0)

        h = compute_health_score()
        return {
            "success": True,
            "data": {
                "health": {"score": h["score"], "grade": h["grade"], "trend": h["trend"]},
                "issues": {
                    "total": total_i,
                    "pending": by_status.get("待处理", 0),
                    "processing": by_status.get("处理中", 0),
                    "resolved": resolved,
                    "resolution_rate": round(resolved/total_i*100, 1) if total_i else 0,
                    "urgent_unresolved": urgent_u,
                    "stale_over_7days": stale_n,
                },
                "proposals": {
                    "total": total_p,
                    "unresponded": unresponded,
                    "adopted": adopted,
                    "adoption_rate": round(adopted/total_p*100, 1) if total_p else 0,
                },
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# AI 对话——核心端点

class FakeSession(dict):
    """模拟 Streamlit 的 session_state，dict 和属性两种访问都要支持。

    session_state 里既会 st["key"] 也会 st.key，所以两种写法都得能用。
    """

    def __getattr__(self, key: str):
        """支持 st.key 这种读法，键不存在就抛 AttributeError。"""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"FakeSession has no attribute '{key}'")

    def __setattr__(self, key: str, value):
        """支持 st.key = value 这种写法，下划线开头的键走正常属性。"""
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            self[key] = value

    def __contains__(self, key):
        """支持 'key' in st 判断，session_state 内部会用到。"""
        if isinstance(key, str) and key.startswith("_"):
            return key in self.__dict__
        return super().__contains__(key)


_agent = None


def _get_agent():
    global _agent
    if _agent is not None:
        return _agent

    fake_st = FakeSession()
    fake_st["chat_history"] = []
    fake_st["user_profile"] = {}

    from agent.engine import CommunityAgent
    _agent = CommunityAgent(fake_st)
    return _agent


@app.post("/api/chat", tags=["智能对话"])
def agent_chat(req: ChatRequest):
    """智能对话 —— 完整 OODA 治理工作流。

    扣子把用户消息传过来，Agent 自动判断意图、调用工具、返回回复。
    扣子 Bot 中把此端点配置为插件的 API 即可。
    """
    try:
        agent = _get_agent()
        if req.resident_id:
            agent.memory.st["user_profile"] = {
                "name": req.resident_id,
                "resident_id": req.resident_id,
                "community": "社区先知",
            }

        response = agent.run(req.message)
        return {
            "success": True,
            "data": {
                "reply": response,
                "thinking": getattr(agent, "_last_thinking", ""),
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/offline", tags=["智能对话"])
def agent_chat_offline(req: ChatRequest):
    """离线模式 —— 不依赖 DeepSeek API，规则匹配。"""
    try:
        from agent.offline_agent import OfflineAgent

        fake_st = FakeSession()
        fake_st["chat_history"] = []
        fake_st["user_profile"] = {}
        if req.resident_id:
            fake_st["user_profile"] = {
                "name": req.resident_id,
                "resident_id": req.resident_id,
                "community": "社区先知",
            }

        agent = OfflineAgent(fake_st)
        response = agent.run(req.message)
        return {
            "success": True,
            "data": {"reply": response, "mode": "offline"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 反馈

@app.get("/api/feedback", tags=["反馈"])
def get_feedback(topic: Optional[str] = Query(None)):
    """获取意见反馈"""
    try:
        from data.database import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, topic, opinion, sentiment, source, created_at "
                "FROM feedback_items ORDER BY id DESC LIMIT 50"
            ).fetchall()
        items = [dict(r) for r in rows]
        if topic:
            items = [i for i in items if topic in i.get("topic", "")]
        return {"success": True, "total": len(items), "items": items}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# 导出 OpenAPI（扣子插件要用）

@app.get("/openapi.json", tags=["系统"], include_in_schema=False)
def export_openapi():
    """导出 OpenAPI 3.0 schema，可直接导入扣子插件"""
    schema = app.openapi()
    schema["info"]["title"] = "CommunityInsight Agent"
    schema["info"]["description"] = (
        "社区先知 —— 社区微治理平台。提供诉求上报/查询、提案管理、"
        "议题讨论、天气、社区脉搏、治理健康度、智能对话等能力。"
    )
    return schema


# 入口

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="CommunityInsight Agent API")
    parser.add_argument("--port", type=int, default=18800)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    print(f"""
   CommunityInsight Agent API v2.0
   http://{args.host}:{args.port}
   文档: http://localhost:{args.port}/docs
   OpenAPI: http://localhost:{args.port}/openapi.json
   公网: ngrok http {args.port}
    """)

    uvicorn.run(app, host=args.host, port=args.port)
