<template>
  <div class="page-pq">
    <PageHeader
      title="内涵质控工作台"
      description="AI 语义内涵与终末病历质控，支持按患者聚合查阅或按核查流水排障管理。"
    >
      <template #actions>
        <el-radio-group v-model="activeView" size="default" @change="onViewChange">
          <el-radio-button value="patients">按患者汇总</el-radio-button>
          <el-radio-button value="records">按核查流水</el-radio-button>
        </el-radio-group>
        <template v-if="activeView === 'patients'">
          <el-button :loading="loading" @click="load">刷新</el-button>
          <el-dropdown :disabled="total <= 0 || exportLoading" @command="(cmd: string) => cmd === 'qc' ? exportQcSummary() : exportXlsx()">
            <el-button type="primary" :loading="exportLoading" :disabled="total <= 0">
              导出当前筛选<el-icon class="el-icon--right"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="visit">导出病历数据（完整文书汇总，支持历史患者）</el-dropdown-item>
                <el-dropdown-item command="qc">导出质控汇总（统计+问题明细）</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </template>
      </template>
    </PageHeader>

    <!-- ── 视角 A：按患者汇总（临床/科主任视角）── -->
    <template v-if="activeView === 'patients'">
      <!-- 4 张可点击快捷筛选卡（WP05：取代旧统计条；点击即切筛选） -->
      <div @click="onSummaryClick">
        <SummaryStrip :items="quickCards" :loading="loading" />
      </div>
      <el-alert v-if="routeSource" title="来自工作台的联动筛选" type="info" :closable="false" class="route-hint" />

      <FilterPanel title="筛选条件" :collapsible="true" @search="onSearch" @reset="resetFilters">
        <div class="pq-filter-row">
          <label class="pq-filter-item">
            核查日期范围
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="开始"
              end-placeholder="结束"
              size="small"
              style="width: 240px"
              @change="onSearch"
            />
          </label>
          <el-radio-group v-model="datePreset" size="small" @change="applyDatePreset">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="last7">近7天</el-radio-button>
            <el-radio-button value="last30">近30天</el-radio-button>
          </el-radio-group>
          <label class="pq-filter-item">
            在院/质控科室
            <el-select v-model="filters.dept" clearable filterable placeholder="全部科室" size="small" style="width: 160px" @change="onSearch">
              <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
            </el-select>
          </label>
          <label class="pq-filter-item">
            质控类型
            <el-select v-model="filters.audit_type_code" clearable filterable placeholder="全部类型" size="small" style="width: 180px" @change="onSearch">
              <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
            </el-select>
          </label>
          <label class="pq-filter-item">
            最高风险
            <el-select v-model="filters.severity" clearable placeholder="全部" size="small" style="width: 110px" @change="onSearch">
              <el-option label="高危" value="high" />
              <el-option label="中危" value="medium" />
              <el-option label="低危" value="low" />
              <el-option label="无异常" value="none" />
            </el-select>
          </label>
          <label class="pq-filter-item">
            患者姓名 / ID / 住院号
            <el-input
              v-model="patientKeyword"
              clearable
              placeholder="回车查询"
              size="small"
              style="width: 170px"
              @keyup.enter="applyPatientKeyword"
              @clear="applyPatientKeyword"
            />
          </label>
        </div>
        <template #more>
          <div class="pq-filter-row">
            <label class="pq-filter-item">
              出院科室
              <el-select v-model="filters.discharge_dept_name" clearable filterable placeholder="全部" size="small" style="width: 160px" @change="onSearch">
                <el-option v-for="d in deptOptions" :key="d.value" :label="d.label" :value="d.value" />
              </el-select>
            </label>
            <label class="pq-filter-item">
              整改状态
              <el-select v-model="filters.status" clearable placeholder="全部" size="small" style="width: 120px" @change="onSearch">
                <el-option label="待处理" value="pending" />
                <el-option label="已整改" value="rectified" />
                <el-option label="已关闭" value="closed" />
              </el-select>
            </label>
          </div>
        </template>
      </FilterPanel>

      <ErrorState v-if="error && !loading" :message="error" @retry="load" />
      <EmptyState v-else-if="!loading && !items.length" description="暂无患者质控记录" />
      <el-table
        v-else
        v-loading="loading"
        :data="items"
        stripe
        border
        size="small"
        class="pq-table"
        :max-height="tableMaxHeight"
        @row-click="(row: PatientRow) => openDetail(row)"
      >
        <el-table-column label="患者信息" width="185" fixed="left">
          <template #default="{ row }">
            <div class="pq-cell-main">
              <b>{{ row.patient_name || '—' }}</b>
              <span class="cell-sub pq-sex-age">患者号 {{ row.patient_id }} · 第{{ row.visit_number }}次</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="科室与管床" width="165" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.dept || '—' }}</div>
            <div v-if="row.discharge_dept_name && row.discharge_dept_name !== row.dept" class="cell-sub">出院 {{ row.discharge_dept_name }}</div>
          </template>
        </el-table-column>
        <el-table-column label="核查维度摘要" min-width="240">
          <template #default="{ row }">
            <div class="pq-dim-caps">
              <el-tag v-if="row.high_count > 0" size="small" effect="plain" type="danger">高危 {{ row.high_count }}</el-tag>
              <el-tag v-if="row.medium_count > 0" size="small" effect="plain" type="warning">中危 {{ row.medium_count }}</el-tag>
              <span v-if="row.issue_count > (row.high_count + row.medium_count)" class="cell-sub">+{{ row.issue_count - row.high_count - row.medium_count }} 项</span>
              <span v-if="!row.issue_count" class="cell-sub">暂无异常维度</span>
            </div>
            <div class="cell-sub">问题 {{ row.issue_count }} · 待处理 {{ row.pending_count }} · 已闭环 {{ row.resolved_count }}</div>
          </template>
        </el-table-column>
        <el-table-column label="最高风险" width="90" align="center">
          <template #default="{ row }"><RiskTag :value="row.highest_severity" /></template>
        </el-table-column>
        <el-table-column label="核查次数" width="95" align="center">
          <template #default="{ row }">
            <span>共 {{ row.push_log_count }} 次</span>
            <span v-if="row.high_count > 0" class="cell-sub count-danger">（高危 {{ row.high_count }}）</span>
          </template>
        </el-table-column>
        <el-table-column label="复核闭环" width="105" align="center">
          <template #default="{ row }">
            <StatusTag :value="reviewStatus(row as PatientRow)" />
          </template>
        </el-table-column>
        <el-table-column label="最近核查时间" width="155">
          <template #default="{ row }">{{ formatDateTime(row.latest_push_time) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="165" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="openDetail(row as PatientRow)">查看详情</el-button>
            <HolographyButton :patient-id="(row as PatientRow).patient_id" link />
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
    </template>

    <!-- ── 视角 B：按核查流水（排障/管理员视角）── -->
    <AuditRecordListPanel v-else />

    <!-- 宽敞详情抽屉（WP05：复用 PatientQcDetailView，取代旧右侧夹板+多页签内联详情） -->
    <DetailDrawer v-model="detailVisible" title="患者质控详情" :loading="detailLoading" size="820px">
      <template #actions>
        <el-button v-if="hasPrev" link @click="prevDetail">上一条</el-button>
        <span v-if="detailIndex >= 0" class="nav-pos">{{ detailIndex + 1 }} / {{ items.length }}</span>
        <el-button v-if="hasNext" link @click="nextDetail">下一条</el-button>
      </template>
      <PatientQcDetailView
        v-if="detailVisible && selectedPatientId"
        :key="`${selectedPatientId}__${selectedVisitNumber}`"
        :patient-id="selectedPatientId"
        :visit-number="selectedVisitNumber"
        :dept="selectedDept"
        :in-drawer="true"
        @updated="load"
      />
    </DetailDrawer>
  </div>
