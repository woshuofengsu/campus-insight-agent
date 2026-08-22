<script setup>
// 老年端 Agent 语音对话区：按住说话（60秒）→ 转写确认（对，提交/重新说）→ 大字回复 + 语音播报（可再听一次）
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { agent } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

const message = useMessage()
const { recognize, speak } = useSpeech()

const msgs = ref([])
const listening = ref(false)
const remain = ref(60)
const pendingText = ref(null) // 转写待确认
const input = ref('')
const busy = ref(false)
let timer = null

const QUICK = ['家里灯不亮了', '医保怎么报销', '今天天气', '我要联系社区']

onMounted(() => {
  msgs.value.push({
    bot: true,
    text: '您好，我是社区小助手！按住下方话筒告诉我您要办的事，比如报修、查政策、看天气。',
  })
})

async function startListen() {
  listening.value = true
  remain.value = 60
  timer = setInterval(() => { remain.value -= 1; if (remain.value <= 0) stopListen() }, 1000)
  const r = await recognize()
  clearInterval(timer)
  listening.value = false
  if (r.ok && r.text) {
    pendingText.value = r.text
    speak(`您说的是：${r.text}，对吗？说“对”确认，或点“重新说”。`)
  } else {
    message.warning('没听清，请再说一次或直接打字')
    speak('没听清，请再说一次')
  }
}

function stopListen() {
  clearInterval(timer)
  listening.value = false
}

function confirmText() {
  if (!pendingText.value) return
  input.value = pendingText.value
  pendingText.value = null
  speak('好的，正在为您处理')
  send()
}

function retryText() {
  pendingText.value = null
  speak('好的，请重新说一次')
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
    // 自动语音播报（大字 + 语音）
    speak((reply || '').slice(0, 200))
  } catch (e) {
    msgs.value.push({ bot: true, text: e.message || '服务暂时不可用', error: true })
  } finally {
    busy.value = false
  }
}

function replay(m) {
  speak((m.text || '').slice(0, 200))
}

function sendOption(o) {
  send(o)
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">🤖 社区小助手</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">按住说话，或直接打字问我</p>

    <!-- 语音按钮（至少 80px 高） -->
    <div style="margin:8px 0;">
      <n-button type="error" block size="large" style="min-height:80px;font-size:1.4rem;" :loading="listening" @mousedown="startListen" @mouseup="stopListen" @touchstart="startListen" @touchend="stopListen">
        🎤 {{ listening ? `正在聆听…（${remain} 秒）` : '按住说话（最多 60 秒）' }}
      </n-button>
    </div>

    <!-- 转写确认（对，提交 / 重新说） -->
    <div v-if="pendingText" class="card" style="background:#fefce8;font-size:1.2rem;">
      <div>您说的是：<b>{{ pendingText }}</b></div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;">
        <n-button type="success" size="large" style="min-height:56px;" @click="confirmText">✅ 对，提交</n-button>
        <n-button size="large" style="min-height:56px;" @click="retryText">🔄 重新说</n-button>
      </div>
    </div>

    <!-- 快捷问题 -->
    <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;justify-content:center;">
      <n-button v-for="(q, i) in QUICK" :key="i" size="large" @click="sendOption(q)">{{ q }}</n-button>
    </div>

    <!-- 对话区（大字回复） -->
    <div class="card" style="min-height:220px;max-height:420px;overflow-y:auto;font-size:1.15rem;">
      <div v-for="(m, i) in msgs" :key="i" style="margin-bottom:12px;">
        <div v-if="!m.bot" style="text-align:right;">
          <div style="display:inline-block;background:#2E7D32;color:#fff;border-radius:12px;padding:10px 14px;max-width:85%;">🗣️ {{ m.text }}</div>
        </div>
        <div v-else>
          <div style="display:inline-block;background:#fff;border:1px solid var(--border);border-radius:12px;padding:10px 14px;max-width:90%;white-space:pre-wrap;"
               :style="m.error ? 'color:#dc2626;' : ''">
            🤖 {{ m.text }}
            <div v-if="m.intent" style="margin-top:6px;"><n-tag size="small" type="info">{{ m.intent }}</n-tag></div>
            <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
              <n-button v-for="(a, ai) in (m.actions || [])" :key="ai" size="large" type="primary"
                        @click="a.type === 'navigate' && $router.push(a.to)">{{ a.label }}</n-button>
              <n-button size="large" @click="replay(m)">🔊 再听一次</n-button>
            </div>
          </div>
        </div>
      </div>
      <div v-if="busy" style="color:#6b7280;">🤖 正在思考…</div>
    </div>

    <!-- 文字输入 -->
    <div style="display:flex;gap:8px;margin-top:10px;">
      <n-input v-model:value="input" type="textarea" :rows="2" placeholder="或直接打字告诉我（最多 200 字）" maxlength="200"
               style="font-size:1.2rem;" @keyup.enter="send()" />
      <n-button type="primary" size="large" style="min-height:56px;" :loading="busy" @click="send()">发送</n-button>
    </div>

    <!-- 底部紧急求助（长按 3 秒） -->
    <div style="margin-top:16px;">
      <n-button type="error" block size="large" style="min-height:70px;font-size:1.4rem;background:#dc2626;"
                @click="$router.push('/elderly/home')">🆘 紧急求助（长按 3 秒，去首页）</n-button>
    </div>
  </div>
</template>
