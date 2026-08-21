<script setup>
// 提案管理：审核/决定执行/转执行/执行结果/下架/关闭/改类别/看手机号/提醒确认/延票/负责人投票
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { proposals } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const op = ref({}) // { [id]: { opinion, reason, dept, result, cat, phone, closeReason, downReason, score } }

const CATS = ['公共设施', '环境卫生', '文化活动', '安全治理', '其他']
const DEPTS = ['物业维修班', '环境卫生组', '安全治理组', '文化活动组', '社区服务中心', '综合办公室']

async function load() {
  loading.value = true
  try { list.value = (await proposals.list()) || [] } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

function opOf(p) {
  if (!op.value[p.id]) op.value[p.id] = {}
  return op.value[p.id]
}

async function act(p, data, okMsg) {
  try {
    await proposals.action(p.id, data)
    message.success(okMsg || '操作成功')
    load()
  } catch (e) {
    message.error(e.message)
  }
}

async function viewPhone(p) {
  try {
    const r = await proposals.action(p.id, { action: 'view_phone' })
    message.info(`完整手机号（已留痕）：${r.phone}`)
  } catch (e) {
    message.error(e.message)
  }
}

async function vote(p, score) {
  try {
    await proposals.vote(p.id, score)
    message.success('投票成功（匿名，一票制）')
    load()
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">💡 提案管理</h2>
    <p class="page-sub">共 {{ list.length }} 条提案 · 公开方式由提案人本人确认，负责人不能代替</p>

    <n-spin :show="loading">
      <div v-for="p in list" :key="p.id" class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b>{{ p.title }}</b>
          <n-tag size="small">{{ p.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ p.category }} · {{ p.is_public ? '公开' : '私有' }} · 提案人 {{ p.reporter_name || '—' }}
          <span v-if="p.reopen_count"> · 已重开 {{ p.reopen_count }} 次</span>
        </div>

        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <!-- 审核（意见必填，退回必须写） -->
          <template v-if="['待审核', '退回修改'].includes(p.status)">
            <n-input v-model:value="opOf(p).opinion" placeholder="审核意见（退回必填）" size="small" style="max-width:240px;" />
            <n-button size="small" type="success" @click="act(p, { action: 'audit', approve: true, opinion: opOf(p).opinion || '同意' }, '审核通过')">✅ 通过</n-button>
            <n-button size="small" type="warning" @click="act(p, { action: 'audit', approve: false, opinion: opOf(p).opinion || '请补充' }, '已退回')">↩️ 退回</n-button>
          </template>
          <!-- 待确认公示/私有：提醒提案人确认（负责人不能代替确认） -->
          <template v-if="p.status === '待确认公示/私有'">
            <span class="muted" style="font-size:0.85rem;">等待提案人确认公开/私有</span>
            <n-popconfirm @positive-click="act(p, { action: 'remind' }, '已提醒提案人确认')">
              <template #trigger><n-button size="small">🔔 提醒确认</n-button></template>
              发送提醒给提案人？
            </n-popconfirm>
          </template>
          <!-- 决定执行 -->
          <template v-if="p.status === '待执行'">
            <n-input v-model:value="opOf(p).reason" placeholder="决定理由（选填）" size="small" style="max-width:220px;" />
            <n-popconfirm @positive-click="act(p, { action: 'decide', approve: true, reason: opOf(p).reason || '同意执行' }, '已决定执行')">
              <template #trigger><n-button size="small" type="success">✅ 决定执行</n-button></template>
              同意执行该提案？
            </n-popconfirm>
            <n-popconfirm @positive-click="act(p, { action: 'decide', approve: false, reason: opOf(p).reason || '暂不执行' }, '已决定不执行')">
              <template #trigger><n-button size="small" type="warning">🚫 不执行</n-button></template>
              决定不执行？
            </n-popconfirm>
            <n-select v-model:value="opOf(p).dept" :options="DEPTS.map(v=>({label:v,value:v}))" size="small" style="width:150px;" placeholder="转执行部门" />
            <n-popconfirm @positive-click="act(p, { action: 'execute', dept: opOf(p).dept || '物业维修班' }, '已转部门执行')">
              <template #trigger><n-button size="small" type="info">🔨 转执行</n-button></template>
              转交执行部门？
            </n-popconfirm>
          </template>
          <!-- 执行中 → 填写执行结果 -->
          <template v-if="p.status === '执行中'">
            <n-input v-model:value="opOf(p).result" placeholder="执行结果（必填）" size="small" style="max-width:280px;" />
            <n-popconfirm @positive-click="act(p, { action: 'resolve', result: opOf(p).result || '已执行完成' }, '已提交执行结果，等待提案人反馈')">
              <template #trigger><n-button size="small" type="primary">📋 提交执行结果</n-button></template>
              提交执行结果并转「待提案人反馈」？
            </n-popconfirm>
          </template>
          <!-- 重新执行处理 -->
          <template v-if="p.status === '重新执行'">
            <n-popconfirm @positive-click="act(p, { action: 'reopen', close: false, reason: '继续执行' }, '已继续重新执行')">
              <template #trigger><n-button size="small" type="info">🔁 继续执行</n-button></template>
              继续重新执行？
            </n-popconfirm>
          </template>
          <!-- 公示中：负责人可投票（一票制匿名）+ 延票 -->
          <template v-if="p.status === '公示中'">
            <span class="muted" style="font-size:0.85rem;">评分（负责人也可投，一票制）：</span>
            <n-button v-for="s in 5" :key="'v' + s" size="small" :type="s === 5 ? 'primary' : 'default'" @click="vote(p, s)">{{ s }}★</n-button>
            <n-popconfirm @positive-click="act(p, { action: 'extend_voting', minutes: 1440 }, '已顺延 1 天公示期')">
              <template #trigger><n-button size="small" quaternary>⏱️ 延票 1 天</n-button></template>
              投票异常时顺延公示期 1 天？
            </n-popconfirm>
          </template>
          <!-- 负责人能力：改类别 / 看完整手机号（二次确认留痕） -->
          <template v-if="!['已完成'].includes(p.status)">
            <n-select v-model:value="opOf(p).cat" :options="CATS.map(v=>({label:v,value:v}))" size="small" style="width:130px;" placeholder="改类别" />
            <n-button size="small" @click="act(p, { action: 'update_category', category: opOf(p).cat }, '类别已修改（留痕）')">🗂️ 改类别</n-button>
            <n-popconfirm @positive-click="viewPhone(p)">
              <template #trigger><n-button size="small" quaternary>📞 看完整手机号</n-button></template>
              查看提案人完整手机号将留痕，确认查看？
            </n-popconfirm>
          </template>
          <!-- 违规下架 / 特殊情况关闭（原因必填 + 二次确认） -->
          <template v-if="!['已完成', '已下架', '已关闭'].includes(p.status)">
            <n-input v-model:value="opOf(p).closeReason" placeholder="关闭原因（必填，留痕）" size="small" style="max-width:220px;" />
            <n-popconfirm @positive-click="act(p, { action: 'close', reason: opOf(p).closeReason || '特殊情况关闭' }, '已关闭（留痕）')">
              <template #trigger><n-button size="small" quaternary type="error">🚫 特殊情况关闭</n-button></template>
              确认关闭？将记录原因并留痕
            </n-popconfirm>
            <n-input v-model:value="opOf(p).downReason" placeholder="下架原因（必填，留痕）" size="small" style="max-width:220px;" />
            <n-popconfirm @positive-click="act(p, { action: 'take_down', reason: opOf(p).downReason || '违规下架' }, '已下架（留痕）')">
              <template #trigger><n-button size="small" quaternary type="error">📛 违规下架</n-button></template>
              确认违规下架？将记录原因并留痕
            </n-popconfirm>
          </template>
        </div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="暂无提案" />
    </n-spin>
  </div>
</template>
