<script setup>
// 工单管理：审核/派单/处理/解决/关闭/协商/转出/确认补充/改分类（真实输入 + 筛选 + 时限 + 导出 + 安全提醒 + 批量操作）
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues, exportApi, batch } from '../../api'
import EIcon from '../../components/EIcon.vue'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const expanded = ref({})
const tab = ref('orders')
const safety = ref([])
// 批量选择（P2-E2-01）
const selected = ref([])
const batchAssignee = ref('')
const batchPhone = ref('')
const batchCloseReason = ref('批量关闭')
// 筛选
const statusFilter = ref('全部')
const catFilter = ref('全部')
const urgFilter = ref('全部')
const keyword = ref('')
// 操作输入（按工单 id 存）
const op = ref({}) // { [id]: { opinion, assignee, phone, note, reason, cat, noPhoto, negReason } }
const detailOpen = ref(false)
const detailIssue = ref(null)

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

function openDetail(i) {
  detailIssue.value = i
  detailOpen.value = true
  loadFieldSources(i.id)
}

// 字段来源（v52 沉淀）：问题/位置/责任范围/紧急程度分别从哪来 ——「不许编造」最需要事后可审计的东西
const fieldSources = ref({})
const fieldSourceNote = ref('')
const SOURCE_LABEL = {
  user: '用户自己说的', text: '从原话里抽出来的', profile: '来自登记档案',
  suggestion: '系统建议（老人确认过）', default: '默认值', form: '表单直接填写', agent: '代办人填写',
}
async function loadFieldSources(id) {
  fieldSources.value = {}
  fieldSourceNote.value = ''
  try {
    const r = (await issues.fieldSources(id)) || {}
    fieldSources.value = r.sources || {}
    fieldSourceNote.value = r.note || ''
  } catch (e) {
    fieldSourceNote.value = `字段来源读取失败：${e.message}`
  }
}

