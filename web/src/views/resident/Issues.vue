<script setup>
// 我的报修：列表 + 状态 + 反馈/补充/撤回操作
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)

const STATUS_COLOR = {
  待审核: 'warning', 退回补充信息: 'error', 已审核待派单: 'info',
  已派单: 'info', 处理中: 'success', 待居民反馈: 'warning',
  处理结束: 'default', 已关闭: 'default', 已撤回: 'default', 待协商: 'warning', 已转出: 'default',
}

async function load() {
  loading.value = true
  try { list.value = (await issues.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function act(id, data) {
  try {
    await issues.action(id, data)
    message.success('操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🔧 我的报修</h2>
    <p class="page-sub">共 {{ list.length }} 条工单</p>

    <n-spin :show="loading">
      <div v-for="i in list" :key="i.id" class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>#{{ i.id }} {{ i.title }}</b>
          <n-tag :type="STATUS_COLOR[i.status] || 'default'" size="small">{{ i.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ i.issue_type }} · {{ i.category }} · 📍{{ i.location }} · 🕐{{ (i.created_at || '').slice(0, 16) }}
        </div>
        <div v-if="i.resolve_note" class="muted" style="font-size:0.85rem;">📋 处理结果：{{ i.resolve_note }}</div>

        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
          <!-- 待居民反馈 → 满意度反馈 -->
          <template v-if="i.status === '待居民反馈'">
            <n-popconfirm @positive-click="act(i.id, { action: 'feedback', satisfied: true })">
              <template #trigger><n-button size="small" type="success">✅ 满意，结单</n-button></template>
              确认问题已解决？
            </n-popconfirm>
            <n-popconfirm @positive-click="act(i.id, { action: 'feedback', satisfied: false, reason: '还想再修一下' })">
              <template #trigger><n-button size="small" type="warning">😕 不满意</n-button></template>
              将退回重新处理，确认？
            </n-popconfirm>
          </template>
          <!-- 待审核 → 撤回 -->
          <template v-if="i.status === '待审核'">
            <n-popconfirm @positive-click="act(i.id, { action: 'withdraw' })">
              <template #trigger><n-button size="small" quaternary>↩️ 撤回</n-button></template>
              确认撤回该工单？
            </n-popconfirm>
          </template>
          <!-- 补充信息 -->
          <n-popconfirm v-if="['已审核待派单','已派单','处理中'].includes(i.status)"
                        @positive-click="act(i.id, { action: 'supplement', opinion: '补充：情况说明如下' })">
            <template #trigger><n-button size="small">📝 补充信息</n-button></template>
            补充信息将通知负责人确认（演示版固定文案）
          </n-popconfirm>
        </div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="还没有报修工单">
        <template #extra>
          <n-button type="primary" @click="$router.push('/resident/work-orders/new')">去报修</n-button>
        </template>
      </n-empty>
    </n-spin>
  </div>
</template>
