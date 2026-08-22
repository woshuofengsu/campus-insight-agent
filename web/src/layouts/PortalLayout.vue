<script setup>
// 居民端 / 网格员端布局（依据 UI/UX 规范）：
// 居民端 = 顶部栏 + 底部标签栏（首页|报修|提案|通知|我的）+ 内容
// 网格员端 = 深色侧边导航 + 顶栏 + AI 工作助手（侧边栏默认收起）
import { computed, h, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useThemeStore } from '../stores/theme'
import WeatherBanner from '../components/WeatherBanner.vue'
import AgentChat from '../components/AgentChat.vue'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const theme = useThemeStore()
const agentOpen = ref(false) // AI 工作助手默认收起

const gridMenus = [
  { key: '/grid/dashboard', label: '工作台', icon: '📊' },
  { key: '/grid/work-orders', label: '工单管理', icon: '🔧' },
  { key: '/grid/proposals', label: '提案管理', icon: '💡' },
  { key: '/grid/notices', label: '通知管理', icon: '📢' },
  { key: '/grid/qa', label: '政策问答', icon: '📖' },
  { key: '/grid/weather', label: '天气管理', icon: '🌤️' },
  { key: '/grid/health', label: '健康管理', icon: '🏥' },
  { key: '/grid/elderly-care', label: '老年关怀', icon: '👴' },
]

// 居民端底部标签栏（规范 4.1：首页|报修|提案|通知|我的）
const residentTabs = [
  { key: '/resident/home', label: '首页', icon: '🏠' },
  { key: '/resident/work-orders', label: '报修', icon: '🔧' },
  { key: '/resident/proposals', label: '提案', icon: '💡' },
  { key: '/resident/notices', label: '通知', icon: '📢' },
  { key: '/resident/profile', label: '我的', icon: '👤' },
]

const active = computed(() => {
  const p = route.path
  if (p.startsWith('/resident')) return '/' + p.split('/').slice(0, 3).join('/')
  return '/' + p.split('/').slice(0, 3).join('/')
})

const activeTab = computed(() => {
  const p = route.path
  if (p.includes('/work-orders') || p.includes('/proposals/') || p.includes('/proposals/new')) {
    const seg = p.includes('/proposals') ? 'proposals' : 'work-orders'
    return '/resident/' + seg
  }
  if (p.startsWith('/resident/notices')) return '/resident/notices'
  if (p.startsWith('/resident/profile')) return '/resident/profile'
  return '/resident/home'
})

function logout() {
  store.logout()
  router.replace('/login')
}
</script>

<template>
  <!-- 网格员端：保持原样（浅色侧边导航 + 顶栏 + AI 工作助手） -->
  <n-layout v-if="store.isGrid" style="min-height:100vh" has-sider>
    <n-layout-sider bordered width="230">
      <div style="padding:18px 16px;border-bottom:1px solid var(--border);">
        <div style="font-weight:800;color:#2E7D32;font-size:1.05rem;">🏘️ 社区先知</div>
        <div style="color:var(--muted);font-size:0.75rem;">网格员工作台</div>
      </div>
      <n-menu :options="gridMenus.map(m => ({ key: m.key, label: m.label, icon: () => h('span', m.icon) }))"
              :value="active" @update:value="(k) => router.push(k)" />
      <!-- AI 工作助手（默认收起，不遮挡主内容） -->
      <div style="margin:8px 8px 0;border-top:1px solid var(--border);padding-top:8px;">
        <n-button block :type="agentOpen ? 'primary' : 'default'" size="small" @click="agentOpen = !agentOpen">
          🤖 AI 工作助手 {{ agentOpen ? '▲' : '▼' }}
        </n-button>
        <div v-if="agentOpen" style="margin-top:8px;">
          <AgentChat role="grid" />
        </div>
      </div>
    </n-layout-sider>

    <n-layout>
      <WeatherBanner />
      <n-layout-header bordered style="height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;">
        <div style="font-weight:700;">{{ route.meta.title || '' }}</div>
        <div style="display:flex;align-items:center;gap:12px;">
          <n-button size="small" quaternary @click="theme.toggle()">{{ theme.isDark ? '☀️ 日间' : '🌙 夜间' }}</n-button>
          <n-tag :bordered="false" type="success" size="small">● AI 治理</n-tag>
          <span style="color:var(--muted);">{{ store.user?.name }}</span>
          <n-button size="small" quaternary @click="logout">退出</n-button>
        </div>
      </n-layout-header>
      <n-layout-content content-style="background:var(--bg);">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>

  <!-- 居民端：顶部栏 + 底部标签栏 + 内容 -->
  <n-layout v-else style="min-height:100vh">
    <WeatherBanner />
    <n-layout-header bordered style="height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;background:var(--card-bg);position:sticky;top:0;z-index:10;">
      <div style="font-weight:800;color:var(--primary);">🏘️ 社区先知</div>
      <div style="display:flex;align-items:center;gap:12px;">
        <n-button size="small" quaternary @click="theme.toggle()">{{ theme.isDark ? '☀️ 日间' : '🌙 夜间' }}</n-button>
        <span style="color:var(--muted);">{{ store.user?.name }}</span>
        <n-button size="small" quaternary @click="logout">退出</n-button>
      </div>
    </n-layout-header>
    <n-layout-content content-style="background:var(--bg);padding-bottom:76px;">
      <router-view />
    </n-layout-content>
    <!-- 底部标签栏 -->
    <div style="position:fixed;bottom:0;left:0;right:0;height:64px;background:var(--card-bg);border-top:1px solid var(--border);display:flex;z-index:20;">
      <div v-for="t in residentTabs" :key="t.key"
           :style="{
             flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
             gap: '2px', cursor: 'pointer', fontSize: '0.72rem',
             color: activeTab === t.key ? 'var(--primary)' : 'var(--muted)',
             fontWeight: activeTab === t.key ? 700 : 400,
           }"
           @click="router.push(t.key)">
        <span style="font-size:1.25rem;">{{ t.icon }}</span>{{ t.label }}
      </div>
    </div>
  </n-layout>
</template>
