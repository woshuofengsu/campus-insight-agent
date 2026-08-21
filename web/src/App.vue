<script setup>
import { useUserStore } from './stores/user'
// 登录后按角色跳对应端首页
import { useRouter } from 'vue-router'
import { watch } from 'vue'

const store = useUserStore()
const router = useRouter()

watch(
  () => store.role,
  (role) => {
    if (!role) return
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    if (!router.currentRoute.value.path.startsWith(`/${role}`)) {
      router.replace(home[role] || '/login')
    }
  },
  { immediate: true },
)
</script>

<template>
  <n-config-provider :theme-overrides="{ common: { primaryColor: '#2E7D32', primaryColorHover: '#3B8F44', primaryColorPressed: '#256B28' } }">
    <n-message-provider>
      <router-view />
    </n-message-provider>
  </n-config-provider>
</template>
