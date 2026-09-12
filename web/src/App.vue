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

// 视觉系统 v2：统一品牌蓝 + 字体 + 圆角（亮/暗两套）
const FONT = '"PingFang SC","HarmonyOS Sans SC","MiSans","Microsoft YaHei","Inter","Roboto",-apple-system,"Segoe UI",sans-serif'

const themeOverrides = computed(() => theme.isDark
  ? {
      common: {
        primaryColor: '#6A8DFF', primaryColorHover: '#8FA8FF', primaryColorPressed: '#2D5BFF',
        successColor: '#34D399', warningColor: '#FBBF24', errorColor: '#F87171', infoColor: '#38BDF8',
        bodyColor: '#0F172A', cardColor: '#1E293B', modalColor: '#1E293B', popoverColor: '#1E293B',
        textColorBase: '#E2E8F0', textColor1: '#E2E8F0', textColor2: '#CBD5E1', textColor3: '#94A3B8',
        borderColor: '#334155', dividerColor: '#334155', tableColor: '#1E293B',
        inputColor: '#0F172A', borderRadius: '10px', borderRadiusSmall: '8px',
        fontFamily: FONT,
      },
      Button: { borderRadiusMedium: '10px', fontWeight: '600' },
      Card: { borderRadius: '16px' },
      Input: { borderRadius: '10px' },
      Select: { peers: { InternalSelection: { borderRadius: '10px' } } },
      Modal: { borderRadius: '20px' },
    }
  : {
      common: {
        primaryColor: '#2D5BFF', primaryColorHover: '#4F74FF', primaryColorPressed: '#1E3A8A',
        primaryColorSuppl: '#6A8DFF',
        successColor: '#10B981', warningColor: '#F59E0B', errorColor: '#EF4444', infoColor: '#0EA5E9',
        textColorBase: '#16233B', textColor1: '#16233B', textColor2: '#334155', textColor3: '#64748B',
        borderColor: '#E7ECF3', dividerColor: '#E7ECF3',
        borderRadius: '10px', borderRadiusSmall: '8px',
        fontFamily: FONT,
      },
      Button: { borderRadiusMedium: '10px', fontWeight: '600' },
      Card: { borderRadius: '16px' },
      Input: { borderRadius: '10px' },
      Select: { peers: { InternalSelection: { borderRadius: '10px' } } },
      Modal: { borderRadius: '20px' },
    })
</script>

<template>
  <n-config-provider :theme="theme.isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <n-message-provider>
      <n-dialog-provider>
        <router-view v-slot="{ Component }">
          <transition name="page-fade" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>
