<script setup>
// 政策问答：提问 → 自动回答 / 转人工 + 高频问题
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { qa } from '../../api'

const message = useMessage()
const question = ref('')
const asking = ref(false)
const result = ref(null)
const hot = ref([])

onMounted(async () => {
  try { hot.value = (await qa.highFreq()) || [] } catch { /* 忽略 */ }
})

async function ask() {
  if (!question.value.trim()) return message.warning('请输入问题')
  asking.value = true
  result.value = null
  try {
    result.value = await qa.ask({ question: question.value })
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
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📖 政策问答</h2>
    <p class="page-sub">问问医保、养老、住房政策，系统自动回答</p>

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

    <div class="card" v-if="hot.length">
      <div style="font-weight:700;margin-bottom:8px;">🔥 高频问题</div>
      <div v-for="(h, i) in hot" :key="i" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
        {{ h.summary }} <span class="muted">（{{ h.c }} 次）</span>
      </div>
    </div>
  </div>
</template>
