<script setup>
// 老年端布局：顶部标题 + 大字导航（**6 个入口，已按 v3 复核 B4 收敛**）+ 内容
//
// 为什么收敛：原来顶层摆了 8 个按钮（首页/小助手/报修/我的报修/用药/联系人/通知/政策），
// 首页又有一整套入口 —— 对老人来说"每个都在，等于每个都找不到"。
// 现在顶层只留 5 个高频入口 + 1 个**独立紧急求助键**（在任何页面都能一键到达），
// 其余（小助手/政策问答/用药/健康）收进「更多服务」页；**路由全部保留**，只是展示入口收敛。
import { onMounted, onBeforeUnmount, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../stores/user'
import { useSos } from '../composables/useSos'
import EIcon from '../components/EIcon.vue'

const router = useRouter()
const route = useRoute()
const store = useUserStore()
const message = useMessage()

// 在 body 上打角色类：Naive 的弹窗会 teleport 到 body，
// 只写在 .elderly-page 下的适老样式命不中它们（紧急通知弹窗正是这种）。
// 有了 body.role-elderly，弹窗字号/热区规则就能覆盖（见 style.css）。
onMounted(() => document.body.classList.add('role-elderly'))
onBeforeUnmount(() => document.body.classList.remove('role-elderly'))

// 独立紧急求助（长按 3 秒 → 10 秒确认）：与首页大按钮**共用同一套逻辑**
const sos = useSos({ onMessage: message })
// 老人从别的页面按求助键时，先记下当前页，触发成功后就地提示"首页可拨打 120"
const sosHint = computed(() => route.path === '/elderly/home')

// 图标改**单色线性 SVG**（`components/EIcon.vue`），不再用 emoji：
// emoji 在各家手机上是不同厂商字形（大小/配色/有无都不一样），而这排按钮是老人看见次数最多的图形。
// 文字一个字没改（`mobile_flow_check` 按文字找按钮：'更多服务' 等仍在），只是把图形换成跟着文字色走的线性图标。
const navs = [
  { key: '/elderly/home', label: '首页', icon: 'home' },
  { key: '/elderly/report', label: '反映问题', icon: 'speak' },
  { key: '/elderly/orders', label: '看看进度', icon: 'list' },
  { key: '/elderly/contacts', label: '联系家人', icon: 'family' },
  { key: '/elderly/notices', label: '今日提醒', icon: 'bell' },
  { key: '/elderly/more', label: '更多服务', icon: 'more' },
]
</script>

<template>
  <div style="min-height:100vh;background:var(--bg);">
    <div style="padding-top:calc(14px + env(safe-area-inset-top));padding-left:max(16px,env(safe-area-inset-left));padding-right:max(16px,env(safe-area-inset-right));background:linear-gradient(135deg,#2D5BFF 0%,#6A8DFF 100%);color:#fff;display:flex;align-items:center;justify-content:space-between;gap:10px;">
      <div style="font-size:1.3rem;font-weight:800;display:flex;align-items:center;gap:8px;">
        <EIcon name="community" :size="30" />社区服务
      </div>
      <div style="display:flex;align-items:center;gap:8px;">
        <!-- 独立紧急求助：任何页面都能一键到达（长按 3 秒仍然防误触） -->
        <n-button size="large" type="error" data-longpress
                  style="color:#fff;font-size:1.3rem;min-height:56px;font-weight:800;background:linear-gradient(135deg,#DC2626,#B91C1C);"
                  @pointerdown="sos.pressStart" @pointerup="sos.pressCancel" @pointerleave="sos.pressCancel"
                  @touchstart.prevent="sos.pressStart" @touchend="sos.pressCancel">
          <EIcon name="alert" :size="28" />紧急求助
        </n-button>
        <n-button size="large" text style="color:#fff;font-size:1.25rem;min-height:48px;" @click="store.logout(); router.replace('/login')">退出</n-button>
      </div>
    </div>
    <div class="elderly-nav" style="display:flex;gap:10px;padding:12px 14px;background:var(--primary-light,#E8EDFF);flex-wrap:wrap;">
      <n-button v-for="n in navs" :key="n.key" size="large" round
                :type="route.path.startsWith(n.key) ? 'primary' : 'default'"
                @click="router.push(n.key)" style="min-height:64px;font-size:1.25rem;font-weight:700;padding:0 22px;">
        <span style="display:inline-flex;align-items:center;gap:10px;">
          <EIcon :name="n.icon" :size="28" /><span>{{ n.label }}</span>
        </span>
      </n-button>
    </div>
    <router-view />

    <!-- 紧急求助确认弹窗（与首页同一个状态机：10 秒未确认自动取消） -->
    <n-modal v-model:show="sos.sosConfirm.value" preset="dialog" type="error" title="确认紧急求助？"
             positive-text="确认求助" negative-text="取消"
             @positive-click="sos.confirmSos" @negative-click="sos.cancelConfirm">
      <template #default>
        <div style="text-align:center;font-size:1.3rem;">
          将通知社区负责人{{ sos.contactNames.value ? `，以及紧急联系人：${sos.contactNames.value}` : '' }}。
        </div>
        <div style="text-align:center;font-size:2.1rem;font-weight:800;color:var(--ink-danger);margin-top:8px;">
          {{ sos.sosCountdown.value }} 秒后自动取消
        </div>
        <div v-if="!sosHint" class="muted" style="text-align:center;margin-top:8px;font-size:1.1rem;">
          需要打 120 请回到首页（那里有红色「拨打 120」按钮）
        </div>
      </template>
    </n-modal>

    <div class="elderly-rotate-mask"><EIcon name="phone" :size="40" /><br/>请竖屏使用<br/>转动手机回到竖屏</div>
  </div>
</template>
