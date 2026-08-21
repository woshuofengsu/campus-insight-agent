"""🌤️ 天气管理（负责人端）— 所有社区天气概况、极端天气检查任务、历史检查记录。

按《03-天气.md》第七节负责人后台标准输出实现：
1. 顶部滚动提醒（极端天气类型、预警等级、生效时间；可临时关闭，每次登录或每 6 小时再次出现）；
2. 所有社区天气概况（社区名、当前天气、温度、预警标签；支持搜索）；
3. 极端天气检查任务卡片：天气类型、预警等级、检查清单（逐项勾选 已检查/正常/异常 + 备注）、
   任务状态（待检查/已确认/超时未确认）、剩余确认时间（3 小时倒计时：
   >1 小时绿色、<1 小时红色、超时灰色）、确认已检查 / 超时补填（保留超时标记）、超时升级状态；
4. 历史检查任务记录（时间、天气类型、预警等级、检查人、检查结果、备注、是否超时；支持筛选）。
"""
import json
import logging
from datetime import datetime

import streamlit as st

from ui.guard import require_role

require_role("grid")

from ui.components import TOKEN, page_header, section, stat  # noqa: E402
from data.db_weather import (  # noqa: E402  数据层，只调用不写 SQL
    get_community_weather_overview,
    list_check_tasks,
    get_check_task_history,
    get_task_remaining_hours,
    confirm_check_task,
    fill_overdue_task,
    mark_overdue_tasks,
    get_escalation_status,
    get_reminder_banner_data,
    get_checklist,
    ALERT_TEXTS,
    MODULE,
)
from data.db_notifications import log_activity  # noqa: E402

_log = logging.getLogger(__name__)

page_header("🌤️ 天气管理", "所有社区天气概况 · 极端天气检查任务 · 历史检查记录。")

_memory = st.session_state.get("memory")
_profile = _memory.get_user_profile() if _memory is not None else (st.session_state.get("user_profile") or {})
_actor = (_profile.get("name") or "").strip() or "负责人"
_uid = _profile.get("id") or 0

# 状态自动流转：3 小时未确认 → 标记"超时未确认"（幂等，留痕）
try:
    mark_overdue_tasks()
except Exception:
    _log.debug("标记超时任务失败", exc_info=True)

_LEVEL_COLORS = {"黄色": "#eab308", "橙色": "#f97316", "红色": "#dc2626"}
_BANNER_HIDE_HOURS = 6


def _banner_key() -> str:
    return f"_weather_mgmt_banner_closed_{_uid or 0}"


def _render_banner() -> None:
    """负责人端顶部滚动提醒（可临时关闭，每次登录或每 6 小时再次出现）。"""
    alerts = get_reminder_banner_data()
    if not alerts:
        return
    closed_at = st.session_state.get(_banner_key())
    try:
        if closed_at and (datetime.now() - datetime.fromisoformat(str(closed_at))).total_seconds() < _BANNER_HIDE_HOURS * 3600:
            return
    except Exception:
        pass

    has_red = any(a.get("level") == "红色" for a in alerts)
    bg = "#dc2626" if has_red else "#d97706"
    parts = []
    for a in alerts:
        eff = (a.get("effective_time") or "")[:16]
        text = ALERT_TEXTS.get(a.get("alert_type", ""), "")
        parts.append(
            f'<span style="margin:0 32px;color:#ffffff;white-space:nowrap;">'
            f'⚠️ <b>{a.get("alert_type","")}{a.get("level","")}预警</b>'
            f'<span style="opacity:0.85;">（生效 {eff}）</span> {text}</span>'
        )
    st.markdown(
        '<style>'
        '@keyframes weather-marquee2 { 0% {transform: translateX(100%);} '
        '100% {transform: translateX(-100%);} }'
        '.weather-marquee2-wrap { overflow:hidden; border-radius:12px; }'
        '.weather-marquee2 { display:inline-block; padding-left:100%; '
        'animation: weather-marquee2 20s linear infinite; white-space:nowrap; }'
        '</style>',
        unsafe_allow_html=True,
    )
    c_banner, c_close = st.columns([8, 1])
    with c_banner:
        st.markdown(
            f'<div class="weather-marquee2-wrap" style="background:{bg};padding:8px 0;">'
            f'<div class="weather-marquee2">{"".join(parts)}</div></div>',
            unsafe_allow_html=True,
        )
    with c_close:
        if st.button("✕ 关闭", key="weather_mgmt_banner_close", width="stretch",
                     help="临时关闭滚动提醒，每次登录或每 6 小时再次出现"):
            st.session_state[_banner_key()] = datetime.now().isoformat()
            st.rerun()


