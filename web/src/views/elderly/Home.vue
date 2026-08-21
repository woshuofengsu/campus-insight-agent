<script setup>
// 老年端首页：大字天气(可播放) + 两行三列大按钮 + 用药/通知摘要 + 长按紧急求助 + 联系家属/社区拨打 + 语音帮助
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../../stores/user'
import { elderly } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

const router = useRouter()
const store = useUserStore()
const message = useMessage()
const { speak } = useSpeech()

const home = ref(null)
const vol = ref(1.0)
const volLabels = { 低: 0.5, 中: 1.0, 高: 1.5 }
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
  try { home.value = await elderly.home() } catch { /* 忽略 */ }
  try { contacts.value = (await elderly.contacts()) || [] } catch { /* 忽略 */ }
  if (home.value?.due_medications > 0) {
    speak(`您有 ${home.value.due_medications} 条用药提醒，请注意。`, vol.value)
  }
  if (home.value?.weather?.alert_tags?.length) {
    const tags = home.value.weather.alert_tags.map((a) => `${a.type}${a.level}`).join('、')
    speak(`注意！当前有极端天气预警：${tags}，请尽量减少外出。`, vol.value)
  }
})

onBeforeUnmount(() => {
  if (sosTimer) clearInterval(sosTimer)
  if (callTimer) clearTimeout(callTimer)
})

const rows = [
  [{ icon: '🌤️', label: '天气', action: 'weather' }, { to: '/elderly/notices', icon: '🔊', label: '通知' }, { to: '/elderly/report', icon: '🗣️', label: '报修' }],
  [{ to: '/elderly/qa', icon: '📖', label: '政策问答' }, { to: '/elderly/contacts', icon: '👨‍👩‍👧', label: '联系人' }, { icon: '❓', label: '语音帮助', action: 'help' }],
]

function playWeather() {
  const wt = home.value?.weather
  if (!wt) return
  const tags = (wt.alert_tags || []).map((a) => `${a.type}${a.level}预警`).join('，')
  const txt = `当前天气${wt.condition || ''}，气温${wt.temp_low || ''}度到${wt.temp_high || ''}度${tags ? '，' + tags : ''}。${wt.advice || ''}`
  speak(txt, vol.value)
}

