# api_routes/weather.py
"""天气历史 / 社区概况 / 预报 / 检查任务路由（从 api_web.py 拆出）。"""
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api_routes.deps import _ok, _fail, _user, _require_role

router = APIRouter(prefix="/api/web/weather", tags=["weather"])


# ---------------- 天气历史 / 社区概况 ----------------

@router.get("/history")
def web_weather_history(request: Request, status: str = "", limit: int = 200):
    """负责人端天气检查任务历史。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_weather import get_check_task_history
    rows = get_check_task_history(status=status or None, limit=limit)
    return _ok([dict(r) for r in rows])


@router.get("/overview")
def web_weather_overview(request: Request, limit: int = 50):
    """负责人端所有社区天气概况。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_weather import get_community_weather_overview
    return _ok(get_community_weather_overview(limit=limit))


@router.get("/exception-logs")
def web_weather_exception_logs(request: Request, limit: int = 100):
    """负责人端异常日志（天气等系统异常单独记录 7 天）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_core import get_db
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, created_at, module, error, detail FROM exception_log "
            "ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return _ok([dict(r) for r in rows])


# ---- 天气预报独立端点 ----

@router.get("/forecast")
def web_weather_forecast(request: Request, days: int = 3):
    from data.db_weather import get_weather_for_display
    w = get_weather_for_display("")
    return _ok({"forecast": (w.get("days") or [])[:days], "is_degraded": w.get("is_degraded")})


@router.get("/current")
def web_weather_current(request: Request):
    from data.db_weather import get_weather_for_display, get_daily_advice
    from config import COMMUNITY_CITY, COMMUNITY_DISTRICT
    w = get_weather_for_display("")
    days = w.get("days") or []
    today = days[0] if days else {}
    advice = {}
    try:
        advice = get_daily_advice(city="") or {}
    except Exception:
        pass
    return _ok({
        "location": COMMUNITY_CITY + COMMUNITY_DISTRICT,
        "temp_high": today.get("temp_high"), "temp_low": today.get("temp_low"),
        "condition": today.get("condition"), "emoji": today.get("emoji"),
        "wind": today.get("wind"), "rain_prob": today.get("rain_prob"),
        "humidity": today.get("humidity"), "aqi": today.get("aqi"), "uv": today.get("uv"),
        "advice": today.get("advice"),
        "dress": advice.get("dress", ""), "travel": advice.get("travel", ""),
        "updated_at": w.get("data_updated_at") or "",
        "forecast": days[1:4],
        "is_degraded": w.get("is_degraded"), "note": w.get("note", ""),
    })


@router.get("/alerts")
def web_weather_alerts(request: Request):
    from utils.cache import cached_active_alerts
    return _ok(cached_active_alerts())


class CheckTaskConfirm(BaseModel):
    checker: str = Field(default="")
    items: list = Field(default_factory=list)
    note: str = Field(default="")


@router.post("/check-task/{task_id}/confirm")
def web_check_task_confirm(task_id: int, req: CheckTaskConfirm, request: Request):
    from data.db_weather import confirm_check_task, fill_overdue_task
    from data.db_weather import list_check_tasks
    from utils.cache import invalidate_weather
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    actor = _user(request).get("name") or "负责人"
    rows = list_check_tasks(limit=1000)
    row = next((t for t in rows if t["id"] == task_id), None)
    if not row:
        return _fail(1004, "检查任务不存在")
    if row["status"] == "待检查":
        ok_, msg = confirm_check_task(task_id, req.checker or actor, req.items, req.note, actor=actor)
    elif row["status"] == "超时未确认":
        ok_, msg = fill_overdue_task(task_id, req.checker or actor, req.items, req.note, actor=actor)
    else:
        return _fail(2001, f"当前状态「{row['status']}」不支持确认")
    if not ok_:
        return _fail(2001, msg)
    invalidate_weather()
    return _ok({"task_id": task_id}, "已确认")


@router.get("/tasks")
def web_weather_tasks(request: Request, status: str = ""):
    from data.db_weather import list_check_tasks
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    rows = list_check_tasks(status=status or None, limit=200)
    return _ok([dict(r) for r in rows])
