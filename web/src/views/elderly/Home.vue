<script setup>
// 老年端首页：大字天气(可播放) + 两行三列大按钮 + 用药/通知摘要 + 长按紧急求助 + 联系家属/社区拨打 + 语音帮助
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../../stores/user'
import { elderly, notices } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

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
// 紧急求助（长按 3 秒 → 确认 → 10 秒超时自动取消）
const sosConfirm = ref(false)
let sosTimer = null
let sosCountdown = ref(10)
// 联系家属确认
const callConfirm = ref(false)
let callTimer = null
const callContact = ref(null)
const contacts = ref([])

onMounted(async () => {
  try {
    home.value = await elderly.home()
    // M1：时段问候 + 今日一句关怀 + 语速
    rate.value = home.value?.speech_rate || 0.9
    greetText.value = home.value?.greeting ? `${home.value.greeting}，${home.value.name || '您好'}` : ''
    careLine.value = home.value?.care_line || ''
    if (careLine.value) speak(greetText.value ? `${greetText.value}。${careLine.value}` : careLine.value, vol.value, rate.value)
  } catch { /* 忽略 */ }
  try { contacts.value = (await elderly.contacts()) || [] } catch { /* 忽略 */ }
  // 紧急通知主动弹窗 + 语音（重复两次）
  try {
    const nl = (await notices.list()) || []
    const urgent = nl.find((n) => n.is_urgent && !n.is_read)
    if (urgent) {
      urgentNotice.value = urgent
      const txt = `紧急通知：${urgent.elderly_summary || urgent.title}`
      speak(txt, vol.value, rate.value)
      setTimeout(() => speak(txt, vol.value, rate.value), 3500)
    }
  } catch { /* 忽略 */ }
  if (home.value?.due_medications > 0 && !careLine.value) {
    speak(`今天有 ${home.value.due_medications} 次药要吃，我会到点提醒您。`, vol.value, rate.value)
  }
  if (home.value?.weather?.alert_tags?.length && !careLine.value) {
    const tags = home.value.weather.alert_tags.map((a) => `${a.type}${a.level}`).join('、')
    speak(`注意！当前有极端天气预警：${tags}，请尽量减少外出。`, vol.value, rate.value)
  }
})

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
  if (sosTimer) clearInterval(sosTimer)
  if (callTimer) clearTimeout(callTimer)
})

const rows = [
  [{ icon: '🌤️', label: '天气', action: 'weather' }, { to: '/elderly/notices', icon: '🔊', label: '通知' }, { to: '/elderly/report', icon: '🗣️', label: '报修' }],
  [{ icon: '🏛️', label: '联系社区', action: 'community' }, { to: '/elderly/medication', icon: '💊', label: '用药提醒' }, { icon: '❓', label: '语音帮助', action: 'help' }],
]

function playWeather() {
  const wt = home.value?.weather
  if (!wt) return
  const tags = (wt.alert_tags || []).map((a) => `${a.type}${a.level}预警`).join('，')
  const txt = `当前天气${wt.condition || ''}，气温${wt.temp_low || ''}度到${wt.temp_high || ''}度${tags ? '，' + tags : ''}。${wt.advice || ''}`
  speak(txt, vol.value, rate.value)
}

function voiceHelp() {
  speak('您好，我是社区智能助手。您可以点击天气、通知、报修、联系社区、联系人、用药提醒按钮，也可以长按红色紧急求助按钮联系社区。', vol.value, rate.value)
}

function callCommunity() {
  const phone = home.value?.community_phone || '62319876'
  speak(`正在呼叫社区服务中心，电话 ${phone}`, vol.value, rate.value)
  message.info(`正在呼叫社区服务中心：${phone}`)
  try {
    elderly.contactCall({ target_name: '社区服务中心', target_phone: phone })
  } catch { /* 留痕失败不阻塞 */ }
}

// ---- 紧急求助：长按 3 秒进入确认，10 秒超时自动取消 ----
let pressTimer = null
function pressStart() {
  if (pressTimer) clearTimeout(pressTimer)
  pressTimer = setTimeout(() => {
    sosConfirm.value = true
    sosCountdown.value = 10
    if (sosTimer) clearInterval(sosTimer)
    sosTimer = setInterval(() => {
      sosCountdown.value -= 1
      if (sosCountdown.value <= 0) {
        clearInterval(sosTimer)
        sosConfirm.value = false
        message.info('10 秒未确认，求助已自动取消')
        speak('求助已取消', vol.value, rate.value)
      }
    }, 1000)
  }, 3000)
}
function pressCancel() {
  if (pressTimer) clearTimeout(pressTimer)
  if (!sosConfirm.value && sosTimer) {
    clearInterval(sosTimer)
    sosTimer = null
  }
}

