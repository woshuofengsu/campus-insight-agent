<script setup>
// 老年端：我的报修工单进度 + 满意度反馈
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const fbReason = ref({})

async function load() {
  loading.value = true
  try { list.value = (await issues.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function act(id, data, okMsg) {
  try {
    await issues.action(id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}

const STATUS_TEXT = {
  待审核: '⏳ 等待负责人审核', 退回补充信息: '↩️ 需补充信息', 已审核待派单: '👷 等待派单',
  已派单: '🔧 已派维修人员', 处理中: '🔨 正在处理', 待居民反馈: '📨 已处理，请确认',
  处理结束: '✅ 已完成', 已关闭: '🚫 已关闭', 已撤回: '↩️ 已撤回', 待协商: '🤝 待协商', 已转出: '📤 已转出',
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">🔧 我的报修</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">查看报修进度</p>

    <div v-for="i in list" :key="i.id" class="card" style="font-size:1.15rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b>#{{ i.id }} {{ i.title }}</b>
      </div>
      <div style="margin-top:8px;font-size:1.2rem;font-weight:700;color:#4f46e5;">{{ STATUS_TEXT[i.status] || i.status }}</div>
      <div class="muted" style="font-size:1rem;margin-top:4px;">{{ i.issue_type }} · {{ i.category }} · 📍{{ i.location }}</div>
      <div v-if="i.assignee_name" class="muted" style="font-size:1rem;margin-top:4px;">👷 维修人员：{{ i.assignee_name }}</div>
      <div v-if="i.resolve_note" style="margin-top:6px;">📋 {{ i.resolve_note }}</div>

      <!-- 满意度反馈 -->
      <div v-if="i.status === '待居民反馈'" style="margin-top:12px;background:#fefce8;border-radius:10px;padding:10px;">
        <div style="font-weight:700;">修好了吗？</div>
        <n-input v-model:value="fbReason[i.id]" placeholder="不满意原因（可选）" size="large" style="margin-top:8px;font-size:1.1rem;" />
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;">
          <n-button type="success" size="large" style="min-height:52px;" @click="act(i.id, { action: 'feedback', satisfied: true }, '✅ 已结单')">✅ 满意，结单</n-button>
          <n-button type="warning" size="large" style="min-height:52px;" @click="act(i.id, { action: 'feedback', satisfied: false, reason: fbReason[i.id] || '还需处理' }, '已反馈，将重新处理')">😕 不满意</n-button>
        </div>
      </div>
    </div>
    <n-empty v-if="!loading && list.length === 0" description="还没有报修记录" style="font-size:1.1rem;" />
  </div>
</template>
