<script setup>
// 社区天气：实时 + 3 天预报 + 预警标签
import { ref, onMounted } from 'vue'
import { weather } from '../../api'

const w = ref(null)
const alerts = ref([])

onMounted(async () => {
  try { w.value = await weather.current() } catch { /* 忽略 */ }
  try { alerts.value = (await weather.alerts()) || [] } catch { /* 忽略 */ }
})

const LEVEL_COLOR = { 黄色: '#eab308', 橙色: '#f97316', 红色: '#dc2626' }
</script>

<template>
  <div class="page">
    <h2 class="page-title">🌤️ 社区天气</h2>
    <p class="page-sub">实时天气 · 未来 3 天预报 · 极端天气预警</p>

    <div v-if="w" class="card">
      <div style="display:flex;align-items:center;gap:20px;">
        <div style="font-size:4rem;">{{ w.emoji }}</div>
        <div>
          <div style="font-size:2.4rem;font-weight:800;">{{ w.temp_high }}°C</div>
          <div class="muted">{{ w.condition }} · {{ w.temp_low }}°C ~ {{ w.temp_high }}°C</div>
          <div class="muted">{{ w.wind }} · 💧{{ w.rain_prob }}% · 湿度 {{ w.humidity }}%</div>
        </div>
      </div>
      <!-- AQI / UV / 穿衣 / 出行建议 -->
      <div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;border-top:1px solid var(--border);padding-top:10px;">
        <div v-if="w.aqi != null"><b>空气质量：</b>{{ w.aqi_level || w.aqi }}</div>
        <div v-if="w.uv != null"><b>紫外线：</b>{{ w.uv }}</div>
        <div v-if="w.dress"><b>👕 穿衣：</b>{{ w.dress }}</div>
        <div v-if="w.travel"><b>🚶 出行：</b>{{ w.travel }}</div>
        <div v-if="w.updated_at" class="muted" style="font-size:0.8rem;">数据更新于 {{ (w.updated_at || '').slice(0, 16) }}</div>
      </div>
      <div v-if="w.note" style="margin-top:10px;color:#b91c1c;font-weight:600;">⚠️ {{ w.note }}</div>
    </div>

    <div v-if="alerts.length" class="card" style="background:#fef2f2;border:1px solid #fca5a5;">
      <div style="font-weight:700;color:#b91c1c;">🚨 极端天气预警</div>
      <div v-for="a in alerts" :key="a.id" style="margin-top:8px;">
        <span class="status-pill" :style="{ background: (LEVEL_COLOR[a.level] || '#eab308') + '22', color: LEVEL_COLOR[a.level] || '#eab308', border: '1px solid ' + (LEVEL_COLOR[a.level] || '#eab308') }">
          {{ a.alert_type }}{{ a.level }}预警
        </span>
        <span class="muted" style="margin-left:8px;font-size:0.85rem;">生效 {{ (a.effective_time || '').slice(0, 16) }}</span>
      </div>
    </div>

    <div v-if="w?.forecast?.length" class="card">
      <div style="font-weight:700;margin-bottom:10px;">📅 未来预报</div>
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">
        <div v-for="(d, i) in w.forecast" :key="i" style="text-align:center;background:var(--bg);border:1px solid var(--border);border-radius:10px;padding:12px;">
          <div class="muted">{{ (d.date || '').slice(5) }}</div>
          <div style="font-size:1.6rem;">{{ d.emoji }}</div>
          <div>{{ d.condition }}</div>
          <div class="muted">{{ d.temp_low }}° ~ {{ d.temp_high }}°</div>
        </div>
      </div>
    </div>
  </div>
</template>
