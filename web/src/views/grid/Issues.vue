<script setup>
// 工单管理：审核/派单/处理/解决/关闭全操作
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const statusFilter = ref('全部')
const expanded = ref({})

const STATUS_OPTIONS = ['全部', '待审核', '退回补充信息', '已审核待派单', '已派单', '处理中', '待居民反馈', '处理结束', '已关闭', '已撤回', '待协商', '已转出']
const filtered = computed(() => (statusFilter.value === '全部' ? list.value : list.value.filter((i) => i.status === statusFilter.value)))

async function load() {
  loading.value = true
  try { list.value = (await issues.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

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

        <div v-if="expanded[i.id]" style="margin-top:12px;border-top:1px solid #f0f0f0;padding-top:12px;">
          <div class="muted" style="font-size:0.9rem;">📝 {{ i.description }}</div>
          <div v-if="i.resolve_note" class="muted" style="font-size:0.85rem;margin-top:6px;">📋 处理结果：{{ i.resolve_note }}</div>

          <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap;">
            <!-- 审核 -->
            <template v-if="['待审核', '退回补充信息'].includes(i.status)">
              <n-popconfirm @positive-click="act(i, { action: 'audit', approve: true }, '已审核通过')">
                <template #trigger><n-button size="small" type="success">✅ 审核通过</n-button></template>
                确认通过该工单？
              </n-popconfirm>
              <n-popconfirm @positive-click="act(i, { action: 'audit', approve: false, opinion: '请补充信息' }, '已退回')">
                <template #trigger><n-button size="small" type="warning">↩️ 退回补充</n-button></template>
                退回要求居民补充信息？
              </n-popconfirm>
            </template>
            <!-- 派单 -->
            <n-popconfirm v-if="['已审核待派单', '已派单'].includes(i.status)"
                          @positive-click="act(i, { action: 'dispatch', assignee_name: '维修工甲', assignee_phone: '13900000000' }, '已派单给维修工甲（演示）')">
              <template #trigger><n-button size="small" type="info">🔧 派单（演示）</n-button></template>
              演示环境自动指派给「维修工甲」
            </n-popconfirm>
            <!-- 开始处理 -->
            <n-button v-if="i.status === '已派单'" size="small" type="success" @click="act(i, { action: 'start' }, '已开始处理')">🔨 开始处理</n-button>
            <!-- 解决 -->
            <n-popconfirm v-if="i.status === '处理中'"
                          @positive-click="act(i, { action: 'resolve', note: '已处理完毕（演示）', reason: '' }, '已提交处理结果')">
              <template #trigger><n-button size="small" type="primary">✅ 提交处理结果</n-button></template>
              确认已完成处理？
            </n-popconfirm>
            <!-- 关闭 -->
            <n-popconfirm v-if="['待审核', '处理中'].includes(i.status)"
                          @positive-click="act(i, { action: 'close', reason: '演示关闭' }, '已关闭')">
              <template #trigger><n-button size="small" quaternary type="error">🚫 关闭</n-button></template>
              确认关闭该工单？
            </n-popconfirm>
          </div>
        </div>
      </div>
      <n-empty v-if="!loading && filtered.length === 0" description="没有符合条件的工单" />
    </n-spin>
  </div>
</template>
