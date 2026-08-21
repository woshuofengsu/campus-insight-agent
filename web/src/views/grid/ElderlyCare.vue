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
const auditOp = ref({}) // 审核意见
const replyOp = ref({}) // SOS 处理备注

onMounted(load)

async function load() {
  try { meds.value = (await elderly.manageMeds()) || [] } catch { /* 忽略 */ }
  try { contacts.value = (await elderly.manageContacts()) || [] } catch { /* 忽略 */ }
  try { sosList.value = (await elderly.manageSos()) || [] } catch { /* 忽略 */ }
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
            <b>{{ s.target_name || ('老人#' + s.user_id) }}</b>
            <n-tag size="small" :type="s.status === '求助中' ? 'error' : 'default'">{{ s.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">
            🕐 {{ (s.created_at || '').slice(0, 16) }} · {{ s.content || s.description || '' }}
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
