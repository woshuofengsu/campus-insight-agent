"""🏥 疾病预防（居民端）— 健康内容卡片、天气联动提醒、健康咨询。

按《04-疾病预防.md》第七节居民端标准输出实现：
1. 顶部天气联动提醒卡片区（带"天气提醒"标签，按优先级最多 3 张，其余折叠；
   可临时关闭，重新登录或每 6 小时再次出现）；
2. 内容分类标签（季节性疾病预防/疫苗接种提醒/传染病预警/健康小贴士/就医指引）；
3. 内容卡片列表（标题、内容类型、来源、发布时间、是否置顶；置顶角标排最前，
   其余按发布时间倒序；社区自编正文开头带免责声明；不显示审核人姓名）；
4. "我要咨询"表单（姓名/电话/类型 5 选 1/内容 5-500 字/所属楼栋选填）+ 紧急症状提示；
5. "我的咨询"列表（撤回/重新打开/反馈/关闭）+ 未读回复徽标。
"""
import logging
from datetime import datetime

import streamlit as st

from ui.session_state import SS
from ui.components import TOKEN, page_header, section, info_card

_log = logging.getLogger(__name__)

page_header("🏥 疾病预防", "季节性疾病预防知识 · 疫苗接种提醒 · 健康咨询。", "防")

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else (st.session_state.get("user_profile") or {})
uid = profile.get("id") or st.session_state.get(SS.login_user_id, 0)
community = (profile.get("community") or "").strip()

if not uid:
    st.info("请先登录。")
    st.stop()
if not community:
    st.info("提示：请先绑定所属社区，天气联动提醒将按社区天气触发。")

from data.db_health_content import (  # noqa: E402  数据层，只调用不写 SQL
    CONTENT_TYPES,
    CONSULT_TYPES,
    EMERGENCY_HINT,
    LINKAGE_PRIORITY,
    get_published_contents,
    get_content,
    submit_consult,
    get_my_consults,
    get_unread_reply_count,
    withdraw_consult,
    reopen_consult,
    feedback_consult,
    close_consult,
    trigger_weather_linkage,
    get_linkage_records,
    log_emergency_hint_shown,
)

# 咨询状态颜色（《04-疾病预防.md》：待回复/超时未回复红黄、已回复/继续回复蓝、结束/关闭灰）
_CONSULT_COLORS = {
    "待回复": "#d97706",
    "超时未回复": "#dc2626",
    "已回复": "#2563eb",
    "继续回复": "#2563eb",
    "已结束": "#64748b",
    "已关闭": "#64748b",
    "已撤回": "#64748b",
}
_LINKAGE_HIDE_HOURS = 6


def _consult_tag(status: str) -> str:
    color = _CONSULT_COLORS.get(status, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}1a;border:1px solid {color};'
        f'color:{color};border-radius:999px;padding:1px 10px;font-size:0.78em;'
        f'font-weight:600;white-space:nowrap;">{status}</span>'
    )


def _type_pill(content_type: str) -> str:
    return (
        f'<span style="display:inline-block;background:{TOKEN["accent_bg"]};'
        f'color:{TOKEN["accent"]};border:1px solid {TOKEN["accent_border"]};'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 10px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">{content_type}</span>'
    )


def _pinned_badge() -> str:
    return (
        f'<span style="display:inline-block;background:{TOKEN["warning_bg"]};'
        f'color:{TOKEN["warning"]};border:1px solid {TOKEN["warning_border"]};'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">📌 置顶</span>'
    )


# ============================================================
# 一、天气联动提醒卡片（顶部）
# ============================================================

def _current_weather_event() -> dict:
    """由当前天气数据推导联动事件（预警优先，其次气温阈值）。"""
    try:
        from data.db_weather import get_active_alerts, get_weather_for_display
        alerts = get_active_alerts()
        if alerts:
            top = alerts[0]
            return {"alert_type": top.get("alert_type", ""), "level": top.get("level", "")}
        if community:
            w = get_weather_for_display(community)
            days = w.get("days") or []
            if days:
                d = days[0]
                drop = 0
                if len(days) > 1:
                    try:
                        drop = int(days[1].get("temp_high") or 0) - int(d.get("temp_high") or 0)
                    except (TypeError, ValueError):
                        drop = 0
                return {"temp_high": d.get("temp_high"), "temp_low": d.get("temp_low"),
                        "temp_drop_24h": drop}
    except Exception:
        _log.debug("推导天气联动事件失败", exc_info=True)
    return {}


