<script setup>
// 老年端首页：两行三列大按钮 + 用药/通知摘要 + 紧急求助
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../../stores/user'
import { elderly, weather } from '../../api'

const router = useRouter()
const store = useUserStore()

const home = ref(null)
const w = ref(null)

onMounted(async () => {
  try { home.value = await elderly.home() } catch { /* 忽略 */ }
  try { w.value = await weather.current() } catch { /* 忽略 */ }
})

const rows = [
  [{ to: '/elderly/report', icon: '🗣️', label: '报修' }, { to: '/elderly/notices', icon: '🔊', label: '通知' }, { to: '/elderly/medication', icon: '💊', label: '用药' }],
  [{ to: '/elderly/qa', icon: '📖', label: '政策问答' }, { to: '/elderly/home', icon: '👨‍👩‍👧', label: '联系家人' }, { to: '/elderly/home', icon: '🏠', label: '回首页' }],
]

async function sos() {
  try {
    await elderly.emergency()
    alert('🆘 紧急求助已发出！负责人会尽快联系您。')
  } catch (e) {
    alert(e.message || '触发失败')
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">你好，{{ home?.name || '大爷/阿姨' }}</div>

    <!-- 天气摘要 -->
    <div v-if="w" class="card" style="text-align:center;background:#f0f9ff;font-size:1.2rem;">
      {{ w.emoji }} {{ w.condition }} {{ w.temp_low }}°~{{ w.temp_high }}°
      <div v-if="w.note" style="color:#dc2626;font-weight:700;">⚠️ {{ w.note }}</div>
    </div>

    <!-- 用药提醒 -->
    <div v-if="home?.due_medications > 0" class="card" style="background:#fefce8;text-align:center;font-size:1.3rem;font-weight:700;">
      💊 您有 {{ home.due_medications }} 条用药提醒
    </div>

    <!-- 未读通知 -->
    <div v-if="home?.unread_notices > 0" class="card" style="background:#f0fdf4;text-align:center;font-size:1.2rem;">
      🔔 {{ home.unread_notices }} 条新通知
      <n-button size="large" type="success" @click="router.push('/elderly/notices')">去听</n-button>
    </div>

    <!-- 两行三列大按钮 -->
    <div v-for="(row, ri) in rows" :key="ri" style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin:12px 0;">
      <n-button v-for="b in row" :key="b.label" size="large" type="primary" ghost class="elderly-btn"
                @click="router.push(b.to)">
        <span style="font-size:2rem;">{{ b.icon }}</span>{{ b.label }}
      </n-button>
    </div>

    <!-- 紧急求助 -->
    <div style="margin-top:20px;">
      <n-button size="large" type="error" block class="elderly-btn" style="min-height:84px;font-size:1.6rem;" @click="sos">
        🆘 紧急求助
      </n-button>
    </div>
  </div>
</template>
