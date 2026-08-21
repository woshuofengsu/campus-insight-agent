<script setup>
// 政策问答管理：知识库维护（创建/审核/下架）+ 提问处理（回复）+ 统计与阈值
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { knowledge, qa } from '../../api'

const message = useMessage()
const kb = ref([])
const questions = ref([])
const stats = ref(null)
const threshold = ref(0.6)
const tab = ref('kb')
const replyMap = ref({}) // qid -> reply
const statsDays = ref(0)
const kForm = ref({
  title: '', category: '社保医保', plain_interpretation: '', content: '',
  summary: '', source: '社区整理', keywords: '', effective_date: '', expire_date: '',
  policy_number: '', attachment: '',
})
const kOp = ref({}) // kid -> {opinion, reason}

const KB_CATS = ['社保医保', '养老服务', '住房保障', '办事指引', '社区规定']

onMounted(async () => {
  try { kb.value = (await knowledge.list()) || [] } catch { /* 忽略 */ }
  try { questions.value = (await qa.questions()) || [] } catch { /* 忽略 */ }
  try {
    stats.value = await loadStats()
  } catch { /* 忽略 */ }
  try {
    const t = await qa.getThreshold()
    if (t && t.threshold != null) threshold.value = Number(t.threshold)
  } catch { /* 忽略 */ }
})

async function transfer(q) {
  try {
    await qa.transfer(q.id)
    message.success('已转人工')
  } catch (e) {
    message.error(e.message)
  }
}

async function reply(q) {
  const text = (replyMap.value[q.id] || '').trim()
  if (!text) return message.warning('请填写回复内容')
  try {
    await qa.reply(q.id, { reply: text })
    message.success(`提问 #${q.id} 已回复`)
    replyMap.value[q.id] = ''
    questions.value = (await qa.questions()) || []
  } catch (e) {
    message.error(e.message)
  }
}

async function loadStats() {
  return (await qa.stats({ days: statsDays.value })) || null
}

async function saveThreshold() {
  try {
    const r = await qa.setThreshold(threshold.value)
    message.success(`匹配阈值已更新为 ${r.threshold}`)
  } catch (e) {
    message.error(e.message)
  }
}

// 知识库管理
async function createKb() {
  const f = kForm.value
  if (!f.title || !f.plain_interpretation) return message.warning('请填写标题和通俗解读')
  try {
    await knowledge.create(f)
    message.success('已创建并提交审核')
    kForm.value = { title: '', category: '社保医保', plain_interpretation: '', content: '', summary: '', source: '社区整理', keywords: '', effective_date: '', expire_date: '', policy_number: '', attachment: '' }
    kb.value = (await knowledge.list()) || []
  } catch (e) {
    message.error(e.message)
  }
}

function kOpOf(k) {
  if (!kOp.value[k.id]) kOp.value[k.id] = {}
  return kOp.value[k.id]
}

