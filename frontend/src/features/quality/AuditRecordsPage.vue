<script setup lang="ts">
import { onActivated, onMounted, reactive, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/base/PageHeader.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiDelete, apiDownload, apiGet, apiPost, triggerBrowserDownload } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import type { PaginatedResponse, PushLogListItem } from '@/api/types'
import { displayText, formatDateTime } from '@/utils/format'
import { copyTextToClipboard } from '@/utils/clipboard'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { canEditPushMarker } from '@/utils/rbac'
import { parseAuditRouteQuery } from '@/utils/route-filters'

// ── 状态 ──
const loading = ref(false)
const auth = useAuthStore()
const canEditMarker = computed(() => canEditPushMarker(auth.roleName))
const error = ref('')
const items = ref<PushLogListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

// ── 筛选器（对齐旧前端 11 字段）──
const filters = reactive({
  status: '',
  severity: '',
  alert_level: '',
  dept: '',
  discharge_dept_name: '',
  patient_name: '',
  patient_id: '',
  audit_type_code: '',
  date_from: '' as string,
  date_to: '' as string,
  hide_superseded: false,
  skip_reason: '',
})

// ── 下拉选项 ──
const deptOptions = ref<Array<{ value: string; label: string }>>([])
const auditTypeOptions = ref<Array<{ value: string; label: string }>>([])

// ── 快捷标签 ──
const quickTag = ref('')
function applyQuickTag(tag: string) {
  if (tag === quickTag.value) {
    resetFilters()
    return
  }
  quickTag.value = tag
  // 先重置
  filters.status = ''
  filters.alert_level = ''
  filters.skip_reason = ''
  filters.date_from = ''
  filters.date_to = ''
  if (tag === 'today') {
    const t = new Date().toISOString().slice(0, 10)
    filters.date_from = t
    filters.date_to = t
  } else if (tag === 'failed') {
    filters.status = 'failed'
  } else if (tag === 'skipped') {
    filters.status = 'skipped'
  } else if (tag === 'high') {
    filters.alert_level = 'red'
  }
  page.value = 1
  void load()
}

// ── 统计条 ──
const stats = reactive({ total: 0, success: 0, skipped: 0, failed: 0, unreviewed: 0, empty: 0 })
const skipReasonChips = ref<Array<{ reason: string; label: string; count: number; percent: number }>>([])

// ── 批量选择 ──
const selectedIds = ref<number[]>([])
function onSelectionChange(rows: PushLogListItem[]) {
  selectedIds.value = rows.map((r) => r.id)
}

// ── 详情 ──
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)
const detailIndex = ref(-1)
const marker = reactive({ reviewed_flag: 0, manual_override: 0, skip_reason: '', reviewed_at: '', reviewed_by: '' })
const markerSaving = ref(false)
const route = useRoute(); const router = useRouter()
const routeSource = ref(false)
const routeLogId = ref<number | null>(null)
let routeSignature = ''

// ── label helpers ──
function alertLevelLabel(a: string): string {
  const m: Record<string, string> = { red: '红灯', yellow: '黄灯', blue: '蓝灯', gray: '灰灯' }
  return m[a] || ''
}
function auditTypeLabel(row: Record<string, unknown>): string {
  return String(row.audit_type_name || row.audit_type_code || '')
}
function skipReasonLabel(r: string): string {
  const m: Record<string, string> = {
    unreviewed_pending: '已推送未复核',
    rectified_suppressed: '已整改抑制',
    already_succeeded: '已有成功记录',
    empty_lab_exam: '检验检查数据为空',
    empty_progress_nursing: '病程护理记录为空',
    empty_both_sides: '双源均为空',
    insufficient_surgery_docs: '围手术期文书不足',
    cancelled: '用户取消',
  }
  return m[r] || r || ''
}
function failureReason(row: Record<string, unknown>): string {
  return String(row.failure_reason || row.error_msg || skipReasonLabel(String(row.skip_reason || '')) || '')
}

