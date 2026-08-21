<script setup>
// 社区通知：列表 + 紧急置顶 + 详情弹窗（附件/我知道了）+ 标记已读
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { notices } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const detail = ref(null)

async function load() {
  loading.value = true
  try { list.value = (await notices.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function showDetail(n) {
  try {
    detail.value = await notices.detail(n.id)
  } catch (e) {
    message.error(e.message)
    return
  }
  if (!n.is_read) {
    try {
      await notices.action(n.id, { action: 'mark_read' })
      load()
    } catch { /* 忽略 */ }
  }
}

function atts(n) {
  try { return JSON.parse(n.attachment_json || '[]') } catch { return [] }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📢 社区通知</h2>
    <p class="page-sub">共 {{ list.length }} 条通知 · 点击查看详情</p>
    <n-spin :show="loading">
      <div v-for="n in list" :key="n.id" class="card" style="cursor:pointer;" @click="showDetail(n)"
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

    <!-- 详情弹窗（附件/我知道了） -->
    <n-modal :show="!!detail" @update:show="(v) => { if (!v) detail = null }" preset="card" style="width:600px;" :title="detail ? detail.title : ''">
      <template v-if="detail">
        <div style="margin-bottom:8px;">
          <n-tag v-if="detail.is_urgent" type="error" size="small">🚨 紧急</n-tag>
          <n-tag size="small" style="margin-left:6px;">{{ detail.notice_type }}</n-tag>
          <span class="muted" style="margin-left:8px;font-size:0.8rem;">{{ (detail.published_at || detail.created_at || '').slice(0, 16) }}</span>
        </div>
        <div style="font-size:0.95rem;line-height:1.8;white-space:pre-wrap;">{{ detail.body }}</div>
        <div v-if="atts(detail).length" style="margin-top:10px;">
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:4px;">📎 附件</div>
          <div v-for="(a, i) in atts(detail)" :key="i" style="display:inline-block;margin-right:8px;">
            <img :src="a" style="max-width:140px;max-height:140px;border-radius:6px;border:1px solid var(--border);" />
          </div>
        </div>
        <div style="margin-top:14px;text-align:right;">
          <n-button type="primary" @click="detail = null">我知道了</n-button>
        </div>
      </template>
    </n-modal>
  </div>
</template>
