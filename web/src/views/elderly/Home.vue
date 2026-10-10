<script setup>
// 老年端首页：大字天气(可播放) + 今日提醒 + 通知/用药摘要 + 长按紧急求助 + 拨打 120 + 小助手入口
//
// v3 复核 B4（导航收敛）：首页原来又摆了一套"天气/通知/报修/联系社区/用药/健康"入口，
// 和顶部导航重复 —— 老人"每个都在、等于每个都找不到"。现在首页只保留**首页特有**的内容
// （问候/关怀/天气/今日提醒/紧急求助/120/小助手），高频入口统一由顶部导航承担，
// 其余能力收进「更多服务」。**功能一个没少，只是入口不再重复。**
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { useUserStore } from '../../stores/user'
import { elderly, notices } from '../../api'
import { useSpeech, speechCapability } from '../../composables/useSpeech'
import { useSos } from '../../composables/useSos'
import EIcon from '../../components/EIcon.vue'
import { weatherIcon } from '../../utils/weatherIcon'

const router = useRouter()
const store = useUserStore()
const message = useMessage()
const { speak } = useSpeech()

const home = ref(null)
const vol = ref(1.0)
const rate = ref(0.9) // M1 语速（老人档慢一点）
const volLabels = { 低: 0.5, 中: 1.0, 高: 1.5 }
const greetText = ref('')
const careLine = ref('')
const urgentNotice = ref(null)
// 联系家属确认
const callConfirm = ref(false)
let callTimer = null
const callContact = ref(null)
const contacts = ref([])
// 降级硬化（B4）：语音是增强项，不是唯一路径
const cap = speechCapability()
const ttsOk = ref(cap.hasTTS)
const welcomeText = ref('')        // 首屏要念的话（改由"点一下听"触发）
const urgentText = ref('')         // 紧急通知要念的话

const loadError = ref(false)   // 注意：取数失败**不能**画成"您最近没有在办的事"

/** 首页数据加载：四个请求**并行**（原来串行，最长 20s×4 都停在白屏），
 *  失败必须让老人看见（假空态会让老人以为自己没报过事，也不再重试）。 */
async function loadHome() {
  loadError.value = false
  const [h, c, o, n] = await Promise.allSettled([
    elderly.home(), elderly.contacts(), elderly.orders(), notices.list(),
  ])
  if (h.status === 'fulfilled') {
    home.value = h.value
    // M1：时段问候 + 今日一句关怀 + 语速
    rate.value = home.value?.speech_rate || 0.9
    greetText.value = home.value?.greeting ? `${home.value.greeting}，${home.value.name || '您好'}` : ''
    careLine.value = home.value?.care_line || ''
    // 降级硬化（B4）：**不再挂载即播报**——iOS Safari 的 TTS 必须由用户手势触发，
    // 自动播会静默不响（老人以为坏了）。改成页面上一句大字 + 一个"点一下听"按钮。
    welcomeText.value = careLine.value
      ? (greetText.value ? `${greetText.value}。${careLine.value}` : careLine.value)
      : ''
  } else {
    loadError.value = true
  }
  if (c.status === 'fulfilled') contacts.value = c.value || []
  // 最近办理（只取最近一条）。**取不到就不许说"没有在办的事"** → 转成 loadError
  if (o.status === 'fulfilled') latest.value = (o.value || [])[0] || null
  else loadError.value = true
  // 紧急通知：仍然弹窗（必须让老人看见），但播报改为**用户点一下**（同上，自动播在 iOS 不响）
  if (n.status === 'fulfilled') {
    const urgent = (n.value || []).find((x) => x.is_urgent && !x.is_read)
    if (urgent) {
      urgentNotice.value = urgent
      urgentText.value = `紧急通知：${urgent.elderly_summary || urgent.title}`
    }
  }
  if (home.value?.due_medications > 0 && !careLine.value) {
    welcomeText.value = `今天有 ${home.value.due_medications} 次药要吃，我会到点提醒您。`
  }
  if (home.value?.weather?.alert_tags?.length && !careLine.value) {
    const tags = home.value.weather.alert_tags.map((a) => `${a.type}${a.level}`).join('、')
    welcomeText.value = `注意！当前有极端天气预警：${tags}，请尽量减少外出。`
  }
}

