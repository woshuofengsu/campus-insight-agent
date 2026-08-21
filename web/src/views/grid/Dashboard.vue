<script setup>
// 网格员工作台：待办统计 + 紧急工单 + 待审核提案
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues, proposals } from '../../api'

const router = useRouter()
const message = useMessage()

const stats = ref({ total: 0, pending: 0, processing: 0, resolved: 0 })
const urgent = ref([])
const pendingProps = ref([])

onMounted(async () => {
  try {
    const all = (await issues.list()) || []
    stats.value = {
      total: all.length,
      pending: all.filter((i) => i.status === '待审核' || i.status === '已审核待派单').length,
      processing: all.filter((i) => i.status === '处理中' || i.status === '已派单').length,
      resolved: all.filter((i) => i.status === '处理结束').length,
    }
    urgent.value = all.filter((i) => i.urgency === '紧急' && !['处理结束', '已关闭', '已撤回'].includes(i.status)).slice(0, 5)
  } catch (e) { message.error(e.message) }
  try {
    const ps = (await proposals.list()) || []
    pendingProps.value = ps.filter((p) => p.status === '待审核' || p.status === '重新执行').slice(0, 5)
  } catch { /* 忽略 */ }
})

const cards = [
  { label: '待处理工单', value: stats.value.pending, color: '#f59e0b' },
  { label: '处理中', value: stats.value.processing, color: '#059669' },
  { label: '待审核提案', value: pendingProps.value.length, color: '#2563eb' },
  { label: '已结工单', value: stats.value.resolved, color: '#64748b' },
]
</script>

<template>
  <div class="page">
    <h2 class="page-title">📊 工作台</h2>
    <p class="page-sub">社区治理 · 今日待办概览</p>

    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
      <div v-for="c in cards" :key="c.label" class="card" style="text-align:center;margin:0;">
        <div style="font-size:1.8rem;font-weight:800;" :style="{ color: c.color }">{{ c.value }}</div>
        <div class="muted" style="font-size:0.85rem;">{{ c.label }}</div>
      </div>
    </div>

    <div class="card" v-if="urgent.length" style="border:2px solid #dc2626;">
      <div style="font-weight:700;color:#dc2626;margin-bottom:10px;">🚨 需要立即处理</div>
      <div v-for="i in urgent" :key="i.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
        <div>
          <b>#{{ i.id }} {{ i.title }}</b>
          <span class="status-pill" style="background:#fef2f2;color:#b91c1c;margin-left:8px;">{{ i.status }}</span>
        </div>
        <n-button size="small" type="primary" @click="router.push('/grid/work-orders')">去处理</n-button>
      </div>
    </div>

    <div class="card" v-if="pendingProps.length">
      <div style="font-weight:700;margin-bottom:10px;">💡 待审核提案</div>
      <div v-for="p in pendingProps" :key="p.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;">
        <span>{{ p.title }} <span class="muted">（{{ p.status }}）</span></span>
        <n-button size="small" type="primary" ghost @click="router.push('/grid/proposals')">审核</n-button>
      </div>
    </div>

    <n-empty v-if="!urgent.length && !pendingProps.length" description="暂无待办，社区运转良好！" />
  </div>
</template>
