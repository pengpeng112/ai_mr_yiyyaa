<template>
  <section class="tl-page">
    <PageHeader
      title="病历时效考核统计"
      description="按科室 × 责任医生聚合任意日期区间的按时完成率、预警与超时锁定次数及扣罚口径（受科室可见性约束）；导出写导出审计。"
    >
      <template #actions>
        <el-button
          size="small"
          type="primary"
          plain
          data-testid="goto-approvals"
          @click="goApprovals"
        >
          解锁审批台账 -&gt;
        </el-button>
        <el-button size="small" data-testid="open-mobile-entry" @click="mobileEntryVisible = true">
          📱 手机端入口
        </el-button>
        <el-button v-if="canExport" size="small" :loading="exporting" data-testid="export-monthly" @click="exportExcel">
          导出 Excel
        </el-button>
      </template>
    </PageHeader>

    <!-- 2026-11-16：企微手机端访问入口便捷弹窗 -->
    <el-dialog v-model="mobileEntryVisible" title="企业微信手机端访问入口" width="min(92vw, 520px)">
      <p class="mobile-entry-tip">
        可将此链接配置到企业微信工作台自建应用主页，或发送至企业微信收藏夹，手机点开即可查询超时解锁与统计报表。
      </p>
      <el-input :model-value="mobileUrl" readonly>
        <template #append>
          <el-button @click="copyMobileUrl">一键复制链接</el-button>
        </template>
      </el-input>
      <template #footer>
        <el-button @click="mobileEntryVisible = false">关闭</el-button>
        <el-button type="primary" @click="mobileEntryVisible = false">
          <a :href="mobileUrl" target="_blank" rel="noopener" class="mobile-entry-link">新窗口预览手机端</a>
        </el-button>
      </template>
    </el-dialog>

    <FilterPanel title="考核范围" :collapsible="false" @search="search" @reset="resetFilters">
      <div class="tl-filter-row">
        <label class="tl-filter-item">
          快捷区间
          <el-radio-group v-model="quickRange" size="small" @change="applyQuickRange">
            <el-radio-button value="month">本月</el-radio-button>
            <el-radio-button value="prevMonth">上月</el-radio-button>
            <el-radio-button value="last7">近7天</el-radio-button>
            <el-radio-button value="last10">近10天</el-radio-button>
            <el-radio-button value="last30">近30天</el-radio-button>
            <el-radio-button value="custom">自定义</el-radio-button>
          </el-radio-group>
        </label>
        <label class="tl-filter-item">
          考核时间范围
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            :clearable="false"
            style="width: 250px"
            @change="onDateManualChange"
          />
        </label>
        <label class="tl-filter-item">
          科室
          <el-select v-model="dept" filterable clearable :placeholder="allHospital ? '全院' : '全部授权科室'" style="width: 180px">
            <el-option :label="allHospital ? '全院' : '全部授权科室'" value="" />
            <el-option v-for="item in departments" :key="item.id" :label="item.name" :value="item.code || item.name" />
          </el-select>
        </label>
        <label class="tl-filter-item">
          责任医生
          <el-input
            v-model="doctor"
            clearable
            placeholder="姓名或工号，回车查询"
            style="width: 160px"
            @keyup.enter="search"
          />
        </label>
      </div>
    </FilterPanel>

    <SummaryStrip :items="totalCards" :loading="loading" />

    <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

    <DataTableShell
      :loading="loading"
      :error="loadError"
      :empty="!tableRows.length"
      empty-text="所选区间无事件数据（或当前账号无可见科室）"
      :total="totalRows"
      :page="page"
      :page-size="pageSize"
      @update:page="onPageChange"
      @update:pageSize="onPageSizeChange"
      @retry="loadStats"
    >
      <el-table
        :data="tableRows"
        border
        stripe
        size="small"
        :max-height="tableMaxHeight"
        show-summary
        :summary-method="summaryMethod"
        header-cell-class-name="ma-sticky-th"
      >
        <el-table-column prop="dept_name" label="科室名称" min-width="150" fixed="left" show-overflow-tooltip>
          <template #default="{ row }">{{ row.dept_name || row.dept_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="责任医生" width="140" fixed="left">
          <template #default="{ row }">
            {{ row.responsible_doctor_name || '—' }}<span class="cell-sub">（{{ row.responsible_doctor_id || '无工号' }}）</span>
          </template>
        </el-table-column>
        <el-table-column prop="total" label="事件总数" width="96" align="right" sortable />
        <el-table-column prop="completed_on_time" label="按时完成" width="96" align="right" sortable />
        <el-table-column prop="completed_late" label="超时完成" width="96" align="right" sortable />
        <el-table-column prop="overdue" label="超时未完成" width="106" align="right" sortable />
        <el-table-column prop="warning" label="预警中" width="86" align="right" sortable />
        <el-table-column label="按时率" width="100" align="right">
          <template #default="{ row }">
            <el-tag size="small" :type="rowTagType(row.on_time_rate)">
              {{ Number(row.on_time_rate || 0).toFixed(1) }}%
            </el-tag>
          </template>
        </el-table-column>
        <!-- 2026-11-13 返工：超时申请/扣罚口径 4 列（与 tl_approval 对齐；WP04 保留） -->
        <el-table-column prop="approval_count" label="锁定(超时申请)次数" width="150" align="right" sortable />
        <el-table-column prop="approved_unlock_count" label="解锁通过" width="96" align="right" sortable />
        <el-table-column prop="exempt_count" label="豁免次数" width="90" align="right" sortable />
        <el-table-column prop="penalty_amount_total" label="应扣金额(元)" width="116" align="right" sortable />
      </el-table>
    </DataTableShell>
  </section>
