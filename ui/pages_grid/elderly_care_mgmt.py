# ui/pages_grid/elderly_care_mgmt.py
"""👴 老年关怀管理 — 用药提醒审核 / 紧急联系人审核 / 紧急求助处理（负责人端）。"""
import streamlit as st

from ui.components import TOKEN, section, page_header
from data.db_elderly_care import (
    list_medication_reminders, audit_medication,
    list_emergency_contacts, audit_emergency_contact,
    get_sos_calls, respond_sos, end_sos,
)

page_header("👴 老年关怀管理", "用药提醒 / 紧急联系人审核 + 紧急求助处理")

tab1, tab2, tab3 = st.tabs(["💊 用药提醒审核", "🆘 紧急联系人审核", "🚨 紧急求助处理"])

# ---------- Tab1：用药提醒审核 ----------
with tab1:
    section("待审核用药提醒")
    pending = list_medication_reminders(status="待审核")
    if not pending:
        st.caption("暂无待审核的用药提醒。")
    for r in pending:
        title = f"{r['patient_name']} · {r['drug_name']} {r['dosage']} · {r['times_json']}"
        with st.expander(title, expanded=False):
            st.caption(f"重复周期：{r['repeat_rule']} ｜ 开始 {r['start_date']} ｜ 结束 {r.get('end_date') or '长期'}")
            if r.get("note"):
                st.write(f"备注：{r['note']}")
            opinion = st.text_input("审核意见（不通过必填）", key=f"med_op_{r['id']}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 通过", key=f"med_ok_{r['id']}"):
                    ok, msg = audit_medication(r["id"], True, actor="负责人")
                    st.success(msg or "已通过，将按时语音提醒") if ok else st.error(msg)
                    if ok:
                        st.rerun()
            with c2:
                if st.button("❌ 不通过", key=f"med_no_{r['id']}"):
                    if not opinion.strip():
                        st.error("审核不通过必须填写意见")
                    else:
                        ok, msg = audit_medication(r["id"], False, opinion.strip(), actor="负责人")
                        st.success(msg or "已退回") if ok else st.error(msg)
                        if ok:
                            st.rerun()

    section("全部用药提醒")
    all_meds = list_medication_reminders()
    if not all_meds:
        st.caption("暂无用药提醒记录。")
    for r in all_meds:
        color = {
            "待审核": TOKEN["warning"], "审核通过": TOKEN["success"],
            "审核不通过": TOKEN["danger"], "已暂停": TOKEN["text_muted"],
            "已结束": TOKEN["text_muted"],
        }.get(r["status"], TOKEN["text_muted"])
        st.markdown(
            f"<span style='color:{color};font-weight:600;'>{r['status']}</span>  "
            f"{r['patient_name']} · {r['drug_name']} {r['dosage']} · {r['times_json']}",
            unsafe_allow_html=True,
        )
        if r.get("audit_opinion"):
            st.caption(f"审核意见：{r['audit_opinion']}")

    section("📢 用药播报记录（最近 20 条）")
    try:
        from data.db_core import get_db
        with get_db() as conn:
            rows = conn.execute(
                "SELECT actor, detail, created_at FROM activity_log "
                "WHERE module='老年端' AND action='用药提醒播报' ORDER BY id DESC LIMIT 20"
            ).fetchall()
        if not rows:
            st.caption("暂无播报记录（老人打开老年端首页且到点用药时触发）。")
        for r in rows:
            st.caption(f"🕐 {(r['created_at'] or '')[:16]} · {r['actor']} · {r['detail'] or ''}")
    except Exception:
        st.caption("暂无播报记录。")

# ---------- Tab2：紧急联系人审核 ----------
with tab2:
    section("待审核紧急联系人")
    pending_c = list_emergency_contacts()
    pending_c = [c for c in pending_c if c["status"] == "待审核"]
    if not pending_c:
        st.caption("暂无待审核的紧急联系人。")
    for c in pending_c:
        with st.expander(f"{c['name']}（{c['relation']}）· {c['phone']}", expanded=False):
            opinion = st.text_input("审核意见（不通过必填）", key=f"ct_op_{c['id']}")
            c1, c2 = st.columns(2)
            with c1:
                if st.button("✅ 通过", key=f"ct_ok_{c['id']}"):
                    ok, msg = audit_emergency_contact(c["id"], True, actor="负责人")
                    st.success(msg or "已通过") if ok else st.error(msg)
                    if ok:
                        st.rerun()
            with c2:
                if st.button("❌ 不通过", key=f"ct_no_{c['id']}"):
                    if not opinion.strip():
                        st.error("审核不通过必须填写意见")
                    else:
                        ok, msg = audit_emergency_contact(c["id"], False, opinion.strip(), actor="负责人")
                        st.success(msg or "已退回") if ok else st.error(msg)
                        if ok:
                            st.rerun()

    section("全部紧急联系人")
    all_c = list_emergency_contacts()
    if not all_c:
        st.caption("暂无紧急联系人记录。")
    for c in all_c:
        color = {"待审核": TOKEN["warning"], "审核通过": TOKEN["success"],
                 "审核不通过": TOKEN["danger"]}.get(c["status"], TOKEN["text_muted"])
        st.markdown(
            f"<span style='color:{color};font-weight:600;'>{c['status']}</span>  "
            f"{c['name']}（{c['relation']}）· {c['phone']}",
            unsafe_allow_html=True,
        )

# ---------- Tab3：紧急求助处理 ----------
with tab3:
    section("待处理紧急求助")
    sos_pending = get_sos_calls(status="求助中") + get_sos_calls(status="已响应")
    if not sos_pending:
        st.caption("暂无待处理的紧急求助。")
    for s in sos_pending:
        with st.expander(
            f"#{s['id']} · 状态：{s['status']} · 拨打 {s['target_name'] or '—'} {s['target_phone'] or ''}",
            expanded=False,
        ):
            st.caption(f"触发时间：{s.get('created_at')}")
            if s["status"] == "求助中":
                if st.button("📞 确认响应", key=f"sos_resp_{s['id']}"):
                    ok, msg = respond_sos(s["id"], actor="负责人")
                    st.success(msg or "已响应") if ok else st.error(msg)
                    if ok:
                        st.rerun()
            if s["status"] in ("求助中", "已响应"):
                note = st.text_area("处理结果（结束必填）", key=f"sos_note_{s['id']}")
                if st.button("🏁 结束求助", key=f"sos_end_{s['id']}"):
                    if not note.strip():
                        st.error("处理结果不能为空")
                    else:
                        ok, msg = end_sos(s["id"], note.strip(), actor="负责人")
                        st.success(msg or "已结束，老人端将收到通知") if ok else st.error(msg)
                        if ok:
                            st.rerun()

    section("历史求助记录")
    sos_all = get_sos_calls(limit=30)
    if not sos_all:
        st.caption("暂无求助记录。")
    for s in sos_all:
        st.markdown(
            f"**#{s['id']}** {s['status']} · {s['created_at']}"
            f"{' · ' + s['target_name'] if s.get('target_name') else ''}"
            f"{' · ' + (s.get('handle_note') or '')[:40] if s.get('handle_note') else ''}"
        )
