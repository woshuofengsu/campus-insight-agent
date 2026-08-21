<script setup>
// 居民首页：天气摘要 + 未读通知 + 紧急通知强制弹窗 + 快捷入口
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../../stores/user'
import { weather, notices } from '../../api'

const router = useRouter()
const store = useUserStore()

const w = ref(null)
const noticeList = ref([])
const urgentModal = ref(null) // 紧急通知弹窗

onMounted(async () => {
  try { w.value = await weather.current() } catch { /* 天气失败不阻塞 */ }
  try { noticeList.value = (await notices.list()) || [] } catch { /* 忽略 */ }
  const urgent = noticeList.value.find((n) => n.is_urgent && !n.is_read)
  if (urgent) urgentModal.value = urgent
})

const unread = () => noticeList.value.filter((n) => !n.is_read).length

async function closeUrgent() {
  const n = urgentModal.value
  urgentModal.value = null
  if (n && !n.is_read) {
    try {
      await notices.action(n.id, { action: 'mark_read' })
      noticeList.value = (await notices.list()) || []
    } catch { /* 忽略 */ }
  }
}

const entries = [
  { to: '/resident/work-orders', icon: '🔧', label: '报修' },
  { to: '/resident/proposals', icon: '💡', label: '邻里议事' },
  { to: '/resident/qa', icon: '📖', label: '政策问答' },
  { to: '/resident/notices', icon: '📢', label: '通知' },
  { to: '/resident/health', icon: '🏥', label: '健康防护' },
  { to: '/resident/weather', icon: '🌤️', label: '天气' },
]
</script>

<template>
  <div class="page">
    <h2 class="page-title">你好，{{ store.user?.name || '居民' }}</h2>
    <p class="page-sub">社区先知 · 知 · 报 · 议 · 督</p>

    <div v-if="w?.note" class="card" style="background:#fef2f2;border:1px solid #fca5a5;color:#b91c1c;font-weight:600;">
      ⚠️ {{ w.note }}
    </div>

    <div class="card" v-if="w">
      <div style="display:flex;align-items:center;gap:16px;">
        <div style="font-size:3rem;">{{ w.emoji || '🌤️' }}</div>
        <div>
          <div style="font-size:1.6rem;font-weight:800;">{{ w.temp_high }}°C</div>
          <div class="muted">{{ w.condition }} · {{ w.temp_low }}°C ~ {{ w.temp_high }}°C · {{ w.wind }}</div>
          <div class="muted">{{ w.advice }}</div>
        </div>
      </div>
    </div>

    <div v-if="unread() > 0" class="card" style="background:#f0fdf4;border:1px solid #86efac;">
      <b>🔔 您有 {{ unread() }} 条未读通知</b>
      <n-button size="small" type="success" ghost style="margin-left:8px;" @click="router.push('/resident/notices')">查看</n-button>
    </div>

    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
      <n-button v-for="e in entries" :key="e.to" size="large" type="primary" ghost
                style="min-height:84px;font-size:1.05rem;" @click="router.push(e.to)">
        <span style="font-size:1.8rem;">{{ e.icon }}</span>{{ e.label }}
      </n-button>
    </div>

    <!-- 紧急通知强制弹窗 -->
    <n-modal :show="!!urgentModal" @update:show="(v) => { if (!v) urgentModal = null }" preset="dialog" type="error"
             :title="urgentModal ? ('🚨 ' + urgentModal.title) : ''"
             :content="urgentModal ? urgentModal.body : ''"
             positive-text="我知道了" @positive-click="closeUrgent" />
  </div>
</template>
