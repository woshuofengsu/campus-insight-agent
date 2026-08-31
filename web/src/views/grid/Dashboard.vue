<script setup>
// 网格员工作台：待办统计 + 紧急工单 + 待审核提案 + 红黑榜
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues, proposals, agent } from '../../api'

const router = useRouter()
const message = useMessage()

const stats = ref({ total: 0, pending: 0, processing: 0, resolved: 0 })
const urgent = ref([])
const pendingProps = ref([])
const selfRes = ref({ ai_self_resolution_rate: 0, issue_self_resolution_rate: 0, total_dialogs: 0, total_issues: 0 })
const llm = ref({ calls: 0, cost_yuan: 0, cache_hits: 0 })
const board = ref({ red_board: { satisfied_issues: [], good_workers: [], done_proposals: [] }, black_board: { dissatisfied_issues: [], slow_workers: [], sla_breaches: [] } })
const drillOpen = ref(false)
const drill = ref({ summary: { satisfied: 0, dissatisfied: 0, total: 0, rate: 0 }, items: [] })
const drillTitle = ref('')

async function openDrilldown(category = '', assignee = '', satisfaction = '', title = '满意度下钻') {
  drillTitle.value = title
  try {
    drill.value = (await agent.satisfactionDrilldown({ category, assignee, satisfaction })) || drill.value
  } catch { /* 下钻失败不阻塞 */ }
  drillOpen.value = true
}

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
  try {
    board.value = (await agent.board()) || board.value
  } catch { /* 红黑榜失败不阻塞 */ }
  try {
    selfRes.value = (await agent.selfResolution()) || selfRes.value
  } catch { /* 自转率失败不阻塞 */ }
  try {
    llm.value = (await agent.llmUsage()) || llm.value
  } catch { /* LLM 用量失败不阻塞 */ }
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

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
      <div class="card" style="text-align:center;margin:0;border-left:4px solid #2563eb;">
        <div style="font-size:1.8rem;font-weight:800;color:#2563eb;">{{ selfRes.ai_self_resolution_rate }}%</div>
        <div class="muted" style="font-size:0.85rem;">AI 自解决率（{{ selfRes.total_dialogs }} 轮对话，转人工 {{ selfRes.transferred || 0 }}）</div>
      </div>
      <div class="card" style="text-align:center;margin:0;border-left:4px solid #059669;">
        <div style="font-size:1.8rem;font-weight:800;color:#059669;">{{ selfRes.issue_self_resolution_rate }}%</div>
        <div class="muted" style="font-size:0.85rem;">工单社区自办结率（{{ selfRes.done_issues || 0 }}/{{ selfRes.total_issues }}）</div>
      </div>
      <div class="card" style="text-align:center;margin:0;grid-column:span 2;border-left:4px solid #7c3aed;">
        <div style="display:flex;justify-content:space-around;align-items:center;">
          <div>
            <div style="font-size:1.8rem;font-weight:800;color:#7c3aed;">{{ llm.cost_yuan }}</div>
            <div class="muted" style="font-size:0.85rem;">LLM 费用（¥/近7天）</div>
          </div>
          <div>
            <div style="font-size:1.8rem;font-weight:800;color:#7c3aed;">{{ llm.calls || llm.total_calls || 0 }}</div>
            <div class="muted" style="font-size:0.85rem;">LLM 调用次数</div>
          </div>
          <div>
            <div style="font-size:1.8rem;font-weight:800;color:#059669;">{{ llm.cache_hits }}</div>
            <div class="muted" style="font-size:0.85rem;">缓存命中</div>
          </div>
        </div>
        <div class="muted" style="font-size:0.8rem;margin-top:6px;">规则引擎优先 · LLM 按需（分级路由降本）</div>
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

    <!-- 红黑榜（P2-B4-01） -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;">
      <div class="card" style="border:1px solid #dcfce7;margin:0;">
        <div style="font-weight:700;color:#059669;margin-bottom:10px;">🏆 红榜 · 值得表扬</div>
        <div v-if="board.red_board.satisfied_issues.length">
          <div style="font-size:0.85rem;color:#64748b;margin-bottom:4px;">近期满意工单</div>
          <div v-for="i in board.red_board.satisfied_issues.slice(0,3)" :key="'ri'+i.id"
               style="padding:6px 0;border-bottom:1px solid #f0fdf4;font-size:0.9rem;cursor:pointer;"
               @click="openDrilldown('', '', '满意', '红榜 · 满意工单下钻')">
            #{{ i.id }} {{ i.title }} <span class="muted">（{{ i.assignee_name || '—' }} · {{ i.hours ?? '?' }}h）</span>
          </div>
        </div>
        <div v-if="board.red_board.good_workers.length" style="margin-top:8px;">
          <div style="font-size:0.85rem;color:#64748b;margin-bottom:4px;">高效网格员</div>
          <div v-for="w in board.red_board.good_workers.slice(0,3)" :key="'rw'+w.name"
               style="padding:6px 0;font-size:0.9rem;">
            👍 {{ w.name }} · 解决 {{ w.solved }} 单 · 满意 {{ w.satisfied }}
            <span class="muted" v-if="w.avg_hours">（均 {{ w.avg_hours }}h）</span>
          </div>
        </div>
        <div v-if="!board.red_board.satisfied_issues.length && !board.red_board.good_workers.length" class="muted" style="font-size:0.9rem;">暂无红榜数据</div>
      </div>
      <div class="card" style="border:1px solid #fee2e2;margin:0;">
        <div style="font-weight:700;color:#dc2626;margin-bottom:10px;">⚠️ 黑榜 · 需要改进</div>
        <div v-if="board.black_board.dissatisfied_issues.length">
          <div style="font-size:0.85rem;color:#64748b;margin-bottom:4px;">不满意工单</div>
          <div v-for="i in board.black_board.dissatisfied_issues.slice(0,3)" :key="'bi'+i.id"
               style="padding:6px 0;border-bottom:1px solid #fef2f2;font-size:0.9rem;cursor:pointer;"
               @click="openDrilldown('', '', '不满意', '黑榜 · 不满意工单下钻')">
            #{{ i.id }} {{ i.title }} <span class="muted">{{ i.satisfaction_reason || '' }}</span>
          </div>
        </div>
        <div v-if="board.black_board.sla_breaches.length" style="margin-top:8px;">
          <div style="font-size:0.85rem;color:#64748b;margin-bottom:4px;">SLA 超时</div>
          <div v-for="b in board.black_board.sla_breaches.slice(0,3)" :key="'sl'+b.id"
               style="padding:6px 0;font-size:0.9rem;">
            ⏰ #{{ b.id }} {{ b.title }} <span class="muted">（{{ b.level }}）</span>
          </div>
        </div>
        <div v-if="!board.black_board.dissatisfied_issues.length && !board.black_board.sla_breaches.length" class="muted" style="font-size:0.9rem;">暂无黑榜数据</div>
      </div>
    </div>

    <n-empty v-if="!urgent.length && !pendingProps.length" description="暂无待办，社区运转良好！" />

    <n-drawer v-model:show="drillOpen" placement="right" :width="360">
      <n-drawer-content :title="drillTitle" :native-scrollbar="false">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">
          <div class="card" style="text-align:center;margin:0;">
            <div style="font-size:1.4rem;font-weight:800;color:#059669;">{{ drill.summary.satisfied }}</div>
            <div class="muted" style="font-size:0.8rem;">满意</div>
          </div>
          <div class="card" style="text-align:center;margin:0;">
            <div style="font-size:1.4rem;font-weight:800;color:#dc2626;">{{ drill.summary.dissatisfied }}</div>
            <div class="muted" style="font-size:0.8rem;">不满意</div>
          </div>
          <div class="card" style="text-align:center;margin:0;">
            <div style="font-size:1.4rem;font-weight:800;color:#2563eb;">{{ drill.summary.total }}</div>
            <div class="muted" style="font-size:0.8rem;">总数</div>
          </div>
        </div>
        <n-empty v-if="!drill.items.length" description="暂无明细数据" />
        <div v-for="it in drill.items" :key="it.id" style="padding:8px 0;border-bottom:1px solid var(--border);">
          <b>#{{ it.id }} {{ it.title }}</b>
          <div class="muted" style="font-size:0.85rem;margin-top:2px;">
            {{ it.assignee_name || '—' }} · 满意度 {{ it.satisfaction }} · {{ (it.resolved_at || '') .slice(0, 16) }}
          </div>
          <div v-if="it.satisfaction_reason" class="muted" style="font-size:0.8rem;margin-top:2px;">原因：{{ it.satisfaction_reason }}</div>
        </div>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>
