<script setup lang="ts">
import { reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import { apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { ElMessage, ElMessageBox } from 'element-plus'

const loading = ref(false)
const result = ref<Record<string, unknown> | null>(null)
const form = reactive({
  base_url: '',
  api_key: '',
  inputs_json: '{\n  "mr_txt": ""\n}',
})

async function runDebug() {
  try {
    await ElMessageBox.confirm(
      'Dify 调试仅用于受控环境。确认发起调试请求？请勿粘贴真实病历正文到可共享截图。',
      '受控操作',
      { type: 'warning' },
    )
  } catch {
    return
  }

  let inputs: Record<string, unknown>
  try {
    inputs = JSON.parse(form.inputs_json) as Record<string, unknown>
  } catch {
    ElMessage.error('inputs JSON 无效')
    return
  }

  loading.value = true
  result.value = null
  try {
    const body: Record<string, unknown> = { inputs }
    if (form.base_url.trim()) body.base_url = form.base_url.trim()
    // 密钥：仅当用户显式填写时提交；禁止回填明文
    if (form.api_key.trim()) body.api_key = form.api_key.trim()
    result.value = (await apiPost('/config/dify/debug', body)) as Record<string, unknown>
    ElMessage.success('调试请求完成')
    form.api_key = ''
  } catch (e) {
    ElMessage.error(toUserMessage(e, '调试失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page-debug">
    <PageHeader
      title="Dify 调试"
      description="dev_only 入口。不读取/回填明文 Key；输出以后端脱敏为准。"
    />
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      class="mb"
      title="安全提示"
      description="禁止在 Console、截图或 trace 中保留患者标识、病历正文或密钥。"
    />
    <el-card shadow="never" class="card">
      <el-form label-width="120px">
        <el-form-item label="base_url 覆盖">
          <el-input v-model="form.base_url" placeholder="可选；留空使用配置" />
        </el-form-item>
        <el-form-item label="api_key">
          <el-input
            v-model="form.api_key"
            type="password"
            show-password
            placeholder="可选；留空使用已保存密文"
          />
        </el-form-item>
        <el-form-item label="inputs JSON">
          <el-input v-model="form.inputs_json" type="textarea" :rows="10" class="mono" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="loading" @click="runDebug">执行调试</el-button>
        </el-form-item>
      </el-form>
    </el-card>
    <el-card v-if="result" shadow="never" class="card">
      <template #header>响应（脱敏）</template>
      <pre class="json-pre">{{ JSON.stringify(result, null, 2) }}</pre>
    </el-card>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 12px;
}
.card {
  margin-bottom: 12px;
  border-radius: 12px;
}
.mono :deep(textarea) {
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
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
