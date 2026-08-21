<script setup>
// 老年端大字通知 + 点击语音播报（紧急播两次）
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { notices } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

const message = useMessage()
const { speak } = useSpeech()
const list = ref([])

onMounted(async () => {
  try { list.value = (await notices.list()) || [] } catch (e) { message.error(e.message) }
  // 紧急通知进入页面自动播报（红色重复两次）
  const urgent = list.value.filter((n) => n.is_urgent && !n.is_read)
  if (urgent.length) {
    const txt = urgent.map((n) => `紧急通知：${n.elderly_summary || n.title}`).join('。')
    speak(txt)
    setTimeout(() => speak(txt), 3500)
  }
})

async function play(n) {
  const text = n.elderly_summary || n.title
  speak(text)
  if (n.is_urgent) setTimeout(() => speak(text), 3000)
  if (!n.is_read) {
    try {
      await notices.action(n.id, { action: 'mark_read' })
      list.value = (await notices.list()) || []
    } catch { /* 忽略 */ }
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">🔊 听通知</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">点通知听语音播报</p>

    <div v-for="n in list" :key="n.id" class="card" style="font-size:1.2rem;" @click="play(n)"
         :style="n.is_urgent ? 'border-left:5px solid #dc2626;background:#fef2f2;' : ''">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b style="font-size:1.3rem;">{{ n.title }}</b>
        <span v-if="n.is_urgent" style="color:#dc2626;font-weight:800;">🚨 紧急</span>
        <span v-else-if="!n.is_read" style="color:#4f46e5;font-weight:700;">● 未读</span>
      </div>
      <div class="muted" style="font-size:1.05rem;margin-top:6px;">{{ n.elderly_summary || n.body }}</div>
      <div class="muted" style="font-size:0.95rem;margin-top:6px;">{{ (n.published_at || '').slice(0, 16) }} · 🔊 点击播报</div>
    </div>
    <n-empty v-if="list.length === 0" description="暂无通知" style="font-size:1.1rem;" />
  </div>
</template>
