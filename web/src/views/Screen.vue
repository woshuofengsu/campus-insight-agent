<script setup>
// 治理大屏 v2（开场展示）：数字滚动（差值动画，刷新不抖动）+ 背景呼吸 + 卡片波浪入场 + 辉光
// 数据逻辑与 v1 完全一致（同 8 项接口、30 秒自动刷新）
import { ref, onMounted, onUnmounted } from 'vue'
import { issues, proposals, weather, agent } from '../api'
import EIcon from '../components/EIcon.vue'

const data = ref({
  issues: 0, pending: 0, props: 0, alerts: 0,
  selfRate: 0, temp: '--', kbRate: 0, kbCount: 0, careRate: 0,
})
const ready = ref(false) // 数据未到达前不显示 0（避免"先 0 再跳"）
const forceShow = ref(false) // 手机端「仍要查看」：临时绕过降级层
let timer = null

function toggleForce() {
  forceShow.value = true
}

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
  { label: '今日工单', v: () => data.value.issues, color: '#4fc3f7', icon: 'wrench', suffix: '' },
  { label: '处理中', v: () => data.value.pending, color: '#ffb74d', icon: 'refresh', suffix: '' },
  { label: '公示提案', v: () => data.value.props, color: '#81c784', icon: 'bulb', suffix: '' },
  { label: '天气预警', v: () => data.value.alerts, color: '#e57373', icon: 'alert', suffix: '' },
  { label: 'AI 自转率', v: () => data.value.selfRate, color: '#ba68c8', icon: 'robot', suffix: '%' },
  { label: '知识库命中率', v: () => data.value.kbRate, color: '#4dd0e1', icon: 'book', suffix: '%' },
  { label: '政策语料', v: () => data.value.kbCount, color: '#ffd54f', icon: 'file', suffix: ' 条' },
  { label: '关怀触达率', v: () => data.value.careRate, color: '#f06292', icon: 'heart', suffix: '%' },
]
</script>

<template>
  <div style="min-height:100vh;background:#0B100E;color:#fff;padding:40px;display:flex;flex-direction:column;position:relative;overflow:hidden;">
    <!-- 移动端降级（P1-G3）：治理大屏是桌面/投屏场景，手机上 8 卡会被压扁，
         这里明确告知而不是渲染挤压布局。仅 <900px 显示，桌面/大屏完全不受影响。 -->
    <div v-if="!forceShow" class="screen-mobile-only" style="position:absolute;inset:0;z-index:20;background:#0B100E;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:28px;">
      <div style="display:flex;justify-content:center;"><EIcon name="monitor" :size="56" :weight="1.6" /></div>
      <div style="font-size:1.4rem;font-weight:800;margin-top:12px;">治理大屏请在电脑或投屏上查看</div>
      <div style="color:#9fd8c4;margin-top:10px;line-height:1.9;max-width:22rem;">
        大屏为 8 张实时指标卡设计，手机屏幕会挤压布局。<br />
        建议用电脑浏览器全屏打开，或横屏后刷新。
      </div>
      <div style="margin-top:22px;display:flex;gap:10px;flex-wrap:wrap;justify-content:center;">
        <n-button type="primary" size="large" @click="$router.push('/grid/dashboard')">返回工作台</n-button>
        <n-button size="large" ghost style="color:#fff;" @click="toggleForce">仍要查看</n-button>
      </div>
    </div>

    <!-- v3：删掉背景呼吸光环、标题流光、数字滚动、悬停辉光与整屏渐变。
         大屏是"把这些数看清楚"的地方，不是炫技的地方（任务书 §三.1）。 -->

    <!-- 顶栏 -->
    <div style="text-align:center;margin-bottom:26px;position:relative;">
      <div style="font-size:2.7rem;font-weight:900;letter-spacing:0.08em;">
        <EIcon name="community" :size="18" /> 社区先知 · 治理大屏
      </div>
      <div style="color:#9fd8c4;font-size:1rem;margin-top:10px;letter-spacing:0.04em;">
        CommunityInsight · 社区治理多智能体平台
      </div>
    </div>

    <!-- 核心指标（静态数值：大屏要的是"现在的数"，不跳数） -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:18px;flex:1;align-content:center;position:relative;">
      <div v-for="c in cards" :key="c.label" class="screen-card"
           style="background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.12);border-radius:var(--r-card);padding:26px 16px;text-align:center;">
        <div style="display:flex;justify-content:center;"><EIcon :name="c.icon" :size="40" :weight="1.6" /></div>
        <div style="font-size:2.9rem;font-weight:900;margin-top:8px;letter-spacing:-0.01em;" :style="{ color: c.color }">
          <template v-if="ready">{{ c.v() }}{{ c.suffix || '' }}</template>
          <template v-else>--</template>
        </div>
        <div style="color:#9ab8ab;font-size:1.06rem;margin-top:6px;">{{ c.label }}</div>
      </div>
    </div>

    <!-- 天气 + 刷新状态 -->
    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:28px;padding:16px 22px;background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.10);border-radius:var(--r-card);font-size:1.06rem;position:relative;">
      <div><EIcon name="thermometer" :size="18" /> 当前温度：<b style="color:#ffb74d;">{{ data.temp }}°C</b></div>
      <div style="color:#9ab8ab;">
        <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#4ade80;margin-right:6px;"></span>
        数据每 30 秒自动刷新
      </div>
    </div>

    <div style="text-align:center;color:#5f8575;font-size:0.9rem;margin-top:14px;position:relative;">
      社区先知 CommunityInsight · 演示数据
    </div>
  </div>
</template>
