<script setup>
// 天气管理：当前天气 + 预警 + 检查任务 + 任务历史 + 社区天气概况 + 异常日志
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../../stores/user'
import { weather, exportApi } from '../../api'
import EIcon from '../../components/EIcon.vue'

const message = useMessage()
const store = useUserStore()
const w = ref(null)
const alerts = ref([])
const tasks = ref([])
const history = ref([])
const overview = ref([])
const exLogs = ref([])
const tab = ref('now')
const confirmTask = ref(null)
const hType = ref('全部')
const hStatus = ref('全部')

const H_TYPES = ['全部', '暴雨', '台风', '高温', '寒潮', '大风', '雷电', '冰雹', '大雾']
const H_STATUS = ['全部', '待检查', '已确认', '超时未确认']

const fHistory = () => {
  let arr = history.value
  if (hType.value !== '全部') arr = arr.filter((h) => h.alert_type === hType.value)
  if (hStatus.value !== '全部') arr = arr.filter((h) => h.status === hStatus.value)
  return arr
}

async function exportTasks() {
  try {
    const blob = await exportApi.weatherTasks()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'weather-tasks.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e.message)
  }
}

onMounted(async () => {
  try { w.value = await weather.current() } catch { /* 忽略 */ }
  try { alerts.value = (await weather.alerts()) || [] } catch { /* 忽略 */ }
  try { tasks.value = (await weather.tasks()) || [] } catch { /* 忽略 */ }
  try { history.value = (await weather.history({ limit: 200 })) || [] } catch { /* 忽略 */ }
  try { overview.value = (await weather.overview({ limit: 50 })) || [] } catch { /* 忽略 */ }
  try { exLogs.value = (await weather.exceptionLogs({ limit: 100 })) || [] } catch { /* 忽略 */ }
  await loadSenior()
})

async function confirm(t) {
  // 弹窗逐项确认（清单由后端按天气类型给出）
  const items = (t.checklist && t.checklist.length ? t.checklist : ['公共设施巡查']).map((item) => ({
    item, status: '已检查',
  }))
  confirmTask.value = { ...t, items, note: '' }
}

// ---- 超时升级通知名单（第 2 层）：原来只有程序化配置、没有入口，这里把它接上 ----
const seniorIds = ref([])
const seniorCandidates = ref([])
const seniorScope = ref('')
const savingSenior = ref(false)

async function loadSenior() {
  try {
    const r = (await weather.seniorManagers()) || {}
    seniorIds.value = r.ids || []
    seniorCandidates.value = r.candidates || []
    seniorScope.value = r.scope || ''
  } catch { /* 读不到就不显示候选，保存仍会被后端 fail-closed 拦住 */ }
}

async function saveSenior() {
  savingSenior.value = true
  try {
    const r = (await weather.setSeniorManagers(seniorIds.value)) || {}
    seniorIds.value = r.ids || []
    message.success(`已保存（${seniorIds.value.length} 人）`)
    await loadSenior()
  } catch (e) {
    message.error(e.message)
  } finally {
    savingSenior.value = false
  }
}

/** 整行可点：手机上只点那个小方块太难点（行高 ≥44px，见 .senior-row 样式）。 */
function toggleSenior(id) {
  const i = seniorIds.value.indexOf(id)
  if (i >= 0) seniorIds.value = seniorIds.value.filter((x) => x !== id)
  else seniorIds.value = [...seniorIds.value, id]
}

async function submitConfirm() {
  const t = confirmTask.value
  if (!t) return
  try {
    await weather.confirmTask(t.id, {
      checker: store.user?.name || '网格员',
      items: t.items,
      note: t.note || '',
    })
    message.success(`任务 #${t.id} 已确认`)
    confirmTask.value = null
    tasks.value = (await weather.tasks()) || []
    history.value = (await weather.history({ limit: 200 })) || []
  } catch (e) {
    message.error(e.message)
  }
}

