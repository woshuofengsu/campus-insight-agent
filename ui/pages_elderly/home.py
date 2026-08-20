"""🏠 老年端极简首页 — 大按钮网格 / 紧急求助（长按3秒）/ 联系拨打 / 天气 / 政策问答.

布局（按《06-老年端.md》第七节）：
- 第一行：天气 / 通知 / 报修 / 政策问答
- 第二行：联系社区 / 用药提醒 / 语音帮助
- 底部固定：紧急求助红色大按钮（长按 3 秒触发 → 确认弹窗 → 依次呼叫紧急联系人）
- 顶部：未读通知数量、最近一条联系记录、到点用药提醒
"""
import time

import streamlit as st

from ui.elderly_components import inject_elderly_css, big_card, tts_speak
from data.db_elderly import touch_active
from data.db_elderly_care import (
    COMMUNITY_NAME, COMMUNITY_PHONE, DEFAULT_HELP_TEXT,
    cancel_sos, escalate_sos, get_approved_contacts, get_due_medications,
    get_latest_contact_call, get_latest_sos, list_medication_reminders,
    log_emergency_call, log_sos_dial, migrate_legacy_profile, trigger_sos,
)
from data.db_notifications import get_unread_count, log_activity

inject_elderly_css()

memory = st.session_state.get("memory")
profile = memory.get_user_profile() if memory is not None else {}
uid = (profile or {}).get("id")
name = (profile or {}).get("name", "") or "大爷/阿姨"

if uid:
    touch_active(uid)          # 进入即平安打卡
    migrate_legacy_profile(uid)  # 旧 JSON 数据一次性迁到新表（幂等）

# ---------------------------------------------------------------- JS 片段
# 长按 3 秒触发紧急求助：按住时进度条走满，松开前取消。
# 仅在应用独立页面（window.parent 即顶层）时用 URL 参数回传；嵌入场景降级为文字提示。
_LONG_PRESS_JS = """
<div id="elderly_lp" style="user-select:none;-webkit-user-select:none;cursor:pointer;
  background:#dc2626;color:#ffffff;border:3px solid #b91c1c;border-radius:18px;
  padding:22px;text-align:center;font-size:1.5em;font-weight:800;min-height:92px;">
  🆘 紧急求助<br><span style="font-size:0.65em;font-weight:600;">按住 3 秒呼叫</span>
</div>
<div id="elderly_lp_progress" style="height:10px;background:#e2e8f0;border-radius:99px;
  margin-top:8px;overflow:hidden;">
  <div id="elderly_lp_bar" style="height:100%;width:0%;background:#16a34a;"></div>
</div>
<script>
(function(){
  var el = document.getElementById('elderly_lp');
  var bar = document.getElementById('elderly_lp_bar');
  var timer = null, startT = 0;
  function go(){
    try {
      if (window.parent === window.top) {
        var u = window.parent.location.href.split('?')[0];
        window.parent.location.href = u + '?elderly_sos=1';
      } else {
        el.innerHTML = '已确认触发，请点下方「确认呼叫」按钮';
        el.style.background = '#16a34a';
      }
    } catch(e) {}
  }
  function begin(e){
    if (e) e.preventDefault();
    startT = Date.now();
    timer = setInterval(function(){
      var p = Math.min(100, (Date.now() - startT) / 30);
      bar.style.width = p + '%';
      if (p >= 100) { clearInterval(timer); timer = null; go(); }
    }, 30);
  }
  function end(){ if (timer) { clearInterval(timer); timer = null; bar.style.width = '0%'; } }
  el.addEventListener('pointerdown', begin);
  el.addEventListener('pointerup', end);
  el.addEventListener('pointercancel', end);
  el.addEventListener('pointerleave', end);
})();
</script>
"""

