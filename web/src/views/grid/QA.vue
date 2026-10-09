<script setup>
// 政策问答管理：知识库维护（创建/审核/下架）+ 提问处理（回复）+ 统计与阈值
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { knowledge, qa, agent, issues } from '../../api'
import EIcon from '../../components/EIcon.vue'

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
  // 属地（地区识别 WS7）：适用地区，决定"属地优先"时这条政策为谁优先
  applicable_area: '全国',
})
const kOp = ref({}) // kid -> {opinion, reason}

const KB_CATS = ['社保医保', '养老服务', '住房保障', '办事指引', '社区规定']
// 适用地区候选（可自由输入，兼容存量自由文本）：全国 = 无属地偏好，越具体越优先
const AREA_OPTIONS = ['全国', '北京市', '北京市海淀区', '北京市朝阳区', '海淀小区'].map(v => ({ label: v, value: v }))

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
  await loadProfile()   // 同类处置画像：进页面就给一份"全部"的口径
  await loadCorr()      // 人工修正对照清单：进页面就给一份本社区的口径
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
    kForm.value = { title: '', category: '社保医保', plain_interpretation: '', content: '', summary: '', source: '社区整理', keywords: '', effective_date: '', expire_date: '', policy_number: '', attachment: '', applicable_area: '全国' }
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

// 版本管理
const verModal = ref(null) // { mode: 'new'|'list', k, versions, form }
const kForm2 = ref({})

async function newVersionOf(k) {
  kForm2.value = { ...kForm.value, title: k.title, plain_interpretation: k.plain_interpretation, category: k.category }
  verModal.value = { mode: 'new', k }
}

async function submitNewVersion() {
  const k = verModal.value.k
  const f = kForm2.value
  if (!f.title || !f.plain_interpretation) return message.warning('请填写标题和通俗解读')
  if (!f.keywords) return message.warning('请填写关键词（必填，1-5 个）')
  try {
    await knowledge.newVersion(k.id, f)
    message.success('新版本已创建并提交审核，审核通过自动替换旧版')
    verModal.value = null
    kb.value = (await knowledge.list()) || []
  } catch (e) {
    message.error(e.message)
  }
}

async function showVersions(k) {
  try {
    const versions = (await knowledge.versions(k.id)) || []
    verModal.value = { mode: 'list', k, versions }
  } catch (e) {
    message.error(e.message)
  }
}

// U6 知识图谱：实体关联查询（如「3号楼 电梯」→ 相关工单/政策/关联实体）
const kgQuery = ref('')
const kgResult = ref(null)
const kgLoading = ref(false)

// 同类问题处置画像（v52 沉淀）：按分类看历史处置，把经验变成可查询结构
const profileCat = ref('')
const profileLoading = ref(false)
const profile = ref({ category: '全部', days: 180, total: 0, resolved: 0, resolved_rate: 0,
                      avg_hours: null, overdue: 0, overdue_rate: 0, third_party: 0,
                      third_party_rate: 0, top_assignees: [], top_keywords: [],
                      categories: [], note: '' })
const profileOptions = ref([{ label: '全部分类', value: '' }])
async function loadProfile() {
  profileLoading.value = true
  try {
    const r = (await issues.knowledge({ category: profileCat.value || '', days: 180 })) || {}
    profile.value = { ...profile.value, ...r }
    if (r.categories && r.categories.length) {
      profileOptions.value = [{ label: '全部分类', value: '' },
        ...r.categories.map((c) => ({ label: `${c.category}（${c.count}）`, value: c.category }))]
    }
  } catch (e) {
    message.error(e.message)
  } finally {
    profileLoading.value = false
  }
}
// 人工修正对照清单（第 7 阶段）：系统建议分类 vs 人工最终分类
const corr = ref({ total: 0, with_suggestion: 0, no_suggestion: 0, corrected: 0, agreed: 0,
                   coverage: 0, agreement_rate: 0, corrected_rate: 0, pairs: [], items: [],
                   unlogged_changes: 0, sample_enough: false, note: '', disclaimer: '', days: 180,
                   demo: { total: 0, with_suggestion: 0 }, real: { total: 0, with_suggestion: 0,
                                                                  coverage: 0, agreement_rate: 0 },
                   demo_note: '' })
