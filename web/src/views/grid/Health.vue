<script setup>
// 健康管理：咨询处理（脱敏/筛选/详情/就医指引回复）+ 内容管理（创建/审核/置顶/下架/撤回）+ 天气联动
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { health, exportApi } from '../../api'

const message = useMessage()
const tab = ref('consults')
// 咨询
const consults = ref([])
const statusFilter = ref('全部')
const typeFilter = ref('全部')
const keyword = ref('')
const replyMap = ref({})
const offlineMap = ref({}) // cid -> doctor_guide
const offlineCheck = ref({}) // cid -> confirmed
const cDetail = ref(null) // 咨询详情弹窗
const CONSULT_STATUS = ['全部', '待回复', '已回复', '超时未回复', '已结束', '已撤回', '已关闭']
const CONSULT_TYPES = ['全部', '健康知识', '疫苗接种', '疾病症状', '就医指引', '其他']
// 内容
const contents = ref([])
const cStatus = ref('全部')
const CONTENT_STATUS = ['全部', '草稿', '待审核', '已发布', '已下架']
const CONTENT_TYPES = ['季节性疾病预防', '疫苗接种提醒', '传染病预警', '健康小贴士', '就医指引']
const newForm = ref({
  title: '', content_type: '健康小贴士', body: '', summary: '',
  source: '社区整理', is_pinned: 0, expire_at: '', info_updated_at: '',
  elderly_reminder_text: '', weather_link_json: '[]',
})
const cOp = ref({}) // cid -> {opinion, reason, weatherLinks}

function cOpOf(c) {
  if (!cOp.value[c.id]) cOp.value[c.id] = {}
  return cOp.value[c.id]
}
// 联动
const linkage = ref([])
const thresh = ref({ high_temp: 35, low_temp: 5, temp_drop: 8 })
const linkOp = ref({})
const LINK_KEYS = ['天气转冷', '高温', '暴雨', '台风', '寒潮', '大风', '大雾', '雷电', '冰雹']
const selKey = ref('高温')
const selAction = ref('close')

async function loadAll() {
  try { consults.value = (await health.consults()) || [] } catch { /* 忽略 */ }
  try { contents.value = (await health.articles()) || [] } catch { /* 忽略 */ }
  try { linkage.value = (await health.linkageRecords()) || [] } catch { /* 忽略 */ }
  try { thresh.value = { ...thresh.value, ...((await health.linkageThresholds()) || {}) } } catch { /* 忽略 */ }
}
onMounted(loadAll)

const filteredConsults = () => {
  let arr = consults.value
  if (statusFilter.value !== '全部') arr = arr.filter((c) => c.status === statusFilter.value)
  if (typeFilter.value !== '全部') arr = arr.filter((c) => c.consult_type === typeFilter.value)
  if (keyword.value) arr = arr.filter((c) => [c.name, c.content, c.phone].some((s) => (s || '').includes(keyword.value)))
  return arr
}

async function loadConsults() {
  try {
    consults.value = (await health.consults({
      status: statusFilter.value === '全部' ? '' : statusFilter.value,
      consult_type: typeFilter.value === '全部' ? '' : typeFilter.value,
      keyword: keyword.value,
    })) || []
  } catch (e) { message.error(e.message) }
}

async function showDetail(c) {
  try { cDetail.value = await health.consultDetail(c.id) } catch (e) { message.error(e.message) }
}

async function reply(c) {
  const text = (replyMap.value[c.id] || '').trim()
  if (!text) return message.warning('请填写回复建议')
  const needOffline = !!offlineMap.value[c.id]
  if (needOffline && !offlineCheck.value[c.id]) {
    return message.warning('建议线下就医需二次确认（勾选确认框）')
  }
  try {
    await health.replyConsult(c.id, {
      reply: text,
      doctor_guide: offlineMap.value[c.id] || '',
      need_offline: needOffline,
      offline_confirmed: !!offlineCheck.value[c.id],
    })
    message.success(`咨询 ${c.code || '#' + c.id} 已回复`)
    replyMap.value[c.id] = ''
    offlineMap.value[c.id] = ''
    offlineCheck.value[c.id] = false
    loadConsults()
  } catch (e) {
    message.error(e.message)
  }
}

// ---- 内容管理 ----
const fContents = () => {
  let arr = contents.value
  if (cStatus.value !== '全部') arr = arr.filter((c) => c.status === cStatus.value)
  return arr
}
async function loadContents() {
  try {
    contents.value = (await health.articles({ status: cStatus.value === '全部' ? '' : cStatus.value })) || []
  } catch (e) { message.error(e.message) }
}