def _linkage_from_records() -> list[dict]:
    """从联动留痕恢复今天的已触发内容（触发后当日幂等，防止再次调用返回空）。"""
    today = datetime.now().strftime("%Y-%m-%d")
    cards: list[dict] = []
    seen: set[int] = set()
    try:
        for rec in get_linkage_records(limit=50):
            if rec.get("action") != "联动提醒触发":
                continue
            if not str(rec.get("created_at") or "").startswith(today):
                continue
            cid = rec.get("target_id")
            if cid in seen:
                continue
            c = get_content(cid) if cid else None
            if c and c.get("status") == "已发布":
                seen.add(cid)
                cards.append(c)
    except Exception:
        _log.debug("从联动留痕恢复卡片失败", exc_info=True)
    return cards


def _linkage_triggered_today_already() -> bool:
    """当天是否已触发过联动（监测端或本页），避免重复调用数据层触发造成重复通知。"""
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        return any(
            r.get("action") == "联动提醒触发" and str(r.get("created_at") or "").startswith(today)
            for r in get_linkage_records(limit=100)
        )
    except Exception:
        _log.debug("检查当天联动触发状态失败", exc_info=True)
        return False


def _get_linkage_cards() -> list[dict]:
    """当天联动卡片：触发结果优先，留痕兜底，按优先级排序。"""
    today = datetime.now().strftime("%Y-%m-%d")
    cache_key = f"_health_linkage_cards_{today}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    cards: list[dict] = []
    if not _linkage_triggered_today_already():
        event = _current_weather_event()
        if event:
            try:
                result = trigger_weather_linkage(event, actor="系统")
                cards.extend(result.get("triggered") or [])
            except Exception:
                _log.debug("触发天气联动失败", exc_info=True)
    # 兜底：从当天留痕恢复（同日去重后 trigger 返回空的情况）
    for c in _linkage_from_records():
        if c["id"] not in {x["id"] for x in cards}:
            cards.append(c)

    cards.sort(key=lambda c: LINKAGE_PRIORITY.index(c["content_type"])
               if c["content_type"] in LINKAGE_PRIORITY else 99)
    st.session_state[cache_key] = cards
    return cards


def _linkage_visible() -> bool:
    key = f"_health_linkage_closed_{uid or 0}"
    closed_at = st.session_state.get(key)
    if not closed_at:
        return True
    try:
        return (datetime.now() - datetime.fromisoformat(str(closed_at))).total_seconds() >= _LINKAGE_HIDE_HOURS * 3600
    except Exception:
        return True


linkage_cards = _get_linkage_cards()
if linkage_cards and _linkage_visible():
    section("☁️ 天气联动提醒")
    shown = linkage_cards[:3]
    folded = linkage_cards[3:]
    for c in shown:
        with st.container(border=True):
            st.markdown(
                f'<span style="display:inline-block;background:{TOKEN["info_bg"]};'
                f'color:{TOKEN["info"]};border:1px solid {TOKEN["info_border"]};'
                f'border-radius:{TOKEN["radius_full"]};padding:1px 10px;'
                f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
                f'white-space:nowrap;">🌤️ 天气提醒</span>'
                f'&nbsp;<span style="font-weight:700;color:{TOKEN["text"]};">{c.get("title","")}</span>'
                f'&nbsp;{_type_pill(c.get("content_type",""))}',
                unsafe_allow_html=True,
            )
            body = c.get("body", "")
            preview = body[:120] + ("…" if len(body) > 120 else "")
            st.markdown(
                f'<div style="font-size:0.85em;color:{TOKEN["text_sec"]};line-height:1.6;">'
                f'{preview}</div>',
                unsafe_allow_html=True,
            )
            st.caption(f'来源：{c.get("source") or "—"} · 发布时间：{(c.get("published_at") or c.get("created_at") or "")[:16]}')
    if folded:
        with st.expander(f"📚 还有 {len(folded)} 条联动提醒（已折叠）"):
            for c in folded:
                st.markdown(f"**{c.get('title','')}** · {_type_pill(c.get('content_type',''))}")
                st.caption((c.get("body") or "")[:100])
    cc1, cc2 = st.columns([6, 1])
    with cc2:
        if st.button("✕ 暂时关闭", key="health_linkage_close", width="stretch",
                     help="临时关闭联动提醒，重新登录或每 6 小时再次出现"):
            st.session_state[f"_health_linkage_closed_{uid or 0}"] = datetime.now().isoformat()
            st.rerun()