onMounted(loadHome)

/** 点一下听（用户手势触发，iOS 才会真的响）；播不出来就说明原因并保留大字。 */
async function playWelcome() {
  const ok = await speak(welcomeText.value || greetText.value, vol.value, rate.value)
  if (!ok) ttsOk.value = false
}

async function playUrgent() {
  const ok = await speak(urgentText.value, vol.value, rate.value)
  if (!ok) ttsOk.value = false
}

async function closeUrgent() {
  const n = urgentNotice.value
  urgentNotice.value = null
  if (n && !n.is_read) {
    try {
      await notices.action(n.id, { action: 'mark_read' })
    } catch { /* 忽略 */ }
  }
}

onBeforeUnmount(() => {
  if (callTimer) clearTimeout(callTimer)
})

// 首页三个主要动作（v3 重设计）：任务书 §四.1 要求首页第一层就是三件最常做的事。
// · 「反映问题」「看看进度」保持原位（原有功能与文字不变）；
// · 第三格原来是「更多服务」——而它**同时又是顶部导航的 6 个入口之一**（重复），
//   改成「问一问」（进社区小助手）：既消掉一处重复，又把"报事 / 查进度 / 问政策"三件事摆齐。
//   注意：顶部导航的「更多服务」大按钮**原样保留**，`mobile_flow_check` 依赖它，没有改动。
const quick = [
  { to: '/elderly/report', icon: 'speak', label: '反映问题' },
  { to: '/elderly/orders', icon: 'clipboard', label: '看看进度' },
  { to: '/elderly/agent', icon: 'chat-dots', label: '问一问' },
]

// 第三层的低频入口（不新增一级导航，只是首页上的入口分组）
const moreEntries = [
  { to: '/elderly/more', icon: 'toolbox', label: '更多服务' },
  { to: '/elderly/contacts', icon: 'family', label: '联系家人' },
  { to: '/elderly/health', icon: 'heart', label: '健康服务' },
]

// 最近办理的一件事（数据来自**既有的** /elderly/orders，不新增接口）：
// 首页要能回答"我那件事办到哪一步了、下一步谁做"，而不是让老人先跳一个页面去找。
const latest = ref(null)

function playWeather() {
  const wt = home.value?.weather
  if (!wt) return
  const tags = (wt.alert_tags || []).map((a) => `${a.type}${a.level}预警`).join('，')
  const txt = `这里是${wt.region_label || '您所在社区'}的天气。当前${wt.condition || ''}，气温${wt.temp_low || ''}度到${wt.temp_high || ''}度${tags ? '，' + tags : ''}。${wt.advice || ''}`
  speak(txt, vol.value, rate.value)
}

function voiceHelp() {
  speak('您好，这里是社区服务。最上面有首页、反映问题、看看进度、联系家人、今日提醒、更多服务；红色的紧急求助按钮长按三秒就能找社区。', vol.value, rate.value)
}

function callCommunity() {
  const phone = home.value?.community_phone || ''
  if (!phone) {
    message.warning('暂无社区电话，请联系网格员补充')
    return
  }
  // 诚实呼叫（§6-B2）：号码由**服务端**给出并留痕，页面只说"帮您打开拨号"，
  // 绝不说"正在呼叫"（网页根本不知道有没有拨出去、接通没有）
  try {
    elderly.contactCall({ community: true }).then((info) => {
      window.location.href = (info && info.tel) || `tel:${phone}`
      message.info('已帮您打开手机拨号，请在手机上按绿色按钮拨出')
      speak('已帮您打开手机拨号，请在手机上拨出', vol.value, rate.value)
      if (info && info.call_id) elderly.contactOutcome(info.call_id, 'dialer_opened').catch(() => {})
    }).catch((e) => message.error(e.message || '打开拨号失败'))
  } catch {
    window.location.href = `tel:${phone}`
  }
}

