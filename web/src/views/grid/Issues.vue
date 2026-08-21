<script setup>
// 工单管理：审核/派单/处理/解决/关闭（真实输入框）
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const statusFilter = ref('全部')
const expanded = ref({})
// 操作输入（按工单 id 存）
const op = ref({}) // { [id]: { opinion, assignee, phone, note, reason, cat } }

const STATUS_OPTIONS = ['全部', '待审核', '退回补充信息', '已审核待派单', '已派单', '处理中', '待居民反馈', '处理结束', '已关闭', '已撤回', '待协商', '已转出']
const filtered = computed(() => (statusFilter.value === '全部' ? list.value : list.value.filter((i) => i.status === statusFilter.value)))

async function load() {
  loading.value = true
  try { list.value = (await issues.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

function opOf(i) {
  if (!op.value[i.id]) op.value[i.id] = {}
  return op.value[i.id]
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
</script>

<template>
  <div class="page">
    <h2 class="page-title">🔧 工单管理</h2>
    <p class="page-sub">共 {{ list.length }} 条工单</p>

    <n-select v-model:value="statusFilter" :options="STATUS_OPTIONS.map(v=>({label:v,value:v}))" style="max-width:240px;margin-bottom:12px;" />

    <n-spin :show="loading">
      <div v-for="i in filtered" :key="i.id" class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;cursor:pointer;" @click="expanded[i.id] = !expanded[i.id]">
          <div>
            <b>#{{ i.id }} {{ i.title }}</b>
            <span class="status-pill" style="background:#eef2ff;color:#4f46e5;margin-left:8px;">{{ i.status }}</span>
            <span v-if="i.urgency === '紧急'" class="status-pill" style="background:#fef2f2;color:#dc2626;margin-left:4px;">🔴 紧急</span>
          </div>
          <span class="muted" style="font-size:0.85rem;">{{ expanded[i.id] ? '收起 ▲' : '展开 ▼' }}</span>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:4px;">
          {{ i.issue_type }} · {{ i.category }} · 📍{{ i.location }} · 报修人 {{ i.reporter_name }}
          <span v-if="i.assignee_name"> · 👷 {{ i.assignee_name }}</span>
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
                <n-button size="small" type="warning" @click="act(i, { action: 'audit', approve: false, opinion: opOf(i).opinion || '请补充信息' }, '已退回')">↩️ 退回补充</n-button>
              </div>
            </template>
            <!-- 派单 -->
            <template v-if="['已审核待派单', '已派单'].includes(i.status)">
              <div style="display:flex;gap:8px;margin-bottom:8px;">
                <n-input v-model:value="opOf(i).assignee" placeholder="维修人员姓名" size="small" />
                <n-input v-model:value="opOf(i).phone" placeholder="电话" size="small" />
              </div>
              <n-button size="small" type="info" @click="act(i, { action: 'dispatch', assignee_name: opOf(i).assignee || '维修工甲', assignee_phone: opOf(i).phone || '13900000000' }, '已派单')">🔧 派单</n-button>
            </template>
            <!-- 开始处理 -->
            <n-button v-if="i.status === '已派单'" size="small" type="success" style="margin-top:8px;" @click="act(i, { action: 'start' }, '已开始处理')">🔨 开始处理</n-button>
            <!-- 解决 -->
            <template v-if="i.status === '处理中'">
              <n-input v-model:value="opOf(i).note" placeholder="处理结果（必填）" size="small" style="margin-bottom:8px;" />
              <n-input v-model:value="opOf(i).noPhoto" placeholder="未上传照片原因（选填）" size="small" style="margin-bottom:8px;" />
              <n-button size="small" type="primary" @click="act(i, { action: 'resolve', note: opOf(i).note || '已处理', reason: opOf(i).noPhoto || '' }, '已提交处理结果')">✅ 提交处理结果</n-button>
            </template>
            <!-- 协商 / 转出 -->
            <template v-if="['待审核', '处理中'].includes(i.status)">
              <div style="display:flex;gap:8px;margin-top:8px;">
                <n-button size="small" @click="act(i, { action: 'negotiate', reason: '协商处理' }, '已转待协商')">🤝 转待协商</n-button>
                <n-button size="small" @click="act(i, { action: 'transfer' }, '已转出')">📤 转出</n-button>
              </div>
            </template>
            <!-- 关闭 -->
            <template v-if="['待审核', '处理中'].includes(i.status)">
              <n-input v-model:value="opOf(i).reason" placeholder="关闭原因（必填）" size="small" style="margin:8px 0;" />
              <n-button size="small" quaternary type="error" @click="act(i, { action: 'close', reason: opOf(i).reason || '关闭' }, '已关闭')">🚫 关闭</n-button>
            </template>
          </div>
        </div>
      </div>
      <n-empty v-if="!loading && filtered.length === 0" description="没有符合条件的工单" />
    </n-spin>
  </div>
</template>
