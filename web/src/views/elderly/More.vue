<script setup>
// 老年端「更多服务」（v3 复核 B4：顶层导航收敛到 5 个高频入口 + 独立紧急求助，
// 其余能力收到这一页，**路由不删，只是展示入口收敛**）。
// 设计口径：一屏放得下、每个按钮都是"看得见的大字 + 大热区"，不用滚动也能点准。
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useSpeech } from '../../composables/useSpeech'
import { ref } from 'vue'
import EIcon from '../../components/EIcon.vue'

const router = useRouter()
const message = useMessage()
const { speak } = useSpeech()
const lastSpoken = ref('')
const ttsOk = ref(!!(typeof window !== 'undefined' && window.speechSynthesis))

const items = [
  { to: '/elderly/agent', icon: 'robot', label: '问一问（小助手）', desc: '按住说话，什么都能问' },
  { to: '/elderly/qa', icon: 'book', label: '问一问（政策）', desc: '医保、养老、住房怎么办' },
  { to: '/elderly/medication', icon: 'pill', label: '用药提醒', desc: '到点提醒吃药' },
  { to: '/elderly/health', icon: 'medical', label: '我的健康', desc: '记血压、看趋势' },
  { to: '/elderly/notices', icon: 'bell', label: '听通知', desc: '社区的通知念给您听' },
  { to: '/elderly/home', icon: 'home', label: '回到首页', desc: '紧急求助也在首页' },
]

/** 点一下念出说明（不自动播：iOS 需要用户手势，自动播会静默不响）。 */
async function say(text) {
  lastSpoken.value = text
  const ok = await speak(text, 1.0, 0.9)
  if (!ok) ttsOk.value = false
}

function open(it) {
  router.push(it.to)
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title"><EIcon name="toolbox" :size="18" /> 更多服务</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">点一下就进去，不着急慢慢看</p>

    <n-button v-if="ttsOk" block size="large" style="margin-bottom:12px;min-height:60px;font-size:1.25rem;"
              @click="say('这里是更多服务。有小助手、政策问答、用药提醒、我的健康、听通知。要紧急求助请按最上面的红色按钮。')">
      <EIcon name="speaker" :size="18" /> 听一遍这一页有哪些
    </n-button>
    <div v-else class="card muted" style="font-size:1.25rem;">
      <EIcon name="speaker-off" :size="18" /> 这台手机的语音念不出来，请看屏幕上的大字（内容是一样的）
    </div>

    <div class="elderly-grid-2" style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <n-button v-for="it in items" :key="it.to" size="large" type="primary" ghost class="elderly-btn"
                style="min-height:132px;flex-direction:column;gap:6px;font-size:1.25rem;"
                @click="open(it)">
        <EIcon :name="it.icon" :size="34" />
        <b>{{ it.label }}</b>
        <!-- 注意：老年端叶子文本一律 ≥20px（`mobile_audit` 卡这个下限），1.05rem 会被判不合格 -->
        <span class="muted" style="font-size:1.25rem;">{{ it.desc }}</span>
      </n-button>
    </div>

    <n-button size="large" block style="margin-top:14px;min-height:64px;font-size:1.25rem;"
              @click="router.push('/elderly/home')"><EIcon name="home" :size="18" /> 返回首页</n-button>
  </div>
</template>
