<script setup>
// 老年端一句话报修（v3 卡1 契约）：说话/打字 → **结构化摘要**（缺什么问什么）→ 老人确认 → 提交。
//
// 为什么不是"说完直接提交"：
//   · 原实现位置提取失败就把 location 回落成"社区"直接建单 —— 库里真的留下了 `location='社区'`
//     的**无法派单工单**（老人以为报了，其实没人能去修）；
//   · 也不能让老人确认"一串转写文本"就算确认了办理信息 —— 位置/责任范围（家里还是公共区域）
//     必须老人看得见、答得上。
// 所以：先出摘要 + 缺失项 + 一句能听懂的追问；齐了才出现「确认上报」。
//
// 降级硬化（B4）：语音只是增强项——不支持/没权限/连不上时明确告诉老人"打字就行"。
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'
import { useSpeech, speechCapability, reasonText } from '../../composables/useSpeech'
import EIcon from '../../components/EIcon.vue'
import { newToken } from '../../utils/idemToken'

const router = useRouter()
const message = useMessage()
const { recognize, speak, stopListening, stopSpeaking } = useSpeech()

// 未提交草稿由服务端按用户保存；浏览器不再保存原话、位置等正文。
// 共享设备换人时，接口按当前会话 uid 查询，避免 localStorage/sessionStorage 被篡改后越权展示。
const resumeOffer = ref(null)     // 待恢复的草稿摘要（有值才显示恢复卡）
const speaking = ref(false)       // 正在播报（用于显示「别念了」）

async function saveDraft() {
  const t = (text.value || '').trim()
  if (!t) return
  try {
    await elderly.saveReportDraft({ text: t, answer_location: answer.value.location || '',
      answer_scope: answer.value.scope || '', answer_urgency: answer.value.urgency || '一般' })
  } catch { /* 草稿保存失败不阻断当前办理 */ }
}

async function clearDraft() {
  try { await elderly.clearReportDraft() } catch { /* 草稿已提交时清除失败不阻断 */ }
}

/** 页面打开时由服务端按当前登录身份取自己的草稿。 */
async function loadSavedDraft() {
  try {
    const d = await elderly.reportDraftCurrent()
    if (d && d.text) resumeOffer.value = d
  } catch { /* 未登录或服务暂不可用时不显示旧草稿 */ }
}

/** 老人选「接着填」：把原话与已确认字段放回去，再**从服务端重算一遍摘要**（不拿旧结论当事实）。 */
async function resumeDraft() {
  const d = resumeOffer.value
  resumeOffer.value = null
  if (!d) return
  text.value = d.text || ''
  answer.value = { location: '', scope: '', urgency: '一般', ...(d.answer || {}) }
  await loadDraft(true)
}

/** 老人选「重新开始」：把本会话的草稿丢掉（明确的选择，不是悄悄清掉）。 */
function dropLocalDraft() {
  resumeOffer.value = null
  void clearDraft()
  message.info('好，那就重新说')
}

onMounted(() => {
  loadSavedDraft()
})

// 预置短语（v3 §7.1：**语音不是唯一入口**）——
// 说不出来 / 听不清 / 麦克风不能用时，点一个最接近的说法就能走到同一套办理流程。
// 为什么不做成"选完直接提交"：那等于替老人把位置/责任范围拍板了，所以只**填进输入框**，
// 老人还要看一眼摘要才提交（与打字、语音完全同一条路径）。
const PHRASES = [
  '楼道的灯不亮了',
  '家里水管漏水了',
  '电梯坏了，不动了',
  '楼下垃圾没人清',
]

const text = ref('')
const listening = ref(false)
const submitting = ref(false)
const loadingDraft = ref(false)
const draft = ref(null)          // 结构化摘要（服务端返回）
const submitted = ref(null)      // 提交成功后的四段值
const resultVia = ref('')        // 'submit'=提交时直接拿到结果 / 'verify'=网络没回话后**核对**到的
const unknownToken = ref('')     // 提交结果未知时的幂等编号（§6-I5：不诱导老人重复点提交）
// 老人补充/确认的字段（预填系统的建议，老人可改）
const answer = ref({ location: '', scope: '', urgency: '一般' })

