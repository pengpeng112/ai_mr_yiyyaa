<template>
  <section class="tl-approvals">
    <el-alert
      v-if="loadError"
      type="error"
      :title="loadError"
      :closable="false"
      class="tl-alert"
    />

    <!-- 筛选区：患者 / 科室 / 触发规则 / 状态（flag） -->
    <div class="tl-filters" data-testid="approval-filters">
      <el-input
        v-model="filters.patient_id"
        placeholder="患者ID（精确匹配）"
        clearable
        size="small"
        style="width: 150px"
        @change="reload"
      />
      <el-select
        v-model="filters.dept"
        filterable
        clearable
        placeholder="全部科室"
        size="small"
        style="width: 180px"
        @change="reload"
      >
        <el-option
          v-for="dept in departments"
          :key="dept.id"
          :label="dept.name"
          :value="dept.code || dept.name"
        />
      </el-select>
      <el-select
        v-model="filters.monitor_code"
        filterable
        clearable
        placeholder="触发规则 / 监控项"
        size="small"
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
      <el-select
        v-model="filters.flag"
        placeholder="审批状态"
        clearable
        size="small"
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
      <el-button size="small" type="primary" plain :loading="loading" data-testid="approval-refresh" @click="reload">
        查询
      </el-button>
    </div>

    <!-- 2026-11-15 去黑话：主列优先人类可读信息，内部编码退居次要小字/悬停提示 -->
    <el-table v-loading="loading" :data="rows" size="small" border>
      <el-table-column label="申请单号" width="90">
        <template #default="{ row }">#{{ row.id }}</template>
      </el-table-column>
      <el-table-column label="患者（姓名/住院号）" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span class="tl-patient">{{ patientText(row as TlApproval) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="科室" min-width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ row.dept_name || row.dept_code || '—' }}</template>
      </el-table-column>
      <el-table-column label="触发规则" min-width="140" show-overflow-tooltip>
        <template #default="{ row }">
          <span :title="row.monitor_code">{{ ruleText(row as TlApproval) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="申请人" min-width="120">
        <template #default="{ row }">
          {{ row.apply_user_name ? `${row.apply_user_name}（${row.apply_user_id || '—'}）` : (row.apply_user_id || '—') }}
        </template>
      </el-table-column>
      <el-table-column label="解锁类型" width="100">
        <template #default="{ row }">{{ approvalTypeLabel(row.type) }}</template>
      </el-table-column>
      <el-table-column prop="apply_reason" label="申请原因" min-width="160" show-overflow-tooltip>
        <template #default="{ row }">{{ row.apply_reason || '—' }}</template>
      </el-table-column>
      <el-table-column label="状态" width="110">
        <template #default="{ row }">
          <el-tag :type="row.flag === '2' ? 'success' : 'warning'" size="small">
            {{ approvalFlagLabel(row.flag) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="apply_date_time" label="申请时间" min-width="140">
        <template #default="{ row }">{{ formatTime(row.apply_date_time) }}</template>
      </el-table-column>
      <el-table-column label="应扣金额" width="100">
        <template #default="{ row }">
          <span :class="{ 'is-exempt': row.penalty_exempt }">{{ approvalPenaltyText(row) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="豁免" width="80">
        <template #default="{ row }">
          <el-tag v-if="row.penalty_exempt" type="info" size="small">已豁免</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="审批渠道" width="110">
        <template #default="{ row }">{{ approvalChannelLabel(row.approve_channel) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="220" fixed="right">
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
//   未传的筛选项清空避免残留上次筛选；科室/规则筛选升级可搜索下拉（加载失败静默降级）。
import { onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  approveApprovalApi,
  exemptApprovalApi,
  fetchApprovalsApi,
  fetchDepartmentsApi,
  fetchTimelinessDictsApi,
} from './api'
import {
  APPROVAL_FLAG_OPTIONS,
  approvalChannelLabel,
  approvalFlagLabel,
  approvalPenaltyText,
} from './types'
import type { DepartmentOption, TlApproval, TlDicts } from './types'

const route = useRoute()

const loading = ref(false)
const loadError = ref('')
const rows = ref<TlApproval[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 50

const filters = reactive({ patient_id: '', dept: '', monitor_code: '', flag: '' })

const departments = ref<DepartmentOption[]>([])
const monitorItems = ref<Array<{ code: string; label: string }>>([])

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
  applyRouteQuery()
  // 科室/监控项字典静默加载（失败降级：下拉为空不影响手输查询链路）。
  void fetchDepartmentsApi()
    .then((res) => (departments.value = res))
    .catch(() => undefined)
  void fetchTimelinessDictsApi()
    .then((res: TlDicts) => (monitorItems.value = res.monitor_items?.items || []))
    .catch(() => undefined)
  await reload()
})

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
    })
    rows.value = body.items
    total.value = body.total
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '审批台账加载失败'
  } finally {
    loading.value = false
  }
}

function formatTime(value: string | null): string {
  return value ? value.replace('T', ' ').slice(0, 16) : '—'
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
.tl-filters {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.tl-alert {
  margin-bottom: 10px;
}
.tl-subtitle {
  margin: 4px 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tl-patient {
  font-variant-numeric: tabular-nums;
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
