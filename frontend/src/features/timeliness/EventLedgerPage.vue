<template>
  <section class="tl-page">
    <PageHeader
      title="在院时效台账"
      description="规则命中事件（只读）：列表与详情受科室可见性约束；状态流转与通知动作全量留痕；人工豁免即时终态化。"
    >
      <template #actions>
        <el-button size="small" @click="loadEvents">刷新</el-button>
      </template>
    </PageHeader>

    <FilterPanel title="筛选条件" :collapsible="true" @search="search" @reset="resetFilters">
      <div class="tl-filter-row">
        <label class="tl-filter-item">
          科室
          <el-select
            v-model="filters.dept"
            filterable
            clearable
            :placeholder="dicts?.all_hospital ? '全院' : '全部授权科室'"
            style="width: 190px"
          >
            <el-option :label="dicts?.all_hospital ? '全院' : '全部授权科室'" value="" />
            <el-option
              v-for="dept in departments"
              :key="dept.id"
              :label="dept.name"
              :value="dept.code || dept.name"
            />
          </el-select>
        </label>
        <label class="tl-filter-item">
          状态
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 140px">
            <el-option
              v-for="status in statusOptions"
              :key="status.value"
              :label="status.label"
              :value="status.value"
            />
          </el-select>
        </label>
        <label class="tl-filter-item">
          规则
          <el-select v-model="filters.rule_code" filterable clearable placeholder="全部规则（可搜索中文名）" style="width: 210px">
            <el-option
              v-for="rule in rules"
              :key="rule.rule_code"
              :label="rule.rule_name ? `${rule.rule_name}（${rule.rule_code}）` : rule.rule_code"
              :value="rule.rule_code"
            />
          </el-select>
        </label>
        <label class="tl-filter-item">
          患者
          <el-input v-model="filters.patient_id" clearable placeholder="患者号（精确匹配）" style="width: 150px" />
        </label>
        <label class="tl-filter-item">
          责任医生
          <el-input v-model="filters.doctor" clearable placeholder="姓名或工号" style="width: 140px" />
        </label>
      </div>
      <template #more>
        <div class="tl-filter-row">
          <label class="tl-filter-item">
            起止日期
            <el-date-picker
              v-model="dateRange"
              type="daterange"
              value-format="YYYY-MM-DD"
              range-separator="至"
              start-placeholder="开始"
              end-placeholder="结束"
              style="width: 250px"
            />
          </label>
        </div>
      </template>
    </FilterPanel>

    <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

    <el-card shadow="never">
      <el-table
        v-loading="loading"
        :data="events"
        size="small"
        border
        :max-height="tableMaxHeight"
        class="tl-event-table"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="tl-hint">事件唯一号：{{ row.event_uid }}</div>
          </template>
        </el-table-column>
        <el-table-column label="患者信息" width="180" fixed="left">
          <template #default="{ row }">
            <div class="tl-cell-main">{{ row.patient_name || row.patient_id || '—' }}</div>
            <div class="cell-sub">
              <span v-if="row.sex || row.age" class="tl-grey">{{ row.sex }}<template v-if="row.age"> · {{ row.age }}岁</template></span>
              <span class="tl-grey">患者号 {{ row.patient_id || '—' }}<template v-if="row.inp_no"> / 住院号 {{ row.inp_no }}</template></span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="科室与医生" width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.dept_name || row.dept_code || '—' }}</div>
            <div class="cell-sub">
              {{ row.responsible_doctor_name ? `${row.responsible_doctor_name}（${row.responsible_doctor_id || '—'}）` : (row.responsible_doctor_id || '—') }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="入院与诊断" width="190" show-overflow-tooltip>
          <template #default="{ row }">
            <div>
              {{ fmtShort(row.admission_date) || '—' }}
              <el-tag v-if="row.nursing_level" size="small" type="info" class="tl-nursing">{{ row.nursing_level }}</el-tag>
            </div>
            <div class="cell-sub" :title="row.admission_diagnosis || ''">{{ row.admission_diagnosis || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="质控规则" width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.rule_name || row.rule_code }}</template>
        </el-table-column>
        <el-table-column label="计时节点" width="175">
          <template #default="{ row }">
            <div class="cell-sub">起算 {{ fmtShort(row.t0) }}</div>
            <div class="cell-sub">截止 {{ fmtShort(row.deadline) }}</div>
            <div v-if="row.completed_at" class="cell-sub tl-ok">完成 {{ fmtShort(row.completed_at) }}</div>
          </template>
        </el-table-column>
        <el-table-column label="时效状态" width="150">
          <template #default="{ row }">
            <el-tag size="small" :type="countdownBadge(row as TlEvent).type">{{ countdownBadge(row as TlEvent).text }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="解锁审批" width="120">
          <template #default="{ row }">
            <template v-if="row.latest_approval">
              <el-tag size="small" :type="row.latest_approval.flag === '2' ? 'success' : 'warning'">
                {{ row.latest_approval.flag === '2' ? '已解锁' : '锁定待审批' }}
              </el-tag>
              <div v-if="row.latest_approval.penalty_exempt" class="cell-sub">
                <el-tag size="small" type="info">已豁免</el-tag>
              </div>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="210" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text data-testid="event-detail" @click="openDetail(row as TlEvent)">详情</el-button>
            <el-button
              v-if="canExempt(row as TlEvent)"
              size="small"
              text
              type="warning"
              data-testid="event-register-exempt"
              @click="openExempt(row as TlEvent)"
            >
              豁免
            </el-button>
            <el-button
              v-if="(row as TlEvent).status === 'APPLYING' || (row as TlEvent).status === 'APPROVED'"
              size="small"
              text
              type="primary"
              data-testid="event-go-approve"
              @click="goApprove(row as TlEvent)"
            >
              去审批
            </el-button>
            <HolographyButton :patient-id="(row as TlEvent).patient_id" link />
          </template>
        </el-table-column>
      </el-table>

      <div class="tl-pagination">
        <el-pagination
          v-model:current-page="page"
          :page-size="limit"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadEvents"
        />
      </div>
    </el-card>

    <el-dialog v-model="detailVisible" title="事件详情（时间线 + 动作留痕）" width="min(94vw, 880px)">
      <template v-if="detail">
        <div class="tl-dialog-head">
          <h4 class="tl-section-title tl-dialog-title">患者临床信息</h4>
          <HolographyButton :patient-id="detail.patient_id" />
        </div>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="患者">{{ detail.patient_name || detail.patient_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="患者号 / 住院号">{{ detail.patient_id || '—' }} / {{ detail.inp_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="性别 / 年龄">{{ detail.sex || '—' }} / {{ detail.age ? `${detail.age}岁` : '—' }}</el-descriptions-item>
          <el-descriptions-item label="入院日期">{{ fmtTime(detail.admission_date) }}</el-descriptions-item>
          <el-descriptions-item label="入院诊断" :span="2">{{ detail.admission_diagnosis || '—' }}</el-descriptions-item>
          <el-descriptions-item label="护理级别">{{ detail.nursing_level || '—' }}</el-descriptions-item>
          <el-descriptions-item label="科室">{{ detail.dept_name || detail.dept_code || '—' }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="tl-section-title">时效与解锁记录</h4>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="规则">{{ detail.rule_name ? `${detail.rule_name}（${detail.rule_code}）` : detail.rule_code }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">{{ eventStatusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="起算 T0">{{ fmtTime(detail.t0) }}</el-descriptions-item>
          <el-descriptions-item label="截止">{{ fmtTime(detail.deadline) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ fmtTime(detail.completed_at) }}</el-descriptions-item>
          <el-descriptions-item label="超时(分)">{{ detail.overdue_minutes ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="剩余/已超时">{{ countdownBadge(detail).text }}</el-descriptions-item>
          <el-descriptions-item label="责任医生">{{ detail.responsible_doctor_name ? `${detail.responsible_doctor_name}（${detail.responsible_doctor_id || '—'}）` : (detail.responsible_doctor_id || '—') }}</el-descriptions-item>
          <el-descriptions-item label="最近解锁申请" :span="2">
            <template v-if="detail.latest_approval">
              {{ detail.latest_approval.flag === '2' ? '已解锁' : '锁定待审批' }}
              （申请 {{ fmtTime(detail.latest_approval.apply_date_time) }}
              <template v-if="detail.latest_approval.penalty_exempt"> · 已豁免</template>）
            </template>
            <template v-else>—</template>
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="tl-section-title">状态流转历史</h4>
        <el-table :data="detail.history" size="small" border max-height="200">
          <el-table-column label="从" width="120">
            <template #default="{ row }">{{ row.from_status ? eventStatusLabel(row.from_status) : '（新建）' }}</template>
          </el-table-column>
          <el-table-column label="至" width="120">
            <template #default="{ row }">{{ eventStatusLabel(row.to_status) }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
          <el-table-column prop="scan_run_id" label="扫描批次" width="90" />
          <el-table-column label="时间" min-width="150">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>

        <h4 class="tl-section-title">动作留痕（通知 / 写入 / 豁免全量记录）</h4>
        <el-table :data="detail.action_logs" size="small" border max-height="200">
          <el-table-column label="动作" min-width="130">
            <template #default="{ row }">{{ actionTypeLabel(row.action_type) }}</template>
          </el-table-column>
          <el-table-column label="模式" width="130">
            <template #default="{ row }">
              <el-tag size="small" :type="actionModeTagType(row.mode)">{{ actionModeExecLabel(row.mode) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="target" label="目标" width="120" show-overflow-tooltip />
          <el-table-column prop="operator" label="操作人" width="110" />
          <el-table-column prop="result" label="结果" min-width="180" show-overflow-tooltip />
          <el-table-column label="时间" min-width="150">
            <template #default="{ row }">{{ fmtTime(row.created_at) }}</template>
          </el-table-column>
        </el-table>
      </template>
      <div v-else-if="detailLoading" v-loading="true" class="tl-detail-loading" />
    </el-dialog>

    <!-- 事件人工豁免（2026-11-15 P0-2：即时终态化，需 timeliness_admin） -->
    <el-dialog v-model="exemptVisible" title="事件特殊豁免" width="460px">
      <p class="tl-subtitle">
        患者 {{ exemptTarget ? patientText(exemptTarget) : '' }} ·
        {{ exemptTarget?.rule_name || exemptTarget?.rule_code }}
      </p>
      <el-alert
        type="warning"
        :closable="false"
        class="tl-alert"
        title="豁免后该事件进入终态，不再发送预警或触发锁定"
      />
      <el-input
        v-model="exemptReason"
        type="textarea"
        :rows="3"
        placeholder="豁免原因（必填，写入审计留痕）"
        data-testid="event-exempt-reason-input"
      />
      <template #footer>
        <el-button @click="exemptVisible = false">取消</el-button>
        <el-button
          type="primary"
          :disabled="!exemptReason.trim()"
          :loading="exemptBusy"
          data-testid="event-exempt-confirm"
          @click="submitExempt"
        >
          确定豁免
        </el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
// T6 事件台账页（只读 + 人工豁免写入口）：过滤条件与 GET /timeliness/events 参数一一对应；
// dateRange 拆为 date_from / date_to（后端对纯日期 date_to 取当天 23:59:59 含当日）。
// 2026-11-15 P0-1：路由 keepAlive 下用 applyRouteQuery + watch(route.query) 响应跨页带参
// 跳转；P0-2：登记豁免走 POST /events/{id}/exempt 即时终态化；P1-1/P1-2：详情弹窗中文化。
// WP04（064 总计划）：临床字段（住院号/性别年龄/入院日期/入院诊断/护理级别）、
// remaining_minutes 剩余胶囊、latest_approval 解锁状态、责任医生筛选、固定表头 +
// 左侧患者列/右侧操作列冻结、360 全息按钮、详情双 descriptions（临床信息+时效解锁）。
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import HolographyButton from '@/components/base/HolographyButton.vue'
import {
  exemptEventApi,
  fetchTimelinessEventApi,
  fetchTimelinessEventsApi,
  fetchTimelinessDictsApi,
  fetchTimelinessRulesApi,
} from './api'
import {
  actionModeExecLabel,
  actionModeTagType,
  actionTypeLabel,
  eventStatusLabel,
  type DepartmentOption,
  type TlDicts,
  type TlEvent,
  type TlEventDetail,
  type TlRule,
} from './types'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()

const loading = ref(false)
const loadError = ref('')
const events = ref<TlEvent[]>([])
const total = ref(0)
const page = ref(1)
const limit = 50

const dicts = ref<TlDicts | null>(null)
const rules = ref<TlRule[]>([])
const departments = ref<DepartmentOption[]>([])

const filters = reactive({
  dept: '',
  rule_code: '',
  status: '',
  patient_id: '',
  doctor: '',
})
const dateRange = ref<[string, string] | null>(null)

/** 固定表头高度（WP04）：视口减页头/筛选/分页合计。 */
const tableMaxHeight = 'calc(100vh - 340px)'

/** 状态下拉：英文枚举值 + 中文标签（预警中/已超时/按时完成/超时完成/已豁免/未到期等）。 */
const statusOptions = computed(() => {
  const fromDicts = dicts.value?.event_statuses || []
  return fromDicts.map((status) => ({ value: status, label: eventStatusLabel(status) }))
})

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<TlEventDetail | null>(null)

const exemptVisible = ref(false)
const exemptTarget = ref<TlEvent | null>(null)
const exemptReason = ref('')
const exemptBusy = ref(false)

/** 完成类/取消类/已豁免终态不再显示「豁免」。 */
function canExempt(row: TlEvent): boolean {
  const mayExempt = auth.roleName === 'admin' || auth.user?.permissions?.includes('timeliness_admin')
  return Boolean(mayExempt) && !['COMPLETED_ON_TIME', 'COMPLETED_LATE', 'CANCELLED', 'EXEMPT'].includes(row.status)
}

/** 跨页带参跳转预填（keepAlive 下 onMounted 只走一次，query 变化交给 watch）。 */
function applyRouteQuery(): void {
  const qStatus = typeof route.query.status === 'string' ? route.query.status.trim().toUpperCase() : ''
  const qPatient = typeof route.query.patient_id === 'string' ? route.query.patient_id.trim() : ''
  const qRule = typeof route.query.rule_code === 'string' ? route.query.rule_code.trim() : ''
  const qDept = typeof route.query.dept === 'string' ? route.query.dept.trim() : ''
  const qDoctor = typeof route.query.doctor === 'string' ? route.query.doctor.trim() : ''
  filters.status = qStatus
  filters.patient_id = qPatient
  filters.rule_code = qRule
  filters.doctor = qDoctor
  filters.dept = qDept || dicts.value?.default_dept || ''
  page.value = 1
}

// 首次挂载由 onMounted 统一加载（避免与 watch 双重请求）；
// 之后的 query 变化（同路由带参跳转）在此响应并重查。
watch(
  () => route.query,
  () => {
    if (route.name === 'quality-timeliness-events') {
      applyRouteQuery()
      void loadEvents()
    }
  },
)

onMounted(async () => {
  await Promise.allSettled([
    fetchTimelinessDictsApi().then((res) => {
      dicts.value = res
      departments.value = res.departments || []
    }),
    fetchTimelinessRulesApi().then((res) => (rules.value = res.items)),
  ])
  applyRouteQuery()
  await loadEvents()
})

function search(): void {
  page.value = 1
  loadEvents()
}

function resetFilters(): void {
  filters.dept = dicts.value?.default_dept || ''
  filters.rule_code = ''
  filters.status = ''
  filters.patient_id = ''
  filters.doctor = ''
  dateRange.value = null
  search()
}

async function loadEvents(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchTimelinessEventsApi({
      page: page.value,
      limit,
      dept: filters.dept || undefined,
      rule_code: filters.rule_code || undefined,
      status: filters.status || undefined,
      patient_id: filters.patient_id || undefined,
      doctor: filters.doctor || undefined,
      date_from: dateRange.value?.[0] || undefined,
      date_to: dateRange.value?.[1] || undefined,
    })
    events.value = res.items
    total.value = res.total
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '事件台账加载失败'
  } finally {
    loading.value = false
  }
}

async function openDetail(row: TlEvent): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await fetchTimelinessEventApi(row.id)
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '事件详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

function openExempt(row: TlEvent): void {
  exemptTarget.value = row
  exemptReason.value = ''
  exemptVisible.value = true
}

async function submitExempt(): Promise<void> {
  if (!exemptTarget.value) return
  exemptBusy.value = true
  try {
    const result = await exemptEventApi(exemptTarget.value.id, exemptReason.value.trim())
    ElMessage.success(result.message === 'event already exempted' ? '该事件已豁免' : '已豁免')
    exemptVisible.value = false
    await loadEvents()
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : '豁免失败'
    ElMessage.error(
      message.includes('403') ? '需要时效管理员权限 timeliness_admin' : message,
    )
  } finally {
    exemptBusy.value = false
  }
}

/** APPLYING/APPROVED 事件的解锁走审批中心（按患者预填筛选）。 */
function goApprove(row: TlEvent): void {
  void router.push({ name: 'timeliness-approvals', query: { patient_id: row.patient_id, dept: row.dept_code || '' } })
}

function fmtTime(value: string | null | undefined): string {
  return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
}

/** 表格短时间：MM-DD HH:mm（年份通常为当年，省空间）。 */
function fmtShort(value: string | null | undefined): string {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(5, 16)
}

/** 患者可读文本：有姓名展示「姓名（住院号 · 住院次N）」，无姓名回退「住院号（住院次 N）」。 */
function patientText(row: Pick<TlEvent, 'patient_id' | 'visit_id' | 'patient_name' | 'inp_no'>): string {
  const pid = row.patient_id || '—'
  const seq = `住院次 ${row.visit_id || '—'}`
  if (row.patient_name || row.inp_no) {
    return `${row.patient_name || '—'}（${row.inp_no || pid} · ${seq}）`
  }
  return `${pid}（${seq}）`
}

/**
 * WP04 纯函数：时效状态胶囊（type + 中文文案）。
 * 终态优先；remaining_minutes<0 已超时（≥1440 分钟显示天时，否则小时分）；
 * WARNING 剩余高亮；其余显示剩余。
 */
function countdownBadge(row: Pick<TlEvent, 'status' | 'remaining_minutes' | 'overdue_minutes'>): {
  type: 'success' | 'info' | 'danger' | 'warning'
  text: string
} {
  if (row.status === 'COMPLETED_ON_TIME') return { type: 'success', text: '按时完成' }
  if (row.status === 'COMPLETED_LATE') return { type: 'info', text: '超时完成' }
  if (row.status === 'EXEMPT') return { type: 'info', text: '已豁免' }
  if (row.status === 'CANCELLED') return { type: 'info', text: '已取消' }
  const minutes = row.remaining_minutes
  if (minutes !== null && minutes !== undefined) {
    if (minutes < 0) return { type: 'danger', text: `已超时 ${formatDuration(-minutes)}` }
    if (row.status === 'WARNING') return { type: 'warning', text: `剩余 ${formatDuration(minutes)}` }
    return { type: 'info', text: `剩余 ${formatDuration(minutes)}` }
  }
  if (row.status === 'OVERDUE') {
    return { type: 'danger', text: `已超时 ${formatDuration(row.overdue_minutes || 0)}` }
  }
  return { type: 'warning', text: eventStatusLabel(row.status) || '计时中' }
}

/** 分钟 → 「X天Y时」或「X小时Y分」中文时长。 */
function formatDuration(totalMinutes: number): string {
  const safe = Math.max(0, Math.floor(totalMinutes))
  if (safe >= 1440) {
    const days = Math.floor(safe / 1440)
    const hours = Math.floor((safe % 1440) / 60)
    return hours > 0 ? `${days}天${hours}时` : `${days}天`
  }
  const hours = Math.floor(safe / 60)
  const minutes = safe % 60
  return `${hours}小时${minutes}分`
}
</script>

<style scoped>
.tl-page {
  padding: 4px;
}
.tl-alert {
  margin-bottom: 10px;
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
.tl-event-table {
  min-height: 360px;
}
.tl-cell-main {
  font-weight: 600;
}
.cell-sub {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}
.tl-grey {
  display: inline-block;
  margin-right: 6px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.tl-nursing {
  margin-left: 4px;
}
.tl-ok {
  color: var(--el-color-success);
}
.tl-pagination {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
.tl-section-title {
  margin: 14px 0 6px;
  font-size: 13px;
}
.tl-dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.tl-dialog-title {
  margin: 4px 0 6px;
}
.tl-detail-loading {
  min-height: 120px;
}
.tl-subtitle {
  margin: 4px 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tl-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
