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
uid = st.session_state.get("_elderly_uid") or (profile or {}).get("id")
name = st.session_state.get("_elderly_name") or (profile or {}).get("name", "") or "大爷/阿姨"
# 家属代操作模式（spec 06：家属不能代替老人触发紧急求助）
_is_family_mode = bool(st.session_state.get("_elderly_uid")) and \
    st.session_state.get("_elderly_uid") != (profile or {}).get("id")

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
        # 全部未接通：通知负责人端（spec：同时通知负责人端，可代为跟进）
        if not st.session_state.get("_sos_all_failed_notified"):
            st.session_state["_sos_all_failed_notified"] = True
            try:
                from data.db_elderly_care import _notify_grids
                _notify_grids(f"📵 紧急求助联系人全部未接通（#{latest['id']}）",
                              f"老人 {name} 的紧急求助电话全部未接通，请负责人主动联系老人或其家属确认情况。",
                              related_id=latest["id"])
            except Exception:
                pass
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

st.markdown(f'<div class="elderly-title">🏘️ 社区服务</div>', unsafe_allow_html=True)
st.caption(f"您好，{name}！点下面的大按钮就行，有事随时按红色按钮。")

# 音量设置（spec：语音按老人设置音量）
_vol_map = {"低": 0.5, "中": 1.0, "高": 1.5}
_vc1, _vc2 = st.columns([3, 1])
with _vc1:
    _vol_choice = st.selectbox("🔊 音量", ["中", "低", "高"],
                               index=["中", "低", "高"].index(
                                   next((k for k, v in _vol_map.items()
                                         if abs(v - float(st.session_state.get("_tts_volume", 1.0))) < 0.01),
                                        "中")),
                               key="elderly_volume")
with _vc2:
    st.markdown("<div style='margin-top:26px;'></div>", unsafe_allow_html=True)
    if st.button("保存音量", key="elderly_volume_save", width="stretch"):
        st.session_state["_tts_volume"] = _vol_map.get(_vol_choice, 1.0)
        tts_speak("音量已设置")
        st.rerun()

# 疾病预防联动语音提醒（#33：每天最多一次，最多连续 7 天；打开页面即播报）
try:
    from data.db_health_content import get_elderly_linkage_reminders, log_elderly_linkage_reminder
    _linkage_reminders = get_elderly_linkage_reminders()
    if _linkage_reminders and not st.session_state.get("_elderly_linkage_announced"):
        st.session_state["_elderly_linkage_announced"] = True
        for _lr in _linkage_reminders[:2]:
            big_card(f"🩺 <strong>健康提醒：{_lr.get('text', '')}</strong>", bg="#f0f9ff", border="#2563eb")
            tts_speak(_lr.get("text", ""))
            log_elderly_linkage_reminder(_lr["content_id"], _lr.get("text", "")[:80])
except Exception:
    pass

# 到点用药提醒（置顶，语音播报一次）
due = get_due_medications(uid) if uid else []
if due:
    # 同一时间超 3 条：先提示数量（spec：您有 X 条用药提醒）
    if len(due) > 3:
        big_card(f"💊 <strong>您有 {len(due)} 条用药提醒</strong>", bg="#fefce8", border="#eab308")
        tts_speak(f"您有 {len(due)} 条用药提醒，请查看。")
    else:
        med_text = "，".join(f"{d['drug_name']} {d['dosage']}" for d in due)
        big_card(f"💊 <strong>该吃药了：{med_text}</strong>", bg="#fefce8", border="#eab308")
        if not st.session_state.get("_due_announced"):
            st.session_state["_due_announced"] = True
            tts_speak(f"该吃药了：{med_text}")
            # 播报记录（spec 06.4：记录每次播报时间，负责人后台可查看）
            try:
                from data.db_notifications import log_activity
                log_activity(name or "老人", "用药提醒播报", "medication_reminder", uid,
                             med_text, module="老年端", detail=f"播报用药：{med_text}")
            except Exception:
                pass

# 未读通知 + 最近联系记录
# 广播通知未读数（spec：老年端「通知」按钮显示广播通知未读数量）
try:
    from data.db_notice import get_notice_unread_count as _notice_unread
    unread = _notice_unread("elderly", uid) if uid else 0
except Exception:
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

# ---------------------------------------------------------------- 两行三列大按钮（spec：天气/通知/报修/联系社区/用药提醒/语音帮助）
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


