<script setup>
// 通用异常状态组件（P3-04）：网络/服务/无权限/数据为空，友好提示 + 恢复入口
import { useRouter } from 'vue-router'

const props = defineProps({
  type: { type: String, default: 'network' }, // network | service | forbidden | empty
  title: { type: String, default: '' },
  desc: { type: String, default: '' },
})
const router = useRouter()

const MAP = {
  network: { icon: '📡', title: '网络似乎断了', desc: '请检查网络连接后重试', action: '重新连接' },
  service: { icon: '🛠️', title: '服务暂时不可用', desc: '我们正在努力修复，请稍后再试。紧急求助保持可用', action: '重新尝试' },
  forbidden: { icon: '🔒', title: '您无权访问', desc: '该操作需要对应权限，请联系管理员开通', action: '返回首页' },
  empty: { icon: '📭', title: '暂无数据', desc: '还没有相关记录', action: '立即创建' },
}

const m = MAP[props.type] || MAP.network

function retry() {
  if (props.type === 'forbidden') router.push('/')
  else window.location.reload()
}
</script>

<template>
  <div style="min-height:60vh;display:flex;align-items:center;justify-content:center;padding:24px;">
    <div style="text-align:center;max-width:360px;">
      <div style="font-size:3rem;">{{ m.icon }}</div>
      <div style="font-size:1.2rem;font-weight:800;margin:12px 0 6px;">{{ title || m.title }}</div>
      <div class="muted" style="font-size:0.9rem;line-height:1.8;">{{ desc || m.desc }}</div>
      <n-button type="primary" style="margin-top:18px;" @click="retry">{{ m.action }}</n-button>
      <slot />
    </div>
  </div>
</template>
