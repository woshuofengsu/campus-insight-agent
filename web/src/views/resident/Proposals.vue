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

async function load() {
  loading.value = true
  try { list.value = (await proposals.list()) || [] } catch (e) { message.error(e.message) }
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
          <b>{{ p.title }}</b>
          <n-tag size="small" :type="p.status === '公示中' ? 'success' : 'default'">{{ p.status }}</n-tag>
        </div>
        <div class="muted" style="font-size:0.85rem;margin-top:6px;">
          {{ p.category }} · {{ p.is_public ? '公开' : '私有' }} · 提案人 {{ p.reporter_name || '—' }}
        </div>
        <div v-if="p.status === '公示中'" style="margin-top:10px;display:flex;gap:6px;align-items:center;">
          <span class="muted" style="font-size:0.85rem;">评分（1-5）：</span>
          <n-button v-for="s in 5" :key="'v' + s" size="small" :type="s === 5 ? 'primary' : 'default'"
                    @click="vote(p, s)">{{ s }}★</n-button>
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
  </div>
</template>
