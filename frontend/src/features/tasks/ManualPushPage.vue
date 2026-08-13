<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildHistoricalCreatePayload, buildHistoricalPreviewPayload } from '@/utils/historical-rerun'

// ── 模式 Tab ──
type Mode = 'standard' | 'historical'
const mode = ref<Mode>('standard')

// ── 配置表单 ──
const form = reactive({
  date_mode: 'single' as 'single' | 'range',
  query_date: '',
  date_range: [] as string[],
  date_dimension: 'record_create_date',
  dept_filter: '',
  audit_type_codes: [] as string[],
  parallel_audit_types: false,
  dry_run: false,
  async_mode: false,
  replace_current: false,
  replace_alert_policy: 'suppress',
  allow_rectified: false,
  skip_already_succeeded: true,
  parallel_workers: 4,
  empty_retry_max: 0,
  empty_retry_backoff_ms: 1000,
  target_strategy: 'round_robin',
  // 历史重跑
  reaudit_reason: '',
  alert_policy: 'suppress',
  include_rectified: false,
  historical_run_mode: 'daily_increment',
  shard_limit: 100,
})

const auditTypeOptions = ref<Array<{ value: string; label: string; default_for_schedule?: boolean }>>([])

// ── 候选记录 ──
const queryLoading = ref(false)
const queryRows = ref<Array<Record<string, unknown>>>([])
const queryTotal = ref(0)
const queryPage = ref(1)
const queryPageSize = ref(50)
const selectedKeys = ref<string[]>([])
const querySummary = ref<Record<string, unknown>>({})

// ── 预检 ──
const precheckLoading = ref(false)
const precheckResult = ref<Record<string, unknown> | null>(null)
const precheckVisible = ref(false)
const matchDiagnostics = ref<Record<string, unknown> | null>(null)
const matchLoading = ref(false)

// ── 推送执行 ──
const pushLoading = ref(false)
const taskId = ref('')
const taskProg = ref<Record<string, unknown> | null>(null)
const pushResult = ref<Record<string, unknown> | null>(null)
const resultPage = ref(1)
const resultPageSize = ref(20)
let pollTimer: ReturnType<typeof setInterval> | null = null

// ── 历史重跑 ──
const histPreviewLoading = ref(false)
const histPreview = ref<Record<string, unknown> | null>(null)
const histBatchLoading = ref(false)
const histBatch = ref<Record<string, unknown> | null>(null)
const histItems = ref<Array<Record<string, unknown>>>([])
const histItemsTotal = ref(0)
const reconciliation = ref<Record<string, unknown> | null>(null)
const histDetailLoading = ref(false)
const controlLoading = ref('')

// ── 步骤指示 ──
const activeStep = computed(() => {
  if (pushResult.value || taskProg.value) return 3
  if (precheckResult.value || queryRows.value.length) return 1
  return 0
})

// ── label helpers ──
const skipReasonLabels: Record<string, string> = {
  empty_lab_exam: '检验检查数据为空',
  empty_progress_nursing: '病程护理记录为空',
  empty_both_sides: '双源均为空',
  already_succeeded: '已有成功记录',
  unreviewed_pending: '已推送未复核',
  rectified_suppressed: '已整改抑制',
  insufficient_surgery_docs: '围手术期文书不足',
}
function skipLabel(r: string): string { return skipReasonLabels[r] || r }

const pushResultRows = computed(() => {
  if (!pushResult.value) return []
  const rows = pushResult.value.dry_run ? pushResult.value.preview : pushResult.value.results
  return Array.isArray(rows) ? rows : []
})
const pagedResultRows = computed(() => {
  const start = (resultPage.value - 1) * resultPageSize.value
  return pushResultRows.value.slice(start, start + resultPageSize.value)
})

const targetMetricsRows = computed(() => {
  const m = pushResult.value?.target_metrics as Record<string, Record<string, number>> | undefined
  if (!m) return []
  return Object.entries(m).map(([name, v]) => ({
    name, selected: v.selected || 0, success: v.success || 0, failed: v.failed || 0, empty: v.empty || 0,
  }))
})

// ── 审计类型加载 ──
async function loadAuditTypes() {
  try {
    const data = await apiGet<{ items?: Array<{ code: string; name: string; default_for_schedule?: boolean }> }>('/audit-types/options')
    auditTypeOptions.value = (data.items || []).map((i) => ({
      value: i.code, label: i.name, default_for_schedule: !!i.default_for_schedule,
    }))
    if (!form.audit_type_codes.length) {
      form.audit_type_codes = auditTypeOptions.value.filter((a) => a.default_for_schedule).map((a) => a.value)
    }
  } catch { /* 静默 */ }
}