// ---- 紧急求助：长按 3 秒进入确认，10 秒超时自动取消 ----
// v3 复核 B4：逻辑抽到 `composables/useSos.js`，与顶部导航的红色求助键**共用同一套状态机**
const sos = useSos({ onMessage: message, speakOpts: () => [vol.value, rate.value] })
const sosConfirm = sos.sosConfirm
const sosCountdown = sos.sosCountdown
const pressStart = sos.pressStart
const pressCancel = sos.pressCancel
const confirmSos = sos.confirmSos

// ---- 联系家属/社区：确认 → 拨号留痕，10 秒超时 ----
async function callPerson(c) {
  callContact.value = c
  callConfirm.value = true
  if (callTimer) clearTimeout(callTimer)
  callTimer = setTimeout(() => {
    callConfirm.value = false
    message.info('10 秒未确认，拨打已取消')
  }, 10000)
}

async function confirmCall() {
  clearTimeout(callTimer)
  callConfirm.value = false
  const c = callContact.value
  if (!c) return
  try {
    // 只传 contact_id：姓名/号码由服务端解析（§6-I8）
    const info = await elderly.contactCall({ contact_id: c.id })
    const phone = (info && info.phone) || c.phone
    window.location.href = (info && info.tel) || `tel:${phone}`
    // 只承诺"已打开拨号盘"——接通与否网页无从得知（§6-B2）
    message.info(`已帮您打开手机拨号，请在手机上按绿色按钮拨给 ${info?.name || c.name}`)
    speak(`已帮您打开手机拨号，请拨给${info?.name || c.name}`, vol.value, rate.value)
    if (info && info.call_id) {
      elderly.contactOutcome(info.call_id, 'dialer_opened').catch(() => {})
    }
  } catch (e) {
    message.error(e.message || '打开拨号失败')
  }
}

function cancelCall() {
  clearTimeout(callTimer)
  callConfirm.value = false
}
</script>

