"""🏥 我的健康 — 紧急信息卡 + 血压记录 + 紧急联系人."""
import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card
from data.db_elderly_care import (
    add_emergency_contact, list_emergency_contacts, migrate_legacy_profile,
    status_color,
)

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")

if uid:
    migrate_legacy_profile(uid)  # 旧 JSON 数据一次性迁到新表（幂等）

st.markdown('<div class="elderly-title">🏥 我的健康</div>', unsafe_allow_html=True)
st.caption("紧急时，网格员和急救人员会先看这张卡片。")

from data.db_elderly import get_profile, set_health_info

elderly = get_profile(uid) if uid else {}
health = elderly.get("health_info", {})

# 紧急信息卡：急救或网格员上门 3 秒看清
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

# 血压记录
st.markdown('<div style="font-size:1.25em;font-weight:800;margin:8px 0;">🩺 血压记录</div>', unsafe_allow_html=True)
bp = health.get("blood_pressure", [])
if bp:
    latest = bp[-1]
    big_card(f"最近一次（{latest.get('date','')}）：<strong>{latest.get('sys')}/{latest.get('dia')} mmHg</strong>")
    for rec in bp[-7:][::-1][1:]:
        st.caption(f"{rec.get('date','')}：{rec.get('sys')}/{rec.get('dia')} mmHg")
else:
    st.info("暂无血压记录。")

# 紧急联系人（新表，负责人审核后生效）
st.markdown('<div style="font-size:1.25em;font-weight:800;margin:8px 0;">👨‍👩‍👧 紧急联系人</div>', unsafe_allow_html=True)
_color_hex = {"黄": "#eab308", "绿": "#16a34a", "红": "#dc2626", "灰": "#64748b", "橙": "#ea580c"}
contacts = list_emergency_contacts(uid) if uid else []
if contacts:
    for c in contacts:
        _color = _color_hex.get(status_color(c.get("status", "")), "#64748b")
        _label = (f'<span style="background:{_color}1f;color:{_color};border:1px solid {_color};'
                  f'border-radius:99px;padding:1px 10px;font-size:0.85em;font-weight:700;">'
                  f"{c.get('status', '')}</span>")
        st.link_button(
            f"📞 呼叫 {c.get('relation', '')} {c.get('name', '')}（{c.get('phone', '')}）",
            f"tel:{c.get('phone', '')}", width="stretch",
        )
        st.caption(f"{c.get('relation', '')} {c.get('name', '')}　{_label}"
                   + (f"　审核意见：{c.get('audit_opinion', '')}" if c.get("audit_opinion") else ""),
                   unsafe_allow_html=True)
else:
    st.info("未设置紧急联系人，可在下方协助录入（需负责人审核通过后生效）。")

# 家属或网格员帮忙录入
with st.expander("➕ 家属/网格员协助录入", expanded=False):
    with st.form("health_input"):
        sys_bp = st.text_input("收缩压（高压）", placeholder="如：150")
        dia_bp = st.text_input("舒张压（低压）", placeholder="如：90")
        child_name = st.text_input("联系人姓名", value=(contacts[0].get("name", "") if contacts else ""))
        child_phone = st.text_input("联系人电话（11 位手机号）",
                                    value=(contacts[0].get("phone", "") if contacts else ""))
        child_rel = st.text_input("与老人关系", value=(contacts[0].get("relation", "") if contacts else "家属"))
        if st.form_submit_button("保存", width="stretch"):
            from datetime import datetime
            msg = ""
            if sys_bp.strip() and dia_bp.strip():
                try:
                    new_bp_list = health.get("blood_pressure", [])
                    new_bp_list.append({"date": datetime.now().strftime("%Y-%m-%d"),
                                        "sys": int(sys_bp), "dia": int(dia_bp)})
                    health["blood_pressure"] = new_bp_list[-7:]
                    set_health_info(uid, health)
                except ValueError:
                    msg = "血压请填数字。"
            if child_phone.strip() and not msg:
                cid, cmsg = add_emergency_contact(uid, child_name or "家属", child_phone.strip(),
                                                  child_rel.strip() or "家属", actor=child_name or "家属")
                if cid:
                    msg = "已保存：紧急联系人已提交，待负责人审核通过后生效。"
                else:
                    msg = cmsg
            st.success(msg or "已保存")
            st.rerun()

if st.button("🏠 返回首页", key="health_back", width="stretch"):
    st.switch_page("ui/pages_elderly/home.py")
