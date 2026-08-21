"""📢 通知管理 — 新建/定时发布/紧急二次确认/撤回/下架/置顶/已读统计/导出.

负责人端广播通知管理（notices 表）。关键规则：
  - 紧急通知：仅指定负责人可发（白名单），发布/定时前二次确认，默认有效期 7 天自动置顶；
  - 定时发布：到点由系统自动发布（本页每次加载先跑一遍自动任务，兜底无定时器场景）；
  - 下架：原因必填 + 二次确认；待发布可撤回（留痕）；草稿可编辑删除；
  - 已读统计：居民端/老年端分开显示总量，不追踪具体谁；
  - 自动刷新：存在已发布紧急通知时列表每 10 秒刷新，否则每 30 秒。
"""
import json
import logging
from datetime import datetime, timedelta

import streamlit as st

from ui.guard import require_role

require_role("grid")

from ui.components import TOKEN, page_header
from data.db_core import get_db
from data.db_notice import (
    NOTICE_TYPES, PUBLISH_SCOPES, STATUS_ALL,
    STATUS_DRAFT, STATUS_PENDING, STATUS_PUBLISHED, STATUS_DOWN, STATUS_FAILED,
    URGENT_DEFAULT_EXPIRE_DAYS, PIN_EXPIRE_DAYS, MAX_PIN_COUNT,
    ATTACHMENT_ALLOWED_EXTS, ATTACHMENT_MAX_SIZE, ATTACHMENT_MAX_COUNT,
    can_publish_urgent, create_notice, update_notice, delete_notice,
    publish_notice, schedule_notice, withdraw_notice, take_down_notice,
    set_pinned, update_urgent_expire, get_notice, get_notices_with_stats,
    get_notice_read_stats, get_notice_timeline, export_notices_csv,
    run_auto_tasks,
)

_log = logging.getLogger(__name__)

page_header("📢 通知管理", "发布社区公告、活动、停水停电、政策与紧急通知；管理定时、下架与已读统计。")

# 当前负责人身份
_memory = st.session_state.get("memory")
_profile = _memory.get_user_profile() if _memory is not None else {}
_user_id = (_profile or {}).get("id") or 0
_actor = ((_profile.get("name") or "").strip()
          or (_profile.get("username") or "").strip() or f"负责人#{_user_id}")

# 每次进入页面先跑系统自动任务（定时发布到点 + 普通置顶超期/紧急到期取消置顶）
try:
    _auto = run_auto_tasks()
    if _auto.get("published"):
        st.toast(f"⏰ 系统已自动发布 {_auto['published']} 条定时通知", icon="⏰")
    if _auto.get("pins") or _auto.get("urgent"):
        st.toast("⏰ 系统已自动取消超期置顶", icon="⏰")
except Exception:
    _log.warning("通知自动任务执行失败", exc_info=True)

_CAN_URGENT = can_publish_urgent(_user_id)


# ---------- 通用小工具 ----------

_STATUS_COLORS = {
    STATUS_DRAFT: ("#f1f5f9", "#cbd5e1", "#64748b"),
    STATUS_PENDING: ("#eff6ff", "#bfdbfe", "#2563eb"),
    STATUS_PUBLISHED: ("#ecfdf5", "#a7f3d0", "#059669"),
    STATUS_DOWN: ("#f8fafc", "#e2e8f0", "#94a3b8"),
    STATUS_FAILED: ("#fef2f2", "#fecaca", "#dc2626"),
}


def _status_badge(status: str) -> str:
    bg, bd, fg = _STATUS_COLORS.get(status, ("#eef0ff", "#cfd4f8", "#4f46e5"))
    return (
        f'<span style="display:inline-block;background:{bg};border:1px solid {bd};'
        f'color:{fg};border-radius:{TOKEN["radius_full"]};padding:2px 10px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">{status}</span>'
    )


