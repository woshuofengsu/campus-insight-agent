<script setup>
// 提交报修（含现场照片上传 + 代报 + 草稿恢复）
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues, upload } from '../../api'

const router = useRouter()
const message = useMessage()
const loading = ref(false)

const form = ref({
  title: '',
  category: '公共设施',
  issue_type: '室内',
  location: '',
  description: '',
  urgency: '一般',
  reporter_name: '',
  reporter_phone: '',
  photo_before: '[]',
  is_agent_report: false, agent_name: '', agent_phone: '', agent_relation: '',
})
const files = ref([]) // 上传的文件列表（n-upload）
const drafts = ref([])

onMounted(async () => {
  try { drafts.value = (await issues.drafts()) || [] } catch { /* 忽略 */ }
})

function restoreDraft(d) {
  form.value.title = d.title || ''
  form.value.location = d.location || ''
  form.value.description = d.description || ''
  message.success('已恢复草稿，可继续填写')
}

const submit = async () => {
  if (!form.value.title || !form.value.location) {
    return message.warning('请填写问题描述和地址')
  }
  loading.value = true
  try {
    // 先传照片（最多3张，≤5MB），再提交工单
    if (files.value.length) {
      const fileObjs = files.value.map((f) => f.file)
      const up = await upload(fileObjs, 'issues')
      form.value.photo_before = JSON.stringify(up.paths || [])
    }
    const data = await issues.create({
      ...form.value,
      is_agent_report: form.value.is_agent_report ? 1 : 0,
    })
    message.success(`工单 #${data.issue_id} 已提交，状态：待审核`)
    router.push('/resident/work-orders')
  } catch (e) {
    message.error(e.message || '提交失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">📝 提交报修</h2>
    <p class="page-sub">填一下问题描述，负责人会尽快电话核实</p>

    <!-- 草稿恢复 -->
    <div v-if="drafts.length" class="card urgent-bg" style="margin-bottom:12px;">
      <b>📝 您有 {{ drafts.length }} 份未完成的报修草稿</b>
      <div v-for="d in drafts" :key="d.id" style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
        <span>{{ d.title }} <span class="muted">（{{ (d.created_at || '').slice(0, 10) }}）</span></span>
        <n-button size="small" @click="restoreDraft(d)">继续填写</n-button>
      </div>
    </div>

    <div class="card">
      <n-form label-placement="top">
        <n-form-item label="问题描述（必填）">
          <n-input v-model:value="form.title" placeholder="比如：3号楼二楼楼道灯不亮了" />
        </n-form-item>
        <n-form-item label="报修地址（必填，小区/院落 + 楼栋单元房号）">
          <n-input v-model:value="form.location" placeholder="比如：幸福小区3号楼2单元302" />
        </n-form-item>
        <n-grid :cols="2" :x-gap="16">
          <n-form-item-gi label="分类">
            <n-select v-model:value="form.issue_type" :options="[{label:'室内',value:'室内'},{label:'室外',value:'室外'}]" />
          </n-form-item-gi>
          <n-form-item-gi label="紧急程度">
            <n-select v-model:value="form.urgency" :options="['紧急','中等','一般','普通'].map(v=>({label:v,value:v}))" />
          </n-form-item-gi>
        </n-grid>
        <n-form-item label="现场照片（选填，jpg/png，≤5MB，最多3张）">
          <n-upload v-model:file-list="files" accept="image/jpeg,image/png" :max="3"
                    list-type="image-card" :default-upload="false" />
        </n-form-item>
        <n-form-item label="报修人姓名">
          <n-input v-model:value="form.reporter_name" placeholder="选填，默认当前账号姓名" />
        </n-form-item>
        <n-form-item label="联系电话">
          <n-input v-model:value="form.reporter_phone" placeholder="11 位手机号" />
        </n-form-item>
        <n-checkbox v-model:checked="form.is_agent_report" style="margin-bottom:8px;">我是代报（帮家人/邻居报修）</n-checkbox>
        <template v-if="form.is_agent_report">
          <n-grid :cols="2" :x-gap="16">
            <n-form-item-gi label="代报人姓名">
              <n-input v-model:value="form.agent_name" placeholder="代报人姓名" />
            </n-form-item-gi>
            <n-form-item-gi label="代报人电话">
              <n-input v-model:value="form.agent_phone" placeholder="代报人电话" />
            </n-form-item-gi>
          </n-grid>
          <n-form-item label="与报修人关系">
            <n-input v-model:value="form.agent_relation" placeholder="如：家人 / 邻居" />
          </n-form-item>
        </template>
        <n-button type="primary" block size="large" :loading="loading" @click="submit">📨 提交报修</n-button>
      </n-form>
    </div>
  </div>
</template>
