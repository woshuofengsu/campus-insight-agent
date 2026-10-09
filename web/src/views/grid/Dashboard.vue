<script setup>
// 网格员工作台：待办统计 + 紧急工单 + 待审核提案 + 红黑榜
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues, proposals, agent } from '../../api'
// v3：不再用 CountUp（工作台要的是"现在几个"，数字跳动只是噪音）
import EIcon from '../../components/EIcon.vue'

const router = useRouter()
const message = useMessage()

const stats = ref({ total: 0, pending: 0, processing: 0, resolved: 0 })
const todo = ref([])
const urgent = ref([])
const pendingProps = ref([])
const selfRes = ref({ ai_self_resolution_rate: 0, issue_self_resolution_rate: 0, total_dialogs: 0, total_issues: 0 })
const llm = ref({ calls: 0, cost_yuan: 0, cache_hits: 0 })
const board = ref({ red_board: { satisfied_issues: [], good_workers: [], done_proposals: [] }, black_board: { dissatisfied_issues: [], slow_workers: [], sla_breaches: [] } })
// 治理指标（v4 §5 壁垒层四）：重复报修率 + 转人工原因分布（后端只算本社区）
const gov = ref({ repeat: { rate: 0, total: 0, repeat_groups: 0, top: [] },
                  transfer: { total: 0, by_reason: {}, by_source: {} } })
// 治理情景模拟器（v4 第 5 阶段）：只读估算——诉求量涨 X% 要多少工时、折算几个人
const sim = ref({ label: '', disclaimer: '', formulas: [], sample: {}, scenario: {},
                  avg_minutes: {}, available_hours: {}, projected: {}, workload: {}, notes: [] })
// 注意：窗口与增长率**不用 `n-input-number`**：它内部的 +/- 小按钮只有 18px 宽，
// 会踩手机端 44px 热区下限（`mobile_audit` 实测抓到 4 处，dev-log 五十三 记过同一个坑）。
// 窗口改成下拉预设（选项本身就是大热区），增长率用普通输入框 + 数字键盘。
const SIM_DAYS = [7, 30, 90, 180, 365].map((d) => ({ label: `近 ${d} 天`, value: d }))
const simGrowth = ref('20')
const simDays = ref(30)
const simBusy = ref(false)
const simCfg = ref({ available_hours: null, avg_minutes: null })
const simCfgOpen = ref(false)

