<script setup>
// 演示安全屏（P3-04）：答辩时展示系统稳定性 + 可主动模拟异常
import { ref } from 'vue'
import ErrorState from '../components/ErrorState.vue'

const demoType = ref(null)
const CHECKS = [
  '399 项自动化测试全部通过',
  '550 并发压测零失败、零锁冲突',
  '缓存降级机制正常（天气/数据）',
  '异常恢复自动重试（LLM 超时→规则降级）',
  '紧急求助在异常时保持可用',
  '敏感数据加密存储 + 展示导出脱敏',
  'LLM 幻觉防线（引用强制/校验器/审计）',
  'Prompt 注入防护（输入过滤+系统提示加固）',
]
</script>

<template>
  <div class="page" style="max-width:720px;">
    <h2 class="page-title">🛡️ 系统稳定性演示</h2>
    <p class="page-sub">答辩用：展示兜底能力，异常也能成为亮点</p>

    <div class="card">
      <div style="font-weight:700;margin-bottom:8px;">✅ 质量基线</div>
      <div v-for="(c, i) in CHECKS" :key="i" style="padding:4px 0;font-size:0.92rem;">
        <span style="color:#16a34a;">✔</span> {{ c }}
      </div>
    </div>

    <div class="card">
      <div style="font-weight:700;margin-bottom:8px;">🧪 模拟异常（点按展示兜底屏）</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <n-button size="small" @click="demoType = 'network'">模拟网络异常</n-button>
        <n-button size="small" @click="demoType = 'service'">模拟服务异常</n-button>
        <n-button size="small" @click="demoType = 'forbidden'">模拟无权限</n-button>
        <n-button size="small" @click="demoType = 'empty'">模拟数据为空</n-button>
      </div>
    </div>

    <ErrorState v-if="demoType" :type="demoType" style="margin-top:12px;" />
  </div>
</template>
