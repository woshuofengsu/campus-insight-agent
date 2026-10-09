<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from './stores/user'
import { useThemeStore } from './stores/theme'
import { darkTheme } from 'naive-ui'
// 设计令牌同源（v2 §12.3/§12.7-1）：与 style.css 共用的颜色从 tokens.js 取，
// 不在这里内联裸 hex —— 两边各写一份是"改了一半就悄悄漂移"的根源。
// 一致性由 tests/test_design_tokens.py 逐条核对（不是靠自觉）。
import { LIGHT, DARK, THEME_ONLY as T } from './config/tokens'

const store = useUserStore()
const theme = useThemeStore()
const router = useRouter()

// 登录后按角色跳对应端首页
// 修复（本轮）：原先在 onMounted 直接读 router.currentRoute.value.path —— 此时首屏导航
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
        primaryColor: T.darkPrimary, primaryColorHover: T.darkPrimaryHover,
        // 按下态用品牌蓝本体（style.css 里 `--primary` 在暗色下**没有**被重定义，两种模式同值）
        primaryColorPressed: LIGHT.primary,
        successColor: T.darkSuccess, warningColor: T.darkWarning, errorColor: T.darkError, infoColor: T.darkInfo,
        bodyColor: DARK.bg, cardColor: DARK.cardBg, modalColor: DARK.cardBg, popoverColor: DARK.cardBg,
        textColorBase: DARK.text, textColor1: DARK.text, textColor2: '#CBD5E1', textColor3: DARK.muted,
        borderColor: DARK.border, dividerColor: DARK.border, tableColor: DARK.cardBg,
        inputColor: DARK.bg, borderRadius: '10px', borderRadiusSmall: '8px',
        fontFamily: FONT,
      },
      Button: { borderRadiusMedium: '10px', fontWeight: '600' },
      Card: { borderRadius: '16px' },
      Input: { borderRadius: '10px', placeholderColor: T.placeholder },
      // Select/级联等的占位符走 InternalSelection 自己的 --n-placeholder-color
      // （不改就是 Naive 默认 #C2C2C2，白底 1.78:1；审计在提案类别下拉里实测抓到）
      Select: { peers: { InternalSelection: { borderRadius: '10px', placeholderColor: T.placeholder } } },
      Modal: { borderRadius: '20px' },
      // 无障碍修正：Naive 默认 placeholder(#C2C2C2, 1.78:1) / Divider 文字(#9CA3AF, 2.54:1) /
      // success 标签文字(2.27:1) 都低于 WCAG AA 4.5:1，这里统一提到达标值
      Divider: { textColor: DARK.muted },
      Empty: { textColor: DARK.muted, iconColor: '#475569' },
      Tag: {
        textColorSuccess: DARK.inkSuccess, textColorWarning: DARK.inkWarning,
        textColorError: DARK.inkDanger, textColorInfo: DARK.inkInfo,
        textColorPrimary: DARK.primaryInk,
        colorSuccess: 'rgba(52,211,153,0.16)',
      },
    }
  : {
      common: {
        primaryColor: LIGHT.primary, primaryColorHover: T.lightPrimaryHover,
        primaryColorPressed: LIGHT.primaryDeep,
        primaryColorSuppl: T.lightPrimarySuppl,
        // errorColor 由 #EF4444 调深：白字配 #EF4444 只有 3.76:1，不达 AA；#DC2626 为 4.84:1
        successColor: T.lightSuccess, warningColor: T.lightWarning,
        errorColor: LIGHT.dangerSolid, infoColor: T.lightInfo,
        // 无障碍修正（第九轮）：Naive 的 errorColorHover 默认是 #de576d，而**弹窗确认按钮会被自动聚焦**
        // （focus 态取 errorColorHover），实测白字只有 3.69:1。这里把 hover/pressed/focus 也一起调深：
        // hover #C0223B = 5.94:1，pressed #A11C33 = 7.69:1。
        errorColorHover: T.lightErrorHover, errorColorPressed: T.lightErrorPressed,
        errorColorSuppl: T.lightErrorHover,
        textColorBase: LIGHT.text, textColor1: LIGHT.text, textColor2: '#334155', textColor3: '#64748B',
        borderColor: LIGHT.border, dividerColor: LIGHT.border,
        borderRadius: '10px', borderRadiusSmall: '8px',
        fontFamily: FONT,
      },
      Button: {
        borderRadiusMedium: '10px', fontWeight: '600',
        // 无障碍修正：Naive 语义色填充按钮用的是**白字**，白字配 #10B981/#F59E0B/#0EA5E9
        // 实测只有 2.5~2.8:1。这里只把「填充按钮」的底色调深（标签/图表仍用上面的亮色），
        // 白字对比度：success 5.54 / warning 5.05 / error 4.84 / info 5.94，全部达标。
        colorSuccess: LIGHT.inkSuccess, colorHoverSuccess: T.lightSuccessFillHover,
        colorPressedSuccess: T.lightSuccessFillPressed,
        colorWarning: LIGHT.inkWarning, colorHoverWarning: T.lightWarningFillHover,
        colorPressedWarning: T.lightWarningFillPressed,
        colorInfo: T.lightInfoFill, colorHoverInfo: T.lightInfoFillHover,
        colorPressedInfo: T.lightInfoFillPressed,
      },
      Card: { borderRadius: '12px' },
      // 占位符/空态文字：v3 起统一用 LIGHT.muted（#5C6B73 = 白底 5.6:1）。
      // 注意：原来写死 #66738A 只有 **4.41:1**，`ui_audit` 在居民端「暂无健康内容」上实测抓到
      // （低于 12–14px 文字要求的 4.5:1）；v3 换配色时顺手改成令牌，避免同类漏网。
      Input: { borderRadius: '10px', placeholderColor: LIGHT.muted },
      Select: { peers: { InternalSelection: { borderRadius: '10px', placeholderColor: LIGHT.muted } } },
      Modal: { borderRadius: '12px' },
      Divider: { textColor: LIGHT.muted },
      Empty: { textColor: LIGHT.muted, iconColor: '#CBD5E1' },
      // Tag 文字色：Naive 默认直接用 warning/error 的亮色作文字（实测 1.96:1），改为深色变体
      Tag: {
        textColorSuccess: '#0A6B39', textColorWarning: '#92400E', textColorError: LIGHT.inkDanger,
        textColorInfo: T.lightInfoFill, textColorPrimary: '#1E40AF',
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
