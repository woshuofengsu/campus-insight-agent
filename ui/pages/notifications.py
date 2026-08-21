"""📢 社区通知 — 广播通知列表（类型标签/紧急置顶/未读红点）+ 详情 + 紧急弹窗.

数据来自 notices 表（广播通知，data/db_notice.py 专管）；
底部保留「系统消息」区（notifications 私信表，用于工单/提案反馈），两套互不混用。
"""
import json
import logging

import streamlit as st

from ui.session_state import SS
from ui.components import TOKEN, page_header
from data.db_notice import (
    NOTICE_TYPES, get_visible_notices, get_active_urgent_notices,
    get_notice, get_notice_unread_count, mark_notice_read,
)

_log = logging.getLogger(__name__)

user_id = st.session_state.get(SS.login_user_id, 0)
if not user_id:
    st.info("请先登录。")
    st.stop()

# 类型配色（居民端列表用彩色标签区分 6 类）
TYPE_COLORS = {
    "社区公告": "#4f46e5",
    "活动通知": "#0891b2",
    "停水停电通知": "#d97706",
    "紧急通知": "#dc2626",
    "政策通知": "#059669",
    "其他": "#64748b",
}


def _type_pill(notice_type: str) -> str:
    color = TYPE_COLORS.get(notice_type, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}18;color:{color};'
        f'border:1px solid {color}40;border-radius:{TOKEN["radius_full"]};'
        f'padding:1px 9px;font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">{notice_type}</span>'
    )


def _urgent_badge() -> str:
    return (
        f'<span style="display:inline-block;background:{TOKEN["danger"]};color:#fff;'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_bold"]};'
        f'white-space:nowrap;">🚨 紧急</span>'
    )


def _pinned_badge() -> str:
    return (
        f'<span style="display:inline-block;background:{TOKEN["warning_bg"]};'
        f'color:{TOKEN["warning"]};border:1px solid {TOKEN["warning_border"]};'
        f'border-radius:{TOKEN["radius_full"]};padding:1px 9px;'
        f'font-size:{TOKEN["font_micro"]};font-weight:{TOKEN["weight_semibold"]};'
        f'white-space:nowrap;">📌 置顶</span>'
    )


def _render_attachments(n: dict):
    """渲染附件：图片直接展示，pdf/其他提供下载。"""
    try:
        files = json.loads(n.get("attachment_json") or "[]")
    except Exception:
        files = []
    if not files:
        return
    st.markdown("**📎 附件**")
    from utils.uploads import resolve_path
    for f in files:
        name = f.get("name", "附件")
        size_kb = (f.get("size") or 0) / 1024
        path = resolve_path(f.get("path"))
        ext = (f.get("ext") or "").lower()
        if path and ext in ("jpg", "jpeg", "png"):
            st.image(path, width=180, caption=name)
        elif path:
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
                st.download_button(
                    f"⬇️ {name}（{size_kb:.0f} KB）", data=data, file_name=name,
                    mime="application/pdf" if ext == "pdf" else "application/octet-stream",
                )
            except Exception:
                st.caption(f"📄 {name}（{size_kb:.0f} KB）")
        else:
            st.caption(f"📄 {name}（{size_kb:.0f} KB）")


unread_total = get_notice_unread_count("resident", user_id)
page_header(
    "📢 社区通知",
    "社区公告、活动、停水停电、政策与紧急通知都在这里。",
    f"{unread_total} 条未读" if unread_total else "",
)

# ---------- 紧急通知弹窗（每次进入页面都检查，直到点「我知道了」） ----------
try:
    urgent_queue = get_active_urgent_notices("resident", user_id)
except Exception:
    _log.warning("读取紧急通知失败", exc_info=True)
    urgent_queue = []

