<script setup lang="ts">
import { onActivated, onMounted, reactive, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiDelete, apiDownload, apiGet, apiPost, triggerBrowserDownload } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import { parseFeedbackRouteQuery } from '@/utils/route-filters'

interface FeedbackRow {
  log_id: number
  patient_id: string
  patient_name: string
  admission_no: string
  dept_id: number
  dept_name: string
  severity: string
  status: string
  audit_type_code: string
  audit_type_name: string
  alert_level: string
  closure_hours: number
  push_time: string
  reviewed_at: string
  issue_count: number
  overall_conclusion: string
}

const loading = ref(false)
const items = ref<FeedbackRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const viewMode = ref<'list' | 'kanban'>('list')

const filters = reactive({
  status: 'pending',
  severity: '',
  audit_type_code: '',
  dept_id: null as number | null,
  days: 30,
  keyword: '',
})

const stats = reactive({ total: 0, high: 0, pending: 0, acknowledged: 0, rectified: 0, closed: 0 })

const auditTypeOptions = ref<Array<{ value: string; label: string }>>([])
const deptOptions = ref<Array<{ id: number; name: string }>>([])
const selectedRows = ref<FeedbackRow[]>([])
const route = useRoute(); const router = useRouter()
const routeSource = ref(false)
let routeSignature = ''

// 详情
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)
const confirmForm = reactive({ action: 'acknowledged', review_comment: '' })

// 看板分组
const kanbanColumns = [
  { key: 'pending', label: '待处理' },
  { key: 'acknowledged', label: '已确认' },
  { key: 'rectified', label: '已整改' },
  { key: 'closed', label: '已关闭' },
]
const kanbanGroups = computed(() => {
  const groups: Record<string, FeedbackRow[]> = { pending: [], acknowledged: [], rectified: [], closed: [] }
  for (const item of items.value) {
    const st = item.status || 'pending'
    if (groups[st]) groups[st].push(item)
    else groups.pending.push(item)
  }
  return groups
})

const closureRate = computed(() => {
  if (!stats.total) return 0
  return Math.round((stats.closed / stats.total) * 100)
})

async function load() {
  loading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, limit: viewMode.value === 'kanban' ? 100 : pageSize.value }
    for (const [k, v] of Object.entries(filters)) {
      if (v !== '' && v !== null && v !== undefined) params[k] = v
    }
    if (viewMode.value === 'kanban') delete params.status
    const data = await apiGet<{ items?: FeedbackRow[]; total?: number; stats?: Record<string, number> }>('/qc/feedback/cases', { params })
    items.value = data.items || []
    total.value = data.total || 0
    const s = data.stats || {}
    stats.total = s.total || 0; stats.high = s.high || 0; stats.pending = s.pending || 0
    stats.acknowledged = s.acknowledged || 0; stats.rectified = s.rectified || 0; stats.closed = s.closed || 0
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载反馈列表失败'))
  } finally {
    loading.value = false
  }
}

function switchView(mode: 'list' | 'kanban') {
  viewMode.value = mode
  page.value = 1
  void load()
}

function resetFilters() {
  Object.assign(filters, { status: 'pending', severity: '', audit_type_code: '', dept_id: null, days: 30, keyword: '' })
  page.value = 1
  routeSource.value = false
  routeSignature = '{}'
  void router.replace({ query: {} })
  void load()
}

function onSearch() { page.value = 1; void load() }

async function openDetail(row: FeedbackRow | Record<string, unknown>) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  const r = row as FeedbackRow
  confirmForm.action = r.status === 'closed' ? 'closed' : 'acknowledged'
  confirmForm.review_comment = ''
  try {
    detail.value = await apiGet<Record<string, unknown>>(`/qc/feedback/cases/${r.log_id}`)
    const fb = (detail.value as Record<string, unknown>).feedback as Record<string, unknown> | undefined
    confirmForm.review_comment = String(fb?.feedback_text || '')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function submitConfirm() {
  if (!detail.value) return
  const logId = Number((detail.value as Record<string, unknown>).log_id)
  try {
    await apiPost(`/qc/feedback/cases/${logId}/confirm`, { action: confirmForm.action, review_comment: confirmForm.review_comment })
    ElMessage.success(confirmForm.action === 'closed' ? '已关闭' : '已确认')
    detailVisible.value = false
    void load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '操作失败'))
  }
}

