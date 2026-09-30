<script setup>
// 老年端：我的报修工单进度 + 满意度反馈
//
// v3 复核 §6-I9（老人订单缺少可理解的完整进度）：进度**由服务端算好**（`/elderly/orders`），
// 页面只负责用大字说实话，四件事必须一眼看到：
//   ① 现在到哪一步（五步进度条）② 下一步谁做 ③ 按社区规定还要多久 ④ **有没有超时**（超时明说）。
// 原来的问题：只把状态字段换个说法（"等待派单"），老人既不知道该等谁、也不知道要等多久，
// 只能反复打电话问。
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly, issues } from '../../api'
import { useSpeech, speechCapability } from '../../composables/useSpeech'
import EIcon from '../../components/EIcon.vue'

const message = useMessage()
const { speak } = useSpeech()
const cap = speechCapability()
const ttsOk = ref(cap.hasTTS)
const lastSpoken = ref('')
const list = ref([])
const loading = ref(true)
// 加载失败必须与"没有记录"**区分开**：查不到就说查不到（可重试），
// 绝不能在接口 500 / 断网时显示"还没有报修记录"——那等于告诉老人"你没有报过修"。
const loadError = ref('')
const fbReason = ref({})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    list.value = (await elderly.orders({ limit: 10 })) || []
  } catch (e) {
    loadError.value = (e && e.message) || '网络不太顺，没能查到您的报修记录'
    list.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

/** 统一播报入口：接住返回值，播不出来就如实降级（不假装老人听到了）。 */
async function say(text) {
  const t = (text || '').trim()
  if (!t) return false
  lastSpoken.value = t
  const ok = await speak(t, 1.0, 0.9)
  if (!ok) ttsOk.value = false
  return ok
}

/** 把一条工单的进度念出来（老人可以选择"听进度"而不是看小字）。 */
function speakProgress(i) {
  const p = i.progress || {}
  say(`工单${i.id}，${i.title}。${p.now_line || ''}。${p.next_line || ''}。${p.eta_line || ''}`)
}

async function act(id, data, okMsg) {
  try {
    await issues.action(id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title"><EIcon name="clipboard" :size="18" /> 我的报修</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">现在到哪一步、下一步谁来做，都写在这里</p>

    <div v-if="lastSpoken && !ttsOk" data-speech-fallback class="card muted" style="font-size:1.2rem;">
      <EIcon name="speaker-off" :size="18" /> 这台手机的语音念不出来，请看屏幕上的大字（内容是一样的）
    </div>

    <div v-for="i in list" :key="i.id" class="card" style="font-size:1.25rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
        <b>#{{ i.id }} {{ i.title }}</b>
      </div>

      <!-- 五步进度：已走过的高亮（注意：老年端字号一律 ≥20px，1.05rem=16.8px 会被 ui_audit 判不合格） -->
      <div style="display:flex;gap:4px;margin-top:10px;">
        <div v-for="(s, si) in (i.progress?.steps || [])" :key="s"
             :style="`flex:1;text-align:center;font-size:1.25rem;padding:6px 2px;border-radius:8px;` +
                     (si < (i.progress?.step_index || 0)
                       ? 'background:var(--success-light,#dcfce7);color:var(--ink-success);font-weight:700;'
                       : 'background:var(--bg);color:var(--muted);')">
          <EIcon v-if="si < (i.progress?.step_index || 0)" name="checkCircle" :size="22" />{{ s }}
        </div>
      </div>

      <!-- 四句话说清：现在 / 下一步 / 谁 / 还要多久（超时就明说） -->
      <div style="margin-top:10px;font-weight:800;color:var(--ink-info);">
        {{ i.progress?.now_line || i.status }}
      </div>
      <div style="margin-top:6px;"><EIcon name="arrowRight" :size="18" /> {{ i.progress?.next_line }}</div>
      <div class="muted" style="margin-top:4px;font-size:1.25rem;"><EIcon name="user" :size="18" /> 这一步由：{{ i.progress?.who }}</div>
      <div :style="`margin-top:6px;font-size:1.25rem;` +
                   (i.progress?.overdue ? 'color:var(--ink-danger);font-weight:700;' : '')">
        ⏱️ {{ i.progress?.eta_line }}
      </div>

      <div class="muted" style="font-size:1.25rem;margin-top:6px;">
        {{ i.issue_type }} · {{ i.category }} · <EIcon name="pin" :size="18" /> {{ i.location }}
        <span v-if="i.assignee_name"> · <EIcon name="user-worker" :size="18" /> {{ i.assignee_name }}</span>
      </div>
      <div v-if="i.resolve_note" style="margin-top:6px;"><EIcon name="clipboard" :size="18" /> {{ i.resolve_note }}</div>

      <n-button block size="large" style="margin-top:10px;min-height:60px;font-size:1.2rem;"
                @click="speakProgress(i)"><EIcon name="speaker" :size="18" /> 听一遍这条进度</n-button>

      <!-- 满意度反馈 -->
      <div v-if="i.status === '待居民反馈'" class="panel-warm" style="margin-top:12px;border-radius:10px;padding:10px;">
        <div style="font-weight:700;font-size:1.25rem;">修好了吗？</div>
        <n-input v-model:value="fbReason[i.id]" placeholder="不满意原因（可选）" size="large"
                 style="margin-top:8px;font-size:1.25rem;" />
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:8px;">
          <n-button type="success" size="large" style="min-height:56px;font-size:1.2rem;"
                    @click="act(i.id, { action: 'feedback', satisfied: true }, '已结单')"><EIcon name="checkCircle" :size="18" /> 满意，结单</n-button>
          <n-button type="warning" size="large" style="min-height:56px;font-size:1.2rem;"
                    @click="act(i.id, { action: 'feedback', satisfied: false, reason: fbReason[i.id] || '还需处理' }, '已反馈，将重新处理')">
            <EIcon name="face-sad" :size="18" /> 不满意
          </n-button>
        </div>
      </div>
    </div>
    <n-empty v-if="!loading && !loadError && list.length === 0" description="还没有报修记录" style="font-size:1.25rem;" />

    <!-- 查不到 ≠ 没有记录：明确说清是"没查到"，并给一次重试 -->
    <div v-if="loadError" class="panel-warm" data-load-error
         style="border-radius:14px;padding:12px;font-size:1.25rem;">
      <EIcon name="alert" :size="18" /> 没能查到您的报修记录（{{ loadError }}）
      <n-button block size="large" type="primary" style="margin-top:10px;min-height:60px;font-size:1.25rem;"
                @click="load"><EIcon name="refresh" :size="18" /> 再试一次</n-button>
    </div>
  </div>
</template>
