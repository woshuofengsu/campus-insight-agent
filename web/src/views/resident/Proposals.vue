<script setup>
// 邻里议事：提案列表 + 投票 + 公示期匿名议论
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { proposals } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)
const commentInput = ref({}) // pid -> 输入内容
const commentList = ref({}) // pid -> 议论列表
const votedIds = ref([])
const editModal = ref(null) // 退回/撤回后编辑重提

const CATS_EDIT = ['公共设施', '环境卫生', '文化活动', '安全治理', '其他']

async function load() {
  loading.value = true
  try {
    list.value = (await proposals.list()) || []
    votedIds.value = list.value.filter((p) => p.has_voted).map((p) => p.id)
  } catch (e) { message.error(e.message) }
  finally { loading.value = false }
}
onMounted(load)

async function vote(p, score) {
  try {
    await proposals.vote(p.id, score)
    message.success('投票成功（匿名）')
    load()
  } catch (e) {
    message.error(e.message)
  }
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

// 退回修改 / 已撤回：编辑后重新提交（可修改一次）
function openEdit(p) {
  editModal.value = { id: p.id, title: p.title, description: '', category: p.category }
  try {
    const full = JSON.parse(localStorage.getItem('ci_prop_' + p.id) || '{}')
    editModal.value.description = full.description || ''
  } catch { /* 忽略 */ }
}

async function submitEdit() {
  const e = editModal.value
  if (!e.title || !e.description || e.description.length < 10) {
    return message.warning('请填写标题和至少 10 字内容')
  }
  try {
    await proposals.action(e.id, {
      action: 'resubmit',
      opinion: e.title,
      result: e.description,
      category: e.category,
    })
    message.success('已修改并重新提交，等待审核')
    editModal.value = null
    load()
  } catch (err) {
    message.error(err.message)
  }
}

// 展开议论（匿名可见）
async function toggleComments(p) {
  commentList.value[p.id] = null
  try {
    commentList.value[p.id] = await proposals.comments(p.id)
  } catch (e) {
    message.error(e.message)
  }
}

async function addComment(p) {
  const text = (commentInput.value[p.id] || '').trim()
  if (!text) return message.warning('请输入议论内容')
  try {
    await proposals.addComment(p.id, { content: text })
    message.success('议论已发布（匿名）')
    commentInput.value[p.id] = ''
    commentList.value[p.id] = await proposals.comments(p.id)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <h2 class="page-title">💡 邻里议事</h2>
        <p class="page-sub">提建议、看公示、投出你的一票（匿名），公示期可匿名议论</p>
      </div>
      <n-button type="primary" @click="$router.push('/resident/proposals/new')">+ 提交提案</n-button>
    </div>

    <n-spin :show="loading">
      <div v-for="p in list" :key="p.id" class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;">
          <b style="cursor:pointer;" @click="$router.push('/resident/proposals/' + p.id)">{{ p.title }} ›</b>
          <n-tag size="small" :type="p.status === '公示中' ? 'success' : 'default'">{{ p.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ p.category }} · {{ p.is_public ? '公开' : '私有' }} · 提案人 {{ p.reporter_name || '—' }}
          <n-tag v-if="p.mine" size="tiny" type="info" style="margin-left:6px;">我的提案</n-tag>
          <span v-if="p.status === '公示中'" style="margin-left:8px;">
            <n-tag size="tiny" type="warning" v-if="p.remaining_days != null">剩 {{ p.remaining_days }} 天</n-tag>
            <n-tag size="tiny" v-if="p.vote_count">🗳️ {{ p.vote_count }} 人 · {{ p.avg_score }} 分</n-tag>
          </span>
        </div>

        <!-- 我的提案：待审核撤回 / 已撤回重开 / 退回修改重提 / 待确认公示私有 -->
        <div v-if="p.mine" style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
          <n-button v-if="p.status === '待审核'" size="small" quaternary @click="act(p, { action: 'withdraw' }, '已撤回')">↩️ 撤回</n-button>
          <n-button v-if="p.status === '已撤回'" size="small" type="info" @click="act(p, { action: 'reopen_mine' }, '已重新打开，待审核')">🔓 重新打开</n-button>
          <n-button v-if="p.status === '退回修改'" size="small" type="warning" @click="openEdit(p)">📝 修改后重新提交</n-button>
          <template v-if="p.status === '待确认公示/私有'">
            <span class="muted" style="font-size:0.85rem;">请确认公开方式：</span>
            <n-button size="small" type="success" @click="act(p, { action: 'confirm', is_public: 1 }, '已确认公开，进入公示')">🌐 确认公开</n-button>
            <n-button size="small" type="default" @click="act(p, { action: 'confirm', is_public: 0 }, '已确认私有')">🔒 确认私有</n-button>
          </template>
        </div>

        <div v-if="p.status === '公示中'" style="margin-top:10px;display:flex;gap:6px;align-items:center;">
          <template v-if="p.mine">
            <span class="muted" style="font-size:0.85rem;">这是您自己的提案，不能给自己投票</span>
          </template>
          <template v-else>
            <span class="muted" style="font-size:0.85rem;">评分（1-5，匿名一票制）：</span>
            <n-button v-for="s in 5" :key="'v' + s" size="small" :type="s === 5 ? 'primary' : 'default'"
                      :disabled="votedIds.includes(p.id)" @click="vote(p, s)">{{ s }}★</n-button>
            <span v-if="votedIds.includes(p.id)" class="muted" style="font-size:0.85rem;">您已评分，不可修改</span>
          </template>
        </div>

        <!-- 公示期匿名议论 -->
        <div v-if="p.status === '公示中'" style="margin-top:12px;border-top:1px solid var(--border);padding-top:10px;">
          <n-button size="small" quaternary @click="toggleComments(p)">💬 议论（{{ commentList[p.id] ? commentList[p.id].length : '展开' }}）</n-button>
          <template v-if="commentList[p.id]">
            <div v-for="c in commentList[p.id]" :key="c.id"
                 style="padding:8px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
              <span style="color:var(--accent);font-weight:600;">{{ c.author }}</span>
              <span class="muted" style="margin-left:8px;font-size:0.75rem;">{{ c.created_at }}</span>
              <div style="margin-top:4px;">{{ c.content }}</div>
            </div>
            <n-empty v-if="commentList[p.id].length === 0" description="还没有议论，来说两句" style="font-size:0.85rem;padding:8px;" />
            <div style="display:flex;gap:8px;margin-top:8px;">
              <n-input v-model:value="commentInput[p.id]" placeholder="匿名发表议论（≤500字）" maxlength="500" />
              <n-button size="small" type="primary" @click="addComment(p)">发表</n-button>
            </div>
          </template>
        </div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="还没有提案" />
    </n-spin>

    <!-- 编辑重提弹窗 -->
    <n-modal :show="!!editModal" @update:show="(v) => { if (!v) editModal = null }" preset="card" style="width:560px;" title="✏️ 修改后重新提交（可修改一次）">
      <template v-if="editModal">
        <n-form label-placement="top">
          <n-form-item label="标题">
            <n-input v-model:value="editModal.title" maxlength="50" />
          </n-form-item>
          <n-form-item label="内容（10-1000字）">
            <n-input v-model:value="editModal.description" type="textarea" :rows="4" />
          </n-form-item>
          <n-form-item label="分类">
            <n-select v-model:value="editModal.category" :options="CATS_EDIT.map(v=>({label:v,value:v}))" />
          </n-form-item>
          <div style="text-align:right;">
            <n-button type="primary" @click="submitEdit">📤 重新提交（待审核）</n-button>
          </div>
        </n-form>
      </template>
    </n-modal>
  </div>
</template>
