<script setup lang="ts">
import { onActivated, onMounted, reactive, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import { apiDownload, apiGet, apiPost, triggerBrowserDownload } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { copyTextToClipboard } from '@/utils/clipboard'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildPatientQcExportParams, canQuickAction, diagnosisValue, feedbackInfo, formatEvidence, hasEvidence, normalizePushLogId } from '@/utils/patient-qc-contracts'
import { parsePatientRouteQuery } from '@/utils/route-filters'

interface PatientRow {
  patient_id: string
  visit_number: string
  patient_name: string
  admission_no: string
  dept: string
  discharge_dept_name: string
  highest_severity: string
  high_count: number
  medium_count: number
  issue_count: number
  pending_count: number
  resolved_count: number
  audit_type_count: number
  push_log_count: number
  latest_push_time: string
}

interface DetailData {
  patient: Record<string, unknown>
  summary: Record<string, unknown>
  audit_groups: Array<Record<string, unknown>>
}

const loading = ref(false)
const error = ref('')
const items = ref<PatientRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  patient_id: '',
  patient_name: '',
  admission_no: '',
  visit_number: '',
  dept: '',
  discharge_dept_name: '',
  severity: '',
  status: '',
  date_from: '' as string,
  date_to: '' as string,
})

const deptOptions = ref<Array<{ value: string; label: string }>>([])

const pageStats = computed(() => {
  const s = { high: 0, medium: 0, pending: 0, resolved: 0 }
  for (const r of items.value) {
    s.high += r.high_count || 0
    s.medium += r.medium_count || 0
    s.pending += r.pending_count || 0
    s.resolved += r.resolved_count || 0
  }
  return s
})

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<DetailData | null>(null)
const detailError = ref('')
const lastDetailRequest = ref<{ patientId: string; visitNumber: string; dept: string } | null>(null)
const detailIndex = ref(-1)
const detailSection = ref('overview')
const otherReasonVisible = ref(false)
const otherReasonText = ref('')
const otherReasonLogId = ref(0)
const actionLoading = ref<Record<number, boolean>>({})
const otherSubmitting = ref(false)
const exportLoading = ref(false)
const selectedRow = ref<PatientRow | null>(null)
const route = useRoute(); const router = useRouter()
const routeSource = ref(false)
let routeSignature = ''

function rowKey(row: PatientRow): string {
  return `${row.patient_id}__${row.visit_number}__${row.dept || ''}`
}

function selectRow(row: PatientRow) {
  selectedRow.value = row
}

function isSelected(row: PatientRow): boolean {
  return !!selectedRow.value && rowKey(selectedRow.value) === rowKey(row)
}

const issueList = computed(() => {
  if (!detail.value?.audit_groups) return []
  const issues: Array<Record<string, unknown>> = []
  for (const g of detail.value.audit_groups) {
    const logs = (g.logs as Array<Record<string, unknown>>) || []
    for (const log of logs) {
      const dims = (log.dimensions as Array<Record<string, unknown>>) || []
      for (const dim of dims) {
        const st = String(dim.status || '')
        if (['fail', 'risk', 'warning', 'warn'].includes(st) || dim.issue_summary) {
          issues.push({
            push_log_id: normalizePushLogId(log),
            dimension_name: dim.dimension || dim.dimension_name || dim.dimension_code,
            dimension_code: dim.dimension_code,
            audit_type_name: g.audit_type_name,
            severity: dim.severity || log.severity || g.severity,
            status: st,
            issue_summary: dim.issue_summary,
            explanation: dim.explanation,
            recommendation: dim.recommendation,
            medical_evidence: dim.medical_evidence,
            nursing_evidence: dim.nursing_evidence,
            push_time: log.push_time,
          })
        }
      }
    }
  }
  const order: Record<string, number> = { high: 0, medium: 1, low: 2 }
  return issues.sort((a, b) => (order[String(a.severity)] ?? 3) - (order[String(b.severity)] ?? 3))
})

const pendingIssues = computed(() => issueList.value.slice(0, 5))

// 维度问题页签：严重度筛选
const dimSeverityFilter = ref('')
const dimFilters = computed(() => {
  const counts: Record<string, number> = { high: 0, medium: 0, low: 0 }
  for (const i of issueList.value) {
    const s = String(i.severity || '')
    if (s in counts) counts[s] += 1
  }
  return [
    { key: '', label: '全部', count: issueList.value.length },
    { key: 'high', label: '高危', count: counts.high },
    { key: 'medium', label: '中危', count: counts.medium },
    { key: 'low', label: '低危', count: counts.low },
  ]
})
const filteredIssueList = computed(() => {
  if (!dimSeverityFilter.value) return issueList.value
  return issueList.value.filter((i) => String(i.severity || '') === dimSeverityFilter.value)
})

function riskLevel(): string {
  if (!detail.value) return ''
  const s = detail.value.summary
  if (Number(s.high_count) > 0) return 'high'
  if (Number(s.medium_count) > 0) return 'medium'
  if (Number(s.issue_count) > 0) return 'low'
  return ''
}

