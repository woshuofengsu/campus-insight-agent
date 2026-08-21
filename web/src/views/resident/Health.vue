<script setup>
// 健康防护：健康内容（分类筛选/详情/置顶角标）+ 咨询（字段齐全/紧急提示/附件/代报）+ 我的咨询（未读/反馈）
import { ref, onMounted } from 'vue'
import { useMessage, NModal } from 'naive-ui'
import { health, upload } from '../../api'

const message = useMessage()
const articles = ref([])
const myConsults = ref([])
const unread = ref(0)
const tab = ref('articles')
const typeFilter = ref('全部')
const detail = ref(null) // 内容详情弹窗

const TYPES = ['全部', '季节性疾病预防', '疫苗接种提醒', '传染病预警', '健康小贴士', '就医指引']
const CONSULT_TYPES = ['健康知识', '疫苗接种', '疾病症状', '就医指引', '其他']

const cform = ref({
  name: '', phone: '', consult_type: '健康知识', content: '',
  building: '', attachment_json: '[]',
  is_agent_report: false, agent_name: '', agent_phone: '', agent_relation: '',
})
const files = ref([])
const submitting = ref(false)
const submitted = ref(null) // 提交成功反馈
const fbReason = ref({}) // consult id -> reason

const TYPE_COLOR = {
  季节性疾病预防: 'info', 疫苗接种提醒: 'warning', 传染病预警: 'error',
  健康小贴士: 'success', 就医指引: 'primary',
}

onMounted(async () => {
  try { articles.value = (await health.articles()) || [] } catch { /* 忽略 */ }
  try { myConsults.value = (await health.consults()) || [] } catch { /* 忽略 */ }
  try { unread.value = (await health.unread()).count || 0 } catch { /* 忽略 */ }
})

async function loadArticles() {
  try {
    articles.value = (await health.articles({ content_type: typeFilter.value === '全部' ? '' : typeFilter.value })) || []
  } catch (e) { message.error(e.message) }
}

async function showDetail(a) {
  try { detail.value = await health.articleDetail(a.id) } catch (e) { message.error(e.message) }
}

async function submit() {
  if (cform.value.content.length < 5) return message.warning('请填写至少 5 字内容')
  if (!/^1\d{10}$/.test(cform.value.phone)) return message.warning('请输入正确的 11 位手机号')
  submitting.value = true
  try {
    // 附件上传
    if (files.value.length) {
      const up = await upload(files.value.map((f) => f.file), 'health')
      cform.value.attachment_json = JSON.stringify(up.paths || [])
    }
    const d = await health.createConsult({
      ...cform.value,
      is_agent_report: cform.value.is_agent_report ? 1 : 0,
    })
    submitted.value = d
    cform.value.content = ''
    myConsults.value = (await health.consults()) || []
  } catch (e) {
    message.error(e.message)
  } finally {
    submitting.value = false
  }
}

async function toggle(c, action) {
  try {
    await health.toggleConsult(c.id, { action })
    message.success('操作成功')
    myConsults.value = (await health.consults()) || []
  } catch (e) {
    message.error(e.message)
  }
}

async function fb(c, solved) {
  try {
    await health.feedbackConsult(c.id, { solved, reason: fbReason.value[c.id] || '问题仍未解决' })
    message.success('反馈已提交')
    myConsults.value = (await health.consults()) || []
  } catch (e) {
    message.error(e.message)
  }
}

