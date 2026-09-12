<script setup>
// 登录页 v2（视觉系统最终版）：网格渐变背景 + 星光粒子 + 玻璃双栏 + 数字滚动 + 三端角色卡
// 业务逻辑与 v1 完全一致（staff 登录 / 演示免密 / 角色跳转），仅重做视觉层
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../stores/user'
import CountUp from '../components/CountUp.vue'

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
  { role: 'resident', icon: '🏠', label: '居民', desc: '报修 · 议事 · 问策' },
  { role: 'elderly', icon: '👴', label: '老年', desc: '大字 · 语音 · 免密' },
  { role: 'grid', icon: '🛠️', label: '网格员', desc: '工单 · 督办 · 决策' },
]

// 品牌指标（与仓库实测一致：555 测试 / 42 条检索评测 / hit@1 100% / AI 自转率 62%）
const stats = [
  { v: 555, s: '', lbl: '自动化测试' },
  { v: 42, s: '', lbl: '检索评测集' },
  { v: 100, s: '%', lbl: '命中率 hit@1' },
  { v: 62, s: '%', lbl: 'AI 自转率' },
]

// 星光粒子（固定参数，避免随机导致重渲染抖动）
const particles = [
  { l: '6%', d: '15s', delay: '0s', size: 3 }, { l: '14%', d: '18s', delay: '3s', size: 2 },
  { l: '23%', d: '13s', delay: '6s', size: 4 }, { l: '31%', d: '19s', delay: '1.5s', size: 2 },
  { l: '42%', d: '16s', delay: '8s', size: 3 }, { l: '51%', d: '14s', delay: '4.5s', size: 2 },
  { l: '60%', d: '17s', delay: '10s', size: 4 }, { l: '69%', d: '15s', delay: '2.5s', size: 2 },
  { l: '77%', d: '20s', delay: '7s', size: 3 }, { l: '85%', d: '13s', delay: '11s', size: 2 },
  { l: '92%', d: '18s', delay: '5s', size: 3 }, { l: '97%', d: '16s', delay: '9s', size: 2 },
]
</script>

