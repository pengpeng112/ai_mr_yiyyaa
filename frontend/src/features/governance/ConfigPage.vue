<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { buildDifySaveBody } from '@/utils/mutation-contracts'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const saving = ref(false)
const error = ref('')
const active = ref('dify')

const dify = reactive({
  base_url: '',
  api_key: '',
  workflow_input_variable: 'mr_txt',
  has_api_key: false,
})
const push = reactive<Record<string, unknown>>({})
const privacy = reactive<Record<string, unknown>>({})
const dataSource = reactive<{ type?: string }>({})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [d, p, pr, ds] = await Promise.all([
      apiGet<Record<string, unknown>>('/config/dify'),
      apiGet<Record<string, unknown>>('/config/push'),
      apiGet<Record<string, unknown>>('/config/privacy-masking'),
      apiGet<{ type?: string }>('/config/data-source'),
    ])
    dify.base_url = String(d.base_url || '')
    dify.workflow_input_variable = String(d.workflow_input_variable || 'mr_txt')
    dify.has_api_key = Boolean(d.has_api_key || d.api_key_masked || d.api_key_enc)
    dify.api_key = '' // 留空 = 保留旧密文
    Object.assign(push, p || {})
    Object.assign(privacy, pr || {})
    Object.assign(dataSource, ds || {})
  } catch (e) {
    error.value = toUserMessage(e, '加载系统配置失败')
  } finally {
    loading.value = false
  }
}

async function saveDify() {
  try {
    await ElMessageBox.confirm(
      '确认保存 Dify 配置？api_key 留空将保留已有密文；base_url 空字符串不得覆盖已有地址（由后端保护）。',
      '请确认',
      { type: 'warning' },
    )
  } catch {
    return
  }
  saving.value = true
  try {
    const body = buildDifySaveBody({
      base_url: dify.base_url,
      workflow_input_variable: dify.workflow_input_variable,
      api_key: dify.api_key,
    })
    await apiPost('/config/dify', body)
    ElMessage.success('Dify 配置已保存')
    dify.api_key = ''
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    saving.value = false
  }
}

async function savePush() {
  try {
    await ElMessageBox.confirm('确认保存推送参数？', '请确认', { type: 'warning' })
  } catch {
    return
  }
  saving.value = true
  try {
    await apiPost('/config/push', push)
    ElMessage.success('推送参数已保存')
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
  <div class="page-config">
    <PageHeader
      title="系统配置"
      description="配置域导航 + 表单 + sticky 保存。密钥留空保留、部分更新语义不可回退。"
    >
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <el-tabs v-else v-model="active" v-loading="loading">
      <el-tab-pane label="数据源" name="ds">
        <el-card shadow="never" class="card">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="当前类型">{{ dataSource.type || '—' }}</el-descriptions-item>
          </el-descriptions>
          <el-alert
            class="mt"
            type="info"
            :closable="false"
            title="连接串与密码请在对应子配置页维护；本页不回显明文密钥。"
          />
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="Dify" name="dify">
        <el-card shadow="never" class="card">
          <el-form label-width="160px">
            <el-form-item label="base_url">
              <el-input v-model="dify.base_url" placeholder="Dify API base URL" />
            </el-form-item>
            <el-form-item label="workflow 输入变量">
              <el-input v-model="dify.workflow_input_variable" placeholder="默认 mr_txt" />
            </el-form-item>
            <el-form-item label="API Key">
              <el-input
                v-model="dify.api_key"
                type="password"
                show-password
                :placeholder="dify.has_api_key ? '已配置（留空保留）' : '未配置'"
              />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :loading="saving" @click="saveDify">保存 Dify</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="推送参数" name="push">
        <el-card shadow="never" class="card">
          <pre class="json-pre">{{ JSON.stringify(push, null, 2) }}</pre>
          <el-button class="mt" type="primary" :loading="saving" @click="savePush">保存推送参数</el-button>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="隐私脱敏" name="privacy">
        <el-card shadow="never" class="card">
          <pre class="json-pre">{{ JSON.stringify(privacy, null, 2) }}</pre>
        </el-card>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<style scoped>
.card {
  border-radius: 12px;
}
.mt {
  margin-top: 12px;
}
.json-pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 420px;
  overflow: auto;
}
</style>
