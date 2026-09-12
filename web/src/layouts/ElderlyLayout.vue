<script setup>
// 老年端布局：顶部标题 + 大字导航 + 内容
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const navs = [
  { key: '/elderly/home', label: '🏠 首页' },
  { key: '/elderly/agent', label: '🤖 小助手' },
  { key: '/elderly/report', label: '🗣️ 报修' },
  { key: '/elderly/orders', label: '🔧 我的报修' },
  { key: '/elderly/medication', label: '💊 用药' },
  { key: '/elderly/contacts', label: '👨‍👩‍👧 联系人' },
  { key: '/elderly/notices', label: '🔊 通知' },
  { key: '/elderly/qa', label: '📖 政策' },
]
</script>

<template>
  <div style="min-height:100vh;background:var(--bg);">
    <div style="padding-top:calc(14px + env(safe-area-inset-top));padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right));background:linear-gradient(135deg,#2D5BFF 0%,#6A8DFF 100%);color:#fff;display:flex;align-items:center;justify-content:space-between;">
      <div style="font-size:1.3rem;font-weight:800;">🏘️ 社区服务</div>
      <n-button size="small" text style="color:#fff;font-size:1.25rem;" @click="store.logout(); router.replace('/login')">退出</n-button>
    </div>
    <div class="elderly-nav" style="display:flex;gap:10px;padding:12px 14px;background:var(--primary-light,#E8EDFF);flex-wrap:wrap;">
      <n-button v-for="n in navs" :key="n.key" size="large" round
                :type="route.path.startsWith(n.key) ? 'primary' : 'default'"
                @click="router.push(n.key)" style="min-height:64px;font-size:1.25rem;font-weight:700;padding:0 22px;">
        {{ n.label }}
      </n-button>
    </div>
    <router-view />
    <div class="elderly-rotate-mask">📱<br/>请竖屏使用<br/>转动手机回到竖屏</div>
  </div>
</template>
