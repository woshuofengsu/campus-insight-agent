<script setup>
// Agent 对话组件（居民端首页 / 负责人端侧边栏共用）
// 识别意图 → 引导补全（追问按钮）→ 路由执行 → 返回结果
import { ref, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { agent } from '../api'

const props = defineProps({
  role: { type: String, default: 'resident' }, // resident | grid
  collapsed: { type: Boolean, default: false }, // 负责人端侧边栏默认收起
})
const emit = defineEmits(['toggle'])

const router = useRouter()
const message = useMessage()
const msgs = ref([])
const input = ref('')
const busy = ref(false)
const scrollBox = ref(null)
const showHistory = ref(false)
const history = ref([])

// 快捷问题
const QUICK = props.role === 'grid'
  ? ['今天有什么待办', '导出本月工单', '本周工单统计', '打开待审核工单']
  : ['我家水管漏水了', '我想提个建议', '医保怎么报销', '今天天气怎么样', '帮我联系社区', '最近有什么通知']

onMounted(() => {
  // 首次使用欢迎语
  msgs.value.push({
    bot: true,
    text: props.role === 'grid'
      ? '我是您的工作助手，可以帮您查待办、导出数据、搜索资料、查看统计、跳转页面。'
      : '您好，我是社区小助手！可以帮您报修、提建议、查政策、看天气和通知，也可以帮您联系社区。',
    intents: QUICK,
  })
  loadHistory()
})

async function loadHistory() {
  try {
    history.value = (await agent.history()) || []
  } catch { /* 忽略 */ }
}

function scrollBottom() {
  nextTick(() => { if (scrollBox.value) scrollBox.value.scrollTop = scrollBox.value.scrollHeight })
}

async function send(text, fromQuick = false) {
  const t = (text ?? input.value ?? '').trim()
  if (!t || busy.value) return
  input.value = ''
  msgs.value.push({ bot: false, text: t })
  busy.value = true
  scrollBottom()
  try {
    const fn = props.role === 'grid' ? agent.chat : agent.chat
    const r = await fn({ text: t })
    const m = {
      bot: true,
      text: r.reply,
      intent: r.intent,
      status: r.status,
      actions: r.actions || [],
      related_id: r.related_id,
      corrected: r.corrected,
    }
    msgs.value.push(m)
    // 追问按钮自动出现在下一条消息（quick 选项）
    if (m.actions) {
      const opts = []
      for (const a of m.actions) {
        if (a.type === 'buttons') opts.push(...(a.options || []))
      }
      if (opts.length) m.quick = opts
    }
    loadHistory()
  } catch (e) {
    msgs.value.push({ bot: true, text: e.message || '服务暂时不可用，请稍后再试', error: true })
  } finally {
    busy.value = false
    scrollBottom()
  }
}

// 动作处理
async function onAction(a) {
  if (a.type === 'navigate') {
    router.push(a.to)
  } else if (a.type === 'confirm_call') {
    message.info(`正在呼叫 ${a.phone}`)
  } else if (a.type === 'download') {
    // Agent 导出（负责人端）→ 下载工单报表
    try {
      const { exportApi } = await import('../api')
      const blob = await exportApi.issues()
      const url = URL.createObjectURL(blob)
      const el = document.createElement('a')
      el.href = url; el.download = 'issues.csv'; el.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      message.error(e.message)
    }
  } else if (a.type === 'confirm_transfer') {
    message.success('已为您转人工，负责人会在 24 小时内回复')
  } else if (a.type === 'buttons') {
    // 按钮选项直接作为下一条输入发送
    send(a.option, true)
  }
}

function sendOption(opt) {
  send(opt, true)
}

async function delHistory(id) {
  try {
    await agent.deleteHistory(id)
    message.success('已删除')
    loadHistory()
  } catch (e) {
    message.error(e.message)
  }
}

async function clearAll() {
  try {
    await agent.clearHistory()
    message.success('已清空历史对话')
    loadHistory()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="agent-chat" :class="{ collapsed }">
    <!-- 简洁工具栏（无蓝色板块与标题文字；历史入口与 grid 收起保留） -->
    <div class="agent-head">
      <div style="display:flex;gap:6px;align-items:center;">
        <n-button v-if="role !== 'grid'" size="tiny" quaternary @click="showHistory = !showHistory">{{ showHistory ? '收起历史' : '📋 历史' }}</n-button>
      </div>
      <div style="display:flex;gap:6px;align-items:center;">
        <n-button v-if="role === 'grid'" size="tiny" quaternary @click="emit('toggle')">{{ collapsed ? '展开' : '收起' }}</n-button>
      </div>
    </div>

    <template v-if="!collapsed">
      <!-- 历史对话 -->
      <div v-if="showHistory" class="agent-history">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">
          <b style="font-size:0.85rem;">📋 最近对话（5 条）</b>
          <n-button size="tiny" quaternary @click="clearAll">清空</n-button>
        </div>
        <div v-for="h in history" :key="h.id" style="display:flex;justify-content:space-between;align-items:center;padding:4px 0;border-bottom:1px solid var(--border);font-size:0.8rem;">
          <span class="muted" style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
            {{ h.is_bot ? '🤖' : '👤' }} {{ h.text }}
          </span>
          <n-button size="tiny" quaternary type="error" @click="delHistory(h.id)">删</n-button>
        </div>
      </div>

      <!-- 消息区 -->
      <div ref="scrollBox" class="agent-body">
        <div v-for="(m, i) in msgs" :key="i" :class="['agent-msg', m.bot ? 'bot' : 'user']">
          <div class="agent-bubble" :class="{ error: m.error }">
            <div style="white-space:pre-wrap;">{{ m.text }}</div>
            <div v-if="m.intent && m.status" style="margin-top:6px;display:flex;gap:6px;align-items:center;">
              <n-tag size="tiny" type="info">{{ m.intent }}</n-tag>
              <n-tag size="tiny" :type="m.status === '成功' ? 'success' : m.status === '需确认' || m.status === '追问' ? 'warning' : 'default'">{{ m.status }}</n-tag>
            </div>
            <!-- 动作按钮 -->
            <div v-if="m.actions && m.actions.length" style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
              <template v-for="(a, ai) in m.actions" :key="ai">
                <n-button v-if="a.type === 'navigate'" size="small" type="primary" @click="onAction(a)">{{ a.label || '前往' }}</n-button>
                <n-button v-if="a.type === 'confirm_call'" size="small" type="warning" @click="onAction(a)">📞 {{ a.label || '拨打' }}</n-button>
                <n-button v-if="a.type === 'download'" size="small" type="success" @click="onAction(a)">⬇️ {{ a.label || '下载' }}</n-button>
                <n-button v-if="a.type === 'confirm_transfer'" size="small" @click="onAction(a)">🙋 {{ a.label || '转人工' }}</n-button>
              </template>
            </div>
            <!-- 快捷选项 -->
            <div v-if="m.quick && m.quick.length" style="margin-top:8px;display:flex;gap:6px;flex-wrap:wrap;">
              <n-button v-for="(o, oi) in m.quick" :key="oi" size="tiny" @click="sendOption(o)">{{ o }}</n-button>
            </div>
          </div>
        </div>
        <div v-if="busy" class="agent-msg bot"><div class="agent-bubble">正在思考…</div></div>
      </div>

      <!-- 快捷问题 -->
      <div class="agent-quick">
        <n-button v-for="(q, qi) in QUICK" :key="qi" size="tiny" quaternary @click="sendOption(q)">{{ q }}</n-button>
      </div>

      <!-- 输入区 -->
      <div class="agent-input">
        <n-input v-model:value="input" placeholder="请输入您的问题（如：我家水管漏水了）" maxlength="200"
                 @keyup.enter="send()" />
        <n-button type="primary" :loading="busy" @click="send()">发送</n-button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.agent-chat { display: flex; flex-direction: column; }
.agent-chat.collapsed { display: none; }
.agent-head { display: flex; align-items: center; justify-content: space-between; padding: 6px 12px;
  border-bottom: 1px solid var(--border); }
.agent-history { padding: 8px 12px; border-bottom: 1px solid var(--border); max-height: 140px; overflow-y: auto; }
.agent-body { padding: 12px; overflow-y: auto; flex: 1; min-height: 240px; max-height: 420px;
  background: var(--bg, #f5f7f5); }
.agent-msg { display: flex; margin-bottom: 10px; }
.agent-msg.bot { justify-content: flex-start; }
.agent-msg.user { justify-content: flex-end; }
.agent-bubble { max-width: 85%; padding: 8px 12px; border-radius: 12px; font-size: 0.9rem; line-height: 1.6; }
.agent-bubble.error { color: #dc2626; }
.agent-msg.user .agent-bubble { background: #2E7D32; color: #fff; }
.agent-msg.bot .agent-bubble { background: #fff; color: #374151; border: 1px solid var(--border); }
.agent-quick { display: flex; gap: 6px; flex-wrap: wrap; padding: 6px 12px; border-top: 1px solid var(--border); }
.agent-input { display: flex; gap: 8px; padding: 10px 12px; border-top: 1px solid var(--border); }
</style>
