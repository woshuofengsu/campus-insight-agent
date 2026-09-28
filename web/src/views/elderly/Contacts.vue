<script setup>
// 老年端紧急联系人：列表（审核通过可呼叫）+ 新增 + 删除（最后一个拦截）
//
// 诚实呼叫（v3 复核 §6-B2）：网页**不能**替手机说"正在呼叫"。
// 流程 = ① 请求后端"准备拨打"（号码由服务端解析，前端不传）→ ② 用 tel: 调起系统拨号盘
//        → ③ 把真实发生的事回填（已打开拨号盘 / 取消 / 失败）。
// 系统上没有"已接通"这个状态：网页拿不到通话结果，绝不编。
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { elderly } from '../../api'

const message = useMessage()
const list = ref([])
const showForm = ref(false)
const form = ref({ name: '', phone: '', relation: '家属' })
const callConfirm = ref(null)
// 拨号中：{ call_id, name, phone } —— 停在"已打开拨号盘"这一步，等老人自己说结果
const calling = ref(null)

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

/** 第一步+第二步一起做：后端准备拨打 → 调起拨号盘 → 回填"已打开拨号盘"。 */
async function confirmCall() {
  const c = callConfirm.value
  callConfirm.value = null
  let info
  try {
    // 只传 contact_id：号码与姓名由服务端解析（前端传号码 = 留痕可伪造）
    info = await elderly.contactCall({ contact_id: c.id })
  } catch (e) {
    message.error(e.message || '发起呼叫失败')
    return
  }
  calling.value = info
  try {
    window.location.href = info.tel || `tel:${info.phone}`
    // ⚠️ 这里只能记录"已经打开拨号盘"：是否拨出、是否接通**网页不知道**
    await elderly.contactOutcome(info.call_id, 'dialer_opened')
  } catch (e) {
    try { await elderly.contactOutcome(info.call_id, 'failed') } catch { /* 留痕失败不阻塞老人 */ }
    message.error('没能打开手机拨号，请手动拨打 ' + (info.phone || ''))
  }
}

/** 老人反馈：其实没拨出去 / 取消了 —— 如实记下来（不修就是"默认打过电话"）。 */
async function markCancelled() {
  const info = calling.value
  calling.value = null
  if (!info) return
  try {
    await elderly.contactOutcome(info.call_id, 'cancelled')
    message.info('已记录：这次没有拨出')
  } catch (e) {
    message.warning(e.message || '记录失败')
  }
}
</script>

<template>
  <div class="elderly-page">
    <div class="elderly-title">👨‍👩‍👧 紧急联系人</div>
    <p style="text-align:center;color:var(--muted);font-size:1.25rem;">紧急时可以一键呼叫他们（最多 3 个）</p>

    <!-- 拨号进行中：只承诺"已帮您打开手机拨号"，并给一个"没拨出去"的出口 -->
    <div v-if="calling" class="card" style="font-size:1.25rem;border:2px solid var(--primary);">
      <b>📱 已帮您打开手机拨号</b>
      <div style="margin-top:8px;">
        请在手机上按绿色按钮拨给 <b>{{ calling.name }}</b>（{{ calling.phone }}）。
      </div>
      <div class="muted" style="margin-top:8px;font-size:1.1rem;">
        手机是否接通，这个页面看不到，所以我们不会替您记成"已通话"。
      </div>
      <n-button block size="large" style="margin-top:12px;min-height:60px;font-size:1.2rem;"
                @click="markCancelled">我没拨出去 / 取消了</n-button>
    </div>

    <div v-for="c in list" :key="c.id" class="card" style="font-size:1.25rem;">
      <div style="display:flex;justify-content:space-between;align-items:center;">
        <b>{{ c.name }}（{{ c.relation }}）</b>
        <div>
          <n-tag size="large" :type="c.status === '审核通过' ? 'success' : 'warning'">{{ c.status }}</n-tag>
        </div>
      </div>
      <div class="muted" style="margin-top:6px;">📱 {{ c.phone }}</div>
      <div v-if="c.status === '审核通过'" style="display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-top:10px;">
        <n-button type="primary" size="large" style="min-height:60px;font-size:1.25rem;" @click="callConfirm = c">📞 呼叫 {{ c.name }}</n-button>
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
    <n-empty v-if="list.length === 0" description="还没有紧急联系人" style="font-size:1.25rem;" />

    <n-button v-if="!showForm" type="primary" block size="large" style="margin-top:14px;min-height:64px;font-size:1.3rem;"
              @click="showForm = true">➕ 添加联系人</n-button>

    <div v-if="showForm" class="card" style="margin-top:12px;">
      <n-input v-model:value="form.name" placeholder="联系人姓名" size="large" style="font-size:1.25rem;" />
      <n-input v-model:value="form.phone" placeholder="11 位手机号" size="large" style="margin-top:10px;" />
      <n-input v-model:value="form.relation" placeholder="与您的关系（如：儿子/女儿）" size="large" style="margin-top:10px;" />
      <n-button type="primary" block size="large" style="margin-top:12px;min-height:60px;" @click="add">📨 提交（待审核）</n-button>
    </div>

    <!-- 呼叫确认（10 秒超时） -->
    <n-modal :show="!!callConfirm" preset="dialog" type="warning" title="确认拨打？"
             :content="callConfirm ? `将打开手机拨号打给 ${callConfirm.name}（${callConfirm.phone}），并留痕记录` : ''"
             positive-text="确认拨打" negative-text="取消"
             @positive-click="confirmCall" @negative-click="callConfirm = null" />
  </div>
</template>
