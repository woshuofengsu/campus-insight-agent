"""💊 用药提醒 — 列表 / 添加 / 详情 + 审核状态 + 暂停/恢复/修改.

对接 data/db_elderly_care（schema v18 medication_reminders 表）。
状态颜色遵循《06-老年端.md》第七节：待审核黄、审核通过绿、审核不通过红、已暂停/已结束灰。
修改后需重新审核，审核期间原规则继续生效。
"""
from datetime import date

import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak
from data.db_elderly_care import (
    add_medication_reminder, format_repeat_rule, get_medication_reminder,
    list_medication_reminders, migrate_legacy_profile, modify_medication,
    pause_medication, resume_medication, status_color,
)

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = st.session_state.get("_elderly_uid") or (profile or {}).get("id")
name = st.session_state.get("_elderly_name") or (profile or {}).get("name", "") or "老人"

if uid:
    migrate_legacy_profile(uid)  # 旧 JSON 数据一次性迁到新表（幂等）

st.markdown('<div class="elderly-title">💊 用药提醒</div>', unsafe_allow_html=True)
st.caption("到点系统会语音提醒您。提醒需社区负责人审核通过后生效。")

_COLOR_HEX = {"黄": "#eab308", "绿": "#16a34a", "红": "#dc2626", "灰": "#64748b", "橙": "#ea580c"}

_REPEAT_BASE = ["每天", "每周固定几天", "每月固定几号", "仅一次"]


def _status_label(status: str) -> str:
    color = _COLOR_HEX.get(status_color(status), "#64748b")
    return (f'<span style="background:{color}1f;color:{color};border:1px solid {color};'
            f'border-radius:99px;padding:2px 12px;font-weight:800;">{status}</span>')


def _split_repeat_rule(rule: str) -> tuple[str, str]:
    """把「每周固定几天:1,3,5」拆成 (基准, 后缀数字串)。"""
    rule = (rule or "每天").strip()
    for base in ("每周固定几天", "每月固定几号"):
        if rule.startswith(base):
            suffix = rule.split(":", 1)[1] if ":" in rule else ""
            return base, suffix
    return rule if rule in ("每天", "仅一次") else "每天", ""


def _render_med_form(uid, existing: dict | None, rid: int | None = None):
    """添加/修改用药提醒表单（共用）。"""
    if existing:
        st.markdown(f'<div class="elderly-title">✏️ 修改用药提醒（{existing["drug_name"]}）</div>',
                    unsafe_allow_html=True)
        st.caption("修改后需重新审核：审核期间原规则继续生效，通过后切换新规则。")
    else:
        st.markdown('<div class="elderly-title">➕ 添加用药提醒</div>', unsafe_allow_html=True)
        st.caption("提交后由社区负责人审核，通过后开始语音提醒。")

    default_patient = existing["patient_name"] if existing else (name if name != "老人" else "")
    rule_base, rule_suffix = _split_repeat_rule(existing["repeat_rule"]) if existing else ("每天", "")
    start_val = date.fromisoformat(existing["start_date"]) if existing and existing.get("start_date") else date.today()
    end_val = None
    if existing and existing.get("end_date"):
        try:
            end_val = date.fromisoformat(existing["end_date"])
        except ValueError:
            end_val = None

    with st.form("meds_form"):
        patient_name = st.text_input("用药人姓名", value=default_patient)
        drug_name = st.text_input("药品名称", value=existing["drug_name"] if existing else "")
        dosage = st.text_input("剂量（数字+单位，如 1片、10ml）",
                               value=existing["dosage"] if existing else "")
        times_str = st.text_input("用药时间（最多 5 个，逗号分隔）",
                                  value="、".join(existing["times"]) if existing and existing["times"] else "08:00")
        rule_base = st.selectbox("重复周期", _REPEAT_BASE,
                                 index=_REPEAT_BASE.index(rule_base) if rule_base in _REPEAT_BASE else 0)
        suffix_input = ""
        if rule_base == "每周固定几天":
            suffix_input = st.text_input("星期（1=周一…7=周日，逗号分隔）", value=rule_suffix,
                                         placeholder="如：1,3,5")
        elif rule_base == "每月固定几号":
            suffix_input = st.text_input("每月几号（逗号分隔）", value=rule_suffix,
                                         placeholder="如：1,15")
        repeat_rule = rule_base + (f":{suffix_input.strip()}" if suffix_input.strip() else "")
        start_d = st.date_input("开始日期", value=start_val)
        end_d = st.date_input("结束日期（选填，晚于开始日期）", value=end_val)
        note = st.text_input("备注（选填，如：饭后服用）", value=existing["note"] if existing else "")
        photo = st.file_uploader("药品照片（选填 jpg/png ≤5MB，仅记录文件名）",
                                 type=["jpg", "jpeg", "png"])
        submitted = st.form_submit_button("提交审核", type="primary", width="stretch")

    if submitted:
        times = [t.strip() for t in times_str.replace("，", ",").split(",") if t.strip()]
        photo_name = ""
        if photo is not None:
            if photo.size > 5 * 1024 * 1024:
                st.error("药品照片不能超过 5MB。")
                return
            photo_name = photo.name
        elif existing:
            photo_name = existing.get("photo") or ""
        if rid:
            ok, err = modify_medication(rid, patient_name, drug_name, dosage, times,
                                        repeat_rule, start_d, end_d, note, photo_name, actor=name)
        else:
            _, err = add_medication_reminder(uid, patient_name, drug_name, dosage, times,
                                             repeat_rule, start_d, end_d, note, photo_name, actor=name)
            ok = err == ""
        if ok:
            st.session_state["_meds_msg"] = (
                "修改已提交审核，审核期间原规则继续生效。" if rid
                else "已提交审核，负责人审核通过后开始提醒。"
            )
            st.session_state["_meds_view"] = "list"
            st.rerun()
        else:
            st.error(err)


