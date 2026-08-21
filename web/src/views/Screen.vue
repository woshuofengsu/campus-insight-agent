<script setup>
// 治理大屏（开场展示）：社区运行数据总览
import { ref, onMounted } from 'vue'
import { issues, proposals, weather, qa } from '../api'

const data = ref({ issues: 0, pending: 0, props: 0, alerts: 0, qaCount: 0, temp: '--' })
const tick = ref(0)

async function load() {
  try {
    const all = (await issues.list()) || []
    const ps = (await proposals.list()) || []
    const alerts = (await weather.alerts()) || []
    const w = await weather.current()
    const qs = (await qa.questions()) || []
    data.value = {
      issues: all.length,
      pending: all.filter((i) => ['待审核', '已审核待派单', '处理中'].includes(i.status)).length,
      props: ps.filter((p) => p.status === '公示中').length,
      alerts: alerts.length,
      qaCount: qs.length,
      temp: w?.temp_high || '--',
    }
  } catch { /* 大屏失败不阻塞 */ }
}

onMounted(() => {
  load()
  setInterval(() => { tick.value++; load() }, 30000) // 30 秒自动刷新
})

const cards = [
  { label: '今日工单', value: () => data.value.issues, color: '#4fc3f7', icon: '🔧' },
  { label: '处理中', value: () => data.value.pending, color: '#ffb74d', icon: '🔄' },
  { label: '公示提案', value: () => data.value.props, color: '#81c784', icon: '💡' },
  { label: '天气预警', value: () => data.value.alerts, color: '#e57373', icon: '⚠️' },
  { label: '政策问答', value: () => data.value.qaCount, color: '#ba68c8', icon: '📖' },
]
</script>

<template>
  <div style="min-height:100vh;background:radial-gradient(ellipse at top,#0d3b2e 0%,#071f18 60%,#04120d 100%);color:#fff;padding:40px;display:flex;flex-direction:column;">
    <!-- 顶栏 -->
    <div style="text-align:center;margin-bottom:30px;">
      <div style="font-size:2.6rem;font-weight:800;letter-spacing:0.1em;background:linear-gradient(90deg,#81c784,#4fc3f7);-webkit-background-clip:text;background-clip:text;color:transparent;">
        🏘️ 社区先知 · 治理大屏
      </div>
      <div style="color:#7fbfa8;font-size:1rem;margin-top:8px;">CommunityInsight · 社区治理多智能体平台</div>
    </div>

    <!-- 核心指标 -->
    <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:24px;flex:1;align-content:center;">
      <div v-for="c in cards" :key="c.label" style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:20px;padding:30px 16px;text-align:center;">
        <div style="font-size:2.6rem;">{{ c.icon }}</div>
        <div style="font-size:3rem;font-weight:800;" :style="{ color: c.color }">{{ c.value() }}</div>
        <div style="color:#9ab8ab;font-size:1.1rem;margin-top:6px;">{{ c.label }}</div>
      </div>
    </div>

    <!-- 天气 + 实时状态 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:30px;padding:16px 20px;background:rgba(255,255,255,0.04);border-radius:14px;font-size:1.1rem;">
      <div>🌡️ 当前温度：<b style="color:#ffb74d;">{{ data.temp }}°C</b></div>
      <div>🔄 数据每 30 秒自动刷新</div>
    </div>

    <div style="text-align:center;color:#5f8575;font-size:0.9rem;margin-top:16px;">
      社区先知 CommunityInsight · 演示数据
    </div>
  </div>
</template>