</template>

<script setup lang="ts">
// 时效月度考核页（只读 + 导出）+ WP04（064 总计划）全面升级：
// - 任意日期区间（快捷区间 本月/上月/近7/10/30天/自定义）+ 真分页（page/limit≤200，
//   totals 始终全量合计）+ 固定表头与左侧科室/医生列冻结；
// - 主按钮导出真 Excel（openpyxl 后端生成；默认 CSV 契约保持）；
// - 移除页内旧审批页签（审批台账集中在 /timeliness/approvals 独立页），
//   页头保留「解锁审批台账 ->」直达按钮与手机端入口弹窗；
// - 导出走 apiDownload（blob），无 timeliness_export 权限时后端 403 → 提示降级。
import { computed, onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import { exportMonthlyApi, fetchMonthlyRangeStatsApi, fetchTimelinessDictsApi } from './api'
import type { DepartmentOption, MonthlyRow, MonthlyStats } from './types'

const router = useRouter()
const auth = useAuthStore()
const canExport = computed(() => auth.roleName === 'admin' || auth.user?.permissions?.includes('timeliness_export'))

// 2026-11-16：企微手机端入口弹窗（与 ApprovalCenterPage 同款）
const mobileEntryVisible = ref(false)
const mobileUrl = computed(() => `${window.location.origin}/mobile/qc/timeliness`)

async function copyMobileUrl(): Promise<void> {
  try {
    await navigator.clipboard.writeText(mobileUrl.value)
    ElMessage.success('手机端链接已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择链接复制')
  }
}

const loading = ref(false)
const exporting = ref(false)
const loadError = ref('')
const stats = ref<MonthlyStats | null>(null)
const totalRows = ref(0)
const page = ref(1)
const pageSize = ref(50)
const dept = ref('')
const doctor = ref('')
const departments = ref<DepartmentOption[]>([])
const allHospital = ref(false)

/** WP04：固定表头高度（页头+筛选+汇总卡让出）。 */
const tableMaxHeight = 'calc(100vh - 380px)'

type QuickRange = 'month' | 'prevMonth' | 'last7' | 'last10' | 'last30' | 'custom'
const quickRange = ref<QuickRange>('month')
const dateRange = ref<[string, string]>([monthFirstDay(), todayText()])
/** 程序化写回日期框时抑制「手动改日期 → 切自定义」。 */
let suppressDateWatch = false

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function fmtDate(date: Date): string {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function todayText(): string {
  return fmtDate(new Date())
}

function monthFirstDay(offsetMonths = 0): string {
  const now = new Date()
  return fmtDate(new Date(now.getFullYear(), now.getMonth() + offsetMonths, 1))
}

function monthLastDay(offsetMonths = 0): string {
  const now = new Date()
  return fmtDate(new Date(now.getFullYear(), now.getMonth() + offsetMonths + 1, 0))
}

/** 快捷区间：非自定义自动算起止并写回日期框（本月=1日~今天；上月/近N天整段）。 */
function applyQuickRange(rawMode: string | number | boolean | undefined): void {
  const mode = String(rawMode ?? '') as QuickRange
  if (mode === 'custom') return
  const today = new Date()
  let from = monthFirstDay()
  let to = todayText()
  if (mode === 'prevMonth') {
    from = monthFirstDay(-1)
    to = monthLastDay(-1)
  } else if (mode === 'last7' || mode === 'last10' || mode === 'last30') {
    const days = mode === 'last7' ? 7 : mode === 'last10' ? 10 : 30
    const start = new Date(today)
    start.setDate(start.getDate() - (days - 1))
    from = fmtDate(start)
    to = todayText()
  }
  suppressDateWatch = true
  dateRange.value = [from, to]
  page.value = 1
  void loadStats()
}

/** 手动改日期 → 快捷区间自动切「自定义」（程序化写回除外）。 */
function onDateManualChange(): void {
  if (suppressDateWatch) {
    suppressDateWatch = false
    return
  }
  quickRange.value = 'custom'
  page.value = 1
  void loadStats()
}

const tableRows = computed<MonthlyRow[]>(() => stats.value?.rows || [])

/** SummaryStrip 6 卡：事件总数 / 按时率 / 超时未完成 / 锁定(超时申请)次数 / 豁免次数 / 应扣金额。 */
const totalCards = computed<SummaryItem[]>(() => {
  const totals = stats.value?.totals
  if (!totals) return []
  const denom = totals.completed_on_time + totals.completed_late
  const rate = denom ? Math.round((totals.completed_on_time / denom) * 1000) / 10 : 0
  return [
    { key: 'total', label: '事件总数', value: totals.total },
    { key: 'on_time_rate', label: '按时完成率', value: `${rate.toFixed(1)}%`, tone: rate >= 95 ? 'success' : rate >= 85 ? 'warning' : 'danger' },
    { key: 'overdue', label: '超时未完成', value: totals.overdue, tone: 'danger' },
    { key: 'approval_count', label: '锁定(超时申请)次数', value: totals.approval_count, tone: 'warning' },
    { key: 'exempt_count', label: '豁免次数', value: totals.exempt_count, tone: 'info' },
    { key: 'penalty_amount_total', label: '应扣金额(元)', value: totals.penalty_amount_total, tone: 'danger' },
  ]
})

/** 按时率 tag 颜色档（95/85 分界，与合计口径一致）。 */
function rowTagType(rate: number | undefined): 'success' | 'warning' | 'danger' {
  const value = Number(rate || 0)
  if (value >= 95) return 'success'
  if (value >= 85) return 'warning'
  return 'danger'
}

/** 合计行：首列「全期合计」，其余列取后端 totals（全量合计，非当页小计）。 */
function summaryMethod({ columns }: { columns: Array<{ property?: string; label: string }> }): Array<string> {
  const totals = stats.value?.totals
  if (!totals) return columns.map(() => '')
  const denom = totals.completed_on_time + totals.completed_late
  const rate = denom ? Math.round((totals.completed_on_time / denom) * 1000) / 10 : 0
  const byProp: Record<string, string | number> = {
    dept_name: '全期合计',
    total: totals.total,
    completed_on_time: totals.completed_on_time,
    completed_late: totals.completed_late,
    overdue: totals.overdue,
    warning: totals.warning,
    approval_count: totals.approval_count,
    approved_unlock_count: totals.approved_unlock_count,
    exempt_count: totals.exempt_count,
    penalty_amount_total: totals.penalty_amount_total,
  }
  return columns.map((col, index) => {
    if (index === 0) return '全期合计'
    if (col.property === undefined && col.label === '按时率') return `${rate.toFixed(1)}%`
    const value = col.property ? byProp[col.property] : ''
    return value === undefined ? '' : String(value)
  })
}

onMounted(async () => {
  try {
    const dicts = await fetchTimelinessDictsApi()
    departments.value = dicts.departments || []
    dept.value = dicts.default_dept || ''
    allHospital.value = Boolean(dicts.all_hospital)
  } catch {
    // 字典暂不可用时按后端授权范围查询。
  }
  await loadStats()
})

function search(): void {
  page.value = 1
  void loadStats()
}

function resetFilters(): void {
  dept.value = ''
  doctor.value = ''
  quickRange.value = 'month'
  applyQuickRange('month')
}

function onPageChange(next: number): void {
  page.value = next
  void loadStats()
}

function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  void loadStats()
}

async function loadStats(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const body = await fetchMonthlyRangeStatsApi({
      date_from: dateRange.value[0],
      date_to: dateRange.value[1],
      dept: dept.value || undefined,
      doctor: doctor.value || undefined,
      page: page.value,
      limit: pageSize.value,
    })
    stats.value = body
    totalRows.value = body.total_rows ?? body.rows.length
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '考核统计加载失败'
  } finally {
    loading.value = false
  }
}