const cap = speechCapability()
const asrBlocked = ref(!cap.hasASR || !cap.secure)
const blockReason = ref(cap.asrReason || '')
// 常见说法面板：语音不可用、或者老人"说不出来"时自动推到眼前（也可以自己点开）
const showPhrases = ref(!cap.hasASR || !cap.secure)
const banner = computed(() => reasonText(blockReason.value || 'unsupported'))
// 播报是否真的响过：iOS Safari 的 TTS 必须由**用户手势**触发，挂载即播会静默不响，
// 所以本页**不自动播报**，只提供"听一遍"，并且播不出来时如实说明（不假装老人听到了）
const ttsOk = ref(cap.hasTTS)
const lastSpoken = ref('')

// 字段来源的五种中文说法（v52 落库的白名单值，与 `data/db_repair.ALLOWED_FIELD_SOURCES` 对应）。
// 注意：不许笼统写"系统记录"：「您自己说的」和「我们按登记资料替您填的」可信度完全不同，
// 含糊写就等于把最该讲清的那句糊掉了（这是本页最要紧的一句口径）。
const SOURCE_LABEL = {
  text: '来自您说的话',
  user: '您确认的',
  profile: '来自您的登记资料',
  suggestion: '系统建议（您已确认）',
  default: '默认值',
  form: '表单直接填写',
  agent: '代办人填写',
  none: '暂缺',
}
const srcTip = (k) => SOURCE_LABEL[k] || ''
/** 确认卡片用：来源 + 一句"这是谁说的"，缺失时如实写"暂缺"。
 *  字段名有两套口径（契约里"责任范围"叫 issue_type，落库/展示叫 scope）→ 两套都认，
 *  否则会出现"其实有来源、却显示暂缺"的假缺失。 */
const srcLine = (o, k) => {
  const s = (o && o.sources) || {}
  const v = s[k] || (k === 'scope' ? s.issue_type : '') || (k === 'title' ? s.description : '') || ''
  return v ? `（${SOURCE_LABEL[v] || v}）` : '（暂缺）'
}

/** 统一播报入口：返回是否真的响了；失败就把 降级成"请看大字"的说明。 */
async function say(text) {
  const t = (text || '').trim()
  if (!t) return false
  lastSpoken.value = t
  speaking.value = true
  let ok = false
  try {
    ok = await speak(t, 1.0, 0.9)
  } finally {
    speaking.value = false
  }
  if (!ok && ttsOk.value) ttsOk.value = false
  return ok
}

/** 老人按「别念了」：立刻停下播报（v3 §7.3：允许重听、暂停与停止）。 */
function hush() {
  stopSpeaking()
  speaking.value = false
}

async function startListen() {
  if (asrBlocked.value) return                      // 已知不可用：直接给打字路径，不空转
  listening.value = true
  const r = await recognize()
  listening.value = false
  if (r.ok && r.text) {
    text.value = r.text
    // 识别结果**显示**在页面上即可，播报交给"听一遍"（挂载/自动播在 iOS 不响）
    await say(`您说的是：${r.text}。请确认下面的信息`)
    await loadDraft()
    return
  }
  const reason = r.reason || 'empty'
  // 老人自己按的「停下」：不是故障，**不标记语音不可用**、也不覆盖他已经打进去的字
  if (reason === 'cancelled') {
    message.info(reasonText('cancelled'))
    return
  }
  // 按真实原因分派文案：不支持/没权限/网络 → 引导打字；空识别 → 请再说一次
  if (reason !== 'empty' && reason !== 'done') {
    asrBlocked.value = true
    blockReason.value = reason
  }
  message.warning(reasonText(reason))
  // 说不出来的老人别卡在这里：把「常见说法」推到他眼前（v3 §7.1 的替代途径）
  showPhrases.value = true
}

/** 老人按了「停下」：立刻结束这次聆听（不让他被 60 秒倒计时拖着）。 */
function haltListen() {
  stopListening()
}

/** 点一个常见说法：填进输入框，再走与打字/语音完全相同的"看看还缺什么"。 */
async function usePhrase(p) {
  text.value = p
  draft.value = null
  submitted.value = null
  await loadDraft()
}

/** 先不提交了：不建单、也不假装存了草稿，直接回首页（本会话里的临时草稿一并清掉）。 */
function giveUp() {
  restart()
  text.value = ''
  void clearDraft()
  message.info('好，这次没有提交，也没有建工单')
  router.push('/elderly/home')
}

