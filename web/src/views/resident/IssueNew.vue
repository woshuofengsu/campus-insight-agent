<script setup>
// 提交报修
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useMessage } from 'naive-ui'
import { issues } from '../../api'

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
})

const submit = async () => {
  if (!form.value.title || !form.value.location) {
    return message.warning('请填写问题描述和地址')
  }
  loading.value = true
  try {
    const data = await issues.create(form.value)
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
        <n-form-item label="报修人姓名">
          <n-input v-model:value="form.reporter_name" placeholder="选填，默认当前账号姓名" />
        </n-form-item>
        <n-form-item label="联系电话">
          <n-input v-model:value="form.reporter_phone" placeholder="11 位手机号" />
        </n-form-item>
        <n-button type="primary" block size="large" :loading="loading" @click="submit">📨 提交报修</n-button>
      </n-form>
    </div>
  </div>
</template>