/** 维度状态英文码 → 中文文案与标签类型，便于非技术用户阅读 */
function dimStatusText(status: unknown): string {
  const s = String(status || '').toLowerCase()
  if (s === 'fail') return '发现不一致'
  if (s === 'risk' || s === 'warning' || s === 'warn') return '需关注'
  if (s === 'pass' || s === 'ok' || s === 'success') return '通过'
  if (s === 'unknown' || s === 'pending') return '未评'
  return s || '未知'
}
function dimStatusTagType(status: unknown): 'danger' | 'warning' | 'success' | 'info' {
  const s = String(status || '').toLowerCase()
  if (s === 'fail') return 'danger'
  if (s === 'risk' || s === 'warning' || s === 'warn') return 'warning'
  if (s === 'pass' || s === 'ok' || s === 'success') return 'success'
  return 'info'
}

/** 概览页：各审计类型的最新总体结论（有内容才展示） */
const overviewConclusions = computed(() => {
  if (!detail.value?.audit_groups) return []
  return detail.value.audit_groups
    .map((g) => ({
      audit_type_name: String(g.audit_type_name || g.audit_type_code || ''),
      severity: String(g.severity || ''),
      text: String(g.overall_qc_summary || g.overall_conclusion || ''),
    }))
    .filter((c) => c.text)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, unknown> = { page: page.value, limit: pageSize.value }
    for (const [k, v] of Object.entries(filters)) {
      if (v) params[k] = v
    }
    const data = await apiGet<{ items: PatientRow[]; total: number }>('/patient-qc/patients', { params })
    items.value = data.items || []
    total.value = data.total || 0
    // 列表刷新后尽量保持选中；否则默认选中首行，避免右侧空白
    if (selectedRow.value) {
      const keep = items.value.find((r) => rowKey(r) === rowKey(selectedRow.value as PatientRow))
      selectedRow.value = keep || items.value[0] || null
    } else {
      selectedRow.value = items.value[0] || null
    }
  } catch (e) {
    error.value = toUserMessage(e, '加载患者质控失败')
  } finally {
    loading.value = false
  }
}

async function loadDeptOptions() {
  try {
    const data = await apiGet<{ items?: Array<string | { value: string; count?: number }> }>('/logs/dept-options')
    deptOptions.value = (data.items || []).map((d) => {
      if (typeof d === 'string') return { value: d, label: d }
      return { value: d.value, label: `${d.value} (${d.count || 0})` }
    })
  } catch { /* 静默 */ }
}

function resetFilters() {
  Object.assign(filters, {
    patient_id: '', patient_name: '', admission_no: '', visit_number: '',
    dept: '', discharge_dept_name: '', severity: '', status: '', date_from: '', date_to: '',
  })
  page.value = 1
  routeSource.value = false
  routeSignature = '{}'
  void router.replace({ query: {} })
  void load()
}

function onSearch() { page.value = 1; void load() }

async function openDetail(row: PatientRow) {
  selectRow(row)
  detailIndex.value = items.value.findIndex(
    (r) => r.patient_id === row.patient_id && r.visit_number === row.visit_number)
  await fetchDetail(row.patient_id, row.visit_number, row.dept)
}

async function fetchDetail(patientId: string, visitNumber: string, dept: string) {
  lastDetailRequest.value = { patientId, visitNumber, dept }
  detailVisible.value = true
  detailLoading.value = true
  detailError.value = ''
  detail.value = null
  detailSection.value = 'overview'
  try {
    detail.value = (await apiGet<DetailData>('/patient-qc/patient-detail', {
      params: { patient_id: patientId, visit_number: visitNumber, dept },
    })) as DetailData
  } catch (e) {
    detailError.value = toUserMessage(e, '加载详情失败')
  } finally {
    detailLoading.value = false
  }
}

const hasPrev = computed(() => detailIndex.value > 0)
const hasNext = computed(() => detailIndex.value >= 0 && detailIndex.value < items.value.length - 1)
async function prevDetail() {
  if (!hasPrev.value) return
  detailIndex.value--
  const r = items.value[detailIndex.value]
  await fetchDetail(r.patient_id, r.visit_number, r.dept)
}
async function nextDetail() {
  if (!hasNext.value) return
  detailIndex.value++
  const r = items.value[detailIndex.value]
  await fetchDetail(r.patient_id, r.visit_number, r.dept)
}

async function quickAction(pushLogId: number, action: string) {
  if (!Number.isSafeInteger(pushLogId) || pushLogId <= 0 || actionLoading.value[pushLogId]) return
  if (otherSubmitting.value && otherReasonLogId.value === pushLogId) return
  if (action === 'rectified' || action === 'pending') { try { await ElMessageBox.confirm(action === 'rectified' ? '确认标记为已整改？' : '确认标记为未处理？', '请确认', { type: 'warning' }) } catch { return } }
  actionLoading.value[pushLogId] = true
  try {
    await apiPost('/patient-qc/feedback/quick-action', { push_log_id: pushLogId, action })
    ElMessage.success(action === 'rectified' ? '已标记整改' : '已标记未处理')
    if (detail.value) {
      const p = detail.value.patient
      await fetchDetail(String(p.patient_id), String(p.visit_number), String(p.dept))
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '操作失败'))
  } finally {
    actionLoading.value[pushLogId] = false
  }
}

function openOtherReason(pushLogId: number) {
  if (!Number.isSafeInteger(pushLogId) || pushLogId <= 0 || actionLoading.value[pushLogId]) return
  otherReasonLogId.value = pushLogId
  otherReasonText.value = ''
  otherReasonVisible.value = true
}

