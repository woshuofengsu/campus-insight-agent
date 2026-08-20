"""🔊 听通知 — 大字版广播通知列表 + 详情语音播报 + 紧急通知主动弹窗.

数据来自 notices 表（广播通知）；已读按老年端（client_type='elderly'）单独记录。
紧急通知：红色大弹窗 + 语音自动播报两遍（摘要为空播报兜底文案），
点「我知道了」关闭并记已读；未点每次进入本页再次弹出。
"""
import json
import logging
from datetime import datetime

import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak
from data.db_notice import (
    get_visible_notices, get_active_urgent_notices, get_notice,
    get_notice_unread_count, mark_notice_read,
)

_log = logging.getLogger(__name__)

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

st.markdown('<div class="elderly-title">🔊 听通知</div>', unsafe_allow_html=True)

# 顶部：返回首页大按钮
if st.button("🏠 返回首页", key="notify_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
st.markdown("---")

if not uid:
    st.info("请先登录。")
    st.stop()

# 类型彩色标签（大字版）
TYPE_COLORS = {
    "社区公告": "#4f46e5",
    "活动通知": "#0891b2",
    "停水停电通知": "#d97706",
    "紧急通知": "#dc2626",
    "政策通知": "#059669",
    "其他": "#64748b",
}


def _type_tag(notice_type: str) -> str:
    color = TYPE_COLORS.get(notice_type, "#64748b")
    return (
        f'<span style="display:inline-block;background:{color}22;color:{color};'
        f'border:2px solid {color};border-radius:12px;padding:2px 12px;'
        f'font-size:0.85em;font-weight:800;white-space:nowrap;">{notice_type}</span>'
    )


def _simplify_time(ts: str) -> str:
    """发布时间简化：今天 / 昨天 / XX月XX日。"""
    try:
        dt = datetime.strptime(str(ts)[:10], "%Y-%m-%d")
        today = datetime.now().strftime("%Y-%m-%d")
        if str(ts)[:10] == today:
            return "今天"
        from datetime import timedelta
        if str(ts)[:10] == (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"):
            return "昨天"
        return dt.strftime("%m月%d日")
    except Exception:
        return str(ts)[:10]


def _elderly_tts_html(text: str, height: int = 70):
    """语音自动播报两遍（Web Speech API 队列连播），另带手动按钮。"""
    text_js = json.dumps(text, ensure_ascii=False)
    st.components.v1.html(f"""
    <div style="text-align:center;">
      <button onclick="speak()" style="font-size:1.1em;padding:12px 20px;border-radius:14px;
          border:2px solid #dc2626;background:#fee2e2;cursor:pointer;font-weight:700;">🔊 再听一遍</button>
    </div>
    <script>
    function speak() {{
        if ('speechSynthesis' in window) {{
            var u1 = new SpeechSynthesisUtterance({text_js});
            u1.lang = 'zh-CN'; u1.rate = 0.85;
            var u2 = new SpeechSynthesisUtterance({text_js});
            u2.lang = 'zh-CN'; u2.rate = 0.85;
            speechSynthesis.cancel();
            speechSynthesis.speak(u1);
            speechSynthesis.speak(u2);
        }} else {{
            alert('当前浏览器不支持语音朗读');
        }}
    }}
    window.addEventListener('load', function() {{ setTimeout(speak, 300); }});
    </script>
    """, height=height)


# ---------- 紧急通知主动弹窗（最新一条，点「我知道了」后自动弹下一条） ----------
try:
    urgent_queue = get_active_urgent_notices("elderly", uid)
except Exception:
    _log.warning("读取老年端紧急通知失败", exc_info=True)
    urgent_queue = []

if urgent_queue:
    latest = urgent_queue[0]
    summary = (latest.get("elderly_summary") or "").strip() or "您有一条新通知，请查看详情"
    big_card(
        f'<span style="color:#dc2626;font-size:1.4em;font-weight:900;">🚨 紧急通知</span>'
        f'<br><strong style="font-size:1.25em;">{latest["title"]}</strong>'
        f'<br><span style="font-size:1.05em;">{summary}</span>',
        bg="#fef2f2", border="#dc2626",
    )
    # 语音自动播报两遍（紧急通知）
    _elderly_tts_html(summary)
    if st.button("我知道了", key=f"elderly_urgent_ack_{latest['id']}", type="primary", width="stretch"):
        mark_notice_read(latest["id"], "elderly", uid)
        st.rerun()
    if st.button("查看详情", key=f"elderly_urgent_detail_{latest['id']}", width="stretch"):
        mark_notice_read(latest["id"], "elderly", uid)
        st.session_state["_elderly_notice_id"] = latest["id"]
        st.rerun()
    st.markdown("---")

# ---------- 详情视图 ----------
detail_id = st.session_state.get("_elderly_notice_id")
if detail_id:
    n = get_notice(int(detail_id))
    if not n or n.get("status") != "已发布":
        st.info("该通知已下架或不存在。")
        if st.button("← 返回通知列表", key="elderly_back_missing", width="stretch"):
            st.session_state.pop("_elderly_notice_id", None)
            st.rerun()
        st.stop()
    # 已读判定：老人点详情即记已读
    mark_notice_read(n["id"], "elderly", uid)

    st.markdown(
        f'<div style="font-size:1.5em;font-weight:900;color:#000;line-height:1.35;">'
        + ('🚨 ' if n.get("is_urgent") else "")
        + f'{n["title"]}</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="margin:10px 0;">{_type_tag(n.get("notice_type", ""))}</div>'
        f'<div style="font-size:0.95em;color:#444;margin-bottom:12px;">'
        f'发布时间：{_simplify_time(str(n.get("published_at") or ""))}</div>',
        unsafe_allow_html=True,
    )
    big_card(
        f'<div style="font-size:1.15em;line-height:1.9;white-space:pre-wrap;">{n.get("body", "")}</div>'
    )

    # 附件：「查看附件」打开预览（不自动下载）
    try:
        files = json.loads(n.get("attachment_json") or "[]")
    except Exception:
        files = []
    if files:
        st.markdown("**📎 附件**")
        if st.button(f"查看附件（{len(files)} 个）", key="elderly_view_files", width="stretch"):
            st.session_state["_elderly_show_files"] = True
        if st.session_state.get("_elderly_show_files"):
            for f in files:
                big_card(f"📄 {f.get('name', '附件')}", bg="#f8fafc", border="#94a3b8")

    # 语音播报：摘要优先，为空播报兜底文案
    speak_text = (n.get("elderly_summary") or "").strip() or "您有一条新通知，请查看详情"
    tts_speak(speak_text, label="🔊 播放通知")
    if n.get("is_urgent"):
        if st.button("我知道了", key=f"elderly_detail_ack_{n['id']}", type="primary", width="stretch"):
            mark_notice_read(n["id"], "elderly", uid)
            st.rerun()
    if st.button("← 返回通知列表", key="elderly_back_list", width="stretch"):
        st.session_state.pop("_elderly_notice_id", None)
        st.session_state.pop("_elderly_show_files", None)
        st.rerun()
    st.stop()

# ---------- 大字版通知列表（每页 5 条，查看更多加载） ----------
unread_count = get_notice_unread_count("elderly", uid)
st.caption(f"您有 {unread_count} 条未读通知" if unread_count else "没有未读通知")

try:
    notices = get_visible_notices("elderly", uid, limit=100)
except Exception:
    _log.warning("读取老年端通知列表失败", exc_info=True)
    notices = []

if not notices:
    st.info("暂无通知。")
else:
    page_size = 5
    offset = st.session_state.get("_elderly_notice_offset", 0)
    page = notices[offset:offset + page_size]

    for n in page:
        nid = n["id"]
        is_unread = not n.get("is_read", 0)
        dot = (
            f'<span style="display:inline-block;width:14px;height:14px;border-radius:50%;'
            f'background:#dc2626;margin-right:8px;"></span>'
            if is_unread else ""
        )
        urgent_tag = (
            f'<span style="display:inline-block;background:#dc2626;color:#fff;'
            f'border-radius:12px;padding:2px 14px;font-size:0.9em;font-weight:900;'
            f'margin-right:8px;">紧急</span>'
            if n.get("is_urgent") else ""
        )
        big_card(
            f'{dot}<strong style="font-size:1.2em;">{n["title"]}</strong>'
            f'<br><span style="color:#555;font-size:0.95em;">'
            f'{_simplify_time(str(n.get("published_at") or ""))}</span>'
            f'<br><span style="margin-top:6px;display:inline-block;">'
            f'{urgent_tag}{_type_tag(n.get("notice_type", ""))}</span>'
        )
        if st.button("查看详情", key=f"elderly_view_{nid}", width="stretch"):
            st.session_state["_elderly_notice_id"] = nid
            st.rerun()

    if offset + page_size < len(notices):
        if st.button("查看更多", key="elderly_more", width="stretch"):
            st.session_state["_elderly_notice_offset"] = offset + page_size
            st.rerun()
    elif offset > 0:
        if st.button("收起", key="elderly_less", width="stretch"):
            st.session_state["_elderly_notice_offset"] = 0
            st.rerun()
