<script setup>
// 老年端布局：顶部标题 + 大字导航 + 内容
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const navs = [
  { key: '/elderly/home', label: '🏠 首页' },
  { key: '/elderly/report', label: '🗣️ 报修' },
  { key: '/elderly/orders', label: '🔧 我的报修' },
  { key: '/elderly/medication', label: '💊 用药' },
  { key: '/elderly/contacts', label: '👨‍👩‍👧 联系人' },
  { key: '/elderly/notices', label: '🔊 通知' },
  { key: '/elderly/qa', label: '📖 政策' },
]
</script>

<template>
  <div style="min-height:100vh;background:#fff;">
    <div style="background:#2E7D32;color:#fff;padding:14px 16px;display:flex;align-items:center;justify-content:space-between;">
      <div style="font-size:1.3rem;font-weight:800;">🏘️ 社区服务</div>
      <n-button size="small" text style="color:#fff;" @click="store.logout(); router.replace('/login')">退出</n-button>
    </div>
    <div style="display:flex;gap:8px;padding:10px 12px;background:#f0faf0;flex-wrap:wrap;">
      <n-button v-for="n in navs" :key="n.key" size="large" round
                :type="route.path.startsWith(n.key) ? 'primary' : 'default'"
                @click="router.push(n.key)" style="min-height:52px;font-size:1.1rem;">
        {{ n.label }}
      </n-button>
    </div>
    <router-view />
  </div>
</template>
