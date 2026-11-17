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

    <el-card shadow="never">
      <el-form inline size="small" class="tl-filters">
        <el-form-item label="科室">
          <el-select
            v-model="filters.dept"
            filterable
            clearable
            placeholder="全部可见科室"
            style="width: 200px"
          >
            <el-option
              v-for="dept in departments"
              :key="dept.id"
              :label="dept.code ? `${dept.code} ${dept.name}` : dept.name"
              :value="dept.code || dept.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="规则">
          <el-select v-model="filters.rule_code" filterable clearable placeholder="全部规则（可搜索中文名）" style="width: 220px">
            <el-option
              v-for="rule in rules"
              :key="rule.rule_code"
              :label="rule.rule_name ? `${rule.rule_name}（${rule.rule_code}）` : rule.rule_code"
              :value="rule.rule_code"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 150px">
            <el-option
              v-for="status in dicts?.event_statuses || []"
              :key="status"
              :label="eventStatusLabel(status)"
              :value="status"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="患者ID">
          <el-input v-model="filters.patient_id" clearable placeholder="精确匹配" style="width: 140px" />
        </el-form-item>
        <el-form-item label="起算日期">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 240px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
        </el-form-item>
      </el-form>

      <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

      <el-table v-loading="loading" :data="events" size="small" border>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="tl-hint">事件唯一号：{{ row.event_uid }}</div>
          </template>
        </el-table-column>
        <el-table-column label="规则" width="150">
          <template #default="{ row }">{{ row.rule_name || row.rule_code }}</template>
        </el-table-column>
        <el-table-column label="患者（姓名/住院号）" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="tl-patient">{{ patientText(row as TlEvent) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="科室" width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.dept_name || row.dept_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="责任医生" width="130" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.responsible_doctor_name ? `${row.responsible_doctor_name}（${row.responsible_doctor_id || '—'}）` : (row.responsible_doctor_id || '—') }}
          </template>
        </el-table-column>
        <el-table-column label="起算时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.t0) }}</template>
        </el-table-column>
        <el-table-column label="截止时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.deadline) }}</template>
        </el-table-column>
        <el-table-column label="当前状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.status)">{{ eventStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="超时时长(分)" width="100">
          <template #default="{ row }">{{ row.overdue_minutes ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text data-testid="event-detail" @click="openDetail(row as TlEvent)">查看时间线</el-button>
            <el-button
              v-if="canExempt(row as TlEvent)"
              size="small"
              text
              type="warning"
              data-testid="event-register-exempt"
              @click="openExempt(row as TlEvent)"
            >
              登记豁免
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
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="事件唯一号" :span="2">{{ detail.event_uid }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ eventStatusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="规则">{{ detail.rule_name ? `${detail.rule_name}（${detail.rule_code}）` : detail.rule_code }}</el-descriptions-item>
          <el-descriptions-item label="患者">{{ patientText(detail) }}</el-descriptions-item>
          <el-descriptions-item label="科室">{{ detail.dept_name || detail.dept_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="起算 T0">{{ fmtTime(detail.t0) }}</el-descriptions-item>
          <el-descriptions-item label="截止">{{ fmtTime(detail.deadline) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ fmtTime(detail.completed_at) }}</el-descriptions-item>
          <el-descriptions-item label="超时(分)">{{ detail.overdue_minutes ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="责任医生">{{ detail.responsible_doctor_name ? `${detail.responsible_doctor_name}（${detail.responsible_doctor_id || '—'}）` : (detail.responsible_doctor_id || '—') }}</el-descriptions-item>
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
// 跳转（首页预警/超时快捷卡二次点击也能刷新）；P0-2：登记豁免走
// POST /events/{id}/exempt 即时终态化（替代跳空审批表的死胡同），APPLYING/APPROVED
// 引导「去审批」；P1-1/P1-2：详情弹窗中文化 + PageHeader 视觉统一。
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import {
  exemptEventApi,
  fetchDepartmentsApi,
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
})
const dateRange = ref<[string, string] | null>(null)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<TlEventDetail | null>(null)

const exemptVisible = ref(false)
const exemptTarget = ref<TlEvent | null>(null)
const exemptReason = ref('')
const exemptBusy = ref(false)

/** 完成类/取消类/已豁免终态不再显示「登记豁免」。 */
function canExempt(row: TlEvent): boolean {
  return !['COMPLETED_ON_TIME', 'COMPLETED_LATE', 'CANCELLED', 'EXEMPT'].includes(row.status)
}

/** 跨页带参跳转预填（keepAlive 下 onMounted 只走一次，query 变化交给 watch）。 */
function applyRouteQuery(): void {
  const qStatus = typeof route.query.status === 'string' ? route.query.status.trim().toUpperCase() : ''
  const qPatient = typeof route.query.patient_id === 'string' ? route.query.patient_id.trim() : ''
  const qRule = typeof route.query.rule_code === 'string' ? route.query.rule_code.trim() : ''
  const qDept = typeof route.query.dept === 'string' ? route.query.dept.trim() : ''
  filters.status = qStatus
  filters.patient_id = qPatient
  filters.rule_code = qRule
  filters.dept = qDept
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
  applyRouteQuery()
  await Promise.allSettled([
    fetchTimelinessDictsApi().then((res) => (dicts.value = res)),
    fetchTimelinessRulesApi().then((res) => (rules.value = res.items)),
    fetchDepartmentsApi().then((res) => (departments.value = res)),
  ])
  await loadEvents()
})

function search(): void {
  page.value = 1
  loadEvents()
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
  void router.push({ name: 'timeliness-approvals', query: { patient_id: row.patient_id } })
}

function fmtTime(value: string | null): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '—'
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

function statusTagType(status: string): 'danger' | 'warning' | 'success' | 'info' {
  if (status === 'OVERDUE' || status === 'COMPLETED_LATE') return 'danger'
  if (status === 'WARNING' || status === 'APPLYING') return 'warning'
  if (status === 'COMPLETED_ON_TIME' || status === 'APPROVED' || status === 'EXEMPT') return 'success'
  return 'info'
}
</script>

<style scoped>
.tl-page {
  padding: 4px;
}
.tl-filters {
  margin-bottom: 4px;
}
.tl-alert {
  margin-bottom: 10px;
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
.tl-detail-loading {
  min-height: 120px;
}
.tl-subtitle {
  margin: 4px 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tl-patient {
  font-variant-numeric: tabular-nums;
}
.tl-hint {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
</style>
