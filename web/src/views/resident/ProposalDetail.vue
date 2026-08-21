<script setup>
// 提案详情：信息 + 投票统计 + 匿名议论 + 提案人反馈
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { proposals } from '../../api'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const p = ref(null)
const comments = ref([])
const commentText = ref('')
const fbReason = ref('')

onMounted(load)
async function load() {
  try {
    p.value = await proposals.detail(route.params.id)
    comments.value = await proposals.comments(route.params.id)
  } catch (e) { message.error(e.message) }
}

async function vote(score) {
  try { await proposals.vote(p.value.id, score); message.success('投票成功（匿名）'); load() }
  catch (e) { message.error(e.message) }
}

async function addComment() {
  const t = commentText.value.trim()
  if (!t) return message.warning('请输入议论内容')
  try { await proposals.addComment(p.value.id, { content: t }); commentText.value = ''; comments.value = await proposals.comments(p.value.id) }
  catch (e) { message.error(e.message) }
}

async function feedback(satisfied) {
  try {
    await proposals.action(p.value.id, { action: 'feedback', satisfied, reason: fbReason.value || '执行效果未达预期' })
    message.success('反馈已提交')
    load()
  } catch (e) { message.error(e.message) }
}

// 附件路径列表
function attachments() {
  try { return JSON.parse(p.value.attachment || '[]') } catch { return [] }
}

async function changeVis(isPublic) {
  try {
    await proposals.action(p.value.id, { action: 'change_visibility', is_public: isPublic })
    message.success('公开/私有已修改（仅一次机会）')
    load()
  } catch (e) { message.error(e.message) }
}
</script>

<template>
  <div class="page">
    <n-button quaternary size="small" style="margin-bottom:8px;" @click="router.back()">← 返回</n-button>
    <template v-if="p">
      <h2 class="page-title">💡 {{ p.title }}</h2>
      <p class="page-sub">{{ p.category }} · {{ p.is_public ? '公开' : '私有' }} · 状态 <b>{{ p.status }}</b></p>

      <div class="card">
        <div class="muted" style="line-height:2;">{{ p.description }}</div>
        <div v-if="p.community_building" class="muted" style="margin-top:6px;font-size:0.9rem;">🏠 所属楼栋：{{ p.community_building }}</div>
        <div v-if="p.vote_stats" class="muted" style="margin-top:6px;font-size:0.9rem;">
          🗳️ 投票：{{ p.vote_stats.vote_count || 0 }} 人 · 平均 {{ p.vote_stats.avg_score || '—' }} 分
        </div>
        <!-- 附件（本人或公开） -->
        <div v-if="attachments().length" style="margin-top:8px;">
          <div style="font-weight:700;font-size:0.9rem;margin-bottom:4px;">📎 附件（{{ p.attachment_public ? '公开' : '仅本人可见' }}）</div>
          <div v-for="(a, i) in attachments()" :key="i" style="display:inline-block;margin-right:8px;">
            <img :src="a" style="max-width:120px;max-height:120px;border-radius:6px;border:1px solid var(--border);" :alt="'附件' + (i + 1)" />
          </div>
        </div>
      </div>

      <!-- 我的提案：确认前/私有待执行时修改公开方式（7 天内一次机会） -->
      <div v-if="p.mine && ['待确认公示/私有', '待执行'].includes(p.status)" class="card">
        <div style="font-weight:700;margin-bottom:8px;">🔀 修改公开/私有（审核通过后 7 天内仅一次机会）</div>
        <div style="display:flex;gap:8px;">
          <n-button size="small" type="success" @click="changeVis(1)">🌐 改为公开</n-button>
          <n-button size="small" type="default" @click="changeVis(0)">🔒 改为私有</n-button>
        </div>
      </div>

      <!-- 投票 -->
      <div v-if="p.status === '公示中'" class="card">
        <div style="font-weight:700;margin-bottom:8px;">🗳️ 匿名评分（1-5 星）</div>
        <div style="display:flex;gap:6px;">
          <n-button v-for="s in 5" :key="s" size="small" :type="s === 5 ? 'primary' : 'default'" @click="vote(s)">{{ s }}★</n-button>
        </div>
      </div>

      <!-- 提案人反馈 -->
      <div v-if="p.status === '待提案人反馈'" class="card">
        <div style="font-weight:700;margin-bottom:8px;">📨 执行完成，请反馈满意度</div>
        <n-input v-model:value="fbReason" placeholder="不满意原因（可选）" size="small" style="margin-bottom:8px;" />
        <div style="display:flex;gap:8px;">
          <n-button type="success" @click="feedback(true)">✅ 满意</n-button>
          <n-button type="warning" @click="feedback(false)">😕 不满意</n-button>
        </div>
      </div>

      <!-- 匿名议论 -->
      <div v-if="['公示中','待执行','执行中','待提案人反馈','重新执行'].includes(p.status)" class="card">
        <div style="font-weight:700;margin-bottom:8px;">💬 议论（匿名）</div>
        <div v-for="c in comments" :key="c.id" style="padding:8px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
          <span style="color:var(--accent);font-weight:600;">{{ c.author }}</span>
          <span class="muted" style="margin-left:8px;font-size:0.75rem;">{{ c.created_at }}</span>
          <div style="margin-top:4px;">{{ c.content }}</div>
        </div>
        <n-empty v-if="comments.length === 0" description="还没有议论，来说两句" style="font-size:0.85rem;padding:8px;" />
        <div style="display:flex;gap:8px;margin-top:8px;">
          <n-input v-model:value="commentText" placeholder="匿名发表议论（≤500字）" maxlength="500" />
          <n-button size="small" type="primary" @click="addComment">发表</n-button>
        </div>
      </div>

      <!-- 时间线 -->
      <div class="card">
        <div style="font-weight:700;margin-bottom:8px;">📜 处理留痕</div>
        <div v-for="t in p.timeline || []" :key="t.id" style="padding:6px 0;border-bottom:1px solid var(--border);font-size:0.9rem;">
          {{ (t.created_at || '').slice(0, 16) }} · {{ t.actor || '' }} · {{ t.action || '' }}
        </div>
        <n-empty v-if="!(p.timeline || []).length" description="暂无留痕" style="font-size:0.85rem;padding:8px;" />
      </div>
    </template>
  </div>
</template>
