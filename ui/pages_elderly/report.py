"""🗣️ 一句话上报 — 语音/文字描述问题，自动分类生成工单."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak, voice_input

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

st.markdown('<div class="elderly-title">🗣️ 一句话上报</div>', unsafe_allow_html=True)
st.caption("说出或写下您遇到的问题，我们会帮您上报给网格员。")

# 语音输入（识别文本回填到下方输入框）
_voice_text = voice_input("elderly_voice_text")
if _voice_text and not st.session_state.get("elderly_report_text"):
    st.session_state["elderly_report_text"] = _voice_text
    st.rerun()

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
        from agent.router import route_intent
        from tools.action_report_issue import _llm_classify
        from data.database import report_issue
        from agent.helpers import extract_location

        category, urgency = _llm_classify(text, "")
        loc = extract_location(text)
        iid = report_issue(
            title=text.strip()[:80], category=category, location=loc,
            description=text.strip(), urgency=urgency, reporter_id=uid,
        )
        st.session_state._elderly_report_result = f"✅ 已上报成功，工单编号 #{iid}（{category}）"
        st.session_state.pop("elderly_report_text", None)
        st.rerun()

if st.session_state.get("_elderly_report_result"):
    result = st.session_state["_elderly_report_result"]
    big_card(f"<strong>{result}</strong>", bg="#f0fdf4", border="#16a34a")
    tts_speak(result)
    if st.button("🏠 返回首页", key="elderly_report_back", width="stretch"):
        st.session_state.pop("_elderly_report_result", None)
        st.switch_page("ui/pages_elderly/home.py")