<template>
  <div class="elderly-page">
    <!-- ═══════════ 第一层：我是谁 · 今天想办理什么 · 三个主要动作 ═══════════
         v3 重设计（任务书 §四.1）：进门第一眼是"能办什么"，不是"系统在干什么"。 -->
    <div class="elderly-title">{{ greetText || ('您好，' + (home?.name || '大爷/阿姨')) }}</div>
    <div style="font-size:1.3rem;color:var(--muted);margin-bottom:14px;">
      今天想办理什么？说一声、点一下都行。
    </div>

    <!-- 语音不可用时的降级说明（审计靠 data-speech-fallback 验证"关掉语音仍可用"） -->
    <div v-if="!ttsOk" data-speech-fallback
         class="card panel-warm" style="border-radius:var(--r-card);font-size:1.3rem;margin-bottom:12px;">
      <EIcon name="speaker-off" :size="18" /> 这台手机不能自动念出来，页面上的字都放大了，点按钮一样能办事
    </div>

    <!-- 三个主要动作（反映问题 / 看看进度 / 问一问）
         data-quick-actions：给基线脚本一个**精确锚点**——页面上还有另外两处三列栅格
         （第三层入口、联系家人），按 `.elderly-grid-3` 数会把它们一起数进来，
         "快捷动作 3 个不变"就变成了假数字（实测：重设计后那样数出来是 7 个）。 -->
    <div class="elderly-grid-3" data-quick-actions style="margin-bottom:8px;">
      <n-button v-for="q in quick" :key="q.to" size="large" type="primary" ghost class="elderly-btn"
                @click="router.push(q.to)">
        <EIcon :name="q.icon" :size="30" />{{ q.label }}
      </n-button>
    </div>
    <div class="muted" style="font-size:1.25rem;margin-bottom:16px;">
      说一句就能报事 · 进度随时能查 · 不懂的政策可以问一问
    </div>

    <!-- ═══════════ 第二层：今天要留意的事 · 最近办理 · 下一步 ═══════════ -->
    <!-- 今日提醒：关怀 / 用药 / 天气预警 合并成一块（原来东一句西一句，老人要自己找） -->
    <div v-if="careLine || (home?.due_medications > 0)" class="card panel-warm" style="border-radius:var(--r-card);">
      <div style="font-weight:700;font-size:1.3rem;margin-bottom:6px;"><EIcon name="bell" :size="18" /> 今天要留意</div>
      <div v-if="careLine" style="font-size:1.3rem;"><EIcon name="heart" :size="18" /> {{ careLine }}</div>
      <div v-if="home?.due_medications > 0" style="font-size:1.3rem;margin-top:4px;">
        <EIcon name="pill" :size="18" /> 今天有 {{ home.due_medications }} 次药要吃
        <n-button size="large" type="primary" ghost style="margin-left:8px;min-height:56px;font-size:1.25rem;"
                  @click="router.push('/elderly/medication')">去看看</n-button>
      </div>
    </div>

    <!-- 最近办理：一件事办到哪一步、下一步谁做（老人最想先知道的） -->
    <div class="card" style="border-radius:var(--r-card);">
      <div class="section-title" style="margin-top:0;">最近办理</div>
      <template v-if="latest">
        <div style="font-size:1.3rem;font-weight:700;">
          {{ latest.title }}
          <span v-if="latest.issue_code" class="muted" style="font-weight:400;">（编号 {{ latest.issue_code }}）</span>
        </div>
        <div style="font-size:1.25rem;margin-top:6px;color:var(--ink-info);font-weight:700;">
          {{ latest.progress?.now_line || latest.status }}
        </div>
        <div style="font-size:1.25rem;margin-top:4px;">
          <EIcon name="arrowRight" :size="18" /> {{ latest.progress?.next_line }}
        </div>
        <div class="muted" style="font-size:1.25rem;margin-top:4px;">
          <EIcon name="user" :size="18" /> 这一步由：{{ latest.progress?.who }}
        </div>
        <n-button block size="large" style="margin-top:10px;min-height:64px;font-size:1.25rem;"
                  @click="router.push('/elderly/orders')">
          <EIcon name="clipboard" :size="22" /> 看看完整进度
        </n-button>
      </template>
      <template v-else-if="loadError">
        <div style="font-size:1.25rem;color:var(--ink-danger);">暂时没连上社区服务，没法确认您的事办到哪了。</div>
        <div class="muted" style="font-size:1.25rem;margin-top:4px;">不是"没有在办的事"——请稍等一下再点重试。</div>
        <n-button block size="large" style="margin-top:10px;min-height:64px;font-size:1.25rem;"
                  @click="loadHome">
          <EIcon name="refresh" :size="22" /> 重新加载
        </n-button>
      </template>
      <template v-else>
        <div style="font-size:1.25rem;">您最近没有在办的事。</div>
        <div class="muted" style="font-size:1.25rem;margin-top:4px;">社区里有什么问题，点上面的「反映问题」说一声就行。</div>
      </template>
    </div>

    <!-- 未读通知 -->
    <div v-if="home?.unread_notices > 0" class="card entry-tile panel-mint"
         style="border-radius:var(--r-card);display:flex;align-items:center;justify-content:space-between;gap:10px;"
         @click="router.push('/elderly/notices')">
      <div style="font-size:1.25rem;"><EIcon name="bell" :size="18" /> {{ home.unread_notices }} 条新通知</div>
      <n-button size="large" type="success" style="font-size:1.25rem;min-height:56px;">去听 ›</n-button>
    </div>

    <!-- 最近求助状态 / 最近联系（有才显示，如实记录） -->
    <div v-if="home?.latest_sos" class="card panel-warm" style="border-radius:var(--r-card);font-size:1.25rem;">
      <EIcon name="siren" :size="18" /> 最近求助：{{ home.latest_sos.status || '处理中' }}
    </div>
    <div v-if="home?.latest_contact" class="muted" style="text-align:center;font-size:1.25rem;margin:6px 0;">
      最近联系：{{ home.latest_contact }}
    </div>

    <!-- ═══════════ 第三层：低频功能（天气 / 更多服务 / 联系家人 / 健康） ═══════════ -->
    <div class="section-title">更多</div>

    <!-- 大字天气（可播放；不外采定位，属地来自账号所属社区） -->
    <div v-if="home?.weather" class="card panel-sky" style="border-radius:var(--r-card);">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
        <div class="panel-hi" style="font-size:1.6rem;font-weight:800;">
          <span style="display:inline-flex;vertical-align:-0.2em;"><EIcon :name="weatherIcon(home.weather.condition, home.weather.emoji)" :size="38" weight="1.8" /></span>
          {{ home.weather.condition }} {{ home.weather.temp_low }}°~{{ home.weather.temp_high }}°
        </div>
        <n-button size="large" type="primary" ghost style="min-height:56px;font-size:1.25rem;" @click="playWeather">
          <EIcon name="speaker" :size="18" /> 听天气
        </n-button>
      </div>
      <div v-if="home.weather.alert_tags && home.weather.alert_tags.length" style="margin-top:6px;">
        <n-tag v-for="(a, i) in home.weather.alert_tags" :key="i" size="large" type="error" style="margin:0 4px;"><EIcon name="alert" :size="18" /> {{ a.type }}{{ a.level }}</n-tag>
      </div>
      <div v-if="home.weather.advice" class="muted" style="margin-top:8px;font-size:1.25rem;">{{ home.weather.advice }}</div>
      <!-- 属地（地区识别 WS7）：与居民端口径一致（都来自账号所属社区，不用定位权限）
           注意：字号必须 ≥20px（mobile_audit 对老年端卡 20px 下限） -->
      <div v-if="home.weather.region_label" class="muted" style="margin-top:6px;font-size:1.25rem;">
        <EIcon name="pin" :size="18" /> {{ home.weather.region_label }} · 更新于 {{ (home.weather.updated_at || '').slice(11, 16) || home.weather.updated_at }}
      </div>
    </div>

    <!-- 低频入口：更多服务 / 联系家人 / 健康服务（不新增一级导航） -->
    <div class="elderly-grid-3" style="margin:10px 0;">
      <n-button v-for="q in moreEntries" :key="q.to" size="large" class="elderly-btn"
                @click="router.push(q.to)">
        <EIcon :name="q.icon" :size="30" />{{ q.label }}
      </n-button>
    </div>

    <!-- 音量（语音按老人设置音量）与"点一下听" -->
    <div v-if="welcomeText && ttsOk" style="margin:6px 0 12px;">
      <n-button type="primary" block size="large" style="min-height:72px;font-size:1.35rem;border-radius:var(--r-card);"
                @click="playWelcome"><EIcon name="speaker" :size="18" /> 点一下听今天的提醒</n-button>
    </div>
    <!-- 不识字/看不清的老人也需要"这一页怎么用"：一次语音说明，放在这里而不是塞进第一屏 -->
    <n-button v-if="ttsOk" block size="large" style="margin:6px 0 12px;min-height:64px;font-size:1.25rem;border-radius:var(--r-card);"
              @click="voiceHelp"><EIcon name="speaker" :size="18" /> 听一遍这一页怎么用</n-button>
    <div style="display:flex;align-items:center;gap:10px;justify-content:center;margin-bottom:12px;flex-wrap:wrap;">
      <span style="font-size:1.25rem;"><EIcon name="speaker" :size="18" /> 音量：</span>
      <n-button-group size="large">
        <n-button v-for="(v, k) in volLabels" :key="k" :type="vol === v ? 'primary' : 'default'"
                  style="font-size:1.25rem;min-height:56px;min-width:76px;" @click="vol = v; speak('音量已设置', v, rate)">{{ k }}</n-button>
      </n-button-group>
    </div>

    <!-- ═══════════ 紧急（独立显示、深红克制：整页只有这一块是红的） ═══════════ -->
    <div style="margin-top:16px;">
      <n-button size="large" type="error" block class="elderly-btn" data-longpress
                style="min-height:92px;font-size:1.7rem;background:var(--danger-solid);border-color:var(--danger-solid);border-radius:var(--r-card);"
                @pointerdown="pressStart" @pointerup="pressCancel" @pointerleave="pressCancel"
                @touchstart.prevent="pressStart" @touchend="pressCancel">
        <EIcon name="siren" :size="18" /> 紧急求助（长按 3 秒）
      </n-button>
      <div class="muted" style="text-align:center;margin-top:6px;font-size:1.25rem;">按住 3 秒后确认呼叫</div>
    </div>

    <!-- 拨打 120 红色大按钮 -->
    <div style="margin-top:14px;">
      <n-button size="large" type="error" block class="elderly-btn"
                style="min-height:76px;font-size:1.45rem;background:var(--danger-solid);border-color:var(--danger-solid);border-radius:var(--r-card);"
                tag="a" href="tel:120"><EIcon name="siren" :size="18" /> 拨打 120（急救）</n-button>
    </div>
    <!-- 联系社区（走服务端给的号码，留痕；只说"打开拨号盘"，不替手机说"已接通"） -->
    <div style="margin-top:10px;">
      <n-button size="large" block class="elderly-btn" style="border-radius:var(--r-card);"
                @click="callCommunity"><EIcon name="phone" :size="18" /> 联系社区</n-button>
    </div>

    <!-- 联系家人（有紧急联系人时才显示） -->
    <div v-if="contacts.length" style="margin-top:10px;">
      <div class="section-title">联系家人</div>
      <div class="elderly-grid-3">
        <n-button v-for="c in contacts" :key="c.id" size="large" class="elderly-btn" @click="callPerson(c)">
          <EIcon name="family" :size="30" />{{ c.name }}
        </n-button>
      </div>
    </div>

    <!-- 紧急求助确认弹窗 -->
    <n-modal v-model:show="sosConfirm" preset="dialog" type="error" title="确认紧急求助？"
             positive-text="确认求助" negative-text="取消"
             @positive-click="confirmSos" @negative-click="sos.cancelConfirm">
      <template #default>
        <div style="text-align:center;font-size:1.3rem;">
          将通知社区负责人{{ sos.contactNames.value ? `，以及紧急联系人：${sos.contactNames.value}` : '' }}。
        </div>
        <div style="text-align:center;font-size:2.1rem;font-weight:800;color:var(--ink-danger);margin-top:8px;">{{ sosCountdown }} 秒后自动取消</div>
        <div class="muted" style="text-align:center;margin-top:8px;font-size:1.25rem;">
          手机不能自动连续拨号，需要时请点下面的「拨打 120」
        </div>
      </template>
    </n-modal>

    <!-- 联系家属确认弹窗 -->
    <n-modal v-model:show="callConfirm" preset="dialog" type="warning" title="确认拨打？"
             :content="callContact ? `将呼叫 ${callContact.name}（${callContact.phone}），10 秒内未确认将取消` : ''"
             positive-text="确认拨打" negative-text="取消"
             @positive-click="confirmCall" @negative-click="cancelCall" />

    <!-- 紧急通知主动弹窗（我知道了 + 点一下听；不再自动播报，iOS 需要用户手势） -->
    <n-modal :show="!!urgentNotice" @update:show="(v) => { if (!v) urgentNotice = null }" preset="dialog" type="error"
             :title="urgentNotice ? ('' + urgentNotice.title) : ''"
             :content="urgentNotice ? (urgentNotice.elderly_summary || urgentNotice.body) : ''"
             positive-text="我知道了" @positive-click="closeUrgent">
      <template #action>
        <n-button v-if="ttsOk" type="error" size="large" style="min-height:64px;font-size:1.3rem;"
                  @click="playUrgent"><EIcon name="speaker" :size="18" /> 点一下听</n-button>
        <n-button size="large" style="min-height:64px;font-size:1.3rem;" @click="closeUrgent">我知道了</n-button>
      </template>
    </n-modal>
  </div>
</template>