if urgent_queue:
    latest = urgent_queue[0]
    st.markdown(
        f'<div style="background:{TOKEN["danger_bg"]};border:2px solid {TOKEN["danger"]};'
        f'border-radius:{TOKEN["radius_card"]};padding:18px 20px;margin:6px 0 16px;">'
        f'<div style="font-size:1.25em;font-weight:{TOKEN["weight_bold"]};color:{TOKEN["danger"]};'
        f'margin-bottom:6px;">🚨 紧急通知</div>'
        f'<div style="font-size:1.05em;font-weight:{TOKEN["weight_semibold"]};'
        f'color:{TOKEN["text"]};">{latest["title"]}</div>'
        f'<div style="color:{TOKEN["text_sec"]};margin-top:8px;line-height:1.6;">'
        f'{latest.get("body", "")}</div>'
        f'<div style="color:{TOKEN["text_muted"]};font-size:{TOKEN["font_micro"]};'
        f'margin-top:8px;">发布：{str(latest.get("published_at") or "")[:16]}'
        + (f' · 有效期至 {str(latest.get("expire_at") or "")[:16]}' if latest.get("expire_at") else "")
        + '</div></div>',
        unsafe_allow_html=True,
    )
    c1, c2 = st.columns([1, 3])
    with c1:
        if st.button("我知道了", key=f"urgent_ack_{latest['id']}", type="primary", width="stretch"):
            mark_notice_read(latest["id"], "resident", user_id)
            st.rerun()
    with c2:
        if st.button("查看详情", key=f"urgent_detail_{latest['id']}", width="stretch"):
            mark_notice_read(latest["id"], "resident", user_id)
            st.session_state["_notice_detail_id"] = latest["id"]
            st.rerun()
    st.markdown("---")

# ---------- 详情视图 ----------
detail_id = st.session_state.get("_notice_detail_id")

if detail_id:
    n = get_notice(int(detail_id))
    if not n or n.get("status") != "已发布":
        st.warning("该通知已下架或不存在。")
        if st.button("← 返回通知列表", key="back_from_missing", width="stretch"):
            st.session_state.pop("_notice_detail_id", None)
            st.rerun()
        st.stop()
    # 已读判定：居民点详情即记已读（含紧急）
    mark_notice_read(n["id"], "resident", user_id)

    st.markdown(
        f'<div style="font-size:1.35em;font-weight:{TOKEN["weight_bold"]};color:{TOKEN["text"]};'
        f'line-height:1.3;">'
        + (f'<span style="color:{TOKEN["danger"]};">🚨 </span>' if n.get("is_urgent") else "")
        + f'{n["title"]}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="margin:8px 0 4px;">{_type_pill(n.get("notice_type", ""))} '
        + (f'{_urgent_badge()} ' if n.get("is_urgent") else "")
        + (f'{_pinned_badge()}' if n.get("is_pinned") else "")
        + '</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f'社区通知 · 发布于 {str(n.get("published_at") or "")[:16]}'
        + (f' · 有效期至 {str(n.get("expire_at") or "")[:16]}' if n.get("expire_at") else "")
    )
    st.markdown("---")
    st.markdown(
        f'<div style="font-size:1.02em;line-height:1.8;color:{TOKEN["text"]};'
        f'white-space:pre-wrap;">{n.get("body", "")}</div>',
        unsafe_allow_html=True,
    )
    _render_attachments(n)

    if n.get("is_urgent"):
        if st.button("我知道了", key=f"detail_ack_{n['id']}", type="primary", width="stretch"):
            mark_notice_read(n["id"], "resident", user_id)
            st.rerun()
    if st.button("← 返回通知列表", key="back_to_list", width="stretch"):
        st.session_state.pop("_notice_detail_id", None)
        st.rerun()
    st.stop()

# ---------- 通知列表 ----------
type_choice = st.radio(
    "类型筛选",
    ["全部"] + NOTICE_TYPES,
    horizontal=True,
    label_visibility="collapsed",
    key="_notice_type_filter",
)
notice_type_val = None if type_choice == "全部" else type_choice

try:
    notices = get_visible_notices("resident", user_id, notice_type=notice_type_val, limit=100)
except Exception:
    _log.warning("读取广播通知列表失败", exc_info=True)
    notices = []

if not notices:
    st.markdown(
        f'<div style="text-align:center;padding:48px 0;">'
        f'<div style="font-size:3em;margin-bottom:12px;">📭</div>'
        f'<div style="font-size:1em;font-weight:600;color:{TOKEN["text"]};">暂无社区通知</div>'
        f'<div style="font-size:0.8em;color:{TOKEN["text_muted"]};margin-top:4px;">'
        f'负责人发布公告、活动、停水停电等通知后，会显示在这里。</div>'
        f'</div>',
        unsafe_allow_html=True,
    )