async function submitOtherReason() {
  if (!otherReasonText.value.trim()) {
    ElMessage.warning('请填写原因')
    return
  }
  if (otherSubmitting.value) return
  otherSubmitting.value = true
  try {
    await apiPost('/patient-qc/feedback/quick-action', {
      push_log_id: otherReasonLogId.value,
      action: 'other',
      reason: otherReasonText.value,
    })
    ElMessage.success('已提交')
    otherReasonVisible.value = false
    if (detail.value) {
      const p = detail.value.patient
      await fetchDetail(String(p.patient_id), String(p.visit_number), String(p.dept))
    }
  } catch (e) {
    ElMessage.error(toUserMessage(e, '提交失败'))
  } finally { otherSubmitting.value = false }
}

async function copyPatientId(pid: string) {
  if (!pid) return
  // 非 HTTPS / 无剪贴板权限时降级 execCommand，与质控记录页复制行为一致
  const ok = await copyTextToClipboard(pid)
  if (ok) ElMessage.success('已复制患者ID')
  else ElMessage.warning('复制失败，请手动复制')
}

async function exportQcSummary() {
  if (exportLoading.value) return
  if (total.value <= 0) {
    ElMessage.warning('当前筛选条件下无可导出数据')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将导出当前筛选条件下全部 ${total.value} 位患者的质控结果汇总（含高危/中危问题明细与整改建议，支持历史患者），不限当前页，是否继续？`,
      '导出质控汇总',
      { type: 'warning' },
    )
    exportLoading.value = true
    const { blob, filename } = await apiDownload('/patient-qc/export/qc-summary', {
      params: buildPatientQcExportParams(filters),
      timeout: 600_000,
    })
    triggerBrowserDownload(blob, filename)
    ElMessage.success('导出完成')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '导出失败'))
  } finally {
    exportLoading.value = false
  }
}

async function exportXlsx() {
  if (exportLoading.value) return
  if (total.value <= 0) {
    ElMessage.warning('当前筛选条件下无可导出数据')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将导出当前筛选条件下全部 ${total.value} 位患者的完整临床文书汇总（病历/护理/检验/检查/手术/出院记录，支持历史患者；人数较多时可能需要 5-15 分钟，请耐心等待），是否继续？`,
      '导出临床文书汇总',
      { type: 'warning' },
    )
    exportLoading.value = true
    const { blob, filename } = await apiDownload('/patient-qc/export/patient-visit-summary', {
      params: buildPatientQcExportParams(filters),
      timeout: 1_200_000,
    })
    triggerBrowserDownload(blob, filename)
    ElMessage.success('导出完成')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '导出失败'))
  } finally {
    exportLoading.value = false
  }
}

function syncRouteQuery() {
  const signature = JSON.stringify(route.query)
  if (signature === routeSignature) return false
  routeSignature = signature
  const parsed = parsePatientRouteQuery(route.query)
  Object.assign(filters, { patient_id: '', patient_name: '', admission_no: '', visit_number: '', dept: '', discharge_dept_name: '', severity: '', status: '', date_from: '', date_to: '' }, parsed.filters)
  routeSource.value = parsed.source === 'workbench'
  page.value = 1
  void load()
  return true
}
onMounted(() => { syncRouteQuery(); void loadDeptOptions() })
onActivated(() => { syncRouteQuery() })
watch(() => route.fullPath, () => { syncRouteQuery() })
</script>