function goApprovals(): void {
  // 快捷直达独立审批中心（预填 flag=1 待办）。
  void router.push({ name: 'timeliness-approvals', query: { flag: '1', dept: dept.value } })
}

async function exportExcel(): Promise<void> {
  exporting.value = true
  try {
    await exportMonthlyApi(dateRange.value[0].slice(0, 7), dept.value || undefined, {
      date_from: dateRange.value[0],
      date_to: dateRange.value[1],
      doctor: doctor.value || undefined,
      format: 'xlsx',
    })
    ElMessage.success(`已导出 ${dateRange.value[0]} 至 ${dateRange.value[1]} 考核统计 Excel`)
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : '导出失败'
    ElMessage.error(message.includes('403') ? '无导出权限（timeliness_export）' : message)
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.tl-page {
  padding: 4px;
}
.tl-filter-row {
  display: flex;
  gap: 14px;
  flex-wrap: wrap;
  align-items: center;
}
.tl-filter-item {
  display: inline-flex;
  gap: 6px;
  align-items: center;
  font-size: 13px;
  color: var(--el-text-color-regular);
}
.tl-alert {
  margin-bottom: 10px;
}
.cell-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.mobile-entry-tip {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.mobile-entry-link {
  color: inherit;
  text-decoration: none;
}
</style>

<style>
/* WP04：固定表头吸顶样式（show-summary 场景下表头冻结在 max-height 顶部）。 */
.ma-sticky-th {
  position: sticky !important;
  top: 0;
  z-index: 3;
  background: #f1f5f9 !important;
  color: #0f172a !important;
  font-weight: 600 !important;
}
</style>
