<script setup>
// 全局极端天气滚动提醒（居民端/网格员端所有页面顶部，可临时关闭 6 小时，登录或 6 小时后重现）
import { ref, onMounted, onUnmounted } from 'vue'
import { weather } from '../api'

const alerts = ref([])
const hidden = ref(false)
const tick = ref(0)
let timer = null

function isHidden() {
  try {
    const raw = localStorage.getItem('ci_banner_hidden')
    if (!raw) return false
    const { ts } = JSON.parse(raw)
    // 6 小时后自动重现
    if (Date.now() - ts > 6 * 3600 * 1000) {
      localStorage.removeItem('ci_banner_hidden')
      return false
    }
    return true
  } catch {
    return false
  }
}

hidden.value = isHidden()

async function load() {
  try { alerts.value = (await weather.alerts()) || [] } catch { /* 忽略 */ }
}
onMounted(() => {
  load()
  timer = setInterval(() => { tick.value++; load() }, 60000) // 每分钟刷新
})
onUnmounted(() => timer && clearInterval(timer))

function closeBanner() {
  hidden.value = true
  localStorage.setItem('ci_banner_hidden', JSON.stringify({ ts: Date.now() }))
}
</script>

<template>
  <div v-if="alerts.length && !hidden" style="background:#dc2626;color:#fff;padding:8px 12px;overflow:hidden;font-size:0.9rem;">
    <div style="display:flex;align-items:center;gap:10px;">
      <div style="flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
        <span v-for="a in alerts" :key="a.id" style="margin-right:32px;">
          ⚠️ <b>{{ a.alert_type }}{{ a.level }}预警</b>（生效 {{ (a.effective_time || '').slice(0, 16) }}）
        </span>
      </div>
      <button @click="closeBanner" style="background:rgba(255,255,255,0.2);border:none;color:#fff;border-radius:99px;padding:2px 12px;cursor:pointer;font-size:0.8rem;">✕ 关闭（6 小时）</button>
    </div>
  </div>
</template>