const corrLoading = ref(false)
async function loadCorr() {
  corrLoading.value = true
  try {
    corr.value = { ...corr.value, ...((await issues.categoryCorrections({ days: 180, limit: 50 })) || {}) }
  } catch (e) {
    message.error(e.message)
  } finally {
    corrLoading.value = false
  }
}

async function kgSearch() {
  const q = kgQuery.value.trim()
  if (!q) return message.warning('请输入实体，如「3号楼」「电梯」「加装电梯」')
  kgLoading.value = true
  try {
    kgResult.value = await agent.kgEntity(q)
  } catch (e) {
    message.error(e.message)
    kgResult.value = null
  } finally {
    kgLoading.value = false
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title"><EIcon name="book" :size="18" /> 政策问答管理</h2>
    <p class="page-sub">知识库维护 + 居民提问处理 + 运行统计与阈值配置</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="kb" tab="知识库">
        <div class="card" style="margin-bottom:12px;">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="plus" :size="18" /> 新建知识条目（创建即提交审核，审核人≠发布人）</div>
          <n-form label-placement="top">
            <n-grid :cols="2" :x-gap="12">
              <n-form-item-gi label="标题">
                <n-input v-model:value="kForm.title" placeholder="政策标题" />
              </n-form-item-gi>
              <n-form-item-gi label="分类">
                <n-select v-model:value="kForm.category" :options="KB_CATS.map(v=>({label:v,value:v}))" />
              </n-form-item-gi>
            </n-grid>
            <n-grid :cols="2" :x-gap="12">
              <n-form-item-gi label="适用地区（属地优先）">
                <n-select v-model:value="kForm.applicable_area" filterable tag
                          :options="AREA_OPTIONS" placeholder="全国 / 北京市 / 北京市海淀区 / 海淀小区" />
              </n-form-item-gi>
              <n-form-item-gi label="说明">
                <span class="muted" style="font-size:0.8rem;line-height:1.6;">
                  越具体越优先：本社区 &gt; 区 &gt; 市 &gt; 全国。填「全国」表示对所有社区一致；
                  属地只影响排序，不会屏蔽其他地区的政策。
                </span>
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
            <n-button type="primary" @click="createKb"><EIcon name="send" :size="18" /> 创建并提交审核</n-button>
          </n-form>
        </div>
        <div v-for="k in kb" :key="k.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ k.title }}</b>
            <n-tag size="small" :type="k.status === '已发布' ? 'success' : k.status === '待审核' ? 'warning' : 'default'">{{ k.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            {{ k.category }} · {{ (k.updated_at || '').slice(0, 16) }}
            <!-- 属地（地区识别 WS7）：让"这条政策为谁优先"一眼可见 -->
            <n-tag v-if="k.applicable_area" size="tiny" :bordered="false" style="margin-left:6px;"><EIcon name="pin" :size="18" /> {{ k.applicable_area }}</n-tag>
          </div>
          <div style="margin-top:8px;font-size:0.9rem;">{{ k.plain_interpretation }}</div>
          <div v-if="k.audit_opinion" class="muted" style="font-size:0.8rem;margin-top:4px;">审核意见：{{ k.audit_opinion }}</div>
          <div v-if="['待审核', '已发布'].includes(k.status)" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <template v-if="k.status === '待审核'">
              <n-input v-model:value="kOpOf(k).opinion" placeholder="审核意见（退回必填）" size="small" style="max-width:220px;" />
              <n-button size="small" type="success" @click="kAct(k, { action: 'audit', approve: true, opinion: kOpOf(k).opinion || '同意' }, '已通过发布')"><EIcon name="checkCircle" :size="18" /> 通过</n-button>
              <n-button size="small" type="warning" @click="kAct(k, { action: 'audit', approve: false, opinion: kOpOf(k).opinion || '请补充' }, '已退回')"><EIcon name="arrowLeft" :size="18" />  退回</n-button>
              <n-button size="small" quaternary @click="kAct(k, { action: 'withdraw' }, '已撤回审核，转草稿')"><EIcon name="arrowLeft" :size="18" /> 撤回审核</n-button>
              <n-popconfirm @positive-click="kAct(k, { action: 'delete' }, '已删除草稿')">
                <template #trigger><n-button size="small" quaternary type="error"><EIcon name="trash" :size="18" /> 删除</n-button></template>
                确认删除该草稿？
              </n-popconfirm>
            </template>
            <template v-if="k.status === '已发布'">
              <n-input v-model:value="kOpOf(k).reason" placeholder="下架原因（必填）" size="small" style="max-width:200px;" />
              <n-popconfirm @positive-click="kAct(k, { action: 'offline', reason: kOpOf(k).reason || '内容过期' }, '已下架')">
                <template #trigger><n-button size="small" quaternary type="error"><EIcon name="ban" :size="18" /> 下架</n-button></template>
                确认下架？将记录原因
              </n-popconfirm>
              <n-button size="small" @click="newVersionOf(k)"><EIcon name="plusCircle" :size="18" /> 建新版本</n-button>
              <n-popconfirm @positive-click="showVersions(k)">
                <template #trigger><n-button size="small" quaternary><EIcon name="scroll" :size="18" /> 版本历史</n-button></template>
                查看版本历史？
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
            <span v-if="q.remaining_hours != null" :style="q.overdue ? 'color:var(--ink-danger);font-weight:700;' : ''">
              · {{ q.overdue ? `超时 ${Math.abs(q.remaining_hours).toFixed(1)}h` : `剩 ${q.remaining_hours.toFixed(1)}h` }}
            </span>
          </div>
          <div v-if="q.auto_answer" style="margin-top:6px;font-size:0.9rem;"><EIcon name="robot" :size="18" /> 自动回答：{{ q.auto_answer }}</div>
          <div v-if="q.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:8px;font-size:0.9rem;">
            <EIcon name="chat-dots" :size="18" /> 已回复：{{ q.reply }}
          </div>
          <div v-if="['待人工回复', '处理中', '已转人工', '超时未回复'].includes(q.status)" style="margin-top:10px;">
            <div style="display:flex;gap:8px;">
              <n-input v-model:value="replyMap[q.id]" placeholder="人工回复内容（≤2000字）" />
              <n-button type="primary" @click="reply(q)"><EIcon name="chat-dots" :size="18" /> 回复</n-button>
            </div>
          </div>
        </div>
        <n-empty v-if="questions.length === 0" description="暂无提问" />
      </n-tab-pane>

      <n-tab-pane name="kg" tab="知识图谱">
        <!-- 同类问题处置画像（v52 沉淀）：把散在处置说明里的经验变成可查询结构 -->
        <div class="card" style="margin-bottom:12px;" data-category-profile>
          <div style="font-weight:700;margin-bottom:6px;"><EIcon name="chart" :size="18" /> 同类问题处置画像</div>
          <div class="muted" style="font-size:0.85rem;margin-bottom:10px;">
            按分类看历史：办结率 / 平均时长 / 超时率 / 第三方责任占比 / 常见责任方 / 常见处置关键词。
            样本不足会明确标注，不拿两三条记录当规律。
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;">
            <n-select v-model:value="profileCat" :options="profileOptions" size="large" style="width:180px;"
                      @update:value="loadProfile" />
            <n-button type="primary" :loading="profileLoading" @click="loadProfile">查询</n-button>
            <span class="muted" style="font-size:0.82rem;align-self:center;">
              近 {{ profile.days }} 天 · 共 {{ profile.total }} 单
            </span>
          </div>
          <div v-if="profile.total" style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:10px;">
            <div><div style="font-weight:800;font-size:1.2rem;">{{ profile.resolved_rate }}%</div><div class="muted" style="font-size:0.8rem;">办结率（{{ profile.resolved }}/{{ profile.total }}）</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;">{{ profile.avg_hours ?? '—' }}</div><div class="muted" style="font-size:0.8rem;">平均处理小时</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;">{{ profile.overdue_rate }}%</div><div class="muted" style="font-size:0.8rem;">超时率（{{ profile.overdue }} 单）</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;">{{ profile.third_party_rate }}%</div><div class="muted" style="font-size:0.8rem;">第三方责任</div></div>
          </div>
          <div v-if="profile.total" style="margin-top:8px;font-size:0.85rem;">
            <div v-if="profile.top_assignees.length">
              常见责任方：<b v-for="a in profile.top_assignees" :key="a.name" style="margin-right:10px;">{{ a.name }}（{{ a.count }}）</b>
            </div>
            <div v-if="profile.top_keywords.length" class="muted" style="margin-top:4px;">
              常见处置关键词：{{ profile.top_keywords.map(k => k[0]).join(' · ') }}
            </div>
            <div v-if="profile.note" style="color:var(--ink-warning);margin-top:4px;">{{ profile.note }}</div>
          </div>
        </div>

        <div class="card" style="margin-bottom:12px;" data-cat-corrections>
          <div style="font-weight:700;margin-bottom:6px;"><EIcon name="checkCircle" :size="18" /> 人工修正对照清单</div>
          <div class="muted" style="font-size:0.85rem;margin-bottom:10px;">
            把「系统当初建议的分类」和「网格员最终用的分类」放在一起对账。
            <b>覆盖率必须和一致率一起看</b>：系统建议是 2026-09-29 之后才落库的，
            更早的工单没有建议值，只报一致率就是拿一小撮样本冒充全体。
            这张表只供人工核查，<b>不用于模型训练或调参</b>。
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
            <n-button type="primary" :loading="corrLoading" @click="loadCorr" data-corr-load>刷新</n-button>
            <span class="muted" style="font-size:0.82rem;">
              近 {{ corr.days }} 天 · 共 {{ corr.total }} 单
            </span>
          </div>
          <div style="margin-top:10px;display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;">
            <div><div style="font-weight:800;font-size:1.2rem;" data-corr-coverage>{{ corr.coverage }}%</div>
              <div class="muted" style="font-size:0.8rem;">建议覆盖率（{{ corr.with_suggestion }}/{{ corr.total }}）</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;" data-corr-agreement>{{ corr.agreement_rate }}%</div>
              <div class="muted" style="font-size:0.8rem;">一致率（未被人改）</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;" data-corr-corrected>{{ corr.corrected }}</div>
              <div class="muted" style="font-size:0.8rem;">被人工改过（{{ corr.corrected_rate }}%）</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;" data-corr-nosug>{{ corr.no_suggestion }}</div>
              <div class="muted" style="font-size:0.8rem;">无系统建议（人工自选）</div></div>
            <div><div style="font-weight:800;font-size:1.2rem;"
                      :style="corr.unlogged_changes ? 'color:var(--ink-danger);' : ''"
                      data-corr-unlogged>{{ corr.unlogged_changes }}</div>
              <div class="muted" style="font-size:0.8rem;">未留痕的改动（应为 0）</div></div>
          </div>
          <div v-if="corr.note" style="color:var(--ink-warning);margin-top:8px;font-size:0.85rem;" data-corr-note>{{ corr.note }}</div>
          <!-- 演示数据免责：**由数据驱动**（只要分母里有演示数据就必须显示，且四条缺一不可）
               注意：原来写 `background:var(--panel-lemon)`（变量不存在，一直没底色）；
               2026-10-06 由 ui_style_audit 的"未定义变量"判据抓出 → 改用 .panel-lemon class -->
          <div v-if="corr.demo && corr.demo.total" data-corr-demo class="panel-lemon"
               style="margin-top:10px;padding:10px 12px;border-radius:var(--r-xs);font-size:0.88rem;">
            <div style="font-weight:700;">
              <EIcon name="info" :size="16" /> 已标记演示数据 {{ corr.demo.total }} 条
            </div>
            <div style="margin-top:3px;">
              演示数据 · <b>不代表真实居民样本</b> · 不用于模型训练 · <b>不代表线上准确率</b>
            </div>
            <div class="muted" style="margin-top:3px;">
              两部分请分开看：已标记演示 {{ corr.demo.total }} 单（带系统建议 {{ corr.demo.with_suggestion }} 单）；
              未标记 {{ corr.real.total }} 单（带建议 {{ corr.real.with_suggestion }} 单，
              覆盖率 {{ corr.real.coverage }}%、一致率 {{ corr.real.agreement_rate }}%）。
              合在一起算会把自造样本算成真实样本。
            </div>
            <div class="muted" style="margin-top:3px;">
              （演示数据是走真实接口造出来的，所以接口/分类/留痕都是真的；但诉求内容不是真实居民提的。
              本机演示库里<b>未标记的那些</b>同样是演示/验证脚本产生的，不应当作真实居民数据引用。）
            </div>
          </div>
          <div v-if="corr.unlogged_changes" style="color:var(--ink-danger);margin-top:8px;font-size:0.85rem;" data-corr-anomaly>
            有 {{ corr.unlogged_changes }} 条分类变了但查不到留痕（说明存在绕过受控入口的写入路径，需要排查）
          </div>
          <div v-if="corr.pairs.length" style="margin-top:8px;font-size:0.85rem;" data-corr-pairs>
            常见改动：<b v-for="p in corr.pairs" :key="p.suggested + '>' + p.final" style="margin-right:12px;">
              {{ p.suggested }} → {{ p.final }}（{{ p.count }}）
            </b>
          </div>
          <div v-if="corr.items.length" style="margin-top:10px;overflow-x:auto;">
            <table style="width:100%;font-size:0.85rem;border-collapse:collapse;">
              <thead><tr class="muted" style="text-align:left;">
                <th style="padding:4px;">工单</th><th style="padding:4px;">摘要</th>
                <th style="padding:4px;">系统建议</th><th style="padding:4px;">最终分类</th>
                <th style="padding:4px;">改动人</th><th style="padding:4px;">改动时间</th>
              </tr></thead>
              <tbody>
                <tr v-for="it in corr.items" :key="it.issue_id" style="border-top:1px solid var(--border);">
                  <td style="padding:4px;">#{{ it.issue_id }}</td>
                  <td style="padding:4px;">{{ it.title || '—' }}</td>
                  <td style="padding:4px;">{{ it.suggested }}</td>
                  <td style="padding:4px;" :style="it.changed ? 'color:var(--ink-danger);font-weight:700;' : ''">
                    {{ it.final }}
                  </td>
                  <td style="padding:4px;">{{ it.changed_by || '—' }}</td>
                  <td style="padding:4px;">{{ it.changed_at || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-else class="muted" style="margin-top:8px;font-size:0.85rem;">
            近 180 天没有带系统建议的工单（清单为空是预期的：建议写入侧是 2026-09-29 才补的）
          </div>
          <div class="muted" style="margin-top:6px;font-size:0.8rem;">{{ corr.disclaimer }}</div>
        </div>

        <div class="card" style="margin-bottom:12px;">
          <div style="font-weight:700;margin-bottom:6px;"><EIcon name="network" :size="18" /> 实体关联查询</div>
          <div class="muted" style="font-size:0.85rem;margin-bottom:10px;">
            按实体反查业务对象：「3号楼」→ 该楼栋历史工单与相关设施；「电梯」「加装电梯」→ 相关工单 + 政策。
            支持复合查询（如「3号楼 电梯」= 同时提及两者的工单）。
          </div>
          <div style="display:flex;gap:8px;">
            <n-input v-model:value="kgQuery" placeholder="输入实体，如 3号楼 / 电梯 / 加装电梯 / 老人"
                     @keyup.enter="kgSearch" clearable />
            <n-button type="primary" :loading="kgLoading" @click="kgSearch">查询</n-button>
          </div>
        </div>

        <div v-if="kgResult && !kgResult.found" class="card">
          <div class="muted">{{ kgResult.hint || '图谱中未收录该实体' }}
            <span v-if="kgResult.graph_entities">（当前图谱含 {{ kgResult.graph_entities }} 个实体）</span>
          </div>
        </div>

        <template v-if="kgResult && kgResult.found">
          <div class="card" style="margin-bottom:12px;">
            <div style="font-size:0.9rem;">
              命中实体：<b v-for="e in kgResult.entities" :key="e.id" style="margin-right:8px;">
                {{ e.name }}<span class="muted">（{{ e.etype }}）</span></b>
              <span class="muted">· 匹配方式 {{ kgResult.match_mode }}</span>
            </div>
            <div v-if="kgResult.summary" class="muted" style="font-size:0.85rem;margin-top:6px;">{{ kgResult.summary }}</div>
          </div>

          <div class="card" style="margin-bottom:12px;" v-if="kgResult.related_issues && kgResult.related_issues.length">
            <div style="font-weight:700;margin-bottom:8px;"><EIcon name="wrench" :size="18" /> 关联工单（{{ kgResult.related_issues.length }}）</div>
            <div v-for="it in kgResult.related_issues.slice(0, 8)" :key="'i' + it.id"
                 style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
              #{{ it.id }} {{ it.title }}
              <span class="muted">（{{ it.status || '' }} · {{ it.location || '' }}）</span>
            </div>
          </div>

          <div class="card" style="margin-bottom:12px;" v-if="kgResult.related_knowledge && kgResult.related_knowledge.length">
            <div style="font-weight:700;margin-bottom:8px;"><EIcon name="file" :size="18" /> 关联政策（{{ kgResult.related_knowledge.length }}）</div>
            <div v-for="k in kgResult.related_knowledge.slice(0, 8)" :key="'k' + k.id"
                 style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
              {{ k.title }} <span class="muted">（{{ k.category || '' }}）</span>
            </div>
          </div>

          <div class="card" v-if="kgResult.related_entities && kgResult.related_entities.length">
            <div style="font-weight:700;margin-bottom:8px;"><EIcon name="link" :size="18" /> 关联实体</div>
            <div style="font-size:0.9rem;">
              <span v-for="re in kgResult.related_entities.slice(0, 15)" :key="re.name"
                    class="status-pill" style="background:#eef2ff;color:var(--ink-info);margin:0 6px 6px 0;display:inline-block;">
                {{ re.name }}<span class="muted"> · {{ re.rel }}</span>
              </span>
            </div>
          </div>
        </template>
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
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="chart-line" :size="18" /> 近 8 天提问趋势</div>
          <div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding-top:8px;">
            <div v-for="p in stats.trend" :key="p.day" style="flex:1;text-align:center;">
              <div style="font-size:0.8rem;color:#888;">{{ p.count }}</div>
              <div :style="{ height: Math.max(4, p.count * 18) + 'px', background: '#4caf50', borderRadius: '4px 4px 0 0' }"></div>
              <div style="font-size:0.7rem;color:#999;margin-top:4px;">{{ p.day.slice(5) }}</div>
            </div>
          </div>
        </div>

        <div class="card" v-if="stats && stats.expiring && stats.expiring.length">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="hourglass" :size="18" /> 7 天内到期知识条目</div>
          <div v-for="e in stats.expiring" :key="e.id" style="padding:4px 0;display:flex;justify-content:space-between;">
            <span>{{ e.title }}</span>
            <span class="muted" style="font-size:0.85rem;">到期 {{ e.expire_date }}</span>
          </div>
        </div>

        <div class="card" v-if="stats && stats.match_failed_list && stats.match_failed_list.length">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="x" :size="18" /> 匹配失败明细（留痕）</div>
          <div v-for="f in stats.match_failed_list" :key="f.id" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
            <b>{{ f.actor || '居民' }}</b>：{{ f.detail }}
            <span class="muted" style="font-size:0.8rem;"> · {{ (f.created_at || '').slice(0, 16) }}</span>
          </div>
        </div>

        <div class="card" v-if="stats && stats.unhelpful_list && stats.unhelpful_list.length">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="thumb-down" :size="18" /> 居民点「无帮助」明细（留痕）</div>
          <div v-for="(f, i) in stats.unhelpful_list" :key="i" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
            <b>{{ f.actor || '居民' }}</b> 对「{{ f.target_title || '—' }}」：{{ f.detail }}
            <span class="muted" style="font-size:0.8rem;"> · {{ (f.created_at || '').slice(0, 16) }}</span>
          </div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="sliders" :size="18" /> 自动回答匹配阈值</div>
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

    <!-- 版本管理弹窗 -->
    <n-modal :show="!!verModal" @update:show="(v) => { if (!v) verModal = null }" preset="card" style="width:600px;"
             :title="verModal ? (verModal.mode === 'new' ? '创建新版本' : '版本历史') : ''">
      <template v-if="verModal">
        <template v-if="verModal.mode === 'new'">
          <n-form label-placement="top">
            <n-form-item label="标题">
              <n-input v-model:value="kForm2.title" />
            </n-form-item>
            <n-form-item label="分类">
              <n-select v-model:value="kForm2.category" :options="KB_CATS.map(v=>({label:v,value:v}))" />
            </n-form-item>
            <n-form-item label="通俗解读">
              <n-input v-model:value="kForm2.plain_interpretation" type="textarea" :rows="2" />
            </n-form-item>
            <n-form-item label="关键词（必填，逗号分隔）">
              <n-input v-model:value="kForm2.keywords" placeholder="如：医保,报销" />
            </n-form-item>
            <n-form-item label="正文">
              <n-input v-model:value="kForm2.content" type="textarea" :rows="3" />
            </n-form-item>
            <n-grid :cols="2" :x-gap="12">
              <n-form-item-gi label="生效日期">
                <n-input v-model:value="kForm2.effective_date" placeholder="如 2026-01-01" />
              </n-form-item-gi>
              <n-form-item-gi label="失效日期">
                <n-input v-model:value="kForm2.expire_date" placeholder="如 2027-12-31" />
              </n-form-item-gi>
            </n-grid>
            <n-button type="primary" @click="submitNewVersion"><EIcon name="send" :size="18" /> 创建并提交审核</n-button>
          </n-form>
        </template>
        <template v-else>
          <div v-for="v in verModal.versions" :key="v.id" style="padding:8px 0;border-bottom:1px solid var(--border);">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <b>V{{ v.version || 1 }} {{ v.title }}</b>
              <n-tag size="small" :type="v.audit_status === '已发布' ? 'success' : 'default'">{{ v.audit_status }}</n-tag>
            </div>
            <div class="muted" style="font-size:0.8rem;margin-top:2px;">{{ (v.updated_at || v.created_at || '').slice(0, 16) }} · 发布人 {{ v.publisher || '' }}</div>
          </div>
          <n-empty v-if="!verModal.versions || !verModal.versions.length" description="暂无版本记录" style="font-size:0.85rem;padding:8px;" />
        </template>
      </template>
    </n-modal>
  </div>
</template>
