"""📋 我的工单 — 大字版进度查看（报修状态机）+ 满意度反馈（家属可代，留痕）。"""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = st.session_state.get("_elderly_uid") or (profile or {}).get("id")
name = st.session_state.get("_elderly_name") or (profile or {}).get("name", "") or "老人"

st.markdown('<div class="elderly-title">📋 我的工单</div>', unsafe_allow_html=True)
st.caption("您上报过的问题，都在这里。")

# 报修状态机工单（老年端上报走 db_repair.submit_issue）
from data.db_repair import get_issues as _get_issues, feedback_issue

repair_issues = _get_issues(reporter_id=uid, limit=20) if uid else []
# 旧治理工单（早期路径）
from data.database import get_my_issues, get_my_anonymous_issues
from ui.components import resolve_author

_author = resolve_author(profile)
legacy = get_my_issues(_author, limit=20)
anon = get_my_anonymous_issues(uid, limit=20) if uid else []
seen = {i["id"] for i in repair_issues}
legacy += [a for a in anon if a["id"] not in seen]

_emoji = {"待审核": "📝", "退回补充信息": "↩️", "已审核待派单": "📌", "已派单": "🔧",
          "处理中": "🔄", "待居民反馈": "🧐", "处理结束": "✅", "已关闭": "🚫",
          "待协商": "🤝", "已转出": "📤", "已撤回": "🗑️"}

if not repair_issues and not legacy:
    st.info("还没有工单。有问题就点「一句话上报」。")
else:
    for i in (repair_issues + legacy)[:10]:
        stt = i.get("status", "")
        emoji = _emoji.get(stt, "📌")
        extra = ""
        if i.get("assignee_name"):
            extra = f" · 维修人员：{i['assignee_name']}"
        big_card(
            f"{emoji} <strong>#{i['id']} {i.get('title', '')[:30]}</strong><br>"
            f"状态：{stt}{extra} · {((i.get('reported_at') or '')[:16])}"
        )
        # 待居民反馈：满意度反馈（家属可代老人反馈并留痕，spec）
        if stt == "待居民反馈":
            sat = st.radio("问题解决了吗？", ["满意", "不满意"], horizontal=True,
                           key=f"pr_sat_{i['id']}")
            reason = ""
            if sat == "不满意":
                reason = st.text_input("不满意原因（必填）", key=f"pr_reason_{i['id']}")
            if st.button("📤 提交反馈", key=f"pr_btn_{i['id']}", type="primary", width="stretch"):
                ok, msg = feedback_issue(i["id"], sat == "满意", reason,
                                         actor=name or "老人")
                if ok:
                    st.success("反馈已提交，感谢您的反馈！" if sat == "满意" else "反馈已提交，将重新处理。")
                    st.rerun()
                else:
                    st.error(msg)

if st.button("🏠 返回首页", key="progress_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
