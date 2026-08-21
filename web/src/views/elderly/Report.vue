<script setup>
// 老年端语音报修：语音识别（60秒）→ 转写确认（10秒超时）→ 提交
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

const router = useRouter()
const message = useMessage()
const { recognize, speak } = useSpeech()

const text = ref('')
const listening = ref(false)
const confirming = ref(false)
const submitting = ref(false)
const lastResult = ref(null) // {issue_id, category, corrected, original}

onMounted(() => speak('请说出或写下您遇到的问题'))

async function startListen() {
  listening.value = true
  const r = await recognize()
  listening.value = false
  if (r.ok && r.text) {
    text.value = r.text
    confirming.value = true
    speak(`您说的是：${r.text}，对吗？`)
    // 10 秒确认超时自动取消（方案：确认超时 10 秒）
    setTimeout(() => {
      if (confirming.value) {
        confirming.value = false
        message.info('确认超时已取消，内容已保留，可重新提交')
      }
    }, 10000)
  } else {
    message.warning('没听清，请再说一次或直接打字')
  }
}

async function submit() {
  if (text.value.trim().length < 5) return message.warning('请描述问题，至少 5 个字')
  submitting.value = true
  try {
    const d = await elderly.voiceReport({ text: text.value, issue_type: '室内' })
    lastResult.value = d
    message.success(`已上报成功，工单 #${d.issue_id}（${d.category}，待审核）`)
    text.value = ''
    confirming.value = false
  } catch (e) {
    message.error(e.message)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">🗣️ 一句话报修</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">点「🎤 按住说话」语音上报，或直接打字</p>

    <div class="card" style="font-size:1.3rem;">
      <n-button type="error" block size="large" style="min-height:72px;font-size:1.4rem;" :loading="listening" @click="startListen">
        🎤 {{ listening ? '正在聆听…（最多 60 秒）' : '按住说话' }}
      </n-button>

      <n-input v-model:value="text" type="textarea" :rows="4" placeholder="或直接输入问题：3号楼电梯坏了"
               style="font-size:1.3rem;margin-top:12px;" />

      <!-- 转写确认（10 秒超时） -->
      <div v-if="confirming" style="background:#eef2ff;border-radius:10px;padding:10px;margin-top:12px;font-size:1.1rem;">
        ✅ 已识别：{{ text }}（10 秒内确认）
      </div>

      <n-button type="primary" block size="large" style="margin-top:14px;min-height:64px;font-size:1.3rem;"
                :loading="submitting" @click="submit">
        ✅ 确认上报
      </n-button>

      <!-- 纠错确认（原始描述与纠正后描述均保留） -->
      <div v-if="lastResult && lastResult.corrected && lastResult.corrected !== lastResult.original"
           style="background:#fefce8;border-radius:10px;padding:10px;margin-top:12px;font-size:1rem;">
        <b>✏️ 已为您纠正描述（原始与纠正后均保留）：</b>
        <div style="margin-top:6px;">🗣️ 您说的：{{ lastResult.original }}</div>
        <div style="margin-top:4px;">✅ 已纠正：{{ lastResult.corrected }}</div>
      </div>
    </div>

    <n-button size="large" block style="margin-top:12px;min-height:56px;" @click="router.push('/elderly/home')">🏠 返回首页</n-button>
  </div>
</template>
