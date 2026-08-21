<script setup>
// 老年端大字通知 + 语音播报提示
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { notices } from '../../api'

const message = useMessage()
const list = ref([])

onMounted(async () => {
  try { list.value = (await notices.list()) || [] } catch (e) { message.error(e.message) }
})

async function markRead(n) {
  if (n.is_read) return
  try {
    await notices.action(n.id, { action: 'mark_read' })
    list.value = (await notices.list()) || []
  } catch { /* 忽略 */ }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">🔊 听通知</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">点通知可语音播报（演示环境以文字展示）</p>

    <div v-for="n in list" :key="n.id" class="card" style="font-size:1.2rem;" @click="markRead(n)"
         :style="n.is_urgent ? 'border-left:5px solid #dc2626;' : ''">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b style="font-size:1.3rem;">{{ n.title }}</b>
        <span v-if="n.is_urgent" style="color:#dc2626;font-weight:800;">🚨 紧急</span>
      </div>
      <div class="muted" style="font-size:1.05rem;margin-top:6px;">{{ n.body }}</div>
      <div class="muted" style="font-size:0.95rem;margin-top:6px;">{{ (n.published_at || '').slice(0, 16) }}</div>
    </div>
    <n-empty v-if="list.length === 0" description="暂无通知" style="font-size:1.1rem;" />
  </div>
</template>
