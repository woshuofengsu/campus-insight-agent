<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from './stores/user'
import { useThemeStore } from './stores/theme'
import { darkTheme } from 'naive-ui'

const store = useUserStore()
const theme = useThemeStore()
const router = useRouter()

// 登录后按角色跳对应端首页
onMounted(() => {
  theme.apply()
  const role = store.role
  if (role && !router.currentRoute.value.path.startsWith(`/${role}`)) {
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    if (router.currentRoute.value.path !== '/screen') {
      router.replace(home[role] || '/login')
    }
  }
})

const themeOverrides = computed(() => theme.isDark
  ? { common: { primaryColor: '#4caf50', primaryColorHover: '#66bb6a', primaryColorPressed: '#388e3c', bodyColor: '#0f1a15', cardColor: '#16251e', textColorBase: '#e5efe8' } }
  : { common: { primaryColor: '#2E7D32', primaryColorHover: '#3B8F44', primaryColorPressed: '#256B28' } })
</script>

<template>
  <n-config-provider :theme="theme.isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>