// ── 数据加载 ──
async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, unknown> = {
      page: page.value,
      limit: pageSize.value,
    }
    for (const [k, v] of Object.entries(filters)) {
      if (v !== '' && v !== false && v !== null && v !== undefined) {
        params[k] = v
      }
    }
    // 并发：列表 + 统计
    const [data, skipStats, failedResp] = await Promise.all([
      apiGet<PaginatedResponse<PushLogListItem>>('/logs', { params }),
      apiGet<{ total_skipped: number; items: Array<{ reason: string; label: string; count: number }> }>('/logs/skip-reasons/stats', {
        params: {
          date_from: filters.date_from || undefined,
          date_to: filters.date_to || undefined,
          dept: filters.dept || undefined,
          audit_type_code: filters.audit_type_code || undefined,
        },
      }).catch(() => ({ total_skipped: 0, items: [] })),
      apiGet<{ total: number }>('/logs', { params: { status: 'failed', limit: 1 } }).catch(() => ({ total: 0 })),
    ])
    items.value = data.items || []
    total.value = data.total || 0
    if (routeLogId.value) {
      const id = routeLogId.value
      routeLogId.value = null
      detailIndex.value = items.value.findIndex((item) => item.id === id)
      await fetchDetail(id)
    }

    // 统计条
    stats.total = data.total || 0
    stats.failed = (failedResp as { total?: number }).total || 0
    stats.skipped = skipStats.total_skipped || 0
    stats.success = Math.max(0, stats.total - stats.failed - stats.skipped)
    const unreviewed = skipStats.items?.find((i) => i.reason === 'unreviewed_pending')
    stats.unreviewed = unreviewed?.count || 0
    stats.empty = (skipStats.items || []).filter((i) => i.reason.startsWith('empty_')).reduce((s, i) => s + i.count, 0)

    // 跳过原因 chips
    skipReasonChips.value = (skipStats.items || []).map((i) => ({
      reason: i.reason,
      label: i.label || skipReasonLabel(i.reason),
      count: i.count,
      percent: skipStats.total_skipped ? Math.round((i.count / skipStats.total_skipped) * 100) : 0,
    }))
  } catch (e) {
    error.value = toUserMessage(e, '加载质控记录失败')
  } finally {
    loading.value = false
  }
}

async function loadFilterOptions() {
  try {
    const data = await apiGet<{
      dept_options?: Array<string | { value: string; count?: number }>
      audit_type_options?: Array<string | { value: string; label?: string }>
    }>('/logs/filters/options')
    deptOptions.value = (data.dept_options || []).map((d) => {
      if (typeof d === 'string') return { value: d, label: d }
      return { value: d.value, label: `${d.value} (${d.count || 0})` }
    })
    auditTypeOptions.value = (data.audit_type_options || []).map((a) => {
      if (typeof a === 'string') return { value: a, label: a }
      return { value: a.value, label: a.label || a.value }
    })
  } catch { /* 静默 */ }
}

function resetFilters() {
  quickTag.value = ''
  Object.assign(filters, {
    status: '', severity: '', alert_level: '', dept: '', discharge_dept_name: '',
    patient_name: '', patient_id: '', audit_type_code: '',
    date_from: '', date_to: '', hide_superseded: false, skip_reason: '',
  })
  page.value = 1
  routeSource.value = false
  routeLogId.value = null
  routeSignature = '{}'
  void router.replace({ query: {} })
  void load()
}

function onSearch() {
  quickTag.value = ''
  page.value = 1
  void load()
}

function onSkipChipClick(reason: string) {
  filters.skip_reason = filters.skip_reason === reason ? '' : reason
  page.value = 1
  void load()
}

// ── 行操作 ──
async function retrySingle(row: PushLogListItem) {
  try {
    await ElMessageBox.confirm(`确认重推该记录？(ID: ${row.id})`, '重推确认', { type: 'warning' })
    await apiPost(`/logs/${row.id}/retry`)
    ElMessage.success('重推已提交')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '重推失败'))
  }
}

async function deleteSingle(row: PushLogListItem) {
  try {
    await ElMessageBox.confirm(`确认删除该记录？此操作不可恢复。(ID: ${row.id})`, '删除确认', { type: 'error' })
    await apiDelete(`/logs/${row.id}`)
    ElMessage.success('已删除')
    detailVisible.value = false
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '删除失败'))
  }
}

async function copyPatientId(row: Record<string, unknown>) {
  const pid = String(row.patient_id || '')
  if (!pid) return
  // 与报文区复制一致：统一走 copyText（含非 HTTPS / 无权限时的 execCommand 降级）
  await copyText(pid, '患者ID')
}

async function openPrintableReport(row: PushLogListItem) {
  try {
    const tokenData = await apiPost<{ token?: string }>(`/report/${row.id}/print-token`)
    if (tokenData.token) {
      window.open(`/report/${row.id}?token=${tokenData.token}`, '_blank', 'noopener')
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '生成打印报告失败'))
  }
}

function openStandaloneDetail(row: Record<string, unknown>) {
  const id = Number(row.id)
  if (!Number.isSafeInteger(id) || id <= 0) {
    ElMessage.warning('缺少有效日志ID，无法打开独立详情')
    return
  }
  window.open(`/log_detail.html?id=${encodeURIComponent(String(id))}`, '_blank', 'noopener,noreferrer')
}

