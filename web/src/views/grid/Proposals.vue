<script setup>
// 提案管理：审核/决定执行/转执行/执行结果/下架/关闭/改类别/看手机号/提醒确认/延票/负责人投票 + 详情/导出
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { proposals, exportApi } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const op = ref({}) // { [id]: { opinion, reason, dept, result, cat, phone, closeReason, downReason, score, attachOk } }
const detail = ref(null)

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

async function showDetail(p) {
  try { detail.value = await proposals.detail(p.id) } catch (e) { message.error(e.message) }
}

async function exportProposals() {
  try {
    const blob = await exportApi.proposals()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'proposals.csv'; a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    message.error(e.message)
  }
}

function atts(p) {
  try { return JSON.parse(p.attachment || '[]') } catch { return [] }
}
</script>

<template>
  <div class="page">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h2 class="page-title">💡 提案管理</h2>
      <n-button size="small" @click="exportProposals">⬇️ 导出</n-button>
    </div>
    <p class="page-sub">共 {{ list.length }} 条提案 · 公开方式由提案人本人确认，负责人不能代替</p>

    <n-spin :show="loading">
      <div v-for="p in list" :key="p.id" class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b style="cursor:pointer;" @click="showDetail(p)">{{ p.title }} ›</b>
          <n-tag size="small">{{ p.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ p.category }} · {{ p.is_public ? '公开' : '私有' }} · 提案人 {{ p.reporter_name || '—' }}
          <span v-if="p.reopen_count"> · 已重开 {{ p.reopen_count }} 次</span>
        </div>

        <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <!-- 审核（意见必填，退回必须写；附件公开审核） -->
          <template v-if="['待审核', '退回修改'].includes(p.status)">
            <n-input v-model:value="opOf(p).opinion" placeholder="审核意见（退回必填）" size="small" style="max-width:240px;" />
            <n-checkbox v-if="p.attachment_public" v-model:checked="opOf(p).attachOk" :checked-value="1" :unchecked-value="0" size="small">附件含隐私→不公开</n-checkbox>
            <n-button size="small" type="success" @click="act(p, { action: 'audit', approve: true, opinion: opOf(p).opinion || '同意', attachment_public_ok: opOf(p).attachOk ? false : true }, '审核通过')">✅ 通过</n-button>
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

    <!-- 提案详情弹窗（完整字段 + 留痕） -->
    <n-modal :show="!!detail" @update:show="(v) => { if (!v) detail = null }" preset="card" style="width:640px;" :title="detail ? detail.title : ''">
      <template v-if="detail">
        <div style="margin-bottom:8px;">
          <n-tag size="small">{{ detail.status }}</n-tag>
          <n-tag size="small" style="margin-left:6px;">{{ detail.category }}</n-tag>
          <span class="muted" style="margin-left:8px;font-size:0.8rem;">{{ detail.is_public ? '公开' : '私有' }} · 提案人 {{ detail.reporter_name || '—' }} · {{ detail.reporter_phone || '' }}</span>
        </div>
        <div v-if="detail.community_building" class="muted" style="font-size:0.85rem;">🏠 楼栋：{{ detail.community_building }}</div>
        <div v-if="detail.is_agent_report && detail.agent_name" class="muted" style="font-size:0.85rem;">🙋 代报：{{ detail.agent_name }}（{{ detail.agent_relation }}）</div>
        <div style="font-size:0.95rem;line-height:1.8;margin-top:8px;white-space:pre-wrap;">{{ detail.description }}</div>
        <div v-if="atts(detail).length" style="margin-top:8px;">
          <div style="font-weight:700;font-size:0.9rem;">📎 附件（{{ detail.attachment_public ? '公开' : '不公开' }}）</div>
          <div v-for="(a, i) in atts(detail)" :key="i" style="display:inline-block;margin-right:8px;">
            <img :src="a" style="max-width:120px;max-height:120px;border-radius:6px;border:1px solid var(--border);" />
          </div>
        </div>
        <div v-if="detail.vote_stats" style="margin-top:8px;font-size:0.9rem;" class="muted">
          🗳️ 投票 {{ detail.vote_stats.vote_count || 0 }} 人 · 平均 {{ detail.vote_stats.avg_score || '—' }} 分 · 排名 {{ detail.vote_stats.rank || '—' }}
        </div>
        <div v-if="detail.audit_opinion" style="margin-top:8px;font-size:0.9rem;">审核意见：{{ detail.audit_opinion }}</div>
        <div v-if="detail.execution_result" style="margin-top:8px;font-size:0.9rem;">执行结果：{{ detail.execution_result }}</div>
        <div style="margin-top:12px;">
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:4px;">📜 处理留痕</div>
          <div v-for="t in detail.timeline || []" :key="t.id" style="padding:4px 0;border-bottom:1px solid var(--border);font-size:0.85rem;">
            {{ (t.created_at || '').slice(0, 16) }} · {{ t.actor || '' }} · {{ t.action || '' }}
            <span v-if="t.detail" class="muted">（{{ t.detail }}）</span>
          </div>
          <n-empty v-if="!(detail.timeline || []).length" description="暂无留痕" style="font-size:0.8rem;padding:4px;" />
        </div>
      </template>
    </n-modal>
  </div>
</template>