// ── 构建请求体 ──
function buildBody(extra: Record<string, unknown> = {}): Record<string, unknown> {
  const dateFrom = form.date_mode === 'range' ? (form.date_range[0] || '') : form.query_date
  const dateTo = form.date_mode === 'range' ? (form.date_range[1] || '') : form.query_date
  const depts = form.dept_filter ? form.dept_filter.split(',').map((s) => s.trim()).filter(Boolean) : null
  const replace = form.replace_current
  return {
    query_date: form.date_mode === 'single' ? form.query_date : null,
    date_from: form.date_mode === 'range' ? dateFrom : null,
    date_to: form.date_mode === 'range' ? dateTo : null,
    date_dimension: form.date_dimension,
    dept_filter: depts,
    dry_run: form.dry_run,
    async_mode: form.async_mode && !form.dry_run,
    parallel_workers: form.parallel_workers,
    empty_retry_max: form.empty_retry_max,
    empty_retry_backoff_ms: form.empty_retry_backoff_ms,
    target_strategy: form.target_strategy,
    audit_type_codes: form.audit_type_codes.length ? form.audit_type_codes : null,
    parallel_audit_types: form.parallel_audit_types,
    selected_record_keys: extra.selected_record_keys || null,
    page: extra.page ?? null,
    page_size: extra.page_size ?? null,
    existing_result_policy: replace ? 'replace_current' : 'skip_success',
    alert_policy: replace ? form.replace_alert_policy : (mode.value === 'historical' ? form.alert_policy : 'default'),
    allow_rectified: mode.value === 'historical' ? form.include_rectified : form.allow_rectified,
    skip_already_succeeded: replace ? false : form.skip_already_succeeded,
    run_purpose: mode.value === 'historical' ? 'historical_reaudit' : 'standard',
    reaudit_reason: mode.value === 'historical' ? form.reaudit_reason : undefined,
  }
}
function historicalScope() {
  const body = buildBody()
  return {
    query_date: body.query_date as string | null,
    date_from: body.date_from as string | null,
    date_to: body.date_to as string | null,
    date_dimension: String(body.date_dimension),
    audit_type_codes: body.audit_type_codes as string[] | null,
    dept_filter: body.dept_filter as string[] | null,
  }
}

function validateDateRange(): boolean {
  if (form.date_mode === 'single' && !form.query_date) {
    ElMessage.warning('请选择日期')
    return false
  }
  if (form.date_mode === 'range' && (!form.date_range?.length || !form.date_range[0])) {
    ElMessage.warning('请选择日期范围')
    return false
  }
  if (mode.value === 'historical' && !form.reaudit_reason.trim()) {
    ElMessage.warning('请填写重跑原因')
    return false
  }
  return true
}

// ── 查询候选 ──
async function queryCandidates(showMsg = true) {
  if (!validateDateRange()) return
  queryLoading.value = true
  try {
    const data = await apiPost<Record<string, unknown>>('/push/query-preview', buildBody({
      page: queryPage.value, page_size: queryPageSize.value,
    }))
    querySummary.value = data || {}
    queryRows.value = (data.rows as Array<Record<string, unknown>>) || []
    queryTotal.value = Number(data.total_rows ?? queryRows.value.length)
    queryPage.value = Number(data.page ?? queryPage.value)
    if (showMsg) ElMessage.success(`查询完成，共 ${queryTotal.value} 条候选`)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '查询候选失败'))
  } finally {
    queryLoading.value = false
  }
}

function onSelectionChange(rows: Array<Record<string, unknown>>) {
  selectedKeys.value = rows.map((r) => String(r.record_key || '')).filter(Boolean)
}

// ── 预检 ──
async function precheck() {
  if (!validateDateRange()) return
  precheckLoading.value = true
  precheckResult.value = null
  try {
    precheckResult.value = await apiPost<Record<string, unknown>>('/push/precheck', buildBody())
    precheckVisible.value = true
  } catch (e) {
    ElMessage.error(toUserMessage(e, '预检失败'))
  } finally {
    precheckLoading.value = false
  }
}