async function kAct(k, data, okMsg) {
  try {
    await knowledge.action(k.id, data)
    message.success(okMsg || '操作成功')
    kb.value = (await knowledge.list()) || []
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📖 政策问答管理</h2>
    <p class="page-sub">知识库维护 + 居民提问处理 + 运行统计与阈值配置</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="kb" tab="知识库">
        <div class="card" style="margin-bottom:12px;">
          <div style="font-weight:700;margin-bottom:8px;">➕ 新建知识条目（创建即提交审核，审核人≠发布人）</div>
          <n-form label-placement="top">
            <n-grid :cols="2" :x-gap="12">
              <n-form-item-gi label="标题">
                <n-input v-model:value="kForm.title" placeholder="政策标题" />
              </n-form-item-gi>
              <n-form-item-gi label="分类">
                <n-select v-model:value="kForm.category" :options="KB_CATS.map(v=>({label:v,value:v}))" />
              </n-form-item-gi>
            </n-grid>
            <n-form-item label="通俗解读（必填）">
              <n-input v-model:value="kForm.plain_interpretation" type="textarea" :rows="2" placeholder="给居民看的一句话解读" />
            </n-form-item>
            <n-form-item label="正文">
              <n-input v-model:value="kForm.content" type="textarea" :rows="3" placeholder="政策原文/详细内容（选填）" />
            </n-form-item>
            <n-grid :cols="2" :x-gap="12">
              <n-form-item-gi label="来源">
                <n-input v-model:value="kForm.source" placeholder="社区整理" />
              </n-form-item-gi>
              <n-form-item-gi label="关键词（必填，逗号分隔 1-5 个）">
                <n-input v-model:value="kForm.keywords" placeholder="如：医保,报销,材料" />
              </n-form-item-gi>
            </n-grid>
            <n-grid :cols="2" :x-gap="12">
              <n-form-item-gi label="生效日期">
                <n-input v-model:value="kForm.effective_date" placeholder="如 2026-01-01" />
              </n-form-item-gi>
              <n-form-item-gi label="失效日期">
                <n-input v-model:value="kForm.expire_date" placeholder="如 2027-12-31（到期自动下架）" />
              </n-form-item-gi>
            </n-grid>
            <n-form-item label="政策文号（选填）">
              <n-input v-model:value="kForm.policy_number" placeholder="如 京人社发〔2026〕1号" />
            </n-form-item>
            <n-button type="primary" @click="createKb">📤 创建并提交审核</n-button>
          </n-form>
        </div>
        <div v-for="k in kb" :key="k.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ k.title }}</b>
            <n-tag size="small" :type="k.status === '已发布' ? 'success' : k.status === '待审核' ? 'warning' : 'default'">{{ k.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ k.category }} · {{ (k.updated_at || '').slice(0, 16) }}</div>
          <div style="margin-top:8px;font-size:0.9rem;">{{ k.plain_interpretation }}</div>
          <div v-if="k.audit_opinion" class="muted" style="font-size:0.8rem;margin-top:4px;">审核意见：{{ k.audit_opinion }}</div>
          <div v-if="['待审核', '已发布'].includes(k.status)" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <template v-if="k.status === '待审核'">
              <n-input v-model:value="kOpOf(k).opinion" placeholder="审核意见（退回必填）" size="small" style="max-width:220px;" />
              <n-button size="small" type="success" @click="kAct(k, { action: 'audit', approve: true, opinion: kOpOf(k).opinion || '同意' }, '已通过发布')">✅ 通过</n-button>
              <n-button size="small" type="warning" @click="kAct(k, { action: 'audit', approve: false, opinion: kOpOf(k).opinion || '请补充' }, '已退回')">↩️ 退回</n-button>
            </template>
            <template v-if="k.status === '已发布'">
              <n-input v-model:value="kOpOf(k).reason" placeholder="下架原因（必填）" size="small" style="max-width:200px;" />
              <n-popconfirm @positive-click="kAct(k, { action: 'offline', reason: kOpOf(k).reason || '内容过期' }, '已下架')">
                <template #trigger><n-button size="small" quaternary type="error">📛 下架</n-button></template>
                确认下架？将记录原因
              </n-popconfirm>
            </template>
          </div>
        </div>
        <n-empty v-if="kb.length === 0" description="暂无知识库条目" />
      </n-tab-pane>

      <n-tab-pane name="q" tab="提问处理">
        <div v-for="q in questions" :key="q.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ q.summary }}</b>
            <n-tag size="small" :type="q.status === '已转人工' || q.status === '超时未回复' ? 'warning' : q.status === '已回复' ? 'success' : 'default'">{{ q.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            {{ q.nickname_masked || q.nickname || '居民' }} · {{ q.q_type }} · {{ (q.created_at || '').slice(0, 16) }}
            <span v-if="q.remaining_hours != null" :style="q.overdue ? 'color:#dc2626;font-weight:700;' : ''">
              · {{ q.overdue ? `⏰ 超时 ${Math.abs(q.remaining_hours).toFixed(1)}h` : `⏳ 剩 ${q.remaining_hours.toFixed(1)}h` }}
            </span>
          </div>
          <div v-if="q.auto_answer" style="margin-top:6px;font-size:0.9rem;">🤖 自动回答：{{ q.auto_answer }}</div>
          <div v-if="q.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:8px;font-size:0.9rem;">
            💬 已回复：{{ q.reply }}
          </div>
          <div v-if="['待人工回复', '处理中', '已转人工', '超时未回复'].includes(q.status)" style="margin-top:10px;">
            <div style="display:flex;gap:8px;">
              <n-input v-model:value="replyMap[q.id]" placeholder="人工回复内容（≤2000字）" />
              <n-button type="primary" @click="reply(q)">💬 回复</n-button>
            </div>
          </div>
        </div>
        <n-empty v-if="questions.length === 0" description="暂无提问" />
      </n-tab-pane>

      <n-tab-pane name="stats" tab="统计与阈值">
        <div style="display:flex;gap:8px;margin-bottom:12px;">
          <n-radio-group v-model:value="statsDays" @update:value="async () => { stats.value = await loadStats() }">
            <n-radio :value="0">全部</n-radio>
            <n-radio :value="7">近 7 天</n-radio>
            <n-radio :value="30">近 30 天</n-radio>
          </n-radio-group>
        </div>
        <div v-if="stats" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:16px;">
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;">{{ stats.total_questions }}</div>
            <div class="muted" style="font-size:0.85rem;">累计提问</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#4caf50;">{{ stats.auto_success }}</div>
            <div class="muted" style="font-size:0.85rem;">自动回答成功</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#f59e0b;">{{ stats.transferred }}</div>
            <div class="muted" style="font-size:0.85rem;">转人工</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#ef4444;">{{ stats.match_failed }}</div>
            <div class="muted" style="font-size:0.85rem;">匹配失败</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#ef4444;">{{ stats.unhelpful }}</div>
            <div class="muted" style="font-size:0.85rem;">居民点无帮助</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;">{{ stats.avg_reply_hours ?? '—' }}</div>
            <div class="muted" style="font-size:0.85rem;">平均回复(小时)</div>
          </div>
        </div>

        <div class="card" v-if="stats && stats.trend && stats.trend.length">
          <div style="font-weight:700;margin-bottom:8px;">📈 近 8 天提问趋势</div>
          <div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding-top:8px;">
            <div v-for="p in stats.trend" :key="p.day" style="flex:1;text-align:center;">
              <div style="font-size:0.8rem;color:#888;">{{ p.count }}</div>
              <div :style="{ height: Math.max(4, p.count * 18) + 'px', background: '#4caf50', borderRadius: '4px 4px 0 0' }"></div>
              <div style="font-size:0.7rem;color:#999;margin-top:4px;">{{ p.day.slice(5) }}</div>
            </div>
          </div>
        </div>

        <div class="card" v-if="stats && stats.expiring && stats.expiring.length">
          <div style="font-weight:700;margin-bottom:8px;">⏳ 7 天内到期知识条目</div>
          <div v-for="e in stats.expiring" :key="e.id" style="padding:4px 0;display:flex;justify-content:space-between;">
            <span>{{ e.title }}</span>
            <span class="muted" style="font-size:0.85rem;">到期 {{ e.expire_date }}</span>
          </div>
        </div>

        <div class="card" v-if="stats && stats.match_failed_list && stats.match_failed_list.length">
          <div style="font-weight:700;margin-bottom:8px;">❌ 匹配失败明细（留痕）</div>
          <div v-for="f in stats.match_failed_list" :key="f.id" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
            <b>{{ f.actor || '居民' }}</b>：{{ f.detail }}
            <span class="muted" style="font-size:0.8rem;"> · {{ (f.created_at || '').slice(0, 16) }}</span>
          </div>
        </div>

        <div class="card" v-if="stats && stats.unhelpful_list && stats.unhelpful_list.length">
          <div style="font-weight:700;margin-bottom:8px;">👎 居民点「无帮助」明细（留痕）</div>
          <div v-for="(f, i) in stats.unhelpful_list" :key="i" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
            <b>{{ f.actor || '居民' }}</b> 对「{{ f.target_title || '—' }}」：{{ f.detail }}
            <span class="muted" style="font-size:0.8rem;"> · {{ (f.created_at || '').slice(0, 16) }}</span>
          </div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">🎚️ 自动回答匹配阈值</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
            <n-slider v-model:value="threshold" :min="0.1" :max="5" :step="0.1" style="max-width:320px;flex:1;" />
            <span style="min-width:60px;font-weight:700;">{{ threshold.toFixed(2) }}</span>
            <n-button type="primary" size="small" @click="saveThreshold">保存阈值</n-button>
          </div>
          <div class="muted" style="font-size:0.8rem;margin-top:6px;">数值越高要求越严格（相似度不足时自动回答判为失败并留痕转人工）。</div>
        </div>

        <n-empty v-if="!stats" description="暂无统计数据" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
