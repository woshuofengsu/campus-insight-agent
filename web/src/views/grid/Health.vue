<script setup>
// 健康管理：咨询处理（回复）+ 内容列表
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { health } from '../../api'

const message = useMessage()
const consults = ref([])
const tab = ref('consults')
const replyMap = ref({})

onMounted(async () => {
  try { consults.value = (await health.consults()) || [] } catch { /* 忽略 */ }
})

async function reply(c) {
  const text = replyMap.value[c.id] || ''
  if (!text) return message.warning('请填写回复内容')
  try {
    await health.replyConsult(c.id, { reply: text })
    message.success(`咨询 ${c.code || '#' + c.id} 已回复`)
    replyMap.value[c.id] = ''
    consults.value = (await health.consults()) || []
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🏥 健康管理</h2>
    <p class="page-sub">健康咨询处理（24 小时内回复）</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="consults" tab="咨询处理">
        <div v-for="c in consults" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ c.code || ('#' + c.id) }}</b>
            <n-tag size="small" :type="c.status === '待回复' ? 'warning' : c.status === '已回复' ? 'success' : 'default'">{{ c.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ c.name }} · {{ c.consult_type }} · {{ (c.created_at || '').slice(0, 16) }}</div>
          <div style="margin-top:8px;">{{ c.content }}</div>
          <div v-if="c.reply" style="background:#f0fdf4;border-radius:8px;padding:8px;margin-top:8px;font-size:0.9rem;">
            💬 已回复：{{ c.reply }}
          </div>
          <div v-if="['待回复', '超时未回复'].includes(c.status)" style="margin-top:10px;display:flex;gap:8px;">
            <n-input v-model:value="replyMap[c.id]" placeholder="输入回复建议..." />
            <n-button type="primary" @click="reply(c)">回复</n-button>
          </div>
        </div>
        <n-empty v-if="consults.length === 0" description="暂无咨询" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
