<script setup>
// 政策问答管理：知识库列表 + 待处理提问
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { knowledge, qa } from '../../api'

const message = useMessage()
const kb = ref([])
const questions = ref([])
const tab = ref('kb')

onMounted(async () => {
  try { kb.value = (await knowledge.list()) || [] } catch { /* 忽略 */ }
  try { questions.value = (await qa.questions()) || [] } catch { /* 忽略 */ }
})

async function transfer(q) {
  try {
    await qa.transfer(q.id)
    message.success('已转人工')
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📖 政策问答管理</h2>
    <p class="page-sub">知识库维护 + 居民提问处理</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="kb" tab="知识库">
        <div v-for="k in kb" :key="k.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ k.title }}</b>
            <n-tag size="small" :type="k.status === '已发布' ? 'success' : 'default'">{{ k.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ k.category }} · {{ (k.updated_at || '').slice(0, 16) }}</div>
          <div style="margin-top:8px;font-size:0.9rem;">{{ k.plain_interpretation }}</div>
        </div>
        <n-empty v-if="kb.length === 0" description="暂无知识库条目" />
      </n-tab-pane>

      <n-tab-pane name="q" tab="提问处理">
        <div v-for="q in questions" :key="q.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ q.summary }}</b>
            <n-tag size="small" :type="q.status === '已转人工' || q.status === '超时未回复' ? 'warning' : 'default'">{{ q.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ q.q_type }} · {{ (q.created_at || '').slice(0, 16) }}</div>
          <div v-if="q.status === '已转人工'" style="margin-top:8px;">
            <n-popconfirm @positive-click="transfer(q)">
              <template #trigger><n-button size="small" type="primary">🙋 转人工处理</n-button></template>
              确认转人工并通知负责人？
            </n-popconfirm>
          </div>
        </div>
        <n-empty v-if="questions.length === 0" description="暂无提问" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
