<script setup>
// 网格员端消息中心：系统通知 + 人工处理包（无缝转人工：AI 已整理上下文，可直接处理）
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { messages, agent } from '../../api'

const message = useMessage()
const list = ref([])
const handoffs = ref([])
const tab = ref('notices')
const loading = ref(true)

async function load() {
  loading.value = true
  try { list.value = (await messages.list({ limit: 100 })) || [] } catch { /* 忽略 */ }
  try { handoffs.value = (await agent.handoffs({ limit: 20 })) || [] } catch { /* 忽略 */ }
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

async function resolve(h) {
  try {
    await agent.resolveHandoff(h.id)
    message.success(`处理包 #${h.id} 已处理完成`)
    load()
  } catch (e) {
    message.error(e.message)
  }
}

const TYPE_ICON = { issue: '🔧', proposal: '💡', notice: '📢', health_consult: '🏥', supplement: '📝', sla: '⏰', elderly: '👴', agent_handoff: '🤝' }
</script>

<template>
  <div class="page">
    <h2 class="page-title">📬 消息中心</h2>
    <p class="page-sub">系统通知 + 人工处理包（AI 已整理上下文，可直接处理）</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="handoffs" tab="🤝 人工处理包">
        <div v-for="h in handoffs" :key="h.id" class="card"
             :style="h.status === '待处理' ? 'border-left:4px solid var(--st-pending);' : 'opacity:0.6;'">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>#{{ h.id }} {{ h.package?.intent || h.intent }}（{{ h.status }}）</b>
            <span class="muted" style="font-size:0.8rem;">{{ (h.created_at || '').slice(0, 16) }}</span>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">👤 用户 #{{ h.user_id }} · 原始问题：{{ h.package?.original_input || '—' }}</div>
          <div v-if="h.reason" style="margin-top:4px;font-size:0.9rem;">⚠️ 待确认：{{ h.reason }}</div>
          <div v-if="h.package?.collected_fields && Object.keys(h.package.collected_fields).length" style="margin-top:4px;" class="muted">
            📋 AI 已收集：{{ JSON.stringify(h.package.collected_fields) }}
          </div>
          <div v-if="h.package?.recent_history && h.package.recent_history.length" style="margin-top:4px;" class="muted">
            💬 最近对话：{{ h.package.recent_history.map(x => (x.role === 'user' ? '👤' : '🤖') + x.content.slice(0, 30)).join(' / ') }}
          </div>
          <n-button v-if="h.status === '待处理'" size="small" type="primary" style="margin-top:8px;" @click="resolve(h)">
            ✅ 已处理完成
          </n-button>
        </div>
        <n-empty v-if="handoffs.length === 0" description="暂无人工处理包" />
      </n-tab-pane>

      <n-tab-pane name="notices" tab="系统通知">
        <div v-for="m in list" :key="m.id" class="card" style="cursor:pointer;" @click="read(m)"
             :style="m.is_read ? 'opacity:0.6;' : 'border-left:4px solid var(--primary);'">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ TYPE_ICON[m.type] || '📌' }} {{ m.title }}</b>
            <span class="muted" style="font-size:0.8rem;">{{ (m.created_at || '').slice(0, 16) }}</span>
          </div>
          <div class="muted" style="font-size:0.9rem;margin-top:6px;">{{ m.content }}</div>
        </div>
        <n-empty v-if="list.length === 0" description="暂无通知" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
