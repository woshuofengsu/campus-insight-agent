<script setup>
// 老年端首页：大字天气(可播放) + 今日提醒 + 通知/用药摘要 + 长按紧急求助 + 拨打 120 + 小助手入口
//
// v3 复核 B4（导航收敛）：首页原来又摆了一套"天气/通知/报修/联系社区/用药/健康"入口，
// 和顶部导航重复 —— 老人"每个都在、等于每个都找不到"。现在首页只保留**首页特有**的内容
// （问候/关怀/天气/今日提醒/紧急求助/120/小助手），高频入口统一由顶部导航承担，
// 其余能力收进「更多服务」。**功能一个没少，只是入口不再重复。**
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../../stores/user'
import { elderly, notices } from '../../api'
import { useSpeech, speechCapability } from '../../composables/useSpeech'
import { useSos } from '../../composables/useSos'
import EIcon from '../../components/EIcon.vue'
import { weatherIcon } from '../../utils/weatherIcon'

const router = useRouter()
const store = useUserStore()
const message = useMessage()
const { speak } = useSpeech()

const home = ref(null)
const vol = ref(1.0)
const rate = ref(0.9) // M1 语速（老人档慢一点）
const volLabels = { 低: 0.5, 中: 1.0, 高: 1.5 }
const greetText = ref('')
const careLine = ref('')
const urgentNotice = ref(null)
// 联系家属确认
const callConfirm = ref(false)
let callTimer = null
const callContact = ref(null)
const contacts = ref([])
// 降级硬化（B4）：语音是增强项，不是唯一路径
const cap = speechCapability()
const ttsOk = ref(cap.hasTTS)
const welcomeText = ref('')        // 首屏要念的话（改由"点一下听"触发）
const urgentText = ref('')         // 紧急通知要念的话

onMounted(async () => {
  try {
    home.value = await elderly.home()
    // M1：时段问候 + 今日一句关怀 + 语速
    rate.value = home.value?.speech_rate || 0.9
    greetText.value = home.value?.greeting ? `${home.value.greeting}，${home.value.name || '您好'}` : ''
    careLine.value = home.value?.care_line || ''
    // 降级硬化（B4）：**不再挂载即播报**——iOS Safari 的 TTS 必须由用户手势触发，
    // 自动播会静默不响（老人以为坏了）。改成页面上一句大字 + 一个"点一下听"按钮。
    welcomeText.value = careLine.value
      ? (greetText.value ? `${greetText.value}。${careLine.value}` : careLine.value)
      : ''
  } catch { /* 忽略 */ }
  try { contacts.value = (await elderly.contacts()) || [] } catch { /* 忽略 */ }
  // 紧急通知：仍然弹窗（必须让老人看见），但播报改为**用户点一下**（同上，自动播在 iOS 不响）
  try {
    const nl = (await notices.list()) || []
    const urgent = nl.find((n) => n.is_urgent && !n.is_read)
    if (urgent) {
      urgentNotice.value = urgent
      urgentText.value = `紧急通知：${urgent.elderly_summary || urgent.title}`
    }
  } catch { /* 忽略 */ }
  if (home.value?.due_medications > 0 && !careLine.value) {
    welcomeText.value = `今天有 ${home.value.due_medications} 次药要吃，我会到点提醒您。`
  }
  if (home.value?.weather?.alert_tags?.length && !careLine.value) {
    const tags = home.value.weather.alert_tags.map((a) => `${a.type}${a.level}`).join('、')
    welcomeText.value = `注意！当前有极端天气预警：${tags}，请尽量减少外出。`
  }
})

/** 点一下听（用户手势触发，iOS 才会真的响）；播不出来就说明原因并保留大字。 */
async function playWelcome() {
  const ok = await speak(welcomeText.value || greetText.value, vol.value, rate.value)
  if (!ok) ttsOk.value = false
}

async function playUrgent() {
  const ok = await speak(urgentText.value, vol.value, rate.value)
  if (!ok) ttsOk.value = false
}

async function closeUrgent() {
  const n = urgentNotice.value
  urgentNotice.value = null
  if (n && !n.is_read) {
    try {
      await notices.action(n.id, { action: 'mark_read' })
    } catch { /* 忽略 */ }
  }
}

onBeforeUnmount(() => {
  if (callTimer) clearTimeout(callTimer)
})

// 首页保留的"首页特有"快捷入口（高频的报修/进度/联系人/通知已由顶部导航承担，不再重复）
const quick = [
  { to: '/elderly/report', icon: 'speak', label: '反映问题' },
  { to: '/elderly/orders', icon: 'clipboard', label: '看看进度' },
  { to: '/elderly/more', icon: 'toolbox', label: '更多服务' },
]