function deadlineText(i) {
  if (i.status === '处理结束' || i.status === '已关闭' || i.status === '已撤回' || i.status === '已转出') return ''
  if (i.remaining_hours == null) return ''
  if (i.overdue) return `已超时 ${Math.abs(i.remaining_hours).toFixed(1)}h`
  return `剩余 ${i.remaining_hours.toFixed(1)}h`
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

// ---- 批量操作（P2-E2-01）----
function toggleAll() {
  selected.value = selected.value.length === filtered.value.length ? [] : filtered.value.map((i) => i.id)
}
async function batchDispatch() {
  if (!selected.value.length) return message.warning('请先勾选工单')
  if (!batchAssignee.value.trim()) return message.warning('请填写维修人员姓名')
  try {
    const out = await batch.dispatch(selected.value, batchAssignee.value.trim(), batchPhone.value.trim())
    message.success(`批量派单完成：成功 ${out.success}，失败 ${out.failed}`)
    selected.value = []
    load()
  } catch (e) { message.error(e.message) }
}
async function batchClose() {
  if (!selected.value.length) return message.warning('请先勾选工单')
  if (!batchCloseReason.value.trim()) return message.warning('请填写关闭原因')
  try {
    const out = await batch.close(selected.value, batchCloseReason.value.trim())
    message.success(`批量关闭完成：成功 ${out.success}，失败 ${out.failed}`)
    selected.value = []
    load()
  } catch (e) { message.error(e.message) }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title"><EIcon name="wrench" :size="18" /> 工单管理</h2>
    <p class="page-sub">共 {{ list.length }} 条工单 · 超时按紧急程度计时（紧急1h/中等4h/一般24h/普通48h）</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="orders" tab="工单管理">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
          <n-select v-model:value="statusFilter" :options="STATUS_OPTIONS.map(v=>({label:v,value:v}))" style="width:150px;" />
          <n-select v-model:value="catFilter" :options="CAT_OPTIONS.map(v=>({label:v,value:v}))" style="width:130px;" />
          <n-select v-model:value="urgFilter" :options="URG_OPTIONS.map(v=>({label:v,value:v}))" style="width:110px;" />
          <n-input v-model:value="keyword" placeholder="搜索标题/地址/描述/报修人" clearable style="flex:1;min-width:200px;" />
          <n-button size="small" @click="load">刷新</n-button>
          <n-button size="small" @click="exportIssues"><EIcon name="arrowDown" :size="18" /> 导出</n-button>
        </div>

        <!-- 批量操作栏（P2-E2-01） -->
        <div class="card" style="padding:10px 12px;margin:0 0 12px 0;display:flex;gap:8px;flex-wrap:wrap;align-items:center;background:#f8fafc;">
          <n-checkbox :checked="selected.length === filtered.length && filtered.length > 0" @update:checked="toggleAll">全选（{{ selected.length }}）</n-checkbox>
          <n-input v-model:value="batchAssignee" placeholder="批量派单：维修人员姓名" size="small" style="width:180px;" />
          <n-input v-model:value="batchPhone" placeholder="电话" size="small" style="width:130px;" />
          <n-button size="small" type="info" @click="batchDispatch"><EIcon name="wrench" :size="18" /> 批量派单</n-button>
          <n-input v-model:value="batchCloseReason" placeholder="批量关闭原因" size="small" style="width:160px;" />
          <n-button size="small" quaternary type="error" @click="batchClose"><EIcon name="ban" :size="18" /> 批量关闭</n-button>
        </div>

        <n-spin :show="loading">
          <div v-for="i in filtered" :key="i.id" class="card">
            <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" @click="expanded[i.id] = !expanded[i.id]">
              <div style="display:flex;align-items:center;gap:8px;">
                <n-checkbox :checked="selected.includes(i.id)" @update:checked="(v) => { if (v) selected.push(i.id); else selected = selected.filter((x) => x !== i.id) }" @click.stop />
                <div>
                  <!-- v3：网格端同时给出**内部号**与**对外事项编号**。
                       内部号是工作人员日常叫法（#572），对外编号是居民/服务台那侧能查到的号
                       （居民报事、电话问进度都报它）——两个都摆出来，免得两头对不上。
                       注意：内部号 `#id` 必须保留——三条端到端旅程按它定位卡片。 -->
                  <b>#{{ i.id }} <span v-if="i.issue_code" class="muted" style="font-weight:400;">{{ i.issue_code }}</span> {{ i.title }}</b>
                  <!-- 状态色文字全部改用「跟随主题」的令牌（值与原写死色在亮色下完全相同，暗色下自动换亮变体）：
                       处理结束 #047857→var(--ink-success)、已关闭/已撤回 #5B6B80→var(--muted)、
                       超时 #b91c1c→var(--ink-danger)、待审核 #4f46e5→var(--ink-info)。
                       写死色的暗色实测：待审核 2.58:1、处理结束 2.96:1（全站审计抓到），
                       另外「已关闭/超时」两条当前数据没触发，但同样是隐患，一并收掉。 -->
                  <span class="status-pill" :style="{
                    background: i.status === '处理结束' ? '#ecfdf5' : i.status === '已关闭' ? '#f5f5f5' : i.status === '已撤回' ? '#f5f5f5' : i.status === '已超时' || (i.overdue && i.status !== '处理结束') ? '#fef2f2' : '#eef2ff',
                    color: i.status === '处理结束' ? 'var(--ink-success)' : i.status === '已关闭' || i.status === '已撤回' ? 'var(--muted)' : i.status === '已超时' || (i.overdue && i.status !== '处理结束') ? 'var(--ink-danger)' : 'var(--ink-info)',
                  }" style="margin-left:8px;">{{ i.status }}</span>
                  <span v-if="i.urgency === '紧急'" class="status-pill" style="background:#fef2f2;color:var(--ink-danger);margin-left:4px;"><EIcon name="dot" :size="18" /> 紧急</span>
                  <span v-if="i.is_violation" class="status-pill" style="background:#fef2f2;color:var(--ink-danger);margin-left:4px;"><EIcon name="ban" :size="18" /> 违规标记</span>
                  <span v-if="i.non_community_responsibility" class="status-pill" style="background:#fffbeb;color:var(--ink-warning);margin-left:4px;"><EIcon name="construction" :size="18" /> 第三方施工</span>
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span v-if="deadlineText(i)" class="status-pill" :style="i.overdue ? 'background:#fef2f2;color:var(--ink-danger);' : 'background:#f0fdf4;color:var(--ink-success);'">{{ deadlineText(i) }}</span>
                <n-button size="tiny" secondary @click.stop="openDetail(i)">详情</n-button>
                <span class="muted" style="font-size:0.85rem;">{{ expanded[i.id] ? '收起 ▲' : '展开 ▼' }}</span>
              </div>
            </div>
            <div class="muted" style="font-size:0.85rem;margin-top:4px;">
              {{ i.issue_type }} · {{ i.category }} · <EIcon name="pin" :size="18" /> {{ i.location }} · 报修人 {{ i.reporter_name }}
              <span v-if="i.assignee_name"> · <EIcon name="user-worker" :size="18" /> {{ i.assignee_name }}</span>
              <span v-if="i.is_agent_report && i.agent_name"> · <EIcon name="hand" :size="18" /> 代报：{{ i.agent_name }}（{{ i.agent_relation }}）</span>
            </div>

            <!-- v3：展开后是**左信息 / 右操作**两栏（任务书 §六）。
                 为什么还保留"就地展开"而不是换成左右分栏页面：三条端到端旅程
                 （journey 1/4/8 与 demo_flow_check）都是"展开这张卡 → 点卡里的按钮"，
                 改成独立详情页会连带改三套验收脚本；**同屏两栏**已经达到"信息在左、操作在右"的
                 目的，而且少一次跳转、少一次出错。 -->
            <div v-if="expanded[i.id]" style="margin-top:12px;border-top:1px solid var(--border);padding-top:12px;">
              <div class="issue-expand">
                <div class="issue-expand-info">
                  <div class="muted" style="font-size:0.9rem;"><EIcon name="edit" :size="18" /> {{ i.description }}</div>
                  <div v-if="i.resolve_note" class="muted" style="font-size:0.88rem;margin-top:6px;"><EIcon name="clipboard" :size="18" /> 处理结果：{{ i.resolve_note }}</div>
                  <!-- 技术细节折叠：需要追溯时再展开（Agent / 校验 / 仲裁留痕都在这里） -->
                  <details class="issue-tech">
                    <summary><EIcon name="info" :size="16" /> 分析详情（系统研判与留痕）</summary>
                    <div class="muted" style="font-size:0.85rem;margin-top:6px;">
                      <div>字段来源：见详情抽屉「字段来源（谁说的）」——位置、责任范围、紧急程度各自是谁给的。</div>
                      <div v-if="i.is_agent_report">代报：{{ i.agent_name || '—' }}（{{ i.agent_relation || '—' }}）</div>
                      <div>traceId：{{ i.trace_id || '—' }}（用于对齐 agent_logs 里的研判与仲裁记录）</div>
                    </div>
                  </details>
                </div>

                <div class="issue-expand-ops" style="margin-top:0;">
                <!-- 审核 -->
                <template v-if="['待审核', '退回补充信息'].includes(i.status)">
                  <n-input v-model:value="opOf(i).opinion" placeholder="审核意见（退回必填）" size="small" style="margin-bottom:8px;" />
                  <div style="display:flex;gap:8px;">
                    <n-button size="small" type="success" @click="act(i, { action: 'audit', approve: true, opinion: opOf(i).opinion || '同意' }, '已审核通过')"><EIcon name="checkCircle" :size="18" /> 审核通过</n-button>
                    <n-button size="small" type="warning" @click="requireValue(i, 'opinion', '退回必须填写审核意见') && act(i, { action: 'audit', approve: false, opinion: opOf(i).opinion }, '已退回')"><EIcon name="arrowLeft" :size="18" />  退回补充</n-button>
                  </div>
                </template>
                <!-- 派单 -->
                <template v-if="['已审核待派单', '已派单'].includes(i.status)">
                  <div style="display:flex;gap:8px;margin-bottom:8px;">
                    <n-input v-model:value="opOf(i).assignee" placeholder="维修人员姓名（必填）" size="small" />
                    <n-input v-model:value="opOf(i).phone" placeholder="电话（必填）" size="small" />
                  </div>
                  <n-button size="small" type="info" @click="requireValue(i, 'assignee', '请填写维修人员姓名') && requireValue(i, 'phone', '请填写维修人员电话') && act(i, { action: 'dispatch', assignee_name: opOf(i).assignee, assignee_phone: opOf(i).phone }, '已派单')"><EIcon name="wrench" :size="18" /> 派单</n-button>
                </template>
                <!-- 开始处理（已派单 / 待协商均可推进） -->
                <n-button v-if="['已派单', '待协商'].includes(i.status)" size="small" type="success" style="margin-top:8px;" @click="act(i, { action: 'start' }, '已开始处理')"><EIcon name="hammer" :size="18" /> 开始处理</n-button>
                <!-- 解决 -->
                <template v-if="i.status === '处理中'">
                  <n-input v-model:value="opOf(i).note" placeholder="处理结果（必填）" size="small" style="margin-bottom:8px;" />
                  <n-input v-model:value="opOf(i).noPhoto" placeholder="未上传照片原因（选填）" size="small" style="margin-bottom:8px;" />
                  <n-button size="small" type="primary" @click="requireValue(i, 'note', '请填写处理结果') && act(i, { action: 'resolve', note: opOf(i).note, reason: opOf(i).noPhoto || '' }, '已提交处理结果')"><EIcon name="checkCircle" :size="18" /> 提交处理结果</n-button>
                </template>
                <!-- 确认补充信息 -->
                <template v-if="i.supplement_pending">
                  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
                    <span style="font-size:0.85rem;">居民补充了信息：</span>
                    <n-button size="small" type="primary" @click="act(i, { action: 'confirm_supplement', affects_timing: false }, '已确认补充')"><EIcon name="checkCircle" :size="18" /> 确认（不影响时限）</n-button>
                    <n-button size="small" type="warning" @click="act(i, { action: 'confirm_supplement', affects_timing: true }, '已确认（时限重算）')"><EIcon name="clock" :size="18" />  确认且重算时限</n-button>
                  </div>
                </template>
                <!-- 改分类 -->
                <template v-if="['已派单', '处理中', '已审核待派单'].includes(i.status)">
                  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
                    <n-select v-model:value="opOf(i).cat" :options="CAT_OPTIONS.filter(c=>c!=='全部').map(v=>({label:v,value:v}))" size="small" style="width:160px;" placeholder="改分类" />
                    <n-button size="small" @click="requireValue(i, 'cat', '请选择新分类') && act(i, { action: 'update_category', category: opOf(i).cat }, '分类已修改')"><EIcon name="folder" :size="18" /> 修改分类</n-button>
                    <span class="muted" style="font-size:0.75rem;">已派单后改分类将强制重新分派</span>
                  </div>
                </template>
                <!-- 协商 / 转出 -->
                <template v-if="['待审核', '处理中'].includes(i.status)">
                  <div style="display:flex;gap:8px;margin-top:8px;align-items:center;">
                    <n-input v-model:value="opOf(i).negReason" placeholder="协商原因" size="small" style="max-width:200px;" />
                    <n-button size="small" @click="requireValue(i, 'negReason', '请填写协商原因') && act(i, { action: 'negotiate', reason: opOf(i).negReason }, '已转待协商')"><EIcon name="handshake" :size="18" /> 转待协商</n-button>
                    <n-button size="small" @click="act(i, { action: 'transfer' }, '已转出')"><EIcon name="send" :size="18" /> 转出</n-button>
                  </div>
                </template>
                <!-- 关闭 -->
                <template v-if="['待审核', '处理中'].includes(i.status)">
                  <div style="display:flex;gap:8px;align-items:center;margin-top:8px;">
                    <n-input v-model:value="opOf(i).reason" placeholder="关闭原因（必填）" size="small" style="max-width:240px;" />
                    <n-button size="small" quaternary type="error" @click="requireValue(i, 'reason', '请填写关闭原因') && act(i, { action: 'close', reason: opOf(i).reason }, '已关闭')"><EIcon name="ban" :size="18" /> 关闭</n-button>
                  </div>
                </template>
                </div>
              </div>
            </div>
          </div>
          <n-empty v-if="!loading && filtered.length === 0" description="没有符合条件的工单" />
        </n-spin>
      </n-tab-pane>

      <n-tab-pane name="safety" tab="安全提醒记录">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="alert" :size="18" /> 安全隐患提醒记录（未生成工单，需线下处理）</div>
          <div v-for="s in safety" :key="s.id" style="padding:8px 0;border-bottom:1px solid var(--border);">
            <div style="font-size:0.9rem;">{{ s.description }}</div>
            <div class="muted" style="font-size:0.8rem;margin-top:2px;"><EIcon name="pin" :size="18" /> {{ s.location }} · {{ (s.created_at || '').slice(0, 16) }}</div>
          </div>
          <n-empty v-if="safety.length === 0" description="暂无安全提醒记录" />
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-drawer v-model:show="detailOpen" placement="right" :width="420">
      <n-drawer-content v-if="detailIssue" :title="'工单 #' + detailIssue.id + ' 详情'" :native-scrollbar="false">
        <div class="detail-status">
          <span class="status-pill">{{ detailIssue.status }}</span>
          <span v-if="detailIssue.urgency === '紧急'" class="status-pill detail-danger"><EIcon name="dot" :size="18" /> 紧急</span>
          <span v-if="deadlineText(detailIssue)" class="muted">{{ deadlineText(detailIssue) }}</span>
        </div>
        <h3 style="margin:12px 0 6px;">{{ detailIssue.title }}</h3>
        <div class="detail-grid">
          <span>问题类型</span><b>{{ detailIssue.issue_type || '—' }}</b>
          <span>分类</span><b>{{ detailIssue.category || '—' }}</b>
          <span>位置</span><b>{{ detailIssue.location || '—' }}</b>
          <span>报修人</span><b>{{ detailIssue.reporter_name || '—' }}</b>
          <span>责任人</span><b>{{ detailIssue.assignee_name || '待派单' }}</b>
        </div>
        <div class="detail-block"><div class="muted">居民原话 / 问题描述</div><div>{{ detailIssue.description || '—' }}</div></div>
        <!-- 字段来源（v52）：位置到底是老人自己说的、还是系统按档案替他填的，这里能查 -->
        <div class="detail-block" data-field-sources>
          <div class="muted">字段来源（谁说的）</div>
          <div v-if="Object.keys(fieldSources).length" class="detail-grid" style="border:0;padding:6px 0;">
            <template v-for="(v, k) in fieldSources" :key="k">
              <span>{{ { title: '问题', location: '位置', scope: '责任范围', urgency: '紧急程度' }[k] || k }}</span>
              <b>{{ SOURCE_LABEL[v] || v }}</b>
            </template>
          </div>
          <div v-else class="muted" style="font-size:0.85rem;">{{ fieldSourceNote || '—' }}</div>
        </div>
        <div v-if="detailIssue.resolve_note" class="detail-block"><div class="muted">处理结果</div><div>{{ detailIssue.resolve_note }}</div></div>
        <n-button type="primary" block @click="expanded[detailIssue.id] = true; detailOpen = false">回到列表处理</n-button>
      </n-drawer-content>
    </n-drawer>
  </div>
</template>

<style scoped>
.detail-status { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.detail-danger { background:#fef2f2; color:var(--ink-danger); }
.detail-grid { display:grid; grid-template-columns:90px 1fr; gap:9px 12px; padding:12px 0; border-top:1px solid var(--border); border-bottom:1px solid var(--border); }
.detail-grid span, .detail-block .muted { color:var(--muted); font-size:0.85rem; }
.detail-block { padding:12px 0; line-height:1.65; }

/* v3：展开区两栏 —— 左「信息」右「操作」。窄屏（平板竖屏/手机）自动落成一栏，
   因为网格员在手机上处理时，两栏各一半反而都看不清。 */
.issue-expand { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,320px); gap:16px; align-items:start; }
.issue-expand-info { min-width:0; }
.issue-expand-ops { min-width:0; border-left:1px solid var(--border); padding-left:14px; }
/* 长工单往下滚时，操作区跟着停在视野里（网格员不用来回滚找按钮） */
@media (min-width: 901px) { .issue-expand-ops { position:sticky; top:12px; } }
@media (max-width: 900px) {
  .issue-expand { grid-template-columns:1fr; gap:10px; }
  .issue-expand-ops { border-left:0; border-top:1px solid var(--border); padding-left:0; padding-top:10px; }
}
/* 技术细节默认折叠（Agent 研判 / 校验 / 仲裁留痕这类，需要追溯时再展开） */
.issue-tech { margin-top:8px; }
.issue-tech > summary {
  cursor:pointer; min-height:32px; display:flex; align-items:center; gap:6px;
  color:var(--muted); font-size:0.88rem;
}
</style>