# 确认框 10 秒自动取消（长按/联系拨打通用）：10 秒后回传 ?elderly_confirm_cancel=1
_TIMEOUT_CANCEL_JS = """
<script>
setTimeout(function(){
  try {
    if (window.parent === window.top) {
      var u = window.parent.location.href.split('?')[0];
      window.parent.location.href = u + '?elderly_confirm_cancel=1';
    }
  } catch(e) {}
}, 10000);
</script>
"""

# ---------------------------------------------------------------- URL 参数回传
_qp = st.query_params
if _qp.get("elderly_sos") == "1" and not st.session_state.get("_sos_active"):
    # 长按 3 秒完成 → 进入确认弹窗（防误触）
    st.session_state["_sos_confirm"] = True
    st.session_state["_sos_confirm_at"] = time.time()
    try:
        _qp.clear()
    except Exception:
        pass
    st.rerun()
if _qp.get("elderly_confirm_cancel") == "1":
    # 确认框超时自动取消（紧急求助 / 联系拨打）
    if st.session_state.get("_sos_confirm"):
        log_activity(name or "老人", "紧急求助确认超时自动取消", "emergency_call",
                     module="老年端", detail="确认框 10 秒未操作，已自动取消，未通知负责人")
        st.session_state.pop("_sos_confirm", None)
        st.session_state.pop("_sos_confirm_at", None)
    if st.session_state.get("_dial_target"):
        t = st.session_state["_dial_target"]
        log_activity(name or "老人", "联系确认超时自动取消", "emergency_call",
                     module="老年端", detail=f"确认拨打 {t.get('label', '')} 超时，已自动取消")
        st.session_state.pop("_dial_target", None)
    try:
        _qp.clear()
    except Exception:
        pass
    st.rerun()

# ---------------------------------------------------------------- 紧急求助辅助函数


def _clear_sos_session():
    st.session_state.pop("_sos_call_id", None)
    st.session_state.pop("_sos_dial_idx", None)
    st.session_state.pop("_sos_all_failed", None)
    st.session_state.pop("_sos_confirm", None)
    st.session_state.pop("_sos_confirm_at", None)


def _render_sos_confirm(uid, name):
    """确认弹窗（防误触）：10 秒未操作自动取消。"""
    confirm_at = st.session_state.get("_sos_confirm_at", time.time())
    if time.time() - confirm_at > 10:
        log_activity(name or "老人", "紧急求助确认超时自动取消", "emergency_call",
                     module="老年端", detail="确认框 10 秒未操作，已自动取消，未通知负责人")
        st.session_state.pop("_sos_confirm", None)
        st.session_state.pop("_sos_confirm_at", None)
        st.rerun()
    contacts = get_approved_contacts(uid) if uid else []
    names = "、".join(c["name"] for c in contacts) or "（暂无已审核联系人）"
    big_card(f"⚠️ <strong>将依次呼叫：{names}。确认呼叫吗？</strong><br>"
             f"确认后将通知社区负责人（10 秒内未操作自动取消）",
             bg="#fef2f2", border="#dc2626")
    st.components.v1.html(_TIMEOUT_CANCEL_JS, height=0)
    cc1, cc2 = st.columns(2)
    with cc1:
        if st.button("✅ 确认呼叫", key="sos_yes", type="primary", width="stretch"):
            if not uid:
                st.error("未登录，无法触发紧急求助。")
            else:
                call_id, msg = trigger_sos(uid, actor=name)
                if call_id:
                    st.session_state["_sos_call_id"] = call_id
                    st.session_state["_sos_dial_idx"] = 0
                    st.session_state.pop("_sos_all_failed", None)
                    st.session_state.pop("_sos_confirm", None)
                    st.session_state.pop("_sos_confirm_at", None)
                    st.rerun()
                else:
                    st.error(msg)
    with cc2:
        if st.button("❌ 取消（误按）", key="sos_no", width="stretch"):
            log_activity(name or "老人", "取消紧急求助（误触）", "emergency_call",
                         module="老年端", detail="未触发，不通知负责人")
            st.session_state.pop("_sos_confirm", None)
            st.session_state.pop("_sos_confirm_at", None)
            st.rerun()