/** 说错了/不是这个位置 → 明确入口：清空重来（v3 §7.2 纠错是一等功能）。 */
function restart() {
  draft.value = null
  submitted.value = null
  resultVia.value = ''
  unknownToken.value = ''
  answer.value = { location: '', scope: '', urgency: '一般' }
  void clearDraft()
  if (listening.value) stopListening()
  listening.value = false
}

/** 让服务端把原话解析成结构化摘要（缺什么会明说，且**此时不会建单**）。
 *
 * `withAnswer=true`（"补充好了，再看一遍"）：把老人在追问里填的补充值一起送上去重算。
 * 这里踩过一次真坑：补充值原来只存在页面上、重查时不送上行，而后端只按原话解析，
 * 于是"缺位置 → 补 → 再看"永远是同一个缺失结论，**「确认上报」根本不出现**（两步契约成死路）。
 * 首批八条浏览器旅程第 2 条（缺位置→追问→更正→确认提交）就是为抓这类问题立的。
 */
async function loadDraft(withAnswer = false) {
  if (text.value.trim().length < 5) return message.warning('请描述问题，至少 5 个字')
  draft.value = null
  submitted.value = null
  resultVia.value = ''
  loadingDraft.value = true
  try {
    const d = await elderly.reportDraft(text.value, withAnswer ? {
      answer_location: answer.value.location,
      answer_scope: answer.value.scope,
      answer_urgency: answer.value.urgency,
    } : {})
    draft.value = d
    answer.value = {
      location: d.fields.location || d.suggestion.location || '',
      scope: d.fields.issue_type || '',
      urgency: d.fields.urgency || '一般',
    }
    // 先松开"正在识别"再播报：播报是增强项，**不能拖住按钮**。
    // （实测踩到：某些机型 speak() 既不回 onend 也不回 onerror，按钮会一直转圈，
    //  老人既看不到结果也点不了第二次——现在 speak() 有兜底超时，这里再把顺序摆正。）
    loadingDraft.value = false
    await saveDraft()         // 正文保存到服务端，按当前用户恢复
    if (d.need_more) {
      // 补充值被判"不够用"时，先说明为什么（否则老人不知道要改成什么样）
      if (d.reject_hint) message.warning(d.reject_hint)
      await say(d.ask)
      message.info(d.ask)
    } else {
      await say('信息我记好了，请确认后上报')
    }
    if (d.phone_hint) message.warning(d.phone_hint)
  } catch (e) {
    message.error(e.message || '没能识别，请再试一次')
  } finally {
    loadingDraft.value = false
  }
}

/** 老人补充完信息后重新解析（不建单）：**带上补充值**，直到没有缺失项。 */
async function recheck() {
  await loadDraft(true)
}

async function submit() {
  if (!draft.value) return
  submitting.value = true
  // 同一个草稿只在第一次生成 token，重试沿用（否则重试会变成"新的一次提交"）；
  // 生成逻辑统一在 `utils/idemToken.js`（三处调用方共用一份，格式不一致会**静默不幂等**）
  if (!unknownToken.value) unknownToken.value = newToken()
  const token = unknownToken.value
  try {
    const d = await elderly.reportSubmit({
      text: text.value,
      location: answer.value.location || '',
      scope: answer.value.scope || '',
      urgency: answer.value.urgency || '',
      client_token: token,
    })
    submitted.value = d
    resultVia.value = 'submit'
    unknownToken.value = ''
    submitting.value = false      // 同上：结果已经拿到，播报不该让按钮继续转圈
    if (d.issue_id > 0) {
      message.success(`已上报，工单号 ${d.issue_id}（待审核）`)
      await say(`已经帮您报上去了，工单号 ${d.issue_id}，请等负责人联系您`)
    } else {
      // 例：安全隐患只记提醒不建单 —— 如实告诉老人，不假装建了工单
      message.success('已记录为安全提醒，负责人会看到')
      await say('已经记录下来，负责人会看到')
    }
    draft.value = null
    text.value = ''
    await clearDraft()             // 已经建单了：服务端草稿失效
  } catch (e) {
    // 断网/超时时**不能**说"提交失败"就完事 —— 可能其实已经提交成功了。
    // 如实告诉老人"结果还不确定"，并给一个"查一下"的出口，**不诱导他再点一次**（§6-I5）。
    const msg = String((e && e.message) || '')
    if (/提交中/.test(msg)) {
      // 并发提交（老人连点/网络重试）：服务端说"正有人在做这件事"，等它做完再核对，
      // **绝不在这里再发一次提交**（那才会真的建出第二张单）
      message.info(msg)
      await say('这条报修正在提交中，我帮您等一下再核对')
      await new Promise((r) => setTimeout(r, 2000))
      await checkSubmitted()
      return
    }
    const maybe = /超时|timeout|Network|Failed to fetch|网络/i.test(msg)
    if (maybe) {
      message.warning('网络没回话，我先帮您核对一下是否已经报上去了')
      await say('网络没有回话，我帮您核对一下是不是已经报上去了')
      await checkSubmitted()
    } else {
      message.error(msg || '上报失败，请稍后再试')
    }
  } finally {
    submitting.value = false
  }
}