<template>
  <div style="min-height:100vh;position:relative;display:flex;align-items:center;justify-content:center;padding:24px;overflow:hidden;">
    <!-- 渐变网格背景 + 漂浮光斑 + 星光粒子 -->
    <div class="mesh-bg">
      <div class="mesh-orb" style="width:360px;height:360px;background:#6A8DFF;top:-90px;left:-70px;"></div>
      <div class="mesh-orb" style="width:300px;height:300px;background:#14B8A6;bottom:-80px;right:-60px;animation-delay:2.5s;"></div>
      <div class="mesh-orb" style="width:240px;height:240px;background:#FF8C42;top:38%;right:10%;animation-delay:5s;"></div>
      <div class="mesh-particles">
        <i v-for="(p, i) in particles" :key="i"
           :style="{ left: p.l, width: p.size + 'px', height: p.size + 'px', animationDuration: p.d, animationDelay: p.delay }"></i>
      </div>
    </div>

    <!-- 玻璃双栏主卡 -->
    <div class="glass fade-up"
         style="position:relative;z-index:1;border-radius:24px;width:900px;max-width:100%;display:flex;flex-wrap:wrap;overflow:hidden;">
      <!-- 左：品牌面板 -->
      <div class="grad-flow" style="flex:1 1 390px;min-width:320px;background:var(--primary-gradient-2);color:#fff;padding:44px 36px;display:flex;flex-direction:column;justify-content:space-between;position:relative;overflow:hidden;">
        <div style="position:absolute;width:230px;height:230px;border-radius:50%;background:rgba(255,255,255,0.10);top:-80px;right:-80px;"></div>
        <div style="position:absolute;width:150px;height:150px;border-radius:50%;background:rgba(255,255,255,0.07);bottom:-40px;left:-40px;"></div>

        <div class="fade-up-d1" style="position:relative;">
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:24px;">
            <div class="tilt-hover" style="width:48px;height:48px;border-radius:14px;background:rgba(255,255,255,0.18);display:flex;align-items:center;justify-content:center;font-size:1.55rem;border:1px solid rgba(255,255,255,0.28);">🏘️</div>
            <div>
              <div style="font-size:1.55rem;font-weight:800;letter-spacing:0.02em;">社区先知</div>
              <div style="font-size:0.76rem;opacity:0.75;letter-spacing:0.06em;">CommunityInsight</div>
            </div>
          </div>

          <div style="font-size:1.04rem;line-height:1.8;opacity:0.94;">
            基层治理 · <b>多智能体协作平台</b><br/>
            知 · 报 · 议 · 督，让社区服务有温度
          </div>

          <div style="margin-top:22px;display:flex;flex-direction:column;gap:9px;">
            <div v-for="(f, i) in [
              ['🤝', '9 个智能体黑板协作 · 真协商'],
              ['🛡️', 'Verifier + Arbiter 双层防线'],
              ['👴', '适老语音 · 免登录 · 人文关怀'],
            ]" :key="i"
                 style="display:flex;align-items:center;gap:10px;background:rgba(255,255,255,0.10);border:1px solid rgba(255,255,255,0.16);border-radius:12px;padding:9px 13px;font-size:0.87rem;">
              <span style="font-size:1.1rem;">{{ f[0] }}</span>{{ f[1] }}
            </div>
          </div>
        </div>

        <!-- 可信指标（数字滚动） -->
        <div class="fade-up-d2" style="position:relative;display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:24px;">
          <div v-for="s in stats" :key="s.lbl"
               style="text-align:center;background:rgba(255,255,255,0.10);border-radius:10px;padding:9px 4px;">
            <div style="font-weight:800;font-size:0.98rem;">
              <CountUp :value="s.v" :suffix="s.s" :duration="1600" />
            </div>
            <div style="font-size:0.66rem;opacity:0.78;margin-top:1px;">{{ s.lbl }}</div>
          </div>
        </div>
      </div>

      <!-- 右：登录面板 -->
      <div class="fade-up-d3" style="flex:1 1 340px;min-width:300px;padding:44px 36px;display:flex;flex-direction:column;justify-content:center;background:var(--card-bg);">
        <div style="margin-bottom:20px;">
          <div style="font-size:1.28rem;font-weight:800;">欢迎回来</div>
          <div style="color:var(--muted);font-size:0.85rem;margin-top:3px;">登录，或选一个角色快速体验</div>
        </div>

        <n-form @submit.prevent="doLogin">
          <n-form-item label="用户名">
            <n-input v-model:value="username" placeholder="如 demo_grid" size="large" />
          </n-form-item>
          <n-form-item label="密码">
            <n-input v-model:value="password" type="password" placeholder="demo_grid / demo123" size="large"
                     show-password-on="click" />
          </n-form-item>
          <n-button class="btn-shimmer" type="primary" block size="large" :loading="loading" attr-type="submit"
                    style="font-weight:700;height:46px;letter-spacing:0.06em;">登 录</n-button>
        </n-form>

        <n-divider style="font-size:0.78rem;color:var(--disabled);">或选择角色快速体验</n-divider>

        <div class="wave" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;">
          <div v-for="r in roles" :key="r.role"
               class="entry-tile"
               :style="loading ? 'opacity:.6;pointer-events:none' : ''"
               style="border:1px solid var(--border);border-radius:14px;padding:13px 8px;text-align:center;background:var(--card-bg);"
               @click="demo(r.role)">
            <div class="entry-icon" style="font-size:1.65rem;">{{ r.icon }}</div>
            <div style="font-weight:700;margin-top:3px;">{{ r.label }}</div>
            <div style="font-size:0.68rem;color:var(--muted);margin-top:2px;">{{ r.desc }}</div>
          </div>
        </div>

        <div style="text-align:center;color:var(--disabled);font-size:0.73rem;margin-top:18px;">
          居民 / 老人演示免密 · 网格员 demo123
        </div>
      </div>
    </div>
  </div>
</template>
