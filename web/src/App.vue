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
// ⚠ 修复（本轮）：原先在 onMounted 直接读 router.currentRoute.value.path —— 此时首屏导航
// 往往还没解析完（路径仍是 '/'），于是任何**深链刷新**（如 /grid/work-orders）以及公开页
// /screen 都会被强制弹回角色首页；刷新丢失当前页面、大屏在登录后永远打不开。
// 正确做法：先 await router.isReady()，且**只**在根路径/登录页做兜底跳转。
onMounted(async () => {
  theme.apply()
  await router.isReady()
  const role = store.role
  const path = router.currentRoute.value.path
  if (role && (path === '/' || path === '/login')) {
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    router.replace(home[role] || '/login')
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
      Input: { borderRadius: '10px', placeholderColor: '#8B95A8' },
      Select: { peers: { InternalSelection: { borderRadius: '10px' } } },
      Modal: { borderRadius: '20px' },
      // 无障碍修正：Naive 默认 placeholder(#C2C2C2, 1.78:1) / Divider 文字(#9CA3AF, 2.54:1) /
      // success 标签文字(2.27:1) 都低于 WCAG AA 4.5:1，这里统一提到达标值
      Divider: { textColor: '#94A3B8' },
      Empty: { textColor: '#94A3B8', iconColor: '#475569' },
      Tag: {
        textColorSuccess: '#6EE7B7', textColorWarning: '#FCD34D', textColorError: '#FCA5A5',
        textColorInfo: '#7DD3FC', textColorPrimary: '#93B4FF',
        colorSuccess: 'rgba(52,211,153,0.16)',
      },
    }
  : {
      common: {
        primaryColor: '#2D5BFF', primaryColorHover: '#4F74FF', primaryColorPressed: '#1E3A8A',
        primaryColorSuppl: '#6A8DFF',
        // errorColor 由 #EF4444 调深：白字配 #EF4444 只有 3.76:1，不达 AA；#DC2626 为 4.84:1
        successColor: '#10B981', warningColor: '#F59E0B', errorColor: '#DC2626', infoColor: '#0EA5E9',
        // 无障碍修正（第九轮）：Naive 的 errorColorHover 默认是 #de576d，而**弹窗确认按钮会被自动聚焦**
        // （focus 态取 errorColorHover），实测白字只有 3.69:1。这里把 hover/pressed/focus 也一起调深：
        // hover #C0223B = 5.94:1，pressed #A11C33 = 7.69:1。
        errorColorHover: '#C0223B', errorColorPressed: '#A11C33', errorColorSuppl: '#C0223B',
        textColorBase: '#16233B', textColor1: '#16233B', textColor2: '#334155', textColor3: '#64748B',
        borderColor: '#E7ECF3', dividerColor: '#E7ECF3',
        borderRadius: '10px', borderRadiusSmall: '8px',
        fontFamily: FONT,
      },
      Button: {
        borderRadiusMedium: '10px', fontWeight: '600',
        // 无障碍修正：Naive 语义色填充按钮用的是**白字**，白字配 #10B981/#F59E0B/#0EA5E9
        // 实测只有 2.5~2.8:1。这里只把「填充按钮」的底色调深（标签/图表仍用上面的亮色），
        // 白字对比度：success 5.54 / warning 5.05 / error 4.84 / info 5.94，全部达标。
        colorSuccess: '#047857', colorHoverSuccess: '#036B4E', colorPressedSuccess: '#02543D',
        colorWarning: '#B45309', colorHoverWarning: '#92400E', colorPressedWarning: '#78350F',
        colorInfo: '#0369A1', colorHoverInfo: '#075985', colorPressedInfo: '#0C4A6E',
      },
      Card: { borderRadius: '16px' },
      Input: { borderRadius: '10px', placeholderColor: '#66738A' },
      Select: { peers: { InternalSelection: { borderRadius: '10px' } } },
      Modal: { borderRadius: '20px' },
      Divider: { textColor: '#5B6B80' },
      Empty: { textColor: '#66738A', iconColor: '#CBD5E1' },
      // Tag 文字色：Naive 默认直接用 warning/error 的亮色作文字（实测 1.96:1），改为深色变体
      Tag: {
        textColorSuccess: '#0A6B39', textColorWarning: '#92400E', textColorError: '#B91C1C',
        textColorInfo: '#0369A1', textColorPrimary: '#1E40AF',
        colorSuccess: 'rgba(16,185,129,0.14)',
      },
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
