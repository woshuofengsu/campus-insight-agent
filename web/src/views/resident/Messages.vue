<script setup>
// 消息中心（居民端）：报修/咨询/通知等系统消息列表，点开已读
// 纯展示已有端点（/api/web/messages），不新增业务功能
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { messages } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try { list.value = (await messages.list({ limit: 100 })) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function read(m) {
  if (m.is_read) return
  try {
    await messages.read(m.id)
    load()
  } catch { /* 忽略 */ }
}

const TYPE_ICON = { issue: '🔧', proposal: '💡', notice: '📢', health_consult: '🏥', supplement: '📝', sla: '⏰', elderly: '👴' }
</script>

<template>
  <div class="page">
    <h2 class="page-title">✉️ 消息中心</h2>
    <p class="page-sub">报修进度、咨询回复、通知提醒等系统消息</p>

    <n-spin :show="loading">
      <div v-for="m in list" :key="m.id" class="card" style="cursor:pointer;"
           @click="read(m)" :style="m.is_read ? 'opacity:0.6;' : 'border-left:4px solid var(--primary);'">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div style="font-weight:700;">
            <span>{{ TYPE_ICON[m.type] || '📌' }} {{ m.title }}</span>
            <n-tag v-if="!m.is_read" size="tiny" type="primary" style="margin-left:6px;">未读</n-tag>
          </div>
          <span class="muted" style="font-size:0.8rem;">{{ (m.created_at || '').slice(0, 16) }}</span>
        </div>
        <div class="muted" style="font-size:0.9rem;margin-top:6px;">{{ m.content }}</div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="暂无消息" />
    </n-spin>
  </div>
</template>