// ── 批量操作 ──
async function retrySelected() {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量重推 ${selectedIds.value.length} 条记录？`, '批量重推', { type: 'warning' })
    await apiPost('/push/retry', { log_ids: selectedIds.value })
    ElMessage.success('批量重推已提交')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '批量重推失败'))
  }
}

async function deleteSelected() {
  if (!selectedIds.value.length) return
  try {
    await ElMessageBox.confirm(`确认批量删除 ${selectedIds.value.length} 条记录？不可恢复。`, '批量删除', { type: 'error' })
    await apiDelete('/logs/bulk/delete', { data: { log_ids: selectedIds.value } })
    ElMessage.success('批量删除完成')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '批量删除失败'))
  }
}

// ── 导出 ──
async function exportCsv() {
  try {
    const params: Record<string, unknown> = { page: 1, limit: 5000 }
    for (const [k, v] of Object.entries(filters)) {
      if (v !== '' && v !== false && v !== null && v !== undefined) params[k] = v
    }
    const { blob, filename } = await apiDownload('/logs/export/csv', { params })
    triggerBrowserDownload(blob, filename)
    ElMessage.success('导出已开始（后端会记录导出审计）')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '导出失败'))
  }
}

// ── 详情 ──
async function openDetail(row: PushLogListItem) {
  detailIndex.value = items.value.findIndex((i) => i.id === row.id)
  await fetchDetail(row.id)
}

async function fetchDetail(id: number) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  payloadTab.value = 'request'
  try {
    detail.value = (await apiGet(`/logs/${id}`)) as Record<string, unknown>
    const saved = await apiGet<Record<string, unknown>>(`/logs/${id}/marker`)
    Object.assign(marker, {
      reviewed_flag: Number(saved.reviewed_flag || 0),
      manual_override: Number(saved.manual_override || 0),
      skip_reason: String(saved.skip_reason || ''),
      reviewed_at: String(saved.reviewed_at || ''),
      reviewed_by: String(saved.reviewed_by || ''),
    })
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function saveMarker() {
  if (!detail.value || markerSaving.value) return
  try {
    await ElMessageBox.confirm('确认更新人工复核与手动覆盖标记？', '标记更新确认', { type: 'warning' })
    markerSaving.value = true
    await apiPost(`/logs/${Number(detail.value.id)}/marker`, {
      reviewed_flag: marker.reviewed_flag,
      manual_override: marker.manual_override,
      skip_reason: marker.skip_reason,
    })
    ElMessage.success('标记已更新')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '标记更新失败'))
  } finally {
    markerSaving.value = false
  }
}

const hasPrev = computed(() => detailIndex.value > 0)
const hasNext = computed(() => detailIndex.value >= 0 && detailIndex.value < items.value.length - 1)

async function prevDetail() {
  if (!hasPrev.value) return
  detailIndex.value--
  await fetchDetail(items.value[detailIndex.value].id)
}
async function nextDetail() {
  if (!hasNext.value) return
  detailIndex.value++
  await fetchDetail(items.value[detailIndex.value].id)
}

// ── 详情派生数据 ──
const detailDimensions = computed(() => {
  if (!detail.value) return []
  const ar = detail.value.audit_result as { dimensions?: Array<Record<string, unknown>> } | undefined
  if (Array.isArray(ar?.dimensions) && ar!.dimensions!.length) return ar!.dimensions!
  // 兼容 stored_audit.dimensions
  const stored = detail.value.stored_audit as { dimensions?: Array<Record<string, unknown>> } | undefined
  return Array.isArray(stored?.dimensions) ? stored!.dimensions! : []
})
const detailConclusion = computed(() => {
  if (!detail.value) return null
  const ar = detail.value.audit_result as { conclusion?: Record<string, unknown> } | undefined
  if (ar?.conclusion && typeof ar.conclusion === 'object') return ar.conclusion
  const stored = detail.value.stored_audit as { conclusion?: Record<string, unknown> } | undefined
  return stored?.conclusion && typeof stored.conclusion === 'object' ? stored.conclusion : null
})
const detailOverallConclusion = computed(() => {
  if (!detail.value) return ''
  return String(detail.value.overall_conclusion || (detailConclusion.value?.overall_conclusion as string) || '')
})

/** 推送报文 / Dify 返回：便于排障分析（对齐旧 log_detail） */
const payloadTab = ref('request')

function prettyJson(value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'string') {
    const t = value.trim()
    if (!t) return ''
    try {
      return JSON.stringify(JSON.parse(t), null, 2)
    } catch {
      return value
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

const requestJsonPretty = computed(() => prettyJson(detail.value?.request_json))
const responseJsonPretty = computed(() => {
  if (!detail.value) return ''
  return prettyJson(detail.value.response_json || detail.value.ai_result)
})
const rawDebugPretty = computed(() => {
  if (!detail.value) return ''
  if (detail.value.raw_debug) return prettyJson(detail.value.raw_debug)
  // 兜底：无 raw_debug 时拼装常用调试字段
  return prettyJson({
    response_json: detail.value.response_json || null,
    ai_result: detail.value.ai_result || null,
    parse_status: detail.value.parse_status || null,
    parse_error: detail.value.parse_error || null,
    workflow_run_id: detail.value.workflow_run_id || null,
    task_id: detail.value.task_id || null,
  })
})
const mrTextPretty = computed(() => String(detail.value?.mr_text || '').trim())
const hasPayloadSection = computed(() =>
  !!(requestJsonPretty.value || responseJsonPretty.value || mrTextPretty.value || rawDebugPretty.value),
)

async function copyText(text: string, label: string) {
  const content = String(text || '').trim()
  if (!content) {
    ElMessage.warning(`${label}为空，无法复制`)
    return
  }
  // 复制逻辑统一走 utils/clipboard（含非 HTTPS / 无权限时的 execCommand 降级）
  const ok = await copyTextToClipboard(content)
  if (ok) ElMessage.success(`${label}已复制`)
  else ElMessage.warning('当前浏览器不支持复制')
}

function syncRouteQuery() {
  const signature = JSON.stringify(route.query)
  if (signature === routeSignature) return false
  routeSignature = signature
  const parsed = parseAuditRouteQuery(route.query)
  Object.assign(filters, { status: '', severity: '', alert_level: '', dept: '', discharge_dept_name: '', patient_name: '', patient_id: '', audit_type_code: '', date_from: '', date_to: '', hide_superseded: false, skip_reason: '' }, parsed.filters)
  routeSource.value = parsed.source === 'workbench' || parsed.source === 'task-progress'
  routeLogId.value = parsed.logId
  page.value = 1
  void load()
  return true
}
onMounted(() => { syncRouteQuery(); void loadFilterOptions() })
onActivated(() => { syncRouteQuery() })
watch(() => route.fullPath, () => { syncRouteQuery() })
</script>

<template>
  <div class="page-audit">
    <PageHeader title="质控记录" description="推送/质控结果列表，兼容历史 NULL，导出记录审计。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="exportCsv">导出 CSV</el-button>
        <el-button :disabled="!selectedIds.length" @click="retrySelected">批量重推 ({{ selectedIds.length }})</el-button>
        <el-button :disabled="!selectedIds.length" type="danger" plain @click="deleteSelected">批量删除</el-button>
      </template>
    </PageHeader>
    <el-alert v-if="routeSource" :title="route.query.source === 'task-progress' ? '来自任务进度的联动筛选' : '来自工作台的联动筛选'" type="info" :closable="false" class="route-hint" />

    <!-- 快捷标签 -->
    <div class="quick-tags">
      <el-button size="small" :type="quickTag === 'today' ? 'primary' : 'default'" @click="applyQuickTag('today')">今日</el-button>
      <el-button size="small" :type="quickTag === 'failed' ? 'primary' : 'default'" @click="applyQuickTag('failed')">失败</el-button>
      <el-button size="small" :type="quickTag === 'skipped' ? 'primary' : 'default'" @click="applyQuickTag('skipped')">跳过</el-button>
      <el-button size="small" :type="quickTag === 'high' ? 'primary' : 'default'" @click="applyQuickTag('high')">高危</el-button>
      <el-button size="small" @click="resetFilters">重置</el-button>
    </div>

    <!-- 统计条 -->
    <div class="stat-bar">
      <span class="stat-item">总记录 <b>{{ stats.total }}</b></span>
      <span class="stat-item stat-success">成功 <b>{{ stats.success }}</b></span>
      <span class="stat-item stat-skip">跳过 <b>{{ stats.skipped }}</b></span>
      <span class="stat-item stat-fail">失败 <b>{{ stats.failed }}</b></span>
      <span class="stat-item stat-warn">未复核 <b>{{ stats.unreviewed }}</b></span>
      <span v-if="stats.empty" class="stat-item stat-muted">数据为空 <b>{{ stats.empty }}</b></span>
    </div>

    <!-- 跳过原因 chips -->
    <div v-if="skipReasonChips.length" class="skip-chips">
      <span
        v-for="chip in skipReasonChips"
        :key="chip.reason"
        class="skip-chip"
        :class="{ active: filters.skip_reason === chip.reason }"
        @click="onSkipChipClick(chip.reason)"
      >
        {{ chip.label }} <b>{{ chip.count }}</b> ({{ chip.percent }}%)
      </span>
    </div>

    <!-- 筛选器 -->
    <div class="filter-row">
      <el-select v-model="filters.status" clearable placeholder="状态" size="small" style="width: 110px" @change="onSearch">
        <el-option label="成功" value="success" />
        <el-option label="失败" value="failed" />
        <el-option label="跳过" value="skipped" />
      </el-select>
      <el-select v-model="filters.alert_level" clearable placeholder="预警灯号" size="small" style="width: 110px" @change="onSearch">
        <el-option label="红灯" value="red" />
        <el-option label="黄灯" value="yellow" />
        <el-option label="蓝灯" value="blue" />
        <el-option label="灰灯" value="gray" />
      </el-select>
      <el-select v-model="filters.severity" clearable placeholder="严重度" size="small" style="width: 100px" @change="onSearch">
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-select v-model="filters.dept" clearable filterable placeholder="在院科室" size="small" style="width: 160px" @change="onSearch">
        <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
      </el-select>
      <el-select v-model="filters.discharge_dept_name" clearable filterable placeholder="出院科室" size="small" style="width: 160px" @change="onSearch">
        <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
      </el-select>
      <el-input v-model="filters.patient_name" clearable placeholder="患者姓名" size="small" style="width: 120px" @keyup.enter="onSearch" @clear="onSearch" />
      <el-input v-model="filters.patient_id" clearable placeholder="患者ID" size="small" style="width: 120px" @keyup.enter="onSearch" @clear="onSearch" />
      <el-select v-model="filters.audit_type_code" clearable filterable placeholder="核查类型" size="small" style="width: 180px" @change="onSearch">
        <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-date-picker v-model="filters.date_from" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" size="small" style="width: 140px" @change="onSearch" />
      <el-date-picker v-model="filters.date_to" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" size="small" style="width: 140px" @change="onSearch" />
      <el-checkbox v-model="filters.hide_superseded" @change="onSearch">隐藏已覆盖</el-checkbox>
    </div>

    <!-- 表格 -->
    <el-table
      v-loading="loading"
      :data="items"
      stripe
      border
      size="small"
      style="width: 100%"
      @selection-change="onSelectionChange"
    >
      <el-table-column type="selection" width="36" />
      <el-table-column label="推送时间" width="135">
        <template #default="{ row }">{{ formatDateTime(row.push_time) }}</template>
      </el-table-column>
      <el-table-column label="患者" width="120" fixed>
        <template #default="{ row }">
          <div><b>{{ row.patient_name }}</b></div>
          <div class="cell-sub">{{ row.patient_id }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="dept" label="在院科室" width="110" show-overflow-tooltip />
      <el-table-column prop="discharge_dept_name" label="出院科室" width="110" show-overflow-tooltip />
      <el-table-column label="核查类型" width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag size="small" type="info">{{ auditTypeLabel(row) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <span v-if="row.superseded_by" class="status-pill status-superseded">终末覆盖</span>
          <StatusTag v-else :value="row.status" />
        </template>
      </el-table-column>
      <el-table-column label="严重度" width="70">
        <template #default="{ row }"><RiskTag :value="row.severity" /></template>
      </el-table-column>
      <el-table-column prop="retry_count" label="重试" width="50" />
      <el-table-column label="失败/跳过原因" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ failureReason(row) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openDetail(row as PushLogListItem)">详情</el-button>
          <el-dropdown trigger="click" @command="(cmd: string) => {
            if (cmd === 'retry') retrySingle(row as PushLogListItem)
            else if (cmd === 'print') openPrintableReport(row as PushLogListItem)
            else if (cmd === 'copy') copyPatientId(row)
            else if (cmd === 'standalone') openStandaloneDetail(row)
            else if (cmd === 'delete') deleteSingle(row as PushLogListItem)
          }">
            <el-button link size="small">更多<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="retry">重推</el-dropdown-item>
                <el-dropdown-item command="print">打印报告</el-dropdown-item>
                <el-dropdown-item command="copy">复制患者ID</el-dropdown-item>
                <el-dropdown-item command="standalone">推送详情（JSON）</el-dropdown-item>
                <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100, 200]"
        :total="total"
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="() => { page = 1; load() }"
      />
    </div>

    <!-- 详情抽屉 -->
    <DetailDrawer v-model="detailVisible" title="质控记录详情" :loading="detailLoading" size="70%">
      <template #actions>
        <el-button v-if="hasPrev" link @click="prevDetail">上一条</el-button>
        <span v-if="detailIndex >= 0" class="nav-pos">{{ detailIndex + 1 }} / {{ items.length }}</span>
        <el-button v-if="hasNext" link @click="nextDetail">下一条</el-button>
      </template>

      <template v-if="detail">
        <!-- 基本信息 -->
        <el-descriptions :column="3" border size="small" class="detail-grid">
          <el-descriptions-item label="记录ID">{{ detail.id }}</el-descriptions-item>
          <el-descriptions-item label="推送时间">{{ formatDateTime(detail.push_time as string) }}</el-descriptions-item>
          <el-descriptions-item label="查询日期">{{ displayText(detail.query_date) }}</el-descriptions-item>
          <el-descriptions-item label="患者">{{ detail.patient_name }}（{{ detail.patient_id }}）</el-descriptions-item>
          <el-descriptions-item label="住院号">{{ displayText(detail.admission_no) }}</el-descriptions-item>
          <el-descriptions-item label="触发方式">{{ displayText(detail.trigger_type) }}</el-descriptions-item>
          <el-descriptions-item label="在院科室">{{ displayText(detail.dept) }}</el-descriptions-item>
          <el-descriptions-item label="出院科室">{{ displayText(detail.discharge_dept_name) }}</el-descriptions-item>
          <el-descriptions-item label="核查类型">{{ auditTypeLabel(detail) }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <span v-if="detail.superseded_by" class="status-pill status-superseded">终末覆盖</span>
            <StatusTag v-else :value="String(detail.status)" />
          </el-descriptions-item>
          <el-descriptions-item label="严重度"><RiskTag :value="String(detail.severity)" /></el-descriptions-item>
          <el-descriptions-item label="风险分">{{ detail.risk_score }}</el-descriptions-item>
          <el-descriptions-item label="不一致">{{ detail.inconsistency === 1 ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="预警灯号">{{ alertLevelLabel(String(detail.alert_level || (detailConclusion?.alert_level as string) || '')) }}</el-descriptions-item>
          <el-descriptions-item label="解析状态">{{ displayText(detail.parse_status) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detail.elapsed_ms != null ? `${detail.elapsed_ms} ms` : '—' }}</el-descriptions-item>
          <el-descriptions-item label="AI 版本">{{ displayText(detail.ai_version) }}</el-descriptions-item>
          <el-descriptions-item label="Workflow Run">{{ displayText(detail.workflow_run_id) }}</el-descriptions-item>
          <el-descriptions-item label="Task ID">{{ displayText(detail.task_id) }}</el-descriptions-item>
          <el-descriptions-item label="人工复核">{{ Number(detail.reviewed_flag || 0) === 1 ? '已复核' : '未复核' }}</el-descriptions-item>
          <el-descriptions-item label="手动覆盖">{{ Number(detail.manual_override || 0) === 1 ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="跳过原因">{{ displayText(detail.skip_reason_label || detail.skip_reason) }}</el-descriptions-item>
        </el-descriptions>

        <!-- 错误信息 -->
        <el-alert v-if="detail.error_msg" class="mt" type="error" :closable="false" :title="String(detail.error_msg)" />
        <el-alert
          v-if="detail.parse_error"
          class="mt"
          type="warning"
          :closable="false"
          :title="`解析错误：${String(detail.parse_error)}`"
        />

        <el-card shadow="never" class="mt marker-card">
          <template #header>人工复核标记</template>
          <div v-if="canEditMarker" class="marker-grid">
            <el-checkbox v-model="marker.reviewed_flag" :true-value="1" :false-value="0">已人工复核</el-checkbox>
            <el-checkbox v-model="marker.manual_override" :true-value="1" :false-value="0">手动覆盖</el-checkbox>
            <el-input v-model="marker.skip_reason" maxlength="200" show-word-limit placeholder="跳过原因/备注" />
            <el-button type="primary" :loading="markerSaving" @click="saveMarker">保存标记</el-button>
          </div>
          <div v-else class="marker-readonly">
            <StatusTag :value="Number(marker.reviewed_flag) === 1 ? 'success' : 'pending'" />
            <span>手动覆盖：{{ Number(marker.manual_override) === 1 ? '是' : '否' }}</span>
            <span>跳过原因：{{ displayText(marker.skip_reason) }}</span>
          </div>
          <div class="marker-meta">{{ marker.reviewed_at ? `最近复核：${formatDateTime(marker.reviewed_at)} · ${marker.reviewed_by || '—'}` : '尚未记录复核时间' }}</div>
        </el-card>

        <!-- 总体结论 -->
        <el-card v-if="detailOverallConclusion" class="mt" shadow="never">
          <template #header>总体结论</template>
          <div>{{ detailOverallConclusion }}</div>
          <div v-if="detailConclusion?.overall_qc_summary" class="qc-summary">{{ detailConclusion.overall_qc_summary }}</div>
          <div v-if="(detailConclusion?.focus_items as unknown[])?.length" class="focus-items">
            <strong>重点关注：</strong>
            <el-tag v-for="(f, i) in (detailConclusion?.focus_items as unknown[])" :key="i" size="small" class="focus-tag">{{ f }}</el-tag>
          </div>
        </el-card>

        <!-- 落库维度 -->
        <el-card v-if="detailDimensions.length" class="mt" shadow="never">
          <template #header>质控维度（{{ detailDimensions.length }}）</template>
          <div v-for="(dim, idx) in detailDimensions" :key="idx" class="dim-card">
            <div class="dim-head">
              <span class="dim-name">{{ dim.dimension || dim.dimension_name || dim.dimension_code }}</span>
              <el-tag size="small" :type="(dim.status === 'fail') ? 'danger' : (dim.status === 'warn' || dim.status === 'warning') ? 'warning' : 'success'">
                {{ dim.status }}
              </el-tag>
              <RiskTag v-if="dim.severity" :value="String(dim.severity)" />
              <el-tag v-if="dim.alert_level" size="small" type="info">{{ alertLevelLabel(String(dim.alert_level)) }}</el-tag>
            </div>
            <div v-if="dim.issue_summary" class="dim-issue">{{ dim.issue_summary }}</div>
            <div v-if="dim.recommendation" class="dim-rec">建议：{{ dim.recommendation }}</div>
            <div v-if="(dim.medical_evidence as unknown[])?.length || (dim.nursing_evidence as unknown[])?.length" class="dim-evidence">
              <div v-if="(dim.medical_evidence as unknown[])?.length" class="evidence-col">
                <strong>病程证据：</strong>{{ (dim.medical_evidence as unknown[]).join('；') }}
              </div>
              <div v-if="(dim.nursing_evidence as unknown[])?.length" class="evidence-col">
                <strong>护理证据：</strong>{{ (dim.nursing_evidence as unknown[]).join('；') }}
              </div>
            </div>
          </div>
        </el-card>

        <!-- 推送报文 / Dify 返回（旧系统「消息推送」排障区） -->
        <el-card v-if="hasPayloadSection" class="mt payload-card" shadow="never">
          <template #header>
            <div class="payload-head">
              <div>
                <div class="payload-title">推送报文与 Dify 返回</div>
                <div class="payload-sub">记录发给 Dify 的请求 JSON、返回内容与原始主输入，便于分析解析/空数据/失败原因</div>
              </div>
              <el-button size="small" @click="openStandaloneDetail(detail)">打开完整详情页</el-button>
            </div>
          </template>
          <el-tabs v-model="payloadTab" type="border-card" class="payload-tabs">
            <el-tab-pane label="推送 JSON" name="request">
              <div class="payload-toolbar">
                <span class="payload-hint">request_json（结构化入参）</span>
                <el-button link type="primary" size="small" :disabled="!requestJsonPretty" @click="copyText(requestJsonPretty, '推送 JSON')">复制</el-button>
              </div>
              <pre v-if="requestJsonPretty" class="payload-pre">{{ requestJsonPretty }}</pre>
              <el-empty v-else description="无推送 JSON（历史记录可能未落库）" :image-size="64" />
            </el-tab-pane>
            <el-tab-pane label="Dify 响应" name="response">
              <div class="payload-toolbar">
                <span class="payload-hint">response_json / ai_result</span>
                <el-button link type="primary" size="small" :disabled="!responseJsonPretty" @click="copyText(responseJsonPretty, 'Dify 响应')">复制</el-button>
              </div>
              <pre v-if="responseJsonPretty" class="payload-pre">{{ responseJsonPretty }}</pre>
              <el-empty v-else description="无 Dify 响应内容" :image-size="64" />
            </el-tab-pane>
            <el-tab-pane label="主输入文本" name="mr_text">
              <div class="payload-toolbar">
                <span class="payload-hint">mr_text（送入工作流的主文本）</span>
                <el-button link type="primary" size="small" :disabled="!mrTextPretty" @click="copyText(mrTextPretty, '主输入文本')">复制</el-button>
              </div>
              <pre v-if="mrTextPretty" class="payload-pre">{{ mrTextPretty }}</pre>
              <el-empty v-else description="无主输入文本" :image-size="64" />
            </el-tab-pane>
            <el-tab-pane label="调试信息" name="debug">
              <div class="payload-toolbar">
                <span class="payload-hint">raw_debug（workflow_run_id / 解析状态等）</span>
                <el-button link type="primary" size="small" :disabled="!rawDebugPretty" @click="copyText(rawDebugPretty, '调试信息')">复制</el-button>
              </div>
              <pre v-if="rawDebugPretty" class="payload-pre">{{ rawDebugPretty }}</pre>
              <el-empty v-else description="无调试信息" :image-size="64" />
            </el-tab-pane>
          </el-tabs>
        </el-card>
        <el-alert
          v-else
          class="mt"
          type="info"
          :closable="false"
          title="本条记录未保存推送报文/响应（可能是跳过、历史数据或未落库）。可尝试打开完整详情页或重新推送后再查看。"
        />

        <!-- 操作 -->
        <div class="detail-actions mt">
          <el-button size="small" @click="copyPatientId(detail)">复制患者ID</el-button>
          <el-button size="small" @click="openStandaloneDetail(detail)">完整推送详情</el-button>
          <el-button size="small" @click="openPrintableReport(detail as PushLogListItem)">打印报告</el-button>
          <el-button size="small" type="warning" @click="retrySingle(detail as PushLogListItem)">重推</el-button>
          <el-button size="small" type="danger" plain @click="deleteSingle(detail as PushLogListItem)">删除</el-button>
        </div>
      </template>
    </DetailDrawer>
  </div>
</template>

<style scoped>
.quick-tags { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.stat-bar { display: flex; gap: 16px; margin-bottom: 10px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 8px; flex-wrap: wrap; }
.stat-item { font-size: 13px; color: var(--el-text-color-secondary); }
.stat-item b { font-size: 15px; color: var(--el-text-color-primary); margin-left: 4px; }
.stat-success b { color: var(--el-color-success); }
.stat-skip b { color: var(--el-color-info); }
.stat-fail b { color: var(--el-color-danger); }
.stat-warn b { color: var(--el-color-warning); }
.stat-muted b { color: var(--el-text-color-disabled); }

.skip-chips { display: flex; gap: 6px; margin-bottom: 10px; flex-wrap: wrap; }
.skip-chip { padding: 3px 10px; border: 1px solid var(--el-border-color); border-radius: 999px; font-size: 12px; cursor: pointer; color: var(--el-text-color-secondary); transition: all .2s; }
.skip-chip:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.skip-chip.active { background: var(--el-color-primary); color: #fff; border-color: var(--el-color-primary); }
.skip-chip.active b { color: #fff; }

.filter-row { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }

.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.status-pill { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 11px; }
.status-superseded { background: var(--el-fill-color-dark); color: var(--el-text-color-secondary); }

.mt { margin-top: 12px; }
.nav-pos { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 8px; }

.detail-grid { margin-bottom: 4px; }
.qc-summary { margin-top: 8px; color: var(--el-text-color-secondary); font-size: 13px; }
.focus-items { margin-top: 8px; display: flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.focus-tag { margin: 0; }

.dim-card { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.dim-card:last-child { border-bottom: none; }
.dim-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.dim-name { font-weight: 600; }
.dim-issue { font-size: 13px; color: var(--el-text-color-primary); margin-bottom: 4px; }
.dim-rec { font-size: 12px; color: var(--el-text-color-secondary); }
.dim-evidence { margin-top: 6px; display: flex; gap: 16px; font-size: 12px; }
.evidence-col { flex: 1; min-width: 0; color: var(--el-text-color-secondary); }

.detail-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.marker-grid { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.marker-grid .el-input { max-width: 320px; }
.marker-meta { margin-top: 8px; color: var(--el-text-color-secondary); font-size: 12px; }

.payload-card :deep(.el-card__header) { padding: 12px 16px; }
.payload-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }
.payload-title { font-weight: 700; font-size: 14px; }
.payload-sub { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.4; }
.payload-tabs { border: none; box-shadow: none; }
.payload-tabs :deep(.el-tabs__content) { padding: 12px 0 0; }
.payload-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.payload-hint { font-size: 12px; color: var(--el-text-color-secondary); }
.payload-pre {
  margin: 0;
  max-height: 420px;
  overflow: auto;
  padding: 12px 14px;
  border-radius: 10px;
  background: #0f172a;
  color: #e2e8f0;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
