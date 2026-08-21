<script setup>
// 提案管理：审核/确认公示/决定执行/重开/关闭
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { proposals } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try { list.value = (await proposals.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function act(p, data, okMsg) {
  try {
    await proposals.action(p.id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">💡 提案管理</h2>
    <p class="page-sub">共 {{ list.length }} 条提案</p>

    <n-spin :show="loading">
      <div v-for="p in list" :key="p.id" class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>{{ p.title }}</b>
          <n-tag size="small">{{ p.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ p.category }} · {{ p.is_public ? '公开' : '私有' }} · 提案人 {{ p.reporter_name || '—' }}
          <span v-if="p.reopen_count"> · 已重开 {{ p.reopen_count }} 次</span>
        </div>

        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
          <!-- 审核 -->
          <template v-if="['待审核', '退回修改'].includes(p.status)">
            <n-popconfirm @positive-click="act(p, { action: 'audit', approve: true, opinion: '同意' }, '审核通过')">
              <template #trigger><n-button size="small" type="success">✅ 通过</n-button></template>
              确认通过审核？
            </n-popconfirm>
            <n-popconfirm @positive-click="act(p, { action: 'audit', approve: false, opinion: '请补充' }, '已退回')">
              <template #trigger><n-button size="small" type="warning">↩️ 退回</n-button></template>
              退回修改？
            </n-popconfirm>
          </template>
          <!-- 确认公示（负责人代操作，演示） -->
          <n-popconfirm v-if="p.status === '待确认公示/私有'"
                        @positive-click="act(p, { action: 'confirm', is_public: 1 }, '已确认公开，进入公示')">
            <template #trigger><n-button size="small" type="info">📢 确认公示</n-button></template>
              进入 7 天公示投票期？
          </n-popconfirm>
          <!-- 决定执行 -->
          <template v-if="p.status === '待执行'">
            <n-popconfirm @positive-click="act(p, { action: 'decide', approve: true, reason: '同意执行' }, '已决定执行')">
              <template #trigger><n-button size="small" type="success">✅ 决定执行</n-button></template>
              同意执行该提案？
            </n-popconfirm>
            <n-popconfirm @positive-click="act(p, { action: 'decide', approve: false, reason: '暂不执行' }, '已决定不执行')">
              <template #trigger><n-button size="small" type="warning">🚫 不执行</n-button></template>
              决定不执行？
            </n-popconfirm>
          </template>
          <!-- 转执行 -->
          <n-popconfirm v-if="p.status === '待执行'"
                        @positive-click="act(p, { action: 'execute', dept: '物业' }, '已转物业执行')">
            <template #trigger><n-button size="small" type="info">🔨 转执行（物业）</n-button></template>
            演示：转物业执行
          </n-popconfirm>
          <!-- 重新执行处理 -->
          <template v-if="p.status === '重新执行'">
            <n-popconfirm @positive-click="act(p, { action: 'reopen', close: false, reason: '继续执行' }, '已继续重新执行')">
              <template #trigger><n-button size="small" type="info">🔁 继续执行</n-button></template>
              继续重新执行？
            </n-popconfirm>
            <n-popconfirm @positive-click="act(p, { action: 'reopen', close: true, reason: '关闭' }, '已关闭')">
              <template #trigger><n-button size="small" type="error">🚫 关闭</n-button></template>
              关闭该提案？
            </n-popconfirm>
          </template>
        </div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="暂无提案" />
    </n-spin>
  </div>
</template>
