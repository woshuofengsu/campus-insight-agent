<script setup>
// 天气管理：当前天气 + 预警 + 检查任务 + 任务历史 + 社区天气概况
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { weather } from '../../api'

const message = useMessage()
const w = ref(null)
const alerts = ref([])
const tasks = ref([])
const history = ref([])
const overview = ref([])
const tab = ref('now')

onMounted(async () => {
  try { w.value = await weather.current() } catch { /* 忽略 */ }
  try { alerts.value = (await weather.alerts()) || [] } catch { /* 忽略 */ }
  try { tasks.value = (await weather.tasks()) || [] } catch { /* 忽略 */ }
  try { history.value = (await weather.history({ limit: 200 })) || [] } catch { /* 忽略 */ }
  try { overview.value = (await weather.overview({ limit: 50 })) || [] } catch { /* 忽略 */ }
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
    history.value = (await weather.history({ limit: 200 })) || []
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🌤️ 天气管理</h2>
    <p class="page-sub">实时天气 · 极端预警 · 检查任务 · 历史留痕 · 社区概况</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="now" tab="当前与任务">
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
      </n-tab-pane>

      <n-tab-pane name="history" tab="任务历史">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">📜 历史检查任务（含已确认，留痕可追溯）</div>
          <div v-for="h in history" :key="h.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
            <div>
              <b>#{{ h.id }} {{ h.alert_type }}{{ h.level }}</b>
              <span class="muted" style="margin-left:8px;font-size:0.85rem;">{{ (h.created_at || '').slice(0, 16) }}</span>
              <div v-if="h.checked_at" class="muted" style="font-size:0.8rem;margin-top:2px;">
                确认人：{{ h.checker || '—' }} · 于 {{ (h.checked_at || '').slice(0, 16) }}
                <span v-if="h.note"> · 备注：{{ h.note }}</span>
              </div>
            </div>
            <n-tag size="small" :type="h.status === '已确认' ? 'success' : h.status === '已超时' ? 'error' : 'warning'">{{ h.status }}</n-tag>
          </div>
          <n-empty v-if="history.length === 0" description="暂无历史任务" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="overview" tab="社区概况">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">🏘️ 各社区天气概况（预警为当前生效标签）</div>
          <div v-for="(o, i) in overview" :key="i" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
            <div>
              <b>{{ o.city }}</b>
              <span class="muted" style="margin-left:8px;font-size:0.85rem;">{{ o.condition }} {{ o.temp_low }}°~{{ o.temp_high }}°</span>
              <span v-for="(tag, j) in o.alert_tags" :key="j" style="margin-left:6px;">
                <n-tag size="small" type="error">{{ tag.type }}{{ tag.level }}</n-tag>
              </span>
            </div>
            <span class="muted" style="font-size:0.8rem;">更新 {{ (o.updated_at || '').slice(0, 16) }}</span>
          </div>
          <n-empty v-if="overview.length === 0" description="暂无天气数据" />
        </div>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
