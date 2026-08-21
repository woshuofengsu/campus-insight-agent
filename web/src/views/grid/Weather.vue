<script setup>
// 天气管理：当前天气 + 预警 + 检查任务确认
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { weather } from '../../api'

const message = useMessage()
const w = ref(null)
const alerts = ref([])
const tasks = ref([])

onMounted(async () => {
  try { w.value = await weather.current() } catch { /* 忽略 */ }
  try { alerts.value = (await weather.alerts()) || [] } catch { /* 忽略 */ }
  try { tasks.value = (await weather.tasks()) || [] } catch { /* 忽略 */ }
})

async function confirm(t) {
  try {
    await weather.confirmTask(t.id, {
      checker: '网格员（演示）',
      items: [{ item: '排水沟/雨水口是否畅通', status: '已检查' }],
      note: '演示确认',
    })
    message.success(`任务 #${t.id} 已确认`)
    tasks.value = (await weather.tasks()) || []
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🌤️ 天气管理</h2>
    <p class="page-sub">实时天气 · 极端预警 · 检查任务</p>

    <div v-if="w" class="card">
      <b>当前：{{ w.condition }} {{ w.temp_low }}°~{{ w.temp_high }}°</b>
      <span class="muted" style="margin-left:8px;">{{ w.wind }} · 💧{{ w.rain_prob }}%</span>
      <div v-if="w.note" style="color:#b91c1c;font-size:0.85rem;margin-top:6px;">⚠️ {{ w.note }}</div>
    </div>

    <div class="card" v-if="alerts.length">
      <div style="font-weight:700;margin-bottom:8px;">🚨 生效预警</div>
      <div v-for="a in alerts" :key="a.id">
        {{ a.alert_type }}{{ a.level }}预警 · 生效 {{ (a.effective_time || '').slice(0, 16) }}
      </div>
    </div>

    <div class="card">
      <div style="font-weight:700;margin-bottom:8px;">🧾 检查任务</div>
      <div v-for="t in tasks" :key="t.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
        <div>
          <b>#{{ t.id }} {{ t.alert_type }}{{ t.level }}</b>
          <n-tag size="small" style="margin-left:8px;" :type="t.status === '待检查' ? 'warning' : 'success'">{{ t.status }}</n-tag>
        </div>
        <n-button v-if="t.status === '待检查'" size="small" type="primary" @click="confirm(t)">✅ 确认检查</n-button>
      </div>
      <n-empty v-if="tasks.length === 0" description="暂无检查任务" />
    </div>
  </div>
</template>
