<template>
  <section class="tl-approvals">
    <el-alert
      v-if="loadError"
      type="error"
      :title="loadError"
      :closable="false"
      class="tl-alert"
    />

    <!-- WP04：状态汇总卡（同筛选不含 flag 的全量口径；点击前两卡切换 flag 筛选） -->
    <div @click="onSummaryClick">
      <SummaryStrip :items="summaryItems" :loading="loading" />
    </div>

    <!-- 筛选区（WP04：申请日期范围/申请人新增；监控项/规则移入更多筛选） -->
    <FilterPanel title="筛选条件" :collapsible="true" data-testid="approval-filters" @search="reload" @reset="resetFilters">
      <div class="tl-filter-row">
        <label class="tl-filter-item">
          患者号
          <el-input
            v-model="filters.patient_id"
            placeholder="患者号（精确匹配）"
            clearable
            style="width: 150px"
            @change="reload"
          />
        </label>
        <label class="tl-filter-item">
          科室
          <el-select
            v-model="filters.dept"
            filterable
            clearable
            :placeholder="allHospital ? '全院' : '全部授权科室'"
            style="width: 180px"
            @change="reload"
          >
            <el-option :label="allHospital ? '全院' : '全部授权科室'" value="" />
            <el-option
              v-for="dept in departments"
              :key="dept.id"
              :label="dept.name"
              :value="dept.code || dept.name"
            />
          </el-select>
        </label>
        <label class="tl-filter-item">
          审批状态
          <el-select
            v-model="filters.flag"
            placeholder="全部状态"
            clearable
            style="width: 170px"
            @change="reload"
          >
            <el-option
              v-for="opt in APPROVAL_FLAG_OPTIONS"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </label>
        <label class="tl-filter-item">
          申请人
          <el-input
            v-model="filters.applicant"
            placeholder="姓名或工号"
            clearable
            style="width: 140px"
            @change="reload"
          />
        </label>
        <label class="tl-filter-item">
          申请日期
          <el-date-picker
            v-model="applyDateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 240px"
            @change="reload"
          />
        </label>
      </div>
      <template #more>
        <div class="tl-filter-row">
          <label class="tl-filter-item">
            监控项 / 规则
            <el-select
              v-model="filters.monitor_code"
              filterable
              clearable
              placeholder="触发规则 / 监控项"
              style="width: 220px"
              @change="reload"
            >
              <el-option
                v-for="item in monitorItems"
                :key="item.code"
                :label="`${item.label}（${item.code}）`"
                :value="item.code"
              />
            </el-select>
          </label>
        </div>
      </template>
    </FilterPanel>

    <!-- 2026-11-15 去黑话 + WP04 深度升级：固定表头 + 左侧患者列/右侧操作列冻结 -->
    <el-table v-loading="loading" :data="rows" size="small" border :max-height="tableMaxHeight">
      <el-table-column label="患者信息" width="190" fixed="left">
        <template #default="{ row }">
          <div class="tl-cell-main">{{ row.patient_name || row.patient_id || '—' }}</div>
          <div class="cell-sub">
            患者号 {{ row.patient_id || '—' }}<template v-if="row.inp_no"> / 住院号 {{ row.inp_no }}</template>
          </div>
          <div class="cell-sub">入院 {{ fmtShort(row.admission_date) || '—' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="科室与申请医生" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <div>{{ row.dept_name || row.dept_code || '—' }}</div>
          <div class="cell-sub">
            {{ row.apply_user_name ? `${row.apply_user_name}（${row.apply_user_id || '—'}）` : (row.apply_user_id || '—') }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="触发规则与超时" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <div>{{ row.rule_name || row.monitor_code || '—' }}</div>
          <div v-if="row.event_overdue_minutes" class="cell-sub tl-danger">超时 {{ formatOverdueHours(row.event_overdue_minutes) }}</div>
        </template>
      </el-table-column>
      <el-table-column label="申请时间与原因" min-width="200">
        <template #default="{ row }">
          <div>{{ fmtShort(row.apply_date_time) || '—' }}</div>
          <div class="cell-sub tl-reason" :title="row.apply_reason || ''">
            {{ row.apply_reason || '—' }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="审批结果" min-width="170">
        <template #default="{ row }">
          <el-tag :type="row.flag === '2' ? 'success' : 'warning'" size="small">
            {{ approvalFlagLabel(row.flag) }}
          </el-tag>
          <div class="cell-sub">
            {{ row.approve_user_name || row.approve_user_id || (row.flag === '2' ? '' : '待审批') }}
            <template v-if="row.approve_date_time"> · {{ fmtShort(row.approve_date_time) }}</template>
          </div>
          <div v-if="row.penalty_exempt && row.exempt_reason" class="cell-sub" :title="row.exempt_reason">
            豁免原因：{{ row.exempt_reason }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="应扣金额" width="100">
        <template #default="{ row }">
          <span :class="{ 'is-exempt': row.penalty_exempt }">{{ approvalPenaltyText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="解锁类型" width="100">
        <template #default="{ row }">{{ approvalTypeLabel(row.type) }}</template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="210" fixed="right">
        <template #default="{ row }">
          <el-button
            size="small"
            :type="row.penalty_exempt ? 'info' : 'warning'"
            plain
            data-testid="approval-exempt-toggle"
            @click="openExempt(row as TlApproval)"
          >
            {{ row.penalty_exempt ? '取消豁免' : '扣罚豁免' }}
          </el-button>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="row.flag === '2'"
            data-testid="approval-approve"
            @click="openApprove(row as TlApproval)"
          >
            审批解锁
          </el-button>
          <HolographyButton :patient-id="(row as TlApproval).patient_id" link />
        </template>
      </el-table-column>
    </el-table>
    <p v-if="!loading && rows.length === 0" class="tl-subtitle">当前筛选条件下无审批记录。</p>

    <el-pagination
      v-if="total > pageSize"
      v-model:current-page="page"
      :page-size="pageSize"
      :total="total"
      layout="prev, pager, next, total"
      size="small"
      class="tl-pagination"
      @current-change="reload"
    />

    <!-- 豁免/取消豁免：原因必填 -->
    <el-dialog v-model="exemptVisible" :title="exemptTarget?.penalty_exempt ? '取消扣罚豁免' : '扣罚豁免'" width="420px">
      <p class="tl-subtitle">
        患者 {{ exemptTarget ? patientText(exemptTarget) : '' }}（{{ ruleText(exemptTarget) }}）·
        {{ exemptTarget?.penalty_exempt ? '取消后恢复应扣金额入账' : '豁免后不计入应扣金额统计' }}
      </p>
      <el-input
        v-model="exemptReason"
        type="textarea"
        :rows="3"
        placeholder="豁免/取消原因（必填，写入审计日志）"
        data-testid="exempt-reason-input"
      />
      <template #footer>
        <el-button @click="exemptVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!exemptReason.trim()" :loading="actionBusy" data-testid="exempt-confirm" @click="submitExempt">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 审批解锁：先 dry-run 预览，再确认提交 -->
    <el-dialog v-model="approveVisible" title="审批解锁（回写 JHEMR）" width="520px">
      <p class="tl-subtitle">
        患者 {{ approveTarget ? patientText(approveTarget) : '' }} · {{ ruleText(approveTarget) }} ·
        {{ approvalFlagLabel(approveTarget?.flag) }}
      </p>
      <el-alert
        v-if="approvePreview"
        :type="approvePreview.ok ? 'success' : 'warning'"
        :closable="false"
        class="tl-alert"
        :title="`演练结果：${approvePreview.message}`"
        :description="approvePreview.reason"
      />
      <el-alert
        v-else
        type="info"
        :closable="false"
        title="第一步先演练预览（dry_run），确认回写条件后再提交真实解锁"
      />
      <template #footer>
        <el-button @click="approveVisible = false">关闭</el-button>
        <el-button :loading="actionBusy" data-testid="approve-dry-run" @click="runApproveDryRun">
          演练预览
        </el-button>
        <el-button
          type="primary"
          :disabled="!approvePreview || !approvePreview.ok"
          :loading="actionBusy"
          data-testid="approve-confirm"
          @click="submitApprove"
        >
          确认解锁
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
// 审批与扣罚台账（2026-11-13 返工新增；2026-11-15 去黑话 + 带参跳转响应）：
// - GET /timeliness/approvals 列表（患者/科室/监控码/状态筛选）；
// - 豁免/取消豁免（原因必填入审计）；审批解锁先 dry_run 预览再确认——
//   写网关（timeliness.jhemr_write.enabled）未开时后端 409，页面友好展示提示；
// - P0-1：watch(route.query) 响应首页（?flag=1）与事件页（?patient_id=xxx）带参跳入，
//   未传的筛选项清空避免残留筛选；科室/规则筛选升级可搜索下拉（加载失败静默降级）。
// WP04（064 总计划）：状态汇总卡（status_counts）、申请日期范围与申请人筛选、
// 固定表头 + 左侧患者列/右侧操作列冻结、审批人姓名/豁免原因/关联事件超时展示、360 全息按钮。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import FilterPanel from '@/components/base/FilterPanel.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import HolographyButton from '@/components/base/HolographyButton.vue'
import {
  approveApprovalApi,
  exemptApprovalApi,
  fetchApprovalsApi,
  fetchTimelinessDictsApi,
} from './api'
import {
  APPROVAL_FLAG_OPTIONS,
  approvalFlagLabel,
  approvalPenaltyText,
} from './types'
import type { ApprovalStatusCounts, DepartmentOption, TlApproval, TlDicts } from './types'

const route = useRoute()
const auth = useAuthStore()
const canManage = computed(() => auth.roleName === 'admin' || auth.user?.permissions?.includes('timeliness_admin'))

const loading = ref(false)
const loadError = ref('')
const rows = ref<TlApproval[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50

/** WP04：固定表头高度（页头+汇总卡+筛选+分页让出）。 */
const tableMaxHeight = 'calc(100vh - 380px)'

const allHospital = ref(false)
const defaultDept = ref('')
const filters = reactive({
  patient_id: '',
  dept: '',
  monitor_code: '',
  flag: '',
  applicant: '',
})
const applyDateRange = ref<[string, string] | null>(null)

const departments = ref<DepartmentOption[]>([])
const monitorItems = ref<Array<{ code: string; label: string }>>([])

const statusCounts = ref<ApprovalStatusCounts>({ total: 0, pending: 0, approved: 0, exempted: 0 })

const summaryItems = computed<SummaryItem[]>(() => [
  { key: 'total', label: '申请总数', value: statusCounts.value.total },
  { key: 'pending', label: '锁定待审批', value: statusCounts.value.pending, tone: 'warning', hint: '点击只看待审批' },
  { key: 'approved', label: '已解锁', value: statusCounts.value.approved, tone: 'success' },
  { key: 'exempted', label: '已豁免', value: statusCounts.value.exempted, tone: 'info' },
])

/** 汇总卡点击委托：第 2 卡切 flag=1（锁定待审批），第 3 卡切 flag=2（已解锁）。 */
function onSummaryClick(event: MouseEvent): void {
  const target = event.target as HTMLElement | null
  const card = target?.closest('.summary-strip__card')
  if (!card) return
  const strip = card.parentElement
  if (!strip) return
  const index = Array.from(strip.children).indexOf(card)
  if (index === 1) {
    filters.flag = '1'
    reload()
  } else if (index === 2) {
    filters.flag = '2'
    reload()
  }
}

const exemptVisible = ref(false)
const exemptTarget = ref<TlApproval | null>(null)
const exemptReason = ref('')
const actionBusy = ref(false)

const approveVisible = ref(false)
const approveTarget = ref<TlApproval | null>(null)
const approvePreview = ref<{ ok: boolean; message: string; reason: string } | null>(null)

/** 跨页带参预填（keepAlive 下 query 变化由 watch 响应；未传的筛选项清空防残留）。 */
function applyRouteQuery(): void {
  const qPatient = typeof route.query.patient_id === 'string' ? route.query.patient_id.trim() : ''
  const qFlag = typeof route.query.flag === 'string' ? route.query.flag.trim() : ''
  filters.patient_id = qPatient
  filters.flag = qFlag
  filters.dept = typeof route.query.dept === 'string' ? route.query.dept.trim() : defaultDept.value
  page.value = 1
}

watch(
  () => route.query,
  () => {
    if (route.name === 'timeliness-approvals') {
      applyRouteQuery()
      void reload()
    }
  },
)

onMounted(async () => {
  await fetchTimelinessDictsApi()
    .then((res: TlDicts) => {
      monitorItems.value = res.monitor_items?.items || []
      departments.value = res.departments || []
      defaultDept.value = res.default_dept || ''
      allHospital.value = Boolean(res.all_hospital)
    })
    .catch(() => undefined)
  applyRouteQuery()
  await reload()
})

function resetFilters(): void {
  filters.patient_id = ''
  filters.dept = defaultDept.value
  filters.monitor_code = ''
  filters.flag = ''
  filters.applicant = ''
  applyDateRange.value = null
  reload()
}

async function reload(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const body = await fetchApprovalsApi({
      page: page.value,
      limit: pageSize,
      patient_id: filters.patient_id || undefined,
      dept: filters.dept || undefined,
      monitor_code: filters.monitor_code || undefined,
      flag: filters.flag || undefined,
      applicant: filters.applicant || undefined,
      apply_date_from: applyDateRange.value?.[0] || undefined,
      apply_date_to: applyDateRange.value?.[1] || undefined,
    })
    rows.value = body.items
    total.value = body.total
    if (body.status_counts) statusCounts.value = body.status_counts
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '审批台账加载失败'
  } finally {
    loading.value = false
  }
}

/** 表格短时间：MM-DD HH:mm。 */
function fmtShort(value: string | null | undefined): string {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(5, 16)
}

/** 关联事件超时分钟 → 「X.X 小时」（不足 1 小时显示分钟）。 */
function formatOverdueHours(minutes: number): string {
  if (minutes >= 60) return `${(minutes / 60).toFixed(1)} 小时`
  return `${minutes} 分钟`
}

/** 患者可读文本：有姓名展示「姓名（住院号 · 住院次N）」，无姓名回退「住院号（住院次 N）」。 */
function patientText(row: Pick<TlApproval, 'patient_id' | 'visit_id' | 'patient_name' | 'inp_no'> | null): string {
  if (!row) return '—'
  const pid = row.patient_id || '—'
  const seq = `住院次 ${row.visit_id || '—'}`
  if (row.patient_name || row.inp_no) {
    return `${row.patient_name || '—'}（${row.inp_no || pid} · ${seq}）`
  }
  return `${pid}（${seq}）`
}

/** 触发规则可读文本：规则中文名优先，无则回退监控码。 */
function ruleText(row: TlApproval | null): string {
  if (!row) return '—'
  return row.rule_name || row.monitor_code || '—'
}

/** 解锁类型：EXEMPT=永久豁免，其余（含临时解锁类）按语义映射，未知原样展示。 */
function approvalTypeLabel(value: string | null): string {
  const text = String(value || '').trim().toUpperCase()
  if (!text) return '—'
  if (text.includes('EXEMPT')) return '永久豁免'
  if (text.includes('UNLOCK') || text.includes('LIMIT')) return '临时解锁'
  return String(value)
}

function openExempt(row: TlApproval): void {
  exemptTarget.value = row
  exemptReason.value = ''
  exemptVisible.value = true
}

async function submitExempt(): Promise<void> {
  if (!exemptTarget.value) return
  actionBusy.value = true
  try {
    const result = await exemptApprovalApi(exemptTarget.value.id, exemptReason.value.trim(), {
      cancel: Boolean(exemptTarget.value.penalty_exempt),
    })
    ElMessage.success(result.message)
    exemptVisible.value = false
    await reload()
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : '操作失败'
    ElMessage.error(message.includes('403') ? '无操作权限（timeliness_admin）' : message)
  } finally {
    actionBusy.value = false
  }
}

function openApprove(row: TlApproval): void {
  approveTarget.value = row
  approvePreview.value = null
  approveVisible.value = true
}

async function runApproveDryRun(): Promise<void> {
  if (!approveTarget.value) return
  actionBusy.value = true
  try {
    const result = await approveApprovalApi(approveTarget.value.id, true)
    approvePreview.value = {
      ok: !/blocked/i.test(String(result.data?.reason ?? '')) && result.data?.mode !== 'BLOCKED',
      message: result.message,
      reason: String(result.data?.reason ?? ''),
    }
  } catch (exc) {
    // 网关未开 → 后端 409（detail 提示走 JHEMR 原生画布）；403 → 无权限。
    const message = exc instanceof Error ? exc.message : '演练失败'
    approvePreview.value = {
      ok: false,
      message: message.includes('409')
        ? 'JHEMR 写开关未开启（timeliness.jhemr_write.enabled=false），请在 JHEMR 原生【超时审批】画布操作'
        : message,
      reason: '',
    }
  } finally {
    actionBusy.value = false
  }
}

async function submitApprove(): Promise<void> {
  if (!approveTarget.value) return
  actionBusy.value = true
  try {
    const result = await approveApprovalApi(approveTarget.value.id, false)
    ElMessage.success(result.message)
    approveVisible.value = false
    await reload()
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : '解锁失败'
    ElMessage.error(message.includes('409') ? '回写被拒（409）：申请行不存在/已审批或写开关未开' : message)
  } finally {
    actionBusy.value = false
  }
}
</script>

<style scoped>
.tl-approvals {
  padding: 4px 0;
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
.tl-cell-main {
  font-weight: 600;
}
.cell-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.tl-danger {
  color: var(--el-color-danger);
}
.tl-reason {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.tl-subtitle {
  margin: 4px 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tl-pagination {
  margin-top: 10px;
  justify-content: flex-end;
}
.is-exempt {
  color: var(--el-text-color-secondary);
  text-decoration: line-through;
}
</style>
