<template>
  <div class="page-wrap">
    <PageHeader title="核查工作台" description="无纸化规则核查：就诊检查、缺陷人工处理、复检与试运行观察（经规则中心 BFF）" />

    <!-- 工具栏始终可用（048 F1：首次加载失败后仍可改条件重试恢复） -->
    <div class="toolbar">
      <el-input
        v-model="filterPatient" placeholder="患者ID" size="small" clearable
        style="width: 170px" @keyup.enter="resetAndLoad" @clear="resetAndLoad"
      />
      <el-input
        v-if="canReview" v-model="filterDept" placeholder="科室编码（复核角色）"
        size="small" clearable style="width: 200px" @keyup.enter="resetAndLoad" @clear="resetAndLoad"
      />
      <el-button size="small" :loading="loading" @click="loadChecks">刷新核查列表</el-button>
      <el-button size="small" :loading="trialsLoading" @click="loadTrials">试运行观察</el-button>
    </div>

    <el-alert
      v-if="listError" :title="listError" type="error" :closable="false"
      show-icon style="margin-bottom: 10px"
    >
      <el-button size="small" type="primary" plain @click="loadChecks">重试加载</el-button>
    </el-alert>

    <el-table v-loading="loading" :data="checks" stripe border size="small" max-height="420">
      <el-table-column prop="patient_id" label="患者" width="120" />
      <el-table-column prop="visit_number" label="次数" width="64" align="center" />
      <el-table-column prop="dept_name" label="科室" width="120" show-overflow-tooltip />
      <el-table-column label="检查时间" width="150">
        <template #default="{ row }">{{ row.checked_at || '-' }}</template>
      </el-table-column>
      <el-table-column label="运行状态" width="96" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="runTag(row.status)">{{ runStatusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="缺陷/未知/待期" width="118" align="center">
        <template #default="{ row }">{{ row.summary.fail_count }} / {{ row.summary.unknown_count }} / {{ row.summary.pending_count }}</template>
      </el-table-column>
      <el-table-column label="未解决/整改中" width="100" align="center">
        <template #default="{ row }">{{ row.open_issues }} / {{ row.rectifying_issues }}</template>
      </el-table-column>
      <el-table-column label="操作" width="86" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row as WorkbenchCheck)">详情</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty v-if="!listError" description="当前范围内没有核查记录" :image-size="60" />
      </template>
    </el-table>

    <div class="pager-row">
      <span class="range-hint">{{ rangeText }}</span>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100, 300]" layout="total, sizes, prev, pager, next"
        size="small" @current-change="loadChecks" @size-change="onSizeChange"
      />
    </div>

    <el-dialog v-model="trialVisible" title="试运行观察（隔离执行：不影响正式结果/推送）" width="min(94vw, 880px)">
      <el-alert v-if="trialsError" :title="trialsError" type="error" :closable="false" show-icon style="margin-bottom: 8px">
        <el-button size="small" type="primary" plain @click="loadTrials">重试加载</el-button>
      </el-alert>
      <el-table v-loading="trialsLoading" :data="trials" stripe border size="small" max-height="220" style="cursor: pointer">
        <el-table-column label="试运行ID" min-width="200" show-overflow-tooltip>
          <template #default="{ row }"><el-link @click="openTrialObs(row as { run_id: string })">{{ row.run_id }}</el-link></template>
        </el-table-column>
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }"><el-tag size="small" type="info">{{ runStatusText(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column prop="requested_by" label="发起人" width="110" />
        <el-table-column prop="created_at" label="创建时间" width="150" />
        <template #empty>
          <el-empty v-if="!trialsError" description="暂无试运行记录" :image-size="60" />
        </template>
      </el-table>
      <template v-if="trialObs">
        <el-alert
          :title="`执行量 ${trialObs.totals.executions}｜已复核 ${trialObs.totals.reviewed}｜确认缺陷 ${trialObs.totals.confirmed_defect}｜误报 ${trialObs.totals.false_positive}`"
          type="info" :closable="false" style="margin: 10px 0"
        />
        <el-table v-loading="trialObsLoading" :data="trialObs.rules" stripe border size="small" max-height="240">
          <el-table-column prop="rule_id" label="规则" min-width="180" show-overflow-tooltip />
          <el-table-column label="FID" width="60" align="center"><template #default="{ row }">{{ row.fid || '-' }}</template></el-table-column>
          <el-table-column prop="executions" label="执行" width="60" align="center" />
          <el-table-column prop="hits" label="命中" width="60" align="center" />
          <el-table-column prop="unknown" label="未知" width="60" align="center" />
          <el-table-column prop="confirmed_defect" label="确认缺陷" width="80" align="center" />
          <el-table-column prop="false_positive" label="误报" width="60" align="center" />
        </el-table>
      </template>
      <el-alert v-if="trialObsError" :title="trialObsError" type="error" :closable="false" show-icon style="margin-top: 8px" />
    </el-dialog>

    <el-drawer
      v-model="detailVisible" size="min(100vw, 780px)"
      :title="detail ? `核查详情：${detail.patient_id}/${detail.visit_number}` : '核查详情'"
    >
      <el-alert
        v-if="detailError" :title="detailError" type="error" :closable="false"
        show-icon style="margin-bottom: 8px"
      >
        <el-button v-if="detail" size="small" type="primary" plain @click="reloadDetail">重试加载</el-button>
      </el-alert>
      <div v-loading="detailLoading">
        <template v-if="detail">
          <el-descriptions :column="2" size="small" border style="margin-bottom: 10px">
            <el-descriptions-item label="检查时间">{{ detail.checked_at }}</el-descriptions-item>
            <el-descriptions-item label="数据时点">{{ detail.data_snapshot_at }}</el-descriptions-item>
            <el-descriptions-item label="规则集">{{ detail.ruleset_revision }}</el-descriptions-item>
            <el-descriptions-item label="汇总">
              {{ runStatusText(detail.summary?.status || detail.status) }}
              （缺陷 {{ detail.summary?.fail_count }} / 无法判定 {{ detail.summary?.unknown_count }}）
            </el-descriptions-item>
          </el-descriptions>
          <el-table :data="detail.clauses" stripe border size="small" max-height="480">
            <el-table-column label="FID" width="60" align="center"><template #default="{ row }">{{ row.fid ?? '-' }}</template></el-table-column>
            <el-table-column prop="rule_id" label="规则/条款" min-width="170" show-overflow-tooltip />
            <el-table-column prop="event_instance_id" label="事件" width="100" show-overflow-tooltip />
            <el-table-column label="引擎结论" width="96" align="center">
              <template #default="{ row }"><el-tag size="small" :type="evalTag(row.status)">{{ evalStatusText(row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="判定依据" width="150" show-overflow-tooltip>
              <template #default="{ row }">
                <el-tooltip :content="`技术码：${row.reason_code || '-'}`" placement="top" :disabled="!row.reason_code">
                  <span>{{ reasonText(row.reason_code) }}</span>
                </el-tooltip>
              </template>
            </el-table-column>
            <el-table-column label="人工状态/操作" min-width="230">
              <template #default="{ row }">
                <template v-if="row.issue">
                  <el-tag size="small" :type="issueTag(row.issue.status)" style="margin-right: 4px">{{ issueStatusText(row.issue.status) }}</el-tag>
                  <el-button
                    v-if="canFeedback && row.issue.status === 'open'" size="small"
                    :loading="actingIssueId === row.issue.issue_id" @click="act(row.issue, 'viewed')"
                  >已查看</el-button>
                  <el-button
                    v-if="canFeedback && ['open', 'viewed'].includes(row.issue.status)" size="small" type="warning"
                    :loading="actingIssueId === row.issue.issue_id" @click="act(row.issue, 'rectified')"
                  >提交整改</el-button>
                  <el-button
                    v-if="canReview && row.issue.status === 'rectifying'" size="small" type="success"
                    :loading="actingIssueId === row.issue.issue_id" @click="act(row.issue, 'recheck_passed', true)"
                  >复检通过</el-button>
                  <el-button
                    v-if="canReview && ['open', 'viewed'].includes(row.issue.status)" size="small" type="danger" plain
                    :loading="actingIssueId === row.issue.issue_id" @click="act(row.issue, 'false_positive', true)"
                  >误报</el-button>
                </template>
                <span v-else style="color: var(--el-text-color-secondary)">—</span>
              </template>
            </el-table-column>
          </el-table>
        </template>
        <el-empty v-else-if="!detailLoading && !detailError" description="未选择核查记录" :image-size="60" />
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// 046 T5 核查工作台（ui-next）；048 T3 重构：
// - 工具栏移出错误分支（失败可重试）；列表/详情/trial 列表/trial 观察独立 loading/error；
// - 分页（page/page_size，筛选变化回第一页）；旧请求晚返回不覆盖新状态（序号守卫）；
// - 权限驱动按钮（/users/me permissions；后端 403 仍是最终门）；五态/人工状态中文。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import {
  wbChecksApi,
  wbCheckDetailApi,
  wbIssueActionApi,
  prcTrialRunsApi,
  prcTrialObservationsApi,
} from '@/api/endpoints/prearchiveAdmin'
import { prcDisabledReasonFromError } from '@/utils/prc-degradation'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const loading = ref(false)
const listError = ref('')
const checks = ref<WorkbenchCheck[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const filterPatient = ref('')
const filterDept = ref('')
let listSeq = 0

const detailVisible = ref(false)
const detail = ref<CheckDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
let detailSeq = 0

const trialVisible = ref(false)
const trials = ref<Array<{ run_id: string; status: string; requested_by: string; created_at?: string }>>([])
const trialsLoading = ref(false)
const trialsError = ref('')
let trialsSeq = 0
const trialObs = ref<{ totals: Record<string, number>; rules: Array<Record<string, unknown>> } | null>(null)
const trialObsLoading = ref(false)
const trialObsError = ref('')

const actingIssueId = ref('')

// 权限：优先 /users/me 下发的 permissions；缺失时回退角色名近似（后端 403 兜底）。
// 终态复核动作需要 prearchive_issue_review；查看/整改反馈需要 prearchive_issue_feedback。
function hasPerm(p: string): boolean | undefined {
  const perms = auth.user?.permissions
  if (Array.isArray(perms)) return perms.includes(p)
  return undefined
}
const canReview = computed(() => hasPerm('prearchive_issue_review') ?? ['admin', 'auditor'].includes(auth.roleName))
const canFeedback = computed(() => hasPerm('prearchive_issue_feedback') ?? ['admin', 'clinician', 'dept_manager'].includes(auth.roleName))

interface WorkbenchCheck {
  run_id: string
  patient_id: string
  visit_number: string
  dept_name: string
  checked_at?: string | null
  origin: string
  status: string
  summary: { fail_count: number; unknown_count: number; pending_count: number; status?: string }
  open_issues: number
  rectifying_issues: number
}
interface CheckIssue {
  issue_id: string
  status: string
  version: number
}
interface CheckDetail extends WorkbenchCheck {
  data_snapshot_at?: string | null
  ruleset_revision: string
  clauses: Array<{
    fid: number | null
    rule_id: string
    event_instance_id: string
    status: string
    reason_code: string
    issue: CheckIssue | null
  }>
}

const rangeText = computed(() => {
  if (!total.value) return '共 0 条'
  const start = (page.value - 1) * pageSize.value + 1
  const end = Math.min(page.value * pageSize.value, total.value)
  return `第 ${start}-${end} 条 / 共 ${total.value} 条`
})

async function loadChecks() {
  const seq = ++listSeq
  loading.value = true
  try {
    const data = await wbChecksApi({
      patient_id: filterPatient.value || undefined,
      dept_code: canReview.value && filterDept.value ? filterDept.value : undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    if (seq !== listSeq) return   // 旧请求晚到：丢弃
    checks.value = data.items || []
    total.value = data.total || 0
    listError.value = ''
  } catch (e) {
    if (seq !== listSeq) return
    listError.value = prcDisabledReasonFromError(e, '核查工作台不可用')
  } finally {
    if (seq === listSeq) loading.value = false
  }
}

function resetAndLoad() {
  page.value = 1
  loadChecks()
}

function onSizeChange() {
  page.value = 1
  loadChecks()
}

async function openDetail(row: WorkbenchCheck) {
  detailSeq++
  detailVisible.value = true
  await fetchDetail(row.run_id)
}

async function reloadDetail() {
  if (detail.value) await fetchDetail(detail.value.run_id)
}

async function fetchDetail(runId: string) {
  const seq = ++detailSeq
  detailLoading.value = true
  detailError.value = ''
  try {
    const data = await wbCheckDetailApi(runId) as unknown as CheckDetail
    if (seq !== detailSeq) return
    detail.value = data
  } catch (e) {
    if (seq !== detailSeq) return
    // 失败不残留上一患者内容
    detail.value = null
    detailError.value = prcDisabledReasonFromError(e, '核查详情加载失败')
  } finally {
    if (seq === detailSeq) detailLoading.value = false
  }
}

function apiStatus(e: unknown): number {
  return (e as { status?: number })?.status ?? 0
}

async function act(issue: CheckIssue, action: string, requireReason = false) {
  if (actingIssueId.value) return   // 防重复提交
  let reason = ''
  if (requireReason) {
    try {
      const result = await ElMessageBox.prompt('原因（必填，落审计）', '人工处理', {
        inputPlaceholder: '请填写原因',
      })
      reason = result.value || ''
    } catch { return }
    if (!reason.trim()) {
      ElMessage.error('该操作原因必填')
      return
    }
  }
  actingIssueId.value = issue.issue_id
  try {
    await wbIssueActionApi(issue.issue_id, {
      action, reason, expect_issue_version: issue.version,
    })
    ElMessage.success('已记录（人工状态与引擎结论分开留痕）')
    // 刷新详情与列表（版本号已变化）
    if (detail.value) await fetchDetail(detail.value.run_id)
    await loadChecks()
  } catch (e) {
    const status = apiStatus(e)
    if (status === 409) {
      ElMessage.warning('该缺陷已被他人处理，已为你刷新最新状态')
      if (detail.value) await fetchDetail(detail.value.run_id)
      await loadChecks()
    } else if (status === 403) {
      ElMessage.error('无权限执行该操作（终态复核需质控复核权限）')
    } else if (status === 502 || status === 503) {
      ElMessage.error('核查服务暂不可用，请稍后重试')
    } else {
      ElMessage.error(`操作失败：${(e as Error)?.message || '请重试'}`)
    }
  } finally {
    actingIssueId.value = ''
  }
}

async function loadTrials() {
  const seq = ++trialsSeq
  trialsLoading.value = true
  trialsError.value = ''
  trialObs.value = null
  try {
    const data = await prcTrialRunsApi()
    if (seq !== trialsSeq) return
    trials.value = (data.items || []) as typeof trials.value
    trialVisible.value = true
  } catch (e) {
    if (seq !== trialsSeq) return
    trialsError.value = prcDisabledReasonFromError(e, '试运行列表加载失败')
    trialVisible.value = true
  } finally {
    if (seq === trialsSeq) trialsLoading.value = false
  }
}

async function openTrialObs(row: { run_id: string }) {
  trialObsLoading.value = true
  trialObsError.value = ''
  try {
    trialObs.value = await prcTrialObservationsApi(row.run_id)
  } catch (e) {
    trialObs.value = null   // 失败不残留上一 trial 内容
    trialObsError.value = prcDisabledReasonFromError(e, '观察数据加载失败')
  } finally {
    trialObsLoading.value = false
  }
}

type TagKind = 'success' | 'warning' | 'danger' | 'info'

// ---- 中文状态映射（未知枚举安全回退：显示原码） ----
const RUN_STATUS: Record<string, string> = {
  requested: '已受理', queued: '排队中', running: '执行中',
  completed: '已完成', partial: '部分完成', failed: '失败',
}
const EVAL_STATUS: Record<string, string> = {
  pass: '通过', fail: '缺陷', unknown: '无法判定',
  pending: '待到期复查', not_applicable: '不适用',
}
const ISSUE_STATUS: Record<string, string> = {
  open: '待处理', viewed: '已查看', rectifying: '整改中',
  resolved: '复检通过', false_positive: '误报', manual_closed: '人工关闭',
}
const REASONS: Record<string, string> = {
  within_limit: '时限内', required_doc_missing: '缺少必需文书',
  no_eval_record: '无评估记录', trigger_not_met: '触发条件未满足',
  trigger_not_met_source_error: '触发源查询异常', trigger_kind_unknown: '触发类型未知',
  source_not_ready: '数据源未就绪', missing_doc_source_error: '文书源查询异常',
  event_time_unknown: '事件时间未知', within_time_window: '时限窗口内（待复查）',
  all_docs_present: '文书齐全', doc_not_found: '未找到文书',
  doc_not_found_source_error: '文书源查询异常', doc_time_unknown: '文书时间未知',
  firstpage_source_unavailable: '首页数据源不可用', all_fields_filled: '首页字段齐全',
  no_duplicate: '无重复', evaluator_error: '评估器异常',
}
function runStatusText(status?: string): string {
  return (status && RUN_STATUS[status]) || status || '-'
}
function evalStatusText(status: string): string {
  return EVAL_STATUS[status] || status
}
function issueStatusText(status: string): string {
  return ISSUE_STATUS[status] || status
}
function reasonText(code?: string): string {
  if (!code) return '-'
  return REASONS[code] || code
}
function evalTag(status: string): TagKind {
  return ({ pass: 'success', fail: 'danger', unknown: 'warning', pending: 'info', not_applicable: 'info' } as Record<string, TagKind>)[status] || 'info'
}
function issueTag(status: string): TagKind {
  return ({ open: 'danger', viewed: 'warning', rectifying: 'warning', resolved: 'success', false_positive: 'info', manual_closed: 'info' } as Record<string, TagKind>)[status] || 'info'
}
function runTag(status?: string): TagKind {
  return ({ completed: 'success', partial: 'warning', failed: 'danger' } as Record<string, TagKind>)[status || ''] || 'info'
}

onMounted(loadChecks)
</script>

<style scoped>
.toolbar { display: flex; gap: 8px; margin-bottom: 10px; align-items: center; flex-wrap: wrap; }
.page-wrap { padding: 0 4px; }
.pager-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.range-hint { color: var(--el-text-color-secondary); font-size: 12px; }
@media (max-width: 480px) {
  .toolbar .el-input { width: 100% !important; }
}
</style>
