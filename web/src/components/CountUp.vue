<script setup>
// 数字滚动（视觉系统 v2 动效层）：纯 requestAnimationFrame，零依赖
// · 差值动画：从"当前显示值"滚到新值（大屏 30 秒刷新时不会从 0 重滚导致抖动）
// · 尊重系统「减少动态」设置：直接落值，不做动画
// · 非数字（如 '--'）原样显示，不参与动画
import { ref, watch, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  value: { type: [Number, String], default: 0 },
  duration: { type: Number, default: 1400 },
  decimals: { type: Number, default: 0 },
  suffix: { type: String, default: '' },
})

const shown = ref(typeof props.value === 'number' ? 0 : props.value)
let raf = null

const reduced = (() => {
  try {
    return typeof window !== 'undefined' && window.matchMedia
      ? window.matchMedia('(prefers-reduced-motion: reduce)').matches
      : false
  } catch { return false }
})()

function animateTo(target) {
  const to = Number(target)
  const from = Number(shown.value)
  if (!Number.isFinite(to)) { shown.value = target; return }
  if (reduced || !Number.isFinite(from) || from === to) { shown.value = to; return }
  if (raf) cancelAnimationFrame(raf)
  const t0 = performance.now()
  const step = (now) => {
    const p = Math.min(1, (now - t0) / props.duration)
    const eased = 1 - Math.pow(1 - p, 3) // ease-out cubic
    shown.value = from + (to - from) * eased
    if (p < 1) raf = requestAnimationFrame(step)
    else { shown.value = to; raf = null }
  }
  raf = requestAnimationFrame(step)
}

onMounted(() => { if (typeof props.value === 'number') animateTo(props.value) })
watch(() => props.value, (v) => { if (typeof v === 'number') animateTo(v) })
onUnmounted(() => { if (raf) cancelAnimationFrame(raf) })
</script>

<template>
  <span>{{ typeof shown === 'number' ? shown.toFixed(decimals) : shown }}{{ suffix }}</span>
</template>
