# ui/pages/voice.py
"""🗳️ 有话说 · 议 — 提案、附议（一键操作）、议题讨论（直接发言）."""
import streamlit as st
from data.database import (
    support_proposal as db_support,
    add_opinion, get_opinion_summary,
    create_proposal as db_create_proposal,
)
from tools.action_report_issue import _auto_classify
from ui.cache import (
    cached_proposals as get_proposals,
    cached_proposals_stats as get_proposals_stats,
    cached_active_topics as get_active_topics,
    cached_opinions_by_topic as get_opinions,
    invalidate_proposals,
    invalidate_opinions,
)
from ui.components import TOKEN, section, stat, info_card, proposal_card, topic_card, ooda_nav, resolve_author
import logging
_log = logging.getLogger(__name__)

agent = st.session_state.get("agent")
memory = st.session_state.get("memory")
if memory is not None:
    profile = memory.get_user_profile()
else:
    profile = {}

_author = resolve_author(profile)

st.markdown(
    f'<div style="margin-bottom:4px;">'
    f'<span style="font-size:1.35em;font-weight:800;color:{TOKEN["text"]};">🗳️ 有话说</span>'
    f'<span style="background:{TOKEN["accent"]};color:#fff;font-size:0.7em;font-weight:600;'
    f'padding:2px 8px;border-radius:99px;margin-left:8px;vertical-align:middle;">议</span>'
    f'</div>',
    unsafe_allow_html=True,
)
st.caption("提建议、附议别人、参与 系统发起的民意议题——你的声音，校园听得见。")

ooda_nav("voice")

st.markdown("---")

# ✍️ Create proposal form

create_feedback = st.session_state.get("_create_proposal_feedback", "")
create_error = st.session_state.get("_create_proposal_error", "")

with st.container(border=True):
    st.markdown(
        f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};margin-bottom:6px;">'
        f'✍️ 创建提案</div>',
        unsafe_allow_html=True,
    )
    prop_title = st.text_input(
        "提案标题",
        placeholder="比如：建议图书馆延长闭馆时间到23:00...",
        key="create_proposal_title",
    )
    prop_desc = st.text_area(
        "提案描述",
        placeholder="说说为什么提这个建议、具体怎么实施...",
        key="create_proposal_desc",
        height=80,
    )
    c1, c2 = st.columns([2, 1])
    with c1:
        prop_category = st.selectbox(
            "分类（可选，留空自动推断）",
            ["自动推断"] + ["设施维修", "环境卫生", "安全隐患", "教学设备", "网络服务", "餐饮问题", "校园管理", "其他"],
            key="create_proposal_cat",
        )
    with c2:
        submit_prop = st.button("🚀 发布提案", type="primary", width="stretch", key="create_proposal_btn")

    if submit_prop:
        title = prop_title.strip()
        desc = prop_desc.strip()
        if not title or not desc:
            st.session_state._create_proposal_error = "请填写提案标题和描述。"
            st.session_state._create_proposal_feedback = ""
        else:
            cat = _auto_classify(title, desc) if prop_category == "自动推断" else prop_category
            try:
                pid = db_create_proposal(title=title, description=desc, category=cat, author=_author)
                invalidate_proposals()
                st.session_state._create_proposal_feedback = f"✅ 提案 #{pid}「{title[:25]}」已发布！分类：{cat}"
                st.session_state._create_proposal_error = ""
                # Clear all form fields including category
                st.session_state.create_proposal_title = ""
                st.session_state.create_proposal_desc = ""
                st.session_state.create_proposal_cat = "自动推断"
            except Exception as e:
                _log.debug("non-critical failure", exc_info=True)
                st.session_state._create_proposal_error = f"发布失败：{e}"
                st.session_state._create_proposal_feedback = ""
        st.rerun()

if create_feedback:
    st.success(create_feedback)
    st.session_state._create_proposal_feedback = ""
if create_error:
    st.error(create_error)
    st.session_state._create_proposal_error = ""

st.markdown("---")

# Proposals stats

pstats = get_proposals_stats()
total_p = pstats["total"]

c1, c2, c3 = st.columns(3)
with c1:
    stat("提案总数", str(total_p), TOKEN["accent"])
with c2:
    discussing = pstats.get("by_status", {}).get("讨论中", 0)
    stat("讨论中", str(discussing), TOKEN["accent"])
with c3:
    adopted = sum(
        v for k, v in pstats.get("by_status", {}).items()
        if k in ("已采纳", "已实施")
    )
    stat("已采纳/实施", str(adopted), TOKEN["success"])

st.markdown("")

# Proposals — sortable + support inline

section("热门提案")

sort_by = st.radio(
    "排序方式", ["附议最多", "最新发布"],
    horizontal=True, key="proposal_sort",
)
proposals = get_proposals(
    sort_by="supporters" if sort_by == "附议最多" else "latest",
    limit=20,
)

if not proposals:
    info_card("在对话页说'我有个建议'来创建第一个提案！")
