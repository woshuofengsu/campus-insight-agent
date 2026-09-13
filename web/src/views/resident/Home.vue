<script setup>
// 居民首页 v2（视觉系统最终版）：欢迎横幅（渐变流动）+ 天气卡 + 未读提醒 + 社区小助手 + 彩色快捷入口
// 业务逻辑与 v1 完全一致（天气/通知/紧急弹窗/Agent 展开收起），仅重做视觉层
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../../stores/user'
import { weather, notices } from '../../api'
import AgentChat from '../../components/AgentChat.vue'

const router = useRouter()
const store = useUserStore()

const w = ref(null)
const noticeList = ref([])
const urgentModal = ref(null) // 紧急通知弹窗
const agentOpen = ref(true)   // 社区小助手默认展开可收起

onMounted(async () => {
  try { w.value = await weather.current() } catch { /* 天气失败不阻塞 */ }
  try { noticeList.value = (await notices.list()) || [] } catch { /* 忽略 */ }
  const urgent = noticeList.value.find((n) => n.is_urgent && !n.is_read)
  if (urgent) urgentModal.value = urgent
})

const unread = () => noticeList.value.filter((n) => !n.is_read).length

async function closeUrgent() {
  const n = urgentModal.value
  urgentModal.value = null
  if (n && !n.is_read) {
    try {
      await notices.action(n.id, { action: 'mark_read' })
      noticeList.value = (await notices.list()) || []
    } catch { /* 忽略 */ }
  }
}

// 彩色快捷入口（每格独立色系，点击上浮 + 图标弹跳）
const entries = [
  { to: '/resident/work-orders', icon: '🔧', label: '报修', desc: '报修进度', color: '#2D5BFF', bg: 'rgba(45,91,255,0.10)' },
  { to: '/resident/proposals', icon: '💡', label: '邻里议事', desc: '提案投票', color: '#FF8C42', bg: 'rgba(255,140,66,0.12)' },
  { to: '/resident/qa', icon: '📖', label: '政策问答', desc: '医保社保', color: '#14B8A6', bg: 'rgba(20,184,166,0.12)' },
  { to: '/resident/notices', icon: '📢', label: '通知', desc: '社区公告', color: '#8B5CF6', bg: 'rgba(139,92,246,0.12)' },
  { to: '/resident/health', icon: '🏥', label: '健康防护', desc: '疾病预防', color: '#10B981', bg: 'rgba(16,185,129,0.12)' },
  { to: '/resident/weather', icon: '🌤️', label: '天气', desc: '生活建议', color: '#0EA5E9', bg: 'rgba(14,165,233,0.12)' },
]

const hour = new Date().getHours()
const greet = hour < 6 ? '夜深了' : hour < 11 ? '早上好' : hour < 13 ? '中午好' : hour < 18 ? '下午好' : '晚上好'
</script>

