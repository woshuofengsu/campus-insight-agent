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

const router = useRouter()
const message = useMessage()
const { recognize, speak } = useSpeech()

const text = ref('')
const listening = ref(false)
const submitting = ref(false)
const loadingDraft = ref(false)
const draft = ref(null)          // 结构化摘要（服务端返回）
const submitted = ref(null)      // 提交成功后的四段值
const unknownToken = ref('')     // 提交结果未知时的幂等编号（§6-I5：不诱导老人重复点提交）
// 老人补充/确认的字段（预填系统的建议，老人可改）
const answer = ref({ location: '', scope: '', urgency: '一般' })

const cap = speechCapability()
const asrBlocked = ref(!cap.hasASR || !cap.secure)
const blockReason = ref(cap.asrReason || '')
const banner = computed(() => reasonText(blockReason.value || 'unsupported'))
// 播报是否真的响过：iOS Safari 的 TTS 必须由**用户手势**触发，挂载即播会静默不响，
// 所以本页**不自动播报**，只提供"🔊 听一遍"，并且播不出来时如实说明（不假装老人听到了）
const ttsOk = ref(cap.hasTTS)
const lastSpoken = ref('')

const SOURCE_LABEL = {
  text: '来自您说的话',
  user: '您确认的',
  profile: '来自您的登记资料',
  suggestion: '系统建议（还没确认）',
  default: '默认值',
  none: '暂缺',
}
const srcTip = (k) => SOURCE_LABEL[k] || ''

/** 统一播报入口：返回是否真的响了；失败就把 🔊 降级成"请看大字"的说明。 */
async function say(text) {
  const t = (text || '').trim()
  if (!t) return false
  lastSpoken.value = t
  const ok = await speak(t, 1.0, 0.9)
  if (!ok) ttsOk.value = false
  return ok
}

async function startListen() {
  if (asrBlocked.value) return                      // 已知不可用：直接给打字路径，不空转
  listening.value = true
  const r = await recognize()
  listening.value = false
  if (r.ok && r.text) {
    text.value = r.text
    // 识别结果**显示**在页面上即可，播报交给"🔊 听一遍"（挂载/自动播在 iOS 不响）
    await say(`您说的是：${r.text}。请确认下面的信息`)
    await loadDraft()
  } else {
    // 按真实原因分派文案：不支持/没权限/网络 → 引导打字；空识别 → 请再说一次
    const reason = r.reason || 'empty'
    if (reason !== 'empty' && reason !== 'done') {
      asrBlocked.value = true
      blockReason.value = reason
    }
    message.warning(reasonText(reason))
  }
}

