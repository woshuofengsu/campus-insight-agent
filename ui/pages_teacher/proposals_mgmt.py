# ui/pages_teacher/proposals_mgmt.py
"""💡 提案管理 — 查看、回复、采纳学生提案."""
import csv
import io
from datetime import datetime
import streamlit as st
from ui.components import TOKEN, tag
from ui.cache import cached_proposals, cached_proposals_stats, invalidate_proposals
from data.database import update_proposal_status

# ── Page Render ──
st.markdown(
    f'<span style="font-size:1.2em;font-weight:800;color:{TOKEN["text"]};">'
    f'💡 提案管理</span>',
    unsafe_allow_html=True,
)
st.caption("查看学生提交的校园治理提案，回复并采纳可行建议。")

# ── Filter tabs ──
status_choice = st.radio(
    "状态筛选",
    ["全部", "💬 待回复", "✅ 已采纳", "🎉 已实施"],
    horizontal=True,
    label_visibility="collapsed",
    key="_proposals_status_filter",
)

# ── Fetch data ──
all_props = cached_proposals(sort_by="supporters", limit=200)

if status_choice == "全部":
    proposals = all_props
elif status_choice == "💬 待回复":
    proposals = [p for p in all_props if p.get("status") in ("讨论中", "已回应")]
else:
    status_map = {"✅ 已采纳": "已采纳", "🎉 已实施": "已实施"}
    proposals = [p for p in all_props if p.get("status") == status_map.get(status_choice)]

# ── Stats bar (reuse already-fetched all_props) ──
pending_reply = sum(1 for p in all_props if p.get("status") in ("讨论中", "已回应"))
adopted = sum(1 for p in all_props if p.get("status") == "已采纳")
implemented = sum(1 for p in all_props if p.get("status") == "已实施")

c_stats, c_export = st.columns([5, 1])
with c_stats:
    st.caption(
        f'共 {len(proposals)} 条 · 💬 待回复 {pending_reply} · ✅ 已采纳 {adopted} · 🎉 已实施 {implemented}'
    )
with c_export:
    if proposals:
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer)
        writer.writerow(["ID", "标题", "分类", "状态", "附议数", "提案人", "创建时间", "回复内容", "提案描述"])
        for p in proposals:
            writer.writerow([
                p.get("id"), p.get("title"), p.get("category"), p.get("status"),
                p.get("supporter_count", 0), p.get("author"),
                (p.get("created_at") or "")[:10], p.get("response_text", ""),
                p.get("description", ""),
            ])
        st.download_button(
            "📥 导出CSV",
            csv_buffer.getvalue(),
            file_name=f"提案导出_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            width="stretch",
        )

st.markdown("---")

# ── Analytics Summary Banner ──
total_props = len(all_props)
if total_props > 0:
    discussing = sum(1 for p in all_props if p.get("status") == "讨论中")
    responded = sum(1 for p in all_props if p.get("status") == "已回应")
    adopted_count = sum(1 for p in all_props if p.get("status") == "已采纳")
    implemented_count = sum(1 for p in all_props if p.get("status") == "已实施")

    # Top categories
    from collections import Counter
    cat_counts = Counter(p.get("category", "") for p in all_props)
    top_cat = cat_counts.most_common(1)[0][0] if cat_counts else "—"

    # Total supporters
    total_supporters = sum(p.get("supporter_count", 0) for p in all_props)

    # Conversion funnel
    conversion_rate = f"{implemented_count}/{total_props} = {round(implemented_count/total_props*100)}%" if total_props > 0 else "—"

    banner_cols = st.columns(4)
    with banner_cols[0]:
        st.metric("📊 转化漏斗", conversion_rate, delta="提案→实施")
    with banner_cols[1]:
        st.metric("👍 总附议", f"{total_supporters} 人次")
    with banner_cols[2]:
        st.metric("🏷️ 最热类别", top_cat)
    with banner_cols[3]:
        response_rate = f"{round((responded + adopted_count + implemented_count)/total_props*100)}%" if total_props > 0 else "—"
        st.metric("📤 回应率", response_rate, delta=f"{responded + adopted_count + implemented_count}/{total_props}")

