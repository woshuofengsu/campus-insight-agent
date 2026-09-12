<script setup>
// 治理大屏 v2（开场展示）：数字滚动（差值动画，刷新不抖动）+ 背景呼吸 + 卡片波浪入场 + 辉光
// 数据逻辑与 v1 完全一致（同 8 项接口、30 秒自动刷新）
import { ref, onMounted, onUnmounted } from 'vue'
import { issues, proposals, weather, agent } from '../api'
import CountUp from '../components/CountUp.vue'

const data = ref({
  issues: 0, pending: 0, props: 0, alerts: 0,
  selfRate: 0, temp: '--', kbRate: 0, kbCount: 0, careRate: 0,
})
const ready = ref(false) // 数据未到达前不显示 0（避免"先 0 再跳"）
let timer = null

async function load() {
  try {
    const all = (await issues.list()) || []
    const ps = (await proposals.list()) || []
    const alerts = (await weather.alerts()) || []
    const w = await weather.current()
    const sr = (await agent.selfResolution()) || {}
    const kb = (await agent.kbHealth()) || {}
    const care = (await agent.careMetrics()) || {}
    data.value = {
      issues: all.length,
      pending: all.filter((i) => ['待审核', '已审核待派单', '处理中'].includes(i.status)).length,
      props: ps.filter((p) => p.status === '公示中').length,
      alerts: alerts.length,
      selfRate: sr.ai_self_resolution_rate ?? 0,
      temp: w?.temp_high || '--',
      kbRate: kb.queries ? kb.hit_rate : 0,
      kbCount: kb.kb_published || 0,
      careRate: care.emotion_events ? care.touch_rate : 0,
    }
    ready.value = true
  } catch { /* 大屏失败不阻塞 */ }
}

onMounted(() => {
  load()
  timer = setInterval(load, 30000) // 30 秒自动刷新（CountUp 会做差值滚动）
})
onUnmounted(() => { if (timer) clearInterval(timer) })

const cards = [
  { label: '今日工单', v: () => data.value.issues, color: '#4fc3f7', icon: '🔧', suffix: '' },
  { label: '处理中', v: () => data.value.pending, color: '#ffb74d', icon: '🔄', suffix: '' },
  { label: '公示提案', v: () => data.value.props, color: '#81c784', icon: '💡', suffix: '' },
  { label: '天气预警', v: () => data.value.alerts, color: '#e57373', icon: '⚠️', suffix: '' },
  { label: 'AI 自转率', v: () => data.value.selfRate, color: '#ba68c8', icon: '🤖', suffix: '%' },
  { label: '知识库命中率', v: () => data.value.kbRate, color: '#4dd0e1', icon: '📚', suffix: '%' },
  { label: '政策语料', v: () => data.value.kbCount, color: '#ffd54f', icon: '📄', suffix: ' 条' },
  { label: '关怀触达率', v: () => data.value.careRate, color: '#f06292', icon: '💗', suffix: '%' },
]
</script>

<template>
  <div style="min-height:100vh;background:radial-gradient(ellipse at top,#0d3b2e 0%,#071f18 60%,#04120d 100%);color:#fff;padding:40px;display:flex;flex-direction:column;position:relative;overflow:hidden;">
    <!-- 背景呼吸光环（沉浸感） -->
    <div class="breathe" style="position:absolute;width:900px;height:900px;border-radius:50%;left:-220px;top:-320px;background:radial-gradient(circle,rgba(129,199,132,0.20) 0%,transparent 62%);pointer-events:none;"></div>
    <div class="breathe" style="position:absolute;width:760px;height:760px;border-radius:50%;right:-200px;bottom:-300px;background:radial-gradient(circle,rgba(79,195,247,0.16) 0%,transparent 62%);animation-delay:4s;pointer-events:none;"></div>

    <!-- 顶栏 -->
    <div class="fade-up" style="text-align:center;margin-bottom:26px;position:relative;">
      <div class="title-sheen" style="font-size:2.7rem;font-weight:900;letter-spacing:0.1em;">
        🏘️ 社区先知 · 治理大屏
      </div>
      <div style="color:#7fbfa8;font-size:1rem;margin-top:10px;letter-spacing:0.04em;">
        CommunityInsight · 社区治理多智能体平台
      </div>
    </div>

    <!-- 核心指标（波浪入场 + 数字滚动 + 悬停辉光） -->
    <div class="wave" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:18px;flex:1;align-content:center;position:relative;">
      <div v-for="c in cards" :key="c.label" class="screen-card"
           style="background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);border-radius:20px;padding:28px 16px;text-align:center;backdrop-filter:blur(4px);">
        <div style="font-size:2.5rem;line-height:1;">{{ c.icon }}</div>
        <div style="font-size:2.9rem;font-weight:900;margin-top:8px;letter-spacing:-0.01em;" :style="{ color: c.color, textShadow: '0 0 22px ' + c.color + '55' }">
          <template v-if="ready"><CountUp :value="c.v()" :suffix="c.suffix" :duration="1500" /></template>
          <template v-else>--</template>
        </div>
        <div style="color:#9ab8ab;font-size:1.06rem;margin-top:6px;">{{ c.label }}</div>
      </div>
    </div>

    <!-- 天气 + 刷新状态 -->
    <div class="fade-up-d3" style="display:flex;justify-content:space-between;align-items:center;margin-top:28px;padding:16px 22px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.10);border-radius:16px;font-size:1.06rem;position:relative;">
      <div>🌡️ 当前温度：<b style="color:#ffb74d;">{{ data.temp }}°C</b></div>
      <div style="color:#9ab8ab;">
        <span class="dot-breathe" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:6px;"></span>
        数据每 30 秒自动刷新
      </div>
    </div>

    <div style="text-align:center;color:#5f8575;font-size:0.9rem;margin-top:14px;position:relative;">
      社区先知 CommunityInsight · 演示数据
    </div>
  </div>
</template>