/** 让服务端把原话解析成结构化摘要（缺什么会明说，且**此时不会建单**）。 */
async function loadDraft() {
  if (text.value.trim().length < 5) return message.warning('请描述问题，至少 5 个字')
  draft.value = null
  submitted.value = null
  loadingDraft.value = true
  try {
    const d = await elderly.reportDraft(text.value)
    draft.value = d
    answer.value = {
      location: d.fields.location || d.suggestion.location || '',
      scope: d.fields.issue_type || '',
      urgency: d.fields.urgency || '一般',
    }
    if (d.need_more) {
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

/** 老人补充完信息后重新解析（不建单），直到没有缺失项。 */
async function recheck() {
  await loadDraft()
}

/** 每次"准备提交"生成一个幂等编号：网络重试沿用同一个（卡8 / §6-I5）。 */
function newToken() {
  try {
    if (window.crypto && window.crypto.randomUUID) return window.crypto.randomUUID().replace(/-/g, '')
  } catch { /* 忽略：回落下面的方案 */ }
  return 'r' + Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
}

async function submit() {
  if (!draft.value) return
  submitting.value = true
  // 同一个草稿只在第一次生成 token，重试沿用（否则重试会变成"新的一次提交"）
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
    unknownToken.value = ''
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
  } catch (e) {
    // ⚠️ 断网/超时时**不能**说"提交失败"就完事 —— 可能其实已经提交成功了。
    // 如实告诉老人"结果还不确定"，并给一个"查一下"的出口，**不诱导他再点一次**（§6-I5）。
    const maybe = /超时|timeout|Network|Failed to fetch|网络/i.test(String(e && e.message) || '')
    if (maybe) {
      message.warning('网络没回话，我先帮您核对一下是否已经报上去了')
      await say('网络没有回话，我帮您核对一下是不是已经报上去了')
      await checkSubmitted()
    } else {
      message.error(e.message || '上报失败，请稍后再试')
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
      unknownToken.value = ''
      draft.value = null
      text.value = ''
      message.success(`核对到了：已经提交成功，工单号 ${s.issue_id}`)
      await say(`核对到了，已经提交成功，工单号 ${s.issue_id}`)
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
    <div class="elderly-title">🗣️ 一句话报修</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">说一句或打几个字，我帮您整理成工单</p>

    <!-- 页面提示也做成"点一下听"（不在挂载时自动播：iOS 需要用户手势，否则静默不响） -->
    <n-button v-if="ttsOk && !lastSpoken" block size="large"
              style="margin-bottom:10px;min-height:60px;font-size:1.2rem;"
              @click="say('说一句或打几个字，我帮您整理成工单。位置要说清楚是哪个楼、哪一层。')">
      🔊 听一遍怎么用
    </n-button>
    <div v-else-if="!ttsOk" class="card muted" style="font-size:1.1rem;">
      🔇 这台手机的语音播不出来，请看屏幕上的大字（内容是一样的）
    </div>

    <!-- 降级提示条：语音不可用时明说"打字就行"（审计靠 data-speech-fallback 做机器验证） -->
    <div v-if="asrBlocked" data-speech-fallback
         class="card panel-warm" style="border-radius:14px;font-size:1.3rem;">
      🔇 {{ banner }}
    </div>

    <div class="card" style="font-size:1.3rem;">
      <n-button v-if="!asrBlocked" type="error" block size="large"
                style="min-height:72px;font-size:1.4rem;" :loading="listening" @click="startListen">
        🎤 {{ listening ? '正在聆听…（最多 60 秒）' : '点一下开始说话' }}
      </n-button>
      <div v-else style="font-size:1.3rem;font-weight:700;">
        ✍️ 请在下面的框里打字告诉我们（最少 5 个字）
      </div>

      <n-input v-model:value="text" type="textarea" :rows="3" placeholder="比如：五号楼二层楼道灯坏了"
               style="font-size:1.3rem;margin-top:12px;" />

      <!-- 播报一律"点一下听"（v3 复核 B3）：挂载自动播在 iOS 静默不响，不能假装老人听到了 -->
      <n-button v-if="lastSpoken && ttsOk" block size="large"
                style="margin-top:10px;min-height:60px;font-size:1.25rem;" @click="say(lastSpoken)">
        🔊 听一遍
      </n-button>
      <div v-else-if="lastSpoken && !ttsOk" class="muted" style="margin-top:8px;font-size:1.1rem;">
        🔇 这台手机的语音播不出来，请看屏幕上的大字（内容是一样的）
      </div>

      <n-button type="primary" block size="large" style="margin-top:12px;min-height:60px;font-size:1.25rem;"
                :loading="loadingDraft" @click="loadDraft">
        🔍 帮我看看还缺什么
      </n-button>
    </div>

    <!-- 结构化摘要：老人核对的就是**办理信息**，不是一串转写文本 -->
    <div v-if="draft" class="card" style="font-size:1.25rem;">
      <b>📋 请您核对这几项</b>
      <div style="margin-top:8px;">🗣️ 您说的：{{ draft.original_text }}</div>
      <div style="margin-top:6px;">🔧 问题：{{ draft.fields.title }}</div>
      <div style="margin-top:6px;">
        📍 位置：
        <b v-if="draft.fields.location">{{ draft.fields.location }}</b>
        <span v-else style="color:var(--danger,#c00);">还缺，请在下面补充</span>
        <span class="muted" style="font-size:1rem;">（{{ srcTip(draft.sources.location) }}）</span>
      </div>
      <div style="margin-top:6px;">
        🏠 责任范围：
        <b v-if="draft.fields.issue_type === '室内'">您家里（自己家的事）</b>
        <b v-else-if="draft.fields.issue_type === '室外'">公共地方（楼道/电梯等）</b>
        <span v-else style="color:var(--danger,#c00);">还没定，请选一下</span>
      </div>
      <div style="margin-top:6px;">⏱️ 紧急程度：{{ draft.fields.urgency }}</div>

      <!-- 缺失项：就地追问（缺什么问什么，缺着就不给提交） -->
      <div v-if="draft.need_more" class="panel-warm" style="margin-top:12px;border-radius:10px;padding:10px;">
        <b>❓ {{ draft.ask }}</b>
        <!-- 系统已经能猜出位置时，给一个"就是它"的大按钮：老人点一下就行，不用打字 -->
        <n-button v-if="draft.suggestion.location" type="primary" block size="large"
                  style="margin-top:8px;min-height:64px;font-size:1.25rem;"
                  @click="answer.location = draft.suggestion.location; recheck()">
          ✅ 就是这里：{{ draft.suggestion.location }}
        </n-button>
        <n-input v-model:value="answer.location" placeholder="或者告诉我别的：比如 5号楼二层楼道"
                 size="large" style="font-size:1.2rem;margin-top:8px;" />
        <div style="display:flex;gap:8px;margin-top:8px;">
          <n-button size="large" style="flex:1;min-height:56px;font-size:1.2rem;"
                    :type="answer.scope === '室内' ? 'primary' : 'default'"
                    @click="answer.scope = '室内'">🏠 是我家里</n-button>
          <n-button size="large" style="flex:1;min-height:56px;font-size:1.2rem;"
                    :type="answer.scope === '室外' ? 'primary' : 'default'"
                    @click="answer.scope = '室外'">🏢 是公共地方</n-button>
        </div>
        <n-button type="primary" block size="large" style="margin-top:10px;min-height:60px;font-size:1.25rem;"
                  :loading="loadingDraft" @click="recheck">✅ 补充好了，再看一遍</n-button>
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
                  :loading="submitting" @click="submit">✅ 确认上报</n-button>
        <!-- 结果未知的出口（§6-I5）：不诱导老人重复点提交，而是帮他查清楚 -->
        <n-button v-if="unknownToken" block size="large" style="margin-top:10px;min-height:60px;font-size:1.25rem;"
                  @click="checkSubmitted">🔍 查一下是否已经提交了</n-button>
        <div class="muted" style="margin-top:6px;font-size:1rem;">
          上报后工单进入待审核，负责人会在「我的报修」里回复您。
        </div>
      </template>
    </div>

    <!-- 提交结果：原话 / 系统建议 / 您确认的 / 入库值 四段分开展示（不混成一句"已纠正"） -->
    <div v-if="submitted" class="card" style="background:#ecfdf5;font-size:1.2rem;">
      <b>✅ 已上报（工单号 {{ submitted.issue_id }}）</b>
      <div style="margin-top:8px;">🗣️ 您说的：{{ submitted.original_text }}</div>
      <div style="margin-top:4px;">📍 最终记录的位置：{{ submitted.confirmed.location }}</div>
      <div style="margin-top:4px;">🏠 责任范围：
        {{ submitted.confirmed.issue_type === '室内' ? '您家里' : '公共地方' }}</div>
      <div style="margin-top:4px;">⏱️ 紧急程度：{{ submitted.confirmed.urgency }}</div>
      <div class="muted" style="margin-top:6px;font-size:1rem;">
        位置来源：{{ srcTip(submitted.sources.location) }}（系统不会把您没确认的内容写成事实）
      </div>
    </div>

    <n-button size="large" block style="margin-top:12px;min-height:56px;" @click="router.push('/elderly/home')">🏠 返回首页</n-button>
  </div>
</template>
