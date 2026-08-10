<script setup lang="ts">
import { reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import { apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { buildManualPushBody } from '@/utils/mutation-contracts'
import { ElMessage, ElMessageBox } from 'element-plus'

const step = ref(1)
const loading = ref(false)
const preview = ref<Record<string, unknown> | null>(null)
const form = reactive({
  query_date: '',
  audit_type_codes: '' as string,
  date_dimension: 'query_date',
  dept_filter: '',
  dry_run: true,
  async_mode: true,
  replace_current: false,
  allow_rectified: false,
  skip_already_succeeded: true,
})

function buildBody() {
  return buildManualPushBody({
    query_date: form.query_date,
    date_dimension: form.date_dimension,
    dept_filter: form.dept_filter,
    audit_type_codes: form.audit_type_codes,
    dry_run: form.dry_run,
    async_mode: form.async_mode,
    replace_current: form.replace_current,
    allow_rectified: form.allow_rectified,
    skip_already_succeeded: form.skip_already_succeeded,
  })
}

async function runPreview() {
  loading.value = true
  preview.value = null
  try {
    // 预览固定 dry_run 语义：走 /push/preview，body 仍带 dry_run 等字段
    const body = { ...buildBody(), dry_run: true, async_mode: false }
    preview.value = (await apiPost('/push/preview', body)) as Record<string, unknown>
    step.value = 2
    ElMessage.success('预览完成（未触发真实推送）')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '预览失败'))
  } finally {
    loading.value = false
  }
}

async function runPush() {
  if (form.dry_run) {
    ElMessage.info('当前为 dry-run 模式，请取消勾选后再执行真实推送')
    return
  }
  try {
    await ElMessageBox.confirm(
      '将触发真实手动推送（可能调用 Dify）。请确认范围、日期与审计类型无误。请求体字段与 legacy buildPushRequestBody 核心语义对齐。',
      '高风险操作',
      { type: 'warning', confirmButtonText: '确认推送', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  loading.value = true
  try {
    const body = buildBody()
    const res = await apiPost('/push/manual', body)
    step.value = 3
    preview.value = res as Record<string, unknown>
    ElMessage.success('推送任务已提交')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '推送失败'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="page-push">
    <PageHeader
      title="手动推送"
      description="三步：范围 → 候选预览 → 执行确认。dry_run / replace_current / skip 语义与后端契约对齐。全院任务能力保留。"
    />

    <el-steps :active="step - 1" finish-status="success" align-center class="mb">
      <el-step title="范围" />
      <el-step title="预览" />
      <el-step title="执行" />
    </el-steps>

    <el-card shadow="never" class="card">
      <el-form label-width="140px" @submit.prevent>
        <el-form-item label="查询日期">
          <el-input v-model="form.query_date" placeholder="YYYY-MM-DD" />
        </el-form-item>
        <el-form-item label="日期维度">
          <el-select v-model="form.date_dimension" style="width: 100%">
            <el-option label="query_date" value="query_date" />
            <el-option label="record_create_date" value="record_create_date" />
            <el-option label="admission_date" value="admission_date" />
            <el-option label="discharge_date" value="discharge_date" />
          </el-select>
        </el-form-item>
        <el-form-item label="审计类型">
          <el-input
            v-model="form.audit_type_codes"
            type="textarea"
            :rows="2"
            placeholder="多个 code 用逗号分隔；留空表示后端默认范围"
          />
        </el-form-item>
        <el-form-item label="科室过滤">
          <el-input v-model="form.dept_filter" placeholder="科室编码，逗号分隔；留空表示授权范围内" />
        </el-form-item>
        <el-form-item label="dry-run 保护">
          <el-switch v-model="form.dry_run" active-text="仅预览" inactive-text="允许真实推送" />
        </el-form-item>
        <el-form-item label="异步执行">
          <el-switch v-model="form.async_mode" :disabled="form.dry_run" />
        </el-form-item>
        <el-form-item label="replace_current">
          <el-switch v-model="form.replace_current" />
          <span class="hint">覆盖当前结果（existing_result_policy）</span>
        </el-form-item>
        <el-form-item label="allow_rectified">
          <el-switch v-model="form.allow_rectified" />
        </el-form-item>
        <el-form-item label="skip 已成功">
          <el-switch v-model="form.skip_already_succeeded" :disabled="form.replace_current" />
        </el-form-item>
        <el-form-item>
          <el-button :loading="loading" @click="runPreview">1. 预览候选</el-button>
          <el-button type="danger" :loading="loading" :disabled="form.dry_run" @click="runPush">
            2. 确认执行推送
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card v-if="preview" shadow="never" class="card">
      <template #header>结果 / 预览（脱敏展示）</template>
      <pre class="json-pre">{{ JSON.stringify(preview, null, 2) }}</pre>
    </el-card>
  </div>
</template>

<style scoped>
.mb {
  margin-bottom: 16px;
}
.card {
  margin-bottom: 12px;
  border-radius: 12px;
}
.hint {
  margin-left: 8px;
  color: var(--ma-text-muted);
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
