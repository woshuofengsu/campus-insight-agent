<script setup>
// 老年端 Agent 语音对话区：按住说话（60秒）→ 转写确认（对，提交/重新说）→ 大字回复 + 语音播报（可再听一次）
// 降级硬化（B4）：降级文案统一走 `reasonText`（原来这页自己写了一份，其余页各写各的），
// 并在挂载时就用 `speechCapability()` 把"这台机器不能语音"提前说清楚。
import { ref, onMounted, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { agent } from '../../api'
import { useSpeech, speechCapability, reasonText } from '../../composables/useSpeech'
import EIcon from '../../components/EIcon.vue'

const message = useMessage()
const { recognize, speak, stopListening } = useSpeech()

const msgs = ref([])
const listening = ref(false)
const remain = ref(60)
const pendingText = ref(null) // 转写待确认
const input = ref('')
const inputEl = ref(null) // 文字输入框，语音降级时聚焦
const busy = ref(false)
let timer = null

const cap = speechCapability()
const asrBlocked = ref(!cap.hasASR || !cap.secure)
const blockReason = ref(cap.asrReason || '')
const banner = computed(() => reasonText(blockReason.value || 'unsupported'))
// 播报是否真的响过：失败就把 降级成"请看大字"，**不假装老人听到了**（v3 复核 B3）
const ttsOk = ref(cap.hasTTS)
const lastSpoken = ref('')

/** 统一播报入口：接住 speak() 的返回值，失败时页面会显示降级说明。 */
async function say(text) {
  const t = (text || '').trim()
  if (!t) return false
  lastSpoken.value = t
  const ok = await speak(t, 1.0, 0.9)
  if (!ok) ttsOk.value = false
  return ok
}

const QUICK = ['家里灯不亮了', '医保怎么报销', '今天天气', '我要联系社区']

onMounted(() => {
  msgs.value.push({
    bot: true,
    text: '您好，我是社区小助手！按住下方话筒告诉我您要办的事，比如报修、查政策、看天气。',
  })
})

async function startListen() {
  if (asrBlocked.value) {          // 已知不可用：直接聚焦打字框，不空转
    inputEl.value?.focus()
    return
  }
  listening.value = true
  remain.value = 60
  timer = setInterval(() => { remain.value -= 1; if (remain.value <= 0) stopListen() }, 1000)
  const r = await recognize()
  clearInterval(timer)
  listening.value = false
  if (r.ok && r.text) {
    pendingText.value = r.text
    say(`您说的是：${r.text}，对吗？说“对”确认，或点“重新说”。`)
  } else {
    const reason = r.reason || 'empty'
    const msg = reasonText(reason)
    message.warning(msg)
    say(msg)
    // 语音不可用/没权限 → 明确降级：显示提示条 + 聚焦文字输入框（不静默）
    if (reason !== 'empty' && reason !== 'done') {
      asrBlocked.value = true
      blockReason.value = reason
    }
    inputEl.value?.focus()
  }
}

function stopListen() {
  clearInterval(timer)
  listening.value = false
  // 注意（2026-10-06 修）：原来只改标志位 —— 按钮写着"松开结束"，但**麦克风仍在收音**，
  // 录音指示不灭、转写稍后突然弹出；再按一次还会起第二个识别会话（可能被判成"不支持语音"）。
  // 必须真的停掉识别（`useSpeech` 的 stopListening 会 abort 当前会话）。
  try { stopListening() } catch { /* 组件不支持时忽略（按钮文案已随之降级） */ }
}

function confirmText() {
  if (!pendingText.value) return
  input.value = pendingText.value
  pendingText.value = null
  say('好的，正在为您处理')
  send()
}

function retryText() {
  pendingText.value = null
  say('好的，请重新说一次')
}

async function send(text) {
  const t = (text ?? input.value ?? '').trim()
  if (!t || busy.value) return
  input.value = ''
  msgs.value.push({ bot: false, text: t })
  busy.value = true
  try {
    const r = await agent.elderlyChat({ text: t })
    const reply = r.reply
    msgs.value.push({ bot: true, text: reply, intent: r.intent, actions: r.actions || [], status: r.status })
    // 播报：接住返回值，失败就在页面上说明（v3 复核 B3：不能假装老人听到了）
    await say((reply || '').slice(0, 200))
  } catch (e) {
    msgs.value.push({ bot: true, text: e.message || '服务暂时不可用', error: true })
  } finally {
    busy.value = false
  }
}

function replay(m) {
  say((m.text || '').slice(0, 200))
}

function sendOption(o) {
  send(o)
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title"><EIcon name="robot" :size="18" /> 社区小助手</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">按住说话，或直接打字问我</p>

    <!-- 降级提示条：这台机器不能语音时提前说清（审计靠 data-speech-fallback 验证） -->
    <div v-if="asrBlocked" data-speech-fallback
         class="card panel-warm" style="border-radius:14px;font-size:1.3rem;margin:8px 0;">
      <EIcon name="speaker-off" :size="18" /> {{ banner }}
    </div>
    <!-- 播报失败必须可见（v3 复核 B3）：不能假装老人听到了 -->
    <div v-if="lastSpoken && !ttsOk" class="card muted" style="font-size:1.15rem;margin:8px 0;">
      <EIcon name="speaker-off" :size="18" /> 这台手机的语音念不出来，请看屏幕上的大字（内容是一样的）
    </div>
    <n-button v-else-if="lastSpoken" block size="large" style="margin:8px 0;min-height:56px;font-size:1.25rem;"
              @click="say(lastSpoken)"><EIcon name="speaker" :size="18" /> 再听一遍</n-button>

    <!-- 语音按钮（至少 80px 高） -->
    <div style="margin:8px 0;">
      <n-button v-if="!asrBlocked" type="error" block size="large" style="min-height:80px;font-size:1.4rem;" :loading="listening" @mousedown="startListen" @mouseup="stopListen" @touchstart="startListen" @touchend="stopListen">
        <EIcon name="mic" :size="18" /> {{ listening ? `正在聆听…（${remain} 秒）` : '按住说话（最多 60 秒）' }}
      </n-button>
      <div v-else style="font-size:1.3rem;font-weight:700;text-align:center;">
        <EIcon name="edit" :size="18" /> 在下面的框里打字问我，一样能办事
      </div>
    </div>

    <!-- 转写确认（对，提交 / 重新说） -->
    <div v-if="pendingText" class="card" style="background:#fefce8;font-size:1.25rem;">
      <div>您说的是：<b>{{ pendingText }}</b></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;">
        <n-button type="success" size="large" style="min-height:56px;" @click="confirmText"><EIcon name="checkCircle" :size="18" /> 对，提交</n-button>
        <n-button size="large" style="min-height:56px;" @click="retryText"><EIcon name="refresh" :size="18" /> 重新说</n-button>
      </div>
    </div>

    <!-- 快捷问题 -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;justify-content:center;">
      <n-button v-for="(q, i) in QUICK" :key="i" size="large" style="font-size:1.25rem;min-height:56px;" @click="sendOption(q)">{{ q }}</n-button>
    </div>

    <!-- 对话区（大字回复） -->
    <div class="card" style="min-height:220px;max-height:420px;overflow-y:auto;font-size:1.25rem;">
      <div v-for="(m, i) in msgs" :key="i" style="margin-bottom:12px;">
        <div v-if="!m.bot" style="text-align:right;">
          <div style="display:inline-block;background:#2E7D32;color:#fff;border-radius:12px;padding:10px 14px;max-width:85%;"><EIcon name="speak" :size="18" /> {{ m.text }}</div>
        </div>
        <div v-else>
          <div style="display:inline-block;background:var(--card-bg);border:1px solid var(--border);border-radius:12px;padding:10px 14px;max-width:90%;white-space:pre-wrap;"
               :style="m.error ? 'color:var(--ink-danger);' : ''">
            <EIcon name="robot" :size="18" /> {{ m.text }}
            <div v-if="m.intent" style="margin-top:6px;"><n-tag size="small" type="info">{{ m.intent }}</n-tag></div>
            <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
              <n-button v-for="(a, ai) in (m.actions || [])" :key="ai" size="large" type="primary"
                        @click="a.type === 'navigate' && $router.push(a.to)">{{ a.label }}</n-button>
              <n-button size="large" style="font-size:1.25rem;min-height:56px;" @click="replay(m)"><EIcon name="speaker" :size="18" /> 再听一次</n-button>
            </div>
          </div>
        </div>
      </div>
      <div v-if="busy" style="color:var(--muted);"><EIcon name="robot" :size="18" /> 正在思考…</div>
    </div>

    <!-- 文字输入 -->
    <div style="display:flex;gap:8px;margin-top:10px;">
      <n-input ref="inputEl" v-model:value="input" type="textarea" :rows="2" placeholder="或直接打字告诉我（最多 200 字）" maxlength="200"
               style="font-size:1.25rem;" @keyup.enter="send()" />
      <n-button type="primary" size="large" style="min-height:56px;font-size:1.25rem;" :loading="busy" @click="send()">发送</n-button>
    </div>

    <!-- 去首页找"紧急求助"（**不是** SOS 按钮本身）
         注意（2026-10-06 修）：这里原来是一个深红大按钮写着"紧急求助（长按 3 秒）"、配 siren 图标，
         但只绑了 `@click` —— **长按没有任何反应**（老人以为在求救，实际只是回首页），
         而同屏顶部还有一枚真的 SOS，两者同色同图标、极易混淆。
         按"要么接真机状态机、要么不冒充 SOS"的原则：这里**降级为普通导航入口**，
         去掉红色与 siren（SOS 只保留首页那一处真的好用的长按）。 -->
    <div style="margin-top:16px;">
      <n-button block size="large" style="min-height:70px;font-size:1.4rem;"
                @click="$router.push('/elderly/home')"><EIcon name="home" :size="22" /> 回首页（紧急求助在首页长按）</n-button>
    </div>
  </div>
</template>