st.markdown("---")

# ============================================================
# 二、健康内容卡片（分类筛选）
# ============================================================
section("📚 健康知识")

cat_options = ["全部"] + CONTENT_TYPES
sel_cat = st.radio("内容分类", cat_options, horizontal=True, key="health_cat_filter",
                   label_visibility="collapsed")

contents = get_published_contents(content_type=None if sel_cat == "全部" else sel_cat, limit=100)
if not contents:
    info_card("暂无已发布的健康内容", "负责人发布并审核通过后，内容会显示在这里")
else:
    for c in contents:
        with st.container(border=True):
            st.markdown(
                f'{"📌 " if c.get("is_pinned") else ""}'
                f'<span style="font-weight:700;color:{TOKEN["text"]};">{c.get("title","")}</span>'
                + (f'&nbsp;{_pinned_badge()}' if c.get("is_pinned") else "")
                + f'&nbsp;{_type_pill(c.get("content_type",""))}'
                + f'&nbsp;<span style="display:inline-block;background:{TOKEN["success_bg"]};'
                  f'color:{TOKEN["success"]};border:1px solid {TOKEN["success_border"]};'
                  f'border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
                  f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
                  f'white-space:nowrap;">✓ 已审核</span>',
                unsafe_allow_html=True,
            )
            st.caption(
                f'来源：{c.get("source") or "—"} · 发布时间：{(c.get("published_at") or c.get("created_at") or "")[:16]}'
                + (f' · 信息有效期：{c.get("expire_at") or ""}' if c.get("expire_at") else "")
            )
            body = c.get("body", "")
            with st.expander("查看正文"):
                st.markdown(body)
                if c.get("weather_link"):
                    st.caption(f'联动天气：{"、".join(c["weather_link"])}')

st.markdown("---")

# ============================================================
# 三、健康咨询
# ============================================================
section("💬 健康咨询")

unread = get_unread_reply_count(uid)
sub_title = f'🩺 我要咨询' if unread == 0 else f'🩺 我要咨询　🔔 未读回复 {unread} 条'

tab_ask, tab_mine = st.tabs([sub_title, "📋 我的咨询"])

