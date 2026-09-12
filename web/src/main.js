import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import './style.css'
import './mobile.css'
import { useKeyboardFix } from './composables/useKeyboard.js'

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