async function createContent() {
  const f = newForm.value
  if (!f.title || !f.body) return message.warning('请填写标题和正文')
  try {
    await health.createArticle(f)
    message.success('已创建并提交审核（审核人：社区审核组）')
    newForm.value = { title: '', content_type: '健康小贴士', body: '', summary: '', source: '社区整理', is_pinned: 0, expire_at: '', info_updated_at: '', elderly_reminder_text: '', weather_link_json: '[]' }
    loadContents()
  } catch (e) {
    message.error(e.message)
  }
}

async function cAct(c, data, okMsg) {
  try {
    await health.articleAction(c.id, data)
    message.success(okMsg || '操作成功')
    loadContents()
  } catch (e) {
    message.error(e.message)
  }
}

// ---- 联动 ----
async function saveThresh() {
  try {
    await health.setLinkageThresholds({
      high_temp: Number(thresh.value.high_temp),
      low_temp: Number(thresh.value.low_temp),
      temp_drop: Number(thresh.value.temp_drop),
    })
    message.success('阈值已更新（立即生效留痕）')
  } catch (e) {
    message.error(e.message)
  }
}

async function linkManual(action) {
  try {
    await health.linkageAction(selKey.value, {
      action, reason: linkOp.value['_manual'] || '演示关闭',
    })
    message.success('操作成功（留痕）')
    linkage.value = (await health.linkageRecords()) || []
  } catch (e) {
    message.error(e.message)
  }
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = name; a.click()
  URL.revokeObjectURL(url)
}

function attsOf(c) {
  try { return JSON.parse(c.attachment_json || '[]') } catch { return [] }
}

async function exportConsults() {
  try { downloadBlob(await exportApi.healthConsults(), 'health-consults.csv') }
  catch (e) { message.error(e.message) }
}