@st.cache_data(ttl=600)  # 大字版简化天气补充（预警标签 + 更新时间），每 10 分钟同步
def _cached_simplified_weather(city: str = ""):
    try:
        from data.db_weather import get_simplified_weather
        return get_simplified_weather(city)
    except Exception:
        return None


# 第一行：天气 / 通知 / 报修（两行三列之一）
r1a, r1b, r1c = st.columns(3)
with r1a:
    if st.button(f"🌤️ {_weather_label()}", key="go_weather", width="stretch"):
        st.session_state["_show_weather"] = not st.session_state.get("_show_weather", False)
        st.rerun()
with r1b:
    if st.button(f"🔔 通知（{unread}条未读）", key="go_notify", width="stretch"):
        st.switch_page("ui/pages_elderly/notify.py")
with r1c:
    if st.button("🛠️ 报修", key="go_report", width="stretch"):
        st.switch_page("ui/pages_elderly/report.py")

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

# 政策问答（两行三列外的附加入口，保留语音问答功能）
if st.button("📖 政策问答（语音提问）", key="go_policy", width="stretch"):
    st.session_state["_show_policy"] = not st.session_state.get("_show_policy", False)
    st.rerun()

# ---------------------------------------------------------------- 天气（大字版，内联）
if st.session_state.get("_show_weather"):
    st.markdown(f"### 🌤️ {COMMUNITY_NAME}天气")
    days, loc, is_real = _cached_weather()

    # 极端天气主动提醒（每天一次，红色播报两遍；点「我知道了」关闭当次）
    try:
        from data.db_weather import get_elderly_reminder_plan, log_elderly_reminder
        _plan = get_elderly_reminder_plan()
        _pending = [p for p in _plan if p.get("should_send")]
        if _pending and not st.session_state.get("_weather_alert_done", False):
            for p in _pending:
                big_card(
                    f"<div style='text-align:center;font-size:1.35em;font-weight:800;'>"
                    f"⚠️ {p.get('alert_type','')}{p.get('level','')}预警</div>"
                    f"<div style='text-align:center;margin-top:8px;'>{p.get('text','')}</div>",
                    bg="#fef2f2", border="#dc2626",
                )
                tts_speak(p.get("text", ""))
                if p.get("broadcast_times", 1) >= 2:
                    tts_speak(p.get("text", ""))  # 红色预警播报两遍
                log_elderly_reminder(p.get("alert_id"), p.get("alert_type", ""), p.get("level", ""))
            if st.button("我知道了", key="weather_alert_ok", width="stretch"):
                st.session_state["_weather_alert_done"] = True
                st.rerun()
    except Exception:
        pass

    if days and days[0]:
        t = days[0]
        is_bad = t.get("rain_prob", 0) >= 60 or t.get("condition", "") in (
            "暴雨", "雷阵雨", "大雪", "沙尘暴", "大风",
        )
        # 温度颜色：高温红 / 低温蓝 / 一般黑
        def _temp_color(v):
            try:
                v = int(v)
            except (TypeError, ValueError):
                return "#111827"
            if v >= 33:
                return "#dc2626"
            if v <= 0:
                return "#2563eb"
            return "#111827"

        alert_html = (
            f'<br><span style="color:#dc2626;font-weight:800;">⚠️ 极端天气预警：'
            f'{t.get("condition", "")}，请注意出行安全！</span>' if is_bad else ""
        )
        big_card(
            f"{t.get('emoji', '')} <strong>{t.get('condition', '')}</strong>　"
            f"<span style='color:{_temp_color(t.get('temp_high'))};font-weight:800;'>"
            f"{t.get('temp_low', '')}°C ~ {t.get('temp_high', '')}°C</span><br>"
            f"降水概率：{t.get('rain_prob', 0)}% ｜ {t.get('wind', '')}<br>"
            f"建议：{t.get('advice', '')}{alert_html}",
            bg="#fef2f2" if is_bad else "#f0f9ff",
            border="#dc2626" if is_bad else "#2563eb",
        )
        if st.button("🔊 播放天气", key="weather_speak", width="stretch"):
            tts_speak(f"今天{t.get('condition', '')}，{t.get('temp_low', '')}到{t.get('temp_high', '')}度，"
                      f"{t.get('advice', '')}。")
    else:
        st.info("天气数据暂时不可用，请稍后再试。")

    # 大字版补充：官方极端天气预警标签 + 数据更新时间（get_simplified_weather，失败不影响主卡片）
    try:
        sim = _cached_simplified_weather((profile or {}).get("community") or "")
        if sim and sim.get("alert_tags"):
            _sim_colors = {"黄色": "#eab308", "橙色": "#f97316", "红色": "#dc2626"}
            tags = "".join(
                f'<span style="display:inline-block;background:{_sim_colors.get(t.get("level",""),"#eab308")};'
                f'color:#ffffff;border-radius:99px;padding:6px 18px;font-size:1.25em;font-weight:800;'
                f'margin:4px 6px 4px 0;">⚠️ {t.get("type","")}{t.get("level","")}预警</span>'
                for t in sim["alert_tags"]
            )
            big_card(f"<div style='text-align:center;'>{tags}</div>", bg="#fef2f2", border="#dc2626")
        if sim and sim.get("updated_at"):
            st.caption(f"天气数据更新于{str(sim.get('updated_at'))[11:16]}")
        # 缓存降级/延迟提示（跨模块联动 #11：老年端同步显示，超 30 分钟降级并语音播报）
        if sim and sim.get("is_degraded"):
            st.warning(f"⚠️ {sim.get('note') or '天气数据可能延迟，当前为缓存数据'}")
            tts_speak("天气数据更新延迟，当前显示的是之前的天气信息。")
    except Exception:
        pass

