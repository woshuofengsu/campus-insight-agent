import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import './mobile.css'
import { useKeyboardFix } from './composables/useKeyboard.js'

// 暗色类必须**挂载前**落到 body（复审 F3）：App.vue 里是在 onMounted 才 theme.apply()，
// 而 Naive 的暗色主题是 JS 主题、两者生效差一帧 —— 那一帧里 Naive 已把卡片染暗、
// 我们的 CSS 变量还停在亮色值，用户看到的是一次暗色闪烁（FOUC），
// 自动化审计在这一帧采样还会抓到"假的不达标"。
// 这里先按 localStorage 定类，App.vue 的 apply() 保留（切换主题仍以它为准）。
try {
  if (localStorage.getItem('ci_theme') === 'dark') document.body.classList.add('dark')
} catch (e) { /* 隐私模式下 localStorage 不可用时忽略，走默认亮色 */ }

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
useKeyboardFix()

// 页面不可见时暂停 CSS 动画（style.css 的 body.anim-paused）：
// 挂墙大屏/低端机在后台标签里不必为空转的循环动效消耗 GPU 与电量。
document.addEventListener('visibilitychange', () => {
  document.body.classList.toggle('anim-paused', document.hidden)
})
