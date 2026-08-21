<script setup>
// 邻里议事：提案列表 + 投票
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { proposals } from '../../api'

const message = useMessage()
const list = ref([])
const loading = ref(true)

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
</script>

<template>
  <div class="page">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <h2 class="page-title">💡 邻里议事</h2>
        <p class="page-sub">提建议、看公示、投出你的一票（匿名）</p>
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
          <n-rate v-for="s in 5" :key="s" :count="1" :value="1" readonly style="display:none;" />
          <n-button v-for="s in 5" :key="'v' + s" size="small" :type="s === 5 ? 'primary' : 'default'"
                    @click="vote(p, s)">{{ s }}★</n-button>
        </div>
      </div>
      <n-empty v-if="!loading && list.length === 0" description="还没有提案" />
    </n-spin>
  </div>
</template>
