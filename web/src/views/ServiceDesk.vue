<template>
  <div class="desk">
    <!-- 共享设备横幅：**必须一直看得见**。这台机器一天要接待十几位老人，
         "办完要收尾"这件事不能靠记性。 -->
    <div class="card desk-bar" data-shared-banner>
      <div>
        <b><EIcon name="users" :size="18" /> 服务台模式</b>
        <span class="muted" style="margin-left:8px;font-size:0.9rem;">
          当前社区：<b data-desk-community>{{ ctx.community || '读取中…' }}</b>
          · 操作人：{{ ctx.operator.name || '—' }}
          <span v-if="station">· 服务点：{{ station }}</span>
        </span>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <n-button size="small" @click="resetDevice" data-end-session>
          <EIcon name="checkCircle" :size="18" /> 结束本次办理
        </n-button>
      </div>
    </div>
    <div class="muted desk-tip">
      这是一台<b>共享设备</b>：办理完请点「结束本次办理」，下一位开始前请确认屏幕已回到起始页。
      本机不长期保存登录状态（关闭标签页即失效）。
    </div>

    <!-- 步骤提示：**不用 `n-steps`** —— 它未到达步骤的默认灰只有 1.67:1（亮）/ 3.56:1（暗），
         低于 4.5:1；而"第几步"这件事用一行带令牌的文字说清就够了（信息在每张卡片的标题里）。 -->
    <div class="desk-progress" data-desk-progress>
      第 {{ step + 1 }} 步 / 共 4 步 · {{ STEP_TITLES[step] }}
    </div>

    <!-- ① 办理方式 + 授权情况 -->
    <div v-if="step === 0" class="card" data-desk-step1>
      <div style="font-weight:700;margin-bottom:8px;">① 这次是谁在办？</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button v-for="c in ctx.channels" :key="c.value" class="pick"
                :class="{ on: form.channel === c.value }"
                :data-channel="c.value" @click="form.channel = c.value">
          {{ c.label }}
        </button>
      </div>
      <div style="font-weight:700;margin:14px 0 8px;">授权情况（<b>代录必须留下依据</b>）</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <button v-for="v in ctx.consent_values" :key="v" class="pick"
                :class="{ on: form.consent_status === v }"
                :data-consent="v" @click="form.consent_status = v">
          {{ v }}
        </button>
      </div>
      <div class="muted" style="font-size:0.85rem;margin-top:10px;">
        系统会分别记录「问题属于谁（当事人）」和「谁操作了系统（您）」——
        这样统计老人完成率时，才不会把工作人员代操作算成老人自己完成的。
      </div>
      <div style="margin-top:14px;">
        <n-input v-model:value="station" placeholder="服务点标识（如 STATION-01，便于定位设备）" style="max-width:320px;" data-station />
      </div>
      <n-button type="primary" style="margin-top:14px;" :disabled="!form.channel || !form.consent_status"
                @click="step = 1" data-desk-next1>
        下一步
      </n-button>
    </div>

    <!-- ② 当事人：本社区的人 / 走查居民 -->
    <div v-if="step === 1" class="card" data-desk-step2>
      <div style="font-weight:700;margin-bottom:8px;">② 这件事属于谁？</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
        <n-select v-model:value="form.reporter_id" :options="peopleOptions" filterable
                  placeholder="从本社区人员里选（老人/居民）" style="width:320px;" data-people />
        <n-button size="small" @click="walkIn = !walkIn" data-walkin-toggle>
          {{ walkIn ? '改回选择本社区人员' : '走查居民（没有账号）' }}
        </n-button>
      </div>
      <div v-if="walkIn" style="margin-top:12px;display:grid;gap:10px;max-width:420px;">
        <n-input v-model:value="form.reporter_name" placeholder="姓名（必填）" data-walkin-name />
        <n-input v-model:value="form.reporter_phone" placeholder="手机号（必填，网格员要能联系上）"
                 data-walkin-phone />
        <div class="muted" style="font-size:0.85rem;">
          走查居民会按<b>您所在社区</b>登记，网格员在自己的列表里能看到。
        </div>
      </div>

      <div style="font-weight:700;margin:18px 0 8px;">或者先查一下他有没有在办的事</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        <n-input v-model:value="q.name" placeholder="姓名" style="width:150px;" data-q-name />
        <n-input v-model:value="q.phone_tail" placeholder="手机后四位" style="width:150px;" data-q-tail />
        <n-input v-model:value="q.building" placeholder="楼栋（如 3号楼）" style="width:170px;" data-q-building />
        <n-input v-model:value="q.code" placeholder="事项编号" style="width:150px;" data-q-code />
        <n-button size="small" @click="doSearch" data-q-run>查询</n-button>
      </div>
      <div v-if="searchNote" class="muted" style="margin-top:8px;font-size:0.9rem;" data-q-note>{{ searchNote }}</div>
      <div v-if="results.length" class="card" style="margin-top:10px;" data-q-results>
        <div v-for="it in results" :key="it.issue_id" class="res-row">
          <div>
            <b>{{ it.issue_code || '（无编号）' }}</b> · {{ it.title }}
            <span class="muted">（{{ it.reporter_name }} · {{ it.location }} · {{ it.status }}）</span>
          </div>
          <div class="muted" style="font-size:0.82rem;">
            {{ it.reported_at }} · {{ it.channel_label }}<span v-if="it.is_demo"> · 演示数据</span>
          </div>
        </div>
      </div>

      <div style="margin-top:16px;display:flex;gap:8px;">
        <n-button @click="step = 0">上一步</n-button>
        <n-button type="primary" :disabled="!personReady" @click="step = 2" data-desk-next2>
          下一步
        </n-button>
      </div>
    </div>

    <!-- ③ 问题内容 -->
    <div v-if="step === 2" class="card" data-desk-step3>
      <div style="font-weight:700;margin-bottom:8px;">③ 他要反映什么？</div>
      <div class="muted" style="font-size:0.9rem;margin-bottom:8px;">
        把老人的原话写下来，点「系统帮我抽取」补全位置与责任范围——<b>抽出来的仍要您确认</b>。
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start;">
        <n-input v-model:value="form.text" type="textarea" :rows="3" style="max-width:560px;"
                 placeholder="例如：3号楼2单元楼道灯不亮，晚上看不见" data-desk-text />
        <n-button size="small" :loading="extracting" @click="doExtract" data-desk-extract>系统帮我抽取</n-button>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:14px;">
        <div>
          <div class="lbl">问题标题</div>
          <n-input v-model:value="form.title" placeholder="如 楼道灯不亮" data-f-title />
        </div>
        <div>
          <div class="lbl">位置（楼栋+单元/房号）</div>
          <n-input v-model:value="form.location" placeholder="如 3号楼2单元" data-f-location />
        </div>
        <div>
          <div class="lbl">责任范围</div>
          <n-select v-model:value="form.scope" :options="[{label:'室外（公共区域）',value:'室外'},{label:'室内（家里）',value:'室内'}]" data-f-scope />
        </div>
        <div>
          <div class="lbl">紧急程度</div>
          <n-select v-model:value="form.urgency" :options="URGENCY" data-f-urgency />
        </div>
      </div>
      <div style="margin-top:12px;">
        <div class="lbl">补充说明（会记进工单）</div>
        <n-input v-model:value="form.description" type="textarea" :rows="2" style="max-width:640px;" data-f-desc />
      </div>
      <div v-if="extractSrc" class="muted" style="font-size:0.85rem;margin-top:10px;" data-extract-src>
        系统建议来源：{{ extractSrc }}
      </div>
      <div style="margin-top:16px;display:flex;gap:8px;">
        <n-button @click="step = 1">上一步</n-button>
        <n-button type="primary" :loading="saving" :disabled="!contentReady" @click="doSubmit" data-desk-submit>
          提交登记
        </n-button>
      </div>
    </div>

    <!-- ④ 完成：编号 + 下一步 + 明确"编号不用他记" -->
    <div v-if="step === 3" class="card" data-desk-done style="background:var(--panel-lemon);">
      <div style="font-weight:700;font-size:1.15rem;">
        <EIcon name="checkCircle" :size="18" /> 已登记
        <span v-if="done.issue_code">（事项编号 {{ done.issue_code }}）</span>
      </div>
      <div style="margin-top:8px;">
        下一步：负责人会核实并安排处理；居民可以在自己的手机上看到进度。
      </div>
      <div class="muted" style="margin-top:6px;">
        <b>编号不用他记</b>——以后想查，报姓名、楼栋或大概时间都能查到。
      </div>
      <div style="margin-top:16px;display:flex;gap:8px;flex-wrap:wrap;">
        <n-button type="primary" @click="startNew" data-desk-new>开始新的办理</n-button>
        <n-button @click="resetDevice">结束本次办理</n-button>
      </div>
    </div>

    <div v-if="confirmMultiple" class="card" style="margin-top:12px;border-left:4px solid var(--ink-warning);" data-q-multi>
      <b>{{ searchNote }}</b>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { serviceDesk } from '../api'