# ---------------------------------------------------------------- 政策问答（老年端：语音输入+转写确认+自动回答+转人工）
if st.session_state.get("_show_policy"):
    st.markdown("### 🧾 政策问答")
    st.caption("点「🎤 按住说话」问政策，或直接打字")

    # 历史记录（R25：最近 5 条大字版，点详情语音播报，不提供删除）
    try:
        from data.db_core import get_db as _pgdb
        with _pgdb() as _pconn:
            _myqs = _pconn.execute(
                "SELECT summary, status, auto_answer, created_at FROM policy_questions "
                "WHERE user_id=? ORDER BY id DESC LIMIT 5", (uid or 0,)
            ).fetchall()
        if _myqs:
            with st.expander("📋 我的提问（最近 5 条）"):
                for _mq in _myqs:
                    _st = _mq["status"] or ""
                    _mark = "🔴" if _st in ("已转人工", "超时未回复") else "🟢" if _st == "已自动回答" else "🟡"
                    _txt = f"{_mark} {(_mq['summary'] or '')[:24]}（{_st}，{str(_mq['created_at'])[:10]}）"
                    if st.button(_txt, key=f"mq_{_mq['created_at']}", width="stretch"):
                        _ans = (_mq.get("auto_answer") or _st or "")
                        tts_speak(f"您的问题是：{_mq['summary']}。{_ans[:80]}")
    except Exception:
        pass

    # 语音输入（Web Speech，渐进增强）
    try:
        from ui.elderly_components import voice_input
        _spoken = voice_input(key="elderly_policy_voice")
        if _spoken:
            st.session_state["_policy_confirm_text"] = _spoken
            st.session_state.pop("_policy_result", None)
    except Exception:
        pass

    # 转写确认（spec：先显示转写文本，老人点「对，提交」或「重新说」）
    _confirm_text = st.session_state.get("_policy_confirm_text")
    if _confirm_text:
        big_card(f"您说的是：<strong>{_confirm_text}</strong>", bg="#eef2ff", border="#4f46e5")
        c1, c2 = st.columns(2)
        with c1:
            if st.button("✅ 对，就这样问", key="policy_confirm_yes", width="stretch"):
                # R27：说「转人工」→ 先确认再转人工（生成工单），不当问题内容提交
                if "转人工" in (_confirm_text or ""):
                    st.session_state["_policy_human_confirm"] = True
                    st.session_state.pop("_policy_confirm_text", None)
                    st.session_state["_policy_human_q"] = (_confirm_text or "").replace("转人工", "").strip()
                    st.rerun()
                else:
                    st.session_state["_policy_q"] = _confirm_text
                    st.session_state.pop("_policy_confirm_text", None)
                    st.rerun()
        with c2:
            if st.button("🔁 重新说", key="policy_confirm_no", width="stretch"):
                st.session_state.pop("_policy_confirm_text", None)
                st.rerun()

    q = st.text_input("或输入您想问的问题", key="elderly_policy_q",
                      value=st.session_state.get("_policy_q", ""))
    if st.button("🔍 查询", key="policy_search", width="stretch"):
        if q.strip():
            try:
                from data.db_policy import ask_question
                r = ask_question(uid or 0, q.strip(), source="老年端")
                st.session_state["_policy_result"] = r
                st.session_state["_policy_qid"] = r.get("question_id")
            except Exception:
                st.session_state["_policy_result"] = {"matched": False, "reason": "error"}
            st.rerun()

    res = st.session_state.get("_policy_result")
    if res is not None:
        if res.get("matched"):
            ans = res.get("auto_answer") or ""
            short = ans[:200]
            _kb = res.get("knowledge") or {}
            big_card(f"<strong>{_kb.get('title') or '回答'}</strong><br>{short}",
                     bg="#f0fdf4", border="#16a34a")
            tts_speak(f"{_kb.get('title') or ''}。{short}")
            # 转人工（二次确认；语音说「转人工」也走这里）
            if st.button("🙋 转人工", key="policy_to_human", width="stretch"):
                st.session_state["_policy_human_confirm"] = True
            if st.session_state.get("_policy_human_confirm"):
                st.warning("确认转人工？负责人将在 24 小时内回复。")
                if st.button("✅ 确认转人工（负责人24小时内回复）", key="policy_human_yes", width="stretch"):
                    qid = st.session_state.get("_policy_qid")
                    hq = st.session_state.pop("_policy_human_q", "")
                    try:
                        from data.db_policy import transfer_to_human
                        if qid:
                            transfer_to_human(qid)
                        elif hq:
                            transfer_to_human(user_id=uid or 0, question=hq, source="老年端")
                        else:
                            transfer_to_human(user_id=uid or 0, question=q.strip(), source="老年端")
                    except Exception:
                        pass
                    st.success("已转人工，负责人将在24小时内回复您")
                    st.session_state.pop("_policy_result", None)
                    st.session_state.pop("_policy_human_confirm", None)
                    st.rerun()
        else:
            st.info("没有找到答案，可以点下方转人工。")
            tts_speak("没有找到答案，可以点下方转人工。")
            if st.button("🙋 转人工", key="policy_to_human2", width="stretch"):
                try:
                    from data.db_policy import transfer_to_human
                    transfer_to_human(user_id=uid or 0, question=q.strip(), source="老年端")
                except Exception:
                    pass
                st.success("已转人工，负责人将在24小时内回复您")
                st.rerun()

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


