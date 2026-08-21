<script setup>
// 工单管理：审核/派单/处理/解决/关闭/协商/转出/确认补充/改分类（真实输入 + 筛选 + 时限 + 导出 + 安全提醒）
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues, exportApi } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const expanded = ref({})
const tab = ref('orders')
const safety = ref([])
// 筛选
const statusFilter = ref('全部')
const catFilter = ref('全部')
const urgFilter = ref('全部')
const keyword = ref('')
// 操作输入（按工单 id 存）
const op = ref({}) // { [id]: { opinion, assignee, phone, note, reason, cat, noPhoto, negReason } }

const STATUS_OPTIONS = ['全部', '待审核', '退回补充信息', '已审核待派单', '已派单', '处理中', '待居民反馈', '处理结束', '已关闭', '已撤回', '待协商', '已转出']
const CAT_OPTIONS = ['全部', '公共设施', '水电燃气', '环境卫生', '房屋维修', '绿化养护', '治安消防', '其他']
const URG_OPTIONS = ['全部', '紧急', '中等', '一般', '普通']

const filtered = computed(() => {
  let arr = list.value
  if (statusFilter.value !== '全部') arr = arr.filter((i) => i.status === statusFilter.value)
  if (catFilter.value !== '全部') arr = arr.filter((i) => i.category === catFilter.value)
  if (urgFilter.value !== '全部') arr = arr.filter((i) => i.urgency === urgFilter.value)
  if (keyword.value) {
    const kw = keyword.value.toLowerCase()
    arr = arr.filter((i) => [i.title, i.location, i.description, i.reporter_name].some((s) => (s || '').toLowerCase().includes(kw)))
  }
  return arr
})