</template>

<script setup lang="ts">
// 内涵质控工作台（WP05，用户拍板 D2）：统一「患者质控全景」与「AI 内涵质控记录」双
// 重复菜单为唯一主界面，顶部双视角切换：
// - 按患者汇总（默认，临床视角）：SummaryStrip 快捷筛选卡 + FilterPanel（5 主项 +
//   #more 低频）+ 全宽固定表头 8 列 + 宽敞详情抽屉（复用 PatientQcDetailView）；
// - 按核查流水（排障视角）：完整迁移原质控记录页（AuditRecordListPanel）。
// 彻底移除旧版右侧夹板布局（旧摘要侧栏类名全部清除）；旧 /quality/records 由 AuditRecordsPage 壳页
// 重定向到 ?view=records（书签/跨页跳转无损）。
import { computed, onActivated, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import HolographyButton from '@/components/base/HolographyButton.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import EmptyState from '@/components/feedback/EmptyState.vue'
import PatientQcDetailView from './components/PatientQcDetailView.vue'
import AuditRecordListPanel from './components/AuditRecordListPanel.vue'
import { apiDownload, apiGet, triggerBrowserDownload } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import { buildPatientQcExportParams } from '@/utils/patient-qc-contracts'
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

const route = useRoute()
const router = useRouter()

/** 双视角：URL ?view=records 切流水视角；切换写回 query（书签/刷新可保持）。 */
const activeView = ref<'patients' | 'records'>('patients')

function applyViewFromQuery(): boolean {
  const view = String(route.query.view || '').trim()
  const next = view === 'records' ? 'records' : 'patients'
  if (next !== activeView.value) {
    activeView.value = next
    return true
  }
  return false
}

function onViewChange(): void {
  void router.replace({ query: { ...route.query, view: activeView.value } })
}

const loading = ref(false)
const error = ref('')
const items = ref<PatientRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

/** 固定表头高度（页头+快捷卡+筛选让出）。 */
const tableMaxHeight = 'calc(100vh - 380px)'

const filters = reactive({
  patient_id: '',
  patient_name: '',
  admission_no: '',
  visit_number: '',
  dept: '',
  discharge_dept_name: '',
  severity: '',
  status: '',
  audit_type_code: '',
  date_from: '' as string,
  date_to: '' as string,
})

/** 主行搜索框：姓名/ID/住院号三选一（回车按优先级落到对应筛选）。 */
const patientKeyword = ref('')

const dateRange = ref<[string, string] | null>(null)
const datePreset = ref<'all' | 'last7' | 'last30'>('all')

const deptOptions = ref<Array<{ value: string; label: string }>>([])
const auditTypeOptions = ref<Array<{ value: string; label: string }>>([])

function applyDatePreset(): void {
  if (datePreset.value === 'all') {
    dateRange.value = null
    filters.date_from = ''
    filters.date_to = ''
  } else {
    const days = datePreset.value === 'last7' ? 7 : 30
    const today = new Date()
    const start = new Date(today)
    start.setDate(start.getDate() - (days - 1))
    const pad = (n: number) => String(n).padStart(2, '0')
    const fmt = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
    dateRange.value = [fmt(start), fmt(today)]
    filters.date_from = dateRange.value[0]
    filters.date_to = dateRange.value[1]
  }
  onSearch()
}

/** 患者关键词：纯数字按患者ID，其余按姓名（住院号场景走更多筛选精确框）。 */
function applyPatientKeyword(): void {
  const kw = patientKeyword.value.trim()
  if (/^\d+$/.test(kw) && kw.length >= 6) {
    filters.patient_id = kw
    filters.patient_name = ''
    filters.admission_no = ''
  } else if (kw) {
    filters.patient_name = kw
    filters.patient_id = ''
    filters.admission_no = ''
  } else {
    filters.patient_id = ''
    filters.patient_name = ''
    filters.admission_no = ''
  }
  onSearch()
}

/** 快捷卡：全部患者 / 高危（红）/ 中危（橙）/ 待处理（蓝）——点击切筛选。 */
const quickCards = computed<SummaryItem[]>(() => [
  {
    key: 'all', label: '全部患者', value: total.value,
    hint: filters.severity || filters.status ? '点击查看全部' : '当前全部',
  },
  { key: 'high', label: '高危患者', value: pageStats.value.high, tone: 'danger', hint: '点击只看高危' },
  { key: 'medium', label: '中危患者', value: pageStats.value.medium, tone: 'warning', hint: '点击只看中危' },
  { key: 'pending', label: '待复核', value: pageStats.value.pending, tone: 'info', hint: '点击只看待处理' },
])

/** 快捷卡点击委托（与审批台账同款容器委托）。 */
function onSummaryClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null
  const card = target?.closest('.summary-strip__card')
  if (!card) return
  const strip = card.parentElement
  if (!strip) return
  const index = Array.from(strip.children).indexOf(card)
  if (index === 0) {
    filters.severity = ''
    filters.status = ''
  } else if (index === 1) {
    filters.severity = 'high'
    filters.status = ''
  } else if (index === 2) {
    filters.severity = 'medium'
    filters.status = ''
  } else if (index === 3) {
    filters.severity = ''
    filters.status = 'pending'
  } else {
    return
  }
  onSearch()
}

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