<template>
  <div class="page-pq">
    <PageHeader title="患者质控" description="按患者维度查看质控结果、维度详情和整改闭环。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-dropdown :disabled="total <= 0 || exportLoading" @command="(cmd: string) => cmd === 'qc' ? exportQcSummary() : exportXlsx()">
          <el-button type="primary" :loading="exportLoading" :disabled="total <= 0">
            导出汇总<el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="qc">导出质控汇总（含问题明细，支持历史患者）</el-dropdown-item>
              <el-dropdown-item command="visit">导出临床文书汇总（仅当前就诊名单）</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </template>
    </PageHeader>

    <div class="stat-bar">
      <span class="stat-item">总病例 <b>{{ total }}</b></span>
      <span class="stat-item stat-danger">高危 <b>{{ pageStats.high }}</b></span>
      <span class="stat-item stat-warn">中危 <b>{{ pageStats.medium }}</b></span>
      <span class="stat-item">待处理 <b>{{ pageStats.pending }}</b></span>
      <span class="stat-item stat-ok">已闭环 <b>{{ pageStats.resolved }}</b></span>
      <span class="stat-note">（高危/中危/待处理/已闭环为本页统计）</span>
    </div>
    <el-alert v-if="routeSource" title="来自工作台的联动筛选" type="info" :closable="false" class="route-hint" />

    <div class="filter-row">
      <el-input v-model="filters.patient_id" clearable placeholder="患者ID" size="small" style="width: 110px" @keyup.enter="onSearch" />
      <el-input v-model="filters.patient_name" clearable placeholder="患者姓名" size="small" style="width: 110px" @keyup.enter="onSearch" />
      <el-input v-model="filters.admission_no" clearable placeholder="住院号" size="small" style="width: 120px" @keyup.enter="onSearch" />
      <el-input v-model="filters.visit_number" clearable placeholder="住院次" size="small" style="width: 80px" @keyup.enter="onSearch" />
      <el-select v-model="filters.dept" clearable filterable placeholder="在院科室" size="small" style="width: 150px" @change="onSearch">
        <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
      </el-select>
      <el-select v-model="filters.discharge_dept_name" clearable filterable placeholder="出院科室" size="small" style="width: 150px" @change="onSearch">
        <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
      </el-select>
      <el-select v-model="filters.severity" clearable placeholder="严重度" size="small" style="width: 100px" @change="onSearch">
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="状态" size="small" style="width: 100px" @change="onSearch">
        <el-option label="待处理" value="pending" />
        <el-option label="已整改" value="rectified" />
        <el-option label="已关闭" value="closed" />
      </el-select>
      <el-date-picker v-model="filters.date_from" type="date" value-format="YYYY-MM-DD" placeholder="开始日期" size="small" style="width: 135px" @change="onSearch" />
      <el-date-picker v-model="filters.date_to" type="date" value-format="YYYY-MM-DD" placeholder="结束日期" size="small" style="width: 135px" @change="onSearch" />
      <el-button size="small" @click="resetFilters">重置</el-button>
    </div>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <EmptyState v-else-if="!loading && !items.length" description="暂无患者质控记录" />
    <div v-else class="pq-body">
      <div class="pq-table-wrap">
        <el-table
          v-loading="loading"
          :data="items"
          stripe
          border
          size="small"
          class="pq-table"
          highlight-current-row
          :row-class-name="(params: { row: PatientRow; rowIndex: number }) => (isSelected(params.row) ? 'is-selected-row' : '')"
          @row-click="(row: PatientRow) => selectRow(row)"
        >
          <el-table-column label="患者姓名" min-width="108" fixed>
            <template #default="{ row }">
              <div><b>{{ row.patient_name }}</b></div>
              <div class="cell-sub">{{ row.patient_id }}</div>
            </template>
          </el-table-column>
          <el-table-column prop="visit_number" label="住院次" width="68" align="center" />
          <el-table-column prop="admission_no" label="住院号" min-width="100" show-overflow-tooltip />
          <el-table-column prop="dept" label="在院科室" min-width="120" show-overflow-tooltip />
          <el-table-column prop="discharge_dept_name" label="出院科室" min-width="120" show-overflow-tooltip />
          <el-table-column label="最高严重度" width="92" align="center">
            <template #default="{ row }"><RiskTag :value="row.highest_severity" /></template>
          </el-table-column>
          <el-table-column label="高危" width="58" align="center">
            <template #default="{ row }"><span :class="{ 'count-danger': row.high_count > 0 }">{{ row.high_count }}</span></template>
          </el-table-column>
          <el-table-column prop="medium_count" label="中危" width="58" align="center" />
          <el-table-column label="问题数" width="64" align="center">
            <template #default="{ row }"><b>{{ row.issue_count }}</b></template>
          </el-table-column>
          <el-table-column prop="pending_count" label="待处理" width="68" align="center" />
          <el-table-column prop="resolved_count" label="已闭环" width="68" align="center" />
          <el-table-column prop="audit_type_count" label="类型数" width="68" align="center" />
          <el-table-column prop="push_log_count" label="推送次" width="68" align="center" />
          <el-table-column label="最近推送" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">{{ formatDateTime(row.latest_push_time) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="72" fixed="right" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openDetail(row as PatientRow)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :page-sizes="[20, 50, 100]"
            :total="total"
            layout="total, sizes, prev, pager, next"
            @current-change="load"
            @size-change="() => { page = 1; load() }"
          />
        </div>
      </div>

      <!-- 右侧患者摘要：填满空白区，对齐旧系统 -->
      <aside class="pq-side">
        <template v-if="selectedRow">
          <div class="pq-side-title">患者摘要</div>
          <div class="pq-side-name">
            <b>{{ selectedRow.patient_name }}</b>
            <RiskTag :value="selectedRow.highest_severity" />
          </div>
          <div class="pq-side-grid">
            <div class="pq-side-item"><span>患者ID</span><b>{{ selectedRow.patient_id }}</b></div>
            <div class="pq-side-item"><span>住院号</span><b>{{ displayText(selectedRow.admission_no) }}</b></div>
            <div class="pq-side-item"><span>住院次</span><b>{{ selectedRow.visit_number }}</b></div>
            <div class="pq-side-item"><span>在院科室</span><b>{{ displayText(selectedRow.dept) }}</b></div>
            <div class="pq-side-item"><span>出院科室</span><b>{{ displayText(selectedRow.discharge_dept_name) }}</b></div>
            <div class="pq-side-item"><span>最近推送</span><b>{{ formatDateTime(selectedRow.latest_push_time) }}</b></div>
          </div>
          <div class="pq-side-metrics">
            <div class="pq-metric"><span>问题数</span><b>{{ selectedRow.issue_count || 0 }}</b></div>
            <div class="pq-metric danger"><span>高危</span><b>{{ selectedRow.high_count || 0 }}</b></div>
            <div class="pq-metric warn"><span>中危</span><b>{{ selectedRow.medium_count || 0 }}</b></div>
            <div class="pq-metric"><span>待处理</span><b>{{ selectedRow.pending_count || 0 }}</b></div>
            <div class="pq-metric ok"><span>已闭环</span><b>{{ selectedRow.resolved_count || 0 }}</b></div>
            <div class="pq-metric"><span>推送次</span><b>{{ selectedRow.push_log_count || 0 }}</b></div>
          </div>
          <div class="pq-side-actions">
            <el-button type="primary" size="small" @click="openDetail(selectedRow)">查看详情</el-button>
            <el-button size="small" @click="copyPatientId(selectedRow.patient_id)">复制患者ID</el-button>
          </div>
        </template>
        <div v-else class="pq-side-empty">
          <div class="pq-side-title">患者摘要</div>
          <p>点击左侧列表中的患者，在此查看摘要信息。</p>
        </div>
      </aside>
    </div>

    <DetailDrawer v-model="detailVisible" title="患者质控详情" :loading="detailLoading" size="80%">
      <template #actions>
        <el-button v-if="hasPrev" link @click="prevDetail">上一条</el-button>
        <span v-if="detailIndex >= 0" class="nav-pos">{{ detailIndex + 1 }} / {{ items.length }}</span>
        <el-button v-if="hasNext" link @click="nextDetail">下一条</el-button>
      </template>

      <ErrorState v-if="detailError && !detailLoading" :message="detailError" @retry="() => lastDetailRequest && fetchDetail(lastDetailRequest.patientId, lastDetailRequest.visitNumber, lastDetailRequest.dept)" />
      <template v-if="detail">
        <div class="pq-header">
          <div class="pq-title">
            <h3>{{ detail.patient.patient_name }}</h3>
            <RiskTag :value="riskLevel()" />
          </div>
          <div class="pq-meta">
            {{ detail.patient.patient_id }} ｜ 住院号 {{ displayText(detail.patient.admission_no) }} ｜ {{ detail.patient.visit_number }} 次 ｜ {{ displayText(detail.patient.dept) }}
          </div>
          <div class="pq-counts">
            <span>问题 <b>{{ detail.summary.issue_count }}</b></span>
            <span class="count-danger">高危 <b>{{ detail.summary.high_count }}</b></span>
            <span>中危 <b>{{ detail.summary.medium_count }}</b></span>
            <span>待处理 <b>{{ detail.summary.pending_count }}</b></span>
          </div>
        </div>

        <div class="pq-nav">
          <el-button size="small" :type="detailSection === 'overview' ? 'primary' : 'default'" @click="detailSection = 'overview'">概览</el-button>
          <el-button size="small" :type="detailSection === 'dimensions' ? 'primary' : 'default'" @click="detailSection = 'dimensions'">维度问题</el-button>
          <el-button size="small" :type="detailSection === 'logs' ? 'primary' : 'default'" @click="detailSection = 'logs'">推送记录</el-button>
          <el-button size="small" :type="detailSection === 'patient' ? 'primary' : 'default'" @click="detailSection = 'patient'">患者信息</el-button>
        </div>

        <div v-show="detailSection === 'overview'">
          <div class="metric-cards">
            <div class="metric-card"><span>审计类型</span><b>{{ detail.summary.audit_type_count }}</b></div>
            <div class="metric-card"><span>推送次数</span><b>{{ detail.summary.push_log_count }}</b></div>
            <div class="metric-card"><span>问题数</span><b>{{ detail.summary.issue_count }}</b></div>
            <div class="metric-card"><span>高危</span><b class="count-danger">{{ detail.summary.high_count }}</b></div>
            <div class="metric-card"><span>中危</span><b>{{ detail.summary.medium_count }}</b></div>
            <div class="metric-card"><span>待处理</span><b>{{ detail.summary.pending_count }}</b></div>
          </div>
          <div class="ov-grid">
            <el-card v-if="overviewConclusions.length" shadow="never">
              <template #header>各类型最新总体结论</template>
              <div v-for="(c, i) in overviewConclusions" :key="i" class="conclusion-item">
                <div class="conclusion-head">
                  <el-tag size="small" type="info">{{ c.audit_type_name }}</el-tag>
                  <RiskTag :value="c.severity" />
                </div>
                <div class="conclusion-text">{{ c.text }}</div>
              </div>
            </el-card>
            <el-card v-if="pendingIssues.length" shadow="never">
              <template #header>待处理重点问题</template>
              <div v-for="(issue, i) in pendingIssues" :key="i" class="issue-item">
                <div class="issue-head">
                  <RiskTag :value="String(issue.severity || '')" />
                  <span class="issue-dim">{{ issue.dimension_name }}</span>
                  <el-tag size="small" type="info">{{ issue.audit_type_name }}</el-tag>
                </div>
                <div class="issue-text">{{ issue.issue_summary }}</div>
              </div>
            </el-card>
            <div v-if="!overviewConclusions.length && !pendingIssues.length" class="empty-text">该患者暂无总体结论与待处理问题</div>
          </div>
        </div>

        <div v-show="detailSection === 'dimensions'">
          <div v-if="!issueList.length" class="empty-text">暂无问题维度</div>
          <template v-else>
            <!-- 严重度筛选条：一眼看清分布，点击过滤 -->
            <div class="dim-filter">
              <span
                v-for="f in dimFilters" :key="f.key"
                class="dim-chip" :class="[{ active: dimSeverityFilter === f.key }, f.key]"
                @click="dimSeverityFilter = f.key"
              >{{ f.label }} <b>{{ f.count }}</b></span>
            </div>
            <div v-if="!filteredIssueList.length" class="empty-text">该级别暂无问题</div>
            <div v-for="(issue, i) in filteredIssueList" :key="i" class="dim-card">
              <div class="dim-head">
                <RiskTag :value="String(issue.severity || '')" />
                <span class="dim-name">{{ issue.dimension_name }}</span>
                <el-tag size="small" :type="dimStatusTagType(issue.status)">{{ dimStatusText(issue.status) }}</el-tag>
                <el-tag size="small" type="info">{{ issue.audit_type_name }}</el-tag>
              </div>
              <div v-if="issue.issue_summary" class="dim-issue">{{ issue.issue_summary }}</div>
              <!-- 长文本（说明/建议/证据）默认折叠，避免满屏文字 -->
              <details v-if="issue.explanation || issue.recommendation || hasEvidence(issue.medical_evidence) || hasEvidence(issue.nursing_evidence)" class="dim-more">
                <summary>详细分析</summary>
                <div v-if="issue.explanation" class="dim-rec"><span class="dim-rec-label">说明</span>{{ issue.explanation }}</div>
                <div v-if="issue.recommendation" class="dim-rec"><span class="dim-rec-label">建议</span>{{ issue.recommendation }}</div>
                <div v-if="hasEvidence(issue.medical_evidence)" class="dim-rec"><span class="dim-rec-label">病历证据</span><pre>{{ formatEvidence(issue.medical_evidence) }}</pre></div>
                <div v-if="hasEvidence(issue.nursing_evidence)" class="dim-rec"><span class="dim-rec-label">护理证据</span><pre>{{ formatEvidence(issue.nursing_evidence) }}</pre></div>
              </details>
            </div>
          </template>
        </div>

        <div v-show="detailSection === 'logs'">
          <div v-if="!detail.audit_groups.length" class="empty-text">暂无推送记录</div>
          <el-collapse v-else :model-value="detail.audit_groups.map((_, i) => i)">
            <el-collapse-item v-for="(g, gi) in detail.audit_groups" :key="gi" :name="gi">
              <template #title>
                <div class="group-title">
                  <span class="group-name">{{ g.audit_type_name }}</span>
                  <RiskTag :value="String(g.severity || '')" />
                  <span class="group-meta">{{ (g.logs as unknown[])?.length }} 次推送 · 最近 {{ formatDateTime(String(g.latest_push_time || '')) }}</span>
                </div>
              </template>
              <div v-for="(log, li) in (g.logs as Array<Record<string, unknown>>)" :key="String(normalizePushLogId(log) || `${gi}-${li}-${log.push_time || ''}`)" class="log-card">
                <div class="log-head">
                  <span class="log-time">{{ formatDateTime(log.push_time as string) }}</span>
                  <StatusTag :value="String(log.status || '')" />
                  <RiskTag :value="String(log.severity || '')" />
                  <StatusTag :value="feedbackInfo(log).status" />
                  <span v-if="feedbackInfo(log).assigned_to_name" class="cell-sub">负责人：{{ feedbackInfo(log).assigned_to_name }}</span>
                  <span v-if="feedbackInfo(log).feedback_text" class="cell-sub log-fb">{{ feedbackInfo(log).feedback_text }}</span>
                </div>
                <div v-if="log.overall_conclusion" class="log-conclusion">{{ log.overall_conclusion }}</div>
                <div v-if="((log.dimensions as Array<Record<string, unknown>>) || []).length" class="dim-mini-list">
                  <div v-for="(dim, di) in ((log.dimensions as Array<Record<string, unknown>>) || [])" :key="di" class="dim-mini">
                    <el-tag size="small" :type="dimStatusTagType(dim.status)" class="dim-mini-tag">{{ dimStatusText(dim.status) }}</el-tag>
                    <span class="dim-mini-name">{{ dim.dimension || dim.dimension_name }}</span>
                    <span v-if="dim.issue_summary" class="dim-mini-text">{{ dim.issue_summary }}</span>
                  </div>
                </div>
                <div v-if="canQuickAction(feedbackInfo(log).status)" class="log-actions"><template v-if="normalizePushLogId(log)"><el-button size="small" type="success" :disabled="!!actionLoading[normalizePushLogId(log) as number] || otherSubmitting" :loading="actionLoading[normalizePushLogId(log) as number]" @click="quickAction(normalizePushLogId(log) as number, 'rectified')">已整改</el-button><el-button size="small" :disabled="!!actionLoading[normalizePushLogId(log) as number] || otherSubmitting" :loading="actionLoading[normalizePushLogId(log) as number]" @click="quickAction(normalizePushLogId(log) as number, 'pending')">标记未处理</el-button><el-button size="small" :disabled="!!actionLoading[normalizePushLogId(log) as number] || otherSubmitting" @click="openOtherReason(normalizePushLogId(log) as number)">其他原因</el-button></template><template v-else><el-button size="small" disabled>已整改</el-button><el-button size="small" disabled>标记未处理</el-button><el-button size="small" disabled>其他原因</el-button><span class="cell-sub">缺少推送日志ID，无法操作</span></template>
                </div>
              </div>
            </el-collapse-item>
          </el-collapse>
        </div>

        <div v-show="detailSection === 'patient'">
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="患者ID">{{ detail.patient.patient_id }}</el-descriptions-item>
            <el-descriptions-item label="姓名">{{ detail.patient.patient_name }}</el-descriptions-item>
            <el-descriptions-item label="住院次">{{ detail.patient.visit_number }}</el-descriptions-item>
            <el-descriptions-item label="住院号">{{ displayText(detail.patient.admission_no) }}</el-descriptions-item>
            <el-descriptions-item label="在院科室">{{ displayText(detail.patient.dept) }}</el-descriptions-item>
            <el-descriptions-item label="入院科室">{{ displayText(detail.patient.admission_dept_name) }}</el-descriptions-item>
            <el-descriptions-item label="出院科室">{{ displayText(detail.patient.discharge_dept_name) }}</el-descriptions-item>
            <el-descriptions-item label="入院日期">{{ displayText(detail.patient.admission_date) }}</el-descriptions-item>
            <el-descriptions-item label="出院日期">{{ displayText(detail.patient.discharge_date) }}</el-descriptions-item>
            <el-descriptions-item label="管床医师">{{ displayText(detail.patient.attending_doctor_name) }}</el-descriptions-item>
            <el-descriptions-item label="护士长">{{ displayText(detail.patient.nurse_head_name) }}</el-descriptions-item>
            <el-descriptions-item label="手术">{{ displayText(detail.patient.surgery) }}</el-descriptions-item>
            <el-descriptions-item label="入院诊断" :span="2">{{ displayText(detail.patient.admission_diagnosis) }}</el-descriptions-item>
            <el-descriptions-item label="出院主诊断" :span="2">{{ diagnosisValue(detail.patient) }}</el-descriptions-item>
          </el-descriptions>
          <div class="mt">
            <el-button size="small" @click="copyPatientId(String(detail.patient.patient_id))">复制患者ID</el-button>
          </div>
        </div>
      </template>
    </DetailDrawer>

    <el-dialog v-model="otherReasonVisible" title="其他原因" width="400px" :show-close="!otherSubmitting" :close-on-click-modal="!otherSubmitting" :close-on-press-escape="!otherSubmitting">
      <el-input v-model="otherReasonText" type="textarea" :rows="3" :disabled="otherSubmitting" placeholder="请填写原因（必填）" />
      <template #footer>
        <el-button :disabled="otherSubmitting" @click="otherReasonVisible = false">取消</el-button>
        <el-button type="primary" :loading="otherSubmitting" @click="submitOtherReason">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-pq { width: 100%; min-width: 0; }