def _parse_files(files) -> str:
    """校验附件（格式/大小/数量）并真实保存到 uploads/notices/，返回 attachment_json。

    每条含 {name, size, type, ext, path}，path 为真实文件相对路径（供两端下载/预览）。
    """
    if not files:
        return "[]"
    if len(files) > ATTACHMENT_MAX_COUNT:
        st.error(f"附件最多 {ATTACHMENT_MAX_COUNT} 个")
        return ""
    meta = []
    for f in files:
        ext = (f.name.rsplit(".", 1)[-1] if "." in f.name else "").lower()
        if ext not in ATTACHMENT_ALLOWED_EXTS:
            st.error(f"附件「{f.name}」格式不支持（仅 jpg/png/pdf）")
            return ""
        if f.size > ATTACHMENT_MAX_SIZE:
            st.error(f"附件「{f.name}」超过 5MB")
            return ""
        try:
            from utils.uploads import save_uploaded_files
            saved = save_uploaded_files([f], folder="notices", max_count=1)
            path = saved[0] if saved else ""
        except Exception:
            path = ""
        meta.append({"name": f.name, "size": f.size, "type": f.type or ext, "ext": ext, "path": path})
    return json.dumps(meta, ensure_ascii=False)


def _scope_target_options(publish_scope: str) -> tuple[list[str], list[str]]:
    """返回 (小区列表, 楼栋列表)。"""
    communities: list[str] = []
    buildings: list[str] = []
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT DISTINCT community, building FROM user_profile "
                "WHERE is_active=1 AND community != ''"
            ).fetchall()
        communities = sorted({r["community"] for r in rows})
        buildings = sorted({f"{r['community']}|{r['building']}" for r in rows
                            if r["building"]})
    except Exception:
        _log.warning("读取发布范围选项失败", exc_info=True)
    return communities, buildings


def _scope_target_json(publish_scope: str, selected: list[str]) -> str:
    return json.dumps(list(selected or []), ensure_ascii=False)


def _fmt_ts(ts) -> str:
    return str(ts or "")[:16]


# ---------- 新建通知 ----------

