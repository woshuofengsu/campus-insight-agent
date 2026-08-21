<script setup>
// 健康防护：健康内容 + 提交咨询 + 我的咨询
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { health } from '../../api'

const message = useMessage()
const articles = ref([])
const myConsults = ref([])
const tab = ref('articles')

const cform = ref({ name: '', phone: '', consult_type: '健康知识', content: '' })
const submitting = ref(false)

onMounted(async () => {
  try { articles.value = (await health.articles()) || [] } catch { /* 忽略 */ }
  try { myConsults.value = (await health.consults()) || [] } catch { /* 忽略 */ }
})

async function submit() {
  if (cform.value.content.length < 5) return message.warning('请填写至少 5 字内容')
  submitting.value = true
  try {
    const d = await health.createConsult(cform.value)
    message.success(`咨询已提交，编号 ${d.code}`)
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
</script>

<template>
  <div class="page">
    <h2 class="page-title">🏥 健康防护</h2>
    <p class="page-sub">疾病预防内容 + 健康咨询（负责人 24 小时内回复）</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="articles" tab="健康知识">
        <div v-for="a in articles" :key="a.id" class="card">
          <b>{{ a.title }}</b>
          <n-tag size="small" style="margin-left:8px;">{{ a.content_type }}</n-tag>
          <div class="muted" style="font-size:0.85rem;margin-top:6px;">{{ a.summary }}</div>
        </div>
        <n-empty v-if="articles.length === 0" description="暂无健康内容" />
      </n-tab-pane>

      <n-tab-pane name="ask" tab="健康咨询">
        <div class="card">
          <n-form label-placement="top">
            <n-form-item label="姓名">
              <n-input v-model:value="cform.name" placeholder="可为昵称" />
            </n-form-item>
            <n-form-item label="联系电话（必填）">
              <n-input v-model:value="cform.phone" placeholder="11 位手机号" />
            </n-form-item>
            <n-form-item label="咨询内容（5-500字）">
              <n-input v-model:value="cform.content" type="textarea" :rows="4" />
            </n-form-item>
            <n-button type="primary" block :loading="submitting" @click="submit">🩺 提交咨询</n-button>
          </n-form>
        </div>
      </n-tab-pane>

      <n-tab-pane name="mine" tab="我的咨询">
        <div v-for="c in myConsults" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ c.code || ('#' + c.id) }}</b>
            <n-tag size="small" :type="c.status === '待回复' ? 'warning' : c.status === '已回复' ? 'success' : 'default'">{{ c.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:6px;">{{ c.content }}</div>
          <div v-if="c.reply" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:8px;font-size:0.9rem;">
            💬 负责人：{{ c.reply }}
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
  </div>
</template>