# 滚动提醒已由 app.py 全局注入，这里不再重复渲染


def _level_pill(alert_type: str, level: str) -> str:
    color = _LEVEL_COLORS.get(level, "#eab308")
    return (
        f'<span style="display:inline-block;background:{color};color:#ffffff;'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 10px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_bold"]};'
        f'white-space:nowrap;">{alert_type}{level}预警</span>'
    )


def _status_badge(status: str) -> str:
    color = {"待检查": "#d97706", "已确认": "#059669", "超时未确认": "#64748b"}.get(status, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}1a;border:1px solid {color};'
        f'color:{color};border-radius:999px;padding:1px 10px;font-size:0.78em;'
        f'font-weight:600;white-space:nowrap;">{status}</span>'
    )


def _remaining_html(remain: dict) -> str:
    """剩余确认时间：>1 小时绿色、<1 小时红色、超时灰色（《03-天气.md》）。"""
    rh = remain.get("remaining_hours")
    if rh is None:
        return f'<span style="color:{TOKEN["text_muted"]};">倒计时 —</span>'
    if remain.get("overdue"):
        return f'<span style="color:{TOKEN["text_muted"]};">已超时 {abs(rh):.1f} 小时</span>'
    color = TOKEN["success"] if remain.get("urgency") == "ok" else TOKEN["danger"]
    return f'<span style="color:{color};font-weight:700;">剩余 {rh:.1f} 小时</span>'


def _escalation_html(esc: dict) -> str:
    if not esc.get("escalated"):
        return ""
    if esc.get("state") == "cannot_upgrade":
        return (
            f'<div style="font-size:0.8em;color:{TOKEN["danger"]};margin-top:4px;">'
            f'🚨 超时升级：未配置更高级负责人，持续提醒在线负责人，保持最高优先级告警'
            f'（{esc.get("escalated_at","")[:16]}）</div>'
        )
    if esc.get("state") == "notify_failed":
        return (
            f'<div style="font-size:0.8em;color:{TOKEN["danger"]};margin-top:4px;">'
            f'🚨 升级通知失败：紧急天气检查任务等待人工介入（{esc.get("detail","")}）</div>'
        )
    return (
        f'<div style="font-size:0.8em;color:{TOKEN["warning"]};margin-top:4px;">'
        f'⏫ 已升级通知在线负责人（{esc.get("escalated_at","")[:16]}）：{esc.get("detail","")}</div>'
    )


# ============================================================
# 一、所有社区天气概况
# ============================================================
section("🌍 所有社区天气概况")

overview = get_community_weather_overview(limit=50)
if not overview:
    st.info("暂无社区天气数据（请先在天气数据源接入后刷新）。")
else:
    kw = st.text_input("🔍 搜索社区", placeholder="输入社区名称筛选...", key="weather_overview_search",
                       label_visibility="collapsed")
    kw = (kw or "").strip()
    shown = [o for o in overview if not kw or kw in (o.get("city") or "")]
    if not shown:
        st.caption("没有匹配的社区。")
    for o in shown:
        tags = ""
        if o.get("alert_tags"):
            tags = "".join(
                _level_pill(t["type"], t["level"]) for t in o["alert_tags"]
            ) + " "
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])
            with c1:
                st.markdown(
                    f'<span style="font-weight:700;color:{TOKEN["text"]};">📍 {o.get("city") or "默认社区"}</span>'
                    f'&nbsp;{tags}',
                    unsafe_allow_html=True,
                )
            with c2:
                st.markdown(
                    f'<div style="text-align:right;font-size:0.9em;color:{TOKEN["text"]};">'
                    f'{o.get("condition") or "—"}</div>',
                    unsafe_allow_html=True,
                )
            with c3:
                st.markdown(
                    f'<div style="text-align:right;font-weight:700;color:{TOKEN["text"]};">'
                    f'{o.get("temp_low") or "—"}°~{o.get("temp_high") or "—"}°</div>',
                    unsafe_allow_html=True,
                )
            st.caption(f'更新于 {o.get("updated_at") or "—"}')

