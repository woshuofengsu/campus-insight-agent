<script setup>
// 老年端政策问答：语音提问确认（对，提交/重新说）+ 答案大字播报 + 转人工二次确认 + 最近5条历史
// 降级硬化（B4）：语音不可用/没权限/连不上时**明说原因并引导打字**，不再一律"没听清"。
import { ref, onMounted, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { qa } from '../../api'
import { useSpeech, speechCapability, reasonText } from '../../composables/useSpeech'

const message = useMessage()
const { recognize, speak } = useSpeech()

const question = ref('')
const asking = ref(false)
const listening = ref(false)
const result = ref(null)
const pendingText = ref(null) // 语音转写待确认
const confirmTimer = null
const transferConfirm = ref(false)
const history = ref([])

const cap = speechCapability()
const asrBlocked = ref(!cap.hasASR || !cap.secure)
const blockReason = ref(cap.asrReason || '')
const banner = computed(() => reasonText(blockReason.value || 'unsupported'))

onMounted(async () => {
  try {
    const rows = (await qa.questions()) || []
    history.value = rows.slice(0, 5)
  } catch { /* 忽略 */ }
})

async function startListen() {
  if (asrBlocked.value) return
  listening.value = true
  const r = await recognize()
  listening.value = false
  if (r.ok && r.text) {
    pendingText.value = r.text
    speak(`您说的是：${r.text}。说“对”或点确认提交，说“重新说”重新来。`)
  } else {
    const reason = r.reason || 'empty'
    if (reason !== 'empty' && reason !== 'done') {
      asrBlocked.value = true
      blockReason.value = reason
    }
    message.warning(reasonText(reason))
  }
}

function confirmText() {
  if (pendingText.value) question.value = pendingText.value
  pendingText.value = null
  speak('好的，已填入问题。')
}

function retryText() {
  pendingText.value = null
  speak('好的，请重新说一次。')
}

async function ask() {
  if (!question.value.trim()) return message.warning('请先说或写下问题')
  asking.value = true
  result.value = null
  try {
    result.value = await qa.ask({ question: question.value, source: '老年端' })
    if (result.value.matched) {
      const answer = (result.value.answer || '').slice(0, 200)
      speak(`已为您找到答案：${answer}`)
    } else {
      speak('暂时没有找到答案，可以转人工咨询')
    }
    history.value = ((await qa.questions()) || []).slice(0, 5)
  } catch (e) {
    message.error(e.message)
  } finally {
    asking.value = false
  }
}

function playAnswer() {
  if (result.value?.matched) speak((result.value.answer || '').slice(0, 200))
}

async function doTransfer() {
  try {
    await qa.transfer(0, question.value || pendingText.value || '')
    message.success('已转人工，负责人会在 24 小时内回复您')
    speak('已转人工，负责人会在24小时内回复您')
    result.value = null
    question.value = ''
    pendingText.value = null
    history.value = ((await qa.questions()) || []).slice(0, 5)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">📖 政策问答</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">问医保、养老、住房政策</p>

    <div class="card">
      <div v-if="asrBlocked" data-speech-fallback class="panel-warm"
           style="border-radius:12px;padding:10px;margin-bottom:10px;font-size:1.3rem;">
        🔇 {{ banner }}
      </div>
      <n-button v-if="!asrBlocked" type="error" block size="large" style="min-height:64px;font-size:1.3rem;" :loading="listening" @click="startListen">
        🎤 {{ listening ? '正在聆听…（最多 60 秒）' : '按住说话提问' }}
      </n-button>

      <!-- 转写确认（对，提交 / 重新说） -->
      <div v-if="pendingText" class="card" style="margin-top:10px;background:#fefce8;font-size:1.25rem;">
        <div>您说的是：<b>{{ pendingText }}</b></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;">
          <n-button type="success" size="large" style="min-height:56px;" @click="confirmText">✅ 对，提交</n-button>
          <n-button size="large" style="min-height:56px;" @click="retryText">🔄 重新说</n-button>
        </div>
      </div>

      <n-input v-model:value="question" type="textarea" :rows="3" placeholder="想问什么政策？"
               style="font-size:1.3rem;margin-top:12px;" />
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px;">
        <n-button type="primary" size="large" style="min-height:60px;font-size:1.25rem;" :loading="asking" @click="ask">🔍 提问</n-button>
        <n-button size="large" style="min-height:60px;font-size:1.25rem;" @click="transferConfirm = true">🙋 转人工</n-button>
      </div>
    </div>

    <div v-if="result" class="card" style="font-size:1.25rem;">
      <template v-if="result.matched">
        <div style="font-weight:700;color:#2E7D32;">✅ 已回答</div>
        <!-- 属地可解释性（三端口径一致）：大字告知这条政策适用于哪里 -->
        <div v-if="result.applicable_area" style="margin-top:6px;font-size:1.15rem;">
          📍 适用地区：<b>{{ result.applicable_area }}</b>
        </div>
        <div style="margin-top:8px;white-space:pre-wrap;">{{ result.answer }}</div>
        <n-button type="primary" ghost block size="large" style="margin-top:12px;min-height:56px;" @click="playAnswer">🔊 播放回答</n-button>
      </template>
      <template v-else>
        <div style="font-weight:700;color:#d97706;">暂未找到答案</div>
        <div class="muted" style="margin-top:6px;">{{ result.manual_text }}</div>
        <n-button size="large" type="primary" ghost block style="margin-top:12px;min-height:56px;" @click="transferConfirm = true">🙋 转人工咨询</n-button>
      </template>
    </div>

    <!-- 最近 5 条历史（大字版） -->
    <div v-if="history.length" class="card" style="margin-top:12px;">
      <div style="font-weight:700;font-size:1.25rem;margin-bottom:8px;">📋 最近提问</div>
      <div v-for="h in history" :key="h.id" style="padding:8px 0;border-bottom:1px solid var(--border);font-size:1.25rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>{{ h.summary }}</b>
          <n-tag size="large" :type="h.status === '已自动回答' ? 'success' : h.status === '已回复' ? 'success' : 'warning'">{{ h.status }}</n-tag>
        </div>
        <div v-if="h.auto_answer" class="muted" style="font-size:1rem;margin-top:4px;">{{ h.auto_answer }}</div>
        <div v-if="h.reply" style="margin-top:4px;color:#2E7D32;">💬 {{ h.reply }}</div>
      </div>
    </div>

    <!-- 转人工二次确认 -->
    <n-modal v-model:show="transferConfirm" preset="dialog" type="warning"
             title="确认转人工？"
             content="负责人会在 24 小时内回复您，确认转人工？"
             positive-text="确认转人工" negative-text="再想想"
             @positive-click="doTransfer" @negative-click="transferConfirm = false" />
  </div>
</template>