function playWeather() {
  const wt = home.value?.weather
  if (!wt) return
  const tags = (wt.alert_tags || []).map((a) => `${a.type}${a.level}预警`).join('，')
  const txt = `这里是${wt.region_label || '您所在社区'}的天气。当前${wt.condition || ''}，气温${wt.temp_low || ''}度到${wt.temp_high || ''}度${tags ? '，' + tags : ''}。${wt.advice || ''}`
  speak(txt, vol.value, rate.value)
}

function voiceHelp() {
  speak('您好，我是社区智能助手。最上面有首页、反映问题、看看进度、联系家人、今日提醒、更多服务；红色的紧急求助按钮长按三秒就能找社区。', vol.value, rate.value)
}

function callCommunity() {
  const phone = home.value?.community_phone || ''
  if (!phone) {
    message.warning('暂无社区电话，请联系网格员补充')
    return
  }
  // 诚实呼叫（§6-B2）：号码由**服务端**给出并留痕，页面只说"帮您打开拨号"，
  // 绝不说"正在呼叫"（网页根本不知道有没有拨出去、接通没有）
  try {
    elderly.contactCall({ community: true }).then((info) => {
      window.location.href = (info && info.tel) || `tel:${phone}`
      message.info('已帮您打开手机拨号，请在手机上按绿色按钮拨出')
      speak('已帮您打开手机拨号，请在手机上拨出', vol.value, rate.value)
      if (info && info.call_id) elderly.contactOutcome(info.call_id, 'dialer_opened').catch(() => {})
    }).catch((e) => message.error(e.message || '打开拨号失败'))
  } catch {
    window.location.href = `tel:${phone}`
  }
}

// ---- 紧急求助：长按 3 秒进入确认，10 秒超时自动取消 ----
// v3 复核 B4：逻辑抽到 `composables/useSos.js`，与顶部导航的红色求助键**共用同一套状态机**
const sos = useSos({ onMessage: message, speakOpts: () => [vol.value, rate.value] })
const sosConfirm = sos.sosConfirm
const sosCountdown = sos.sosCountdown
const pressStart = sos.pressStart
const pressCancel = sos.pressCancel
const confirmSos = sos.confirmSos

// ---- 联系家属/社区：确认 → 拨号留痕，10 秒超时 ----
async function callPerson(c) {
  callContact.value = c
  callConfirm.value = true
  if (callTimer) clearTimeout(callTimer)
  callTimer = setTimeout(() => {
    callConfirm.value = false
    message.info('10 秒未确认，拨打已取消')
  }, 10000)
}

async function confirmCall() {
  clearTimeout(callTimer)
  callConfirm.value = false
  const c = callContact.value
  if (!c) return
  try {
    // 只传 contact_id：姓名/号码由服务端解析（§6-I8）
    const info = await elderly.contactCall({ contact_id: c.id })
    const phone = (info && info.phone) || c.phone
    window.location.href = (info && info.tel) || `tel:${phone}`
    // 只承诺"已打开拨号盘"——接通与否网页无从得知（§6-B2）
    message.info(`已帮您打开手机拨号，请在手机上按绿色按钮拨给 ${info?.name || c.name}`)
    speak(`已帮您打开手机拨号，请拨给${info?.name || c.name}`, vol.value, rate.value)
    if (info && info.call_id) {
      elderly.contactOutcome(info.call_id, 'dialer_opened').catch(() => {})
    }
  } catch (e) {
    message.error(e.message || '打开拨号失败')
  }
}

function cancelCall() {
  clearTimeout(callTimer)
  callConfirm.value = false
}
</script>