function voiceHelp() {
  speak('您好，我是社区智能助手。您可以点击报修、通知、用药、政策问答按钮，也可以长按红色紧急求助按钮联系社区。', vol.value)
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
        speak('求助已取消', vol.value)
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
    const names = contacts.value.filter((c) => c.status === '已通过').slice(0, 3).map((c) => c.name).join('、')
    await elderly.emergency()
    speak(`紧急求助已发出${names ? `，将依次呼叫 ${names}` : ''}`, vol.value)
    message.success(`紧急求助已发出${names ? `，将依次呼叫：${names}` : ''}`)
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
    speak(`正在呼叫${callContact.value.name}`, vol.value)
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
    <div class="elderly-title">你好，{{ home?.name || '大爷/阿姨' }}</div>

    <!-- 音量设置（语音按老人设置音量） -->
    <div style="display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:10px;">
      <span style="font-size:1.1rem;">🔊 音量：</span>
      <n-button-group size="large">
        <n-button v-for="(v, k) in volLabels" :key="k" :type="vol === v ? 'primary' : 'default'" @click="vol = v; speak('音量已设置', v)">{{ k }}</n-button>
      </n-button-group>
    </div>

    <!-- 大字天气（可播放） -->
    <div v-if="home?.weather" class="card" style="text-align:center;background:#f0f9ff;font-size:1.3rem;">
      <div style="font-size:1.6rem;font-weight:700;">{{ home.weather.emoji }} {{ home.weather.condition }} {{ home.weather.temp_low }}°~{{ home.weather.temp_high }}°</div>
      <div v-if="home.weather.alert_tags && home.weather.alert_tags.length" style="margin-top:4px;">
        <n-tag v-for="(a, i) in home.weather.alert_tags" :key="i" size="large" type="error" style="margin:0 4px;">⚠️ {{ a.type }}{{ a.level }}</n-tag>
      </div>
      <div v-if="home.weather.advice" class="muted" style="margin-top:6px;font-size:1rem;">💬 {{ home.weather.advice }}</div>
      <div class="muted" style="font-size:0.85rem;margin-top:4px;">更新于 {{ (home.weather.updated_at || '').slice(11, 16) || home.weather.updated_at }}</div>
      <n-button size="large" type="primary" ghost style="margin-top:8px;" @click="playWeather">🔊 播放天气</n-button>
    </div>

    <!-- 用药提醒 -->
    <div v-if="home?.due_medications > 0" class="card" style="background:#fefce8;text-align:center;font-size:1.3rem;font-weight:700;">
      💊 您有 {{ home.due_medications }} 条用药提醒
    </div>

    <!-- 未读通知 -->
    <div v-if="home?.unread_notices > 0" class="card" style="background:#f0fdf4;text-align:center;font-size:1.2rem;">
      🔔 {{ home.unread_notices }} 条新通知
      <n-button size="large" type="success" @click="router.push('/elderly/notices')">去听</n-button>
    </div>

    <!-- 最近求助状态 -->
    <div v-if="home?.latest_sos" class="card" style="background:#fef2f2;text-align:center;">
      🆘 最近求助：{{ home.latest_sos.status || '处理中' }}
    </div>

    <!-- 两行三列大按钮 -->
    <div v-for="(row, ri) in rows" :key="ri" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0;">
      <n-button v-for="b in row" :key="b.label" size="large" type="primary" ghost class="elderly-btn"
                @click="b.action === 'help' ? voiceHelp() : b.action === 'weather' ? playWeather() : router.push(b.to)">
        <span style="font-size:2rem;">{{ b.icon }}</span>{{ b.label }}
      </n-button>
    </div>

    <!-- 最近联系（留痕记录） -->
    <div v-if="home?.latest_contact" class="muted" style="text-align:center;font-size:0.95rem;">
      最近联系：{{ home.latest_contact }}
    </div>

    <!-- 紧急求助（长按 3 秒） -->
    <div style="margin-top:20px;">
      <n-button size="large" type="error" block class="elderly-btn" style="min-height:84px;font-size:1.6rem;background:#dc2626;"
                @mousedown="pressStart" @mouseup="pressCancel" @mouseleave="pressCancel" @touchstart="pressStart" @touchend="pressCancel">
        🆘 紧急求助（长按 3 秒）
      </n-button>
      <div class="muted" style="text-align:center;font-size:0.9rem;margin-top:4px;">按住 3 秒后确认呼叫</div>
    </div>

    <!-- 拨打 120 红色大按钮 -->
    <div style="margin-top:12px;">
      <n-button size="large" type="error" block class="elderly-btn" style="min-height:70px;font-size:1.4rem;background:#b91c1c;"
                tag="a" href="tel:120">🚑 拨打 120（急救）</n-button>
    </div>

    <!-- 紧急求助确认弹窗 -->
    <n-modal v-model:show="sosConfirm" preset="dialog" type="error" title="确认紧急求助？"
             :content="`将依次呼叫：${contacts.filter(c => c.status === '已通过').slice(0, 3).map(c => c.name).join('、') || '暂无紧急联系人'}`"
             positive-text="确认求助" negative-text="取消"
             @positive-click="confirmSos" @negative-click="sosConfirm = false">
      <template #default>
        <div style="text-align:center;font-size:2rem;font-weight:800;color:#dc2626;">{{ sosCountdown }} 秒后自动取消</div>
      </template>
    </n-modal>

    <!-- 联系家属确认弹窗 -->
    <n-modal v-model:show="callConfirm" preset="dialog" type="warning" title="确认拨打？"
             :content="callContact ? `将呼叫 ${callContact.name}（${callContact.phone}），10 秒内未确认将取消` : ''"
             positive-text="确认拨打" negative-text="取消"
             @positive-click="confirmCall" @negative-click="cancelCall" />
  </div>
</template>