def _render_sos_dialing(uid, name, latest, contacts):
    """拨打状态：正在呼叫第 N 个；全部未接通提示；社区/120/撤销常驻。"""
    all_failed = st.session_state.get("_sos_all_failed", False)
    idx = st.session_state.get("_sos_dial_idx", 0)

    if contacts and not all_failed and idx < len(contacts):
        c = contacts[idx]
        big_card(f"📞 <strong>正在呼叫：{c['name']}（第 {idx + 1} 个）</strong><br>电话：{c['phone']}",
                 bg="#fef2f2", border="#dc2626")
        if not st.session_state.get("_sos_calling_announced"):
            st.session_state["_sos_calling_announced"] = True
            tts_speak(f"正在呼叫：{c['name']}，电话 {c['phone']}")
        st.link_button(f"📞 拨打 {c['name']}（{c['phone']}）", f"tel:{c['phone']}", width="stretch")
        st.caption("点号码手机会弹出拨号界面；未接通请点下方按钮继续。")
        nc1, nc2 = st.columns(2)
        with nc1:
            if st.button("📵 未接通，拨打下一个", key="sos_next", width="stretch"):
                log_sos_dial(latest["id"], c["name"], c["phone"], "未接通，转拨下一个",
                             actor=name or "老人")
                if idx + 1 < len(contacts):
                    st.session_state["_sos_dial_idx"] = idx + 1
                else:
                    st.session_state["_sos_all_failed"] = True
                st.rerun()
        with nc2:
            if st.button("🔁 重新拨打当前号码", key="sos_redial", width="stretch"):
                log_sos_dial(latest["id"], c["name"], c["phone"], "重新拨打",
                             actor=name or "老人")
                st.rerun()
    else:
        st.session_state["_sos_all_failed"] = True
        big_card("📵 <strong>电话未接通，请稍后再试。</strong>", bg="#fef2f2", border="#dc2626")
        if not st.session_state.get("_sos_failed_announced"):
            st.session_state["_sos_failed_announced"] = True
            tts_speak("电话未接通，请稍后再试。")

    if st.session_state.get("_sos_all_failed"):
        st.link_button("🚨 拨打 120", "tel:120", width="stretch")

    ac1, ac2, ac3 = st.columns(3)
    with ac1:
        if st.button("🏢 联系社区", key="sos_community", width="stretch"):
            st.session_state["_dial_target"] = {
                "type": "community", "name": COMMUNITY_NAME, "phone": COMMUNITY_PHONE,
                "label": f"社区负责人（{COMMUNITY_PHONE}）",
            }
            st.session_state["_dial_confirm_at"] = time.time()
            st.rerun()
    with ac2:
        st.link_button("🚨 拨打 120", "tel:120", width="stretch")
    with ac3:
        if st.button("我没事了（撤销求助）", key="sos_cancel", width="stretch"):
            cancel_sos(latest["id"], reason="老人撤销求助", actor=name or "老人")
            _clear_sos_session()
            st.rerun()

# ---------------------------------------------------------------- 顶部
_top_l, _top_r = st.columns([4, 1])
with _top_r:
    if st.button("退出", key="_elderly_logout"):
        for k in list(st.session_state.keys()):
            if k.startswith("_login") or k == "user_profile" or k in ("agent", "memory", "messages"):
                st.session_state.pop(k, None)
        st.rerun()

st.markdown(f'<div class="elderly-title">👴 {name}，您好！</div>', unsafe_allow_html=True)
st.caption("点下面的大按钮就行，有事随时按红色按钮。")

# 到点用药提醒（置顶，语音播报一次）
due = get_due_medications(uid) if uid else []
if due:
    med_text = "，".join(f"{d['drug_name']} {d['dosage']}" for d in due)
    big_card(f"💊 <strong>该吃药了：{med_text}</strong>", bg="#fefce8", border="#eab308")
    if not st.session_state.get("_due_announced"):
        st.session_state["_due_announced"] = True
        tts_speak(f"该吃药了：{med_text}")

