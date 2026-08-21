<script setup>
// 老年端紧急联系人：列表（审核通过可拨打，拨打留痕确认）+ 新增 + 删除（最后一个拦截）
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'

const message = useMessage()
const list = ref([])
const showForm = ref(false)
const form = ref({ name: '', phone: '', relation: '家属' })
const callConfirm = ref(null)

onMounted(load)
async function load() {
  try { list.value = (await elderly.contacts()) || [] } catch { /* 忽略 */ }
}

async function add() {
  if (!form.value.name || form.value.phone.length !== 11) return message.warning('请填写姓名和 11 位手机号')
  try {
    await elderly.addContact(form.value)
    message.success('已提交，负责人审核通过后生效')
    form.value = { name: '', phone: '', relation: '家属' }
    showForm.value = false
    load()
  } catch (e) {
    message.error(e.message)
  }
}

async function remove(c) {
  try {
    await elderly.deleteContact(c.id)
    message.success('已删除')
    load()
  } catch (e) {
    message.error(e.message)
  }
}

async function confirmCall() {
  const c = callConfirm.value
  callConfirm.value = null
  try {
    await elderly.contactCall({ target_name: c.name, target_phone: c.phone })
    message.success(`正在呼叫 ${c.name}`)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">👨‍👩‍👧 紧急联系人</div>
    <p style="text-align:center;color:#6b7280;font-size:1.1rem;">紧急时可以一键呼叫他们（最多 3 个）</p>

    <div v-for="c in list" :key="c.id" class="card" style="font-size:1.2rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b>{{ c.name }}（{{ c.relation }}）</b>
        <div>
          <n-tag size="large" :type="c.status === '审核通过' ? 'success' : 'warning'">{{ c.status }}</n-tag>
        </div>
      </div>
      <div class="muted" style="font-size:1.05rem;margin-top:6px;">📱 {{ c.phone }}</div>
      <div v-if="c.status === '审核通过'" style="display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-top:10px;">
        <n-button type="primary" size="large" style="min-height:60px;font-size:1.2rem;" @click="callConfirm = c">📞 呼叫 {{ c.name }}</n-button>
        <n-popconfirm @positive-click="remove(c)">
          <template #trigger><n-button quaternary type="error" size="large" style="min-height:60px;">🗑️ 删除</n-button></template>
          删除后该联系人不再生效，确认删除？
        </n-popconfirm>
      </div>
      <div v-else style="margin-top:10px;">
        <n-popconfirm @positive-click="remove(c)">
          <template #trigger><n-button quaternary type="error" size="large" block>🗑️ 删除（待审核）</n-button></template>
          确认删除该联系人？
        </n-popconfirm>
      </div>
    </div>
    <n-empty v-if="list.length === 0" description="还没有紧急联系人" style="font-size:1.1rem;" />

    <n-button v-if="!showForm" type="primary" block size="large" style="margin-top:14px;min-height:64px;font-size:1.3rem;"
              @click="showForm = true">➕ 添加联系人</n-button>

    <div v-if="showForm" class="card" style="margin-top:12px;">
      <n-input v-model:value="form.name" placeholder="联系人姓名" size="large" style="font-size:1.2rem;" />
      <n-input v-model:value="form.phone" placeholder="11 位手机号" size="large" style="margin-top:10px;" />
      <n-input v-model:value="form.relation" placeholder="与您的关系（如：儿子/女儿）" size="large" style="margin-top:10px;" />
      <n-button type="primary" block size="large" style="margin-top:12px;min-height:60px;" @click="add">📨 提交（待审核）</n-button>
    </div>

    <!-- 拨打确认（10 秒超时） -->
    <n-modal :show="!!callConfirm" preset="dialog" type="warning" title="确认拨打？"
             :content="callConfirm ? `将呼叫 ${callConfirm.name}（${callConfirm.phone}），拨打将留痕记录` : ''"
             positive-text="确认拨打" negative-text="取消"
             @positive-click="confirmCall" @negative-click="callConfirm = null" />
  </div>
</template>