st.markdown("---")

# ============================================================
# 二、极端天气检查任务
# ============================================================
section("🧾 极端天气检查任务")

all_tasks = list_check_tasks(limit=100)
pending = [t for t in all_tasks if t.get("status") in ("待检查", "超时未确认")]
confirmed = [t for t in all_tasks if t.get("status") == "已确认"]

c1, c2, c3 = st.columns(3)
with c1:
    stat("待检查", str(len([t for t in pending if t.get("status") == "待检查"])), TOKEN["warning"], sub="3小时内需确认")
with c2:
    stat("超时未确认", str(len([t for t in pending if t.get("status") == "超时未确认"])), TOKEN["danger"], sub="可补填，保留标记")
with c3:
    stat("已确认", str(len(confirmed)), TOKEN["success"], sub="全部任务")

if not pending:
    st.success("🎉 当前没有待处理的极端天气检查任务。")
else:
    for t in pending:
        tid = t["id"]
        status = t.get("status", "待检查")
        remain = get_task_remaining_hours(tid)
        esc = get_escalation_status(tid)
        try:
            checklist = json.loads(t.get("checklist_json") or "[]")
        except (ValueError, TypeError):
            checklist = get_checklist(t.get("alert_type", ""))
            checklist = [{"item": it, "status": "未检查", "note": ""} for it in checklist]

        with st.container(border=True):
            st.markdown(
                f'<span style="font-weight:700;color:{TOKEN["text"]};">'
                f'任务 #{tid}</span>&nbsp;'
                f'{_level_pill(t.get("alert_type",""), t.get("level",""))}&nbsp;'
                f'{_status_badge(status)}&nbsp;'
                f'{_remaining_html(remain)}',
                unsafe_allow_html=True,
            )
            st.caption(f'创建时间：{t.get("created_at") or "—"} · 检查人：{t.get("checker") or "（未确认）"}'
                       f'{" · 备注：" + str(t.get("note")) if t.get("note") else ""}')
            st.markdown(_escalation_html(esc), unsafe_allow_html=True)

            items: list[dict] = []
            with st.form(key=f"weather_task_form_{tid}"):
                st.markdown("**检查清单（逐项勾选并填写备注）**")
                for i, item in enumerate(checklist):
                    item_name = item.get("item", f"检查项{i + 1}")
                    st.markdown(f'<span style="font-size:0.85em;font-weight:600;color:{TOKEN["text"]};">'
                                f'{i + 1}. {item_name}</span>', unsafe_allow_html=True)
                    ic1, ic2 = st.columns([2, 2])
                    with ic1:
                        s = st.selectbox("状态", ["已检查", "正常", "异常"],
                                         key=f"wti_{tid}_{i}", label_visibility="collapsed")
                    with ic2:
                        n = st.text_input("备注", key=f"wtn_{tid}_{i}", placeholder="（可选）",
                                          label_visibility="collapsed")
                    items.append({"item": item_name, "status": s, "note": (n or "").strip()})
                note = st.text_input("总体备注", key=f"wt_note_{tid}", placeholder="填写检查结果和备注（可选）")
                checker = st.text_input("检查人", value=_actor, key=f"wt_checker_{tid}")
                submit_label = "✅ 确认已检查" if status == "待检查" else "📝 补填检查结果（保留超时标记）"
                submitted = st.form_submit_button(submit_label, width="stretch")

            if submitted:
                ok, msg = (
                    confirm_check_task(tid, (checker or "").strip() or _actor, items, note or "", actor=_actor)
                    if status == "待检查"
                    else fill_overdue_task(tid, (checker or "").strip() or _actor, items, note or "", actor=_actor)
                )
                if ok:
                    st.toast(f"任务 #{tid} 已确认" if status == "待检查" else f"任务 #{tid} 已补填（保留超时标记）", icon="✅")
                    st.rerun()
                else:
                    st.error(msg)

st.markdown("---")

# ============================================================
# 三、历史检查任务记录
# ============================================================
section("📜 历史检查任务记录")

