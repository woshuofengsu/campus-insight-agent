<script setup>
// 登录页 v3（2026-10-06「社区服务站」重设计）
// v2 → v3：删掉网格渐变背景 / 3 个光晕球 / 12 颗星光粒子 / 玻璃卡 / 数字滚动 / 流光按钮，
//          左栏从"技术能力展示"改成"这个服务站能办什么"。
// 业务逻辑与 v1/v2 **完全一致**（staff 登录 / 演示免密 / 角色跳转），仅重做视觉与文案。
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../stores/user'
import { BRAND_METRICS } from '../config/meta.js'
import EIcon from '../components/EIcon.vue'
// 品牌指标：唯一来源 web/src/config/meta.js（数字真实、可复算，由 demo_preflight 自动核对）；
// v3 起**静态显示**，不再做 CountUp 数字滚动（工作台/登录页都不该"跳数"）
const stats = BRAND_METRICS

const router = useRouter()
const message = useMessage()
const store = useUserStore()

const username = ref('')
const password = ref('')
const loading = ref(false)

async function doLogin() {
  if (!username.value) return message.warning('请输入用户名')
  loading.value = true
  try {
    await store.login(username.value, password.value)
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    router.replace(home[store.role] || '/login')
  } catch (e) {
    message.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

async function demo(role) {
  loading.value = true
  try {
    await store.demoLogin(role)
    const home = { resident: '/resident/home', grid: '/grid/dashboard', elderly: '/elderly/home' }
    router.replace(home[role])
  } catch (e) {
    message.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}

const roles = [
  { role: 'resident', icon: 'home', label: '居民', desc: '报修 · 议事 · 问策' },
  { role: 'elderly', icon: 'users', label: '老年', desc: '大字 · 语音 · 免密' },
  { role: 'grid', icon: 'wrench', label: '网格员', desc: '工单 · 督办 · 决策' },
]

// 品牌指标：唯一来源 web/src/config/meta.js（原先硬编码在这里，其中「AI 自转率 62%」与后端
// 实测口径对不上；现已移除易变业务指标，只留可复算的稳定项，并由 demo_preflight 自动核对）
</script>

<template>
  <div style="min-height:100vh;position:relative;display:flex;align-items:center;justify-content:center;padding:24px;overflow:hidden;">
    <!-- 双栏主卡（v3：无背景装饰，就是一张干净的卡片） -->
    <div class="card"
         style="position:relative;z-index:1;border-radius:var(--r-card-lg);width:900px;max-width:100%;display:flex;flex-wrap:wrap;overflow:hidden;padding:0;gap:0;">
      <!-- 左：服务站说明（纯品牌色底 + 白字 6.4:1；不再渐变、不放光斑） -->
      <div style="flex:1 1 390px;min-width:320px;background:var(--primary);color:#fff;padding:40px 34px;display:flex;flex-direction:column;justify-content:space-between;">
        <div>
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:22px;">
            <div style="width:48px;height:48px;border-radius:var(--r-btn);background:rgba(255,255,255,0.18);display:flex;align-items:center;justify-content:center;border:1px solid rgba(255,255,255,0.26);"><EIcon name="community" :size="30" /></div>
            <div>
              <div style="font-size:1.55rem;font-weight:800;letter-spacing:0.02em;">社区先知</div>
              <div style="font-size:0.8rem;opacity:0.82;letter-spacing:0.04em;">社区服务站 · 接诉即办</div>
            </div>
          </div>

          <div style="font-size:1.06rem;line-height:1.75;opacity:0.96;">
            社区里的事，在这里说、在这里办、<br/>办到哪一步都看得见。
          </div>

          <!-- v3：不摆技术名词（智能体/黑板/Verifier 这类留给答辩材料），只写"居民能得到什么" -->
          <div style="margin-top:20px;display:flex;flex-direction:column;gap:9px;">
            <div v-for="f in [
              { icon: 'speak', text: '说一句就能报事，有人接、有安排' },
              { icon: 'list', text: '进度随时可查，办完有反馈' },
              { icon: 'users', text: '老人也适用：大字、能听、免登录' },
            ]" :key="f.text"
                 style="display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.12);border:1px solid rgba(255,255,255,0.18);border-radius:var(--r-xs);padding:9px 13px;font-size:0.9rem;">
              <EIcon :name="f.icon" :size="18" />{{ f.text }}
            </div>
          </div>
        </div>

        <!-- 可信指标（v3：静态数字，不再滚动；数值来自 meta.js，可复算） -->
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:24px;">
          <div v-for="s in stats" :key="s.key"
               style="text-align:center;background:rgba(255,255,255,0.12);border-radius:var(--r-xs);padding:9px 4px;">
            <div style="font-weight:800;font-size:1rem;">{{ s.value }}{{ s.suffix || '' }}</div>
            <div style="font-size:0.78rem;opacity:0.9;margin-top:1px;">{{ s.label }}</div>
          </div>
        </div>
      </div>

      <!-- 右：登录面板 -->
      <div style="flex:1 1 340px;min-width:300px;padding:40px 34px;display:flex;flex-direction:column;justify-content:center;background:var(--card-bg);">
        <div style="margin-bottom:20px;">
          <div style="font-size:1.28rem;font-weight:800;">欢迎回来</div>
          <div style="color:var(--muted);font-size:0.88rem;margin-top:3px;">登录，或选一个角色快速体验</div>
        </div>

        <n-form @submit.prevent="doLogin">
          <n-form-item label="用户名">
            <n-input v-model:value="username" placeholder="如 demo_grid" size="large" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="password" type="password" placeholder="demo_grid / demo123" size="large"
                     show-password-on="click" />
          </n-form-item>
          <n-button type="primary" block size="large" :loading="loading" attr-type="submit"
                    style="font-weight:700;height:48px;letter-spacing:0.06em;">登 录</n-button>
        </n-form>

        <n-divider style="font-size:0.8rem;">或选择角色快速体验</n-divider>

        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
          <div v-for="r in roles" :key="r.role"
               class="entry-tile"
               :style="loading ? 'opacity:.6;pointer-events:none' : ''"
               style="border:1px solid var(--border);border-radius:var(--r-card);padding:13px 8px;text-align:center;background:var(--card-bg);"
               @click="demo(r.role)">
            <div class="entry-icon" style="display:flex;justify-content:center;"><EIcon :name="r.icon" :size="30" /></div>
            <div style="font-weight:700;margin-top:3px;">{{ r.label }}</div>
            <div style="font-size:0.78rem;color:var(--muted);margin-top:3px;">{{ r.desc }}</div>
          </div>
        </div>

        <div style="text-align:center;color:var(--muted);font-size:0.78rem;margin-top:18px;">
          居民 / 老人演示免密 · 网格员 demo123
        </div>
      </div>
    </div>
  </div>
</template>