# 未读通知 + 最近联系记录
unread = get_unread_count(uid) if uid else 0
recent_call = get_latest_contact_call(uid) if uid else None
info_parts = []
if unread:
    info_parts.append(f"🔔 您有 <strong>{unread}</strong> 条未读通知")
if recent_call:
    _t = str(recent_call.get("created_at") or "")
    _hm = _t[11:16] if len(_t) >= 16 else ""
    info_parts.append(f"最近联系：{recent_call.get('target_name') or ''} {_hm}（{recent_call.get('result') or ''}）")
if info_parts:
    st.markdown(" · ".join(info_parts), unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------- 第一行：天气 / 通知 / 报修 / 政策问答
def _weather_label() -> str:
    days, _, _ = _cached_weather()
    if days and days[0]:
        return f"天气 {days[0].get('temp_high', '')}°C"
    return "天气"


@st.cache_data(ttl=600)  # 数据每 10 分钟同步
def _cached_weather():
    try:
        from tools.query_weather import get_today_weather
        return get_today_weather()
    except Exception:
        return None, "", False


c1, c2, c3, c4 = st.columns(4)
with c1:
    if st.button(f"🌤️ {_weather_label()}", key="go_weather", width="stretch"):
        st.session_state["_show_weather"] = not st.session_state.get("_show_weather", False)
        st.rerun()
with c2:
    if st.button(f"🔔 通知（{unread}条未读）", key="go_notify", width="stretch"):
        st.switch_page("ui/pages_elderly/notify.py")
with c3:
    if st.button("🛠️ 报修", key="go_report", width="stretch"):
        st.switch_page("ui/pages_elderly/report.py")
with c4:
    if st.button("🧾 政策问答", key="go_policy", width="stretch"):
        st.session_state["_show_policy"] = not st.session_state.get("_show_policy", False)
        st.rerun()

# ---------------------------------------------------------------- 第二行：联系社区 / 用药提醒 / 语音帮助
meds = list_medication_reminders(uid) if uid else []
_meds_alert = any(
    m["status"] in ("待审核", "审核不通过") or bool(due)
    for m in meds
)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button(f"🏢 联系社区（{COMMUNITY_NAME}）", key="go_community", width="stretch"):
        st.session_state["_dial_target"] = {
            "type": "community", "name": COMMUNITY_NAME, "phone": COMMUNITY_PHONE,
            "label": f"社区负责人（{COMMUNITY_PHONE}）",
        }
        st.session_state["_dial_confirm_at"] = time.time()
        st.rerun()
with c2:
    _dot = " 🔴" if _meds_alert else ""
    if st.button(f"💊 用药提醒{_dot}", key="go_meds", width="stretch"):
        st.switch_page("ui/pages_elderly/meds.py")
with c3:
    if st.button("🔊 语音帮助", key="go_help", width="stretch"):
        st.session_state["_help_tts"] = True
        st.rerun()
if st.session_state.get("_help_tts"):
    tts_speak(DEFAULT_HELP_TEXT)

# ---------------------------------------------------------------- 天气（大字版，内联）
if st.session_state.get("_show_weather"):
    st.markdown("### 🌤️ 大字版天气")
    days, loc, is_real = _cached_weather()
    if days and days[0]:
        t = days[0]
        is_bad = t.get("rain_prob", 0) >= 60 or t.get("condition", "") in (
            "暴雨", "雷阵雨", "大雪", "沙尘暴", "大风",
        )
        alert_html = (
            f'<br><span style="color:#dc2626;font-weight:800;">⚠️ 极端天气预警：'
            f'{t.get("condition", "")}，请注意出行安全！</span>' if is_bad else ""
        )
        big_card(
            f"{t.get('emoji', '')} <strong>{t.get('condition', '')}</strong>　"
            f"{t.get('temp_low', '')}°C ~ {t.get('temp_high', '')}°C<br>"
            f"降水概率：{t.get('rain_prob', 0)}% ｜ {t.get('wind', '')}<br>"
            f"建议：{t.get('advice', '')}{alert_html}",
            bg="#fef2f2" if is_bad else "#f0f9ff",
            border="#dc2626" if is_bad else "#2563eb",
        )
        tts_speak(f"今天{t.get('condition', '')}，{t.get('temp_low', '')}到{t.get('temp_high', '')}度，"
                  f"{t.get('advice', '')}。")
    else:
        st.info("天气数据暂时不可用，请稍后再试。")

# ---------------------------------------------------------------- 政策问答（内联，查知识库）
if st.session_state.get("_show_policy"):
    st.markdown("### 🧾 政策问答")
    q = st.text_input("您想问什么？（如：高龄补贴怎么领）", key="elderly_policy_q",
                      placeholder="输入您想了解的政策问题")
    if st.button("🔍 查询", key="policy_search", width="stretch"):
        if q.strip():
            try:
                from data.db_knowledge import search_knowledge
                hits = search_knowledge(q.strip())
                st.session_state["_policy_answer"] = hits[0] if hits else None
            except Exception:
                st.session_state["_policy_answer"] = None
            st.rerun()
    ans = st.session_state.get("_policy_answer")
    if ans is not None:
        if ans:
            big_card(f"<strong>{ans.get('title', '')}</strong><br>{ans.get('content', '')}",
                     bg="#f0fdf4", border="#16a34a")
            tts_speak(f"{ans.get('title', '')}。{ans.get('content', '')}")
        else:
            st.info("没找到相关回答，可联系社区负责人咨询。")
            tts_speak("没有找到相关回答，可联系社区负责人咨询。")

st.markdown("---")

# ---------------------------------------------------------------- 联系家属/网格员（一键拨打 + 确认弹窗）
approved = get_approved_contacts(uid) if uid else []
if approved:
    st.markdown('<div style="font-size:1.25em;font-weight:800;margin:6px 0;">📞 联系家属</div>',
                unsafe_allow_html=True)
    for c in approved:
        if st.button(f"📞 联系 {c['relation']} {c['name']}", key=f"call_contact_{c['id']}",
                     width="stretch"):
            st.session_state["_dial_target"] = {
                "type": "contact", "name": c["name"], "phone": c["phone"],
                "label": f"{c['name']}（{c['relation']}）",
            }
            st.session_state["_dial_confirm_at"] = time.time()
            st.rerun()
elif uid:
    st.caption("还没有审核通过的紧急联系人，可在家属协助下先添加（用药提醒/健康页）。")

# 联系拨打确认弹窗
if st.session_state.get("_dial_target"):
    target = st.session_state["_dial_target"]
    confirm_at = st.session_state.get("_dial_confirm_at", time.time())
    if time.time() - confirm_at > 10:
        log_activity(name or "老人", "联系确认超时自动取消", "emergency_call",
                     module="老年端", detail=f"确认拨打 {target.get('label', '')} 超时，已自动取消")
        st.session_state.pop("_dial_target", None)
        st.rerun()
    big_card(f"📞 <strong>确认拨打：{target.get('label', '')}？</strong>（10 秒内未操作将自动取消）",
             bg="#eff6ff", border="#2563eb")
    st.components.v1.html(_TIMEOUT_CANCEL_JS, height=0)
    dc1, dc2 = st.columns(2)
    with dc1:
        if st.button("✅ 确认拨打", key="dial_yes", type="primary", width="stretch"):
            log_emergency_call(uid, "contact", target.get("name", ""), target.get("phone", ""),
                               "已拨打", status="已结束", actor=name or "老人")
            st.session_state["_last_dial"] = target
            st.session_state["_dial_result"] = f"已为您拨打 {target.get('label', '')}，请留意通话。"
            st.session_state.pop("_dial_target", None)
            st.rerun()
    with dc2:
        if st.button("❌ 取消", key="dial_no", width="stretch"):
            log_emergency_call(uid, "contact", target.get("name", ""), target.get("phone", ""),
                               "已取消", status="已取消", actor=name or "老人")
            st.session_state.pop("_dial_target", None)
            st.rerun()

# 拨打结果（大字号 + 语音播报一次 + 未接通可重新拨打）
if st.session_state.get("_dial_result"):
    result = st.session_state["_dial_result"]
    big_card(f"📞 <strong>{result}</strong>", bg="#f0fdf4", border="#16a34a")
    if not st.session_state.get("_dial_result_announced"):
        st.session_state["_dial_result_announced"] = True
        tts_speak(result)
    rc1, rc2 = st.columns(2)
    with rc1:
        if st.button("📵 未接通，重新拨打", key="dial_retry", width="stretch"):
            last = st.session_state.get("_last_dial") or {}
            if last:
                log_emergency_call(uid, "contact", last.get("name", ""), last.get("phone", ""),
                                   "重新拨打", status="已结束", actor=name or "老人")
            st.session_state["_dial_result_announced"] = False
            st.rerun()
    with rc2:
        if st.button("✅ 知道了", key="dial_ok", width="stretch"):
            st.session_state.pop("_dial_result", None)
            st.session_state.pop("_dial_result_announced", None)
            st.rerun()

# ---------------------------------------------------------------- 底部固定：紧急求助
st.markdown("---")
st.markdown(
    '<div style="font-size:1.1em;font-weight:800;color:#64748b;text-align:center;">'
    '🆘 紧急求助（长按 3 秒，误触点取消即可）</div>', unsafe_allow_html=True)

latest_sos = get_latest_sos(uid) if uid else None
_sos_active = bool(latest_sos and latest_sos["status"] in ("求助中", "已响应"))

if _sos_active:
    # ---- 进行中：拨打状态 / 负责人响应状态 ----
    if latest_sos["status"] == "求助中":
        try:
            escalate_sos(latest_sos["id"])   # 10 分钟未响应自动升级（幂等）
        except Exception:
            pass
        latest_sos = get_latest_sos(uid) or latest_sos

    if latest_sos["status"] == "求助中":
        if "已升级" in (latest_sos.get("result") or ""):
            big_card(f"🚨 {latest_sos['result']}", bg="#fef2f2", border="#dc2626")
        _render_sos_dialing(uid, name, latest_sos, approved)
    else:  # 已响应
        big_card("✅ <strong>负责人已确认响应，正在赶来处理。</strong><br>请保持电话畅通，不要离开原地。",
                 bg="#f0fdf4", border="#16a34a")
        if not st.session_state.get("_sos_responded_announced"):
            st.session_state["_sos_responded_announced"] = True
            tts_speak("负责人已响应您的紧急求助，正在赶来。")
        if st.button("我没事了（收起求助状态）", key="sos_clear", width="stretch"):
            _clear_sos_session()
            st.rerun()
else:
    # ---- 非进行中：最近一次结果 + 触发入口 ----
    if latest_sos and latest_sos["status"] == "已结束":
        big_card(f"✅ <strong>您的紧急求助已处理。</strong><br>处理结果：{latest_sos.get('handle_note') or ''}",
                 bg="#f0fdf4", border="#16a34a")
        if not st.session_state.get("_sos_ended_announced"):
            st.session_state["_sos_ended_announced"] = True
            tts_speak("您的紧急求助已处理。")
    elif latest_sos and latest_sos["status"] == "已取消":
        big_card(f"ℹ️ 最近一次求助已取消：{latest_sos.get('result') or '已取消'}",
                 bg="#f8fafc", border="#cbd5e1")

    if st.session_state.get("_sos_confirm"):
        _render_sos_confirm(uid, name)
    else:
        st.components.v1.html(_LONG_PRESS_JS, height=130)
        if st.button("🆘 紧急求助（点此进入确认，防误触）", key="sos_fallback",
                     type="primary", width="stretch"):
            st.session_state["_sos_confirm"] = True
            st.session_state["_sos_confirm_at"] = time.time()
            st.rerun()