async function deleteCase(row: FeedbackRow | Record<string, unknown>) {
  const r = row as FeedbackRow
  try {
    await ElMessageBox.confirm(`确认删除反馈记录？(ID: ${r.log_id})`, '删除确认', { type: 'error' })
    await apiDelete(`/qc/feedback/cases/${r.log_id}`)
    ElMessage.success('已删除')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '删除失败'))
  }
}

async function deleteSelected() {
  if (!selectedRows.value.length) return
  const ids = selectedRows.value.map((r) => r.log_id)
  try {
    await ElMessageBox.confirm(`确认批量删除 ${ids.length} 条记录？`, '批量删除', { type: 'error' })
    const resp = await apiDelete<{ data?: { deleted?: number } }>('/qc/feedback/cases/bulk', { data: { log_ids: ids } })
    const deleted = resp?.data?.deleted || ids.length
    ElMessage.success(`已删除 ${deleted} 条`)
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '批量删除失败'))
  }
}

function onSelectionChange(rows: FeedbackRow[]) { selectedRows.value = rows as FeedbackRow[] }

async function copyPatientId(pid: string) {
  if (!pid) return
  try { await navigator.clipboard.writeText(pid); ElMessage.success('已复制') } catch { ElMessage.warning('复制失败') }
}

async function exportExcel() {
  if (!filters.audit_type_code) { ElMessage.warning('导出前请先选择一个审计类型'); return }
  try {
    const params: Record<string, unknown> = { ...filters }
    if (viewMode.value === 'kanban') delete params.status
    const { blob, filename } = await apiDownload('/qc/feedback/export/excel', { params })
    triggerBrowserDownload(blob, filename)
    ElMessage.success('导出已开始')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '导出失败'))
  }
}

// 详情派生
const detailDimensions = computed(() => {
  if (!detail.value) return []
  return ((detail.value as Record<string, unknown>).dimensions as Array<Record<string, unknown>>) || []
})
const detailPatient = computed(() => {
  if (!detail.value) return null
  return ((detail.value as Record<string, unknown>).patient as Record<string, unknown>) || null
})
const detailHistory = computed(() => {
  if (!detail.value) return []
  const fb = (detail.value as Record<string, unknown>).feedback as Record<string, unknown> | undefined
  return (fb?.history as Array<Record<string, unknown>> | undefined) || []
})

function syncRouteQuery() {
  const signature = JSON.stringify(route.query)
  if (signature === routeSignature) return false
  routeSignature = signature
  const parsed = parseFeedbackRouteQuery(route.query)
  Object.assign(filters, { status: 'pending', severity: '', audit_type_code: '', dept_id: null, days: 30, keyword: '' }, parsed.filters)
  routeSource.value = parsed.source === 'workbench'
  page.value = 1
  void load()
  return true
}

onMounted(() => {
  syncRouteQuery()
  apiGet<{ items?: Array<{ code: string; name: string }> }>('/audit-types/options').then((d) => {
    auditTypeOptions.value = (d.items || []).map((a) => ({ value: a.code, label: a.name }))
  }).catch(() => {})
  apiGet<{ data?: Array<{ id: number; name: string }> }>('/departments').then((d) => {
    deptOptions.value = (d.data || d as unknown as Array<{ id: number; name: string }>) || []
  }).catch(() => {})
})
onActivated(() => { syncRouteQuery() })
watch(() => route.fullPath, () => { syncRouteQuery() })
</script>