/** 复核闭环中文状态：待复核 / 已闭环 / 无反馈。 */
function reviewStatus(row: PatientRow): string {
  if (row.pending_count > 0) return '待复核'
  if (row.resolved_count > 0) return '已闭环'
  return '无反馈'
}

const detailVisible = ref(false)
const detailLoading = ref(false)
const detailIndex = ref(-1)
const selectedPatientId = ref('')
const selectedVisitNumber = ref('')
const selectedDept = ref('')

async function load(): Promise<void> {
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
  } catch (e) {
    error.value = toUserMessage(e, '加载患者质控失败')
  } finally {
    loading.value = false
  }
}

async function loadFilterOptions(): Promise<void> {
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
  } catch { /* 静默降级 */ }
}

function resetFilters(): void {
  Object.assign(filters, {
    patient_id: '', patient_name: '', admission_no: '', visit_number: '',
    dept: '', discharge_dept_name: '', severity: '', status: '', audit_type_code: '',
    date_from: '', date_to: '',
  })
  patientKeyword.value = ''
  dateRange.value = null
  datePreset.value = 'all'
  page.value = 1
  routeSource.value = false
  routeSignature = '{}'
  void router.replace({ query: { view: activeView.value } })
  void load()
}

function onSearch(): void {
  page.value = 1
  void load()
}

