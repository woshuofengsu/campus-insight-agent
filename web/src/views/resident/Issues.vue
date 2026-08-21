<script setup>
// 我的报修：列表 + 状态 + 反馈/补充/撤回操作
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const op = ref({}) // { [id]: { reason, content } }

const STATUS_COLOR = {
  待审核: 'warning', 退回补充信息: 'error', 已审核待派单: 'info',
  已派单: 'info', 处理中: 'success', 待居民反馈: 'warning',
  处理结束: 'default', 已关闭: 'default', 已撤回: 'default', 待协商: 'warning', 已转出: 'default',
}

function opOf(i) {
  if (!op.value[i.id]) op.value[i.id] = {}
  return op.value[i.id]
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
          <b style="cursor:pointer;" @click="$router.push('/resident/work-orders/' + i.id)">#{{ i.id }} {{ i.title }} ›</b>
          <n-tag :type="STATUS_COLOR[i.status] || 'default'" size="small">{{ i.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ i.issue_type }} · {{ i.category }} · 📍{{ i.location }} · 🕐{{ (i.created_at || '').slice(0, 16) }}
        </div>
        <div v-if="i.resolve_note" class="muted" style="font-size:0.85rem;">📋 处理结果：{{ i.resolve_note }}</div>

        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <!-- 待居民反馈 → 满意度反馈 -->
          <template v-if="i.status === '待居民反馈'">
            <n-input v-model:value="opOf(i).reason" placeholder="不满意原因（可选）" size="small" style="max-width:220px;" />
            <n-button size="small" type="success" @click="act(i.id, { action: 'feedback', satisfied: true })">✅ 满意，结单</n-button>
            <n-button size="small" type="warning" @click="act(i.id, { action: 'feedback', satisfied: false, reason: opOf(i).reason || '还需处理' })">😕 不满意</n-button>
          </template>
          <!-- 待审核 → 撤回 -->
          <n-button v-if="i.status === '待审核'" size="small" quaternary @click="act(i.id, { action: 'withdraw' })">↩️ 撤回</n-button>
          <!-- 已撤回 → 重新打开（回待审核，可修改一次） -->
          <n-button v-if="i.status === '已撤回'" size="small" type="info" @click="act(i.id, { action: 'reopen' })">🔓 重新打开</n-button>
          <!-- 退回补充信息 → 重新提交 -->
          <n-button v-if="i.status === '退回补充信息'" size="small" type="warning" @click="act(i.id, { action: 'resubmit' })">📤 重新提交</n-button>
          <!-- 补充信息（必填校验） -->
          <template v-if="['已审核待派单', '已派单', '处理中'].includes(i.status)">
            <n-input v-model:value="opOf(i).content" placeholder="补充内容（必填）" size="small" style="max-width:240px;" />
            <n-button size="small" @click="(opOf(i).content || '').trim() ? act(i.id, { action: 'supplement', opinion: opOf(i).content }, '补充已提交') : message.warning('请填写补充内容')">📝 补充信息</n-button>
          </template>
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