<template>
  <div class="page-feedback">
    <PageHeader title="整改反馈" description="质控结果反馈与整改闭环管理，支持列表/看板视图。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="exportExcel">导出 Excel</el-button>
        <el-button :disabled="!selectedRows.length" type="danger" plain @click="deleteSelected">批量删除 ({{ selectedRows.length }})</el-button>
      </template>
    </PageHeader>
    <el-alert v-if="routeSource" title="来自工作台的联动筛选" type="info" :closable="false" class="route-hint" />

    <!-- 统计 -->
    <div class="stat-bar">
      <span class="stat-item">近期不一致 <b>{{ stats.total }}</b></span>
      <span class="stat-item stat-danger">高风险 <b>{{ stats.high }}</b></span>
      <span class="stat-item">待处理 <b>{{ stats.pending }}</b></span>
      <span class="stat-item">已确认 <b>{{ stats.acknowledged }}</b></span>
      <span class="stat-item">已整改 <b>{{ stats.rectified }}</b></span>
      <span class="stat-item stat-ok">已关闭 <b>{{ stats.closed }}</b></span>
      <span class="stat-item">闭环率 <b>{{ closureRate }}%</b></span>
    </div>

    <!-- 视图切换 + 筛选 -->
    <div class="filter-bar">
      <el-radio-group v-model="viewMode" size="small" @change="switchView(viewMode)">
        <el-radio-button value="list">列表</el-radio-button>
        <el-radio-button value="kanban">看板</el-radio-button>
      </el-radio-group>
      <el-select v-model="filters.status" clearable placeholder="状态" size="small" style="width: 100px" @change="onSearch">
        <el-option label="待处理" value="pending" />
        <el-option label="已确认" value="acknowledged" />
        <el-option label="已整改" value="rectified" />
        <el-option label="已关闭" value="closed" />
      </el-select>
      <el-select v-model="filters.severity" clearable placeholder="严重度" size="small" style="width: 90px" @change="onSearch">
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-select v-model="filters.audit_type_code" clearable filterable placeholder="审计类型" size="small" style="width: 160px" @change="onSearch">
        <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
      <el-input v-model="filters.keyword" clearable placeholder="患者ID/姓名/住院号" size="small" style="width: 160px" @keyup.enter="onSearch" />
      <el-select v-model="filters.days" size="small" style="width: 90px" @change="onSearch">
        <el-option label="近7天" :value="7" />
        <el-option label="近30天" :value="30" />
        <el-option label="近90天" :value="90" />
      </el-select>
      <el-button size="small" @click="resetFilters">重置</el-button>
    </div>

    <!-- 列表视图 -->
    <template v-if="viewMode === 'list'">
      <el-table v-loading="loading" :data="items" stripe border size="small" style="width: 100%" @selection-change="onSelectionChange">
        <el-table-column type="selection" width="36" />
        <el-table-column label="患者" width="120" fixed>
          <template #default="{ row }">
            <div><b>{{ row.patient_name }}</b></div>
            <div class="cell-sub">{{ row.patient_id }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="admission_no" label="住院号" width="100" show-overflow-tooltip />
        <el-table-column prop="dept_name" label="科室" width="100" show-overflow-tooltip />
        <el-table-column prop="audit_type_name" label="类型" width="120" show-overflow-tooltip />
        <el-table-column label="严重度" width="70"><template #default="{ row }"><RiskTag :value="row.severity" /></template></el-table-column>
        <el-table-column label="状态" width="80"><template #default="{ row }"><StatusTag :value="row.status" /></template></el-table-column>
        <el-table-column prop="issue_count" label="问题数" width="60" align="center" />
        <el-table-column prop="overall_conclusion" label="结论" min-width="150" show-overflow-tooltip />
        <el-table-column label="推送时间" width="135"><template #default="{ row }">{{ formatDateTime(row.push_time) }}</template></el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openDetail(row)">详情</el-button>
            <el-button link size="small" @click="copyPatientId(row.patient_id)">复制ID</el-button>
            <el-button link type="danger" size="small" @click="deleteCase(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="load" @size-change="() => { page = 1; load() }" />
    </template>

    <!-- 看板视图 -->
    <template v-else>
      <div v-loading="loading" class="kanban">
        <div v-for="col in kanbanColumns" :key="col.key" class="kanban-col">
          <div class="kanban-head">
            <span>{{ col.label }}</span>
            <el-tag size="small" round>{{ kanbanGroups[col.key]?.length || 0 }}</el-tag>
          </div>
          <div class="kanban-body">
            <div v-for="item in (kanbanGroups[col.key] || [])" :key="item.log_id" class="kanban-card" @click="openDetail(item)">
              <div class="card-head">
                <b>{{ item.patient_name }}</b>
                <RiskTag :value="item.severity" />
              </div>
              <div class="card-meta">{{ item.patient_id }} · {{ item.dept_name }}</div>
              <div class="card-type">{{ item.audit_type_name }}</div>
              <div class="card-time">{{ formatDateTime(item.push_time) }}</div>
            </div>
            <div v-if="!(kanbanGroups[col.key]?.length)" class="kanban-empty">无</div>
          </div>
        </div>
      </div>
    </template>

    <!-- 详情抽屉 -->
    <DetailDrawer v-model="detailVisible" title="反馈详情" :loading="detailLoading" size="75%">
      <template v-if="detail">
        <!-- 患者摘要 -->
        <div class="detail-header">
          <div class="detail-title">
            <h3>{{ (detail as Record<string, unknown>).patient_name }}</h3>
            <StatusTag :value="String((detail as Record<string, unknown>).status || '')" />
            <RiskTag :value="String((detail as Record<string, unknown>).severity || '')" />
          </div>
          <div class="detail-meta">
            {{ (detail as Record<string, unknown>).patient_id }} ｜ 住院号 {{ (detail as Record<string, unknown>).admission_no }} ｜ {{ (detail as Record<string, unknown>).dept_name }} ｜ {{ (detail as Record<string, unknown>).audit_type_name }}
          </div>
        </div>

        <!-- 总体结论 -->
        <el-card v-if="(detail as Record<string, unknown>).overall_conclusion" shadow="never" class="mt-sm">
          <template #header>总体结论</template>
          <div>{{ (detail as Record<string, unknown>).overall_conclusion }}</div>
          <div v-if="(detail as Record<string, unknown>).overall_qc_summary" class="qc-summary">{{ (detail as Record<string, unknown>).overall_qc_summary }}</div>
        </el-card>

        <div v-if="(detail as Record<string, unknown>).medical_documents_text || (detail as Record<string, unknown>).nursing_records_text" class="source-sections mt-sm">
          <el-card v-if="(detail as Record<string, unknown>).medical_documents_text" shadow="never">
            <template #header>病程记录</template>
            <pre class="source-text">{{ (detail as Record<string, unknown>).medical_documents_text }}</pre>
          </el-card>
          <el-card v-if="(detail as Record<string, unknown>).nursing_records_text" shadow="never">
            <template #header>护理记录</template>
            <pre class="source-text">{{ (detail as Record<string, unknown>).nursing_records_text }}</pre>
          </el-card>
        </div>

        <!-- 维度详情 -->
        <el-card v-if="detailDimensions.length" shadow="never" class="mt-sm">
          <template #header>质控维度（{{ detailDimensions.length }}）</template>
          <div v-for="(dim, i) in detailDimensions" :key="i" class="dim-card">
            <div class="dim-head">
              <span class="dim-name">{{ dim.dimension || dim.dimension_name || dim.dimension_code }}</span>
              <StatusTag :value="String(dim.status || '')" />
              <RiskTag v-if="dim.severity" :value="String(dim.severity)" />
            </div>
            <div v-if="dim.issue_summary" class="dim-issue">{{ dim.issue_summary }}</div>
            <div v-if="dim.recommendation" class="dim-rec">建议：{{ dim.recommendation }}</div>
            <div v-if="(dim.medical_evidence as unknown[])?.length || (dim.nursing_evidence as unknown[])?.length" class="dim-evidence">
              <div v-if="(dim.medical_evidence as unknown[])?.length"><strong>病程证据：</strong>{{ (dim.medical_evidence as unknown[]).join('；') }}</div>
              <div v-if="(dim.nursing_evidence as unknown[])?.length"><strong>护理证据：</strong>{{ (dim.nursing_evidence as unknown[]).join('；') }}</div>
            </div>
          </div>
        </el-card>

        <!-- 患者信息 -->
        <el-card v-if="detailPatient" shadow="never" class="mt-sm">
          <template #header>患者信息</template>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="患者ID">{{ detailPatient.patient_id }}</el-descriptions-item>
            <el-descriptions-item label="姓名">{{ detailPatient.patient_name }}</el-descriptions-item>
            <el-descriptions-item label="住院次">{{ detailPatient.visit_number }}</el-descriptions-item>
            <el-descriptions-item label="住院号">{{ detailPatient.admission_no }}</el-descriptions-item>
            <el-descriptions-item label="在院科室">{{ detailPatient.dept }}</el-descriptions-item>
            <el-descriptions-item label="入院日期">{{ detailPatient.admission_date }}</el-descriptions-item>
            <el-descriptions-item label="出院日期">{{ detailPatient.discharge_date }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 反馈表单 -->
        <el-card shadow="never" class="mt-sm">
          <template #header>反馈处理</template>
          <div class="form-row">
            <label>操作</label>
            <el-radio-group v-model="confirmForm.action" size="small">
              <el-radio value="acknowledged">确认</el-radio>
              <el-radio value="closed">关闭</el-radio>
            </el-radio-group>
          </div>
          <div class="form-row mt-sm">
            <label>整改意见</label>
            <el-input v-model="confirmForm.review_comment" type="textarea" :rows="3" placeholder="填写整改意见" size="small" />
          </div>
          <el-button type="primary" size="small" @click="submitConfirm" class="mt-sm">提交</el-button>
        </el-card>
        <el-card v-if="detailHistory.length" shadow="never" class="mt-sm">
          <template #header>处理历史</template>
          <el-timeline>
            <el-timeline-item v-for="(h, i) in detailHistory" :key="i" :timestamp="formatDateTime(String(h.created_at || h.changed_at || ''))">
              <StatusTag :value="String(h.new_status || h.status || '')" />
              <span class="history-note">{{ h.change_reason || h.review_comment || h.operator || '' }}</span>
            </el-timeline-item>
          </el-timeline>
        </el-card>
      </template>
    </DetailDrawer>
  </div>
</template>

<style scoped>
.stat-bar { display: flex; gap: 16px; margin-bottom: 10px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 8px; flex-wrap: wrap; }
.stat-item { font-size: 13px; color: var(--el-text-color-secondary); }
.stat-item b { font-size: 15px; margin-left: 4px; }
.stat-danger b { color: var(--el-color-danger); }
.stat-ok b { color: var(--el-color-success); }
.filter-bar { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.kanban { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.kanban-col { background: var(--el-fill-color-light); border-radius: 10px; min-height: 400px; }
.kanban-head { display: flex; justify-content: space-between; align-items: center; padding: 10px 12px; font-weight: 600; font-size: 14px; border-bottom: 1px solid var(--el-border-color-lighter); }
.kanban-body { padding: 8px; display: flex; flex-direction: column; gap: 8px; max-height: 600px; overflow-y: auto; }
.kanban-card { padding: 10px; background: var(--el-bg-color); border: 1px solid var(--el-border-color); border-radius: 8px; cursor: pointer; transition: box-shadow .2s; }
.kanban-card:hover { box-shadow: 0 2px 8px rgba(0,0,0,.1); }
.card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.card-meta { font-size: 12px; color: var(--el-text-color-secondary); }
.card-type { font-size: 11px; color: var(--el-text-color-disabled); margin-top: 2px; }
.card-time { font-size: 11px; color: var(--el-text-color-disabled); margin-top: 4px; }
.kanban-empty { text-align: center; padding: 20px; color: var(--el-text-color-disabled); font-size: 13px; }

.detail-header { margin-bottom: 12px; }
.detail-title { display: flex; align-items: center; gap: 8px; }
.detail-title h3 { margin: 0; font-size: 18px; }
.detail-meta { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 4px; }

.dim-card { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.dim-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.dim-name { font-weight: 600; }
.dim-issue { font-size: 13px; margin-bottom: 4px; }
.dim-rec { font-size: 12px; color: var(--el-text-color-secondary); }
.dim-evidence { margin-top: 6px; display: flex; gap: 16px; font-size: 12px; color: var(--el-text-color-secondary); }

.form-row { display: flex; gap: 8px; align-items: flex-start; }
.form-row label { font-size: 12px; color: var(--el-text-color-secondary); min-width: 60px; padding-top: 6px; }
.qc-summary { margin-top: 8px; color: var(--el-text-color-secondary); font-size: 13px; }
.mt-sm { margin-top: 8px; }
.source-sections { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.source-text { margin: 0; max-height: 280px; overflow: auto; white-space: pre-wrap; word-break: break-word; font: inherit; line-height: 1.6; color: var(--el-text-color-regular); }
.history-note { margin-left: 8px; color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 640px) { .source-sections { grid-template-columns: 1fr; } }

@media (max-width: 1024px) { .kanban { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) { .kanban { grid-template-columns: 1fr; } }
</style>
