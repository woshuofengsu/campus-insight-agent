<script setup>
// 老年关怀管理（负责人）：用药审核 / 紧急联系人审核 / SOS 响应
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'

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

onMounted(load)

async function load() {
  try { meds.value = (await elderly.manageMeds()) || [] } catch { /* 忽略 */ }
  try { contacts.value = (await elderly.manageContacts()) || [] } catch { /* 忽略 */ }
  try { sosList.value = (await elderly.manageSos()) || [] } catch { /* 忽略 */ }
  try { inactive.value = (await elderly.manageInactive({ days: 1 })) || [] } catch { /* 忽略 */ }
  try { elders.value = (await elderly.manageElders()) || [] } catch { /* 忽略 */ }
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
    <h2 class="page-title">👴 老年关怀管理</h2>
    <p class="page-sub">用药提醒审核 · 紧急联系人审核 · 紧急求助处理</p>

    <n-tabs v-model:value="tab" type="line">
      <!-- P4 健康记录：选老人 → 看血压/血糖与分级（只提醒，不下结论） -->
      <n-tab-pane name="vitals" tab="🩺 健康记录">
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
            🕐 {{ (r.measured_at || '').slice(0, 16) }}
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
      <n-tab-pane name="focus" tab="👀 重点关注老人">
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
      <n-tab-pane name="meds" tab="💊 用药审核">
        <div v-for="m in meds" :key="m.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ m.drug_name }} <span class="muted" v-if="m.dosage">（{{ m.dosage }}）</span></b>
            <n-tag size="small" :type="m.status === '审核通过' ? 'success' : 'warning'">{{ m.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            {{ m.patient_name || '老人' }} · ⏰ {{ m.times }} · {{ m.repeat_rule }}
          </div>
          <div v-if="m.status === '待审核'" style="margin-top:10px;display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="auditOp[m.id]" placeholder="审核意见" size="small" style="max-width:200px;" />
            <n-button size="small" type="success" @click="auditMed(m, true)">✅ 通过</n-button>
            <n-button size="small" type="warning" @click="auditMed(m, false)">↩️ 退回</n-button>
          </div>
        </div>
        <n-empty v-if="meds.length === 0" description="暂无用药提醒" />
      </n-tab-pane>

      <!-- 联系人审核 -->
      <n-tab-pane name="contacts" tab="📞 联系人审核">
        <div v-for="c in contacts" :key="c.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ c.name }}（{{ c.relation }}）</b>
            <n-tag size="small" :type="c.status === '审核通过' ? 'success' : 'warning'">{{ c.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">📱 {{ c.phone }}</div>
          <div v-if="c.status === '待审核'" style="margin-top:10px;display:flex;gap:8px;">
            <n-button size="small" type="success" @click="auditContact(c, true)">✅ 通过</n-button>
            <n-button size="small" type="warning" @click="auditContact(c, false)">↩️ 退回</n-button>
          </div>
        </div>
        <n-empty v-if="contacts.length === 0" description="暂无紧急联系人" />
      </n-tab-pane>

      <!-- SOS 处理 -->
      <n-tab-pane name="sos" tab="🚨 紧急求助">
        <div v-for="s in sosList" :key="s.id" class="card"
             :style="s.status === '求助中' ? 'border:2px solid #dc2626;' : ''">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ s.elder_name || s.target_name || ('老人#' + s.user_id) }}</b>
            <n-tag size="small" :type="s.status === '求助中' ? 'error' : 'default'">{{ s.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            🕐 {{ (s.created_at || '').slice(0, 16) }}<template v-if="s.call_type"> · {{ s.call_type }}</template>
            <template v-if="s.handle_note"> · 处理：{{ s.handle_note }}</template>
            <template v-else-if="s.result"> · {{ s.result }}</template>
          </div>
          <div v-if="s.status === '求助中'" style="margin-top:10px;display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="replyOp[s.id]" placeholder="处理备注" size="small" style="max-width:200px;" />
            <n-button size="small" type="primary" @click="sosAction(s, 'respond')">✅ 确认响应</n-button>
          </div>
          <div v-if="s.status === '已响应'" style="margin-top:10px;display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="replyOp[s.id]" placeholder="处理结果" size="small" style="max-width:200px;" />
            <n-button size="small" type="success" @click="sosAction(s, 'close')">✅ 结束求助</n-button>
          </div>
        </div>
        <n-empty v-if="sosList.length === 0" description="暂无求助记录" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
