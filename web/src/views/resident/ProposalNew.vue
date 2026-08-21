<script setup>
// 提交提案（附件上传 + 附件公开选项 + 楼栋 + 草稿保存/恢复）
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { proposals, upload } from '../../api'

const router = useRouter()
const message = useMessage()
const loading = ref(false)
const files = ref([])
const drafts = ref([])

const form = ref({
  title: '',
  description: '',
  category: '其他',
  is_public: 1,
  reporter_name: '',
  reporter_phone: '',
  community_building: '',
  attachment_public: 0,
  attachment: '[]',
  is_agent_report: false, agent_name: '', agent_phone: '', agent_relation: '',
})

const CATS = ['公共设施', '环境卫生', '文化活动', '安全治理', '其他']

onMounted(async () => {
  try { drafts.value = (await proposals.drafts()) || [] } catch { /* 忽略 */ }
})

function restoreDraft(d) {
  form.value.title = d.title || ''
  form.value.description = d.description || ''
  form.value.category = d.category || '其他'
  form.value.is_public = d.is_public
  form.value.reporter_name = d.reporter_name || ''
  form.value.reporter_phone = d.reporter_phone || ''
  form.value.attachment_public = d.attachment_public || 0
  message.success('已恢复草稿，可继续填写')
}

async function saveDraft() {
  try {
    await proposals.saveDraft(form.value)
    message.success('草稿已保存（7 天内可继续填写）')
  } catch (e) {
    message.error(e.message)
  }
}

const submit = async () => {
  if (!form.value.title || form.value.description.length < 10) {
    return message.warning('请填写标题和至少 10 字内容')
  }
  loading.value = true
  try {
    // 附件上传（jpg/png，单张≤5MB，最多3张）
    if (files.value.length) {
      const up = await upload(files.value.map((f) => f.file), 'proposals')
      form.value.attachment = JSON.stringify(up.paths || [])
    }
    const data = await proposals.create({
      ...form.value,
      is_agent_report: form.value.is_agent_report ? 1 : 0,
    })
    message.success(`提案已提交，编号 #${data.proposal_id}，状态：待审核`)
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

    <!-- 草稿恢复 -->
    <div v-if="drafts.length" class="card urgent-bg" style="margin-bottom:12px;">
      <b>📝 您有未完成的提案草稿</b>
      <div v-for="d in drafts" :key="d.id" style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
        <span>{{ d.title || '（未填标题）' }} <span class="muted">（{{ (d.updated_at || '').slice(0, 10) }}）</span></span>
        <div style="display:flex;gap:6px;">
          <n-button size="small" @click="restoreDraft(d)">继续填写</n-button>
        </div>
      </div>
    </div>

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
        <n-form-item label="所属楼栋（选填）">
          <n-input v-model:value="form.community_building" placeholder="比如：3号楼" />
        </n-form-item>
        <n-form-item label="提案人姓名">
          <n-input v-model:value="form.reporter_name" placeholder="选填，默认当前账号姓名" />
        </n-form-item>
        <n-form-item label="联系电话">
          <n-input v-model:value="form.reporter_phone" placeholder="11 位手机号" />
        </n-form-item>
        <n-checkbox v-model:checked="form.is_agent_report" style="margin-bottom:8px;">我是代报（帮家人/邻居提交）</n-checkbox>
        <template v-if="form.is_agent_report">
          <n-grid :cols="2" :x-gap="16">
            <n-form-item-gi label="代报人姓名">
              <n-input v-model:value="form.agent_name" />
            </n-form-item-gi>
            <n-form-item-gi label="代报人电话">
              <n-input v-model:value="form.agent_phone" />
            </n-form-item-gi>
          </n-grid>
          <n-form-item label="与提案人关系">
            <n-input v-model:value="form.agent_relation" placeholder="如：家人 / 邻居" />
          </n-form-item>
        </template>
        <n-form-item label="附件（选填，jpg/png，单张≤5MB，最多3张）">
          <n-upload v-model:file-list="files" accept="image/jpeg,image/png" :max="3"
                    list-type="image-card" :default-upload="false" />
        </n-form-item>
        <n-checkbox v-model:checked="form.attachment_public" :checked-value="1" :unchecked-value="0">
          附件是否公开（勾选后公示期其他居民可查看附件；负责人审核时可能因隐私改为不公开）
        </n-checkbox>
        <div style="display:flex;gap:8px;margin-top:16px;">
          <n-button type="primary" block size="large" :loading="loading" @click="submit">📨 提交提案</n-button>
          <n-button size="large" @click="saveDraft">💾 存草稿</n-button>
        </div>
      </n-form>
    </div>
  </div>
</template>