async function exportContents() {
  try { downloadBlob(await exportApi.healthContents(), 'health-contents.csv') }
  catch (e) { message.error(e.message) }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🏥 健康管理</h2>
    <p class="page-sub">咨询处理 · 内容审核 · 天气联动（24 小时内回复）</p>

    <n-tabs v-model:value="tab" type="line">
      <!-- 咨询处理 -->
      <n-tab-pane name="consults" tab="咨询处理">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center;">
          <n-select v-model:value="statusFilter" :options="CONSULT_STATUS.map(v=>({label:v,value:v}))" style="width:130px;" @update:value="loadConsults" />
          <n-select v-model:value="typeFilter" :options="CONSULT_TYPES.map(v=>({label:v,value:v}))" style="width:140px;" @update:value="loadConsults" />
          <n-input v-model:value="keyword" placeholder="搜索姓名/电话/内容" clearable style="flex:1;min-width:160px;" @keyup.enter="loadConsults" />
          <n-button size="small" @click="loadConsults">搜索</n-button>
          <n-button size="small" @click="exportConsults">⬇️ 导出咨询</n-button>
        </div>
        <div v-for="c in filteredConsults()" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b style="cursor:pointer;" @click="showDetail(c)">{{ c.code || ('#' + c.id) }} ›</b>
            <n-tag size="small" :type="c.status === '待回复' ? 'warning' : c.status === '已回复' ? 'success' : c.status === '超时未回复' ? 'error' : 'default'">{{ c.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ c.name }} · {{ c.phone }} · {{ c.consult_type }} · {{ (c.created_at || '').slice(0, 16) }}</div>
          <!-- 列表不直接展示全文（spec：列表不展示内容和附件） -->
          <div style="margin-top:8px;" class="muted">{{ (c.content || '').slice(0, 50) }}{{ (c.content || '').length > 50 ? '…' : '' }} <n-button size="tiny" text @click="showDetail(c)">查看详情</n-button></div>
          <div v-if="c.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:8px;font-size:0.9rem;">
            💬 已回复：{{ c.reply }}
            <div v-if="c.doctor_guide" style="margin-top:4px;font-size:0.85rem;color:#b45309;">🏥 就医指引：{{ c.doctor_guide }}</div>
          </div>
          <div v-if="['待回复', '超时未回复'].includes(c.status)" style="margin-top:10px;">
            <div class="muted" style="font-size:0.75rem;margin-bottom:4px;">⚠️ 请勿进行疾病诊断，回复仅为健康建议</div>
            <div style="display:flex;gap:8px;">
              <n-input v-model:value="replyMap[c.id]" placeholder="输入回复建议..." />
              <n-button type="primary" @click="reply(c)">回复</n-button>
            </div>
            <div style="display:flex;gap:8px;align-items:center;margin-top:6px;">
              <n-input v-model:value="offlineMap[c.id]" placeholder="需线下就医时填写就医指引（选填）" size="small" style="flex:1;" />
              <n-checkbox v-model:checked="offlineCheck[c.id]">确认建议线下就医（二次确认）</n-checkbox>
            </div>
          </div>
        </div>
        <n-empty v-if="filteredConsults().length === 0" description="暂无咨询" />
      </n-tab-pane>

      <!-- 内容管理 -->
      <n-tab-pane name="contents" tab="内容管理">
        <div class="card" style="margin-bottom:12px;">
          <div style="font-weight:700;margin-bottom:8px;">➕ 新建内容（创建即提交审核，审核人≠发布人）</div>
          <n-grid :cols="2" :x-gap="12">
            <n-form-item-gi label="标题">
              <n-input v-model:value="newForm.title" placeholder="内容标题" />
            </n-form-item-gi>
            <n-form-item-gi label="类型">
              <n-select v-model:value="newForm.content_type" :options="CONTENT_TYPES.map(v=>({label:v,value:v}))" />
            </n-form-item-gi>
          </n-grid>
          <n-form-item label="正文">
            <n-input v-model:value="newForm.body" type="textarea" :rows="3" placeholder="正文内容（社区自编将自动加免责声明；疫苗/传染病类需权威来源）" />
          </n-form-item>
          <n-form-item label="摘要">
            <n-input v-model:value="newForm.summary" placeholder="列表展示摘要（选填）" />
          </n-form-item>
          <n-grid :cols="3" :x-gap="12">
            <n-form-item-gi label="来源">
              <n-input v-model:value="newForm.source" placeholder="社区整理" />
            </n-form-item-gi>
            <n-form-item-gi label="有效期至">
              <n-input v-model:value="newForm.expire_at" placeholder="如 2026-12-31" />
            </n-form-item-gi>
            <n-form-item-gi label="信息更新时间">
              <n-input v-model:value="newForm.info_updated_at" placeholder="如 2026-08-01" />
            </n-form-item-gi>
          </n-grid>
          <n-form-item label="老年端语音提醒文案（选填，口语化≤30字）">
            <n-input v-model:value="newForm.elderly_reminder_text" placeholder="如：天冷了，注意保暖，少出门" />
          </n-form-item>
          <n-checkbox v-model:checked="newForm.is_pinned" :checked-value="1" :unchecked-value="0">置顶展示</n-checkbox>
          <div style="margin-top:10px;">
            <n-button type="primary" @click="createContent">📤 创建并提交审核</n-button>
          </div>
        </div>

        <div style="display:flex;gap:8px;margin-bottom:12px;">
          <n-select v-model:value="cStatus" :options="CONTENT_STATUS.map(v=>({label:v,value:v}))" style="width:130px;" @update:value="loadContents" />
          <n-button size="small" @click="exportContents">⬇️ 导出内容</n-button>
        </div>
        <div v-for="c in fContents()" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ c.title }}</b>
            <div>
              <n-tag v-if="c.is_pinned" size="small" type="error" style="margin-right:6px;">📌 置顶</n-tag>
              <n-tag size="small">{{ c.status }}</n-tag>
            </div>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ c.content_type }} · 来源 {{ c.source || '社区整理' }} · {{ (c.created_at || '').slice(0, 16) }}</div>
          <div v-if="c.audit_opinion" class="muted" style="font-size:0.8rem;margin-top:4px;">审核意见：{{ c.audit_opinion }}</div>
          <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <template v-if="['待审核'].includes(c.status)">
              <n-input v-model:value="cOpOf(c).opinion" placeholder="审核意见（退回必填）" size="small" style="max-width:220px;" />
              <n-button size="small" type="success" @click="cAct(c, { action: 'audit', approve: true, opinion: cOpOf(c).opinion || '同意' }, '已通过并发布')">✅ 通过发布</n-button>
              <n-button size="small" type="warning" @click="cAct(c, { action: 'audit', approve: false, opinion: cOpOf(c).opinion || '请补充' }, '已退回')">↩️ 退回</n-button>
              <n-button size="small" quaternary @click="cAct(c, { action: 'withdraw' }, '已撤回审核，转草稿')">⏪ 撤回审核</n-button>
            </template>
            <template v-if="['草稿'].includes(c.status)">
              <n-popconfirm @positive-click="cAct(c, { action: 'delete' }, '已删除草稿')">
                <template #trigger><n-button size="small" quaternary type="error">🗑️ 删除草稿</n-button></template>
                确认删除草稿？
              </n-popconfirm>
            </template>
            <template v-if="['已发布'].includes(c.status)">
              <n-button size="small" @click="cAct(c, { action: c.is_pinned ? 'unpin' : 'pin' }, c.is_pinned ? '已取消置顶' : '已置顶')">📌 {{ c.is_pinned ? '取消置顶' : '置顶' }}</n-button>
              <n-input v-model:value="cOpOf(c).reason" placeholder="下架原因（必填）" size="small" style="max-width:180px;" />
              <n-popconfirm @positive-click="cAct(c, { action: 'offline', reason: cOpOf(c).reason || '内容过期' }, '已下架')">
                <template #trigger><n-button size="small" quaternary type="error">📛 下架</n-button></template>
                确认下架？将记录原因
              </n-popconfirm>
            </template>
          </div>
        </div>
        <n-empty v-if="fContents().length === 0" description="暂无内容" />
      </n-tab-pane>

      <!-- 天气联动 -->
      <n-tab-pane name="linkage" tab="天气联动">
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">🎚️ 联动阈值（预警生效≤12h / 高温≥35℃ / 低温≤5℃ / 24h降温≥8℃）</div>
          <div style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
            <span>高温 ≥ <n-input-number v-model:value="thresh.high_temp" size="small" style="width:90px;" />℃</span>
            <span>低温 ≤ <n-input-number v-model:value="thresh.low_temp" size="small" style="width:90px;" />℃</span>
            <span>降温 ≥ <n-input-number v-model:value="thresh.temp_drop" size="small" style="width:90px;" />℃</span>
            <n-button size="small" type="primary" @click="saveThresh">保存阈值</n-button>
          </div>
          <div class="muted" style="font-size:0.8rem;margin-top:6px;">仅疾病预防负责人可配置，调整立即生效并留痕。</div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">🛠️ 手动关闭/重开联动（二次确认留痕）</div>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <n-select v-model:value="selKey" :options="LINK_KEYS.map(v=>({label:v,value:v}))" size="small" style="width:130px;" />
            <n-select v-model:value="selAction" :options="[{label:'关闭',value:'close'},{label:'重新开启',value:'reopen'}]" size="small" style="width:110px;" />
            <n-input v-model:value="linkOp._manual" placeholder="关闭原因（关闭时必填）" size="small" style="max-width:200px;" />
            <n-popconfirm @positive-click="linkManual(selAction)">
              <template #trigger><n-button size="small" type="primary">确认执行</n-button></template>
              确认{{ selAction === 'close' ? '关闭' : '重新开启' }}{{ selKey }}联动？（二次确认并留痕）
            </n-popconfirm>
          </div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">📡 联动留痕记录（触发/关闭/重开/阈值调整）</div>
          <div v-for="r in linkage" :key="r.id" style="padding:8px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
            <b>{{ r.action || '' }}</b>
            <span class="muted" style="margin-left:8px;font-size:0.85rem;">{{ r.detail || '' }}</span>
            <div class="muted" style="font-size:0.8rem;margin-top:2px;">{{ r.actor || '' }} · {{ (r.created_at || '').slice(0, 16) }}</div>
          </div>
          <n-empty v-if="linkage.length === 0" description="暂无联动留痕记录" />
        </div>
      </n-tab-pane>
    </n-tabs>

    <!-- 咨询详情弹窗 -->
    <n-modal :show="!!cDetail" @update:show="(v) => { if (!v) cDetail = null }" preset="card" style="width:600px;" :title="cDetail ? (cDetail.code || ('#' + cDetail.id)) : ''">
      <template v-if="cDetail">
        <div style="margin-bottom:8px;">
          <n-tag size="small" :type="cDetail.status === '待回复' ? 'warning' : cDetail.status === '已回复' ? 'success' : 'default'">{{ cDetail.status }}</n-tag>
          <span class="muted" style="margin-left:8px;font-size:0.85rem;">{{ cDetail.name }} · {{ cDetail.phone }} · {{ cDetail.consult_type }}</span>
        </div>
        <div style="font-size:0.95rem;line-height:1.8;white-space:pre-wrap;">{{ cDetail.content }}</div>
        <!-- 附件（仅处理人可见） -->
        <div v-if="attsOf(cDetail).length" style="margin-top:10px;">
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:4px;">📎 附件</div>
          <div v-for="(a, i) in attsOf(cDetail)" :key="i" style="display:inline-block;margin-right:8px;">
            <img :src="a" style="max-width:140px;max-height:140px;border-radius:6px;border:1px solid var(--border);" />
          </div>
        </div>
        <div v-if="cDetail.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:10px;">
          💬 回复：{{ cDetail.reply }}
          <div v-if="cDetail.doctor_guide" style="margin-top:4px;color:#b45309;">🏥 就医指引：{{ cDetail.doctor_guide }}</div>
          <div v-if="cDetail.need_offline" style="margin-top:4px;color:#dc2626;">⚠️ 已建议尽快线下就医</div>
        </div>
        <div v-if="cDetail.feedback" style="margin-top:10px;font-size:0.9rem;">
          居民反馈：{{ cDetail.feedback === '已解决' ? '✅ 已解决' : '😕 未解决' }}<span v-if="cDetail.feedback_reason">（{{ cDetail.feedback_reason }}）</span>
        </div>
      </template>
    </n-modal>
  </div>
</template>