async function loadMatchDiagnostics() {
  if (form.audit_type_codes.length !== 1 || !validateDateRange()) return
  matchLoading.value = true
  try {
    matchDiagnostics.value = await apiPost<Record<string, unknown>>('/push/match-diagnostics', buildBody({ selected_record_keys: selectedKeys.value }))
  } catch (e) {
    ElMessage.error(toUserMessage(e, '匹配诊断失败'))
  } finally { matchLoading.value = false }
}

const precheckSkipRows = computed(() => {
  const counts = precheckResult.value?.skip_reason_counts as Record<string, number> | undefined
  if (!counts) return []
  return Object.entries(counts).map(([reason, count]) => ({ label: skipLabel(reason), count }))
})

// ── 执行推送 ──
async function doPush() {
  if (pushLoading.value) return
  if (!validateDateRange()) return
  const message = form.dry_run
    ? '确认执行预览？预览不会调用 Dify 或写入业务结果。'
    : form.replace_current
      ? '将覆盖当前质控结果：旧记录保留为历史版本，默认抑制外发告警。确认继续？'
      : '确认开始推送？该操作可能调用 Dify 并写入质控结果。'
  try { await ElMessageBox.confirm(message, '执行确认', { type: form.dry_run ? 'info' : 'warning' }) } catch { return }
  pushLoading.value = true
  pushResult.value = null
  resultPage.value = 1
  try {
    const data = await apiPost<Record<string, unknown>>('/push/manual', buildBody())
    if (data.task_id) {
      taskId.value = String(data.task_id)
      taskProg.value = null
      pushResult.value = data
      startPolling()
      ElMessage.success('已提交批量推送任务')
    } else {
      pushResult.value = data
      ElMessage.success(form.dry_run ? '预览完成' : '批量推送完成')
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '推送失败'))
  } finally {
    pushLoading.value = false
  }
}

// ── 勾选推送 ──
async function pushSelected() {
  if (pushLoading.value) return
  if (!selectedKeys.value.length) { ElMessage.warning('请先勾选记录'); return }
  if (!validateDateRange()) return
  if (form.audit_type_codes.length !== 1) { ElMessage.warning('勾选推送请选一个审计类型'); return }
  try { await ElMessageBox.confirm('确认推送已勾选记录？该操作可能调用 Dify 并写入质控结果。', '勾选推送确认', { type: 'warning' }) } catch { return }
  pushLoading.value = true
  try {
    const data = await apiPost<Record<string, unknown>>('/push/manual', buildBody({
      selected_record_keys: selectedKeys.value, audit_type_codes: form.audit_type_codes,
    }))
    if (data.task_id) {
      taskId.value = String(data.task_id)
      pushResult.value = data
      startPolling()
      ElMessage.success(`已提交 ${selectedKeys.value.length} 条勾选记录推送`)
    } else {
      pushResult.value = data
      ElMessage.success('勾选推送完成')
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '勾选推送失败'))
  } finally {
    pushLoading.value = false
  }
}

// ── 轮询 ──
function startPolling() {
  stopPolling()
  void refreshProgress()
  pollTimer = setInterval(refreshProgress, 3000)
}
function stopPolling() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}
async function refreshProgress() {
  if (!taskId.value) return
  try {
    const data = await apiGet<Record<string, unknown>>(`/push/status/${taskId.value}`)
    taskProg.value = data
    if (['completed', 'failed', 'not_found', 'cancelled'].includes(String(data.status))) {
      stopPolling()
    }
  } catch { /* 静默 */ }
}

async function stopPush() {
  if (!taskId.value) return
  try {
    await ElMessageBox.confirm('确认停止正在运行的推送任务？', '停止确认', { type: 'warning' })
    await apiPost(`/push/cancel/${taskId.value}`, {})
    ElMessage.success('已发送停止请求')
    stopPolling()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '停止失败'))
  }
}

// ── 历史重跑 ──
async function previewHistorical() {
  if (!validateDateRange()) return
  histPreviewLoading.value = true
  histPreview.value = null
  try {
    histPreview.value = await apiPost<Record<string, unknown>>('/push/historical-rerun/preview', buildHistoricalPreviewPayload(historicalScope(), form.historical_run_mode, form.shard_limit))
  } catch (e) {
    ElMessage.error(toUserMessage(e, '预检失败'))
  } finally {
    histPreviewLoading.value = false
  }
}