import EIcon from '../components/EIcon.vue'
import { newToken } from '../utils/idemToken'

const message = useMessage()
const step = ref(0)
const URGENCY = ['一般', '中等', '紧急', '普通'].map((v) => ({ label: v, value: v }))
const STEP_TITLES = ['选择办理方式与授权情况', '确认当事人', '记录问题内容', '已登记']

const ctx = ref({ community: '', operator: {}, channels: [], consent_values: [], people: [] })
const station = ref('')
const walkIn = ref(false)
const saving = ref(false)
const extracting = ref(false)
const extractSrc = ref('')
const done = ref({})
const q = ref({ name: '', phone_tail: '', building: '', code: '' })
const results = ref([])
const searchNote = ref('')
const confirmMultiple = ref(false)
const tokens = ref({})

const form = ref({
  channel: '', consent_status: '', reporter_id: null, reporter_name: '', reporter_phone: '',
  text: '', title: '', location: '', scope: '室外', urgency: '一般', description: '',
})

const peopleOptions = computed(() => (ctx.value.people || []).map((p) => ({
  label: `${p.name}（${p.role === 'elderly' ? '老人' : p.role === 'resident' ? '居民' : '工作人员'} #${p.id}）`,
  value: p.id,
})))

const personReady = computed(() => {
  if (walkIn.value) return Boolean(form.value.reporter_name && form.value.reporter_phone)
  return Boolean(form.value.reporter_id)
})
const contentReady = computed(() => Boolean(form.value.title && form.value.location && form.value.description))