function atts(c) {
  try { return JSON.parse(c.attachment_json || '[]') } catch { return [] }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🏥 健康防护</h2>
    <p class="page-sub">疾病预防内容 + 健康咨询（负责人 24 小时内回复）</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="articles" tab="健康知识">
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
          <n-select v-model:value="typeFilter" :options="TYPES.map(v=>({label:v,value:v}))" style="width:180px;" @update:value="loadArticles" />
        </div>
        <div v-for="a in articles" :key="a.id" class="card" style="cursor:pointer;" @click="showDetail(a)">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ a.title }}</b>
            <div>
              <n-tag v-if="a.is_pinned" size="small" type="error" style="margin-right:6px;">📌 置顶</n-tag>
              <n-tag size="small" :type="TYPE_COLOR[a.content_type] || 'default'">{{ a.content_type }}</n-tag>
            </div>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:6px;">{{ a.summary }}</div>
          <div class="muted" style="font-size:0.75rem;margin-top:4px;">
            来源：{{ a.source || '社区整理' }} · 发布：{{ (a.published_at || a.created_at || '').slice(0, 16) }}
          </div>
        </div>
        <n-empty v-if="articles.length === 0" description="暂无健康内容" />
      </n-tab-pane>

      <n-tab-pane name="ask" tab="健康咨询">
        <div class="card" style="border:1px solid #fca5a5;background:var(--card-bg);">
          <b>⚠️ 紧急情况提醒</b>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            如遇胸闷胸痛、呼吸困难、意识不清等急症，请立即拨打 <b>120</b> 急救电话，不要等待在线回复。
          </div>
        </div>
        <div class="card">
          <n-form label-placement="top">
            <n-form-item label="姓名">
              <n-input v-model:value="cform.name" placeholder="可为昵称" />
            </n-form-item>
            <n-form-item label="联系电话（必填，11 位手机号）">
              <n-input v-model:value="cform.phone" placeholder="11 位手机号" maxlength="11" />
            </n-form-item>
            <n-form-item label="咨询类型">
              <n-select v-model:value="cform.consult_type" :options="CONSULT_TYPES.map(v=>({label:v,value:v}))" />
            </n-form-item>
            <n-form-item label="咨询内容（5-500字）">
              <n-input v-model:value="cform.content" type="textarea" :rows="4" maxlength="500" show-count />
            </n-form-item>
            <n-form-item label="楼栋（选填）">
              <n-input v-model:value="cform.building" placeholder="比如：3号楼2单元" />
            </n-form-item>
            <n-form-item label="附件（选填，jpg/png，≤5MB，最多3张）">
              <n-upload v-model:file-list="files" accept="image/jpeg,image/png" :max="3"
                        list-type="image-card" :default-upload="false" />
            </n-form-item>
            <n-checkbox v-model:checked="cform.is_agent_report" style="margin-bottom:8px;">我是代报（帮家人咨询）</n-checkbox>
            <template v-if="cform.is_agent_report">
              <n-grid :cols="2" :x-gap="16">
                <n-form-item-gi label="代报人姓名">
                  <n-input v-model:value="cform.agent_name" />
                </n-form-item-gi>
                <n-form-item-gi label="代报人电话">
                  <n-input v-model:value="cform.agent_phone" />
                </n-form-item-gi>
              </n-grid>
              <n-form-item label="与咨询人关系">
                <n-input v-model:value="cform.agent_relation" placeholder="如：家人 / 邻居" />
              </n-form-item>
            </template>
            <n-button type="primary" block :loading="submitting" @click="submit">🩺 提交咨询</n-button>
          </n-form>
        </div>
        <!-- 提交成功反馈 -->
        <div v-if="submitted" class="card" style="border-color:#86efac;">
          <b style="color:#16a34a;">✅ 咨询已提交</b>
          <div class="muted" style="font-size:0.9rem;margin-top:6px;">
            编号：<b>{{ submitted.code }}</b> · 状态：待回复 · 类型：{{ submitted.consult_type || cform.consult_type }} · 提交时间：{{ new Date().toLocaleString('zh-CN') }}
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">负责人将在 24 小时内回复；附件仅负责人和您本人可见；待回复状态可撤回。</div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="mine">
        <template #tab>
          <n-badge :value="unread" :show="unread > 0">我的咨询</n-badge>
        </template>
        <div v-for="c in myConsults" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ c.code || ('#' + c.id) }}</b>
            <n-tag size="small" :type="c.status === '待回复' ? 'warning' : c.status === '已回复' ? 'success' : 'default'">{{ c.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:6px;">{{ c.content }}</div>
          <div v-if="atts(c).length" class="muted" style="font-size:0.75rem;margin-top:4px;">📎 附件 {{ atts(c).length }} 张（仅您和负责人可见）</div>
          <div v-if="c.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:8px;font-size:0.9rem;">
            💬 负责人：{{ c.reply }}
            <div v-if="c.doctor_guide" style="margin-top:4px;font-size:0.85rem;color:#b45309;">🏥 就医指引：{{ c.doctor_guide }}</div>
            <div v-if="c.need_offline" style="margin-top:4px;font-size:0.85rem;color:#dc2626;">⚠️ 建议尽快线下就医</div>
          </div>
          <!-- 反馈已解决/未解决 -->
          <div v-if="c.status === '已回复' && !c.solved_feedback" style="margin-top:8px;display:flex;gap:8px;align-items:center;">
            <span class="muted" style="font-size:0.85rem;">问题解决了吗？</span>
            <n-button size="small" type="success" @click="fb(c, true)">✅ 已解决</n-button>
            <n-input v-model:value="fbReason[c.id]" placeholder="未解决原因（必填）" size="small" style="max-width:200px;" />
            <n-button size="small" type="warning" @click="fb(c, false)">😕 未解决</n-button>
          </div>
          <div v-if="['待回复','已回复','超时未回复','已撤回'].includes(c.status)" style="margin-top:8px;display:flex;gap:8px;">
            <n-button v-if="c.status === '待回复'" size="small" quaternary @click="toggle(c, 'withdraw')">↩️ 撤回</n-button>
            <n-button v-if="c.status === '已撤回'" size="small" @click="toggle(c, 'reopen')">🔄 重新打开</n-button>
            <n-button v-if="['已回复','超时未回复'].includes(c.status)" size="small" @click="toggle(c, 'close')">✕ 关闭</n-button>
          </div>
        </div>
        <n-empty v-if="myConsults.length === 0" description="还没有咨询记录" />
      </n-tab-pane>
    </n-tabs>

    <!-- 内容详情弹窗 -->
    <n-modal :show="!!detail" @update:show="(v) => { if (!v) detail = null }" preset="card" style="width:640px;" :title="detail ? detail.title : ''">
      <template v-if="detail">
        <div style="margin-bottom:8px;">
          <n-tag size="small" :type="TYPE_COLOR[detail.content_type] || 'default'">{{ detail.content_type }}</n-tag>
          <n-tag size="small" type="success" style="margin-left:6px;">已审核</n-tag>
          <span class="muted" style="margin-left:8px;font-size:0.8rem;">来源：{{ detail.source || '社区整理' }}</span>
          <span v-if="detail.expire_at" class="muted" style="margin-left:8px;font-size:0.8rem;">有效期至 {{ detail.expire_at }}</span>
        </div>
        <div style="line-height:1.9;font-size:0.95rem;white-space:pre-wrap;">{{ detail.body }}</div>
        <div class="muted" style="font-size:0.75rem;margin-top:12px;">* 本内容由社区整理发布，仅供健康科普参考，不构成医疗建议；如有不适请及时就医。</div>
      </template>
    </n-modal>
  </div>
</template>