st.markdown("---")

# ── Reply handler ──
if st.session_state.get("_prop_reply_pid"):
    pid = st.session_state["_prop_reply_pid"]
    prop_title = st.session_state.get("_prop_reply_title", "")
    st.markdown("---")
    st.markdown(f"### ✏️ 回复提案：{prop_title}")
    reply_text = st.text_area("回复内容", placeholder="输入你对这个提案的官方回复...", key="_prop_reply_text")
    c_btn1, c_btn2, c_btn3 = st.columns(3)
    with c_btn1:
        if st.button("📤 回复", type="primary", width="stretch"):
            if reply_text.strip():
                update_proposal_status(pid, "已回应", reply_text.strip())
                invalidate_proposals()
                st.session_state.pop("_prop_reply_pid", None)
                st.session_state.pop("_prop_reply_title", None)
                st.session_state.pop("_prop_reply_text", None)
                st.rerun()
            else:
                st.warning("请输入回复内容")
    with c_btn2:
        if st.button("📤 回复并采纳", width="stretch"):
            if reply_text.strip():
                update_proposal_status(pid, "已采纳", reply_text.strip())
                invalidate_proposals()
                st.session_state.pop("_prop_reply_pid", None)
                st.session_state.pop("_prop_reply_title", None)
                st.session_state.pop("_prop_reply_text", None)
                st.rerun()
            else:
                st.warning("请输入回复内容")
    with c_btn3:
        if st.button("取消", width="stretch"):
            st.session_state.pop("_prop_reply_pid", None)
            st.session_state.pop("_prop_reply_title", None)
            st.rerun()

# ── Proposal cards ──
if not proposals:
    st.info("暂无匹配的提案。")
else:
    medals = ["🥇", "🥈", "🥉"]
    for i, prop in enumerate(proposals):
        pid = prop["id"]
        ptitle = prop.get("title", "")[:40]
        pdesc = prop.get("description", "")[:200]
        pcat = prop.get("category", "")
        pstatus = prop.get("status", "讨论中")
        supporters = prop.get("supporter_count", 0)
        author = prop.get("author", "")
        created = prop.get("created_at", "")[:10]
        response = prop.get("response_text", "")

        with st.container(border=True):
            c_main, c_side = st.columns([4, 1])
            with c_main:
                st.markdown(
                    f'{medals[i] if i < len(medals) and supporters > 10 else "💡"} '
                    f'<strong>{ptitle}</strong>&nbsp;{tag(pstatus)}',
                    unsafe_allow_html=True,
                )
                st.caption(f'{pcat} · 👍 {supporters} 人附议 · 👤 {author} · 🕐 {created}')
                if pdesc:
                    with st.expander("📄 提案详情"):
                        st.write(pdesc)
                if response:
                    st.markdown(
                        f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};'
                        f'background:{TOKEN["success_bg"]};padding:8px 12px;border-radius:6px;'
                        f'margin-top:4px;">💬 <strong>官方回复：</strong>{response[:200]}</div>',
                        unsafe_allow_html=True,
                    )
            with c_side:
                st.markdown("<div style='margin-top:4px;'></div>", unsafe_allow_html=True)
                if pstatus in ("讨论中", "已回应"):
                    if st.button("💬 回复", key=f"prop_reply_{pid}", width="stretch"):
                        st.session_state._prop_reply_pid = pid
                        st.session_state._prop_reply_title = ptitle
                        st.rerun()
                if pstatus == "已回应":
                    if st.button("✅ 采纳", key=f"prop_adopt_{pid}", width="stretch"):
                        update_proposal_status(pid, "已采纳")
                        invalidate_proposals()
                        st.rerun()
                if pstatus == "已采纳":
                    if st.button("🎉 实施", key=f"prop_implement_{pid}", width="stretch"):
                        update_proposal_status(pid, "已实施")
                        invalidate_proposals()
                        st.rerun()