function _num(v) {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

async function runSim() {
  simBusy.value = true
  try {
    sim.value = (await agent.governanceSimulation({
      days: _num(simDays.value) || 30, growth_pct: _num(simGrowth.value),
    })) || sim.value
    simCfg.value = { available_hours: sim.value.available_hours?.value ?? null,
                     avg_minutes: sim.value.avg_minutes?.value ?? null }
  } catch (e) { message.error(e.message) } finally { simBusy.value = false }
}

async function saveSimCfg() {
  try {
    const body = {}
    if (simCfg.value.available_hours !== null && simCfg.value.available_hours !== '') {
      body.available_hours = _num(simCfg.value.available_hours)
    }
    if (simCfg.value.avg_minutes !== null && simCfg.value.avg_minutes !== '') {
      body.avg_minutes = _num(simCfg.value.avg_minutes)
    }
    await agent.saveSimSettings(body)
    message.success('已保存（只对您所在社区生效）')
    simCfgOpen.value = false
    await runSim()
  } catch (e) { message.error(e.message) }
}

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
    gov.value = (await agent.governanceMetrics({ days: 30 })) || gov.value
  } catch { /* 指标失败不阻塞工作台 */ }
  await runSim()
  try {
    const all = (await issues.list()) || []
    stats.value = {
      total: all.length,
      pending: all.filter((i) => i.status === '待审核' || i.status === '已审核待派单').length,
      processing: all.filter((i) => i.status === '处理中' || i.status === '已派单').length,
      resolved: all.filter((i) => i.status === '处理结束').length,
      // v3：任务书 §六 要求工作台第一层固定为「待研判 / 待处理 / 待回访 / 已完成」——
      // 这四个数**从同一份工单列表算出来**（不新增接口、不编数字），口径写在标签下面：
      //   待研判 = 等我审核判断（含退回补充）· 待处理 = 已通过、等派单/处理中
      //   待回访 = 已处理完、等居民反馈 · 已完成 = 处理结束/已关闭
      triage: all.filter((i) => ['待审核', '退回补充信息'].includes(i.status)).length,
      todo: all.filter((i) => ['已审核待派单', '已派单', '处理中', '待协商'].includes(i.status)).length,
      revisit: all.filter((i) => i.status === '待居民反馈').length,
      done: all.filter((i) => ['处理结束', '已关闭'].includes(i.status)).length,
    }
    urgent.value = all.filter((i) => i.urgency === '紧急' && !['处理结束', '已关闭', '已撤回'].includes(i.status)).slice(0, 5)
    const active = all.filter((i) => !['处理结束', '已关闭', '已撤回'].includes(i.status))
    todo.value = active.sort((a, b) => {
      const overdue = Number(Boolean(b.overdue)) - Number(Boolean(a.overdue))
      if (overdue) return overdue
      const rank = { 紧急: 0, 中等: 1, 一般: 2, 普通: 3 }
      return (rank[a.urgency] ?? 9) - (rank[b.urgency] ?? 9)
    }).slice(0, 8)
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

// 注意：必须是 computed —— 普通数组在 setup 期求值，会永久锁死在初始的 0，
// 导致四个统计卡恒显示 0（数据在 onMounted 才回来）。
// v3：任务书 §六 要求工作台第一层固定为「待研判 / 待处理 / 待回访 / 已完成」四格，
// 每格下面写一句口径（工作台不能让人猜"这个数字是什么"）。
const cards = computed(() => [
  { label: '待研判', value: stats.value.triage, hint: '等我审核判断', icon: 'inbox', to: '/grid/work-orders' },
  { label: '待处理', value: stats.value.todo, hint: '已通过，等派单/处理', icon: 'wrench', to: '/grid/work-orders' },
  { label: '待回访', value: stats.value.revisit, hint: '等居民反馈', icon: 'hand', to: '/grid/work-orders' },
  { label: '已完成', value: stats.value.done, hint: '处理结束/已关闭', icon: 'checkCircle', to: '/grid/work-orders' },
])
</script>

<template>
  <div class="page">
    <h2 class="page-title"><EIcon name="chart" :size="18" /> 工作台</h2>
    <p class="page-sub">社区治理 · 今日待办概览</p>

    <!-- 第一层：待研判 / 待处理 / 待回访 / 已完成（任务书 §六）。数字**静态显示**：
         工作台要的是"现在几个"，不该"跳数"（v2 的 CountUp 已移除）。 -->
    <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;">
      <div v-for="c in cards" :key="c.label" class="card entry-tile"
           style="text-align:center;margin:0;border-radius:var(--r-card);padding:14px 10px;"
           @click="router.push(c.to)">
        <div class="entry-icon" style="display:flex;justify-content:center;color:var(--muted);margin-bottom:2px;"><EIcon :name="c.icon" :size="22" /></div>
        <div style="font-size:2rem;font-weight:800;line-height:1.15;color:var(--text);">{{ c.value }}</div>
        <div style="font-weight:700;font-size:0.95rem;">{{ c.label }}</div>
        <div class="muted" style="font-size:0.82rem;margin-top:2px;">{{ c.hint }}</div>
      </div>
    </div>

    <div class="card todo-panel" v-if="todo.length">
      <div class="todo-head">
        <div>
          <div class="todo-title"><EIcon name="inbox" :size="18" /> 先处理这些</div>
          <div class="muted todo-sub">按「超时 → 紧急 → 一般」排好序：超时和紧急的排在最前面，最近的变动也在这一列</div>
        </div>
        <n-button size="small" type="primary" ghost @click="router.push('/grid/work-orders')">进入工单台</n-button>
      </div>
      <div class="todo-list">
        <button v-for="i in todo" :key="i.id" class="todo-row" @click="router.push('/grid/work-orders')">
          <span class="todo-priority" :class="{ danger: i.overdue || i.urgency === '紧急' }">{{ i.overdue ? '超时' : i.urgency || '一般' }}</span>
          <span class="todo-content"><b>{{ i.issue_code ? i.issue_code : ('#' + i.id) }} {{ i.title }}</b><span class="muted">{{ i.location || '未标位置' }} · {{ i.status }}</span></span>
          <span class="muted">查看 ›</span>
        </button>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:16px;">
      <div class="card" style="text-align:center;margin:0;border-left:4px solid #2563eb;">
        <div style="font-size:1.8rem;font-weight:800;color:var(--ink-info);">{{ selfRes.ai_self_resolution_rate }}%</div>
        <div class="muted" style="font-size:0.85rem;">AI 自解决率（{{ selfRes.total_dialogs }} 轮对话，转人工 {{ selfRes.transferred || 0 }}）</div>
      </div>
      <div class="card" style="text-align:center;margin:0;border-left:4px solid #059669;">
        <div style="font-size:1.8rem;font-weight:800;color:var(--ink-success);">{{ selfRes.issue_self_resolution_rate }}%</div>
        <div class="muted" style="font-size:0.85rem;">工单社区自办结率（{{ selfRes.done_issues || 0 }}/{{ selfRes.total_issues }}）</div>
      </div>
      <div class="card" style="text-align:center;margin:0;grid-column:span 2;border-left:4px solid #7c3aed;">
        <div style="display:flex;justify-content:space-around;align-items:center;">
          <div>
            <div style="font-size:1.8rem;font-weight:800;color:var(--ink-purple);">{{ llm.cost_yuan }}</div>
            <div class="muted" style="font-size:0.85rem;">LLM 费用（¥/近7天）</div>
          </div>
          <div>
            <div style="font-size:1.8rem;font-weight:800;color:var(--ink-purple);">{{ llm.calls || llm.total_calls || 0 }}</div>
            <div class="muted" style="font-size:0.85rem;">LLM 调用次数</div>
          </div>
          <div>
            <div style="font-size:1.8rem;font-weight:800;color:var(--ink-success);">{{ llm.cache_hits }}</div>
            <div class="muted" style="font-size:0.85rem;">缓存命中</div>
          </div>
        </div>
        <div class="muted" style="font-size:0.8rem;margin-top:6px;">规则引擎优先 · LLM 按需（分级路由降本）</div>
      </div>
    </div>

    <div class="card" v-if="urgent.length" style="border:2px solid #dc2626;">
      <div style="font-weight:700;color:var(--ink-danger);margin-bottom:10px;"><EIcon name="siren" :size="18" /> 需要立即处理</div>
      <div v-for="i in urgent" :key="i.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
        <div>
          <b>#{{ i.id }} {{ i.title }}</b>
          <span class="status-pill" style="background:#fef2f2;color:var(--ink-danger);margin-left:8px;">{{ i.status }}</span>
        </div>
        <n-button size="small" type="primary" @click="router.push('/grid/work-orders')">去处理</n-button>
      </div>
    </div>

    <div class="card" v-if="pendingProps.length">
      <div style="font-weight:700;margin-bottom:10px;"><EIcon name="bulb" :size="18" /> 待审核提案</div>
      <div v-for="p in pendingProps" :key="p.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;">
        <span>{{ p.title }} <span class="muted">（{{ p.status }}）</span></span>
        <n-button size="small" type="primary" ghost @click="router.push('/grid/proposals')">审核</n-button>
      </div>
    </div>

    <!-- 红黑榜（P2-B4-01） -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px;">
      <div class="card" style="border:1px solid #dcfce7;margin:0;">
        <div style="font-weight:700;color:var(--ink-success);margin-bottom:10px;"><EIcon name="trophy" :size="18" /> 红榜 · 值得表扬</div>
        <div v-if="board.red_board.satisfied_issues.length">
          <div style="font-size:0.85rem;color:var(--muted);margin-bottom:4px;">近期满意工单</div>
          <div v-for="i in board.red_board.satisfied_issues.slice(0,3)" :key="'ri'+i.id"
               style="padding:6px 0;border-bottom:1px solid #f0fdf4;font-size:0.9rem;cursor:pointer;"
               @click="openDrilldown('', '', '满意', '红榜 · 满意工单下钻')">
            #{{ i.id }} {{ i.title }} <span class="muted">（{{ i.assignee_name || '—' }} · {{ i.hours ?? '?' }}h）</span>
          </div>
        </div>
        <div v-if="board.red_board.good_workers.length" style="margin-top:8px;">
          <div style="font-size:0.85rem;color:var(--muted);margin-bottom:4px;">高效网格员</div>
          <div v-for="w in board.red_board.good_workers.slice(0,3)" :key="'rw'+w.name"
               style="padding:6px 0;font-size:0.9rem;">
            <EIcon name="thumb-up" :size="18" /> {{ w.name }} · 解决 {{ w.solved }} 单 · 满意 {{ w.satisfied }}
            <span class="muted" v-if="w.avg_hours">（均 {{ w.avg_hours }}h）</span>
          </div>
        </div>
        <div v-if="!board.red_board.satisfied_issues.length && !board.red_board.good_workers.length" class="muted" style="font-size:0.9rem;">暂无红榜数据</div>
      </div>
      <div class="card" style="border:1px solid #fee2e2;margin:0;">
        <div style="font-weight:700;color:var(--ink-danger);margin-bottom:10px;"><EIcon name="alert" :size="18" /> 黑榜 · 需要改进</div>
        <div v-if="board.black_board.dissatisfied_issues.length">
          <div style="font-size:0.85rem;color:var(--muted);margin-bottom:4px;">不满意工单</div>
          <div v-for="i in board.black_board.dissatisfied_issues.slice(0,3)" :key="'bi'+i.id"
               style="padding:6px 0;border-bottom:1px solid #fef2f2;font-size:0.9rem;cursor:pointer;"
               @click="openDrilldown('', '', '不满意', '黑榜 · 不满意工单下钻')">
            #{{ i.id }} {{ i.title }} <span class="muted">{{ i.satisfaction_reason || '' }}</span>
          </div>
        </div>
        <div v-if="board.black_board.sla_breaches.length" style="margin-top:8px;">
          <div style="font-size:0.85rem;color:var(--muted);margin-bottom:4px;">SLA 超时</div>
          <div v-for="b in board.black_board.sla_breaches.slice(0,3)" :key="'sl'+b.id"
               style="padding:6px 0;font-size:0.9rem;">
            <EIcon name="clock" :size="18" /> #{{ b.id }} {{ b.title }} <span class="muted">（{{ b.level }}）</span>
          </div>
        </div>
        <div v-if="!board.black_board.dissatisfied_issues.length && !board.black_board.sla_breaches.length" class="muted" style="font-size:0.9rem;">暂无黑榜数据</div>
      </div>
    </div>

    <!-- 治理指标（v4 §5 壁垒层四）：重复报修率 + 转人工原因分布 -->
    <div class="card" data-gov-metrics style="margin-top:16px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div style="font-weight:700;"><EIcon name="chart-line" :size="18" /> 治理指标（近 30 天 · 仅本社区）</div>
        <span class="muted" style="font-size:0.8rem;">重复报修＝同一人同一分类<b>跨天</b>再报（同一分钟连点不算）</span>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px;">
        <div>
          <div style="font-size:1.7rem;font-weight:800;">{{ gov.repeat.rate }}%</div>
          <div class="muted" style="font-size:0.85rem;">
            重复报修率 · {{ gov.repeat.repeat_groups }} 组 / 共 {{ gov.repeat.total }} 单
          </div>
          <div v-for="t in gov.repeat.top.slice(0,3)" :key="'rp'+t.reporter_id+t.category"
               class="muted" style="font-size:0.8rem;margin-top:2px;">
            #{{ t.reporter_id }} · {{ t.category }} · {{ t.days }} 天里报了 {{ t.count }} 次
          </div>
          <div v-if="!gov.repeat.top.length" class="muted" style="font-size:0.8rem;margin-top:2px;">近 30 天没有重复报修</div>
        </div>
        <div>
          <div style="font-size:1.7rem;font-weight:800;">{{ gov.transfer.total }}</div>
          <div class="muted" style="font-size:0.85rem;">
            转人工 · 处理包 {{ gov.transfer.by_source['处理包'] || 0 }} · 政策问答 {{ gov.transfer.by_source['政策问答'] || 0 }}
          </div>
          <div v-for="(n, k) in gov.transfer.by_reason" :key="'tr'+k" style="margin-top:2px;font-size:0.82rem;"
               :class="n ? '' : 'muted'">
            {{ k }}：{{ n }}
          </div>
        </div>
      </div>
    </div>

    <!-- 治理情景模拟器（v4 第 5 阶段）：**只读**估算——人还是这么几个人，量涨上来怎么办 -->
    <div class="card" data-gov-sim style="margin-top:16px;">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
        <div style="font-weight:700;"><EIcon name="chart-line" :size="18" /> 治理情景模拟器
          <span class="muted" style="font-weight:400;font-size:0.82rem;">（{{ sim.label || '情景估算' }} · 仅本社区）</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <n-select v-model:value="simDays" :options="SIM_DAYS" size="small" style="width:132px;"
                    data-sim-days />
          <span class="muted" style="font-size:0.82rem;">诉求量增长 %</span>
          <n-input v-model:value="simGrowth" size="small" inputmode="numeric" placeholder="如 20"
                   style="width:96px;" data-sim-growth />
          <n-button size="small" type="primary" :loading="simBusy" @click="runSim"
                    data-sim-run>计算</n-button>
          <n-button size="small" @click="simCfgOpen = true" data-sim-config>参数</n-button>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:12px;">
        <div class="card" style="margin:0;">
          <div style="font-size:1.5rem;font-weight:800;" data-sim-sample>{{ sim.sample.issues ?? 0 }}</div>
          <div class="muted" style="font-size:0.82rem;">
            样本量 · 近 {{ sim.days || simDays }} 天本社区工单
            <template v-if="sim.sample.resolved">（已办结 {{ sim.sample.resolved }} 单）</template>
          </div>
        </div>
        <div class="card" style="margin:0;">
          <div style="font-size:1.5rem;font-weight:800;" data-sim-new>
            {{ sim.projected.new >= 0 ? '+' : '' }}{{ sim.projected.new ?? 0 }}
          </div>
          <div class="muted" style="font-size:0.82rem;">
            预计新增 · 假设增长 {{ sim.scenario.growth_pct ?? 0 }}%（不是预测值）
          </div>
        </div>
        <div class="card" style="margin:0;">
          <div style="font-size:1.5rem;font-weight:800;" data-sim-total>{{ sim.projected.total ?? 0 }}</div>
          <div class="muted" style="font-size:0.82rem;">预计总量 · 样本量 + 预计新增</div>
        </div>
        <div class="card" style="margin:0;">
          <div style="font-size:1.5rem;font-weight:800;" data-sim-hours>
            {{ sim.workload.total_hours === null || sim.workload.total_hours === undefined ? '—' : sim.workload.total_hours + ' 小时' }}
          </div>
          <div class="muted" style="font-size:0.82rem;">
            预计总工时 · 平均处理时长
            {{ sim.avg_minutes.value ? sim.avg_minutes.value + ' 分钟' : '未取得' }}
            <template v-if="sim.avg_minutes.source">（{{ sim.avg_minutes.source }}）</template>
          </div>
        </div>
        <div class="card" style="margin:0;">
          <div style="font-size:1.5rem;font-weight:800;" data-sim-staffing>
            {{ sim.workload.staffing === null || sim.workload.staffing === undefined ? '—' : sim.workload.staffing + ' 人' }}
          </div>
          <div class="muted" style="font-size:0.82rem;">
            折算人手 · 预计总工时 ÷ 人均可用工时
            <template v-if="sim.available_hours.value">（{{ sim.available_hours.value }} 小时/人）</template>
          </div>
        </div>
      </div>

      <!-- 「算不出来」的地方必须说清楚原因：不许拿默认值硬算出一个像样的人手数 -->
      <div v-if="sim.notes && sim.notes.length" class="sim-notes" data-sim-notes>
        <div v-for="(n, i) in sim.notes" :key="'sn' + i">
          <EIcon name="info" :size="16" /> {{ n }}
        </div>
      </div>

      <!-- 公式**默认展开**：这是"可现场复算"的凭证，藏起来就等于黑箱 -->
      <details class="sim-formulas" data-sim-formulas open>
        <summary>公式（结果按下面四条算出来，可现场复算）</summary>
        <div v-for="(f, i) in (sim.formulas || [])" :key="'sf' + i" style="margin-top:4px;">{{ i + 1 }}. {{ f }}</div>
        <div class="muted" style="margin-top:6px;font-size:0.8rem;">{{ sim.disclaimer }}</div>
      </details>
    </div>

    <n-drawer v-model:show="simCfgOpen" placement="right" :width="360">
      <n-drawer-content title="情景参数（只对您所在社区生效）" :native-scrollbar="false">
        <div class="muted" style="font-size:0.85rem;margin-bottom:12px;">
          这两项都是"算账用的参数"，不是业务数据：人均可用工时是"我们社区有几个人、每人能投多少时间"，
          所以按社区分开配，不跨社区共用。
        </div>
        <div style="margin-bottom:12px;">
          <div style="font-size:0.9rem;margin-bottom:4px;">人均可用工时（小时/人/窗口期）</div>
          <n-input v-model:value="simCfg.available_hours" inputmode="decimal" placeholder="如 8"
                   data-sim-cfg-hours />
          <div class="muted" style="font-size:0.78rem;margin-top:2px;">不填 → 折算人手不给数字（会明确写"未配置"）</div>
        </div>
        <div style="margin-bottom:12px;">
          <div style="font-size:0.9rem;margin-bottom:4px;">平均处理时长（分钟 · 每条诉求占用的人工时长）</div>
          <n-input v-model:value="simCfg.avg_minutes" inputmode="numeric" placeholder="如 40"
                   data-sim-cfg-minutes />
          <div class="muted" style="font-size:0.78rem;margin-top:2px;">不填 → 用已办结工单的办结耗时（含等待，会高估工时，页面上会提醒）</div>
        </div>
        <n-button type="primary" @click="saveSimCfg" data-sim-cfg-save>保存</n-button>
      </n-drawer-content>
    </n-drawer>

    <n-empty v-if="!urgent.length && !pendingProps.length" description="暂无待办，社区运转良好！" />

    <n-drawer v-model:show="drillOpen" placement="right" :width="360">
      <n-drawer-content :title="drillTitle" :native-scrollbar="false">
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:12px;">
          <div class="card" style="text-align:center;margin:0;">
            <div style="font-size:1.4rem;font-weight:800;color:var(--ink-success);">{{ drill.summary.satisfied }}</div>
            <div class="muted" style="font-size:0.8rem;">满意</div>
          </div>
          <div class="card" style="text-align:center;margin:0;">
            <div style="font-size:1.4rem;font-weight:800;color:var(--ink-danger);">{{ drill.summary.dissatisfied }}</div>
            <div class="muted" style="font-size:0.8rem;">不满意</div>
          </div>
          <div class="card" style="text-align:center;margin:0;">
            <div style="font-size:1.4rem;font-weight:800;color:var(--ink-info);">{{ drill.summary.total }}</div>
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

<style scoped>
.todo-panel { margin-bottom:16px; }
.todo-head { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:10px; }
.todo-title { font-size:1.1rem; font-weight:750; }
.todo-sub { font-size:0.8rem; margin-top:2px; }
.todo-list { border-top:1px solid var(--border); }
.todo-row { width:100%; display:flex; align-items:center; gap:10px; padding:10px 0; border:0; border-bottom:1px solid var(--border); background:transparent; color:inherit; text-align:left; cursor:pointer; }
.todo-row:hover { background:var(--primary-light); }
.todo-priority { min-width:42px; padding:3px 5px; border-radius:6px; background:var(--primary-light); color:var(--primary-light-ink); font-size:0.78rem; text-align:center; }
.todo-priority.danger { background:color-mix(in srgb, var(--st-danger) 14%, transparent); color:var(--ink-danger); }
.todo-content { display:flex; flex:1; flex-direction:column; gap:3px; min-width:0; }
.todo-content b { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.todo-content .muted { font-size:0.8rem; }
@media (max-width: 720px) { .todo-head { align-items:flex-start; flex-direction:column; } .todo-row { gap:6px; } }
/* 情景模拟器：「算不出来」的原因与公式都要看得见（只读估算，不能是黑箱）
   注意：原来写 `background:var(--panel-lemon)`（变量不存在）→ 提示块一直没底色；
   2026-10-06 由 ui_style_audit 的"未定义变量"判据抓出，改用令牌。 */
.sim-notes { margin-top:12px; padding:10px 12px; border-radius:var(--r-xs); background:var(--accent-light); font-size:0.86rem; display:flex; flex-direction:column; gap:5px; }
.sim-formulas { margin-top:12px; font-size:0.85rem; }
.sim-formulas summary { cursor:pointer; color:var(--ink-info); }
</style>