# ---------- 我要咨询 ----------
with tab_ask:
    st.markdown(
        f'<div style="background:{TOKEN["danger_bg"]};border:1px solid {TOKEN["danger_border"]};'
        f'border-radius:{TOKEN["radius_card"]};padding:10px 14px;margin-bottom:10px;">'
        f'<span style="font-size:0.85em;color:{TOKEN["danger"]};font-weight:600;">🚨 紧急提示：</span>'
        f'<span style="font-size:0.85em;color:{TOKEN["text"]};">{EMERGENCY_HINT}</span></div>',
        unsafe_allow_html=True,
    )
    # 紧急提示已显示 → 留痕（只记录"已显示"，每会话一次）
    if not st.session_state.get(f"_health_emergency_shown_{uid or 0}"):
        try:
            log_emergency_hint_shown(uid)
            st.session_state[f"_health_emergency_shown_{uid or 0}"] = True
        except Exception:
            _log.debug("紧急提示留痕失败", exc_info=True)

    with st.form("health_consult_form"):
        fc1, fc2 = st.columns(2)
        with fc1:
            c_name = st.text_input("姓名（可为昵称，联系电话必须真实）", key="hc_name")
        with fc2:
            c_phone = st.text_input("联系电话（11 位手机号）", key="hc_phone")
        c_type = st.selectbox("咨询类型", CONSULT_TYPES, key="hc_type")
        c_content = st.text_area("咨询内容（5-500 字）", height=120, key="hc_content")
        c_building = st.text_input("所属小区/楼栋（选填）", key="hc_building")
        c_files = st.file_uploader("附件图片（选填，jpg/png，≤5MB，最多3张，仅负责人和您本人可见）",
                                   type=["jpg", "jpeg", "png"], accept_multiple_files=True, key="hc_files")
        submitted = st.form_submit_button("🩺 提交咨询", type="primary", width="stretch")

    if submitted:
        _attach = "[]"
        _upload_errs: list[str] = []
        try:
            from utils.uploads import save_uploaded_files
            _saved, _upload_errs = save_uploaded_files(c_files, folder="consults")
            if _saved:
                import json
                _attach = json.dumps(_saved, ensure_ascii=False)
        except Exception:
            _upload_errs = ["附件上传失败，请重试"]
        if _upload_errs:
            st.error("；".join(_upload_errs) + "。已填内容保留，请重试。")
            st.stop()
        cid, msg, code = submit_consult(
            uid, c_name, c_phone, c_type, c_content, building=c_building,
            attachment_json=_attach,
        )
        if cid:
            st.success(
                f"✅ 提交成功！咨询编号：**{code}**（可复制）\n\n"
                f"- 当前状态：待回复\n"
                f"- 咨询类型：{c_type} · 提交时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"- 负责人将在 **24 小时内** 回复\n"
                f"- 回复前可撤回或修改一次\n"
                f"- 附件已上传时仅负责人和您本人可见"
            )
            st.balloons()
        else:
            st.error(msg)

