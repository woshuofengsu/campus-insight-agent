<script setup>
// 老年端政策问答：语音输入（60秒）→ 自动回答 + 转人工
import { ref } from 'vue'
import { useMessage } from 'naive-ui'
import { qa } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

const message = useMessage()
const { recognize, speak } = useSpeech()

const question = ref('')
const asking = ref(false)
const listening = ref(false)
const result = ref(null)

async function startListen() {
  listening.value = true
  const r = await recognize()
  listening.value = false
  if (r.ok && r.text) {
    question.value = r.text
    speak(`您的问题是：${r.text}，对吗？`)
  } else {
    message.warning('没听清，请再说一次或直接打字')
  }
}

async function ask() {
  if (!question.value.trim()) return message.warning('请先说或写下问题')
  asking.value = true
  result.value = null
  try {
    result.value = await qa.ask({ question: question.value, source: '老年端' })
    if (result.value.matched) speak('已为您找到答案')
  } catch (e) {
    message.error(e.message)
  } finally {
    asking.value = false
  }
}

async function transfer() {
  try {
    await qa.transfer(0, question.value)
    message.success('已转人工，负责人会联系您')
    result.value = null
    question.value = ''
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">📖 政策问答</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">问医保、养老、住房政策</p>

    <div class="card">
      <n-button type="error" block size="large" style="min-height:64px;font-size:1.3rem;" :loading="listening" @click="startListen">
        🎤 {{ listening ? '正在聆听…（最多 60 秒）' : '按住说话提问' }}
      </n-button>
      <n-input v-model:value="question" type="textarea" :rows="3" placeholder="想问什么政策？"
               style="font-size:1.3rem;margin-top:12px;" />
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px;">
        <n-button type="primary" size="large" style="min-height:60px;font-size:1.2rem;" :loading="asking" @click="ask">🔍 提问</n-button>
        <n-button size="large" style="min-height:60px;font-size:1.2rem;" @click="transfer">🙋 转人工</n-button>
      </div>
    </div>

    <div v-if="result" class="card" style="font-size:1.2rem;">
      <template v-if="result.matched">
        <div style="font-weight:700;color:#2E7D32;">✅ 已回答</div>
        <div style="margin-top:8px;white-space:pre-wrap;">{{ result.answer }}</div>
      </template>
      <template v-else>
        <div style="font-weight:700;color:#d97706;">暂未找到答案</div>
        <div class="muted" style="margin-top:6px;">{{ result.manual_text }}</div>
        <n-button size="large" type="primary" ghost block style="margin-top:12px;min-height:56px;" @click="transfer">🙋 转人工咨询</n-button>
      </template>
    </div>
  </div>
</template>