hf1, hf2, hf3 = st.columns(3)
with hf1:
    h_type = st.selectbox("天气类型", ["全部", "暴雨", "台风", "高温", "寒潮", "大风", "雷电", "冰雹", "大雾"],
                          key="weather_history_type")
with hf2:
    h_status = st.selectbox("任务状态", ["全部", "待检查", "已确认", "超时未确认"], key="weather_history_status")
with hf3:
    h_period = st.selectbox("时间范围", ["全部", "近7天", "近30天"], key="weather_history_period")

history = get_check_task_history(
    alert_type=None if h_type == "全部" else h_type,
    status=None if h_status == "全部" else h_status,
    limit=200,
)
# 时间范围过滤（spec 03.17：支持按时间筛选）
if h_period != "全部":
    from datetime import datetime, timedelta
    _cut = (datetime.now() - timedelta(days={"近7天": 7, "近30天": 30}[h_period])).strftime("%Y-%m-%d %H:%M:%S")
    history = [t for t in history if (t.get("created_at") or "") >= _cut]
if not history:
    st.caption("暂无历史检查任务记录。")
else:
    rows = []
    for t in history:
        try:
            result = json.loads(t.get("result") or "[]")
        except (ValueError, TypeError):
            result = []
        abnormal = sum(1 for r in result if r.get("status") == "异常")
        normal = sum(1 for r in result if r.get("status") in ("已检查", "正常"))
        if result:
            result_txt = f"{len(result)} 项检查 · 正常 {normal} · 异常 {abnormal}"
        elif t.get("status") == "待检查":
            result_txt = "（未检查）"
        else:
            result_txt = "—"
        rows.append({
            "任务ID": t["id"],
            "时间": (t.get("created_at") or "")[:16],
            "天气类型": f"{t.get('alert_type','')}{t.get('level','')}",
            "状态": t.get("status", ""),
            "检查人": t.get("checker") or "—",
            "检查结果": result_txt,
            "备注": (t.get("note") or "")[:40],
            "是否超时": "是" if t.get("status") == "超时未确认" else "否",
        })
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption("说明：超时任务补填后仍保留「超时未确认」标记，检查人与结果可查。")

    # 导出检查任务记录（spec：负责人可导出天气检查任务记录）
    import csv as _csv
    from io import StringIO as _StringIO
    _buf = _StringIO()
    _w = _csv.DictWriter(_buf, fieldnames=list(rows[0].keys()))
    _w.writeheader()
    _w.writerows(rows)
    st.download_button(
        "⬇️ 导出检查任务记录 CSV",
        data=_buf.getvalue().encode("utf-8-sig"),
        file_name="天气检查任务记录.csv",
        mime="text/csv",
        key="weather_tasks_export",
        on_click=lambda: log_activity(_actor, "导出天气检查任务记录", module=MODULE,
                                      detail="含时间/类型/状态/检查人/结果"),
    )

st.markdown("---")
section("🛠️ 天气异常日志（近 7 天）")
try:
    from data.db_core import get_db as _get_db
    with _get_db() as _conn:
        _errs = _conn.execute(
            "SELECT id, created_at, module, error, detail FROM exception_log "
            "WHERE module LIKE '%天气%' OR detail LIKE '%天气%' "
            "ORDER BY id DESC LIMIT 50"
        ).fetchall()
    if not _errs:
        st.caption("近 7 天无天气相关异常记录。")
    else:
        _err_rows = [{
            "时间": (r["created_at"] or "")[:16],
            "模块": r["module"] or "",
            "错误": (r["error"] or "")[:60],
            "详情": (r["detail"] or "")[:80],
        } for r in _errs]
        st.dataframe(_err_rows, width="stretch", hide_index=True)
        import csv as _csv2
        from io import StringIO as _StringIO2
        _buf2 = _StringIO2()
        _w2 = _csv2.DictWriter(_buf2, fieldnames=list(_err_rows[0].keys()))
        _w2.writeheader()
        _w2.writerows(_err_rows)
        st.download_button(
            "⬇️ 导出天气异常日志 CSV",
            data=_buf2.getvalue().encode("utf-8-sig"),
            file_name="天气异常日志.csv",
            mime="text/csv",
            key="weather_err_export",
            on_click=lambda: log_activity(_actor, "导出天气异常日志", module=MODULE),
        )
except Exception:
    st.caption("异常日志读取失败。")
