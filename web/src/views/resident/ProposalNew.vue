<script setup>
// 提交提案
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { proposals } from '../../api'

const router = useRouter()
const message = useMessage()
const loading = ref(false)

const form = ref({
  title: '',
  description: '',
  category: '其他',
  is_public: 1,
  reporter_name: '',
  reporter_phone: '',
})

const CATS = ['公共设施', '环境卫生', '文化活动', '安全治理', '其他']

const submit = async () => {
  if (!form.value.title || form.value.description.length < 10) {
    return message.warning('请填写标题和至少 10 字内容')
  }
  loading.value = true
  try {
    const data = await proposals.create(form.value)
    message.success(`提案已提交，编号 #${data.proposal_id}`)
    router.push('/resident/proposals')
  } catch (e) {
    message.error(e.message || '提交失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📝 提交提案</h2>
    <p class="page-sub">你的建议会进入社区议事流程：审核 → 公示 → 投票 → 执行</p>
    <div class="card">
      <n-form label-placement="top">
        <n-form-item label="提案标题（≤50字）">
          <n-input v-model:value="form.title" placeholder="比如：建议延长活动室开放时间" maxlength="50" show-count />
        </n-form-item>
        <n-form-item label="提案内容（10-1000字）">
          <n-input v-model:value="form.description" type="textarea" :rows="5"
                   placeholder="详细说明你的建议和理由" />
        </n-form-item>
        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi label="分类">
            <n-select v-model:value="form.category" :options="CATS.map(v=>({label:v,value:v}))" />
          </n-form-item-gi>
          <n-form-item-gi label="公开/私有">
            <n-select v-model:value="form.is_public"
                      :options="[{label:'公开（公示投票）',value:1},{label:'私有（不公示）',value:0}]" />
          </n-form-item-gi>
        </n-grid>
        <n-button type="primary" block size="large" :loading="loading" @click="submit">📨 提交提案</n-button>
      </n-form>
    </div>
  </div>
</template>