else:
    for n in notices:
        nid = n["id"]
        is_unread = not n.get("is_read", 0)
        pub_time = str(n.get("published_at") or "")[:16]
        border_style = (
            f'border-left:3px solid {TOKEN["danger"]};'
            if n.get("is_urgent") else
            f'border-left:3px solid {TOKEN["accent"]};'
            if is_unread else
            f'border-left:3px solid transparent;'
        )
        with st.container(border=True):
            st.markdown(
                f'<div style="{border_style}padding:6px 0 6px 12px;">'
                f'<div style="display:flex;align-items:flex-start;gap:8px;">'
                f'<div style="flex:1;min-width:0;">'
                f'<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">'
                + (f'{_urgent_badge()}' if n.get("is_urgent") else "")
                + (f'{_pinned_badge()}' if n.get("is_pinned") else "")
                + f'{_type_pill(n.get("notice_type", ""))}'
                + (f'<span style="background:{TOKEN["danger"]};width:8px;height:8px;'
                   f'border-radius:50%;flex-shrink:0;" title="未读"></span>'
                   if is_unread else '')
                + '</div>'
                f'<div style="font-size:1em;font-weight:{TOKEN["weight_semibold"]};'
                f'color:{TOKEN["text"]};margin-top:6px;line-height:1.4;">{n["title"]}</div>'
                f'<div style="font-size:{TOKEN["font_micro"]};color:{TOKEN["text_muted"]};'
                f'margin-top:4px;">{pub_time}</div>'
                f'</div>'
                f'</div></div>',
                unsafe_allow_html=True,
            )
            if st.button("查看详情", key=f"view_{nid}", width="stretch"):
                st.session_state["_notice_detail_id"] = nid
                st.rerun()

st.markdown("---")

# ---------- 系统消息（私信：工单/提案反馈，notifications 表保留不动） ----------
from data.db_notifications import get_notifications, mark_read, mark_all_read

private_unread = 0
try:
    private_list = get_notifications(user_id, limit=50)
    private_unread = sum(1 for x in private_list if not x.get("is_read", 0))
except Exception:
    _log.warning("读取系统消息失败", exc_info=True)
    private_list = []

st.markdown("### 🔔 系统消息")
st.caption("工单处理反馈、提案回复等定向消息。")
if private_list:
    c1, c2 = st.columns([1, 4])
    with c1:
        if st.button("✅ 全部标为已读", width="stretch", type="primary"):
            n = mark_all_read(user_id)
            st.toast(f"已标记 {n} 条为已读", icon="✅")
            st.rerun()
    for n in private_list:
        nid = n["id"]
        is_unread = not n.get("is_read", 0)
        created = (n.get("created_at", "") or "")[:16]
        with st.container(border=True):
            st.markdown(
                f'<div style="padding:4px 0 4px 12px;">'
                f'<div style="display:flex;align-items:flex-start;gap:8px;">'
                f'<div style="flex:1;">'
                f'<div style="font-size:0.9em;font-weight:{700 if is_unread else 500};'
                f'color:{TOKEN["text"]};">{n["title"]}</div>'
                f'<div style="font-size:0.8em;color:{TOKEN["text_sec"]};margin-top:2px;">'
                f'{n.get("content", "")}</div>'
                f'<div style="font-size:0.7em;color:{TOKEN["text_muted"]};margin-top:4px;">'
                f'{created}</div>'
                f'</div>'
                + (f'<span style="background:{TOKEN["accent"]};width:8px;height:8px;'
                   f'border-radius:50%;flex-shrink:0;margin-top:4px;" title="未读"></span>'
                   if is_unread else '')
                + '</div></div>',
                unsafe_allow_html=True,
            )
            if is_unread:
                if st.button("✓ 标为已读", key=f"read_{nid}"):
                    mark_read(nid)
                    st.rerun()
else:
    st.caption("暂无系统消息。")