function remainingText(t) {
  try {
    const created = new Date((t.created_at || '').replace(' ', 'T'))
    const remain = 3 - (Date.now() - created.getTime()) / 3600000
    if (remain < 0) return { text: '已超时', cls: 'background:#fef2f2;color:var(--ink-danger);' }
    if (remain < 1) return { text: `${remain.toFixed(1)}h 内需确认`, cls: 'background:#fef2f2;color:var(--ink-danger);' }
    return { text: `剩余 ${remain.toFixed(1)}h`, cls: 'background:#f0fdf4;color:var(--ink-success);' }
  } catch {
    return { text: '', cls: '' }
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title"><EIcon name="cloud-sun" :size="18" /> 天气管理</h2>
    <p class="page-sub">实时天气 · 极端预警 · 检查任务 · 历史留痕 · 社区概况</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="now" tab="当前与任务">
        <div v-if="w" class="card">
          <b>当前：{{ w.condition }} {{ w.temp_low }}°~{{ w.temp_high }}°</b>
          <span class="muted" style="margin-left:8px;">{{ w.wind }} · <EIcon name="droplet" :size="18" /> {{ w.rain_prob }}%</span>
          <div v-if="w.note" style="color:var(--ink-danger);font-size:0.85rem;margin-top:6px;"><EIcon name="alert" :size="18" /> {{ w.note }}</div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="users" :size="18" /> 超时升级通知名单（第 2 层）</div>
          <div class="muted" style="font-size:0.85rem;margin-bottom:8px;">
            检查任务 3 小时未确认时，先通知本社区负责人；仍无人处理时再通知这里的名单。
            名单**按本社区保存**，候选人只列本社区负责人（跨社区的 id 会被拒绝）。
          </div>
          <div v-if="seniorCandidates.length === 0" class="muted" style="font-size:0.85rem;">
            暂时读不到本社区负责人名单（可能是负责人未登记所属社区）。
          </div>
          <!-- 手机端专项核对（2026-09-29）：n-checkbox 默认只有 22px 高，手指点不准
               → 每个候选人做成一行、行高 ≥44px（含整行可点，不只是那个小方块） -->
          <n-checkbox-group v-else v-model:value="seniorIds" data-senior-managers>
            <div v-for="c in seniorCandidates" :key="c.id" class="senior-row"
                 @click="toggleSenior(c.id)">
              <n-checkbox :value="c.id" :checked="seniorIds.includes(c.id)"
                          @click.stop
                          :label="`${c.name || c.username || ('#' + c.id)}（${c.role || '负责人'}）`" />
            </div>
          </n-checkbox-group>
          <div style="margin-top:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <n-button type="primary" :loading="savingSenior" @click="saveSenior">
              <EIcon name="save" :size="18" /> 保存名单
            </n-button>
            <span class="muted" style="font-size:0.82rem;" data-senior-scope>
              当前生效范围：{{ seniorScope }} · 已选 {{ seniorIds.length }} 人
              <template v-if="seniorIds.length === 0">（空名单 = 超时后无法升级，只会保持最高优先级告警）</template>
            </span>
          </div>
        </div>

        <div class="card" v-if="alerts.length">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="siren" :size="18" /> 生效预警</div>
          <div v-for="a in alerts" :key="a.id">
            {{ a.alert_type }}{{ a.level }}预警 · 生效 {{ (a.effective_time || '').slice(0, 16) }}
          </div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="receipt" :size="18" /> 检查任务（3 小时倒计时）</div>
          <div v-for="t in tasks" :key="t.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
            <div>
              <b>#{{ t.id }} {{ t.alert_type }}{{ t.level }}</b>
              <n-tag size="small" style="margin-left:8px;" :type="t.status === '待检查' ? 'warning' : 'success'">{{ t.status }}</n-tag>
              <span v-if="t.status === '待检查'" class="status-pill" :style="remainingText(t).cls">{{ remainingText(t).text }}</span>
            </div>
            <n-button v-if="t.status === '待检查'" size="small" type="primary" @click="confirm(t)"><EIcon name="checkCircle" :size="18" /> 确认检查</n-button>
            <n-button v-else-if="t.status === '超时未确认'" size="small" type="warning" @click="confirm(t)"><EIcon name="edit" :size="18" /> 补填检查结果</n-button>
          </div>
          <n-empty v-if="tasks.length === 0" description="暂无检查任务" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="history" tab="任务历史">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;align-items:center;">
          <n-select v-model:value="hType" :options="H_TYPES.map(v=>({label:v,value:v}))" style="width:110px;" />
          <n-select v-model:value="hStatus" :options="H_STATUS.map(v=>({label:v,value:v}))" style="width:110px;" />
          <n-button size="small" @click="exportTasks"><EIcon name="arrowDown" :size="18" /> 导出</n-button>
        </div>
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="scroll" :size="18" /> 历史检查任务（含已确认，留痕可追溯）</div>
          <div v-for="h in fHistory()" :key="h.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;display:flex;justify-content:space-between;align-items:center;">
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
          <n-empty v-if="fHistory().length === 0" description="暂无历史任务" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="overview" tab="社区概况">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="community" :size="18" /> 各社区天气概况（预警为当前生效标签）</div>
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

      <n-tab-pane name="logs" tab="异常日志">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="alert" :size="18" /> 系统异常日志（保留 7 天，单独记录不混入业务留痕）</div>
          <div v-for="e in exLogs" :key="e.id" style="padding:8px 0;border-bottom:1px solid #f0f0f0;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <b style="color:var(--ink-danger);">{{ e.module }}：{{ e.error }}</b>
              <span class="muted" style="font-size:0.8rem;">{{ (e.created_at || '').slice(0, 16) }}</span>
            </div>
            <div v-if="e.detail" class="muted" style="font-size:0.8rem;margin-top:2px;">{{ e.detail }}</div>
          </div>
          <n-empty v-if="exLogs.length === 0" description="暂无异常日志" />
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 检查确认弹窗（清单逐项勾选 + 备注） -->
    <n-modal :show="!!confirmTask" @update:show="(v) => { if (!v) confirmTask = null }" preset="card"
             style="width:520px;" :title="confirmTask ? `检查任务 #${confirmTask.id}（${confirmTask.alert_type}${confirmTask.level}）` : ''">
      <template v-if="confirmTask">
        <div v-for="(it, idx) in confirmTask.items" :key="idx" style="padding:8px 0;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;gap:8px;">
          <span style="font-size:0.9rem;">{{ it.item }}</span>
          <n-radio-group v-model:value="it.status" size="small">
            <n-radio value="已检查">已检查</n-radio>
            <n-radio value="正常">正常</n-radio>
            <n-radio value="异常">异常</n-radio>
          </n-radio-group>
        </div>
        <n-input v-model:value="confirmTask.note" placeholder="备注（选填）" style="margin-top:10px;" />
        <div style="margin-top:12px;display:flex;gap:8px;justify-content:flex-end;">
          <n-button @click="confirmTask = null">取消</n-button>
          <n-button type="primary" @click="submitConfirm"><EIcon name="checkCircle" :size="18" /> 提交确认</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
/* 升级名单：整行可点、行高 ≥44px（手指点得准；桌面端也更好点） */
.senior-row {
  display: flex; align-items: center;
  min-height: 44px; padding: 4px 6px; border-radius: 8px;
  cursor: pointer;
}
.senior-row:hover { background: color-mix(in srgb, var(--primary) 8%, transparent); }
</style>