<template>
  <div class="page">
    <!-- 欢迎横幅（渐变流动 + 问候 + 天气胶囊） -->
    <div class="grad-flow fade-up"
         style="background:var(--primary-gradient-2);border-radius:22px;padding:26px 24px;color:#fff;margin-bottom:14px;position:relative;overflow:hidden;box-shadow:var(--shadow-primary);">
      <div style="position:absolute;width:200px;height:200px;border-radius:50%;background:rgba(255,255,255,0.10);top:-90px;right:-60px;"></div>
      <div style="position:relative;display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;">
        <div>
          <div style="font-size:1.5rem;font-weight:800;letter-spacing:0.01em;">
            {{ greet }}，{{ store.user?.name || '居民' }}
          </div>
          <div style="font-size:0.86rem;opacity:0.86;margin-top:5px;">
            社区先知 · 知 · 报 · 议 · 督，有事随时找小助手
          </div>
        </div>
        <div v-if="w" style="display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.16);border:1px solid rgba(255,255,255,0.24);border-radius:14px;padding:10px 14px;">
          <span class="bob" style="font-size:1.9rem;">{{ w.emoji || '🌤️' }}</span>
          <div>
            <div style="font-size:1.35rem;font-weight:800;line-height:1.1;">{{ w.temp_high }}°C</div>
            <div style="font-size:0.76rem;opacity:0.9;">{{ w.condition }} · {{ w.temp_low }}°~{{ w.temp_high }}°</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 天气提示 / 预警 -->
    <div v-if="w?.note" class="card fade-up-d1" style="background:#fef2f2;border:1px solid #fca5a5;color:var(--ink-danger);font-weight:600;">
      ⚠️ {{ w.note }}
    </div>

    <!-- 未读通知（红点呼吸提醒） -->
    <div v-if="unread() > 0" class="card fade-up-d1 entry-tile" style="background:#f0fdf4;border:1px solid #86efac;display:flex;align-items:center;justify-content:space-between;"
         @click="router.push('/resident/notices')">
      <div style="display:flex;align-items:center;gap:9px;">
        <!-- 白字红底徽标：用 --danger-solid(#DC2626=4.83:1)；#ef4444 只有 3.76:1 不达 AA -->
        <span class="pulse-danger" style="display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:var(--danger-solid);color:#fff;font-size:0.78rem;font-weight:700;line-height:1;">{{ unread() }}</span>
        <b>您有 {{ unread() }} 条未读通知</b>
      </div>
      <n-button size="small" type="success" ghost>查看 ›</n-button>
    </div>

    <!-- 社区小助手（AI 入口，品牌渐变头 + 可收起） -->
    <div class="card fade-up-d2 hero-card" style="padding:0;">
      <div class="grad-flow" style="display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:var(--primary-gradient);color:#fff;">
        <b style="display:flex;align-items:center;gap:8px;">
          <span class="pulse-primary" style="display:inline-flex;width:26px;height:26px;border-radius:9px;background:rgba(255,255,255,0.20);align-items:center;justify-content:center;">🤖</span>
          社区小助手
        </b>
        <n-button size="tiny" text style="color:#fff;" @click="agentOpen = !agentOpen">{{ agentOpen ? '收起 ▲' : '展开 ▼' }}</n-button>
      </div>
      <AgentChat v-if="agentOpen" role="resident" />
    </div>

    <!-- 彩色快捷入口 6 宫格 -->
    <div class="section-title fade-up-d3">常用服务</div>
    <div class="wave" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(148px,1fr));gap:12px;">
      <div v-for="e in entries" :key="e.to" class="entry-tile card"
           style="margin:0;text-align:center;padding:18px 12px;border-radius:18px;"
           @click="router.push(e.to)">
        <div class="entry-icon" style="font-size:2.1rem;line-height:1;">{{ e.icon }}</div>
        <div style="font-weight:700;margin-top:8px;font-size:1.02rem;">{{ e.label }}</div>
        <div style="font-size:0.76rem;color:var(--muted);margin-top:2px;">{{ e.desc }}</div>
        <!-- 无障碍修正：原先用 e.color 作文字色（彩色浅底上仅 2.1~3.65:1，低于 AA 4.5:1），
             改为「同色淡底 + 正文色文字」，亮/暗两种模式都稳定达标 -->
        <div :style="{ background: e.bg }"
             style="display:inline-block;margin-top:9px;padding:2px 10px;border-radius:999px;font-size:0.76rem;font-weight:600;color:var(--text);">
          进入 ›
        </div>
      </div>
    </div>

    <!-- 紧急通知强制弹窗 -->
    <n-modal :show="!!urgentModal" @update:show="(v) => { if (!v) urgentModal = null }" preset="dialog" type="error"
             :title="urgentModal ? ('🚨 ' + urgentModal.title) : ''"
             :content="urgentModal ? urgentModal.body : ''"
             positive-text="我知道了" @positive-click="closeUrgent" />
  </div>
</template>
