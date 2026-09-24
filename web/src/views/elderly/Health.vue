<script setup>
// 老年端「我的健康」：血压/血糖录入 + 最近记录（大字大热区）
// 口径：分级与提示语由后端 data/_vitals_logic.py 给，前端只显示，绝不自己判病。
// 审计口径（scripts/mobile_audit.py）：老年端字号 ≥20px、可点元素高 ≥44px、宽 ≥24px
// —— 所以这里不用 n-input-number（内部 +/- 小按钮会踩热区），改用大字 n-input + 数字键盘。
import { ref, onMounted, computed } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'
import { useSpeech } from '../../composables/useSpeech'

const message = useMessage()
const { speak } = useSpeech()
const kind = ref('bp')
const form = ref({ sys: '', dia: '', glucose: '', measure_when: 'random' })
const records = ref([])
const summary = ref({})

// 语义色一律用**亮/暗成对令牌**（写死 hex 在暗色下对比度不达标，ui_audit 会抓）
const LEVEL_COLOR = { normal: 'var(--ink-success)', attention: 'var(--ink-warning)', alert: 'var(--ink-danger)' }
const LEVEL_TEXT = { normal: '正常范围', attention: '需留意', alert: '明显偏离' }
const WHEN_TEXT = { fasting: '空腹', postprandial: '餐后', random: '随机' }

onMounted(load)

async function load() {
  try { records.value = (await elderly.vitals({ limit: 14 })) || [] } catch { /* 忽略 */ }
  try { summary.value = (await elderly.vitalsSummary()) || {} } catch { /* 忽略 */ }
}

const latestBp = computed(() => summary.value.latest_bp || null)
const latestGlu = computed(() => summary.value.latest_glucose || null)

async function save() {
  const payload = { kind: kind.value, measure_when: form.value.measure_when }
  if (kind.value === 'bp') {
    if (!form.value.sys && !form.value.dia) return message.warning('请填写血压数值')
    payload.sys = form.value.sys ? Number(form.value.sys) : null
    payload.dia = form.value.dia ? Number(form.value.dia) : null
  } else {
    if (!form.value.glucose) return message.warning('请填写血糖数值')
    payload.glucose = Number(form.value.glucose)
  }
  try {
    const r = await elderly.addVital(payload)
    message.success(r?.hint || '已记录')
    if (r?.hint) speak(r.hint)      // 录完把提示语念出来（老人不一定看清小字）
    form.value = { sys: '', dia: '', glucose: '', measure_when: 'random' }
    load()
  } catch (e) {
    message.error(e.message)
  }
}

