<script setup>
// 老年端语音报修：文字输入（演示模拟语音转写）→ 确认上报
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'

const router = useRouter()
const message = useMessage()
const text = ref('')
const submitting = ref(false)

async function submit() {
  if (text.value.trim().length < 5) return message.warning('请描述问题，至少 5 个字')
  submitting.value = true
  try {
    const d = await elderly.voiceReport({ text: text.value, issue_type: '室内' })
    message.success(`已上报成功，工单 #${d.issue_id}（${d.category}，待审核）`)
    text.value = ''
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
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">说出或写下您遇到的问题（演示环境支持打字）</p>

    <div class="card" style="font-size:1.3rem;">
      <n-input v-model:value="text" type="textarea" :rows="4" placeholder="比如：3号楼电梯坏了 / 楼道灯不亮了"
               style="font-size:1.3rem;" />
      <n-button type="primary" block size="large" style="margin-top:14px;min-height:64px;font-size:1.3rem;"
                :loading="submitting" @click="submit">
        ✅ 确认上报
      </n-button>
    </div>

    <n-button size="large" block style="margin-top:12px;min-height:56px;" @click="router.push('/elderly/home')">🏠 返回首页</n-button>
  </div>
</template>