async function openDetail(row: PatientRow): Promise<void> {
  detailIndex.value = items.value.findIndex(
    (r) => r.patient_id === row.patient_id && r.visit_number === row.visit_number)
  selectedPatientId.value = row.patient_id
  selectedVisitNumber.value = String(row.visit_number || '')
  selectedDept.value = row.dept || ''
  detailLoading.value = false
  detailVisible.value = true
}

const hasPrev = computed(() => detailIndex.value > 0)
const hasNext = computed(() => detailIndex.value >= 0 && detailIndex.value < items.value.length - 1)
async function prevDetail(): Promise<void> {
  if (!hasPrev.value) return
  detailIndex.value--
  const row = items.value[detailIndex.value]
  selectedPatientId.value = row.patient_id
  selectedVisitNumber.value = String(row.visit_number || '')
  selectedDept.value = row.dept || ''
}
async function nextDetail(): Promise<void> {
  if (!hasNext.value) return
  detailIndex.value++
  const row = items.value[detailIndex.value]
  selectedPatientId.value = row.patient_id
  selectedVisitNumber.value = String(row.visit_number || '')
  selectedDept.value = row.dept || ''
}

const exportLoading = ref(false)

async function exportQcSummary(): Promise<void> {
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

async function exportXlsx(): Promise<void> {
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

let routeSignature = ''
const routeSource = ref(false)

function syncRouteQuery(): void {
  applyViewFromQuery()
  const signature = JSON.stringify(route.query)
  if (signature === routeSignature) return
  routeSignature = signature
  if (activeView.value !== 'patients') return // 流水视角筛选由 AuditRecordListPanel 自行解析
  const parsed = parsePatientRouteQuery(route.query)
  Object.assign(filters, {
    patient_id: '', patient_name: '', admission_no: '', visit_number: '',
    dept: '', discharge_dept_name: '', severity: '', status: '', audit_type_code: '',
    date_from: '', date_to: '',
  }, parsed.filters)
  routeSource.value = parsed.source === 'workbench'
  page.value = 1
  void load()
}

onMounted(() => { syncRouteQuery(); void loadFilterOptions() })
onActivated(() => { syncRouteQuery() })
watch(() => route.fullPath, () => { syncRouteQuery() })
</script>

<style scoped>
.page-pq { padding: 4px; }
.route-hint { margin-bottom: 10px; }
.pq-filter-row { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
.pq-filter-item {
  display: inline-flex; gap: 6px; align-items: center;
  font-size: 13px; color: var(--el-text-color-regular);
}
.pq-table { min-height: 320px; }
.pq-cell-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.pq-cell-main b { font-size: 13px; }
.pq-sex-age { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.count-danger { color: var(--el-color-danger); }
.pq-dim-caps { display: flex; gap: 6px; flex-wrap: wrap; align-items: center; margin-bottom: 2px; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.nav-pos { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 8px; }
</style>
