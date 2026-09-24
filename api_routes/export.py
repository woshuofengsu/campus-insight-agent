# api_routes/export.py
"""导出路由模块（从 api_web.py 拆出，P2-04 / P1-F2-01）：统一 CSV，脱敏 + 留痕。"""
from fastapi import APIRouter, Request
from fastapi.responses import Response

from api_routes.deps import _user, _require_role, _tenant

router = APIRouter(prefix="/api/web/export", tags=["export"])


def _csv_response(buf, fname: str) -> Response:
    """utf-8-sig CSV 下载响应。"""
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/issues")
def export_issues(request: Request):
    """导出报修工单 CSV（负责人，脱敏，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_repair import get_issues
    from data.db_notifications import log_activity
    import csv
    from io import StringIO
    rows = get_issues(limit=1000, tenant=_tenant(request))
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["编号", "标题", "分类", "类型", "紧急度", "状态", "地址", "报修人", "电话", "维修人员", "提交时间"])
    for r in rows:
        p = r.get("reporter_phone") or ""
        w.writerow([r.get("id"), r.get("title"), r.get("category"), r.get("issue_type"),
                    r.get("urgency"), r.get("status"), r.get("location"),
                    r.get("reporter_name"), (p[:3] + "****" + p[-4:]) if len(p) == 11 else "****",
                    r.get("assignee_name") or "", (r.get("reported_at") or "")[:16]])
    log_activity(_user(request).get("name") or "负责人", "导出工单数据", module="报修",
                 detail=f"导出 {len(rows)} 条（脱敏，不含照片附件）")
    return _csv_response(buf, "issues.csv")


@router.get("/proposals")
def export_proposals(request: Request):
    """导出提案 CSV（负责人，含排名/脱敏，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_proposal import get_export_rows, log_export
    import csv
    from io import StringIO
    rows = get_export_rows(tenant=_tenant(request))
    buf = StringIO()
    if rows:
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    log_export(actor=_user(request).get("name") or "负责人")
    return _csv_response(buf, "proposals.csv")


@router.get("/notices")
def export_notices(request: Request):
    """导出通知列表 + 已读统计（负责人，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_notice import export_notices_csv
    content, fname = export_notices_csv(actor=_user(request).get("name") or "负责人",
                                        tenant=_tenant(request))
    return Response(content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/knowledge")
def export_knowledge(request: Request):
    """导出政策知识库 CSV（负责人，脱敏留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_policy import get_knowledge_list
    from data.db_notifications import log_activity
    import csv
    from io import StringIO
    rows = get_knowledge_list(limit=1000)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "标题", "分类", "状态", "版本", "有效期", "引用次数", "更新时间"])
    for k in rows:
        w.writerow([k.get("id"), (k.get("title") or "")[:40], k.get("category"),
                    k.get("audit_status"), k.get("version") or 1,
                    f"{k.get('effective_date') or ''}~{k.get('expire_date') or ''}",
                    k.get("cite_count") or 0, (k.get("updated_at") or k.get("created_at") or "")[:16]])
    log_activity(_user(request).get("name") or "负责人", "导出知识库", module="政策问答",
                 detail=f"导出 {len(rows)} 条（不含正文全文与审核意见）")
    return _csv_response(buf, "knowledge.csv")


@router.get("/health-contents")
def export_health_contents(request: Request):
    """导出健康内容 CSV（负责人，脱敏留痕，不含附件与内部备注）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import export_contents_csv
    content, fname = export_contents_csv(actor=_user(request).get("name") or "负责人")
    return Response(content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/health-consults")
def export_health_consults(request: Request):
    """导出健康咨询 CSV（负责人，电话脱敏留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_health_content import export_consults_csv
    content, fname = export_consults_csv(actor=_user(request).get("name") or "负责人",
                                         tenant=_tenant(request))
    return Response(content.encode("utf-8-sig"), media_type="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


@router.get("/weather-tasks")
def export_weather_tasks(request: Request):
    """导出天气检查任务记录 CSV（负责人，留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_weather import list_check_tasks
    from data.db_notifications import log_activity
    import csv
    from io import StringIO
    rows = list_check_tasks(limit=1000, tenant=_tenant(request))
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["编号", "预警类型", "等级", "状态", "确认人", "备注", "检查时间", "创建时间"])
    for r in rows:
        w.writerow([r.get("id"), r.get("alert_type"), r.get("level"), r.get("status"),
                    r.get("checker") or "", r.get("note") or "",
                    (r.get("checked_at") or "")[:16], (r.get("created_at") or "")[:16]])
    log_activity(_user(request).get("name") or "负责人", "导出天气检查任务",
                 module="天气", detail=f"导出 {len(rows)} 条检查任务记录")
    return _csv_response(buf, "weather-tasks.csv")


@router.get("/agent-logs")
def export_agent_logs(request: Request):
    """导出 Agent 留痕 CSV（负责人，脱敏——不含完整手机号，导出本身留痕）。"""
    if _require_role(request, "grid"):
        return _require_role(request, "grid")
    from data.db_agent import get_agent_logs
    from data.db_notifications import log_activity
    import csv
    from io import StringIO
    rows = get_agent_logs(limit=1000, tenant=_tenant(request))
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["ID", "角色", "用户输入", "纠正后", "识别意图", "路由结果", "状态", "异常", "关联编号", "时间"])
    for r in rows:
        w.writerow([r.get("id"), r.get("role"), (r.get("user_input") or "")[:80],
                    (r.get("corrected") or "")[:80], r.get("intent"), r.get("routed"),
                    r.get("status"), (r.get("error") or "")[:80], r.get("related_id"),
                    (r.get("created_at") or "")[:16]])
    log_activity(_user(request).get("name") or "负责人", "导出Agent留痕",
                 module="Agent", detail=f"导出 {len(rows)} 条（脱敏）")
    return _csv_response(buf, "agent-logs.csv")
