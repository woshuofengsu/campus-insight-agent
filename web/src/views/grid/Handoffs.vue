<script setup>
// 网格端「人工待办」工作台（卡11 / v3 卡7）：AI 转人工的处理包，**在这里办完**。
//
// 为什么要有这一页：原来 agent_handoffs 只有「待处理/已处理」，网格端看得到包却办不了事 ——
// 谁领的、向居民补问了什么、回复了什么、为什么关闭，全都没有记录，居民那边也收不到回音。
// 现在四个动作走同一个状态机（后端 `data/db_agent.handle_handoff`）：
//   ① 领取（一个人领，别人再领会明确告诉他"已被谁领了"）
//   ② 补问（写清要问什么 → 居民收到通知，状态变「等居民补充」）
//   ③ 回复（写清答复 → 居民收到通知，状态变「已回复」）
//   ④ 关闭（必须写关闭说明——这就是居民看到的处理结果）
import { ref, computed, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { agent } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const loadError = ref('')
const busy = ref(0)          // 正在操作的 handoff id（按钮转圈，防连点）
const draft = ref({})        // { [hid]: { ask, reply, close } }
const filter = ref('待处理')

const STATUS_OPTIONS = ['待处理', '已领取', '等居民补充', '已回复', '已处理', '']
const STATUS_LABEL = {
  待处理: '⏳ 没人领取', 已领取: '🙋 已领取（办理中）', 等居民补充: '❓ 等居民补充',
  已回复: '✅ 已回复（待关闭）', 已处理: '🏁 已办结',
}
const STATUS_TYPE = {
  待处理: 'warning', 已领取: 'info', 等居民补充: 'warning', 已回复: 'success', 已处理: 'default',
}

const rows = computed(() => (filter.value ? list.value.filter((r) => r.status === filter.value) : list.value))
const counts = computed(() => {
  const c = {}
  for (const r of list.value) c[r.status] = (c[r.status] || 0) + 1
  return c
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    list.value = (await agent.handoffs({ limit: 100 })) || []
  } catch (e) {
    // 查不到 ≠ 没有待办：接口失败要明确说出来（否则网格员会以为"今天没活儿"）
    loadError.value = (e && e.message) || '网络不太顺，没能读到待办'
    list.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

function d(hid) {
  if (!draft.value[hid]) draft.value[hid] = { ask: '', reply: '', close: '' }
  return draft.value[hid]
}

async function act(row, action, textKey) {
  const text = textKey ? (d(row.id)[textKey] || '').trim() : ''
  if (textKey === 'ask' && !text) return message.warning('请写清要问居民什么')
  if (textKey === 'reply' && !text) return message.warning('请写清回复内容（居民会收到通知）')
  if (textKey === 'close' && !text) return message.warning('请写清关闭说明（这是居民看到的处理结果）')
  busy.value = row.id
  try {
    const r = await agent.handoffAction(row.id, { action, text })
    message.success((r && r.message) || '操作成功')
    if (textKey) draft.value[row.id] = { ask: '', reply: '', close: '' }
    // 操作后**把筛选切到刚进入的状态**：否则这条会因为被筛掉而"瞬间消失"，
    // 网格员会以为没点成功（实测踩到：领取后列表里就找不到这条了）。
    const nextFilter = { claim: '已领取', ask: '等居民补充', reply: '已回复', close: '已处理' }[action]
    if (nextFilter) filter.value = nextFilter
    await load()
  } catch (e) {
    // 例如"已经被别人领取了"——如实转达，不假装成功
    message.error(e.message)
    await load()
  } finally {
    busy.value = 0
  }
}

const fmt = (t) => (t ? String(t).replace('T', ' ').slice(0, 16) : '')
</script>

<template>
  <div class="page">
    <h2 class="page-title">🧑‍💻 人工待办（AI 转过来的处理包）</h2>
    <p class="muted" style="font-size:0.9rem;">
      AI 答不上或需要人工判断时会生成处理包，上下文已经整理好，在这里依次「领取 → 补问 → 回复 → 关闭」即可办完。
    </p>

    <div class="card" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
      <n-select v-model:value="filter" :options="STATUS_OPTIONS.map(v => ({ label: v ? `${v}（${counts[v] || 0}）` : '全部', value: v }))"
                size="small" style="width:200px;" />
      <n-button size="small" @click="load">刷新</n-button>
      <span class="muted" style="font-size:0.85rem;">
        共 {{ list.length }} 条 · 待处理 {{ counts['待处理'] || 0 }} · 办理中 {{ (counts['已领取'] || 0) + (counts['等居民补充'] || 0) }} · 待关闭 {{ counts['已回复'] || 0 }}
      </span>
      <span v-if="loadError" style="color:var(--ink-danger);font-size:0.85rem;" data-load-error>⚠️ {{ loadError }}</span>
    </div>

    <div v-for="r in rows" :key="r.id" class="card">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;">
        <div>
          <b>#{{ r.id }} · {{ r.reason || r.intent }}</b>
          <n-tag size="small" :type="STATUS_TYPE[r.status] || 'default'" style="margin-left:8px;">{{ STATUS_LABEL[r.status] || r.status }}</n-tag>
          <n-tag v-if="r.assignee_name" size="small" style="margin-left:6px;">👤 {{ r.assignee_name }}</n-tag>
        </div>
        <span class="muted" style="font-size:0.8rem;">{{ fmt(r.created_at) }}</span>
      </div>

      <!-- 上下文：AI 已经整理好的原话与分类，负责人不用再问一遍 -->
      <div class="muted" style="font-size:0.9rem;margin-top:6px;">
        🗣️ 居民原话：{{ r.original_input || '（无）' }}
        <span v-if="r.package && r.package.intent"> · 分类：{{ r.package.intent }}</span>
        <span v-if="r.package && r.package.reply"> · AI 已答：{{ String(r.package.reply).slice(0, 60) }}</span>
      </div>

      <!-- 办理记录（谁在什么时候做了什么，都看得见） -->
      <div v-if="r.claimed_at" class="muted" style="font-size:0.85rem;margin-top:6px;">
        🙋 {{ r.assignee_name }} 于 {{ fmt(r.claimed_at) }} 领取
      </div>
      <div v-if="r.ask_back" style="font-size:0.9rem;margin-top:6px;">
        ❓ 已补问（{{ fmt(r.asked_at) }}）：{{ r.ask_back }}
      </div>
      <div v-if="r.reply" style="font-size:0.9rem;margin-top:6px;">
        ✅ 已回复（{{ fmt(r.replied_at) }}）：{{ r.reply }}
      </div>
      <div v-if="r.close_note" style="font-size:0.9rem;margin-top:6px;">
        🏁 办结说明（{{ fmt(r.closed_at) }}）：{{ r.close_note }}
      </div>

      <!-- 操作区：按当前状态给出**能做的动作**（不能做的就不显示，避免点了报错） -->
      <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;">
        <n-button v-if="r.status === '待处理'" type="primary" size="small" :loading="busy === r.id"
                  @click="act(r, 'claim')">🙋 领取</n-button>

        <template v-if="['已领取', '等居民补充'].includes(r.status)">
          <n-input v-model:value="d(r.id).ask" size="small" placeholder="补问居民什么？（会通知居民）" style="max-width:260px;" />
          <n-button size="small" :loading="busy === r.id" @click="act(r, 'ask', 'ask')">❓ 补问</n-button>
          <n-input v-model:value="d(r.id).reply" size="small" placeholder="回复内容（会通知居民）" style="max-width:260px;" />
          <n-button size="small" type="success" :loading="busy === r.id" @click="act(r, 'reply', 'reply')">✅ 回复</n-button>
        </template>

        <template v-if="['已领取', '等居民补充', '已回复'].includes(r.status)">
          <n-input v-model:value="d(r.id).close" size="small" placeholder="关闭说明（居民看得到的处理结果）" style="max-width:280px;" />
          <n-button size="small" type="primary" :loading="busy === r.id" @click="act(r, 'close', 'close')">🏁 关闭</n-button>
        </template>

        <span v-if="r.status === '已处理'" class="muted" style="font-size:0.85rem;">已办结（关闭说明会展示给居民）</span>
      </div>
    </div>

    <n-empty v-if="!loading && !loadError && rows.length === 0"
             :description="filter ? `没有「${filter}」的待办` : '暂时没有待办'" />
  </div>
</template>
