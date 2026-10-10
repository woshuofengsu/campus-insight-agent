<script setup>
// 老年端政策问答：语音提问确认（对，提交/重新说）+ 答案大字播报 + 转人工二次确认 + 最近5条历史
// 降级硬化（B4）：语音不可用/没权限/连不上时**明说原因并引导打字**，不再一律"没听清"。
//
// v3 复核 B3 修正（2026-09-28）：
//   ① 按钮文案写的是"按住说话提问"，事件却只有 `@click` —— 老人按住不放时页面毫无反应。
//      现在真的绑 pointerdown/pointerup（+ touch 事件）实现按住说话，松开即结束；
//   ② `speak()` 的返回值不再丢弃：播不出来（iOS 需用户手势 / 无 TTS / 静音）时
//      页面明确显示"这台手机念不出来，请看大字"，**不假装老人听到了**。
import { ref, onMounted, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { qa } from '../../api'
import { useSpeech, speechCapability, reasonText } from '../../composables/useSpeech'
import EIcon from '../../components/EIcon.vue'

const message = useMessage()
const { recognize, speak, stopListening } = useSpeech()

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
// 播报是否真的响过：失败就把 降级成"请看大字"（见 useSpeech 顶部说明）
const ttsOk = ref(cap.hasTTS)
const lastSpoken = ref('')

/** 统一播报入口：接住返回值，失败就如实降级。 */
async function say(text) {
  const t = (text || '').trim()
  if (!t) return false
  lastSpoken.value = t
  const ok = await speak(t, 1.0, 0.9)
  if (!ok) ttsOk.value = false
  return ok
}

onMounted(async () => {
  try {
    const rows = (await qa.questions()) || []
    history.value = rows.slice(0, 5)
  } catch { /* 忽略 */ }
})

/** 按住说话：按下开始识别，松开即结束（与按钮文案一致）。 */
async function startListen() {
  if (asrBlocked.value) return
  if (listening.value) return
  listening.value = true
  const r = await recognize()
  listening.value = false
  handleResult(r)
}

/** 松开手指/鼠标：**真的结束**本轮识别（识别结果仍会正常走到待确认）。 */
function stopListen() {
  listening.value = false
  // 注意（2026-10-06 修）：原来只改标志位，按钮写着"松开结束"但麦克风还在收音。
  try { stopListening() } catch { /* 不支持时忽略 */ }
}

function handleResult(r) {
  if (r.ok && r.text) {
    pendingText.value = r.text
    say(`您说的是：${r.text}。说“对”或点确认提交，说“重新说”重新来。`)
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
  say('好的，已填入问题。')
}

function retryText() {
  pendingText.value = null
  say('好的，请重新说一次。')
}

async function ask() {
  if (!question.value.trim()) return message.warning('请先说或写下问题')
  asking.value = true
  result.value = null
  try {
    result.value = await qa.ask({ question: question.value, source: '老年端' })
    if (result.value.matched) {
      const answer = (result.value.answer || '').slice(0, 200)
      say(`已为您找到答案：${answer}`)
    } else {
      say('暂时没有找到答案，可以转人工咨询')
    }
    history.value = ((await qa.questions()) || []).slice(0, 5)
  } catch (e) {
    message.error(e.message)
  } finally {
    asking.value = false
  }
}

function playAnswer() {
  if (result.value?.matched) say((result.value.answer || '').slice(0, 200))
}

async function doTransfer() {
  try {
    await qa.transfer(0, question.value || pendingText.value || '')
    message.success('已转人工，负责人会在 24 小时内回复您')
    await say('已转人工，负责人会在24小时内回复您')
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
    <div class="elderly-title"><EIcon name="book" :size="18" /> 政策问答</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">问医保、养老、住房政策</p>

    <div class="card">
      <div v-if="asrBlocked" data-speech-fallback class="panel-warm"
           style="border-radius:12px;padding:10px;margin-bottom:10px;font-size:1.3rem;">
        <EIcon name="speaker-off" :size="18" /> {{ banner }}
      </div>
      <n-button v-if="!asrBlocked" type="error" block size="large" style="min-height:64px;font-size:1.3rem;"
                :loading="listening" @pointerdown="startListen" @pointerup="stopListen"
                @pointerleave="stopListen" @touchstart.prevent="startListen" @touchend="stopListen">
        <EIcon name="mic" :size="18" /> {{ listening ? '正在聆听…（松开结束，最多 60 秒）' : '按住说话提问' }}
      </n-button>
      <!-- 播报失败必须可见（v3 复核 B3）：不能假装老人听到了 -->
      <div v-if="lastSpoken && !ttsOk" class="muted" style="margin-top:8px;font-size:1.25rem;">
        <EIcon name="speaker-off" :size="18" /> 这台手机的语音念不出来，请看屏幕上的大字（内容是一样的）
      </div>
      <n-button v-else-if="lastSpoken" block size="large" style="margin-top:8px;min-height:56px;font-size:1.25rem;"
                @click="say(lastSpoken)"><EIcon name="speaker" :size="18" /> 再听一遍</n-button>

      <!-- 转写确认（对，提交 / 重新说） -->
      <div v-if="pendingText" class="card" style="margin-top:10px;background:#fefce8;font-size:1.25rem;">
        <div>您说的是：<b>{{ pendingText }}</b></div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px;">
          <n-button type="success" size="large" style="min-height:56px;" @click="confirmText"><EIcon name="checkCircle" :size="18" /> 对，提交</n-button>
          <n-button size="large" style="min-height:56px;" @click="retryText"><EIcon name="refresh" :size="18" /> 重新说</n-button>
        </div>
      </div>

      <n-input v-model:value="question" type="textarea" :rows="3" placeholder="想问什么政策？"
               style="font-size:1.3rem;margin-top:12px;" />
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:14px;">
        <n-button type="primary" size="large" style="min-height:60px;font-size:1.25rem;" :loading="asking" @click="ask"><EIcon name="search" :size="18" /> 提问</n-button>
        <n-button size="large" style="min-height:60px;font-size:1.25rem;" @click="transferConfirm = true"><EIcon name="hand" :size="18" /> 转人工</n-button>
      </div>
    </div>

    <div v-if="result" class="card" style="font-size:1.25rem;">
      <template v-if="result.matched">
        <div style="font-weight:700;color:#2E7D32;"><EIcon name="checkCircle" :size="18" /> 已回答</div>
        <!-- 属地可解释性（三端口径一致）：大字告知这条政策适用于哪里 -->
        <div v-if="result.applicable_area" style="margin-top:6px;font-size:1.15rem;">
          <EIcon name="pin" :size="18" /> 适用地区：<b>{{ result.applicable_area }}</b>
        </div>
        <div v-if="result.knowledge" class="elderly-evidence" data-evidence-card>
          <div style="font-weight:700;color:var(--primary-ink);"><EIcon name="search" :size="18" /> 这条回答依据</div>
          <div style="margin-top:5px;">{{ result.knowledge.title }}</div>
          <div style="margin-top:5px;color:var(--muted);font-size:1.25rem;line-height:1.6;">
            <span v-if="result.knowledge.source">来源：{{ result.knowledge.source }} </span>
            <span v-if="result.knowledge.effective_date">生效：{{ result.knowledge.effective_date }} </span>
            <span v-if="result.knowledge.version">版本：V{{ result.knowledge.version }}</span>
          </div>
          <a v-if="result.knowledge.attachment" :href="result.knowledge.attachment" target="_blank" rel="noopener" style="display:inline-block;margin-top:4px;color:var(--primary-ink);">查看政策原文 ↗</a>
        </div>
        <div style="margin-top:8px;white-space:pre-wrap;">{{ result.answer }}</div>
        <n-button type="primary" ghost block size="large" style="margin-top:12px;min-height:56px;" @click="playAnswer"><EIcon name="speaker" :size="18" /> 播放回答</n-button>
      </template>
      <template v-else>
        <div style="font-weight:700;color:#d97706;">暂未找到答案</div>
        <div class="muted" style="margin-top:6px;">{{ result.manual_text }}</div>
        <div v-if="result.reason" class="elderly-evidence elderly-evidence-muted">{{ result.reason === 'weak_evidence' ? '系统提示：依据不够直接，已转人工核对。' : result.reason === 'manual' ? '系统提示：这类问题需要负责人判断。' : '系统提示：暂未找到匹配依据。' }}</div>
        <n-button size="large" type="primary" ghost block style="margin-top:12px;min-height:56px;" @click="transferConfirm = true"><EIcon name="hand" :size="18" /> 转人工咨询</n-button>
      </template>
    </div>

    <!-- 最近 5 条历史（大字版） -->
    <div v-if="history.length" class="card" style="margin-top:12px;">
      <div style="font-weight:700;font-size:1.25rem;margin-bottom:8px;"><EIcon name="clipboard" :size="18" /> 最近提问</div>
      <div v-for="h in history" :key="h.id" style="padding:8px 0;border-bottom:1px solid var(--border);font-size:1.25rem;">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>{{ h.summary }}</b>
          <n-tag size="large" :type="h.status === '已自动回答' ? 'success' : h.status === '已回复' ? 'success' : 'warning'">{{ h.status }}</n-tag>
        </div>
        <div v-if="h.auto_answer" class="muted" style="font-size:1.25rem;margin-top:4px;">{{ h.auto_answer }}</div>
        <div v-if="h.reply" style="margin-top:4px;color:#2E7D32;"><EIcon name="chat-dots" :size="18" /> {{ h.reply }}</div>
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

<style scoped>
.elderly-evidence { margin-top:10px; padding:10px 12px; border:1px solid var(--border); border-left:4px solid var(--primary); border-radius:10px; background:var(--card-bg); }
.elderly-evidence-muted { color:var(--muted); font-size:1.25rem; }
</style>
