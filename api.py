# api.py — CampusInsight Agent REST API
"""FastAPI 后端，把所有 Agent 工具暴露为 REST 端点。
扣子 AI 通过 OpenAPI 插件调用这些接口 → 读取校园治理数据 + 智能对话。

启动方式：
  pip install fastapi uvicorn
  python api.py                    # 默认 http://localhost:18800
  python api.py --port 18801       # 自定义端口

部署到公网（扣子必须能访问的 URL）：
  ngrok http 18800                 # 获得 https://xxx.ngrok-free.app
  或部署到云服务器
"""

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


# -- DB Lazy Init — 防御性初始化，确保任何路径都不会漏掉 --

_db_initialized = False


def _ensure_db():
    """Ensure DB is initialized. Safe to call multiple times — idempotent."""
    global _db_initialized
    if _db_initialized:
        return
    from config import DB_PATH
    from data.db_core import init_db
    from data.seed import seed_all
    init_db(DB_PATH)
    seed_all(DB_PATH)
    _db_initialized = True


# -- FastAPI App --

@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Startup: init DB + seed data. Shutdown: nothing needed."""
    _ensure_db()
    yield


app = FastAPI(
    title="CampusInsight Agent API",
    description="校园先知 CampusInsight — 校园微治理平台对外 API。",
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

# ── Public endpoints (no auth required) ──
_PUBLIC_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json", "/"}


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    """API key authentication middleware.

    Checks Authorization: Bearer <key> or X-API-Key: <key> header.
    Public endpoints (health, docs) are always allowed.
    If CAMPUS_API_KEY is not configured, all endpoints are public.
    """
    from config import CAMPUS_API_KEY

    # Public paths — always allowed
    if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/docs"):
        return await call_next(request)

    # No API key configured — open mode
    if not CAMPUS_API_KEY:
        return await call_next(request)

    # Check auth headers
    auth_header = request.headers.get("Authorization", "")
    api_key_header = request.headers.get("X-API-Key", "")

    token = ""
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
    elif api_key_header:
        token = api_key_header

    if token != CAMPUS_API_KEY:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Invalid or missing API key"},
        )

    return await call_next(request)


@app.middleware("http")
async def _db_init_middleware(request: Request, call_next):
    """Ensure DB is initialized before every request (idempotent, ~0 cost)."""
    _ensure_db()
    return await call_next(request)


# -- Request Models --

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
    student_id: str = Field(default="", description="学号/工号")


# -- Health --

@app.get("/api/health", tags=["系统"])
def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "service": "CampusInsight Agent",
        "version": "2.0.0",
        "timestamp": datetime.now().isoformat(),
    }


# -- Weather --

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


# -- Campus Pulse --

@app.get("/api/campus-pulse", tags=["校园脉搏"])
def get_campus_pulse():
    """校园脉搏——本周热点、提案、议题、治理快照"""
    try:
        from data.database import (
            get_issues, get_proposals, get_active_topics,
            get_campus_events, compute_health_score,
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

        events = get_campus_events(limit=5)
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


# -- Issues --

@app.get("/api/issues", tags=["工单"])
def list_issues(
    category: Optional[str] = Query(None, description="分类"),
    status: Optional[str] = Query(None, description="状态"),
    urgency: Optional[str] = Query(None, description="紧急程度"),
    limit: int = Query(20, ge=1, le=200),
):
    """查询校园问题工单列表"""
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
    """上报校园问题"""
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


# -- Proposals --

@app.get("/api/proposals", tags=["提案"])
def list_proposals(
    category: Optional[str] = Query(None),
    sort_by: str = Query("supporters"),
    limit: int = Query(20, ge=1, le=200),
):
    """查询校园提案列表"""
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
    """创建校园改进提案"""
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


# -- Topics --

@app.get("/api/topics", tags=["议题"])
def list_topics(limit: int = Query(10, ge=1, le=50)):
    """查看活跃的民意议题"""
    try:
        from data.database import get_active_topics, get_opinion_summaries_batch
        topics = get_active_topics(limit=limit)
        # Batch query — single DB round-trip instead of 1+N
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
                     participant_label="匿名学生")
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


# -- Governance --

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
                "SELECT status, COUNT(*) as cnt FROM campus_issues GROUP BY status"
            ).fetchall()
            by_status = {r["status"]: r["cnt"] for r in rows}
            total_i = sum(by_status.values())
            resolved = by_status.get("已解决", 0)

            urgent = conn.execute(
                "SELECT COUNT(*) as cnt FROM campus_issues "
                "WHERE urgency='紧急' AND status != '已解决'"
            ).fetchone()
            urgent_u = urgent["cnt"] if urgent else 0

            stale = conn.execute(
                "SELECT COUNT(*) as cnt FROM campus_issues "
                "WHERE status IN ('待处理','处理中') AND reported_at < date('now', '-7 days')"
            ).fetchone()
            stale_n = stale["cnt"] if stale else 0

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


# -- AI Chat — 核心端点 --

class FakeSession(dict):
    """Session-like object that supports both dict and attribute access.

    Streamlit's session_state uses attribute-style access (st.xxx), so
    FakeSession must support both st["key"] (dict) and st.key (attribute).
    """

    def __getattr__(self, key: str):
        """Support st.key access — raises AttributeError on missing keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"FakeSession has no attribute '{key}'")

    def __setattr__(self, key: str, value):
        """Support st.key = value — only for non-dunder keys."""
        if key.startswith("_"):
            super().__setattr__(key, value)
        else:
            self[key] = value

    def __contains__(self, key):
        """Support 'key' in st check that Streamlit session_state relies on."""
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

    from agent.engine import CampusAgent
    _agent = CampusAgent(fake_st)
    return _agent


@app.post("/api/chat", tags=["智能对话"])
def agent_chat(req: ChatRequest):
    """智能对话 —— 完整 OODA 治理工作流。

    扣子把用户消息传过来，Agent 自动判断意图、调用工具、返回回复。
    扣子 Bot 中把此端点配置为插件的 API 即可。
    """
    try:
        agent = _get_agent()
        if req.student_id:
            agent.memory.st["user_profile"] = {
                "name": req.student_id,
                "student_id": req.student_id,
                "school": "校园先知",
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
        if req.student_id:
            fake_st["user_profile"] = {
                "name": req.student_id,
                "student_id": req.student_id,
                "school": "校园先知",
            }

        agent = OfflineAgent(fake_st)
        response = agent.run(req.message)
        return {
            "success": True,
            "data": {"reply": response, "mode": "offline"},
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -- Feedback --

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


# -- OpenAPI 导出（扣子插件用） --

@app.get("/openapi.json", tags=["系统"], include_in_schema=False)
def export_openapi():
    """导出 OpenAPI 3.0 schema，可直接导入扣子插件"""
    schema = app.openapi()
    schema["info"]["title"] = "CampusInsight Agent"
    schema["info"]["description"] = (
        "校园先知 —— 校园微治理平台。提供工单上报/查询、提案管理、"
        "议题讨论、天气、校园脉搏、治理健康度、智能对话等能力。"
    )
    return schema


# -- Entrypoint --

if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="CampusInsight Agent API")
    parser.add_argument("--port", type=int, default=18800)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    print(f"""
   CampusInsight Agent API v2.0
   http://{args.host}:{args.port}
   文档: http://localhost:{args.port}/docs
   OpenAPI: http://localhost:{args.port}/openapi.json
   公网: ngrok http {args.port}
    """)

    uvicorn.run(app, host=args.host, port=args.port)