else:
    # Track support button clicks
    support_feedback = st.session_state.get("_support_feedback", {})
    support_error = st.session_state.get("_support_error", {})

    for p in proposals:
        pid = p["id"]
        with st.container(border=True):
            c_left, c_right = st.columns([5, 1])
            with c_left:
                # Inline proposal info
                s = p.get("status", "讨论中")
                emoji_map = {"讨论中": "💬", "已回应": "📝", "已采纳": "✅", "已实施": "🎉"}
                emoji = emoji_map.get(s, "📌")
                bg_color = {"讨论中": TOKEN["accent_bg"], "已回应": TOKEN["accent_bg"], "已采纳": TOKEN["success_bg"], "已实施": TOKEN["success_bg"]}.get(s, TOKEN["page_bg"])
                bd_color = {"讨论中": TOKEN["accent_border"], "已回应": TOKEN["accent_border"], "已采纳": TOKEN["success_border"], "已实施": TOKEN["success_border"]}.get(s, TOKEN["border"])
                st.markdown(
                    f'<div style="background:{bg_color};border:1px solid {bd_color};'
                    f'border-radius:{TOKEN["radius_card"]};padding:10px 14px;'
                    f'box-shadow:{TOKEN["shadow"]};font-size:0.88em;line-height:1.5;">'
                    f'{emoji} <strong style="color:{TOKEN["text"]};">{p.get("title","")[:40]}</strong><br>'
                    f'<span style="color:{TOKEN["text_sec"]};font-size:0.82em;">'
                    f'👍 {p.get("supporter_count",0)} 人附议 · {p.get("category","")} · '
                    f'<span style="background:{TOKEN["accent_bg"]};color:{TOKEN["accent"]};'
                    f'padding:0 6px;border-radius:99px;font-size:0.85em;">{s}</span>'
                    f'</span>'
                    f'<div style="color:{TOKEN["text_sec"]};font-size:0.8em;margin-top:4px;">'
                    f'{p.get("description","")[:100]}{"..." if len(p.get("description","") or "") > 100 else ""}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
            with c_right:
                if s in ("讨论中", "已回应"):
                    if st.button("👍 附议", key=f"support_{pid}", width="stretch"):
                        try:
                            new_count = db_support(pid)
                            invalidate_proposals()
                            st.session_state._support_feedback = {str(pid): f"附议成功！{p['title'][:20]} → {new_count} 人"}
                            st.session_state._support_error = {}
                        except Exception as e:
                            _log.debug("non-critical failure", exc_info=True)
                            st.session_state._support_error = {str(pid): str(e)}
                            st.session_state._support_feedback = {}
                        st.rerun()

            # Show feedback for this proposal
            fb_key = str(pid)
            if fb_key in support_feedback:
                st.success(support_feedback[fb_key])
                del st.session_state._support_feedback[fb_key]
            if fb_key in support_error:
                st.error(support_error[fb_key])
                del st.session_state._support_error[fb_key]

st.markdown("---")

# Discussion topics — express opinion inline

section("正在热议")

topics = get_active_topics(limit=20)

if not topics:
    info_card("系统会根据校园热点自动发起讨论")
else:
    opinion_feedback = st.session_state.get("_opinion_feedback", {})

    for t in topics:
        tid = t["id"]
        with st.container(border=True):
            source = "🤖 系统发起" if t.get("created_by_agent") else "👤 管理员"
            st.markdown(
                f'<div style="font-size:0.92em;font-weight:700;color:{TOKEN["text"]};'
                f'margin-bottom:2px;">🔥 {t.get("title","")[:50]}</div>',
                unsafe_allow_html=True,
            )
            st.caption(f"{source} · {t.get('participant_count',0)} 人参与 · {t.get('category','')}")
            if t.get("description"):
                st.markdown(
                    f'<div style="font-size:0.82em;color:{TOKEN["text_sec"]};margin:4px 0 8px;">'
                    f'{t["description"][:150]}</div>',
                    unsafe_allow_html=True,
                )

            # Show existing opinions
            opinions = get_opinions(tid, limit=6)
            if opinions:
                st.markdown(
                    f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};margin:8px 0 4px;">'
                    f'💬 最新意见（{len(opinions)} 条）</div>',
                    unsafe_allow_html=True,
                )
                for op in opinions[:4]:
                    st.markdown(
                        f'<div style="background:{TOKEN["page_bg"]};border-radius:{TOKEN["radius_card"]};'
                        f'padding:6px 10px;margin:3px 0;font-size:0.82em;color:{TOKEN["text"]};">'
                        f'<span style="color:{TOKEN["text_muted"]};font-size:0.85em;">{op.get("participant_label","匿名")}：</span>'
                        f'{op.get("content","")[:100]}</div>',
                        unsafe_allow_html=True,
                    )

            with st.expander("💬 发表你的意见", expanded=False):
                opinion_text = st.text_area(
                    "你的意见（匿名）",
                    placeholder="说说你的想法...",
                    key=f"opinion_input_{tid}",
                    label_visibility="collapsed",
                )
                if st.button("📤 发表意见", key=f"submit_opinion_{tid}"):
                    content = opinion_text.strip()
                    if len(content) < 2:
                        st.warning("意见太短了，至少写几个字~")
                    else:
                        try:
                            add_opinion(topic_id=tid, content=content, participant_label="匿名学生")
                            invalidate_opinions()
                            summary = get_opinion_summary(tid)
                            st.session_state._opinion_feedback = {
                                str(tid): f"✅ 已发表！当前 {summary['total_opinions']} 条意见"
                            }
                            # Clear the input
                            st.session_state[f"opinion_input_{tid}"] = ""
                        except Exception as e:
                            _log.debug("non-critical failure", exc_info=True)
                            st.session_state._opinion_feedback = {str(tid): f"❌ 发表失败：{e}"}
                        st.rerun()

            fb_key = str(tid)
            if fb_key in opinion_feedback:
                st.success(opinion_feedback[fb_key])
                del st.session_state._opinion_feedback[fb_key]

st.markdown("---")

# Status legend

st.markdown(
    f'<div style="font-size:0.75em;color:{TOKEN["text_muted"]};margin-top:12px;">'
    f'💡 提案状态：💬讨论中 → 📝已回应 → ✅已采纳 → 🎉已实施</div>',
    unsafe_allow_html=True,
)
