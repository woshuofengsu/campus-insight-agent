"""💊 吃药提醒 — 今日用药 + 「我已吃」确认 + 提醒设置."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

st.markdown('<div class="elderly-title">💊 吃药提醒</div>', unsafe_allow_html=True)
st.caption("到点系统会提醒您，吃完了点「我已吃」。")

from data.db_elderly import get_profile, due_reminders, set_medication_reminders
from data.db_memory import remember_event

elderly = get_profile(uid) if uid else {}
meds = elderly.get("medication_reminders", [])

if not meds:
    st.info("还没有设置用药提醒。可在下方「家属协助设置」添加。")
else:
    due = due_reminders(uid)
    for m in meds:
        times = "、".join(m.get("times", []))
        is_due = any(d.get("name") == m.get("name") for d in due)
        label = f"{'🔔 ' if is_due else ''}💊 {m.get('name','')} {m.get('dosage','')} · 每天 {times}"
        big_card(f"<strong>{label}</strong>", bg="#fefce8" if is_due else "#ffffff", border="#eab308" if is_due else "#e2e8f0")
        if is_due:
            tts_speak(f"该吃{m.get('name','')}了，{m.get('dosage','')}")
        if st.button(f"✓ 我已吃（{m.get('name','')}）", key=f"taken_{m.get('name')}", width="stretch"):
            if uid:
                remember_event(uid, "medication_taken", f"已服用 {m.get('name','')} {m.get('dosage','')}")
            st.success("已记录，家人和网格员都能看到。")
            st.rerun()

st.markdown("---")

# 家属协助设置用药提醒
with st.expander("➕ 家属协助设置用药提醒", expanded=False):
    with st.form("meds_input"):
        med_name = st.text_input("药名", placeholder="如：降压药")
        med_dosage = st.text_input("剂量", placeholder="如：1片")
        med_times = st.text_input("服用时间（用逗号分隔）", placeholder="如：08:00,20:00")
        if st.form_submit_button("保存提醒", width="stretch"):
            if med_name.strip() and med_times.strip():
                times = [t.strip() for t in med_times.split(",") if t.strip()]
                new_list = [m for m in meds if m.get("name") != med_name.strip()]
                new_list.append({"name": med_name.strip(), "dosage": med_dosage.strip() or "1片", "times": times})
                set_medication_reminders(uid, new_list)
                st.success("已保存")
                st.rerun()
            else:
                st.warning("请填写药名和服用时间")

if st.button("🏠 返回首页", key="meds_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
