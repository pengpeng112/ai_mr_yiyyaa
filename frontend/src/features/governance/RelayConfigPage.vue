<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { buildRelayPartialUpdateBody } from '@/utils/mutation-contracts'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const form = reactive({
  enabled: false,
  base_url: '',
  endpoint: '',
  secret_key: '',
  has_secret: false,
  severity_levels: [] as string[],
  alert_dept_filter: [] as string[],
  source: '',
})
const deptFilterText = ref('')
const severityText = ref('high')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<Record<string, unknown>>('/config/relay-alert')
    form.enabled = Boolean(data.enabled)
    form.base_url = String(data.base_url || '')
    form.endpoint = String(data.endpoint || '')
    form.source = String(data.source || '')
    form.has_secret = Boolean(data.has_secret_key || data.secret_key_masked || data.secret_key_enc)
    form.secret_key = ''
    form.severity_levels = Array.isArray(data.severity_levels)
      ? (data.severity_levels as string[])
      : ['high']
    form.alert_dept_filter = Array.isArray(data.alert_dept_filter)
      ? (data.alert_dept_filter as string[])
      : []
    severityText.value = form.severity_levels.join(',')
    deptFilterText.value = form.alert_dept_filter.join(',')
  } catch (e) {
    error.value = toUserMessage(e, '加载告警推送配置失败')
  } finally {
    loading.value = false
  }
}

async function save() {
  try {
    await ElMessageBox.confirm(
      '将以部分更新方式保存 Relay 配置：secret 留空保留旧密文；base_url 空字符串不会覆盖已有地址。',
      '请确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const body = buildRelayPartialUpdateBody({
      enabled: form.enabled,
      endpoint: form.endpoint,
      source: form.source,
      base_url: form.base_url,
      secret_key: form.secret_key,
      severity_levels: severityText.value,
      alert_dept_filter: deptFilterText.value,
    })

    await apiPost('/config/relay-alert', body)
    ElMessage.success('告警推送配置已保存')
    form.secret_key = ''
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-relay">
    <PageHeader
      title="告警推送配置"
      description="Relay / 企业微信前置机配置。本页不触发真实发送测试，除非另行批准。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <el-card v-else shadow="never" class="card" v-loading="loading">
      <el-form label-width="150px">
        <el-form-item label="启用">
          <el-switch v-model="form.enabled" />
        </el-form-item>
        <el-form-item label="base_url">
          <el-input v-model="form.base_url" placeholder="非空才提交；空串不覆盖已有值" />
        </el-form-item>
        <el-form-item label="endpoint">
          <el-input v-model="form.endpoint" />
        </el-form-item>
        <el-form-item label="secret_key">
          <el-input
            v-model="form.secret_key"
            type="password"
            show-password
            :placeholder="form.has_secret ? '已配置（留空保留）' : '未配置'"
          />
        </el-form-item>
        <el-form-item label="severity_levels">
          <el-input v-model="severityText" placeholder="例如 high,medium" />
        </el-form-item>
        <el-form-item label="alert_dept_filter">
          <el-input
            v-model="deptFilterText"
            type="textarea"
            :rows="3"
            placeholder="科室名称或编码，逗号分隔；空=全部"
          />
        </el-form-item>
        <el-form-item label="source">
          <el-input v-model="form.source" />
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.card {
  border-radius: 12px;
}
</style>
