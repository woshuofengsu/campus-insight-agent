<script setup>
// 老年关怀管理（负责人）：用药审核 / 紧急联系人审核 / SOS 响应
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'
import EIcon from '../../components/EIcon.vue'

const message = useMessage()
const tab = ref('meds')
const meds = ref([])
const contacts = ref([])
const sosList = ref([])
const inactive = ref([])            // P3：久未互动的老人（24h 阈值，后端算好的）
const elders = ref([])              // P4：老人下拉（网格员选对象，不用手输 ID）
const vitalUid = ref(null)
const vitals = ref([])
const auditOp = ref({}) // 审核意见
const replyOp = ref({}) // SOS 处理备注
const loadError = ref('')   // 注意：取数失败必须看得见，否则"暂无求助记录"会骗人

onMounted(load)

async function load() {
  // 注意（2026-10-06 修）：原来五个请求全是空 catch，页面用确定的"暂无求助记录"兜底 ——
  // 网格员会据此判断"今天没有老人求助"，而真相是**取数失败**。
  // 现在：任何一个失败都置 loadError（页面顶部显示红条 + 重试），
  // 并且把该列表的"空"与"没取到"区分开（下面的 v-if 判据都用 loadError 兜住）。
  loadError.value = ''
  const [m, c, s, i, e] = await Promise.allSettled([
    elderly.manageMeds(), elderly.manageContacts(), elderly.manageSos(),
    elderly.manageInactive({ days: 1 }), elderly.manageElders(),
  ])
  const failed = []
  if (m.status === 'fulfilled') meds.value = m.value || []; else failed.push('用药提醒')
  if (c.status === 'fulfilled') contacts.value = c.value || []; else failed.push('紧急联系人')
  if (s.status === 'fulfilled') sosList.value = s.value || []; else failed.push('求助记录')
  if (i.status === 'fulfilled') inactive.value = i.value || []; else failed.push('久未互动')
  if (e.status === 'fulfilled') elders.value = e.value || []; else failed.push('老人名单')
  if (failed.length) loadError.value = `${failed.join('、')}读取失败——下面的"暂无"不代表真的没有，请点重试`
}

// P4：健康记录（只做记录与提醒，页面不出现任何医学结论——文案全部来自后端）
const VITAL_LEVEL = { normal: '正常范围', attention: '需留意', alert: '明显偏离' }

async function loadVitals(uid) {
  vitalUid.value = uid
  vitals.value = []
  if (!uid) return
  try {
    const d = await elderly.manageVitals({ uid, limit: 14 })
    vitals.value = (d && d.records) || []
  } catch (e) { message.error(e.message) }
}

async function auditMed(m, approve) {
  try {
    await elderly.auditMedication(m.id, { approve, opinion: auditOp.value[m.id] || '同意' })
    message.success('审核完成')
    load()
  } catch (e) { message.error(e.message) }
}

async function auditContact(c, approve) {
  try {
    await elderly.auditContact(c.id, { approve, opinion: '同意' })
    message.success('审核完成')
    load()
  } catch (e) { message.error(e.message) }
}

