<script setup>
// 政策问答：提问 → 自动回答 / 转人工 + 高频问题 + 我的提问历史 + 知识库浏览
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { qa, knowledge } from '../../api'

const message = useMessage()
const question = ref('')
const asking = ref(false)
const result = ref(null)
const hot = ref([])
const myQuestions = ref([])
const kb = ref([])
const tab = ref('ask')
const hotType = ref('全部')
const fbReason = ref({}) // qid -> reason

const Q_TYPES = ['全部', '社保医保', '养老服务', '住房保障', '民政救助', '户籍居住证', '就业创业', '其他']

onMounted(async () => {
  try { hot.value = (await qa.highFreq()) || [] } catch { /* 忽略 */ }
  try { myQuestions.value = (await qa.questions()) || [] } catch { /* 忽略 */ }
  try { kb.value = (await knowledge.list()) || [] } catch { /* 忽略 */ }
})

const fHot = () => (hotType.value === '全部' ? hot.value : hot.value.filter((h) => h.q_type === hotType.value))

async function ask() {
  if (!question.value.trim()) return message.warning('请输入问题')
  asking.value = true
  result.value = null
  try {
    result.value = await qa.ask({ question: question.value })
    myQuestions.value = (await qa.questions()) || []
  } catch (e) {
    message.error(e.message)
  } finally {
    asking.value = false
  }
}

async function transfer() {
  try {
    await qa.transfer(0, question.value)
    message.success('已转人工，负责人 24 小时内回复')
    result.value = null
    question.value = ''
    myQuestions.value = (await qa.questions()) || []
  } catch (e) {
    message.error(e.message)
  }
}

async function fb(q, satisfied) {
  try {
    await qa.feedback(q.id, { satisfied, reason: fbReason.value[q.id] || (satisfied ? '' : '回答不清晰') })
    message.success('反馈已提交')
    myQuestions.value = (await qa.questions()) || []
  } catch (e) {
    message.error(e.message)
  }
}

async function transferQuestion(q) {
  try {
    await qa.transfer(q.id)
    message.success('已转人工')
    myQuestions.value = (await qa.questions()) || []
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📖 政策问答</h2>
    <p class="page-sub">问问医保、养老、住房政策，系统自动回答</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="ask" tab="提问">
        <div class="card">
          <n-input v-model:value="question" type="textarea" :rows="3" placeholder="输入您想问的政策问题，比如：医保报销需要带什么材料？" />
          <div style="margin-top:10px;display:flex;gap:8px;">
            <n-button type="primary" :loading="asking" @click="ask">🔍 提问</n-button>
            <n-button secondary @click="transfer">🙋 转人工</n-button>
          </div>
        </div>

        <div v-if="result" class="card">
          <template v-if="result.matched">
            <div style="font-weight:700;color:#2E7D32;">✅ 已自动回答</div>
            <div style="margin-top:8px;white-space:pre-wrap;">{{ result.answer }}</div>
          </template>
          <template v-else>
            <div style="font-weight:700;color:#d97706;">暂未找到答案</div>
            <div class="muted" style="margin-top:6px;">{{ result.manual_text }}</div>
            <div v-if="result.expired_hint" class="muted">{{ result.expired_hint }}</div>
            <n-button size="small" type="primary" ghost style="margin-top:10px;" @click="transfer">🙋 转人工咨询</n-button>
          </template>
        </div>
      </n-tab-pane>

      <n-tab-pane name="history" tab="📋 我的提问">
        <div v-for="q in myQuestions" :key="q.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ q.summary }}</b>
            <n-tag size="small" :type="q.status === '已自动回答' ? 'success' : q.status === '已转人工' || q.status === '超时未回复' ? 'warning' : 'default'">{{ q.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ q.q_type }} · {{ (q.created_at || '').slice(0, 16) }}</div>
          <div v-if="q.auto_answer" style="margin-top:6px;font-size:0.9rem;">{{ q.auto_answer }}</div>
          <div v-if="q.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:6px;font-size:0.9rem;">
            💬 负责人：{{ q.reply }}
            <div v-if="q.reply_ref" class="muted" style="font-size:0.8rem;margin-top:4px;">📎 参考：{{ q.reply_ref }}</div>
          </div>
          <!-- 有帮助/无帮助反馈（无帮助提示可转人工，不自动转） -->
          <div v-if="q.status === '已自动回答'" style="margin-top:8px;display:flex;gap:8px;align-items:center;">
            <span class="muted" style="font-size:0.85rem;">这个回答有帮助吗？</span>
            <n-button size="small" type="success" @click="fb(q, true)">👍 有帮助</n-button>
            <n-input v-model:value="fbReason[q.id]" placeholder="无帮助原因（选填）" size="small" style="max-width:200px;" />
            <n-button size="small" type="warning" @click="fb(q, false)">👎 无帮助</n-button>
          </div>
          <!-- 已转人工 → 人工回复后反馈 -->
          <div v-if="q.reply && q.status !== '已自动回答'" style="margin-top:8px;display:flex;gap:8px;align-items:center;">
            <span class="muted" style="font-size:0.85rem;">问题解决了吗？</span>
            <n-button size="small" type="success" @click="fb(q, true)">✅ 已解决</n-button>
            <n-input v-model:value="fbReason[q.id]" placeholder="未解决原因" size="small" style="max-width:200px;" />
            <n-button size="small" type="warning" @click="fb(q, false)">😕 未解决</n-button>
          </div>
          <!-- 待回复/处理中可转人工 -->
          <div v-if="q.status === '待人工回复' || q.status === '处理中'" style="margin-top:8px;">
            <n-button size="small" @click="transferQuestion(q)">🙋 转人工</n-button>
          </div>
        </div>
        <n-empty v-if="myQuestions.length === 0" description="还没有提问记录" />
      </n-tab-pane>

      <n-tab-pane name="hot" tab="🔥 高频问题">
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;">
          <n-tag v-for="t in Q_TYPES" :key="t" size="small" :type="hotType === t ? 'primary' : 'default'"
                 style="cursor:pointer;" @click="hotType = t">{{ t }}</n-tag>
        </div>
        <div v-for="(h, i) in fHot()" :key="i" style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
          {{ h.summary }} <n-tag size="tiny" style="margin-left:4px;">{{ h.q_type }}</n-tag>
          <span class="muted">（{{ h.c }} 次）</span>
        </div>
        <n-empty v-if="fHot().length === 0" description="暂无高频问题" />
      </n-tab-pane>

      <n-tab-pane name="kb" tab="📚 政策知识库">
        <div v-for="k in kb" :key="k.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ k.title }}</b>
            <n-tag size="small">{{ k.category }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:6px;">{{ k.plain_interpretation }}</div>
          <div style="margin-top:8px;display:flex;gap:8px;">
            <n-button v-if="k.attachment" size="small" tag="a" :href="k.attachment" target="_blank">📄 查看政策原文</n-button>
          </div>
        </div>
        <n-empty v-if="kb.length === 0" description="暂无知识库条目" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
