<script setup>
// 社区通知：列表 + 紧急置顶 + 标记已读
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { notices } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try { list.value = (await notices.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function markRead(n) {
  if (n.is_read) return
  try {
    await notices.action(n.id, { action: 'mark_read' })
    load()
  } catch { /* 忽略 */ }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📢 社区通知</h2>
    <p class="page-sub">共 {{ list.length }} 条通知</p>
    <n-spin :show="loading">
      <div v-for="n in list" :key="n.id" class="card" @click="markRead(n)"
           :style="n.is_urgent ? 'border-left:4px solid #dc2626;' : ''">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>{{ n.title }}</b>
          <span>
            <n-tag v-if="n.is_urgent" type="error" size="small">🚨 紧急</n-tag>
            <n-tag v-if="!n.is_read" size="small" type="warning">未读</n-tag>
          </span>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:4px;">
          {{ n.notice_type }} · {{ (n.published_at || '').slice(0, 16) }}
        </div>
        <div style="margin-top:8px;color:#374151;">{{ n.body }}</div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="暂无通知" />
    </n-spin>
  </div>
</template>
