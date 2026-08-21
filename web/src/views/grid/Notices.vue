<script setup>
// 通知管理：创建发布 + 列表 + 下架/撤回/置顶
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { notices } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)

const form = ref({ title: '', notice_type: '社区公告', publish_scope: '全体居民', body: '', is_urgent: 0 })
const creating = ref(false)

const TYPES = ['社区公告', '活动通知', '停水停电通知', '政策通知', '温馨提示', '其他']

async function load() {
  loading.value = true
  try { list.value = (await notices.manage()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function create() {
  if (!form.value.title || !form.value.body) return message.warning('请填写标题和正文')
  creating.value = true
  try {
    await notices.create(form.value)
    message.success('通知已创建并发布')
    form.value = { title: '', notice_type: '社区公告', publish_scope: '全体居民', body: '', is_urgent: 0 }
    load()
  } catch (e) {
    message.error(e.message)
  } finally {
    creating.value = false
  }
}

async function act(n, data, okMsg) {
  try {
    await notices.action(n.id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📢 通知管理</h2>
    <p class="page-sub">发布公告、活动、停水停电与紧急通知</p>

    <div class="card">
      <div style="font-weight:700;margin-bottom:10px;">➕ 新建通知</div>
      <n-grid :cols="2" :x-gap="16">
        <n-form-item-gi label="标题">
          <n-input v-model:value="form.title" maxlength="50" />
        </n-form-item-gi>
        <n-form-item-gi label="类型">
          <n-select v-model:value="form.notice_type" :options="TYPES.map(v=>({label:v,value:v}))" />
        </n-form-item-gi>
      </n-grid>
      <n-form-item label="正文">
        <n-input v-model:value="form.body" type="textarea" :rows="3" />
      </n-form-item>
      <n-form-item label="发布范围">
        <n-select v-model:value="form.publish_scope" :options="['全体居民','指定小区','指定楼栋','仅老年端'].map(v=>({label:v,value:v}))" />
      </n-form-item>
      <n-checkbox v-model:checked="form.is_urgent">🚨 紧急通知（自动置顶 + 弹窗）</n-checkbox>
      <div style="margin-top:10px;">
        <n-button type="primary" :loading="creating" @click="create">📨 创建并发布</n-button>
      </div>
    </div>

    <n-spin :show="loading">
      <div v-for="n in list" :key="n.id" class="card" :style="n.is_urgent ? 'border-left:4px solid #dc2626;' : ''">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <b>{{ n.title }}</b>
            <n-tag v-if="n.is_urgent" type="error" size="small" style="margin-left:8px;">🚨 紧急</n-tag>
            <n-tag size="small" style="margin-left:4px;">{{ n.status }}</n-tag>
          </div>
          <span class="muted" style="font-size:0.8rem;">
            已读 {{ (n.stats && n.stats.resident_read) || 0 }} / 未读 {{ (n.stats && n.stats.resident_unread) || 0 }}
          </span>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ n.notice_type }} · {{ (n.published_at || n.created_at || '').slice(0, 16) }}</div>
        <div style="margin-top:8px;">{{ n.body }}</div>
        <div style="margin-top:10px;display:flex;gap:8px;">
          <n-popconfirm v-if="n.status === '已发布'" @positive-click="act(n, { action: 'take_down', reason: '演示下架' }, '已下架')">
            <template #trigger><n-button size="small" type="warning">⏬ 下架</n-button></template>
            下架后居民端不再显示，确认？
          </n-popconfirm>
          <n-button v-if="n.status === '已发布' && !n.is_pinned" size="small" @click="act(n, { action: 'pin' }, '已置顶')">📌 置顶</n-button>
          <n-button v-if="n.is_pinned" size="small" quaternary @click="act(n, { action: 'unpin' }, '已取消置顶')">📌 取消置顶</n-button>
        </div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="暂无通知" />
    </n-spin>
  </div>
</template>