# ---------- 我的咨询 ----------
with tab_mine:
    my_consults = get_my_consults(uid, limit=50)
    if not my_consults:
        st.info("还没有提交过健康咨询。")
    else:
        if unread:
            st.caption(f"🔔 您有 {unread} 条咨询有回复待查看/待反馈。")
        for c in my_consults:
            cid = c["id"]
            status = c.get("status", "")
            with st.container(border=True):
                st.markdown(
                    f'<span style="font-weight:700;color:{TOKEN["text"]};">{c.get("code","")}</span>'
                    f'&nbsp;{_type_pill(c.get("consult_type",""))}&nbsp;{_consult_tag(status)}',
                    unsafe_allow_html=True,
                )
                st.caption(f'提交时间：{(c.get("created_at") or "")[:16]}'
                           + (f' · 楼栋：{c.get("building")}' if c.get("building") else ""))
                st.markdown(
                    f'<div style="font-size:0.88em;color:{TOKEN["text_sec"]};line-height:1.6;">'
                    f'{c.get("content","")[:200]}</div>',
                    unsafe_allow_html=True,
                )
                # 我的咨询显示附件（spec：附件仅负责人和居民本人可见）
                try:
                    import json as _json
                    from utils.uploads import resolve_path as _resolve
                    _paths = _json.loads(c.get("attachment_json") or "[]")
                    _imgs = [x for x in (_resolve(x) for x in _paths) if x]
                    if _imgs:
                        st.markdown("**📎 附件图片**")
                        st.image(_imgs, width=140)
                except Exception:
                    pass
                if c.get("reply"):
                    reply_display = c.get("reply", "")
                    if c.get("reply_need_offline"):
                        reply_display = "【建议尽快线下就医】" + reply_display
                    st.markdown(
                        f'<div style="background:{TOKEN["accent_bg"]};border:1px solid {TOKEN["accent_border"]};'
                        f'border-radius:8px;padding:8px 12px;margin-top:6px;">'
                        f'<div style="font-size:0.8em;font-weight:700;color:{TOKEN["accent"]};">'
                        f'💬 负责人回复（{(c.get("reply_at") or "")[:16]}）</div>'
                        f'<div style="font-size:0.86em;color:{TOKEN["text"]};">{reply_display[:300]}</div>'
                        + (f'<div style="font-size:0.8em;color:{TOKEN["text_sec"]};">就医指引：{c.get("reply_doctor_guide")}</div>'
                           if c.get("reply_doctor_guide") else "")
                        + f'</div>',
                        unsafe_allow_html=True,
                    )
                    if c.get("feedback"):
                        st.caption(f'我的反馈：{c.get("feedback")}'
                                   + (f'（原因：{c.get("feedback_reason")}）' if c.get("feedback_reason") else ""))

                # ---- 操作按钮（按状态） ----
                if status == "待回复":
                    a1, a2 = st.columns(2)
                    with a1:
                        if st.button("↩️ 撤回咨询", key=f"hc_withdraw_{cid}", width="stretch"):
                            ok, msg = withdraw_consult(cid, uid)
                            if ok:
                                st.toast("已撤回，可重新打开（可修改一次）", icon="↩️")
                                st.rerun()
                            else:
                                st.error(msg)
                    with a2:
                        if st.button("✕ 关闭咨询", key=f"hc_close_{cid}", width="stretch"):
                            ok, msg = close_consult(cid, uid)
                            if ok:
                                st.toast("咨询已关闭", icon="✕")
                                st.rerun()
                            else:
                                st.error(msg)
                elif status == "已撤回":
                    with st.form(key=f"hc_reopen_{cid}"):
                        new_content = st.text_area("修改咨询内容（可选，每条咨询最多修改一次）",
                                                   value=c.get("content", ""), key=f"hc_reopen_txt_{cid}",
                                                   height=90)
                        reopened = st.form_submit_button("🔓 重新打开咨询", width="stretch")
                    if reopened:
                        content_arg = new_content if new_content != c.get("content", "") else ""
                        ok, msg = reopen_consult(cid, uid, content=content_arg)
                        if ok:
                            st.toast("咨询已重新打开（待回复，重新计时 24 小时）", icon="🔓")
                            st.rerun()
                        else:
                            st.error(msg)
                elif status == "已回复":
                    b1, b2 = st.columns(2)
                    with b1:
                        if st.button("✅ 已解决", key=f"hc_solved_{cid}", width="stretch"):
                            ok, msg = feedback_consult(cid, uid, solved=True)
                            if ok:
                                st.toast("感谢反馈，咨询已结束", icon="✅")
                                st.rerun()
                            else:
                                st.error(msg)
                    with b2:
                        if st.button("✕ 关闭咨询", key=f"hc_close2_{cid}", width="stretch"):
                            ok, msg = close_consult(cid, uid)
                            if ok:
                                st.toast("咨询已关闭", icon="✕")
                                st.rerun()
                            else:
                                st.error(msg)
                    with st.form(key=f"hc_unsolved_{cid}"):
                        reason = st.text_input("反馈未解决的原因（必填）", key=f"hc_reason_{cid}")
                        unsolved = st.form_submit_button("🔄 未解决（重新计时）", width="stretch")
                    if unsolved:
                        ok, msg = feedback_consult(cid, uid, solved=False, reason=reason or "")
                        if ok:
                            st.toast("已反馈未解决，负责人将重新开始 24 小时回复计时", icon="🔄")
                            st.rerun()
                        else:
                            st.error(msg)
                elif status == "继续回复":
                    if st.button("✕ 关闭咨询", key=f"hc_close3_{cid}", width="stretch"):
                        ok, msg = close_consult(cid, uid)
                        if ok:
                            st.toast("咨询已关闭", icon="✕")
                            st.rerun()
                        else:
                            st.error(msg)
                elif status == "超时未回复":
                    st.caption("⚠️ 负责人超过 24 小时未回复，系统已标记「超时未回复」并再次提醒负责人。")
                    if st.button("✕ 关闭咨询", key=f"hc_close4_{cid}", width="stretch"):
                        ok, msg = close_consult(cid, uid)
                        if ok:
                            st.toast("咨询已关闭", icon="✕")
                            st.rerun()
                        else:
                            st.error(msg)