<template>
  <div class="elderly-page">
    <!-- 时段问候 + 今日关怀（暖色，唯一保留的淡入动效） -->
    <div class="elderly-title">{{ greetText || ('你好，' + (home?.name || '大爷/阿姨')) }}</div>
    <div v-if="careLine" class="card panel-warm fade-up"
         style="text-align:center;font-size:1.3rem;font-weight:600;margin-bottom:12px;border-radius:18px;">
      <EIcon name="heart" :size="18" /> {{ careLine }}
    </div>

    <!-- 语音不可用时的降级说明（审计靠 data-speech-fallback 验证"关掉语音仍可用"） -->
    <div v-if="!ttsOk" data-speech-fallback
         class="card panel-warm" style="border-radius:14px;font-size:1.3rem;margin-bottom:12px;">
      <EIcon name="speaker-off" :size="18" /> 这台手机不能自动念出来，页面上的字都放大了，点按钮一样能办事
    </div>

    <!-- 首屏问候/提醒：**改成点一下听**（iOS Safari 的 TTS 必须由用户手势触发，自动播会静默不响） -->
    <div v-if="welcomeText && ttsOk" style="margin-bottom:12px;">
      <n-button type="primary" block size="large" style="min-height:72px;font-size:1.35rem;border-radius:18px;"
                @click="playWelcome"><EIcon name="speaker" :size="18" /> 点一下听今天的提醒</n-button>
    </div>

    <!-- 音量设置（语音按老人设置音量） -->
    <div style="display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:12px;flex-wrap:wrap;">
      <span style="font-size:1.25rem;"><EIcon name="speaker" :size="18" /> 音量：</span>
      <n-button-group size="large">
        <n-button v-for="(v, k) in volLabels" :key="k" :type="vol === v ? 'primary' : 'default'"
                  style="font-size:1.25rem;min-height:56px;min-width:76px;" @click="vol = v; speak('音量已设置', v, rate)">{{ k }}</n-button>
      </n-button-group>
    </div>

    <!-- 大字天气（可播放） -->
    <div v-if="home?.weather" class="card panel-sky fade-up-d1"
         style="text-align:center;font-size:1.3rem;border-radius:20px;">
      <!-- P3 修复：原先写死内联 color:#075985，暗色下面板变深(#10202E)而这行深蓝字不变 →
           实测对比 2.3:1 看不清。改用 .panel-hi（带暗色变体） -->
      <div class="panel-hi" style="font-size:1.7rem;font-weight:800;">
        <span class="bob" style="display:inline-flex;vertical-align:-0.2em;"><EIcon :name="weatherIcon(home.weather.condition, home.weather.emoji)" :size="40" weight="1.8" /></span>
        {{ home.weather.condition }} {{ home.weather.temp_low }}°~{{ home.weather.temp_high }}°
      </div>
      <div v-if="home.weather.alert_tags && home.weather.alert_tags.length" style="margin-top:6px;">
        <n-tag v-for="(a, i) in home.weather.alert_tags" :key="i" size="large" type="error" style="margin:0 4px;"><EIcon name="alert" :size="18" /> {{ a.type }}{{ a.level }}</n-tag>
      </div>
      <div v-if="home.weather.advice" class="muted" style="margin-top:8px;"><EIcon name="chat-dots" :size="18" /> {{ home.weather.advice }}</div>
      <!-- 属地（地区识别 WS7）：老年端与居民端口径一致（都来自账号所属社区，不用定位权限）
           注意：字号必须 ≥20px（`mobile_audit` 对老年端卡 20px 下限，1.15rem=18.4px 会被判不合格） -->
      <div v-if="home.weather.region_label" class="muted" style="margin-top:6px;font-size:1.3rem;">
        <EIcon name="pin" :size="18" /> {{ home.weather.region_label }}
      </div>
      <div class="muted" style="margin-top:4px;">更新于 {{ (home.weather.updated_at || '').slice(11, 16) || home.weather.updated_at }}</div>
      <n-button size="large" type="primary" ghost style="margin-top:10px;min-height:56px;font-size:1.25rem;" @click="playWeather"><EIcon name="speaker" :size="18" /> 播放天气</n-button>
    </div>

    <!-- 用药提醒 -->
    <div v-if="home?.due_medications > 0" class="card panel-lemon"
         style="text-align:center;font-size:1.35rem;font-weight:800;border-radius:18px;">
      <EIcon name="pill" :size="18" /> 您有 {{ home.due_medications }} 条用药提醒
    </div>

    <!-- 未读通知 -->
    <div v-if="home?.unread_notices > 0" class="card entry-tile panel-mint"
         style="text-align:center;font-size:1.25rem;border-radius:18px;"
         @click="router.push('/elderly/notices')">
      <EIcon name="bell" :size="18" /> {{ home.unread_notices }} 条新通知
      <!-- 老年端可达性：老年端文字一律 ≥20px（这里是 1.25rem 的 15px 默认字号），
           按钮高度也提到 52px 以上——长辈版不该出现"小字小按钮"。 -->
      <n-button size="large" type="success" style="margin-left:8px;font-size:1.2rem;min-height:52px;">去听 ›</n-button>
    </div>

    <!-- 最近求助状态 -->
    <div v-if="home?.latest_sos" class="card" style="background:#fef2f2;text-align:center;border-radius:18px;">
      <EIcon name="siren" :size="18" /> 最近求助：{{ home.latest_sos.status || '处理中' }}
    </div>

    <!-- 语音对话区：社区小助手（语音优先） -->
    <div class="card hero-card" style="padding:0;">
      <div class="grad-flow" style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:linear-gradient(135deg,#166534,#2E7D32);color:#fff;">
        <b style="font-size:1.25rem;"><EIcon name="robot" :size="18" /> 社区小助手</b>
        <n-button size="large" text style="color:#fff;font-size:1.25rem;min-height:52px;" @click="router.push('/elderly/agent')">全页对话 ›</n-button>
      </div>
      <div style="padding:14px;">
        <n-button type="error" block size="large" style="min-height:76px;font-size:1.3rem;font-weight:700;border-radius:18px;"
                  @click="router.push('/elderly/agent')">
          <EIcon name="mic" :size="18" /> 点这里说话：报修 / 查政策 / 问天气
        </n-button>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;justify-content:center;">
          <n-button v-for="(q, i) in ['家里灯不亮了', '医保怎么报销', '今天天气', '我要联系社区']" :key="i" size="large"
                    style="border-radius:14px;min-height:56px;font-size:1.25rem;"
                    @click="router.push('/elderly/agent')">{{ q }}</n-button>
        </div>
      </div>
    </div>

    <!-- 首页特有入口（高频的报修/进度/联系人/通知已由**顶部导航**承担，这里不重复摆放） -->
    <div class="elderly-grid-3" style="margin:14px 0;">
      <n-button v-for="q in quick" :key="q.to" size="large" type="primary" ghost class="elderly-btn"
                @click="router.push(q.to)">
        <EIcon :name="q.icon" :size="30" />{{ q.label }}
      </n-button>
    </div>

    <!-- 最近联系（留痕记录） -->
    <div v-if="home?.latest_contact" class="muted" style="text-align:center;">
      最近联系：{{ home.latest_contact }}
    </div>

    <!-- 紧急求助（长按 3 秒）——老年端唯一动效：呼吸光圈，让最重要的按钮被看见
         v3 复核 B4：与顶部导航的红色求助键共用 `composables/useSos.js` 的同一套状态机 -->
    <div style="margin-top:22px;">
      <n-button size="large" type="error" block class="elderly-btn sos-breathe" data-longpress
                style="min-height:92px;font-size:1.7rem;background:linear-gradient(135deg,#DC2626,#B91C1C);border-radius:20px;"
                @pointerdown="pressStart" @pointerup="pressCancel" @pointerleave="pressCancel"
                @touchstart.prevent="pressStart" @touchend="pressCancel">
        <EIcon name="siren" :size="18" /> 紧急求助（长按 3 秒）
      </n-button>
      <div class="muted" style="text-align:center;margin-top:6px;">按住 3 秒后确认呼叫</div>
    </div>

    <!-- 拨打 120 红色大按钮 -->
    <div style="margin-top:14px;">
      <n-button size="large" type="error" block class="elderly-btn"
                style="min-height:76px;font-size:1.45rem;background:linear-gradient(135deg,#B91C1C,#991B1B);border-radius:20px;"
                tag="a" href="tel:120"><EIcon name="siren" :size="18" /> 拨打 120（急救）</n-button>
    </div>

    <!-- 紧急求助确认弹窗 -->
    <n-modal v-model:show="sosConfirm" preset="dialog" type="error" title="确认紧急求助？"
             positive-text="确认求助" negative-text="取消"
             @positive-click="confirmSos" @negative-click="sos.cancelConfirm">
      <template #default>
        <div style="text-align:center;font-size:1.3rem;">
          将通知社区负责人{{ sos.contactNames.value ? `，以及紧急联系人：${sos.contactNames.value}` : '' }}。
        </div>
        <div style="text-align:center;font-size:2.1rem;font-weight:800;color:var(--ink-danger);margin-top:8px;">{{ sosCountdown }} 秒后自动取消</div>
        <div class="muted" style="text-align:center;margin-top:8px;font-size:1.1rem;">
          手机不能自动连续拨号，需要时请点下面的「拨打 120」
        </div>
      </template>
    </n-modal>

    <!-- 联系家属确认弹窗 -->
    <n-modal v-model:show="callConfirm" preset="dialog" type="warning" title="确认拨打？"
             :content="callContact ? `将呼叫 ${callContact.name}（${callContact.phone}），10 秒内未确认将取消` : ''"
             positive-text="确认拨打" negative-text="取消"
             @positive-click="confirmCall" @negative-click="cancelCall" />

    <!-- 紧急通知主动弹窗（我知道了 + 点一下听；不再自动播报，iOS 需要用户手势） -->
    <n-modal :show="!!urgentNotice" @update:show="(v) => { if (!v) urgentNotice = null }" preset="dialog" type="error"
             :title="urgentNotice ? ('' + urgentNotice.title) : ''"
             :content="urgentNotice ? (urgentNotice.elderly_summary || urgentNotice.body) : ''"
             positive-text="我知道了" @positive-click="closeUrgent">
      <template #action>
        <n-button v-if="ttsOk" type="error" size="large" style="min-height:64px;font-size:1.3rem;"
                  @click="playUrgent"><EIcon name="speaker" :size="18" /> 点一下听</n-button>
        <n-button size="large" style="min-height:64px;font-size:1.3rem;" @click="closeUrgent">我知道了</n-button>
      </template>
    </n-modal>
  </div>
</template>