.stat-bar { display: flex; gap: 16px; margin-bottom: 10px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 8px; flex-wrap: wrap; align-items: center; }
.stat-item { font-size: 13px; color: var(--el-text-color-secondary); }
.stat-item b { font-size: 15px; margin-left: 4px; }
.stat-danger b { color: var(--el-color-danger); }
.stat-warn b { color: var(--el-color-warning); }
.stat-ok b { color: var(--el-color-success); }
.stat-note { font-size: 11px; color: var(--el-text-color-disabled); }
.filter-row { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.count-danger { color: var(--el-color-danger); font-weight: 600; }

/* 左右分栏：表格 + 患者摘要，消除右侧大块空白 */
.pq-body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 14px;
  align-items: start;
  width: 100%;
  min-width: 0;
}
.pq-table-wrap { min-width: 0; width: 100%; }
.pq-table { width: 100% !important; }
.pq-table :deep(.el-table__body),
.pq-table :deep(.el-table__header) { width: 100% !important; }
.pq-table :deep(.is-selected-row > td.el-table__cell) {
  background: #eff6ff !important;
}
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.pq-side {
  position: sticky;
  top: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  background: #fff;
  padding: 14px;
  min-height: 320px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}
.pq-side-title {
  font-size: 13px;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 10px;
}
.pq-side-name {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.pq-side-name b { font-size: 16px; }
.pq-side-grid {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
}
.pq-side-item {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  padding: 6px 8px;
  border-radius: 8px;
  background: #f8fafc;
}
.pq-side-item span { color: var(--el-text-color-secondary); flex-shrink: 0; }
.pq-side-item b {
  font-weight: 600;
  text-align: right;
  word-break: break-all;
  color: #0f172a;
}
.pq-side-metrics {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  margin-bottom: 14px;
}
.pq-metric {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  padding: 8px 10px;
  background: #fafafa;
}
.pq-metric span {
  display: block;
  font-size: 11px;
  color: var(--el-text-color-secondary);
  margin-bottom: 2px;
}
.pq-metric b { font-size: 18px; color: #0f172a; }
.pq-metric.danger b { color: var(--el-color-danger); }
.pq-metric.warn b { color: var(--el-color-warning); }
.pq-metric.ok b { color: var(--el-color-success); }
.pq-side-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pq-side-actions .el-button { width: 100%; margin: 0; }
.pq-side-empty p {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

@media (max-width: 1200px) {
  .pq-body { grid-template-columns: minmax(0, 1fr) 240px; }
}
@media (max-width: 960px) {
  .pq-body { grid-template-columns: 1fr; }
  .pq-side { position: static; }
}
.pq-header { margin-bottom: 10px; }
.pq-title { display: flex; align-items: center; gap: 8px; }
.pq-title h3 { margin: 0; font-size: 18px; }
.pq-meta { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 4px; }
.pq-counts { display: flex; gap: 16px; margin-top: 6px; font-size: 13px; }
.pq-counts b { margin-left: 4px; }
.pq-nav { display: flex; gap: 4px; margin-bottom: 10px; border-bottom: 1px solid var(--el-border-color); padding-bottom: 8px; }
.nav-pos { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 8px; }
/* 概览：指标条单行紧凑 + 结论/待处理双列并排，尽量一屏展示 */
.metric-cards { display: grid; grid-template-columns: repeat(6, 1fr); gap: 8px; }
.metric-card { padding: 6px 8px; border: 1px solid var(--el-border-color); border-radius: 8px; display: flex; align-items: baseline; justify-content: space-between; gap: 6px; }
.metric-card span { font-size: 12px; color: var(--el-text-color-secondary); }
.metric-card b { font-size: 18px; }
.ov-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; align-items: start; }
.ov-grid > .el-card:only-child { grid-column: 1 / -1; }
.ov-grid > .empty-text { grid-column: 1 / -1; }
.ov-grid :deep(.el-card__header) { padding: 8px 12px; font-size: 13px; }
.ov-grid :deep(.el-card__body) { padding: 6px 12px; max-height: 48vh; overflow: auto; }
@media (max-width: 900px) {
  .metric-cards { grid-template-columns: repeat(3, 1fr); }
  .ov-grid { grid-template-columns: 1fr; }
}
.issue-item { padding: 6px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.issue-item:last-child { border-bottom: none; }
.conclusion-item { padding: 6px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.conclusion-item:last-child { border-bottom: none; }
.conclusion-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.conclusion-text { font-size: 13px; color: var(--el-text-color-regular); line-height: 1.6; white-space: pre-wrap; }
.issue-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.issue-dim { font-weight: 600; font-size: 13px; }
.issue-text { font-size: 12px; color: var(--el-text-color-secondary); }
.empty-text { text-align: center; padding: 30px; color: var(--el-text-color-disabled); }
.dim-filter { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.dim-chip { cursor: pointer; font-size: 12px; padding: 3px 12px; border-radius: 99px; border: 1px solid var(--el-border-color); color: var(--el-text-color-secondary); background: var(--el-fill-color-light); user-select: none; }
.dim-chip b { margin-left: 2px; }
.dim-chip:hover { border-color: var(--el-color-primary-light-5); }
.dim-chip.active { border-color: var(--el-color-primary); color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.dim-chip.high.active { border-color: var(--el-color-danger); color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.dim-chip.medium.active { border-color: var(--el-color-warning); color: var(--el-color-warning); background: var(--el-color-warning-light-9); }
.dim-chip.low.active { border-color: var(--el-color-info); color: var(--el-color-info); background: var(--el-color-info-light-9); }
.dim-card { padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; margin-bottom: 8px; }
.dim-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.dim-name { font-weight: 600; }
.dim-issue { font-size: 13px; margin-bottom: 4px; line-height: 1.6; }
.dim-more { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.dim-more summary { cursor: pointer; color: var(--el-color-primary); }
.dim-rec { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.dim-rec-label { font-weight: 600; color: var(--el-text-color-regular); margin-right: 6px; }
.dim-rec pre { white-space: pre-wrap; word-break: break-all; margin: 4px 0 0; padding: 6px 8px; background: var(--el-fill-color-light); border-radius: 6px; font-size: 12px; }
.group-title { display: flex; align-items: center; gap: 8px; }
.group-name { font-weight: 600; font-size: 13px; }
.group-meta { font-size: 12px; color: var(--el-text-color-secondary); }
.log-card { padding: 10px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; margin-bottom: 8px; }
.log-head { display: flex; align-items: center; gap: 8px; font-size: 12px; margin-bottom: 6px; flex-wrap: wrap; }
.log-time { font-weight: 600; font-size: 13px; color: var(--el-text-color-primary); font-variant-numeric: tabular-nums; }
.log-fb { max-width: 40%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.log-conclusion { font-size: 13px; margin-bottom: 6px; padding: 6px 10px; border-left: 3px solid var(--el-color-primary-light-5); background: var(--el-fill-color-light); border-radius: 0 6px 6px 0; line-height: 1.6; }
.dim-mini-list { border-top: 1px dashed var(--el-border-color-lighter); padding-top: 6px; margin-top: 2px; }
.dim-mini { font-size: 12px; padding: 4px 0; display: flex; align-items: baseline; gap: 8px; }
.dim-mini + .dim-mini { border-top: 1px dashed var(--el-border-color-extra-light); }
.dim-mini-tag { flex-shrink: 0; }
.dim-mini-name { font-weight: 500; flex-shrink: 0; }
.dim-mini-text { color: var(--el-text-color-secondary); line-height: 1.5; }
.log-actions { margin-top: 8px; display: flex; gap: 6px; justify-content: flex-end; border-top: 1px dashed var(--el-border-color-lighter); padding-top: 8px; }
.mt { margin-top: 12px; }
.evidence pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; }
</style>