function readAloud() {
  const parts = []
  if (latestBp.value) parts.push(`最近一次血压，高压${latestBp.value.sys}，低压${latestBp.value.dia}`)
  if (latestGlu.value) parts.push(`最近一次血糖${latestGlu.value.glucose}`)
  parts.push(summary.value.bp_trend_label || '')
  speak(parts.filter(Boolean).join('。'))
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">🩺 我的健康</h2>

    <!-- 最近一次记录 -->
    <div class="card" style="border-radius:18px;">
      <div style="font-size:1.35rem;font-weight:800;margin-bottom:8px;">最近一次记录</div>
      <div v-if="latestBp" style="font-size:1.5rem;">
        血压 <b>{{ latestBp.sys }}/{{ latestBp.dia }}</b>
        <span :style="{ color: LEVEL_COLOR[latestBp.level], fontWeight: 800 }">
          （{{ LEVEL_TEXT[latestBp.level] }}）
        </span>
      </div>
      <div v-if="latestGlu" style="font-size:1.5rem;margin-top:6px;">
        血糖 <b>{{ latestGlu.glucose }}</b>
        <span style="font-size:1.25rem;">{{ WHEN_TEXT[latestGlu.measure_when] || '' }}</span>
        <span :style="{ color: LEVEL_COLOR[latestGlu.level], fontWeight: 800 }">
          （{{ LEVEL_TEXT[latestGlu.level] }}）
        </span>
      </div>
      <div v-if="!latestBp && !latestGlu" style="font-size:1.3rem;">
        还没有记录，下面填一次就有了。
      </div>
      <div v-if="latestBp?.level_hint" style="font-size:1.3rem;margin-top:8px;">
        {{ latestBp.level_hint }}
      </div>
      <n-button size="large" block style="margin-top:12px;min-height:64px;font-size:1.3rem;"
                @click="readAloud">🔊 听一遍</n-button>
    </div>

    <!-- 录入 -->
    <div class="card" style="border-radius:18px;">
      <div style="font-size:1.35rem;font-weight:800;margin-bottom:10px;">记一次</div>

      <div style="display:flex;gap:12px;margin-bottom:14px;">
        <n-button size="large" :type="kind === 'bp' ? 'primary' : 'default'"
                  style="flex:1;min-height:64px;font-size:1.3rem;" @click="kind = 'bp'">血压</n-button>
        <n-button size="large" :type="kind === 'glucose' ? 'primary' : 'default'"
                  style="flex:1;min-height:64px;font-size:1.3rem;" @click="kind = 'glucose'">血糖</n-button>
      </div>

      <div v-if="kind === 'bp'">
        <div style="font-size:1.3rem;margin-bottom:6px;">高压（上面那个数）</div>
        <n-input v-model:value="form.sys" size="large" inputmode="numeric" maxlength="3"
                 placeholder="例如 130" class="big-input" style="min-height:64px;" />
        <div style="font-size:1.3rem;margin:12px 0 6px;">低压（下面那个数）</div>
        <n-input v-model:value="form.dia" size="large" inputmode="numeric" maxlength="3"
                 placeholder="例如 80" class="big-input" style="min-height:64px;" />
      </div>

      <div v-else>
        <div style="font-size:1.3rem;margin-bottom:6px;">血糖值（mmol/L）</div>
        <n-input v-model:value="form.glucose" size="large" inputmode="decimal" maxlength="4"
                 placeholder="例如 6.2" class="big-input" style="min-height:64px;" />
        <div style="font-size:1.3rem;margin:12px 0 6px;">什么时候测的</div>
        <div style="display:flex;gap:12px;">
          <n-button v-for="w in ['fasting', 'postprandial', 'random']" :key="w" size="large"
                    :type="form.measure_when === w ? 'primary' : 'default'"
                    style="flex:1;min-height:60px;font-size:1.25rem;"
                    @click="form.measure_when = w">{{ WHEN_TEXT[w] }}</n-button>
        </div>
      </div>

      <n-button type="primary" size="large" block
                style="margin-top:16px;min-height:76px;font-size:1.4rem;font-weight:800;border-radius:18px;"
                @click="save">✅ 保存这一条</n-button>
    </div>

    <!-- 最近记录 -->
    <div class="card" style="border-radius:18px;">
      <div style="font-size:1.35rem;font-weight:800;margin-bottom:8px;">最近的记录</div>
      <div v-for="r in records" :key="r.id"
           style="font-size:1.3rem;padding:10px 0;border-bottom:1px solid var(--border);">
        <span style="font-size:1.25rem;">{{ (r.measured_at || '').slice(5, 16) }}</span>
        ·
        <template v-if="r.kind === 'bp'">血压 {{ r.sys }}/{{ r.dia }}</template>
        <template v-else>血糖 {{ r.glucose }}（{{ WHEN_TEXT[r.measure_when] }}）</template>
        <span :style="{ color: LEVEL_COLOR[r.level], fontWeight: 800 }">（{{ LEVEL_TEXT[r.level] }}）</span>
      </div>
      <div v-if="records.length === 0" style="font-size:1.3rem;">还没有记录</div>
      <div style="font-size:1.25rem;margin-top:10px;">
        这里只做记录和提醒；具体怎么用药、要不要调整，请听社区医生的。
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 老年端审计要求字号 ≥20px：把输入框内部元素一并放大（naive-ui 默认 14px） */
.big-input :deep(.n-input__input-el),
.big-input :deep(.n-input__placeholder) {
  font-size: 1.5rem;
  height: 100%;
}
</style>
