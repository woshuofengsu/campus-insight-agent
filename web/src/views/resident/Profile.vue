<script setup>
// 居民端「我的」页（依据 UI/UX 规范 4.1.6）：个人信息 + 事务卡片 + 常用服务 + 设置
// 纯展示与已有操作入口，不新增任何业务功能
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../../stores/user'
import { useThemeStore } from '../../stores/theme'
import { issues, proposals, notices, messages, agent } from '../../api'

const router = useRouter()
const message = useMessage()
const store = useUserStore()
const theme = useThemeStore()

const issueCount = ref(0)
const proposalCount = ref(0)
const unreadNotices = ref(0)
const unreadMsgs = ref(0)
const contactPhone = ref('')

onMounted(async () => {
  try { issueCount.value = (await issues.list())?.length || 0 } catch { /* 忽略 */ }
  try { proposalCount.value = (await proposals.list())?.length || 0 } catch { /* 忽略 */ }
  try {
    const nl = (await notices.list()) || []
    unreadNotices.value = nl.filter((n) => !n.is_read).length
  } catch { /* 忽略 */ }
  try { unreadMsgs.value = (await messages.list())?.filter((m) => !m.is_read).length || 0 } catch { /* 忽略 */ }
  try {
    const home = await import('../../api').then((m) => m.elderly.home())
    contactPhone.value = home.community_phone || '62319876'
  } catch { /* 忽略 */ }
})

function maskPhone(p) {
  if (!p) return '—'
  return p.length === 11 ? p.slice(0, 3) + '****' + p.slice(-4) : p
}

async function clearHistory() {
  try {
    await agent.clearHistory()
    message.success('历史对话已清除')
  } catch (e) {
    message.error(e.message)
  }
}

// PIPL：导出本人数据
async function exportMyData() {
  try {
    const api = await import('../../api')
    const blob = await api.default.get('/me/export', { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'my-data.json'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e.message)
  }
}

// PIPL：注销账号（二次确认）
async function deleteAccount() {
  try {
    const api = await import('../../api')
    await api.default.post('/me/delete')
    message.success('账号已注销，个人数据已匿名化')
    store.logout()
    setTimeout(() => { window.location.href = '/login' }, 800)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <!-- 个人信息 -->
    <div class="card" style="display:flex;align-items:center;gap:16px;background:var(--primary-gradient);color:#fff;border:none;">
      <div style="width:60px;height:60px;border-radius:50%;background:rgba(255,255,255,0.25);display:flex;align-items:center;justify-content:center;font-size:1.8rem;">
        {{ (store.user?.name || '居')[0] }}
      </div>
      <div>
        <div style="font-size:1.2rem;font-weight:800;">{{ store.user?.name || '居民' }}</div>
        <div style="font-size:0.85rem;opacity:0.9;margin-top:2px;">
          {{ store.user?.role === 'resident' ? '居民' : store.user?.role }} · {{ maskPhone(store.user?.phone) }}
          <span v-if="store.user?.community"> · {{ store.user.community }}</span>
        </div>
      </div>
    </div>

    <!-- 事务卡片 -->
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-bottom:12px;">
      <div class="card stat-card" style="margin:0;cursor:pointer;" @click="router.push('/resident/work-orders')">
        <div class="num" style="color:var(--st-doing);">🔧 {{ issueCount }}</div>
        <div class="lbl">我的报修</div>
      </div>
      <div class="card stat-card" style="margin:0;cursor:pointer;" @click="router.push('/resident/proposals')">
        <div class="num" style="color:var(--st-feedback);">💡 {{ proposalCount }}</div>
        <div class="lbl">我的提案</div>
      </div>
      <div class="card stat-card" style="margin:0;cursor:pointer;" @click="router.push('/resident/notices')">
        <div class="num" style="color:var(--st-pending);">📢 {{ unreadNotices }}</div>
        <div class="lbl">未读通知</div>
      </div>
      <div class="card stat-card" style="margin:0;cursor:pointer;" @click="router.push('/resident/messages')">
        <div class="num" style="color:var(--st-danger);">✉️ {{ unreadMsgs }}</div>
        <div class="lbl">未读消息</div>
      </div>
    </div>

    <!-- 常用服务 -->
    <div class="card">
      <div style="font-weight:700;margin-bottom:8px;">⚡ 常用服务</div>
      <div style="display:flex;flex-direction:column;gap:4px;">
        <div class="svc" @click="router.push('/resident/qa')"><span>📖</span> 政策问答</div>
        <div class="svc" @click="router.push('/resident/health')"><span>🏥</span> 健康防护</div>
        <div class="svc" @click="router.push('/resident/weather')"><span>🌤️</span> 天气查询</div>
        <div class="svc" @click="message.info(`社区服务中心电话：${contactPhone}`)"><span>📞</span> 联系社区（{{ contactPhone }}）</div>
      </div>
    </div>

    <!-- 设置 -->
    <div class="card">
      <div style="font-weight:700;margin-bottom:8px;">⚙️ 设置</div>
      <div style="display:flex;flex-direction:column;gap:4px;">
        <div class="svc" @click="theme.toggle()"><span>🌙</span> {{ theme.isDark ? '日间模式' : '夜间模式' }}</div>
        <div class="svc" @click="clearHistory"><span>🗑️</span> 清除历史对话</div>
        <div class="svc" @click="exportMyData"><span>📤</span> 导出我的数据（脱敏）</div>
        <div class="svc" @click="router.push('/resident/privacy')"><span>🔒</span> 隐私政策</div>
        <n-popconfirm @positive-click="deleteAccount" :positive-button-props="{ type: 'error' }">
          <template #trigger><div class="svc" style="color:#dc2626;"><span>🚪</span> 注销账号（数据匿名化）</div></template>
          注销后您的报修/提案记录将匿名化、不可恢复，确认注销？
        </n-popconfirm>
        <div class="svc" @click="store.logout(); router.replace('/login')"><span>🔑</span> 退出登录</div>
      </div>
      <div class="muted" style="font-size:0.75rem;margin-top:12px;">社区先知 · 社区治理智能体 · 演示数据均为虚构</div>
    </div>
  </div>
</template>

<style scoped>
.svc {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 12px; border-radius: 10px; cursor: pointer;
  font-size: 0.95rem;
}
.svc:hover { background: var(--primary-light); }
</style>