async function confirmHistoricalBatch() {
  if (!histPreview.value) return
  if (histBatchLoading.value) return
  try { await ElMessageBox.confirm('确认创建历史重跑批次？后续执行可能调用 Dify 并替代当前结果。', '历史重跑确认', { type: 'warning' }) } catch { return }
  histBatchLoading.value = true
  try {
    const hash = histPreview.value.candidate_hash
    histBatch.value = await apiPost<Record<string, unknown>>('/push/historical-rerun/batches', buildHistoricalCreatePayload(historicalScope(), {
      audit_run_mode: form.historical_run_mode,
      candidate_hash: String(hash || ''),
      reaudit_reason: form.reaudit_reason,
      alert_policy: form.alert_policy,
      include_rectified: form.include_rectified,
      auto_start: true,
    }))
    ElMessage.success('批次已创建')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '创建批次失败'))
  } finally {
    histBatchLoading.value = false
  }
}

async function controlBatch(action: string) {
  if (!histBatch.value?.id) return
  if (controlLoading.value) return
  try { await ElMessageBox.confirm(`确认${action === 'pause' ? '暂停' : action === 'resume' ? '继续' : '取消'}历史重跑批次？`, '批次操作确认', { type: 'warning' }) } catch { return }
  controlLoading.value = action
  try {
    histBatch.value = await apiPost<Record<string, unknown>>(`/push/historical-rerun/batches/${histBatch.value.id}/${action}`, {})
    ElMessage.success(`已${action === 'pause' ? '暂停' : action === 'resume' ? '继续' : '取消'}`)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '操作失败'))
  } finally { controlLoading.value = ''
  }
}

async function refreshBatch() {
  if (!histBatch.value?.id) return
  try {
    histBatch.value = await apiGet<Record<string, unknown>>(`/push/historical-rerun/batches/${histBatch.value.id}`)
  } catch { /* 静默 */ }
}