onMounted(async () => {
  try {
    ctx.value = (await serviceDesk.context()) || ctx.value
  } catch (e) {
    message.error(e.message)
  }
  // 服务点写在 sessionStorage 里：同一台设备刷新后还在，**关掉标签页就没了**（共享设备要求）
  try { station.value = sessionStorage.getItem('ci_desk_station') || '' } catch { /* 忽略 */ }
})

async function doExtract() {
  const text = (form.value.text || '').trim()
  if (text.length < 2) return message.warning('先把老人的原话写下来')
  extracting.value = true
  try {
    const d = (await serviceDesk.extract(text)) || {}
    const f = d.fields || {}
    if (f.title) form.value.title = f.title
    if (f.location) form.value.location = f.location
    if (f.issue_type) form.value.scope = f.issue_type
    if (f.urgency) form.value.urgency = f.urgency
    form.value.description = form.value.description || text
    const s = d.sources || {}
    extractSrc.value = Object.entries(s).map(([k, v]) => `${k}=${v}`).join(' · ')
    if (!d.ok && d.ask) message.info(d.ask)
  } catch (e) {
    message.error(e.message)
  } finally {
    extracting.value = false
  }
}

async function doSearch() {
  try {
    const d = (await serviceDesk.search({ ...q.value, limit: 20 })) || {}
    results.value = d.items || []
    searchNote.value = d.note || ''
    confirmMultiple.value = Boolean(d.need_confirm)
  } catch (e) {
    message.error(e.message)
  }
}

async function doSubmit() {
  saving.value = true
  try {
    const body = {
      channel: form.value.channel,
      consent_status: form.value.consent_status,
      station_id: station.value,
      reporter_id: walkIn.value ? 0 : Number(form.value.reporter_id || 0),
      reporter_name: walkIn.value ? form.value.reporter_name : (peopleName(form.value.reporter_id)),
      reporter_phone: walkIn.value ? form.value.reporter_phone : '',
      title: form.value.title, description: form.value.description,
      location: form.value.location, scope: form.value.scope,
      urgency: form.value.urgency, raw_text: form.value.text,
      // 幂等：同一次意图沿用同一个编号（重复点/网络重试不会建两张单）
      client_token: tokens.value.submit || (tokens.value.submit = newToken()),
    }
    const d = (await serviceDesk.submit(body)) || {}
    done.value = d
    step.value = 3
    try { sessionStorage.setItem('ci_desk_station', station.value || '') } catch { /* 忽略 */ }
  } catch (e) {
    message.error(e.message)
  } finally {
    saving.value = false
  }
}

function peopleName(id) {
  const p = (ctx.value.people || []).find((x) => x.id === Number(id))
  return p ? p.name : ''
}

function startNew() {
  // 下一位老人：**清掉上一位的全部输入**，只保留服务点与办理方式以外的默认值
  form.value = {
    channel: form.value.channel, consent_status: '', reporter_id: null,
    reporter_name: '', reporter_phone: '', text: '', title: '', location: '',
    scope: '室外', urgency: '一般', description: '',
  }
  walkIn.value = false
  results.value = []
  searchNote.value = ''
  extractSrc.value = ''
  done.value = {}
  tokens.value = {}
  step.value = 0
}

async function resetDevice() {
  try {
    await serviceDesk.reset({ station_id: station.value, reporter_id: form.value.reporter_id || 0 })
  } catch (e) {
    // 清理失败**必须让工作人员看到**（否则下一位老人的信息还留在机器上）
    message.error(`本机临时数据未清理干净：${e.message}`)
    return
  }
  // 浏览器侧：清掉本次办理的一切痕迹
  try {
    sessionStorage.removeItem('ci_desk_station')
    sessionStorage.clear()
  } catch { /* 忽略 */ }
  startNew()
  message.success('本次办理已结束，可以接待下一位')
}
</script>

<style scoped>
.desk { max-width: 1100px; margin: 0 auto; padding: 16px; }
.desk-bar { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.desk-tip { font-size: 0.85rem; margin-top: 8px; }
.desk-progress { margin: 12px 0 16px; font-weight: 700; color: var(--ink-info); }
.pick { min-height: 44px; padding: 8px 14px; border-radius: 8px; border: 1px solid var(--border);
        background: var(--card-bg); color: var(--text); font-size: 0.95rem; cursor: pointer; }
.pick.on { border-color: var(--primary-ink); color: var(--primary-ink); font-weight: 700; }
.lbl { font-size: 0.85rem; margin-bottom: 4px; color: var(--muted); }
.res-row { padding: 8px 0; border-bottom: 1px solid var(--border); }
.res-row:last-child { border-bottom: 0; }
</style>