async function load() {
  loading.value = true
  try { list.value = (await issues.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
async function loadSafety() {
  try { safety.value = (await issues.safetyReminders()) || [] } catch { /* 忽略 */ }
}
onMounted(() => { load(); loadSafety() })

function opOf(i) {
  if (!op.value[i.id]) op.value[i.id] = {}
  return op.value[i.id]
}

function deadlineText(i) {
  if (i.status === '处理结束' || i.status === '已关闭' || i.status === '已撤回' || i.status === '已转出') return ''
  if (i.remaining_hours == null) return ''
  if (i.overdue) return `⏰ 已超时 ${Math.abs(i.remaining_hours).toFixed(1)}h`
  return `⏳ 剩余 ${i.remaining_hours.toFixed(1)}h`
}

async function act(i, data, okMsg) {
  try {
    await issues.action(i.id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}

// 必填校验：审核退回意见 / 派单人员 / 处理结果 / 关闭原因
function requireValue(i, field, tip) {
  const v = (opOf(i)[field] || '').trim()
  if (!v) {
    message.warning(tip)
    return null
  }
  return v
}

async function exportIssues() {
  try {
    const blob = await exportApi.issues()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'issues.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🔧 工单管理</h2>
    <p class="page-sub">共 {{ list.length }} 条工单 · 超时按紧急程度计时（紧急1h/中等4h/一般24h/普通48h）</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="orders" tab="工单管理">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
          <n-select v-model:value="statusFilter" :options="STATUS_OPTIONS.map(v=>({label:v,value:v}))" style="width:150px;" />
          <n-select v-model:value="catFilter" :options="CAT_OPTIONS.map(v=>({label:v,value:v}))" style="width:130px;" />
          <n-select v-model:value="urgFilter" :options="URG_OPTIONS.map(v=>({label:v,value:v}))" style="width:110px;" />
          <n-input v-model:value="keyword" placeholder="搜索标题/地址/描述/报修人" clearable style="flex:1;min-width:200px;" />
          <n-button size="small" @click="load">刷新</n-button>
          <n-button size="small" @click="exportIssues">⬇️ 导出</n-button>
        </div>

        <n-spin :show="loading">
          <div v-for="i in filtered" :key="i.id" class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" @click="expanded[i.id] = !expanded[i.id]">
              <div>
                <b>#{{ i.id }} {{ i.title }}</b>
                <span class="status-pill" :style="{
                  background: i.status === '处理结束' ? '#ecfdf5' : i.status === '已关闭' ? '#f5f5f5' : i.status === '已撤回' ? '#f5f5f5' : i.status === '已超时' || (i.overdue && i.status !== '处理结束') ? '#fef2f2' : '#eef2ff',
                  color: i.status === '处理结束' ? '#059669' : i.status === '已关闭' || i.status === '已撤回' ? '#888' : i.status === '已超时' || (i.overdue && i.status !== '处理结束') ? '#dc2626' : '#4f46e5',
                }" style="margin-left:8px;">{{ i.status }}</span>
                <span v-if="i.urgency === '紧急'" class="status-pill" style="background:#fef2f2;color:#dc2626;margin-left:4px;">🔴 紧急</span>
                <span v-if="i.is_violation" class="status-pill" style="background:#fef2f2;color:#dc2626;margin-left:4px;">🚫 违规标记</span>
                <span v-if="i.non_community_responsibility" class="status-pill" style="background:#fffbeb;color:#b45309;margin-left:4px;">🏗️ 第三方施工</span>
              </div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span v-if="deadlineText(i)" class="status-pill" :style="i.overdue ? 'background:#fef2f2;color:#dc2626;' : 'background:#f0fdf4;color:#16a34a;'">{{ deadlineText(i) }}</span>
                <span class="muted" style="font-size:0.85rem;">{{ expanded[i.id] ? '收起 ▲' : '展开 ▼' }}</span>
              </div>
            </div>
            <div class="muted" style="font-size:0.85rem;margin-top:4px;">
              {{ i.issue_type }} · {{ i.category }} · 📍{{ i.location }} · 报修人 {{ i.reporter_name }}
              <span v-if="i.assignee_name"> · 👷 {{ i.assignee_name }}</span>
              <span v-if="i.is_agent_report && i.agent_name"> · 🙋 代报：{{ i.agent_name }}（{{ i.agent_relation }}）</span>
            </div>

            <div v-if="expanded[i.id]" style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px;">
              <div class="muted" style="font-size:0.9rem;">📝 {{ i.description }}</div>
              <div v-if="i.resolve_note" class="muted" style="font-size:0.85rem;margin-top:6px;">📋 处理结果：{{ i.resolve_note }}</div>

              <div style="margin-top:12px;">
                <!-- 审核 -->
                <template v-if="['待审核', '退回补充信息'].includes(i.status)">
                  <n-input v-model:value="opOf(i).opinion" placeholder="审核意见（退回必填）" size="small" style="margin-bottom:8px;" />
                  <div style="display:flex;gap:8px;">
                    <n-button size="small" type="success" @click="act(i, { action: 'audit', approve: true, opinion: opOf(i).opinion || '同意' }, '已审核通过')">✅ 审核通过</n-button>
                    <n-button size="small" type="warning" @click="requireValue(i, 'opinion', '退回必须填写审核意见') && act(i, { action: 'audit', approve: false, opinion: opOf(i).opinion }, '已退回')">↩️ 退回补充</n-button>
                  </div>
                </template>
                <!-- 派单 -->
                <template v-if="['已审核待派单', '已派单'].includes(i.status)">
                  <div style="display:flex;gap:8px;margin-bottom:8px;">
                    <n-input v-model:value="opOf(i).assignee" placeholder="维修人员姓名（必填）" size="small" />
                    <n-input v-model:value="opOf(i).phone" placeholder="电话（必填）" size="small" />
                  </div>
                  <n-button size="small" type="info" @click="requireValue(i, 'assignee', '请填写维修人员姓名') && requireValue(i, 'phone', '请填写维修人员电话') && act(i, { action: 'dispatch', assignee_name: opOf(i).assignee, assignee_phone: opOf(i).phone }, '已派单')">🔧 派单</n-button>
                </template>
                <!-- 开始处理（已派单 / 待协商均可推进） -->
                <n-button v-if="['已派单', '待协商'].includes(i.status)" size="small" type="success" style="margin-top:8px;" @click="act(i, { action: 'start' }, '已开始处理')">🔨 开始处理</n-button>
                <!-- 解决 -->
                <template v-if="i.status === '处理中'">
                  <n-input v-model:value="opOf(i).note" placeholder="处理结果（必填）" size="small" style="margin-bottom:8px;" />
                  <n-input v-model:value="opOf(i).noPhoto" placeholder="未上传照片原因（选填）" size="small" style="margin-bottom:8px;" />
                  <n-button size="small" type="primary" @click="requireValue(i, 'note', '请填写处理结果') && act(i, { action: 'resolve', note: opOf(i).note, reason: opOf(i).noPhoto || '' }, '已提交处理结果')">✅ 提交处理结果</n-button>
                </template>
                <!-- 确认补充信息 -->
                <template v-if="i.supplement_pending">
                  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
                    <span style="font-size:0.85rem;">居民补充了信息：</span>
                    <n-button size="small" type="primary" @click="act(i, { action: 'confirm_supplement', affects_timing: false }, '已确认补充')">✅ 确认（不影响时限）</n-button>
                    <n-button size="small" type="warning" @click="act(i, { action: 'confirm_supplement', affects_timing: true }, '已确认（时限重算）')">⏱️ 确认且重算时限</n-button>
                  </div>
                </template>
                <!-- 改分类 -->
                <template v-if="['已派单', '处理中', '已审核待派单'].includes(i.status)">
                  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
                    <n-select v-model:value="opOf(i).cat" :options="CAT_OPTIONS.filter(c=>c!=='全部').map(v=>({label:v,value:v}))" size="small" style="width:160px;" placeholder="改分类" />
                    <n-button size="small" @click="requireValue(i, 'cat', '请选择新分类') && act(i, { action: 'update_category', category: opOf(i).cat }, '分类已修改')">🗂️ 修改分类</n-button>
                    <span class="muted" style="font-size:0.75rem;">已派单后改分类将强制重新分派</span>
                  </div>
                </template>
                <!-- 协商 / 转出 -->
                <template v-if="['待审核', '处理中'].includes(i.status)">
                  <div style="display:flex;gap:8px;margin-top:8px;align-items:center;">
                    <n-input v-model:value="opOf(i).negReason" placeholder="协商原因" size="small" style="max-width:200px;" />
                    <n-button size="small" @click="requireValue(i, 'negReason', '请填写协商原因') && act(i, { action: 'negotiate', reason: opOf(i).negReason }, '已转待协商')">🤝 转待协商</n-button>
                    <n-button size="small" @click="act(i, { action: 'transfer' }, '已转出')">📤 转出</n-button>
                  </div>
                </template>
                <!-- 关闭 -->
                <template v-if="['待审核', '处理中'].includes(i.status)">
                  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
                    <n-input v-model:value="opOf(i).reason" placeholder="关闭原因（必填）" size="small" style="max-width:240px;" />
                    <n-button size="small" quaternary type="error" @click="requireValue(i, 'reason', '请填写关闭原因') && act(i, { action: 'close', reason: opOf(i).reason }, '已关闭')">🚫 关闭</n-button>
                  </div>
                </template>
              </div>
            </div>
          </div>
          <n-empty v-if="!loading && filtered.length === 0" description="没有符合条件的工单" />
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="safety" tab="安全提醒记录">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">⚠️ 安全隐患提醒记录（未生成工单，需线下处理）</div>
          <div v-for="s in safety" :key="s.id" style="padding:8px 0;border-bottom:1px solid var(--border);">
            <div style="font-size:0.9rem;">{{ s.description }}</div>
            <div class="muted" style="font-size:0.8rem;margin-top:2px;">📍 {{ s.location }} · {{ (s.created_at || '').slice(0, 16) }}</div>
          </div>
          <n-empty v-if="safety.length === 0" description="暂无安全提醒记录" />
        </div>
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
