<script setup>
// 政策问答管理：知识库列表 + 待处理提问 + 统计与阈值
import { ref, onMounted } from 'vue'
import { useMessage } from 'naive-ui'
import { knowledge, qa } from '../../api'

const message = useMessage()
const kb = ref([])
const questions = ref([])
const stats = ref(null)
const threshold = ref(0.6)
const tab = ref('kb')

onMounted(async () => {
  try { kb.value = (await knowledge.list()) || [] } catch { /* 忽略 */ }
  try { questions.value = (await qa.questions()) || [] } catch { /* 忽略 */ }
  try {
    stats.value = (await qa.stats()) || null
  } catch { /* 忽略 */ }
  try {
    const t = await qa.getThreshold()
    if (t && t.threshold != null) threshold.value = Number(t.threshold)
  } catch { /* 忽略 */ }
})

async function transfer(q) {
  try {
    await qa.transfer(q.id)
    message.success('已转人工')
  } catch (e) {
    message.error(e.message)
  }
}

async function saveThreshold() {
  try {
    const r = await qa.setThreshold(threshold.value)
    message.success(`匹配阈值已更新为 ${r.threshold}`)
  } catch (e) {
    message.error(e.message)
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📖 政策问答管理</h2>
    <p class="page-sub">知识库维护 + 居民提问处理 + 运行统计与阈值配置</p>

    <n-tabs v-model:value="tab" type="line">
      <n-tab-pane name="kb" tab="知识库">
        <div v-for="k in kb" :key="k.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ k.title }}</b>
            <n-tag size="small" :type="k.status === '已发布' ? 'success' : 'default'">{{ k.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ k.category }} · {{ (k.updated_at || '').slice(0, 16) }}</div>
          <div style="margin-top:8px;font-size:0.9rem;">{{ k.plain_interpretation }}</div>
        </div>
        <n-empty v-if="kb.length === 0" description="暂无知识库条目" />
      </n-tab-pane>

      <n-tab-pane name="q" tab="提问处理">
        <div v-for="q in questions" :key="q.id" class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <b>{{ q.summary }}</b>
            <n-tag size="small" :type="q.status === '已转人工' || q.status === '超时未回复' ? 'warning' : 'default'">{{ q.status }}</n-tag>
          </div>
          <div class="muted" style="font-size:0.85rem;margin-top:4px;">{{ q.q_type }} · {{ (q.created_at || '').slice(0, 16) }}</div>
          <div v-if="q.status === '已转人工'" style="margin-top:8px;">
            <n-popconfirm @positive-click="transfer(q)">
              <template #trigger><n-button size="small" type="primary">🙋 转人工处理</n-button></template>
              确认转人工并通知负责人？
            </n-popconfirm>
          </div>
        </div>
        <n-empty v-if="questions.length === 0" description="暂无提问" />
      </n-tab-pane>

      <n-tab-pane name="stats" tab="统计与阈值">
        <div v-if="stats" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:16px;">
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;">{{ stats.total_questions }}</div>
            <div class="muted" style="font-size:0.85rem;">累计提问</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#4caf50;">{{ stats.auto_success }}</div>
            <div class="muted" style="font-size:0.85rem;">自动回答成功</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#f59e0b;">{{ stats.transferred }}</div>
            <div class="muted" style="font-size:0.85rem;">转人工</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#ef4444;">{{ stats.match_failed }}</div>
            <div class="muted" style="font-size:0.85rem;">匹配失败</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;color:#ef4444;">{{ stats.unhelpful }}</div>
            <div class="muted" style="font-size:0.85rem;">居民点无帮助</div>
          </div>
          <div class="card" style="text-align:center;">
            <div style="font-size:1.6rem;font-weight:800;">{{ stats.avg_reply_hours ?? '—' }}</div>
            <div class="muted" style="font-size:0.85rem;">平均回复(小时)</div>
          </div>
        </div>

        <div class="card" v-if="stats && stats.trend && stats.trend.length">
          <div style="font-weight:700;margin-bottom:8px;">📈 近 8 天提问趋势</div>
          <div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding-top:8px;">
            <div v-for="p in stats.trend" :key="p.day" style="flex:1;text-align:center;">
              <div style="font-size:0.8rem;color:#888;">{{ p.count }}</div>
              <div :style="{ height: Math.max(4, p.count * 18) + 'px', background: '#4caf50', borderRadius: '4px 4px 0 0' }"></div>
              <div style="font-size:0.7rem;color:#999;margin-top:4px;">{{ p.day.slice(5) }}</div>
            </div>
          </div>
        </div>

        <div class="card" v-if="stats && stats.expiring && stats.expiring.length">
          <div style="font-weight:700;margin-bottom:8px;">⏳ 7 天内到期知识条目</div>
          <div v-for="e in stats.expiring" :key="e.id" style="padding:4px 0;display:flex;justify-content:space-between;">
            <span>{{ e.title }}</span>
            <span class="muted" style="font-size:0.85rem;">到期 {{ e.expire_date }}</span>
          </div>
        </div>

        <div class="card" v-if="stats && stats.match_failed_list && stats.match_failed_list.length">
          <div style="font-weight:700;margin-bottom:8px;">❌ 匹配失败明细（留痕）</div>
          <div v-for="f in stats.match_failed_list" :key="f.id" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
            <b>{{ f.actor || '居民' }}</b>：{{ f.detail }}
            <span class="muted" style="font-size:0.8rem;"> · {{ (f.created_at || '').slice(0, 16) }}</span>
          </div>
        </div>

        <div class="card" v-if="stats && stats.unhelpful_list && stats.unhelpful_list.length">
          <div style="font-weight:700;margin-bottom:8px;">👎 居民点「无帮助」明细（留痕）</div>
          <div v-for="(f, i) in stats.unhelpful_list" :key="i" style="padding:6px 0;border-bottom:1px solid #f0f0f0;font-size:0.9rem;">
            <b>{{ f.actor || '居民' }}</b> 对「{{ f.target_title || '—' }}」：{{ f.detail }}
            <span class="muted" style="font-size:0.8rem;"> · {{ (f.created_at || '').slice(0, 16) }}</span>
          </div>
        </div>

        <div class="card">
          <div style="font-weight:700;margin-bottom:8px;">🎚️ 自动回答匹配阈值</div>
          <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
            <n-slider v-model:value="threshold" :min="0.1" :max="5" :step="0.1" style="max-width:320px;flex:1;" />
            <span style="min-width:60px;font-weight:700;">{{ threshold.toFixed(2) }}</span>
            <n-button type="primary" size="small" @click="saveThreshold">保存阈值</n-button>
          </div>
          <div class="muted" style="font-size:0.8rem;margin-top:6px;">数值越高要求越严格（相似度不足时自动回答判为失败并留痕转人工）。</div>
        </div>

        <n-empty v-if="!stats" description="暂无统计数据" />
      </n-tab-pane>
    </n-tabs>
  </div>
</template>
