// 主题状态：light / dark（夜间模式），localStorage 持久化
import { defineStore } from 'pinia'

export const useThemeStore = defineStore('theme', {
  state: () => ({
    mode: localStorage.getItem('ci_theme') || 'light',
  }),
  getters: {
    isDark: (s) => s.mode === 'dark',
  },
  actions: {
    toggle() {
      this.mode = this.mode === 'light' ? 'dark' : 'light'
      localStorage.setItem('ci_theme', this.mode)
      this.apply()
    },
    apply() {
      // 切换 document.body 类，驱动 CSS 变量
      document.body.classList.toggle('dark', this.mode === 'dark')
    },
  },
})
