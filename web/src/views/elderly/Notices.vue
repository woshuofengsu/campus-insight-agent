<script setup>
// 老年端大字通知 + 点击语音播报（紧急播两次）
// 降级硬化（B4）：
//   ① **不再挂载即自动播报**——iOS Safari 的 TTS 必须由用户手势触发，自动播会静默不响，
//      老人看到"🔊 点击播报"却点不动、也不知道为什么。改成"点一下听"；
//   ② `speak()` 的返回值不再丢弃：不支持/失败时把"🔊"降级成"大字已显示"，并显式说明原因。
import { ref, onMounted, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { notices } from '../../api'
import { useSpeech, speechCapability } from '../../composables/useSpeech'

const message = useMessage()
const { speak } = useSpeech()
const list = ref([])
const cap = speechCapability()
const ttsOk = ref(cap.hasTTS)          // 播报失败后置 false，页面据此切换文案
const urgentText = computed(() => {
  const urgent = list.value.filter((n) => n.is_urgent && !n.is_read)
  return urgent.map((n) => `紧急通知：${n.elderly_summary || n.title}`).join('。')
})

onMounted(async () => {
  try { list.value = (await notices.list()) || [] } catch (e) { message.error(e.message) }
})

async function readUrgent() {
  const ok = await speak(urgentText.value)
  if (!ok) ttsOk.value = false
}

async function play(n) {
  const text = n.elderly_summary || n.title
  const ok = await speak(text)
  if (!ok) {
    ttsOk.value = false          // 这台机器播不出来：页面下面会说明"请看大字"
  } else if (n.is_urgent) {
    setTimeout(() => speak(text), 3000)
  }
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
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">
      {{ ttsOk ? '点通知听语音播报' : '语音播报在这台手机上不可用，请看下面的大字' }}
    </p>

    <!-- 降级提示条（审计靠 data-speech-fallback 验证"关掉语音仍可用"） -->
    <div v-if="!ttsOk" data-speech-fallback
         class="card panel-warm" style="border-radius:14px;font-size:1.3rem;">
      🔇 这台手机不能自动念出来，通知内容都在下面用大字显示
    </div>

    <div v-if="urgentText && ttsOk" class="card" style="border-radius:14px;">
      <div style="font-size:1.3rem;font-weight:700;margin-bottom:8px;">📢 有紧急通知</div>
      <n-button type="error" block size="large" style="min-height:72px;font-size:1.4rem;"
                @click="readUrgent">🔊 点一下听紧急通知</n-button>
    </div>
    <div v-for="n in list" :key="n.id" class="card" style="font-size:1.25rem;" @click="play(n)"
         :style="n.is_urgent ? 'border-left:5px solid #dc2626;background:#fef2f2;' : ''">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b style="font-size:1.3rem;">{{ n.title }}</b>
        <span v-if="n.is_urgent" style="color:var(--ink-danger);font-weight:800;">🚨 紧急</span>
        <span v-else-if="!n.is_read" style="color:var(--ink-info);font-weight:700;">● 未读</span>
      </div>
      <div class="muted" style="margin-top:6px;">{{ n.elderly_summary || n.body }}</div>
      <div class="muted" style="margin-top:6px;">{{ (n.published_at || '').slice(0, 16) }} · 🔊 点击播报</div>
    </div>
    <n-empty v-if="list.length === 0" description="暂无通知" style="font-size:1.25rem;" />
  </div>
</template>
