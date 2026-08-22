<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../stores/user'

const router = useRouter()
const message = useMessage()
const store = useUserStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function doLogin() {
  if (!username.value) return message.warning('请输入用户名')
  loading.value = true
  try {
    await store.login(username.value, password.value)
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    router.replace(home[store.role] || '/login')
  } catch (e) {
    message.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

async function demo(role) {
  loading.value = true
  try {
    await store.demoLogin(role)
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    router.replace(home[role])
  } catch (e) {
    message.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#1E3A8A 0%,#2D5BFF 60%,#6A8DFF 100%);">
    <div style="background:var(--card-bg);border-radius:20px;padding:40px 36px;width:380px;box-shadow:0 16px 48px rgba(0,0,0,0.25);">
      <div style="text-align:center;margin-bottom:24px;">
        <div style="font-size:2.4rem;">🏘️</div>
        <div style="font-size:1.4rem;font-weight:800;color:#1f2937;">社区先知</div>
        <div style="color:#6b7280;font-size:0.85rem;margin-top:4px;">CommunityInsight · 社区治理多智能体平台</div>
      </div>

      <n-form @submit.prevent="doLogin">
        <n-form-item label="用户名">
          <n-input v-model:value="username" placeholder="如 demo_grid" size="large" />
        </n-form-item>
        <n-form-item label="密码">
          <n-input v-model:value="password" type="password" placeholder="演示账号 demo_grid / demo123" size="large" />
        </n-form-item>
        <n-button type="primary" block size="large" :loading="loading" attr-type="submit">登 录</n-button>
      </n-form>

      <n-divider style="font-size:0.8rem;color:#9ca3af;">快速体验</n-divider>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
        <n-button secondary type="success" @click="demo('resident')">居民</n-button>
        <n-button secondary type="warning" @click="demo('grid')">网格员</n-button>
        <n-button secondary type="error" @click="demo('elderly')">👴 老年入口（免登录）</n-button>
      </div>
      <div style="text-align:center;color:#9ca3af;font-size:0.75rem;margin-top:16px;">
        居民/老人演示免密 · 网格员 demo123
      </div>
    </div>
  </div>
</template>
