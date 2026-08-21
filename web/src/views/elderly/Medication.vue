<script setup>
// 老年端用药提醒：列表 + 新增
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'

const message = useMessage()
const list = ref([])
const showForm = ref(false)
const form = ref({ drug_name: '', dosage: '', times: '08:00', repeat_rule: '每天', start_date: '', end_date: '' })

onMounted(load)
async function load() {
  try { list.value = (await elderly.medications()) || [] } catch { /* 忽略 */ }
}

async function add() {
  if (!form.value.drug_name) return message.warning('请填写药品名称')
  try {
    await elderly.createMedication(form.value)
    message.success('已提交，负责人审核通过后生效')
    form.value = { drug_name: '', dosage: '', times: '08:00', repeat_rule: '每天', start_date: '', end_date: '' }
    showForm.value = false
    load()
  } catch (e) {
    message.error(e.message)
  }
}

async function toggle(m, action) {
  try {
    await elderly.toggleMedication(m.id, action)
    message.success(action === 'pause' ? '已暂停（暂停期间不播报）' : '已恢复播报')
    load()
  } catch (e) {
    message.error(e.message)
  }
}

// 修改并重新提交审核（审核期间原规则继续播报）
const editTarget = ref(null)
function startEdit(m) {
  editTarget.value = m
  form.value = {
    drug_name: m.drug_name || '', dosage: m.dosage || '', times: m.times || '08:00',
    repeat_rule: m.repeat_rule || '每天', start_date: m.start_date || '', end_date: m.end_date || '',
  }
  showForm.value = true
}
async function saveEdit() {
  if (!form.value.drug_name) return message.warning('请填写药品名称')
  try {
    await elderly.modifyMedication(editTarget.value.id, form.value)
    message.success('修改已提交，负责人重新审核；审核期间原规则继续播报')
    editTarget.value = null
    form.value = { drug_name: '', dosage: '', times: '08:00', repeat_rule: '每天', start_date: '', end_date: '' }
    showForm.value = false
    load()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">💊 用药提醒</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">到点会语音提醒您吃药</p>

    <div v-for="m in list" :key="m.id" class="card" style="font-size:1.2rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b>{{ m.drug_name }} <span class="muted" v-if="m.dosage">（{{ m.dosage }}）</span></b>
        <div>
          <n-tag size="large" :type="m.status === '审核通过' ? 'success' : m.status === '已暂停' ? 'default' : 'warning'">{{ m.status }}</n-tag>
          <n-button v-if="m.status === '审核通过'" size="small" style="margin-left:8px;" @click="toggle(m, 'pause')">⏸️ 暂停</n-button>
          <n-button v-if="m.status === '已暂停'" size="small" type="primary" style="margin-left:8px;" @click="toggle(m, 'resume')">▶️ 恢复</n-button>
          <n-button v-if="['审核通过', '已暂停', '审核不通过'].includes(m.status)" size="small" style="margin-left:8px;" @click="startEdit(m)">✏️ 修改</n-button>
        </div>
      </div>
      <div class="muted" style="font-size:1.05rem;margin-top:6px;">⏰ {{ m.times }} · {{ m.repeat_rule }}</div>
      <div v-if="m.audit_opinion" class="muted" style="font-size:0.95rem;margin-top:4px;">审核意见：{{ m.audit_opinion }}</div>
    </div>
    <n-empty v-if="list.length === 0" description="还没有用药提醒" style="font-size:1.1rem;" />

    <n-button v-if="!showForm" type="primary" block size="large" style="margin-top:14px;min-height:64px;font-size:1.3rem;"
              @click="showForm = true">➕ 添加用药提醒</n-button>

    <div v-if="showForm" class="card" style="margin-top:12px;">
      <div v-if="editTarget" style="font-weight:700;font-size:1.1rem;margin-bottom:8px;">✏️ 修改：{{ editTarget.drug_name }}（提交后重新审核，审核期间原规则继续播报）</div>
      <n-input v-model:value="form.drug_name" placeholder="药品名称（如：降压药）" size="large" style="font-size:1.2rem;" />
      <n-input v-model:value="form.dosage" placeholder="剂量（如：1片）" size="large" style="margin-top:10px;" />
      <n-input v-model:value="form.times" placeholder="时间，逗号分隔（如：08:00,20:00）" size="large" style="margin-top:10px;" />
      <n-input v-model:value="form.start_date" placeholder="开始日期（如：2026-08-21）" size="large" style="margin-top:10px;" />
      <n-input v-model:value="form.end_date" placeholder="结束日期（如：2026-12-31）" size="large" style="margin-top:10px;" />
      <n-button v-if="editTarget" type="primary" block size="large" style="margin-top:12px;min-height:60px;" @click="saveEdit">📨 提交修改（待重新审核）</n-button>
      <n-button v-else type="primary" block size="large" style="margin-top:12px;min-height:60px;" @click="add">📨 提交（待审核）</n-button>
    </div>
  </div>
</template>
