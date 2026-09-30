<script setup>
// 工单详情：完整字段 + 时间线 + 状态操作（居民视角：编辑一次/撤回/补充/反馈/重开/重提）
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'
import EIcon from '../../components/EIcon.vue'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const detail = ref(null)
const loading = ref(true)
const loadError = ref('')
const fbReason = ref('')
const supContent = ref('')
const editForm = ref(null)

onMounted(load)
async function load() {
  loading.value = true
  loadError.value = ''
  try { detail.value = await issues.detail(route.params.id) }
  catch (e) {
    // 只弹一个 3 秒就消失的 toast 不算"界面可理解"：老人/居民回头看屏幕时只剩空白页，
    // 分不清"没这条单"还是"页面坏了"。所以把原因**留在页面上**，并说明下一步能做什么
    // （首批八条浏览器旅程第 7 条：跨社区/他人工单被拒时必须看得懂）。
    detail.value = null
    loadError.value = e.message || '这条工单打不开'
    message.error(loadError.value)
  }
  finally { loading.value = false }
}

async function act(data, okMsg) {
  try {
    await issues.action(detail.value.id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) { message.error(e.message) }
}

function openEdit() {
  editForm.value = {
    title: detail.value.title, location: detail.value.location,
    description: detail.value.description, urgency: detail.value.urgency,
  }
}

async function submitEdit() {
  const f = editForm.value
  if (!f.title || !f.location || !f.description) return message.warning('请填写完整')
  try {
    await issues.action(detail.value.id, {
      action: 'edit', title: f.title, location: f.location,
      description: f.description, urgency: f.urgency,
    })
    message.success('已修改工单（仅一次机会，负责人将重新核实）')
    editForm.value = null
    load()
  } catch (e) { message.error(e.message) }
}
</script>

<template>
  <div class="page">
    <n-button quaternary size="small" style="margin-bottom:8px;" @click="router.back()">← 返回</n-button>
    <n-spin :show="loading">
      <!-- 打不开时给**留在页面上的**原因与出口（不是一闪而过的提示） -->
      <div v-if="loadError && !detail" class="card" data-load-error
           style="text-align:center;padding:22px;">
        <div style="font-size:1.05rem;font-weight:700;color:var(--ink-danger);"><EIcon name="ban" :size="18" /> {{ loadError }}</div>
        <div class="muted" style="margin-top:8px;font-size:0.9rem;">
          只能查看您自己报的工单；如果这不是您报的，返回列表看您自己的工单即可。
        </div>
        <div style="display:flex;gap:8px;justify-content:center;margin-top:12px;">
          <n-button type="primary" @click="load"><EIcon name="refresh" :size="18" /> 再试一次</n-button>
          <n-button @click="router.push('/resident/work-orders')">← 回到我的报修</n-button>
        </div>
      </div>
      <template v-if="detail">
        <h2 class="page-title"><EIcon name="wrench" :size="18" /> 工单 #{{ detail.id }} {{ detail.title }}</h2>
        <p class="page-sub">状态：<b>{{ detail.status }}</b> · {{ detail.issue_type }} · {{ detail.category }}</p>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="clipboard" :size="18" /> 工单信息</div>
          <div class="muted" style="line-height:2;font-size:0.95rem;">
            <EIcon name="pin" :size="18" /> 地址：{{ detail.location }}<br>
            <EIcon name="dot" :size="18" /> 紧急度：{{ detail.urgency }}<br>
            <EIcon name="user" :size="18" /> 报修人：{{ detail.reporter_name }} · {{ detail.reporter_phone }}<br>
            <template v-if="detail.assignee_name"><EIcon name="user-worker" :size="18" /> 维修人员：{{ detail.assignee_name }}<br></template>
            <EIcon name="clock" :size="18" /> 提交时间：{{ (detail.created_at || '').slice(0, 16) }}<br>
            <span v-if="detail.is_violation"><EIcon name="ban" :size="18" /> 违规标记<br></span>
            <span v-if="detail.non_community_responsibility"><EIcon name="construction" :size="18" /> 第三方施工（非社区责任）<br></span>
            <span v-if="detail.remaining_hours != null">⏱️ {{ detail.overdue ? `已超时 ${Math.abs(detail.remaining_hours).toFixed(1)}h` : `剩余 ${detail.remaining_hours.toFixed(1)}h` }}（{{ detail.urgency }}级时限 {{ detail.deadline_hours }}h）<br></span>
          </div>
          <div style="margin-top:8px;"><EIcon name="edit" :size="18" /> {{ detail.description }}</div>
          <div v-if="detail.resolve_note" style="background:var(--card-bg);border:1px solid var(--border);border-radius:8px;padding:8px;margin-top:10px;">
            <EIcon name="clipboard" :size="18" /> 处理结果：{{ detail.resolve_note }}
          </div>
        </div>

        <!-- 编辑工单（待审核，仅一次） -->
        <div v-if="detail.status === '待审核' && !editForm" class="card">
          <n-button type="primary" ghost @click="openEdit"><EIcon name="edit" :size="18" /> 修改工单内容（仅一次机会）</n-button>
        </div>
        <div v-if="editForm" class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="edit" :size="18" /> 修改工单</div>
          <n-input v-model:value="editForm.title" placeholder="标题" style="margin-bottom:8px;" />
          <n-input v-model:value="editForm.location" placeholder="地址" style="margin-bottom:8px;" />
          <n-input v-model:value="editForm.description" type="textarea" :rows="3" placeholder="问题描述" style="margin-bottom:8px;" />
          <n-select v-model:value="editForm.urgency" :options="['紧急','中等','一般','普通'].map(v=>({label:v,value:v}))" style="margin-bottom:8px;" />
          <div style="display:flex;gap:8px;">
            <n-button type="primary" @click="submitEdit"><EIcon name="checkCircle" :size="18" /> 保存修改</n-button>
            <n-button @click="editForm = null">取消</n-button>
          </div>
        </div>

        <!-- 操作 -->
        <div v-if="detail.status === '待居民反馈'" class="card">
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;">
            <n-button type="success" @click="act({ action: 'feedback', satisfied: true }, '已确认解决')"><EIcon name="checkCircle" :size="18" /> 满意，结单</n-button>
            <n-input v-model:value="fbReason" placeholder="不满意原因（选填）" size="small" style="max-width:220px;" />
            <n-button type="warning" @click="act({ action: 'feedback', satisfied: false, reason: fbReason || '还需处理' }, '已反馈')"><EIcon name="face-sad" :size="18" /> 不满意</n-button>
          </div>
        </div>
        <div v-if="detail.status === '待审核'" class="card">
          <n-button quaternary @click="act({ action: 'withdraw' }, '已撤回')">↩️ 撤回工单</n-button>
        </div>
        <div v-if="detail.status === '已撤回'" class="card">
          <n-button type="info" @click="act({ action: 'reopen' }, '已重新打开，待审核')"><EIcon name="unlock" :size="18" /> 重新打开（可修改一次）</n-button>
        </div>
        <div v-if="detail.status === '退回补充信息'" class="card">
          <n-button type="warning" @click="act({ action: 'resubmit' }, '已重新提交，待审核')"><EIcon name="send" :size="18" /> 重新提交</n-button>
        </div>
        <div v-if="['已审核待派单','已派单','处理中'].includes(detail.status)" class="card">
          <div style="display:flex;gap:8px;align-items:center;">
            <n-input v-model:value="supContent" placeholder="补充内容（必填）" size="small" style="max-width:260px;" />
            <n-button @click="supContent.trim() ? act({ action: 'supplement', opinion: supContent }, '补充已提交') : message.warning('请填写补充内容')"><EIcon name="edit" :size="18" /> 补充信息</n-button>
          </div>
        </div>

        <!-- 时间线 -->
        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;"><EIcon name="scroll" :size="18" /> 处理留痕</div>
          <div v-for="t in detail.timeline || []" :key="t.id" style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
            {{ (t.created_at || '').slice(0, 16) }} · {{ t.actor || '' }} · {{ t.action || '' }}
            <span v-if="t.detail" class="muted">（{{ t.detail }}）</span>
          </div>
          <n-empty v-if="!(detail.timeline || []).length" description="暂无留痕" style="font-size:0.85rem;padding:8px;" />
        </div>
      </template>
    </n-spin>
  </div>
</template>