/** 按幂等编号查真实结果：已经报上了就报工单号，没报上就明说可以重试。 */
async function checkSubmitted() {
  if (!unknownToken.value) return
  try {
    const s = await elderly.reportStatus(unknownToken.value)
    if (s && s.submitted && s.issue_id > 0) {
      submitted.value = s
      // 诚实标注结果的**来路**：这一条不是提交时拿到的，而是网络断了以后按提交编号核对出来的。
      // 不标的话，老人（和评审）无法区分"服务端回了成功"与"我们去问过服务端"。
      resultVia.value = 'verify'
      unknownToken.value = ''
      draft.value = null
      text.value = ''
      await clearDraft()
      message.success(`核对到了：已经提交成功，工单号 ${s.issue_id}`)
      await say(`核对到了，已经提交成功，工单号 ${s.issue_id}`)
    } else if (s && s.in_flight) {
      // 另一个请求正在建单：**不能说"没成功、可以再点一次"**（那一下就会建出第二张单）
      message.info('这次提交还在处理中，请等几秒再点一次核对')
      await say('这条报修还在处理中，请等几秒再点一次查一下')
    } else {
      message.info('核对结果：这次没有提交成功，可以再点一次「确认上报」')
      await say('核对过了，这次没有提交成功，可以再点一次确认上报')
    }
  } catch (e) {
    message.warning(e.message || '暂时查不到，请稍后再点「查一下是否已提交」')
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title"><EIcon name="speak" :size="18" /> 反映问题（一句话就行）</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">说一句或打几个字，我帮您整理成工单</p>

    <!-- 页面提示也做成"点一下听"（不在挂载时自动播：iOS 需要用户手势，否则静默不响） -->
    <n-button v-if="ttsOk && !lastSpoken" block size="large"
              style="margin-bottom:10px;min-height:60px;font-size:1.2rem;"
              @click="say('说一句或打几个字，我帮您整理成工单。位置要说清楚是哪个楼、哪一层。')">
      <EIcon name="speaker" :size="18" /> 听一遍怎么用
    </n-button>
    <div v-else-if="!ttsOk" class="card muted" style="font-size:1.1rem;">
      <EIcon name="speaker-off" :size="18" /> 这台手机的语音播不出来，请看屏幕上的大字（内容是一样的）
    </div>

    <!-- 降级提示条：语音不可用时明说"打字就行"（审计靠 data-speech-fallback 做机器验证） -->
    <div v-if="asrBlocked" data-speech-fallback
         class="card panel-warm" style="border-radius:14px;font-size:1.3rem;">
      <EIcon name="speaker-off" :size="18" /> {{ banner }}
    </div>

    <!-- 上次没填完的报修（v3 §7.4 中断可恢复）：**先给摘要再让老人选**，
         不替他决定继续还是新建；换人/换社区时这张卡根本不会出现（见 loadLocalDraft）。 -->
    <div v-if="resumeOffer" class="card panel-lemon" data-resume-draft
         style="border-radius:14px;font-size:1.25rem;">
      <b><EIcon name="edit" :size="18" /> 上次有一条没填完的报修</b>
      <div style="margin-top:6px;">{{ resumeOffer.summary }}</div>
      <div style="display:flex;gap:8px;margin-top:10px;">
        <n-button type="primary" size="large" style="flex:1;min-height:60px;font-size:1.2rem;"
                  @click="resumeDraft"><EIcon name="arrowRight" :size="18" />  接着填</n-button>
        <n-button size="large" style="flex:1;min-height:60px;font-size:1.2rem;"
                  @click="dropLocalDraft"><EIcon name="trash" :size="18" /> 重新开始</n-button>
      </div>
    </div>

    <div class="card" style="font-size:1.3rem;">
      <n-button v-if="!asrBlocked" type="error" block size="large"
                style="min-height:72px;font-size:1.4rem;" :loading="listening" @click="startListen">
        <EIcon name="mic" :size="18" /> {{ listening ? '正在聆听…（最多 60 秒）' : '点一下开始说话' }}
      </n-button>
      <!-- 「允许停止和取消」（v3 §7.1）：点了开始就必须能自己停下，别被倒计时拖着 -->
      <n-button v-if="listening" block size="large" data-speech-stop
                style="min-height:64px;font-size:1.3rem;margin-top:10px;" @click="haltListen">
        <EIcon name="stop" :size="18" /> 停下（我说完了 / 不想说了）
      </n-button>
      <div v-else style="font-size:1.3rem;font-weight:700;">
        <EIcon name="edit" :size="18" /> 请在下面的框里打字告诉我们（最少 5 个字）
      </div>

      <n-input v-model:value="text" type="textarea" :rows="3" placeholder="比如：五号楼二层楼道灯坏了"
               style="font-size:1.3rem;margin-top:12px;" />

      <!-- 预置短语（v3 §7.1）：语音不是唯一入口，说不出来也能办成同一件事 -->
      <div style="margin-top:12px;">
        <n-button block size="large" quaternary style="min-height:52px;font-size:1.15rem;"
                  @click="showPhrases = !showPhrases">
          <EIcon name="chat-dots" :size="18" /> {{ showPhrases ? '收起常见说法' : '说不出来？点一个常见说法' }}
        </n-button>
        <div v-if="showPhrases" data-phrases
             style="display:grid;grid-template-columns:1fr;gap:8px;margin-top:8px;">
          <n-button v-for="p in PHRASES" :key="p" block size="large"
                    style="min-height:60px;font-size:1.25rem;" @click="usePhrase(p)">
            <EIcon name="speak" :size="18" /> {{ p }}
          </n-button>
        </div>
      </div>

      <!-- 播报一律"点一下听"（v3 复核 B3）：挂载自动播在 iOS 静默不响，不能假装老人听到了 -->
      <n-button v-if="lastSpoken && ttsOk" block size="large"
                style="margin-top:10px;min-height:60px;font-size:1.25rem;" @click="say(lastSpoken)">
        <EIcon name="speaker" :size="18" /> 听一遍
      </n-button>
      <!-- v3 §7.3：允许重听、暂停与停止 —— 念到一半不想听了要能停（不能只能等它念完） -->
      <n-button v-if="speaking" block size="large" data-hush
                style="margin-top:8px;min-height:56px;font-size:1.2rem;" @click="hush">
        <EIcon name="stop" :size="18" /> 别念了
      </n-button>
      <div v-else-if="lastSpoken && !ttsOk" class="muted" style="margin-top:8px;font-size:1.1rem;">
        <EIcon name="speaker-off" :size="18" /> 这台手机的语音播不出来，请看屏幕上的大字（内容是一样的）
      </div>

      <n-button type="primary" block size="large" style="margin-top:12px;min-height:60px;font-size:1.25rem;"
                :loading="loadingDraft" @click="loadDraft">
        <EIcon name="search" :size="18" /> 帮我看看还缺什么
      </n-button>
    </div>

    <!-- 结构化摘要：老人核对的就是**办理信息**，不是一串转写文本 -->
    <div v-if="draft" class="card" style="font-size:1.25rem;">
      <b><EIcon name="clipboard" :size="18" /> 请您核对这几项</b>
      <div style="margin-top:8px;"><EIcon name="speak" :size="18" /> 您说的：{{ draft.original_text }}</div>
      <div style="margin-top:6px;"><EIcon name="wrench" :size="18" /> 问题：{{ draft.fields.title }}</div>
      <div style="margin-top:6px;">
        <EIcon name="pin" :size="18" /> 位置：
        <b v-if="draft.fields.location">{{ draft.fields.location }}</b>
        <span v-else style="color:var(--danger,#c00);">还缺，请在下面补充</span>
        <span class="muted" style="font-size:1rem;">（{{ srcTip(draft.sources.location) }}）</span>
      </div>
      <div style="margin-top:6px;">
        <EIcon name="home" :size="18" /> 责任范围：
        <b v-if="draft.fields.issue_type === '室内'">您家里（自己家的事）</b>
        <b v-else-if="draft.fields.issue_type === '室外'">公共地方（楼道/电梯等）</b>
        <span v-else style="color:var(--danger,#c00);">还没定，请选一下</span>
      </div>
      <div style="margin-top:6px;"><EIcon name="clock" :size="18" />  紧急程度：{{ draft.fields.urgency }}</div>

      <!-- 缺失项：就地追问（缺什么问什么，缺着就不给提交） -->
      <div v-if="draft.need_more" class="panel-warm" style="margin-top:12px;border-radius:10px;padding:10px;">
        <b><EIcon name="question" :size="18" /> {{ draft.ask }}</b>
        <!-- 补充值不够用时说明原因（不能默默不理会老人答的话） -->
        <div v-if="draft.reject_hint" data-reject-hint
             style="color:var(--danger,#c00);font-weight:700;margin-top:6px;font-size:1.15rem;">
          <EIcon name="alert" :size="18" /> {{ draft.reject_hint }}
        </div>
        <!-- 系统已经能猜出位置时，给一个"就是它"的大按钮：老人点一下就行，不用打字 -->
        <n-button v-if="draft.suggestion.location" type="primary" block size="large"
                  style="margin-top:8px;min-height:64px;font-size:1.25rem;"
                  @click="answer.location = draft.suggestion.location; recheck()">
          <EIcon name="checkCircle" :size="18" /> 就是这里：{{ draft.suggestion.location }}
        </n-button>
        <n-input v-model:value="answer.location" placeholder="或者告诉我别的：比如 5号楼二层楼道"
                 size="large" style="font-size:1.2rem;margin-top:8px;" />
        <div style="display:flex;gap:8px;margin-top:8px;">
          <n-button size="large" style="flex:1;min-height:56px;font-size:1.2rem;"
                    :type="answer.scope === '室内' ? 'primary' : 'default'"
                    @click="answer.scope = '室内'"><EIcon name="home" :size="18" /> 是我家里</n-button>
          <n-button size="large" style="flex:1;min-height:56px;font-size:1.2rem;"
                    :type="answer.scope === '室外' ? 'primary' : 'default'"
                    @click="answer.scope = '室外'"><EIcon name="building" :size="18" /> 是公共地方</n-button>
        </div>
        <n-button type="primary" block size="large" style="margin-top:10px;min-height:60px;font-size:1.25rem;"
                  :loading="loadingDraft" @click="recheck"><EIcon name="checkCircle" :size="18" /> 补充好了，再看一遍</n-button>
      </div>

      <template v-else>
        <div style="margin-top:12px;">
          <div class="muted" style="font-size:1.05rem;">紧急程度可以改（不急就选「一般」）：</div>
          <div style="display:flex;gap:8px;margin-top:6px;">
            <n-button v-for="u in ['一般', '中等', '紧急']" :key="u" size="large"
                      style="flex:1;min-height:56px;font-size:1.2rem;"
                      :type="answer.urgency === u ? 'primary' : 'default'"
                      @click="answer.urgency = u">{{ u }}</n-button>
          </div>
        </div>
        <n-button type="primary" block size="large" style="margin-top:14px;min-height:64px;font-size:1.3rem;"
                  :loading="submitting" @click="submit"><EIcon name="checkCircle" :size="18" /> 确认上报</n-button>
        <!-- 结果未知的出口（§6-I5）：不诱导老人重复点提交，而是帮他查清楚 -->
        <n-button v-if="unknownToken" block size="large" style="margin-top:10px;min-height:60px;font-size:1.25rem;"
                  @click="checkSubmitted"><EIcon name="search" :size="18" /> 查一下是否已经提交了</n-button>
        <div class="muted" style="margin-top:6px;font-size:1rem;">
          上报后工单进入待审核，负责人会在「我的报修」里回复您。
        </div>
      </template>

      <!-- 纠错与退出（v3 §7.2「纠错是一等功能」）：说错了/不是这个位置要能一键重来。
           放在**摘要卡内部紧挨着内容**，不在页面最底部——老人看到哪就得能在哪改，
           翻到页面底下才找到"重新说"等于没有这个入口（实测：手机上一屏根本看不到）。 -->
      <div style="display:flex;gap:8px;margin-top:14px;">
        <n-button size="large" data-restart style="flex:1;min-height:60px;font-size:1.2rem;"
                  @click="restart"><EIcon name="refresh" :size="18" /> 说错了，重新说</n-button>
        <n-button size="large" data-giveup style="flex:1;min-height:60px;font-size:1.2rem;"
                  @click="giveUp"><EIcon name="x" :size="18" /> 先不报修了</n-button>
      </div>
    </div>

    <!-- 提交结果＝**确认卡片**（收敛方案第 2 阶段）：让老人看见"系统到底记住了什么"，并且**逐条标明来源**。
         口径纪律（不许含糊）：来源有五种，各自中文说法见 SOURCE_LABEL ——
         「您确认的 / 来自您说的话 / 来自您的登记资料 / 系统建议（您已确认） / 默认值」，
         位置没确认时写「位置待人工确认」，绝不写成像已确认的样子。 -->
    <div v-if="submitted" class="card" data-confirm-card :data-result-via="resultVia || 'submit'"
         style="background:#ecfdf5;font-size:1.2rem;">
      <b><EIcon name="checkCircle" :size="18" /> 已经报上去了（工单号 {{ submitted.issue_id }}）</b>
      <!-- 结果是从"核对"来的就说清楚：老人/家属才知道这条不是当时服务端回的 -->
      <div v-if="resultVia === 'verify'" style="margin-top:6px;font-weight:700;color:var(--ink-info);">
        <EIcon name="signal" :size="18" /> 刚才网络没回话，工单号是按提交编号核对到的真实结果（没有重复上报）
      </div>

      <div style="margin-top:10px;font-weight:800;">您刚才反映的是：</div>
      <div style="margin-top:4px;">{{ submitted.confirmed.title || submitted.original_text }}</div>

      <div style="margin-top:10px;font-weight:800;">系统记录：</div>
      <div style="margin-top:4px;" data-src-location>
        <EIcon name="pin" :size="18" /> 位置：{{ submitted.confirmed.location || '位置待人工确认' }}
        <span class="muted" style="font-size:1rem;">{{ srcLine(submitted, 'location') }}</span>
        <span v-if="!submitted.confirmed.location" class="muted" style="font-size:1rem;">
          —— 我们没听清地点，已交人工帮您确认，不会随便填一个
        </span>
      </div>
      <div style="margin-top:4px;" data-src-scope>
        <EIcon name="home" :size="18" /> 责任范围：
        {{ submitted.confirmed.issue_type === '室内' ? '您家里' : '公共地方' }}
        <span class="muted" style="font-size:1rem;">{{ srcLine(submitted, 'scope') }}</span>
      </div>
      <div style="margin-top:4px;" data-src-urgency>
        <EIcon name="clock" :size="18" /> 紧急程度：{{ submitted.confirmed.urgency }}
        <span class="muted" style="font-size:1rem;">{{ srcLine(submitted, 'urgency') }}</span>
      </div>
      <div style="margin-top:4px;">
        <EIcon name="megaphone" :size="18" /> 所属社区：{{ submitted.community || '账号所属社区' }}
        <span class="muted" style="font-size:1rem;">（账号所属社区，不采集手机定位）</span>
      </div>
      <div style="margin-top:4px;">
        <EIcon name="clock" :size="18" /> 提交时间：{{ submitted.submitted_at || '刚刚' }}
        <span class="muted" style="font-size:1rem;">（系统记录）</span>
      </div>
      <div style="margin-top:6px;">
        <EIcon name="signal" :size="18" /> 当前状态：<b>已提交，等待网格员处理</b>
        <span class="muted" style="font-size:1rem;">（进度可以在「看看进度」里随时看）</span>
      </div>
      <div class="muted" style="margin-top:8px;font-size:1rem;">
        括号里写的是每条信息**从哪来的**：您说的、您确认的、还是我们按登记资料填的。
        系统不会把您没确认的内容写成事实。
      </div>
    </div>

    <n-button size="large" block style="margin-top:12px;min-height:56px;" @click="router.push('/elderly/home')"><EIcon name="home" :size="18" /> 返回首页</n-button>
  </div>
</template>