async function loadHistoricalDetails() {
  const id = histBatch.value?.id
  if (!id) return
  histDetailLoading.value = true
  try {
    const items = await apiGet<{ items?: Array<Record<string, unknown>>; total?: number }>(`/push/historical-rerun/batches/${id}/items`, { params: { page: 1, limit: 50 } })
    histItems.value = items.items || []
    histItemsTotal.value = Number(items.total || 0)
    try {
      reconciliation.value = await apiGet<Record<string, unknown>>(`/push/historical-rerun/batches/${id}/reconciliation`)
    } catch (e) {
      ElMessage.warning(`批次明细已加载，对账尚未就绪，请稍后重试：${toUserMessage(e, '对账不可用')}`)
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载批次明细失败'))
  } finally { histDetailLoading.value = false }
}

function resetAll() {
  queryRows.value = []
  queryTotal.value = 0
  selectedKeys.value = []
  precheckResult.value = null
  pushResult.value = null
  taskProg.value = null
  taskId.value = ''
  histPreview.value = null
  histBatch.value = null
  matchDiagnostics.value = null
  histItems.value = []
  reconciliation.value = null
  stopPolling()
}

onMounted(() => { void loadAuditTypes() })
onUnmounted(() => stopPolling())
</script>

<template>
  <div class="page-push">
    <PageHeader title="手动推送" description="按范围选择 → 预检确认 → 执行推送 → 结果追踪。">
      <template #actions>
        <el-button @click="resetAll">重置</el-button>
      </template>
    </PageHeader>

    <!-- 模式切换 -->
    <el-radio-group v-model="mode" class="mode-tabs">
      <el-radio-button value="standard">普通推送</el-radio-button>
      <el-radio-button value="historical">历史重新核查</el-radio-button>
    </el-radio-group>

    <!-- 步骤指示 -->
    <el-steps :active="activeStep" class="push-steps" finish-status="success" simple>
      <el-step title="配置范围" />
      <el-step title="预检/候选" />
      <el-step title="执行推送" />
      <el-step title="结果追踪" />
    </el-steps>

    <!-- 步骤1: 配置 -->
    <el-card shadow="never" class="section-card">
      <div class="section-title">基础配置</div>
      <div class="form-grid">
        <div class="form-item">
          <label>推送模式</label>
          <el-radio-group v-model="form.date_mode" size="small">
            <el-radio value="single">单日</el-radio>
            <el-radio value="range">日期范围</el-radio>
          </el-radio-group>
        </div>
        <div class="form-item">
          <label>日期维度</label>
          <el-select v-model="form.date_dimension" size="small" style="width: 180px">
            <el-option label="病历创建日期" value="record_create_date" />
            <el-option label="入院日期" value="admission_date" />
            <el-option label="出院日期" value="discharge_date" />
          </el-select>
        </div>
        <div v-if="form.date_mode === 'single'" class="form-item">
          <label>目标日期</label>
          <el-date-picker v-model="form.query_date" type="date" value-format="YYYY-MM-DD" placeholder="选择日期" size="small" style="width: 180px" />
        </div>
        <div v-else class="form-item form-item-wide">
          <label>日期范围</label>
          <el-date-picker v-model="form.date_range" type="daterange" range-separator="~" start-placeholder="开始" end-placeholder="结束" value-format="YYYY-MM-DD" size="small" style="width: 260px" />
        </div>
        <div class="form-item form-item-wide">
          <label>审计类型</label>
          <el-select v-model="form.audit_type_codes" multiple collapse-tags collapse-tags-tooltip filterable size="small" style="width: 360px" placeholder="选择审计类型">
            <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </div>
        <div class="form-item">
          <label>科室过滤</label>
          <el-input v-model="form.dept_filter" placeholder="逗号分隔，留空用系统配置" size="small" style="width: 200px" />
        </div>
      </div>

      <!-- 执行选项 -->
      <div class="section-sub-title">执行选项</div>
      <div class="switch-row">
        <el-checkbox v-model="form.dry_run">预览模式（不调 Dify）</el-checkbox>
        <el-checkbox v-model="form.async_mode" :disabled="form.dry_run">异步执行</el-checkbox>
        <el-checkbox v-model="form.parallel_audit_types">类型并行</el-checkbox>
        <el-checkbox v-model="form.skip_already_succeeded">跳过已成功</el-checkbox>
      </div>

      <!-- 覆盖选项 -->
      <el-collapse class="advanced-collapse">
        <el-collapse-item title="覆盖与高级参数" name="adv">
          <div class="switch-row">
            <el-checkbox v-model="form.replace_current">覆盖原有质控结果</el-checkbox>
            <el-checkbox v-if="form.replace_current" v-model="form.allow_rectified">含已整改抑制</el-checkbox>
          </div>
          <div v-if="form.replace_current" class="form-grid">
            <div class="form-item">
              <label>覆盖时告警</label>
              <el-select v-model="form.replace_alert_policy" size="small" style="width: 160px">
                <el-option label="抑制外发（推荐）" value="suppress" />
                <el-option label="仅新高危" value="new_high_only" />
                <el-option label="按默认规则" value="default" />
              </el-select>
            </div>
          </div>
          <el-alert v-if="form.replace_current" type="warning" :closable="false" show-icon class="mt-sm"
            title="覆盖模式：绕过已推未复核跳过；新结果仅在传输成功且解析可用后成为当前结果，旧记录保留为历史版本，不物理删除。" />
          <div class="form-grid mt-sm">
            <div class="form-item"><label>并发线程</label><el-input-number v-model="form.parallel_workers" :min="1" :max="64" size="small" /></div>
            <div class="form-item"><label>空结果重试</label><el-input-number v-model="form.empty_retry_max" :min="0" :max="10" size="small" /></div>
            <div class="form-item"><label>重试退避ms</label><el-input-number v-model="form.empty_retry_backoff_ms" :min="0" :max="60000" :step="500" size="small" /></div>
            <div class="form-item"><label>分配策略</label>
              <el-select v-model="form.target_strategy" size="small" style="width: 140px">
                <el-option label="轮询" value="round_robin" />
                <el-option label="权重随机" value="weighted_random" />
              </el-select>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <!-- 历史重跑专属 -->
      <template v-if="mode === 'historical'">
        <div class="section-sub-title">历史重新核查配置</div>
        <el-alert type="warning" :closable="false" show-icon class="mt-sm"
          title="新结果仅在传输成功且 parse_success/qc_usable 后替代旧当前结果；默认不重发告警；不物理删除历史。" />
        <div class="form-grid mt-sm">
          <div class="form-item form-item-wide">
            <label>重跑原因（必填）</label>
            <el-input v-model="form.reaudit_reason" maxlength="500" show-word-limit placeholder="审批单号或业务原因；禁止填写密码/病历正文" size="small" />
          </div>
          <div class="form-item">
            <label>告警策略</label>
            <el-select v-model="form.alert_policy" size="small" style="width: 180px">
              <el-option label="抑制外发（默认）" value="suppress" />
              <el-option label="仅新高危" value="new_high_only" />
            </el-select>
          </div>
          <div class="form-item">
            <label>纳入已整改抑制</label>
            <el-switch v-model="form.include_rectified" size="small" />
          </div>
          <div class="form-item">
            <label>运行模式</label>
            <el-select v-model="form.historical_run_mode" size="small" style="width: 180px">
              <el-option label="每日增量" value="daily_increment" />
              <el-option label="出院终末" value="discharge_final" />
            </el-select>
          </div>
          <div class="form-item">
            <label>预检分片上限</label>
            <el-input-number v-model="form.shard_limit" :min="1" :max="1000" size="small" />
          </div>
        </div>
      </template>
    </el-card>

    <!-- 操作按钮区（整合） -->
    <div class="action-bar">
      <template v-if="mode === 'historical'">
        <el-button type="primary" :loading="histPreviewLoading" @click="previewHistorical">① 预检候选</el-button>
        <el-button type="warning" :disabled="!histPreview" :loading="histBatchLoading" @click="confirmHistoricalBatch">② 创建批次</el-button>
        <el-button v-if="histBatch && ['running', 'confirmed'].includes(String(histBatch.status))" :loading="controlLoading === 'pause'" :disabled="!!controlLoading" @click="controlBatch('pause')">暂停</el-button>
        <el-button v-if="histBatch && String(histBatch.status) === 'paused'" :loading="controlLoading === 'resume'" :disabled="!!controlLoading" @click="controlBatch('resume')">继续</el-button>
        <el-button v-if="histBatch && !['completed', 'completed_with_errors', 'cancelled'].includes(String(histBatch.status))" type="danger" plain :loading="controlLoading === 'cancel'" :disabled="!!controlLoading" @click="controlBatch('cancel')">取消批次</el-button>
        <el-button v-if="histBatch" @click="refreshBatch">刷新批次</el-button>
        <el-button v-if="histBatch" :loading="histDetailLoading" @click="loadHistoricalDetails">查看明细/对账</el-button>
      </template>
      <template v-else>
        <el-button :loading="queryLoading" @click="queryCandidates()">查询候选</el-button>
        <el-button :loading="precheckLoading" @click="precheck">预检</el-button>
        <el-button :loading="matchLoading" :disabled="form.audit_type_codes.length !== 1" @click="loadMatchDiagnostics">匹配诊断</el-button>
        <el-button type="primary" :loading="pushLoading" @click="doPush">{{ form.dry_run ? '预览数据' : '开始推送' }}</el-button>
        <el-button v-if="selectedKeys.length" type="success" :loading="pushLoading" @click="pushSelected">推送勾选 ({{ selectedKeys.length }})</el-button>
        <el-button v-if="taskId && (taskProg?.status === 'running' || !taskProg)" @click="refreshProgress">刷新进度</el-button>
        <el-button v-if="taskProg?.status === 'running'" type="danger" plain @click="stopPush">停止</el-button>
      </template>
    </div>

    <!-- 候选记录表 -->
    <el-card v-if="queryRows.length" shadow="never" class="section-card">
      <div class="section-title">候选记录（{{ queryTotal }} 条，已选 {{ selectedKeys.length }}）</div>
      <el-table :data="queryRows" stripe border size="small" max-height="400" style="width: 100%" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="36" />
        <el-table-column prop="patient_id" label="患者ID" width="100" show-overflow-tooltip />
        <el-table-column prop="patient_name" label="姓名" width="80" />
        <el-table-column prop="visit_number" label="住院次" width="60" />
        <el-table-column prop="dept" label="科室" width="100" show-overflow-tooltip />
        <el-table-column prop="audit_type_code" label="类型" width="140" show-overflow-tooltip />
        <el-table-column prop="record_name" label="文书" min-width="120" show-overflow-tooltip />
        <el-table-column label="操作" width="80">
          <template #default="{ row }">
            <el-button link size="small" @click="ElMessage.info(String(row.record_key))">查看键</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="queryPage" v-model:page-size="queryPageSize"
        :total="queryTotal" :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next"
        class="mt-sm" @current-change="() => queryCandidates(false)" @size-change="() => { queryPage=1; queryCandidates(false) }"
      />
    </el-card>

    <el-card v-if="matchDiagnostics" shadow="never" class="section-card">
      <div class="section-title">匹配诊断（只读）</div>
      <div class="stat-grid">
        <div class="stat-box"><span>来源行数</span><b>{{ Object.values((matchDiagnostics.source_row_counts as Record<string, number>) || {}).reduce((a, b) => a + Number(b || 0), 0) }}</b></div>
        <div class="stat-box"><span>分组前</span><b>{{ matchDiagnostics.grouped_before_selected || 0 }}</b></div>
        <div class="stat-box"><span>分组后</span><b>{{ matchDiagnostics.grouped_after_selected || 0 }}</b></div>
        <div class="stat-box"><span>跳过</span><b>{{ matchDiagnostics.skipped_records || 0 }}</b></div>
      </div>
    </el-card>

    <!-- 历史重跑预检结果 -->
    <el-card v-if="histPreview" shadow="never" class="section-card">
      <div class="section-title">预检结果</div>
      <div class="stat-grid">
        <div class="stat-box"><span>候选总数</span><b>{{ histPreview.candidate_count || 0 }}</b></div>
        <div class="stat-box"><span>可推送</span><b>{{ histPreview.pushable_count || 0 }}</b></div>
        <div class="stat-box"><span>身份不明</span><b>{{ histPreview.identity_ambiguous_count || 0 }}</b></div>
        <div class="stat-box"><span>整改抑制</span><b>{{ histPreview.rectified_suppressed_count || 0 }}</b></div>
        <div class="stat-box"><span>已有当前</span><b>{{ histPreview.has_current_count || 0 }}</b></div>
        <div class="stat-box"><span>预计调用</span><b>{{ histPreview.estimated_dify_calls || 0 }}</b></div>
      </div>
      <div v-if="histPreview.candidate_hash" class="hash-line">候选哈希：<code>{{ histPreview.candidate_hash }}</code></div>
    </el-card>

    <!-- 历史重跑批次状态 -->
    <el-card v-if="histBatch" shadow="never" class="section-card">
      <div class="section-title">批次 #{{ histBatch.id }} · <el-tag size="small">{{ histBatch.status }}</el-tag></div>
      <div class="stat-grid">
        <div class="stat-box"><span>进度</span><b>{{ histBatch.processed || 0 }} / {{ histBatch.candidate_count || 0 }}</b></div>
        <div class="stat-box stat-ok"><span>成功</span><b>{{ histBatch.success || 0 }}</b></div>
        <div class="stat-box stat-fail"><span>失败</span><b>{{ histBatch.failed || 0 }}</b></div>
        <div class="stat-box"><span>跳过</span><b>{{ histBatch.skipped || 0 }}</b></div>
        <div class="stat-box"><span>已替代</span><b>{{ histBatch.superseded || 0 }}</b></div>
      </div>
      <div v-if="histBatch.last_error" class="error-line">{{ histBatch.last_error }}</div>
    </el-card>
    <el-card v-if="histItems.length || reconciliation" shadow="never" class="section-card">
      <div class="section-title">批次明细与 before/after 对账</div>
      <div class="stat-grid" v-if="reconciliation">
        <div class="stat-box"><span>明细总数</span><b>{{ histItemsTotal }}</b></div>
        <div class="stat-box"><span>对账状态</span><b>{{ reconciliation.status || reconciliation.summary_status || '—' }}</b></div>
      </div>
      <el-table v-if="histItems.length" :data="histItems" border size="small" max-height="320" class="mt-sm">
        <el-table-column prop="patient_id" label="患者ID" width="110" />
        <el-table-column prop="audit_type_code" label="类型" width="150" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" width="90"><template #default="{ row }"><StatusTag :value="row.status" /></template></el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-card>

    <!-- 推送进度 -->
    <el-card v-if="taskProg" shadow="never" class="section-card">
      <div class="section-title">
        任务进度
        <el-tag size="small" :type="String(taskProg.status) === 'completed' ? 'success' : String(taskProg.status) === 'failed' ? 'danger' : 'warning'">{{ taskProg.status }}</el-tag>
      </div>
      <el-progress :percentage="Number(taskProg.total) ? Math.round(Number(taskProg.processed) / Number(taskProg.total) * 100) : 0" />
      <div class="prog-text">
        已处理 {{ taskProg.processed }}/{{ taskProg.total }}，
        成功 {{ taskProg.success }}，
        失败 {{ taskProg.failed }}，
        跳过 {{ taskProg.skipped || 0 }}
      </div>
    </el-card>

    <!-- 推送结果 -->
    <el-card v-if="pushResult" shadow="never" class="section-card">
      <div class="section-title">推送结果</div>
      <el-alert v-if="pushResult.dry_run" type="info" :closable="false" show-icon>
        预览模式：{{ pushResult.total_patients }} 名患者，{{ pushResult.total_records }} 条记录。
      </el-alert>
      <el-alert v-else type="success" :closable="false" show-icon>
        成功 {{ pushResult.success || 0 }}，失败 {{ pushResult.failed || 0 }}。
        <span v-if="pushResult.used_bulk_executor"> 并发 {{ pushResult.parallel_workers_effective || 1 }}，空结果重试 {{ pushResult.empty_retry_total || 0 }}。</span>
      </el-alert>

      <!-- 节点分配统计 -->
      <div v-if="targetMetricsRows.length" class="mt-sm">
        <div class="section-sub-title">Dify 节点分配统计</div>
        <el-table :data="targetMetricsRows" border size="small" style="width: 100%">
          <el-table-column prop="name" label="节点" min-width="120" />
          <el-table-column prop="selected" label="分配" width="70" align="center" />
          <el-table-column prop="success" label="成功" width="60" align="center" />
          <el-table-column prop="failed" label="失败" width="60" align="center" />
          <el-table-column prop="empty" label="空结果" width="70" align="center" />
        </el-table>
      </div>

      <!-- 结果列表 -->
      <el-table v-if="pushResultRows.length" :data="pagedResultRows" border size="small" class="mt-sm" style="width: 100%">
        <el-table-column prop="patient_id" label="患者ID" width="100" />
        <el-table-column prop="patient_name" label="姓名" width="80" />
        <el-table-column label="状态" width="80"><template #default="{ row }"><StatusTag :value="String(row.status)" /></template></el-table-column>
        <el-table-column prop="error_msg" label="错误" min-width="150" show-overflow-tooltip />
      </el-table>
      <el-pagination v-if="pushResultRows.length > resultPageSize" v-model:current-page="resultPage" :page-size="resultPageSize" :total="pushResultRows.length" layout="prev, pager, next" class="mt-sm" />
    </el-card>

    <!-- 预检弹窗 -->
    <el-dialog v-model="precheckVisible" title="预检结果" width="500px">
      <template v-if="precheckResult">
        <div class="stat-grid">
          <div class="stat-box"><span>总候选</span><b>{{ precheckResult.total_candidates || 0 }}</b></div>
          <div class="stat-box stat-ok"><span>可推送</span><b>{{ precheckResult.pushable || 0 }}</b></div>
          <div class="stat-box"><span>跳过</span><b>{{ precheckResult.skipped || 0 }}</b></div>
        </div>
        <div v-if="precheckSkipRows.length" class="mt-sm">
          <strong>跳过原因：</strong>
          <div v-for="r in precheckSkipRows" :key="r.label" class="skip-row">{{ r.label }}：{{ r.count }}</div>
        </div>
      </template>
      <template #footer>
        <el-button @click="precheckVisible = false">关闭</el-button>
        <el-button type="primary" @click="precheckVisible = false; doPush()">确认推送</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mode-tabs { margin-bottom: 12px; }
.push-steps { margin-bottom: 16px; }
.section-card { margin-bottom: 12px; border-radius: 10px; }
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.section-sub-title { font-size: 13px; font-weight: 600; color: var(--el-text-color-secondary); margin: 12px 0 8px; }
.form-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.form-item { display: flex; flex-direction: column; gap: 4px; }
.form-item label { font-size: 12px; color: var(--el-text-color-secondary); }
.form-item-wide { grid-column: span 2; }
.switch-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: center; }
.advanced-collapse { margin-top: 8px; }
.action-bar { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; padding: 10px 12px; background: var(--el-fill-color-light); border-radius: 8px; }
.mt-sm { margin-top: 8px; }
.stat-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 8px; }
.stat-box { padding: 10px; border: 1px solid var(--el-border-color); border-radius: 8px; text-align: center; }
.stat-box span { display: block; font-size: 11px; color: var(--el-text-color-secondary); }
.stat-box b { font-size: 18px; }
.stat-ok b { color: var(--el-color-success); }
.stat-fail b { color: var(--el-color-danger); }
.hash-line { margin-top: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
.hash-line code { font-family: monospace; }
.error-line { margin-top: 8px; color: var(--el-color-danger); font-size: 12px; }
.prog-text { margin-top: 8px; font-size: 13px; color: var(--el-text-color-secondary); }
.skip-row { font-size: 13px; color: var(--el-text-color-secondary); padding: 2px 0; }
</style>
