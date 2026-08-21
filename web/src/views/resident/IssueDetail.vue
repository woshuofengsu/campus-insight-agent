<script setup>
// 工单详情：完整字段 + 时间线 + 状态操作（居民视角）
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const detail = ref(null)
const loading = ref(true)

onMounted(load)
async function load() {
  loading.value = true
  try { detail.value = await issues.detail(route.params.id) } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}

async function act(data, okMsg) {
  try {
    await issues.action(detail.value.id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) { message.error(e.message) }
}
</script>

<template>
  <div class="page">
    <n-button quaternary size="small" style="margin-bottom:8px;" @click="router.back()">← 返回</n-button>
    <n-spin :show="loading">
      <template v-if="detail">
        <h2 class="page-title">🔧 工单 #{{ detail.id }} {{ detail.title }}</h2>
        <p class="page-sub">状态：<b>{{ detail.status }}</b> · {{ detail.issue_type }} · {{ detail.category }}</p>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">📋 工单信息</div>
          <div class="muted" style="line-height:2;font-size:0.95rem;">
            📍 地址：{{ detail.location }}<br>
            🔴 紧急度：{{ detail.urgency }}<br>
            👤 报修人：{{ detail.reporter_name }} · {{ detail.reporter_phone }}<br>
            <template v-if="detail.assignee_name">👷 维修人员：{{ detail.assignee_name }}<br></template>
            🕐 提交时间：{{ (detail.created_at || '').slice(0, 16) }}<br>
          </div>
          <div style="margin-top:8px;">📝 {{ detail.description }}</div>
          <div v-if="detail.resolve_note" style="background:#f0fdf4;border-radius:8px;padding:8px;margin-top:10px;">
            📋 处理结果：{{ detail.resolve_note }}
          </div>
        </div>

        <!-- 操作 -->
        <div v-if="detail.status === '待居民反馈'" class="card" style="display:flex;gap:8px;align-items:center;">
          <n-button type="success" @click="act({ action: 'feedback', satisfied: true }, '已确认解决')">✅ 满意，结单</n-button>
          <n-button type="warning" @click="act({ action: 'feedback', satisfied: false, reason: '还需处理' }, '已反馈')">😕 不满意</n-button>
        </div>
        <div v-if="detail.status === '待审核'" class="card">
          <n-button quaternary @click="act({ action: 'withdraw' }, '已撤回')">↩️ 撤回工单</n-button>
        </div>
        <div v-if="['已审核待派单','已派单','处理中'].includes(detail.status)" class="card">
          <n-button @click="act({ action: 'supplement', opinion: '补充说明' }, '已补充')">📝 补充信息</n-button>
        </div>

        <!-- 时间线 -->
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">📜 处理留痕</div>
          <div v-for="t in detail.timeline || []" :key="t.id" style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
            {{ (t.created_at || '').slice(0, 16) }} · {{ t.actor || '' }} · {{ t.action || '' }}
          </div>
          <n-empty v-if="!(detail.timeline || []).length" description="暂无留痕" style="font-size:0.85rem;padding:8px;" />
        </div>
      </template>
    </n-spin>
  </div>
</template>
