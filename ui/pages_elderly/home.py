# ui/pages_elderly/home.py
"""🏠 老年关怀版首页 — 大字极简入口：SOS / 一键呼叫 / 上报 / 工单 / 吃药 / 健康."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak
from data.db_elderly import get_profile, touch_active, due_reminders, get_care_reminders, sos_request, cancel_sos

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")
name = (profile or {}).get("name", "") or "大爷/阿姨"

# 每次进入即平安打卡（任一互动都算活跃）
if uid:
    touch_active(uid)

# ── 顶部：退出 ──
_top_l, _top_r = st.columns([4, 1])
with _top_r:
    if st.button("退出", key="_elderly_logout"):
        for k in list(st.session_state.keys()):
            if k.startswith("_login") or k == "user_profile" or k in ("agent", "memory", "messages"):
                st.session_state.pop(k, None)
        st.rerun()

st.markdown(f'<div class="elderly-title">👴 {name}，您好！</div>', unsafe_allow_html=True)
st.caption("点下面的大按钮就行，有事随时按红色按钮。")

# ── 到点用药提醒（置顶） ──
due = due_reminders(uid) if uid else []
if due:
    med_text = "，".join(f"{m['name']} {m['dosage']}" for m in due)
    big_card(f"💊 <strong>该吃药了：{med_text}</strong>", bg="#fefce8", border="#eab308")
    tts_speak(f"该吃药了：{med_text}")

# ── 关怀提醒 ──
for item in get_care_reminders(uid) if uid else []:
    big_card(f"{item['icon']} {item['text']}", bg="#f8fafc")

st.markdown("---")

# ── SOS 紧急求助（二次确认防误触） ──
if not st.session_state.get("_sos_done"):
    if not st.session_state.get("_sos_confirm"):
        if st.button("🆘 我出事了", key="sos_main", type="primary", width="stretch"):
            st.session_state._sos_confirm = True
            st.rerun()
    else:
        big_card("⚠️ <strong>确定要求助吗？</strong>会立即通知子女、网格员和物业。", bg="#fef2f2", border="#dc2626")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ 确定求助", key="sos_yes", type="primary", width="stretch"):
                if uid:
                    sos_id = sos_request(uid)
                    st.session_state._sos_id = sos_id
                    try:
                        from data.db_notifications import broadcast_notification
                        broadcast_notification(
                            "sos", f"⚠️ SOS 紧急求助：{name}",
                            f"老年关怀版用户「{name}」发出紧急求助，请立即联系/上门查看。",
                            related_id=sos_id,
                        )
                    except Exception:
                        pass
                st.session_state._sos_done = True
                st.session_state._sos_confirm = False
                st.rerun()
        with c2:
            if st.button("❌ 取消（误按）", key="sos_no", width="stretch"):
                st.session_state._sos_confirm = False
                st.rerun()
else:
    big_card("✅ <strong>已发出求助，子女和网格员正在赶来。</strong>请不要离开原地。", bg="#f0fdf4", border="#16a34a")
    if st.button("我没事了（撤销求助）", key="sos_cancel_after", width="stretch"):
        if st.session_state.get("_sos_id"):
            cancel_sos(st.session_state.pop("_sos_id"))
        st.session_state._sos_done = False
        st.rerun()

st.markdown("---")

# ── 一键呼叫（子女置顶） ──
elderly = get_profile(uid) if uid else {}
contacts = elderly.get("emergency_contact", [])
st.markdown('<div style="font-size:1.3em;font-weight:800;margin:8px 0;">📞 一键呼叫</div>', unsafe_allow_html=True)

if contacts:
    child = contacts[0]
    st.link_button(f"👨‍👩‍👧 呼叫子女 {child.get('name','')}", f"tel:{child.get('phone','')}", width="stretch")
else:
    st.info("未设置子女电话，可在「我的健康」页补录。")

c1, c2, c3 = st.columns(3)
with c1:
    st.link_button("📞 网格员", "tel:62319876", width="stretch")
with c2:
    st.link_button("🔧 物业", "tel:62310086", width="stretch")
with c3:
    st.link_button("🚨 急救 120", "tel:120", width="stretch")

st.markdown("---")

# ── 功能大按钮导航 ──
if st.button("🗣️ 一句话上报", key="go_report", width="stretch"):
    st.switch_page("ui/pages_elderly/report.py")
if st.button("📋 我的工单", key="go_progress", width="stretch"):
    st.switch_page("ui/pages_elderly/progress.py")
if st.button("💊 吃药提醒", key="go_meds", width="stretch"):
    st.switch_page("ui/pages_elderly/meds.py")
if st.button("🏥 我的健康", key="go_health", width="stretch"):
    st.switch_page("ui/pages_elderly/health.py")
if st.button("🔊 听通知", key="go_notify", width="stretch"):
    st.switch_page("ui/pages_elderly/notify.py")