def _render_new_form():
    st.markdown("### ➕ 新建通知")

    # 紧急二次确认面板（先于表单渲染）
    pending_id = st.session_state.get("_nm_pending_urgent")
    if pending_id:
        n = get_notice(int(pending_id))
        if n:
            mode = st.session_state.get("_nm_pending_mode", "publish")
            mode_txt = "立即发布" if mode == "publish" else "定时发布"
            st.markdown(
                f'<div style="background:{TOKEN["danger_bg"]};border:2px solid {TOKEN["danger"]};'
                f'border-radius:{TOKEN["radius_card"]};padding:18px 20px;">'
                f'<div style="font-size:1.15em;font-weight:{TOKEN["weight_bold"]};'
                f'color:{TOKEN["danger"]};">⚠️ 紧急通知二次确认</div>'
                f'<div style="margin-top:8px;color:{TOKEN["text"]};">'
                f'<b>标题：</b>{n["title"]}<br>'
                f'<b>类型：</b>{n["notice_type"]}　<b>范围：</b>{n["publish_scope"]}<br>'
                f'<b>方式：</b>{mode_txt}　'
                f'<b>有效期：</b>{_fmt_ts(n.get("expire_at")) or f"默认 {URGENT_DEFAULT_EXPIRE_DAYS} 天"}<br>'
                f'<b>摘要：</b>{(n.get("elderly_summary") or "").strip()}</div>'
                f'<div style="margin-top:8px;color:{TOKEN["text_sec"]};font-size:0.9em;">'
                f'紧急通知将自动置顶，并在居民端/老年端强制弹窗触达，请确认内容无误。</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 确认发布", key="nm_confirm_yes", type="primary", width="stretch"):
                    if mode == "publish":
                        ok, msg = publish_notice(int(pending_id), _user_id, _actor, confirm_urgent=True)
                    else:
                        sched = st.session_state.get("_nm_pending_scheduled")
                        ok, msg = schedule_notice(int(pending_id), sched, _user_id, _actor, confirm_urgent=True)
                    st.session_state.pop("_nm_pending_urgent", None)
                    st.session_state.pop("_nm_pending_mode", None)
                    st.session_state.pop("_nm_pending_scheduled", None)
                    if ok:
                        st.session_state["_nm_feedback"] = f"✅ 紧急通知「{n['title']}」已发布"
                        st.rerun(scope="app")
                    else:
                        st.session_state["_nm_feedback"] = f"❌ 发布失败：{msg}（草稿已保留，可在列表编辑）"
                        st.rerun(scope="app")
            with c2:
                if st.button("✖️ 取消", key="nm_confirm_no", width="stretch"):
                    delete_notice(int(pending_id), _actor)
                    for k in ("_nm_pending_urgent", "_nm_pending_mode", "_nm_pending_scheduled"):
                        st.session_state.pop(k, None)
                    st.rerun(scope="app")
        else:
            for k in ("_nm_pending_urgent", "_nm_pending_mode", "_nm_pending_scheduled"):
                st.session_state.pop(k, None)
        st.markdown("---")

    title = st.text_input("通知标题（必填，最多 50 字）", max_chars=50, key="nm_title")
    type_options = [t for t in NOTICE_TYPES if t != "紧急通知"] if not _CAN_URGENT else NOTICE_TYPES
    notice_type = st.selectbox("通知类型", type_options, key="nm_type")
    is_urgent = notice_type == "紧急通知"
    if is_urgent:
        st.caption(f"⚠️ 紧急通知需二次确认；默认有效期 {URGENT_DEFAULT_EXPIRE_DAYS} 天；自动置顶不受 {MAX_PIN_COUNT} 条限制。")
    elif not _CAN_URGENT:
        st.caption("您没有紧急通知发布权限（仅指定负责人可发）。")

    publish_scope = st.selectbox("发布范围", PUBLISH_SCOPES, key="nm_scope")
    communities, buildings = _scope_target_options(publish_scope)
    scope_selected: list[str] = []
    if publish_scope == "指定小区":
        scope_selected = st.multiselect("选择小区（支持搜索、全选）", communities, key="nm_scope_com")
    elif publish_scope == "指定楼栋":
        scope_selected = st.multiselect("选择楼栋（小区|楼栋）", buildings, key="nm_scope_bld")

    body = st.text_area("正文内容（必填，最多 5000 字）", height=160, max_chars=5000, key="nm_body")
    elderly_summary = st.text_input(
        "老年端播报摘要（选填，最多 30 字；紧急通知必填，口语化一句话）",
        max_chars=30, key="nm_summary",
    )

    publish_mode = st.radio("发布方式", ["立即发布", "定时发布"], horizontal=True, key="nm_mode")
    scheduled_at = None
    if publish_mode == "定时发布":
        scheduled_at = st.datetime_input("定时发布时间（晚于当前时间）", key="nm_scheduled")

    expire_at = None
    if is_urgent:
        default_expire = datetime.now() + timedelta(days=URGENT_DEFAULT_EXPIRE_DAYS)
        expire_at = st.date_input(f"紧急通知有效期（默认 {URGENT_DEFAULT_EXPIRE_DAYS} 天）",
                                  value=default_expire.date(), key="nm_expire_urgent")
    else:
        if st.checkbox("设置下架时间（选填，需晚于发布时间）", key="nm_has_expire"):
            expire_at = st.date_input("下架时间", key="nm_expire_opt")

    is_pinned = 0
    if not is_urgent:
        if st.checkbox(f"置顶（普通置顶最多 {MAX_PIN_COUNT} 条，{PIN_EXPIRE_DAYS} 天自动取消）", key="nm_pin"):
            is_pinned = 1

    files = st.file_uploader(
        f"附件（选填，jpg/png/pdf，单张≤5MB，最多 {ATTACHMENT_MAX_COUNT} 个）",
        type=["jpg", "jpeg", "png", "pdf"], accept_multiple_files=True, key="nm_files",
    )

    if st.button("🚀 发布", type="primary", width="stretch", key="nm_publish"):
        if not (title or "").strip():
            st.error("通知标题不能为空")
        elif not (body or "").strip():
            st.error("通知正文不能为空")
        elif is_urgent and not (elderly_summary or "").strip():
            st.error("紧急通知必须填写老年端播报摘要")
        elif publish_scope in ("指定小区", "指定楼栋") and not scope_selected:
            st.error("选择发布范围后必须勾选目标小区/楼栋")
        elif publish_mode == "定时发布" and scheduled_at is None:
            st.error("请选择定时发布时间")
        else:
            attach_json = _parse_files(files)
            if attach_json == "":
                st.stop()
            try:
                notice_id = create_notice(
                    title=title.strip(), notice_type=notice_type, publish_scope=publish_scope,
                    body=body.strip(), elderly_summary=(elderly_summary or "").strip(),
                    publisher=_actor, is_pinned=is_pinned, is_urgent=1 if is_urgent else 0,
                    expire_at=_ts_or_empty(expire_at),
                    attachment_json=attach_json,
                    scope_target_json=_scope_target_json(publish_scope, scope_selected),
                    actor=_actor,
                )
            except ValueError as e:
                st.error(str(e))
                st.stop()

            if is_urgent:
                # 紧急通知：二次确认（草稿先保存，确认后发布，取消即删）
                st.session_state["_nm_pending_urgent"] = notice_id
                st.session_state["_nm_pending_mode"] = "publish" if publish_mode == "立即发布" else "schedule"
                st.session_state["_nm_pending_scheduled"] = _ts_or_empty(scheduled_at)
                st.rerun(scope="app")
            else:
                if publish_mode == "立即发布":
                    ok, msg = publish_notice(notice_id, _user_id, _actor)
                else:
                    ok, msg = schedule_notice(notice_id, scheduled_at, _user_id, _actor)
                if ok:
                    st.session_state["_nm_feedback"] = (
                        f"✅ 已发布「{title.strip()}」" if publish_mode == "立即发布"
                        else f"✅ 已定时「{title.strip()}」→ 待发布"
                    )
                else:
                    st.session_state["_nm_feedback"] = f"❌ {msg}（草稿已保留，可在列表编辑后重试）"
                for k in ("nm_title", "nm_body", "nm_summary", "nm_files"):
                    st.session_state.pop(k, None)
                st.rerun(scope="app")


def _ts_or_empty(v) -> str:
    if not v:
        return ""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(v, "strftime"):  # datetime.date（st.date_input）
        return datetime.combine(v, datetime.min.time().replace(hour=23, minute=59, second=59)).strftime("%Y-%m-%d %H:%M:%S")
    return str(v)


# ---------- 编辑草稿/待发布 ----------

def _render_edit_form(n: dict):
    st.markdown(f"### ✏️ 编辑通知 #{n['id']}（{n['status']}）")
    title = st.text_input("通知标题", value=n["title"], max_chars=50, key="nme_title")
    type_options = [t for t in NOTICE_TYPES if t != "紧急通知"] if not _CAN_URGENT else NOTICE_TYPES
    if n["notice_type"] == "紧急通知" and "紧急通知" not in type_options:
        # 无紧急权限的人编辑紧急通知时，类型选项里保留「紧急通知」，避免被悄悄降级
        type_options = ["紧急通知"] + type_options
    notice_type = st.selectbox("通知类型", type_options,
                               index=type_options.index(n["notice_type"]) if n["notice_type"] in type_options else 0,
                               key="nme_type")
    is_urgent = notice_type == "紧急通知"
    publish_scope = st.selectbox("发布范围", PUBLISH_SCOPES,
                                 index=PUBLISH_SCOPES.index(n["publish_scope"]) if n["publish_scope"] in PUBLISH_SCOPES else 0,
                                 key="nme_scope")
    communities, buildings = _scope_target_options(publish_scope)
    try:
        old_targets = json.loads(n.get("scope_target_json") or "[]")
    except Exception:
        old_targets = []
    scope_selected: list[str] = []
    if publish_scope == "指定小区":
        scope_selected = st.multiselect("选择小区", communities, default=old_targets, key="nme_scope_com")
    elif publish_scope == "指定楼栋":
        scope_selected = st.multiselect("选择楼栋（小区|楼栋）", buildings, default=old_targets, key="nme_scope_bld")
    body = st.text_area("正文内容", value=n["body"], height=150, max_chars=5000, key="nme_body")
    elderly_summary = st.text_input("老年端播报摘要（紧急必填，最多 30 字）",
                                    value=n.get("elderly_summary") or "", max_chars=30, key="nme_summary")
    is_pinned = 1 if st.checkbox("置顶（普通）", value=bool(n.get("is_pinned")), key="nme_pin") else 0
    new_expire = None
    if is_urgent:
        # 紧急通知：可修改有效期（留痕；只影响修改后仍未读的用户）
        try:
            cur_exp = datetime.strptime((n.get("expire_at") or "")[:10], "%Y-%m-%d").date()
        except Exception:
            cur_exp = datetime.now().date() + timedelta(days=URGENT_DEFAULT_EXPIRE_DAYS)
        new_expire = st.date_input("紧急通知有效期至（到期自动取消置顶和弹窗）",
                                   value=cur_exp, key="nme_expire_urgent")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 保存修改", type="primary", width="stretch", key="nme_save"):
            upd = {
                "title": title.strip(), "notice_type": notice_type,
                "publish_scope": publish_scope,
                "scope_target_json": _scope_target_json(publish_scope, scope_selected),
                "body": body.strip(), "elderly_summary": (elderly_summary or "").strip(),
                "is_pinned": is_pinned, "is_urgent": 1 if is_urgent else 0,
            }
            ok, msg = update_notice(n["id"], _actor, **upd)
            if ok and is_urgent and new_expire is not None:
                # 有效期变化才更新，避免保存普通修改时误动有效期（_ts 视为当天 23:59:59）
                if new_expire.strftime("%Y-%m-%d") != (n.get("expire_at") or "")[:10]:
                    ok2, msg2 = update_urgent_expire(n["id"], new_expire, _user_id, _actor)
                    if not ok2:
                        ok, msg = False, f"有效期更新失败：{msg2}"
            if ok:
                st.session_state["_nm_feedback"] = f"✅ 已保存 #{n['id']}"
                st.session_state.pop("_nm_edit_id", None)
                st.rerun(scope="app")
            else:
                st.error(msg)
    with c2:
        if st.button("取消", width="stretch", key="nme_cancel"):
            st.session_state.pop("_nm_edit_id", None)
            st.rerun(scope="app")
    st.markdown("---")


# ---------- 通知列表（含自动刷新 + 统计 + 操作） ----------

def _render_list_fragment():
    st.markdown("### 📋 通知列表")

    # 筛选
    c1, c2 = st.columns(2)
    with c1:
        type_f = st.selectbox("类型", ["全部"] + NOTICE_TYPES, key="nml_type")
    with c2:
        status_f = st.selectbox("状态", ["全部"] + STATUS_ALL, key="nml_status")
    c3, c4 = st.columns(2)
    with c3:
        scope_f = st.selectbox("范围", ["全部"] + PUBLISH_SCOPES, key="nml_scope")
    with c4:
        keyword_f = st.text_input("关键词（标题/正文）", key="nml_keyword")

    notices = get_notices_with_stats(
        notice_type=None if type_f == "全部" else type_f,
        status=None if status_f == "全部" else status_f,
        publish_scope=None if scope_f == "全部" else scope_f,
        keyword=keyword_f.strip() or None,
        limit=200,
    )

    # 导出
    if notices:
        csv_data, fname = export_notices_csv(
            notice_type=None if type_f == "全部" else type_f,
            status=None if status_f == "全部" else status_f,
            publish_scope=None if scope_f == "全部" else scope_f,
            keyword=keyword_f.strip() or None,
            actor=_actor,
        )
        st.download_button(
            "⬇️ 导出列表 + 已读统计（CSV）", data=csv_data, file_name=fname,
            mime="text/csv", key="nml_export",
        )

    if not notices:
        st.info("没有符合条件的通知。")
        return

    # 详情浮层
    detail_id = st.session_state.get("_nm_detail_id")
    if detail_id:
        dn = get_notice(int(detail_id))
        if dn:
            _render_detail(dn)
        st.markdown("---")

    # 下架二次确认浮层
    down_id = st.session_state.get("_nm_down_confirm_id")
    if down_id:
        dn = get_notice(int(down_id))
        if dn:
            st.markdown(
                f'<div style="background:{TOKEN["danger_bg"]};border:1px solid {TOKEN["danger"]};'
                f'border-radius:{TOKEN["radius_card"]};padding:14px 16px;">'
                f'<b style="color:{TOKEN["danger"]};">下架确认：</b>'
                f'「{dn["title"]}」下架后居民端/老年端不再显示，统计保留。'
                f'请填写下架原因（必填）：</div>',
                unsafe_allow_html=True,
            )
            reason = st.text_input("下架原因", key="nml_down_reason")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 确认下架", type="primary", width="stretch", key="nml_down_yes"):
                    if not (reason or "").strip():
                        st.error("下架原因必填")
                    else:
                        ok, msg = take_down_notice(int(down_id), reason, _actor)
                        st.session_state.pop("_nm_down_confirm_id", None)
                        if ok:
                            st.session_state["_nm_feedback"] = f"✅ 已下架 #{down_id}"
                        else:
                            st.session_state["_nm_feedback"] = f"❌ {msg}"
                        st.rerun(scope="app")
            with c2:
                if st.button("取消", width="stretch", key="nml_down_no"):
                    st.session_state.pop("_nm_down_confirm_id", None)
                    st.rerun(scope="fragment")
        else:
            st.session_state.pop("_nm_down_confirm_id", None)
        st.markdown("---")

    # 删除草稿二次确认
    del_id = st.session_state.get("_nm_del_confirm_id")
    if del_id:
        c1, c2 = st.columns(2)
        with c1:
            if st.button("🗑️ 确认删除草稿", type="primary", width="stretch", key="nml_del_yes"):
                ok, msg = delete_notice(int(del_id), _actor)
                st.session_state.pop("_nm_del_confirm_id", None)
                st.session_state["_nm_feedback"] = f"✅ 已删除草稿 #{del_id}" if ok else f"❌ {msg}"
                st.rerun(scope="app")
        with c2:
            if st.button("取消", width="stretch", key="nml_del_no"):
                st.session_state.pop("_nm_del_confirm_id", None)
                st.rerun(scope="fragment")
        st.markdown("---")

    for n in notices:
        nid = n["id"]
        stats = n.get("stats") or {}
        is_urgent = bool(n.get("is_urgent"))
        status = n.get("status", "")

        # 置顶信息：普通显示剩余天数，紧急显示至有效期结束
        pin_info = ""
        if n.get("is_pinned"):
            if is_urgent:
                pin_info = f'至 {_fmt_ts(n.get("expire_at")) or "有效期结束"}'
            else:
                try:
                    pinned = datetime.strptime(str(n.get("pinned_at"))[:19], "%Y-%m-%d %H:%M:%S")
                    remain = max((pinned + timedelta(days=PIN_EXPIRE_DAYS) - datetime.now()).days, 0)
                    pin_info = f"剩 {remain} 天"
                except Exception:
                    pin_info = "7 天内"
        pinned_html = (
            f'<span style="color:{TOKEN["warning"]};font-size:{TOKEN["font_micro"]};">'
            f'📌 置顶（{pin_info}）</span>'
            if n.get("is_pinned") else ""
        )

        urgent_style = f'border-left:3px solid {TOKEN["danger"]};' if is_urgent else ""
        show_time = _fmt_ts(n.get("published_at") or n.get("scheduled_at") or "")
        time_label = "定时时间" if status == STATUS_PENDING else "发布时间"

        with st.container(border=True):
            st.markdown(
                f'<div style="{urgent_style}padding:4px 0 4px 10px;">'
                f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">'
                + ('<span style="color:#dc2626;font-weight:800;font-size:0.85em;">🚨 紧急</span>' if is_urgent else '')
                + f'<span style="font-weight:{TOKEN["weight_semibold"]};color:{TOKEN["text"]};'
                  f'font-size:0.95em;">#{nid} {str(n["title"])[:30]}</span>'
                + ("" if len(str(n["title"])) <= 30 else '<span style="color:#94a3b8;">…</span>')
                + f'{_status_badge(status)}'
                + f'<span style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_sec"]};">'
                  f'{n.get("notice_type", "")} · {n.get("publish_scope", "")} · '
                  f'{n.get("publisher", "")}</span>'
                + '</div>'
                f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_muted"]};'
                f'margin-top:4px;">{time_label}：{show_time} {pinned_html}'
                + (f'　下架原因：{str(n.get("down_reason") or "")[:24]}' if status == STATUS_DOWN else '')
                + '</div>'
                f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text"]};margin-top:4px;">'
                f'居民端 已读 {stats.get("resident_read", 0)} / 未读 {stats.get("resident_unread", 0)}'
                f'（共 {stats.get("resident_total", 0)}）　'
                f'老年端 已读 {stats.get("elderly_read", 0)} / 未读 {stats.get("elderly_unread", 0)}'
                f'（共 {stats.get("elderly_total", 0)}）'
                + '</div></div>',
                unsafe_allow_html=True,
            )

            # 操作按钮
            acts = []
            if st.button("📖 详情", key=f"nml_detail_{nid}", width="stretch"):
                st.session_state["_nm_detail_id"] = nid
                st.rerun(scope="fragment")
            if status in (STATUS_DRAFT, STATUS_PENDING):
                if st.button("✏️ 编辑", key=f"nml_edit_{nid}", width="stretch"):
                    # 清掉旧编辑表单的 widget 残留值，保证重新打开时回填数据库最新值
                    for k in list(st.session_state.keys()):
                        if k.startswith("nme_"):
                            st.session_state.pop(k, None)
                    st.session_state["_nm_edit_id"] = nid
                    st.rerun(scope="app")
            if status == STATUS_PENDING:
                if st.button("⏪ 撤回", key=f"nml_withdraw_{nid}", width="stretch"):
                    ok, msg = withdraw_notice(nid, _actor)
                    st.session_state["_nm_feedback"] = f"✅ 已撤回 #{nid} → 草稿" if ok else f"❌ {msg}"
                    st.rerun(scope="app")
                if st.button("🚀 立即发布", key=f"nml_publish_now_{nid}", width="stretch"):
                    ok, msg = publish_notice(nid, _user_id, _actor,
                                             confirm_urgent=bool(n.get("is_urgent")))
                    if not ok and n.get("is_urgent") and "二次确认" in msg:
                        st.session_state["_nm_feedback"] = "紧急通知定时需在「新建」流程中二次确认，请重新走定时发布"
                    else:
                        st.session_state["_nm_feedback"] = f"✅ 已发布 #{nid}" if ok else f"❌ {msg}"
                    st.rerun(scope="app")
            if status == STATUS_PUBLISHED:
                if st.button("⛔ 下架", key=f"nml_down_{nid}", width="stretch"):
                    st.session_state["_nm_down_confirm_id"] = nid
                    st.rerun(scope="fragment")
                if not is_urgent:
                    if n.get("is_pinned"):
                        if st.button("📌 取消置顶", key=f"nml_unpin_{nid}", width="stretch"):
                            set_pinned(nid, False, _actor)
                            st.rerun(scope="fragment")
                    else:
                        if st.button("📌 置顶", key=f"nml_pin_{nid}", width="stretch"):
                            ok, msg = set_pinned(nid, True, _actor)
                            if not ok:
                                st.session_state["_nm_feedback"] = f"❌ {msg}"
                                st.rerun(scope="app")
                            st.rerun(scope="fragment")
            if status == STATUS_DRAFT:
                if st.button("🗑️ 删除草稿", key=f"nml_del_{nid}", width="stretch"):
                    st.session_state["_nm_del_confirm_id"] = nid
                    st.rerun(scope="fragment")

    # 编辑浮层（草稿/待发布）
    edit_id = st.session_state.get("_nm_edit_id")
    if edit_id:
        en = get_notice(int(edit_id))
        if en and en["status"] in (STATUS_DRAFT, STATUS_PENDING):
            _render_edit_form(en)


def _render_detail(n: dict):
    """详情：全字段 + 已读统计 + 留痕（默认最近 3 条可展开）。"""
    stats = get_notice_read_stats(n["id"])
    st.markdown(f"### 📖 通知详情 #{n['id']}")
    with st.container(border=True):
        st.markdown(
            f'<div style="font-size:1.1em;font-weight:{TOKEN["weight_bold"]};'
            f'color:{TOKEN["text"]};">'
            + ('🚨 ' if n.get("is_urgent") else "")
            + f'{n["title"]}</div>',
            unsafe_allow_html=True,
        )
        st.caption(
            f'类型：{n.get("notice_type", "")}　范围：{n.get("publish_scope", "")}　'
            f'发布人：{n.get("publisher", "")}　状态：{n.get("status", "")}'
        )
        st.caption(
            f'发布时间：{_fmt_ts(n.get("published_at")) or "—"}　'
            f'定时时间：{_fmt_ts(n.get("scheduled_at")) or "—"}　'
            f'有效期至：{_fmt_ts(n.get("expire_at")) or "—"}'
        )
        if n.get("scope_target_json"):
            try:
                targets = json.loads(n["scope_target_json"])
                if targets:
                    st.caption(f'范围目标：{"、".join(targets)}')
            except Exception:
                pass
        if n.get("down_reason"):
            st.caption(f'⛔ 下架原因：{n["down_reason"]}')
        st.markdown("---")
        st.markdown(f'<div style="line-height:1.7;color:{TOKEN["text"]};white-space:pre-wrap;">'
                    f'{n.get("body", "")}</div>', unsafe_allow_html=True)
        if n.get("elderly_summary"):
            st.markdown(f'**老年端播报摘要：**{n["elderly_summary"]}')
        try:
            files = json.loads(n.get("attachment_json") or "[]")
            if files:
                st.markdown("**📎 附件：**" + "、".join(f.get("name", "") for f in files))
        except Exception:
            pass

    st.markdown("### 📊 已读/未读统计")
    c1, c2 = st.columns(2)
    with c1:
        st.metric("居民端已读", stats.get("resident_read", 0),
                  f"未读 {stats.get('resident_unread', 0)} / 共 {stats.get('resident_total', 0)}")
    with c2:
        st.metric("老年端已读", stats.get("elderly_read", 0),
                  f"未读 {stats.get('elderly_unread', 0)} / 共 {stats.get('elderly_total', 0)}")

    st.markdown("### 🧾 操作留痕")
    timeline = get_notice_timeline(n["id"])
    if not timeline:
        st.caption("暂无留痕记录。")
    else:
        for item in timeline[:3]:
            st.caption(
                f'· {str(item.get("created_at") or "")[:19]}　{item.get("actor", "")}　'
                f'{item.get("action", "")}'
                + (f'　[{item.get("before_value", "")} → {item.get("after_value", "")}]'
                   if item.get("before_value") or item.get("after_value") else "")
                + (f'　{item.get("detail", "")[:40]}' if item.get("detail") else "")
            )
        if len(timeline) > 3:
            with st.expander(f"查看全部 {len(timeline)} 条留痕"):
                for item in timeline[3:]:
                    st.caption(
                        f'· {str(item.get("created_at") or "")[:19]}　{item.get("actor", "")}　'
                        f'{item.get("action", "")}'
                        + (f'　[{item.get("before_value", "")} → {item.get("after_value", "")}]'
                           if item.get("before_value") or item.get("after_value") else "")
                        + (f'　{item.get("detail", "")[:60]}' if item.get("detail") else "")
                    )


# ---------- 主布局 ----------

feedback = st.session_state.pop("_nm_feedback", None)
if feedback:
    if feedback.startswith("✅"):
        st.success(feedback)
    else:
        st.error(feedback)

tab_list, tab_new = st.tabs(["📋 通知列表", "➕ 新建通知"])

with tab_new:
    _render_new_form()

with tab_list:
    # 自动刷新：存在已发布紧急通知 → 10 秒；否则 30 秒
    try:
        with get_db() as conn:
            urgent_exist = conn.execute(
                "SELECT COUNT(*) AS c FROM notices WHERE status=? AND is_urgent=1",
                (STATUS_PUBLISHED,),
            ).fetchone()["c"]
    except Exception:
        urgent_exist = 0
    _interval = 10 if urgent_exist else 30

    @st.fragment(run_every=_interval)
    def _list_fragment():
        _render_list_fragment()

    _list_fragment()
