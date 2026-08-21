<script setup>
// 通知管理：创建发布（含紧急/定时/附件）+ 列表（筛选/已读统计/导出）+ 下架/撤回/置顶 + 详情
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { notices, upload, exportApi } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const detail = ref(null)
const files = ref([])

const form = ref({
  title: '', notice_type: '社区公告', publish_scope: '全体居民', body: '',
  is_urgent: 0, elderly_summary: '', scheduled_at: '', attachment_json: '[]', scope_target_json: '[]',
})
const publishMode = ref('now') // now | schedule
const creating = ref(false)
// 筛选
const typeFilter = ref('全部')
const statusFilter = ref('全部')

const TYPES = ['社区公告', '活动通知', '停水停电通知', '紧急通知', '政策通知', '其他']
const STATUS_OPTIONS = ['全部', '草稿', '待发布', '已发布', '已下架']

const filtered = computed(() => {
  let arr = list.value
  if (typeFilter.value !== '全部') arr = arr.filter((n) => n.notice_type === typeFilter.value)
  if (statusFilter.value !== '全部') arr = arr.filter((n) => n.status === statusFilter.value)
  return arr
})

async function load() {
  loading.value = true
  try { list.value = (await notices.manage()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(() => {
  load()
  // 已发布 30 秒 / 紧急 10 秒自动刷新
  setInterval(load, 30000)
  setInterval(() => {
    if (list.value.some((n) => n.is_urgent)) load()
  }, 10000)
})

async function create() {
  if (!form.value.title || !form.value.body) return message.warning('请填写标题和正文')
  if (form.value.is_urgent && !form.value.elderly_summary) return message.warning('紧急通知必填老年端播报摘要')
  if (publishMode.value === 'schedule' && !form.value.scheduled_at) return message.warning('定时发布请选择时间')
  creating.value = true
  try {
    // 附件上传
    if (files.value.length) {
      const up = await upload(files.value.map((f) => f.file), 'notices')
      form.value.attachment_json = JSON.stringify(up.paths || [])
    }
    await notices.create({ ...form.value, scheduled_at: publishMode.value === 'schedule' ? form.value.scheduled_at : '' })
    message.success(publishMode.value === 'schedule' ? '通知已创建并定时发布' : '通知已创建并发布')
    form.value = { title: '', notice_type: '社区公告', publish_scope: '全体居民', body: '', is_urgent: 0, elderly_summary: '', scheduled_at: '', attachment_json: '[]', scope_target_json: '[]' }
    files.value = []
    publishMode.value = 'now'
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

async function showDetail(n) {
  try { detail.value = await notices.detail(n.id) } catch (e) { message.error(e.message) }
}

function atts(n) {
  try { return JSON.parse(n.attachment_json || '[]') } catch { return [] }
}

async function exportNotices() {
  try {
    const blob = await exportApi.notices()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'notices.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📢 通知管理</h2>
    <p class="page-sub">发布公告、活动、停水停电与紧急通知（含定时发布）</p>

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
      <n-form-item label="附件（选填，jpg/png，≤5MB，最多3张）">
        <n-upload v-model:file-list="files" accept="image/jpeg,image/png" :max="3"
                  list-type="image-card" :default-upload="false" />
      </n-form-item>
      <n-form-item label="发布范围">
        <n-select v-model:value="form.publish_scope" :options="['全体居民','指定小区','指定楼栋','仅老年端'].map(v=>({label:v,value:v}))" />
      </n-form-item>
      <n-checkbox v-model:checked="form.is_urgent">🚨 紧急通知（自动置顶 + 弹窗，需二次确认）</n-checkbox>
      <n-form-item v-if="form.is_urgent" label="老年端播报摘要（紧急必填，≤30字）">
        <n-input v-model:value="form.elderly_summary" maxlength="30" placeholder="口语化一句话" />
      </n-form-item>
      <div style="display:flex;gap:10px;align-items:center;margin-top:4px;">
        <n-radio-group v-model:value="publishMode">
          <n-radio value="now">立即发布</n-radio>
          <n-radio value="schedule">定时发布</n-radio>
        </n-radio-group>
        <n-input v-if="publishMode === 'schedule'" v-model:value="form.scheduled_at" placeholder="定时时间，如 2026-08-22 09:00" style="max-width:240px;" />
      </div>
      <div style="margin-top:10px;">
        <n-popconfirm v-if="form.is_urgent" @positive-click="create" :positive-button-props="{ type: 'error' }">
          <template #trigger>
            <n-button type="error" :loading="creating">📨 {{ publishMode === 'schedule' ? '定时发布紧急通知' : '发布紧急通知' }}</n-button>
          </template>
          紧急通知将自动置顶并在居民端/老年端强制弹窗，确认内容无误？
        </n-popconfirm>
        <n-button v-else type="primary" :loading="creating" @click="create">📨 {{ publishMode === 'schedule' ? '创建并定时发布' : '创建并发布' }}</n-button>
      </div>
    </div>

    <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center;">
      <n-select v-model:value="typeFilter" :options="TYPES.map(v=>({label:v,value:v}))" style="width:150px;" />
      <n-select v-model:value="statusFilter" :options="STATUS_OPTIONS.map(v=>({label:v,value:v}))" style="width:120px;" />
      <n-button size="small" @click="exportNotices">⬇️ 导出</n-button>
      <span class="muted" style="font-size:0.8rem;">已发布 30 秒 / 紧急 10 秒自动刷新</span>
    </div>

    <n-spin :show="loading">
      <div v-for="n in filtered" :key="n.id" class="card" :style="n.is_urgent ? 'border-left:4px solid #dc2626;' : ''">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <div>
            <b style="cursor:pointer;" @click="showDetail(n)">{{ n.title }} ›</b>
            <n-tag v-if="n.is_urgent" type="error" size="small" style="margin-left:8px;">🚨 紧急</n-tag>
            <n-tag size="small" style="margin-left:4px;">{{ n.status }}</n-tag>
          </div>
          <span class="muted" style="font-size:0.8rem;">
            居民已读 {{ (n.stats && n.stats.resident_read) || 0 }}/{{ (n.stats && n.stats.resident_total) || 0 }} ·
            老年已读 {{ (n.stats && n.stats.elderly_read) || 0 }}/{{ (n.stats && n.stats.elderly_total) || 0 }}
          </span>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ n.notice_type }} · {{ (n.published_at || n.created_at || '').slice(0, 16) }}</div>
        <div style="margin-top:8px;">{{ n.body }}</div>
        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <n-input v-if="n.status === '已发布'" :value="n.downReason || ''" placeholder="下架原因（必填）" size="small" style="max-width:200px;" @update:value="(v) => (n.downReason = v)" />
          <n-popconfirm v-if="n.status === '已发布'" @positive-click="act(n, { action: 'take_down', reason: n.downReason || '内容更新' }, '已下架')">
            <template #trigger><n-button size="small" type="warning">⏬ 下架</n-button></template>
            下架后居民端不再显示，将记录原因，确认？
          </n-popconfirm>
          <n-button v-if="n.status === '已发布' && !n.is_pinned" size="small" @click="act(n, { action: 'pin' }, '已置顶')">📌 置顶</n-button>
          <n-button v-if="n.is_pinned" size="small" quaternary @click="act(n, { action: 'unpin' }, '已取消置顶')">📌 取消置顶</n-button>
          <n-popconfirm v-if="n.status === '待发布'" @positive-click="act(n, { action: 'withdraw' }, '已撤回为草稿')">
            <template #trigger><n-button size="small">⏪ 撤回</n-button></template>
            撤回为草稿？
          </n-popconfirm>
          <n-button v-if="n.status === '待发布'" size="small" type="primary" @click="act(n, { action: 'publish', confirm_urgent: !!n.is_urgent }, '已发布')">🚀 立即发布</n-button>
          <!-- 草稿：可立即发布（含紧急通知，二次确认） -->
          <n-popconfirm v-if="n.status === '草稿'" @positive-click="act(n, { action: 'publish', confirm_urgent: !!n.is_urgent }, '已发布')">
            <template #trigger><n-button size="small" type="primary">🚀 发布</n-button></template>
            {{ n.is_urgent ? '紧急通知将自动置顶并强制弹窗，确认发布？' : '确认发布该通知？' }}
          </n-popconfirm>
          <n-popconfirm v-if="n.status === '草稿'" @positive-click="act(n, { action: 'delete' }, '已删除')">
            <template #trigger><n-button size="small" quaternary type="error">🗑️ 删除</n-button></template>
            删除该草稿？
          </n-popconfirm>
        </div>
      </div>
      <n-empty v-if="!loading && filtered.length === 0" description="暂无通知" />
    </n-spin>

    <!-- 详情弹窗（含附件/老年摘要） -->
    <n-modal :show="!!detail" @update:show="(v) => { if (!v) detail = null }" preset="card" style="width:600px;" :title="detail ? detail.title : ''">
      <template v-if="detail">
        <div style="margin-bottom:8px;">
          <n-tag size="small" :type="detail.is_urgent ? 'error' : 'default'">{{ detail.notice_type }}</n-tag>
          <n-tag size="small" style="margin-left:6px;">{{ detail.status }}</n-tag>
          <span class="muted" style="margin-left:8px;font-size:0.8rem;">{{ (detail.published_at || detail.created_at || '').slice(0, 16) }}</span>
        </div>
        <div style="font-size:0.95rem;line-height:1.8;white-space:pre-wrap;">{{ detail.body }}</div>
        <div v-if="detail.elderly_summary" style="margin-top:10px;font-size:0.9rem;color:#b45309;">🔊 老年端播报：{{ detail.elderly_summary }}</div>
        <div v-if="atts(detail).length" style="margin-top:10px;">
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:4px;">📎 附件</div>
          <div v-for="(a, i) in atts(detail)" :key="i" style="display:inline-block;margin-right:8px;">
            <img :src="a" style="max-width:140px;max-height:140px;border-radius:6px;border:1px solid var(--border);" :alt="'附件' + (i + 1)" />
          </div>
        </div>
        <div v-if="detail.read_stats" style="margin-top:10px;font-size:0.85rem;" class="muted">
          居民已读 {{ detail.read_stats.resident_read }}/{{ detail.read_stats.resident_total }} · 老年已读 {{ detail.read_stats.elderly_read }}/{{ detail.read_stats.elderly_total }}
        </div>
      </template>
    </n-modal>
  </div>
</template>