async function sosAction(s, action) {
  try {
    await elderly.sosAction(s.id, { action, handle_note: replyOp.value[s.id] || '已处理' })
    message.success(action === 'respond' ? '已确认响应' : '已结束')
    load()
  } catch (e) { message.error(e.message) }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title"><EIcon name="users" :size="18" /> 老年关怀管理</h2>
    <p class="page-sub">用药提醒审核 · 紧急联系人审核 · 紧急求助处理</p>

    <!-- 注意（2026-10-06 修）：取数失败必须在这里显形。
         原来五个请求全空 catch，页面用确定的"暂无求助记录"兜底 →
         网格员会据此判断"今天没有老人求助"，而真相是**取数失败**。 -->
    <div v-if="loadError" data-load-error
         style="border:2px solid var(--danger-solid);border-radius:var(--r-card);padding:10px;margin-bottom:10px;">
      <div style="color:var(--ink-danger);font-size:0.95rem;"><EIcon name="alert" :size="18" /> {{ loadError }}</div>
      <n-button size="small" style="margin-top:8px;" @click="load">重试</n-button>
    </div>

    <n-tabs v-model:value="tab" type="line">
      <!-- P4 健康记录：选老人 → 看血压/血糖与分级（只提醒，不下结论） -->
      <n-tab-pane name="vitals" tab="健康记录">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:10px;">
          <n-select :value="vitalUid" style="max-width:280px;" placeholder="选择老人"
                    :options="elders.map(e => ({ label: (e.name || ('老人#' + e.id)) + '（' + (e.community || '') + '）', value: e.id }))"
                    @update:value="loadVitals" />
          <span class="muted" style="font-size:0.85rem;">只做记录与提醒；具体用药听社区医生的。</span>
        </div>
        <div v-for="r in vitals" :key="r.id" class="card"
             :style="r.level === 'alert' ? 'border:2px solid #dc2626;' : (r.level === 'attention' ? 'border:2px solid #f59e0b;' : '')">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b v-if="r.kind === 'bp'">血压 {{ r.sys }}/{{ r.dia }} mmHg</b>
            <b v-else>血糖 {{ r.glucose }} mmol/L</b>
            <n-tag size="small" :type="r.level === 'normal' ? 'success' : (r.level === 'attention' ? 'warning' : 'error')">
              {{ VITAL_LEVEL[r.level] }}
            </n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            <EIcon name="clock" :size="18" /> {{ (r.measured_at || '').slice(0, 16) }}
            <template v-if="r.kind === 'glucose' && r.measure_when">
              · {{ r.measure_when === 'fasting' ? '空腹' : (r.measure_when === 'postprandial' ? '餐后' : '随机') }}
            </template>
            <template v-if="r.source === 'backfill'"> · 迁移自旧档案</template>
          </div>
          <div v-if="r.level !== 'normal'" class="muted" style="font-size:0.85rem;margin-top:4px;">{{ r.level_hint }}</div>
        </div>
        <n-empty v-if="!vitalUid" description="先选一位老人" />
        <n-empty v-else-if="vitals.length === 0" description="这位老人还没有健康记录" />
      </n-tab-pane>

      <!-- P3 安全闭环：久未互动 / 重点关注老人 -->
      <n-tab-pane name="focus" tab="重点关注老人">
        <div v-for="e in inactive" :key="e.user_id" class="card"
             style="border:2px solid #f59e0b;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ e.name || ('老人#' + e.user_id) }}</b>
            <n-tag size="small" type="warning">已 {{ e.days_inactive }} 天未互动</n-tag>
          </div>
          <div class="muted" style="font-size:0.9rem;margin-top:6px;">
            请电话或上门确认；系统已给网格员发了安全留意通知。
          </div>
        </div>
        <n-empty v-if="inactive.length === 0" description="暂无久未互动的老人" />
        <div class="muted" style="font-size:0.82rem;margin-top:10px;">
          口径：超过 24 小时没有互动（打开老年端 / 语音报修 / 用药打卡）即进入本列表，24 小时内不重复提醒。
        </div>
      </n-tab-pane>

      <!-- 用药审核 -->
      <n-tab-pane name="meds" tab="用药审核">
        <div v-for="m in meds" :key="m.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ m.drug_name }} <span class="muted" v-if="m.dosage">（{{ m.dosage }}）</span></b>
            <n-tag size="small" :type="m.status === '审核通过' ? 'success' : 'warning'">{{ m.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            {{ m.patient_name || '老人' }} · <EIcon name="clock" :size="18" /> {{ m.times }} · {{ m.repeat_rule }}
          </div>
          <div v-if="m.status === '待审核'" style="margin-top:10px;display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="auditOp[m.id]" placeholder="审核意见" size="small" style="max-width:200px;" />
            <n-button size="small" type="success" @click="auditMed(m, true)"><EIcon name="checkCircle" :size="18" /> 通过</n-button>
            <n-button size="small" type="warning" @click="auditMed(m, false)"><EIcon name="arrowLeft" :size="18" />  退回</n-button>
          </div>
        </div>
        <n-empty v-if="meds.length === 0" description="暂无用药提醒" />
      </n-tab-pane>

      <!-- 联系人审核 -->
      <n-tab-pane name="contacts" tab="联系人审核">
        <div v-for="c in contacts" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ c.name }}（{{ c.relation }}）</b>
            <n-tag size="small" :type="c.status === '审核通过' ? 'success' : 'warning'">{{ c.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;"><EIcon name="phone" :size="18" /> {{ c.phone }}</div>
          <div v-if="c.status === '待审核'" style="margin-top:10px;display:flex;gap:8px;">
            <n-button size="small" type="success" @click="auditContact(c, true)"><EIcon name="checkCircle" :size="18" /> 通过</n-button>
            <n-button size="small" type="warning" @click="auditContact(c, false)"><EIcon name="arrowLeft" :size="18" />  退回</n-button>
          </div>
        </div>
        <n-empty v-if="contacts.length === 0" description="暂无紧急联系人" />
      </n-tab-pane>

      <!-- SOS 处理 -->
      <n-tab-pane name="sos" tab="紧急求助">
        <div v-for="s in sosList" :key="s.id" class="card"
             :style="s.status === '求助中' ? 'border:2px solid #dc2626;' : ''">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ s.elder_name || s.target_name || ('老人#' + s.user_id) }}</b>
            <n-tag size="small" :type="s.status === '求助中' ? 'error' : 'default'">{{ s.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            <EIcon name="clock" :size="18" /> {{ (s.created_at || '').slice(0, 16) }}<template v-if="s.call_type"> · {{ s.call_type }}</template>
            <template v-if="s.handle_note"> · 处理：{{ s.handle_note }}</template>
            <template v-else-if="s.result"> · {{ s.result }}</template>
          </div>
          <div v-if="s.status === '求助中'" style="margin-top:10px;display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="replyOp[s.id]" placeholder="处理备注" size="small" style="max-width:200px;" />
            <n-button size="small" type="primary" @click="sosAction(s, 'respond')"><EIcon name="checkCircle" :size="18" /> 确认响应</n-button>
          </div>
          <div v-if="s.status === '已响应'" style="margin-top:10px;display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="replyOp[s.id]" placeholder="处理结果" size="small" style="max-width:200px;" />
            <n-button size="small" type="success" @click="sosAction(s, 'close')"><EIcon name="checkCircle" :size="18" /> 结束求助</n-button>
          </div>
        </div>
        <n-empty v-if="sosList.length === 0" description="暂无求助记录" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