# ================================================================ 视图分发
view = st.session_state.get("_meds_view", "list")

if st.session_state.get("_meds_msg"):
    st.success(st.session_state.pop("_meds_msg"))

if view == "list":
    meds = list_medication_reminders(uid) if uid else []
    if not meds:
        st.info("还没有用药提醒。点下方「添加用药提醒」为老人设置。")
    else:
        for m in meds:
            times_show = "、".join(m["times"][:2])
            if len(m["times"]) > 2:
                times_show += f" 等{len(m['times'])}个"
            extra = ""
            bg, border = "#ffffff", "#e2e8f0"
            if m["status"] == "审核不通过":
                extra = f'<br><span style="color:#dc2626;">审核意见：{m.get("audit_opinion") or ""}</span>'
                bg, border = "#fef2f2", "#dc2626"
            elif m["status"] == "待审核":
                bg, border = "#fefce8", "#eab308"
            elif m["pending"]:
                extra = '<br><span style="color:#b45309;">⏳ 修改待审核（原规则继续生效）</span>'
                bg, border = "#fefce8", "#eab308"
            big_card(
                f"{_status_label(m['status'])} <strong>{m['patient_name']} - {m['drug_name']}</strong>　"
                f"{m['dosage']}<br>时间：{times_show} · {format_repeat_rule(m['repeat_rule'])}{extra}",
                bg=bg, border=border,
            )
            if st.button(f"查看详情（{m['drug_name']}）", key=f"med_detail_{m['id']}", width="stretch"):
                st.session_state["_meds_view"] = f"detail:{m['id']}"
                st.rerun()
    if st.button("➕ 添加用药提醒", key="med_add", type="primary", width="stretch"):
        st.session_state["_meds_view"] = "add"
        st.rerun()

elif view == "add":
    _render_med_form(uid, None)
    if st.button("⬅️ 返回列表", key="med_back_add", width="stretch"):
        st.session_state["_meds_view"] = "list"
        st.rerun()

elif view.startswith("edit:"):
    rid = int(view.split(":", 1)[1])
    m = get_medication_reminder(rid)
    if m is None:
        st.error("用药提醒不存在。")
        st.session_state["_meds_view"] = "list"
        st.rerun()
    _render_med_form(uid, m, rid)
    if st.button("⬅️ 返回详情", key="med_back_edit", width="stretch"):
        st.session_state["_meds_view"] = f"detail:{rid}"
        st.rerun()

elif view.startswith("detail:"):
    rid = int(view.split(":", 1)[1])
    m = get_medication_reminder(rid)
    if m is None:
        st.error("用药提醒不存在。")
        st.session_state["_meds_view"] = "list"
        st.rerun()

    fields = [
        f"{_status_label(m['status'])} <strong>{m['patient_name']} - {m['drug_name']}</strong>",
        f"剂量：{m['dosage']}",
        f"用药时间：{'、'.join(m['times'])}",
        f"重复周期：{format_repeat_rule(m['repeat_rule'])}",
        f"开始日期：{m['start_date']}" + (f"　结束日期：{m['end_date']}" if m.get("end_date") else ""),
    ]
    if m.get("note"):
        fields.append(f"备注：{m['note']}")
    if m.get("photo"):
        fields.append(f"药品照片：{m['photo']}（仅记录文件名）")
    big_card("<br>".join(fields), bg="#ffffff", border="#e2e8f0")

    if m.get("audit_opinion"):
        big_card(f"📝 审核意见：{m['audit_opinion']}", bg="#fef2f2", border="#dc2626")
    if m.get("pending"):
        big_card("⏳ 修改待审核（原规则继续生效）", bg="#fefce8", border="#eab308")

    # 语音播报预览（固定模板）
    speech = f"{m['patient_name']}您好，该吃药了：{m['drug_name']}，{m['dosage']}。"
    if m.get("note"):
        speech += f"备注：{m['note']}。"
    tts_speak(speech)

    s = m["status"]
    if s == "审核通过" and not m.get("pending"):
        c1, c2 = st.columns(2)
        with c1:
            if st.button("⏸️ 暂停提醒", key=f"med_pause_{rid}", width="stretch"):
                ok, err = pause_medication(rid, actor=name)
                st.session_state["_meds_msg"] = err or "已暂停，暂停期间不再语音提醒。"
                st.rerun()
        with c2:
            if st.button("✏️ 修改提醒（需重新审核）", key=f"med_edit_{rid}", width="stretch"):
                st.session_state["_meds_view"] = f"edit:{rid}"
                st.rerun()
    elif s == "已暂停":
        if st.button("▶️ 恢复提醒", key=f"med_resume_{rid}", width="stretch"):
            ok, err = resume_medication(rid, actor=name)
            st.session_state["_meds_msg"] = err or "已恢复，将按时语音提醒。"
            st.rerun()
    elif s == "审核不通过":
        if st.button("✏️ 修改并重新提交", key=f"med_edit_{rid}", width="stretch"):
            st.session_state["_meds_view"] = f"edit:{rid}"
            st.rerun()
    elif s == "待审核" and not m.get("pending"):
        st.caption("⏳ 等待负责人审核，通过后开始语音提醒。")
    elif s == "已结束":
        st.caption("该提醒已到期自动结束。")

    if st.button("⬅️ 返回列表", key="med_back_detail", width="stretch"):
        st.session_state["_meds_view"] = "list"
        st.rerun()