async function confirmSos() {
  clearInterval(sosTimer)
  sosTimer = null
  sosConfirm.value = false
  try {
    const names = contacts.value.filter((c) => c.status === '审核通过').slice(0, 3).map((c) => c.name).join('、')
    await elderly.emergency()
    // 诚实化：H5 无法真实连续拨号，改为「已通知紧急联系人 + 可手动打 120」
    const suffix = names ? `，已通知紧急联系人：${names}` : ''
    speak(`紧急求助已发出${suffix}，需要时请点拨打120`, vol.value, rate.value)
    message.success(`紧急求助已发出${suffix}。手机无法自动连续呼叫，请点下方“拨打120”手动求助。`)
  } catch (e) {
    message.error(e.message || '触发失败')
  }
}

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
  try {
    await elderly.contactCall({ target_name: callContact.value.name, target_phone: callContact.value.phone })
    message.success(`正在呼叫 ${callContact.value.name}（${callContact.value.phone}）`)
    speak(`正在呼叫${callContact.value.name}`, vol.value, rate.value)
  } catch (e) {
    message.error(e.message)
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
      💗 {{ careLine }}
    </div>

    <!-- 音量设置（语音按老人设置音量） -->
    <div style="display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:12px;flex-wrap:wrap;">
      <span style="font-size:1.25rem;">🔊 音量：</span>
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
        <span class="bob" style="display:inline-block;">{{ home.weather.emoji }}</span>
        {{ home.weather.condition }} {{ home.weather.temp_low }}°~{{ home.weather.temp_high }}°
      </div>
      <div v-if="home.weather.alert_tags && home.weather.alert_tags.length" style="margin-top:6px;">
        <n-tag v-for="(a, i) in home.weather.alert_tags" :key="i" size="large" type="error" style="margin:0 4px;">⚠️ {{ a.type }}{{ a.level }}</n-tag>
      </div>
      <div v-if="home.weather.advice" class="muted" style="margin-top:8px;">💬 {{ home.weather.advice }}</div>
      <div class="muted" style="margin-top:4px;">更新于 {{ (home.weather.updated_at || '').slice(11, 16) || home.weather.updated_at }}</div>
      <n-button size="large" type="primary" ghost style="margin-top:10px;min-height:56px;font-size:1.25rem;" @click="playWeather">🔊 播放天气</n-button>
    </div>

    <!-- 用药提醒 -->
    <div v-if="home?.due_medications > 0" class="card panel-lemon"
         style="text-align:center;font-size:1.35rem;font-weight:800;border-radius:18px;">
      💊 您有 {{ home.due_medications }} 条用药提醒
    </div>

    <!-- 未读通知 -->
    <div v-if="home?.unread_notices > 0" class="card entry-tile panel-mint"
         style="text-align:center;font-size:1.25rem;border-radius:18px;"
         @click="router.push('/elderly/notices')">
      🔔 {{ home.unread_notices }} 条新通知
      <n-button size="large" type="success" style="margin-left:8px;">去听 ›</n-button>
    </div>

    <!-- 最近求助状态 -->
    <div v-if="home?.latest_sos" class="card" style="background:#fef2f2;text-align:center;font-size:1.15rem;border-radius:18px;">
      🆘 最近求助：{{ home.latest_sos.status || '处理中' }}
    </div>

    <!-- 语音对话区：社区小助手（语音优先） -->
    <div class="card hero-card" style="padding:0;">
      <div class="grad-flow" style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:linear-gradient(135deg,#166534,#2E7D32);color:#fff;">
        <b style="font-size:1.25rem;">🤖 社区小助手</b>
        <n-button size="small" text style="color:#fff;font-size:1.25rem;" @click="router.push('/elderly/agent')">全页对话 ›</n-button>
      </div>
      <div style="padding:14px;">
        <n-button type="error" block size="large" style="min-height:76px;font-size:1.3rem;font-weight:700;border-radius:18px;"
                  @click="router.push('/elderly/agent')">
          🎤 按住说话，报修 / 查政策 / 问天气
        </n-button>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;justify-content:center;">
          <n-button v-for="(q, i) in ['家里灯不亮了', '医保怎么报销', '今天天气', '我要联系社区']" :key="i" size="large"
                    style="border-radius:14px;min-height:56px;font-size:1.25rem;"
                    @click="router.push('/elderly/agent')">{{ q }}</n-button>
        </div>
      </div>
    </div>

    <!-- 两行三列大按钮（.elderly-grid-3 = minmax(0,1fr)，避免内容顶破容器横向溢出） -->
    <div v-for="(row, ri) in rows" :key="ri" class="wave elderly-grid-3" style="margin:14px 0;">
      <n-badge v-for="b in row" :key="b.label" :value="b.label === '用药提醒' ? home?.due_medications || 0 : 0"
               :show="b.label === '用药提醒' && home?.due_medications > 0" :offset="[-8, 8]">
        <n-button size="large" type="primary" ghost class="elderly-btn"
                  @click="b.action === 'help' ? voiceHelp() : b.action === 'weather' ? playWeather() : b.action === 'community' ? callCommunity() : router.push(b.to)">
          <span style="font-size:2rem;">{{ b.icon }}</span>{{ b.label }}
        </n-button>
      </n-badge>
    </div>

    <!-- 最近联系（留痕记录） -->
    <div v-if="home?.latest_contact" class="muted" style="text-align:center;">
      最近联系：{{ home.latest_contact }}
    </div>

    <!-- 紧急求助（长按 3 秒）——老年端唯一动效：呼吸光圈，让最重要的按钮被看见 -->
    <div style="margin-top:22px;">
      <n-button size="large" type="error" block class="elderly-btn sos-breathe" data-longpress
                style="min-height:92px;font-size:1.7rem;background:linear-gradient(135deg,#DC2626,#B91C1C);border-radius:20px;"
                @mousedown="pressStart" @mouseup="pressCancel" @mouseleave="pressCancel" @touchstart="pressStart" @touchend="pressCancel">
        🆘 紧急求助（长按 3 秒）
      </n-button>
      <div class="muted" style="text-align:center;margin-top:6px;">按住 3 秒后确认呼叫</div>
    </div>

    <!-- 拨打 120 红色大按钮 -->
    <div style="margin-top:14px;">
      <n-button size="large" type="error" block class="elderly-btn"
                style="min-height:76px;font-size:1.45rem;background:linear-gradient(135deg,#B91C1C,#991B1B);border-radius:20px;"
                tag="a" href="tel:120">🚑 拨打 120（急救）</n-button>
    </div>

    <!-- 紧急求助确认弹窗 -->
    <n-modal v-model:show="sosConfirm" preset="dialog" type="error" title="确认紧急求助？"
             :content="`将向已审核的紧急联系人（${contacts.filter(c => c.status === '审核通过').slice(0, 3).map(c => c.name).join('、') || '暂无'}）发送求助提醒，用时请点下方拨打120`"
             positive-text="确认求助" negative-text="取消"
             @positive-click="confirmSos" @negative-click="sosConfirm = false">
      <template #default>
        <div style="text-align:center;font-size:2.1rem;font-weight:800;color:var(--ink-danger);">{{ sosCountdown }} 秒后自动取消</div>
      </template>
    </n-modal>

    <!-- 联系家属确认弹窗 -->
    <n-modal v-model:show="callConfirm" preset="dialog" type="warning" title="确认拨打？"
             :content="callContact ? `将呼叫 ${callContact.name}（${callContact.phone}），10 秒内未确认将取消` : ''"
             positive-text="确认拨打" negative-text="取消"
             @positive-click="confirmCall" @negative-click="cancelCall" />

    <!-- 紧急通知主动弹窗（我知道了） -->
    <n-modal :show="!!urgentNotice" @update:show="(v) => { if (!v) urgentNotice = null }" preset="dialog" type="error"
             :title="urgentNotice ? ('🚨 ' + urgentNotice.title) : ''"
             :content="urgentNotice ? (urgentNotice.elderly_summary || urgentNotice.body) : ''"
             positive-text="我知道了" @positive-click="closeUrgent" />
  </div>
</template>
