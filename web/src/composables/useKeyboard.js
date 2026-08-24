// 软键盘弹出适配：聚焦元素延迟滚入可视区 + iOS 键盘收起归位（visualViewport 兜底）
// 在 main.js 入口调用一次。纯增强，无副作用，安装即可用。
export function useKeyboardFix() {
  if (typeof window === 'undefined') return
  let timer = null

  const onFocusIn = (e) => {
    const el = e.target
    if (!(el instanceof HTMLElement)) return
    clearTimeout(timer)
    // 等键盘弹出动画结束再滚，避免两段滚动
    timer = setTimeout(() => {
      try { el.scrollIntoView({ block: 'center', behavior: 'smooth' }) } catch { /* 忽略 */ }
    }, 300)
  }
  document.addEventListener('focusin', onFocusIn, true)

  // iOS Safari 键盘收起后页面可能滞留上移：通过 role=button 等触发可聚焦元素重新回位
  const vv = window.visualViewport
  const onResize = () => {
    if (vv && window.innerHeight - vv.height < 150) {
      window.scrollTo({ top: window.scrollY })
    }
  }
  if (vv) vv.addEventListener('resize', onResize, { passive: true })

  return () => {
    document.removeEventListener('focusin', onFocusIn, true)
    if (vv) vv.removeEventListener('resize', onResize)
  }
}
