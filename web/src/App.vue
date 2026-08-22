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
  ? {
      common: {
        primaryColor: '#2D5BFF', primaryColorHover: '#6A8DFF', primaryColorPressed: '#1E3A8A',
        bodyColor: '#0F172A', cardColor: '#1E293B', textColorBase: '#E2E8F0',
        borderRadius: '10px',
      },
    }
  : {
      common: {
        primaryColor: '#2D5BFF', primaryColorHover: '#6A8DFF', primaryColorPressed: '#1E3A8A',
        borderRadius: '10px',
      },
    })
</script>

<template>
  <n-config-provider :theme="theme.isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>