@st.fragment(run_every=5)
def _sos_status_area():
    """紧急求助状态区：每 5 秒自动刷新（跨模块联动 #5，状态变化主动更新）。"""
    _uid = uid
    latest_sos = get_latest_sos(_uid) if _uid else None
    _sos_active = bool(latest_sos and latest_sos["status"] in ("求助中", "已响应"))

    if _sos_active:
        # ---- 进行中：拨打状态 / 负责人响应状态 ----
        if latest_sos["status"] == "求助中":
            try:
                escalate_sos(latest_sos["id"])   # 10 分钟未响应自动升级（幂等）
            except Exception:
                pass
            latest_sos = get_latest_sos(_uid) or latest_sos

        if latest_sos["status"] == "求助中":
            if "已升级" in (latest_sos.get("result") or ""):
                big_card(f"🚨 {latest_sos['result']}", bg="#fef2f2", border="#dc2626")
            _render_sos_dialing(_uid, name, latest_sos, approved)
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

        if _is_family_mode:
            # 家属代操作：不能代替老人触发紧急求助（spec 06），可代为拨打联系人电话
            big_card("⚠️ 紧急求助需<strong>老人本人</strong>操作。\n家属可代为拨打上方联系人电话。",
                     bg="#fffbeb", border="#d97706")
        elif st.session_state.get("_sos_confirm"):
            _render_sos_confirm(_uid, name)
        else:
            st.components.v1.html(_LONG_PRESS_JS, height=130)
            if st.button("🆘 紧急求助（点此进入确认，防误触）", key="sos_fallback",
                         type="primary", width="stretch"):
                st.session_state["_sos_confirm"] = True
                st.session_state["_sos_confirm_at"] = time.time()
                st.rerun()


_sos_status_area()
