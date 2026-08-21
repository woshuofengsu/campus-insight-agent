"""🗣️ 一句话上报 — 语音/文字描述问题，自动分类生成工单."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak, voice_input

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = st.session_state.get("_elderly_uid") or (profile or {}).get("id")

st.markdown('<div class="elderly-title">🗣️ 一句话上报</div>', unsafe_allow_html=True)
st.caption("说出或写下您遇到的问题，我们会帮您上报给网格员。")

# 语音输入（识别文本回填到下方输入框，可在输入框修改确认后上报）
_voice_text = voice_input("elderly_voice_text")
if _voice_text and not st.session_state.get("elderly_report_text"):
    st.session_state["elderly_report_text"] = _voice_text
    st.session_state["_elderly_voice_confirm"] = f"已识别：{_voice_text}"
    st.rerun()

if st.session_state.get("_elderly_voice_confirm"):
    st.info(st.session_state["_elderly_voice_confirm"] + "（请确认无误后点「确认上报」，也可直接修改）")
    if st.button("🗑️ 重新说", key="elderly_voice_redo", width="stretch"):
        st.session_state.pop("_elderly_voice_confirm", None)
        st.session_state.pop("elderly_report_text", None)
        st.rerun()

# 报修草稿恢复（跨模块联动 #4：老年端报修入口提示草稿，可继续填写）
if uid:
    try:
        from data.db_repair import get_drafts
        _drafts = get_drafts(uid)
        if _drafts and not st.session_state.get("_elderly_draft_offered"):
            st.session_state["_elderly_draft_count"] = len(_drafts)
            st.session_state["_elderly_draft_offered"] = True
        if st.session_state.get("_elderly_draft_count"):
            if st.button(f"📝 继续填写上次未完成的报修（{st.session_state['_elderly_draft_count']} 份草稿）",
                         key="elderly_draft_resume", width="stretch"):
                _d = _drafts[0]
                st.session_state["elderly_report_text"] = (_d.get("description") or _d.get("title") or "")
                st.session_state["_elderly_draft_id"] = _d["id"]
                st.session_state.pop("_elderly_draft_offered", None)
                st.session_state.pop("_elderly_draft_count", None)
                st.rerun()
    except Exception:
        pass

# 大字输入框（主路径）
text = st.text_area(
    "问题描述", key="elderly_report_text",
    placeholder="比如：3号楼电梯坏了 / 楼道灯不亮了",
    height=140,
)

if st.button("✅ 确认上报", key="elderly_report_btn", type="primary", width="stretch"):
    if not text.strip():
        st.warning("请先说出或写下问题")
    else:
        from tools.action_report_issue import _llm_classify
        from agent.helpers import extract_location
        from data.db_repair import submit_issue

        # 走报修状态机（状态待审核，而不是直接待处理入库）
        category, urgency = _llm_classify(text, "")
        loc = extract_location(text) or (profile or {}).get("community") or "社区"
        _phone = (profile or {}).get("phone") or ""
        _name = (profile or {}).get("name") or "老人"
        draft_id = st.session_state.pop("_elderly_draft_id", None)
        iid, hint = submit_issue(
            title=text.strip()[:80], category=category, issue_type="室内",
            location=loc, description=text.strip(), urgency=urgency or "一般",
            reporter_name=_name, reporter_phone=_phone if len(str(_phone)) == 11 else "13800000000",
            reporter_id=uid, draft_id=draft_id,
        )
        if iid > 0:
            st.session_state._elderly_report_result = f"✅ 已上报成功，工单编号 #{iid}（{category}，待审核）"
        else:
            st.session_state._elderly_report_result = f"上报失败：{hint}"
        st.session_state.pop("elderly_report_text", None)
        st.session_state.pop("_elderly_voice_confirm", None)
        st.rerun()

if st.session_state.get("_elderly_report_result"):
    result = st.session_state["_elderly_report_result"]
    big_card(f"<strong>{result}</strong>", bg="#f0fdf4", border="#16a34a")
    tts_speak(result)
    if st.button("🏠 返回首页", key="elderly_report_back", width="stretch"):
        st.session_state.pop("_elderly_report_result", None)
        st.switch_page("ui/pages_elderly/home.py")
