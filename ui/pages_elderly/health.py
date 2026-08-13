# ui/pages_elderly/health.py
"""🏥 我的健康 — 紧急信息卡 + 血压记录 + 子女电话."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

st.markdown('<div class="elderly-title">🏥 我的健康</div>', unsafe_allow_html=True)
st.caption("紧急时，网格员和急救人员会先看这张卡片。")

from data.db_elderly import get_profile, set_health_info, set_emergency_contact

elderly = get_profile(uid) if uid else {}
health = elderly.get("health_info", {})

# ── 紧急信息卡（急救/网格员上门 3 秒看清） ──
chronic = "、".join(health.get("chronic", [])) or "无"
blood_type = health.get("blood_type", "未记录")
allergy = health.get("allergy", "无")
care_notes = health.get("care_notes", "")
big_card(
    f"🆘 <strong>紧急信息卡</strong><br>"
    f"血型：{blood_type}　过敏：{allergy}<br>"
    f"慢病：{chronic}"
    + (f"<br>⚠️ {care_notes}" if care_notes else ""),
    bg="#fef2f2", border="#dc2626",
)

# ── 血压记录 ──
st.markdown('<div style="font-size:1.25em;font-weight:800;margin:8px 0;">🩺 血压记录</div>', unsafe_allow_html=True)
bp = health.get("blood_pressure", [])
if bp:
    latest = bp[-1]
    big_card(f"最近一次（{latest.get('date','')}）：<strong>{latest.get('sys')}/{latest.get('dia')} mmHg</strong>")
    for rec in bp[-7:][::-1][1:]:
        st.caption(f"{rec.get('date','')}：{rec.get('sys')}/{rec.get('dia')} mmHg")
else:
    st.info("暂无血压记录。")

# ── 子女电话 ──
st.markdown('<div style="font-size:1.25em;font-weight:800;margin:8px 0;">👨‍👩‍👧 紧急联系人</div>', unsafe_allow_html=True)
contacts = elderly.get("emergency_contact", [])
if contacts:
    for c in contacts:
        st.link_button(f"呼叫 {c.get('relation','')} {c.get('name','')}", f"tel:{c.get('phone','')}", width="stretch")
else:
    st.info("未设置紧急联系人。")

# ── 家属/网格员协助录入 ──
with st.expander("➕ 家属/网格员协助录入", expanded=False):
    with st.form("health_input"):
        sys_bp = st.text_input("收缩压（高压）", placeholder="如：150")
        dia_bp = st.text_input("舒张压（低压）", placeholder="如：90")
        child_name = st.text_input("子女姓名", value=(contacts[0].get("name", "") if contacts else ""))
        child_phone = st.text_input("子女电话", value=(contacts[0].get("phone", "") if contacts else ""))
        if st.form_submit_button("保存", width="stretch"):
            new_bp = dict(health.get("blood_pressure", []))
            if sys_bp.strip() and dia_bp.strip():
                from datetime import datetime
                new_bp_list = health.get("blood_pressure", [])
                new_bp_list.append({"date": datetime.now().strftime("%Y-%m-%d"), "sys": int(sys_bp), "dia": int(dia_bp)})
                health["blood_pressure"] = new_bp_list[-7:]
                set_health_info(uid, health)
            if child_phone.strip():
                set_emergency_contact(uid, [{"name": child_name or "子女", "relation": "子女", "phone": child_phone.strip()}])
            st.success("已保存")
            st.rerun()

if st.button("🏠 返回首页", key="health_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
