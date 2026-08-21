<script setup>
// 居民端 / 网格员端共用布局：侧边导航 + 顶栏
import { computed, h } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { useThemeStore } from '../stores/theme'
import WeatherBanner from '../components/WeatherBanner.vue'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const theme = useThemeStore()

const menus = computed(() => {
  if (store.isGrid) {
    return [
      { key: '/grid/dashboard', label: '工作台', icon: '📊' },
      { key: '/grid/work-orders', label: '工单管理', icon: '🔧' },
      { key: '/grid/proposals', label: '提案管理', icon: '💡' },
      { key: '/grid/notices', label: '通知管理', icon: '📢' },
      { key: '/grid/qa', label: '政策问答', icon: '📖' },
      { key: '/grid/weather', label: '天气管理', icon: '🌤️' },
      { key: '/grid/health', label: '健康管理', icon: '🏥' },
      { key: '/grid/elderly-care', label: '老年关怀', icon: '👴' },
    ]
  }
  return [
    { key: '/resident/home', label: '首页', icon: '🏠' },
    { key: '/resident/work-orders', label: '报修', icon: '🔧' },
    { key: '/resident/proposals', label: '邻里议事', icon: '💡' },
    { key: '/resident/notices', label: '通知', icon: '📢' },
    { key: '/resident/qa', label: '政策问答', icon: '📖' },
    { key: '/resident/health', label: '健康防护', icon: '🏥' },
    { key: '/resident/weather', label: '天气', icon: '🌤️' },
  ]
})

const active = computed(() => '/' + route.path.split('/').slice(0, 3).join('/'))

function logout() {
  store.logout()
  router.replace('/login')
}
</script>

<template>
  <n-layout style="min-height:100vh" has-sider>
    <n-layout-sider bordered width="210">
      <div style="padding:18px 16px;border-bottom:1px solid var(--border);">
        <div style="font-weight:800;color:#2E7D32;font-size:1.05rem;">🏘️ 社区先知</div>
        <div style="color:var(--muted);font-size:0.75rem;">{{ store.isGrid ? '网格员工作台' : '社区治理平台' }}</div>
      </div>
      <n-menu :options="menus.map(m => ({ key: m.key, label: m.label, icon: () => h('span', m.icon) }))"
              :value="active" @update:value="(k) => router.push(k)" />
    </n-layout-sider>

    <n-layout>
      <WeatherBanner />
      <n-layout-header bordered style="height:56px;display:flex;align-items:center;justify-content:space-between;padding:0 20px;">
        <div style="font-weight:700;">{{ route.meta.title || '' }}</div>
        <div style="display:flex;align-items:center;gap:12px;">
          <n-button size="small" quaternary @click="theme.toggle()">{{ theme.isDark ? '☀️ 日间' : '🌙 夜间' }}</n-button>
          <n-tag :bordered="false" type="success" size="small">● {{ store.isGrid ? 'AI 治理' : '居民端' }}</n-tag>
          <span style="color:var(--muted);">{{ store.user?.name }}</span>
          <n-button size="small" quaternary @click="logout">退出</n-button>
        </div>
      </n-layout-header>
      <n-layout-content content-style="background:var(--bg);">
        <router-view />
      </n-layout-content>
    </n-layout>
  </n-layout>
</template>
