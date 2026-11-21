<template>
  <div class="page-wrap">
    <PageHeader
      title="归档前形式核查"
      description="出院病历归档前自动检查缺失文书、签名与形式规范，辅助病案室质控。"
    >
      <template #actions>
        <el-button size="small" :loading="loading" @click="loadChecks">刷新</el-button>
        <el-button size="small" :loading="trialsLoading" @click="loadTrials">试运行观察</el-button>
      </template>
    </PageHeader>

    <!-- WP07 模式横幅：影子模式状态一目了然 -->
    <el-alert
      v-if="listError || (!loading && !checks.length)"
      type="warning"
      :closable="false"
      show-icon
      class="mode-banner"
      title="归档前检查引擎尚未接入数据（影子模式待启用，详见 123 操作手册）。启用后这里会自动列出每日出院病历的检查结果。"
    />
    <el-alert
      v-else
      type="info"
      :closable="false"
      show-icon
      class="mode-banner"
      title="当前为影子辅助模式：结果仅供病案室在本系统内核对，不会推送给临床或无纸化系统。"
    />

    <!-- 054 U2：权限信息未就绪时写动作 fail-closed，可重试（不清会话） -->
    <el-alert
      v-if="permsState === 'unavailable'" type="warning" :closable="false"
      title="用户权限信息未加载，写操作暂不可用" show-icon style="margin-bottom: 10px"
    >
      <el-button size="small" type="primary" plain :loading="refreshingPerms" @click="retryLoadPerms">
        重新加载权限
      </el-button>
    </el-alert>

    <!-- WP07 SummaryStrip 五卡（按当前筛选结果在前端计算） -->
    <SummaryStrip :items="summaryCards" :loading="loading" />

    <FilterPanel title="筛选条件" :collapsible="true" @search="resetAndLoad" @reset="resetFilters">
      <div class="wb-filter-row">
        <label class="wb-filter-item">
          出院日期范围
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            size="small"
            style="width: 240px"
            @change="resetAndLoad"
          />
        </label>
        <label class="wb-filter-item">
          出院科室
          <el-select
            v-if="canReview"
            v-model="filterDept"
            filterable
            clearable
            placeholder="全部授权科室"
            size="small"
            style="width: 180px"
            @change="resetAndLoad"
          >
            <el-option label="全部授权科室" value="" />
            <el-option v-for="d in deptOptions" :key="d" :label="d" :value="d" />
          </el-select>
          <el-input v-else :model-value="filterDept || '按授权范围'" disabled size="small" style="width: 180px" />
        </label>
        <label class="wb-filter-item">
          复核状态
          <el-select v-model="filterIssueStatus" clearable placeholder="全部" size="small" style="width: 130px" @change="resetAndLoad">
            <el-option label="待确认" value="open" />
            <el-option label="已确认（已查看）" value="viewed" />
            <el-option label="整改中" value="rectifying" />
            <el-option label="复检通过" value="resolved" />
            <el-option label="误报" value="false_positive" />
          </el-select>
        </label>
        <label class="wb-filter-item">
          患者姓名或住院号
          <el-input
            v-model="filterPatient"
            placeholder="患者号 / 住院号（回车查询）"
            size="small"
            clearable
            style="width: 200px"
            @keyup.enter="resetAndLoad"
            @clear="resetAndLoad"
          />
        </label>
      </div>
      <template #more>
        <div class="wb-filter-row">
          <label class="wb-filter-item">
            规则分类
            <el-select v-model="filterRuleCategory" clearable placeholder="全部（明细级筛选随影子数据完善）" size="small" style="width: 240px" @change="resetAndLoad">
              <el-option label="缺失类文书" value="missing" />
              <el-option label="时限类" value="time" />
              <el-option label="一致性质疑" value="consistency" />
            </el-select>
          </label>
        </div>
      </template>
    </FilterPanel>

    <el-alert
      v-if="listError" :title="listError" type="error" :closable="false"
      show-icon style="margin-bottom: 10px"
    >
      <el-button size="small" type="primary" plain @click="loadChecks">重试加载</el-button>
    </el-alert>

    <DataTableShell
      :loading="loading"
      :error="''"
      :empty="!loading && !checks.length && !listError"
      empty-text="当前范围内没有核查记录"
      :total="total"
      :page="page"
      :page-size="pageSize"
      @update:page="onPageChange"
      @update:pageSize="onSizeChange"
      @retry="loadChecks"
    >
      <el-table
        :data="checks"
        stripe
        border
        size="small"
        :max-height="tableMaxHeight"
        @row-click="(row: WorkbenchCheck) => openDetail(row)"
      >
        <el-table-column label="患者信息" width="180" fixed="left">
          <template #default="{ row }">
            <div class="wb-cell-main">{{ row.patient_name || row.patient_id }}</div>
            <div class="cell-sub">患者号 {{ row.patient_id }} · 第{{ row.visit_number }}次</div>
          </template>
        </el-table-column>
        <el-table-column label="出院科室与日期" width="170" show-overflow-tooltip>
          <template #default="{ row }">
            <div>{{ row.dept_name || '—' }}</div>
            <div class="cell-sub">核查 {{ formatTime(row.checked_at) || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="检出缺陷" min-width="200">
          <template #default="{ row }">
            <template v-if="(row.summary?.fail_count ?? 0) > 0">
              <el-tag size="small" type="danger" effect="plain">缺陷 {{ row.summary.fail_count }}</el-tag>
              <el-tag v-if="(row.summary?.unknown_count ?? 0) > 0" size="small" type="warning" effect="plain">
                无法判定 {{ row.summary.unknown_count }}
              </el-tag>
              <el-tag v-if="(row.summary?.pending_count ?? 0) > 0" size="small" effect="plain" type="info">
                待期 {{ row.summary.pending_count }}
              </el-tag>
              <span class="cell-sub">详见核查处理</span>
            </template>
            <span v-else class="cell-sub">未检出缺陷</span>
          </template>
        </el-table-column>
        <el-table-column label="最高严重度" width="100" align="center">
          <template #default="{ row }">
            <RiskTag :value="rowSeverities(row as WorkbenchCheck)" />
          </template>
        </el-table-column>
        <el-table-column label="病案室复核状态" width="130" align="center">
          <template #default="{ row }">
            <el-tag size="small" :type="reviewTag(row as WorkbenchCheck)">{{ reviewText(row as WorkbenchCheck) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="无纸化推送" width="140" align="center">
          <template #default>
            <el-tag size="small" type="info" effect="plain">影子模式 · 未推送</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" plain @click.stop="openDetail(row as WorkbenchCheck)">核查处理</el-button>
            <HolographyButton :patient-id="(row as WorkbenchCheck).patient_id" link />
          </template>
        </el-table-column>
        <template #empty>
          <el-empty v-if="!listError" description="当前范围内没有核查记录" :image-size="60" />
        </template>
      </el-table>
    </DataTableShell>

    <!-- 试运行观察（保留既有隔离执行语义） -->
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
      <el-alert v-if="trialObsError" :title="trialObsError" type="error" :closable="false" style="margin-top: 8px" />
    </el-dialog>

    <!-- 核查处理抽屉（WP07：患者卡+360 主按钮+缺陷卡行内闭环+技术证据折叠） -->
    <DetailDrawer
      v-model="detailVisible"
      title="核查处理"
      size="780px"
      :loading="detailLoading"
    >
      <template #actions>
        <el-button v-if="detailError" link type="primary" @click="reloadDetail">重试加载</el-button>
      </template>
      <div v-loading="detailLoading">
        <template v-if="detail">
          <!-- 顶部患者卡 + 360 全息主按钮 -->
          <div class="patient-banner">
            <div class="banner-top">
              <div class="banner-identity">
                <span class="banner-name">{{ detail.patient_name || detail.patient_id }}</span>
                <span class="cell-sub">患者号 {{ detail.patient_id }} · 第{{ detail.visit_number }}次</span>
              </div>
              <HolographyButton :patient-id="detail.patient_id" size="default" label="打开 360 全息核对病历" />
            </div>
            <div class="banner-meta">
              科室 {{ detail.dept_name || '—' }} · 核查 {{ formatTime(detail.checked_at) || '—' }} ·
              数据时点 {{ formatTime(detail.data_snapshot_at) || '—' }} · 规则集 {{ detail.ruleset_revision || '—' }} ·
              <RiskTag :value="detailSeverities(detail)" />
            </div>
          </div>

          <!-- 每条缺陷一张卡：行内一键闭环 -->
          <div class="issue-cards">
            <p v-if="!detail.clauses.length" class="pane-empty">本次核查无条款结论</p>
            <div
              v-for="(row, index) in detail.clauses"
              :key="`${row.rule_id}-${index}`"
              class="issue-card"
              :class="{ 'is-issue': row.status === 'fail' }"
            >
              <div class="issue-head">
                <span class="issue-name">{{ row.rule_id }}</span>
                <span v-if="row.fid" class="cell-sub">无纸化扣分项 FID {{ row.fid }}</span>
                <el-tag size="small" :type="evalTag(row.status)">{{ evalStatusText(row.status) }}</el-tag>
                <span class="issue-spacer" />
              </div>
              <div class="issue-evidence">{{ reasonText(row.reason_code) }}<template v-if="row.event_instance_id">（触发事件 {{ row.event_instance_id }}）</template></div>
              <div v-if="row.issue" class="issue-footer">
                <el-tag size="small" :type="issueTag(row.issue.status)">{{ issueStatusText(row.issue.status) }}</el-tag>
                <template v-if="canFeedback && ['open', 'viewed'].includes(row.issue.status)">
                  <el-button size="small" type="primary" plain
                    :loading="actingIssueId === row.issue.issue_id"
                    @click="actWithNote(row.issue, 'viewed')">确认缺陷</el-button>
                  <el-button size="small" type="info" plain
                    :loading="actingIssueId === row.issue.issue_id"
                    @click="openFalsePositive(row.issue)">标为误报</el-button>
                  <el-button size="small" type="warning" plain
                    :loading="actingIssueId === row.issue.issue_id"
                    @click="actWithNote(row.issue, 'rectified')">已补齐</el-button>
                </template>
                <el-button
                  v-if="canReview && row.issue.status === 'rectifying'" size="small" type="success" plain
                  :loading="actingIssueId === row.issue.issue_id"
                  @click="actRecheck(row.issue)"
                >复检通过</el-button>
              </div>
              <div v-else class="issue-footer"><span class="cell-sub">—</span></div>
            </div>
          </div>

          <!-- 技术证据默认折叠 -->
          <el-collapse class="tech-collapse">
            <el-collapse-item name="tech">
              <template #title><span class="tech-title">技术证据（运行批次 / 原始结论 JSON）</span></template>
              <el-descriptions :column="2" border size="small" style="margin-bottom: 8px">
                <el-descriptions-item label="运行批次">{{ detail.run_id }}</el-descriptions-item>
                <el-descriptions-item label="来源">{{ detail.origin || '—' }}</el-descriptions-item>
                <el-descriptions-item label="运行状态">{{ runStatusText(detail.status) }}</el-descriptions-item>
                <el-descriptions-item label="汇总">
                  缺陷 {{ detail.summary?.fail_count ?? 0 }} / 无法判定 {{ detail.summary?.unknown_count ?? 0 }} / 待期 {{ detail.summary?.pending_count ?? 0 }}
                </el-descriptions-item>
              </el-descriptions>
              <pre class="raw-json">{{ JSON.stringify(detail.clauses, null, 2) }}</pre>
            </el-collapse-item>
          </el-collapse>
        </template>
        <el-empty v-else-if="!detailLoading && !detailError" description="未选择核查记录" :image-size="60" />
      </div>
    </DetailDrawer>

    <!-- 误报原因选择（任务书：必须选原因） -->
    <el-dialog v-model="fpVisible" title="标为误报（必须选择原因）" width="440px">
      <el-radio-group v-model="fpReason" class="fp-reasons">
        <el-radio value="文书其实存在">文书其实存在</el-radio>
        <el-radio value="规则不适用本科室">规则不适用本科室</el-radio>
        <el-radio value="时间判断错误">时间判断错误</el-radio>
        <el-radio value="其他">其他（请在备注补充说明）</el-radio>
      </el-radio-group>
      <el-input v-model="fpNote" type="textarea" :rows="3" placeholder="补充备注（选填，写入审计留痕）" style="margin-top: 10px" />
      <template #footer>
        <el-button @click="fpVisible = false">取消</el-button>
        <el-button type="primary" :loading="actingIssueId === fpTarget?.issue_id" @click="submitFalsePositive">提交误报</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// WP07 病案室辅助核查台（064 总计划，拍板 D3）：在 046 T5/048 T3 基础上重构布局——
// - 模式横幅（影子模式待启用 / 影子辅助模式）+ SummaryStrip 五卡（按当前页计算）；
// - FilterPanel（出院日期范围/出院科室/复核状态/患者筛选，#more 规则分类）；
// - 主表按患者聚合 + 检出缺陷胶囊 + 无纸化推送预留灰标 + HolographyButton；
// - 核查抽屉（780px）：患者卡+360 全息主按钮+缺陷卡行内闭环（确认缺陷/标为误报
//   [必选原因]/已补齐）+技术证据默认折叠；试运行观察与权限 fail-closed 原样保留。
// 全部取数与提交仍走既有 BFF（wbChecksApi/wbCheckDetailApi/wbIssueActionApi）。
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import HolographyButton from '@/components/base/HolographyButton.vue'
import {
  wbChecksApi,
  wbCheckDetailApi,
  wbIssueActionApi,
  prcTrialRunsApi,
  prcTrialObservationsApi,
} from '@/api/endpoints/prearchiveAdmin'
import { prcDisabledReasonFromError } from '@/utils/prc-degradation'
import { permsStateOf, canUsePerm } from '@/features/governance/workbenchPerms'
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
const dateRange = ref<[string, string] | null>(null)
const filterIssueStatus = ref('')
const filterRuleCategory = ref('')
const deptOptions = ref<string[]>([])
let listSeq = 0

const tableMaxHeight = 'calc(100vh - 380px)'

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
const fpVisible = ref(false)
const fpTarget = ref<CheckIssue | null>(null)
const fpReason = ref('')
const fpNote = ref('')

// 权限（054 U2 fail-closed）：permissions 数组就绪后按精确成员判定，不回退角色名近似；
// 终态复核动作需要 prearchive_issue_review；查看/整改反馈需要 prearchive_issue_feedback。
const permsState = computed(() => permsStateOf(auth.user, auth.isAuthenticated))
const refreshingPerms = ref(false)
async function retryLoadPerms() {
  refreshingPerms.value = true
  try {
    await auth.refreshUser()
  } finally {
    refreshingPerms.value = false
  }
}
const canReview = computed(() =>
  canUsePerm(auth.user, auth.isAuthenticated, 'prearchive_issue_review'))
const canFeedback = computed(() =>
  canUsePerm(auth.user, auth.isAuthenticated, 'prearchive_issue_feedback'))

interface WorkbenchCheck {
  run_id: string
  patient_id: string
  patient_name?: string
  visit_number: string
  dept_name: string
  checked_at?: string | null
  origin: string
  status: string
  summary: { fail_count: number; unknown_count: number; pending_count: number; status?: string }
  open_issues: number
  rectifying_issues: number
  issue_statuses?: string[]
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

/** SummaryStrip 五卡：接口无的指标按当前页计算并在 hint 标注。 */
const summaryCards = computed<SummaryItem[]>(() => {
  const rows = checks.value
  const checkedCount = rows.length
  const defectVisits = rows.filter((r) => (r.summary?.fail_count ?? 0) > 0).length
  const pendingConfirm = rows.reduce((sum, r) => sum + (r.open_issues || 0), 0)
  const rectifying = rows.reduce((sum, r) => sum + (r.rectifying_issues || 0), 0)
  return [
    { key: 'checked', label: '已检查病历', value: checkedCount, hint: '按当前页' },
    { key: 'defect', label: '检出缺陷病历', value: defectVisits, tone: 'danger', hint: '按当前页' },
    { key: 'pending', label: '待病案室确认', value: pendingConfirm, tone: 'warning', hint: '按当前页' },
    { key: 'rectifying', label: '整改中', value: rectifying, hint: '按当前页' },
    { key: 'fp_ratio', label: '误报占比', value: '—', hint: '需缺陷明细级统计，影子数据积累后开放' },
  ]
})

/** 行最高严重度：缺陷数>0 → high；未知>0 → medium；否则空。 */
function rowSeverities(row: WorkbenchCheck): string {
  if ((row.summary?.fail_count ?? 0) > 0) return 'high'
  if ((row.summary?.unknown_count ?? 0) > 0) return 'medium'
  return ''
}
function detailSeverities(detail: CheckDetail): string {
  if (detail.clauses.some((c) => c.status === 'fail')) return 'high'
  if (detail.clauses.some((c) => c.status === 'unknown')) return 'medium'
  return ''
}

/** 复核状态胶囊（行级 open/rectifying 派生；中文标签）。 */
function reviewText(row: WorkbenchCheck): string {
  if ((row.open_issues || 0) > 0) return '待确认'
  if ((row.rectifying_issues || 0) > 0) return '整改中'
  if ((row.summary?.fail_count ?? 0) === 0) return '无缺陷'
  return '已处理'
}
function reviewTag(row: WorkbenchCheck): 'warning' | 'primary' | 'success' | 'info' {
  if ((row.open_issues || 0) > 0) return 'warning'
  if ((row.rectifying_issues || 0) > 0) return 'primary'
  if ((row.summary?.fail_count ?? 0) === 0) return 'success'
  return 'info'
}

function formatTime(value?: string | null): string {
  return value ? String(value).replace('T', ' ').slice(0, 16) : ''
}

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
    // 科室下拉选项（从结果聚合一页范围值；filterable）
    const depts = new Set<string>()
    for (const row of checks.value) {
      if (row.dept_name) depts.add(row.dept_name)
    }
    if (depts.size && !deptOptions.value.length) deptOptions.value = Array.from(depts).sort()
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

function resetFilters(): void {
  filterPatient.value = ''
  filterDept.value = ''
  dateRange.value = null
  filterIssueStatus.value = ''
  filterRuleCategory.value = ''
  resetAndLoad()
}

function onPageChange(next: number): void {
  page.value = next
  loadChecks()
}

function onSizeChange(next: number): void {
  pageSize.value = next
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

/** 复检通过：原因必填（终态复核，落审计）。 */
async function actRecheck(issue: CheckIssue): Promise<void> {
  let reason = ''
  try {
    const result = await ElMessageBox.prompt('复检通过原因（必填，落审计）', '人工复核', {
      inputPlaceholder: '请填写原因',
    })
    reason = String((result as { value?: string }).value || '').trim()
  } catch { return }
  if (!reason) {
    ElMessage.error('该操作原因必填')
    return
  }
  await act(issue, 'recheck_passed', reason)
}

async function act(issue: CheckIssue, action: string, reason = '') {
  if (actingIssueId.value) return   // 防重复提交
  actingIssueId.value = issue.issue_id
  try {
    await wbIssueActionApi(issue.issue_id, {
      action, reason, expect_issue_version: issue.version,
    })
    ElMessage.success('已记录（人工状态与引擎结论分开留痕）')
    fpVisible.value = false
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

/** 确认缺陷 / 已补齐：备注选填（ElMessageBox 备注，提交审计）。 */
async function actWithNote(issue: CheckIssue, action: 'viewed' | 'rectified'): Promise<void> {
  const tip = action === 'viewed' ? '确认缺陷' : '登记已补齐'
  let note = ''
  try {
    const result = await ElMessageBox.prompt(
      `${tip}（备注选填，写入审计留痕）`, '病案室核查', {
        confirmButtonText: '确定', cancelButtonText: '取消',
        inputPlaceholder: '备注（选填）', type: 'warning',
      })
    note = String((result as { value?: string }).value || '').trim()
  } catch {
    return
  }
  await act(issue, action, note)
}

/** 标为误报：必须从四项原因中选一（任务书 §四.6）。 */
function openFalsePositive(issue: CheckIssue): void {
  fpTarget.value = issue
  fpReason.value = ''
  fpNote.value = ''
  fpVisible.value = true
}

async function submitFalsePositive(): Promise<void> {
  if (!fpTarget.value) return
  if (!fpReason.value) {
    ElMessage.warning('请选择误报原因（必填）')
    return
  }
  const reason = fpNote.value.trim()
    ? `[${fpReason.value}] ${fpNote.value.trim()}`
    : `[${fpReason.value}]`
  await act(fpTarget.value, 'false_positive', reason)
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

type TagKind = 'success' | 'warning' | 'danger' | 'info' | 'primary'

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
  open: '待处理', viewed: '已确认（已查看）', rectifying: '整改中',
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
  if (!code) return '—'
  return REASONS[code] || code
}
function evalTag(status: string): TagKind {
  return ({ pass: 'success', fail: 'danger', unknown: 'warning', pending: 'info', not_applicable: 'info' } as Record<string, TagKind>)[status] || 'info'
}
function issueTag(status: string): TagKind {
  return ({ open: 'danger', viewed: 'warning', rectifying: 'warning', resolved: 'success', false_positive: 'info', manual_closed: 'info' } as Record<string, TagKind>)[status] || 'info'
}

onMounted(loadChecks)
</script>

<style scoped>
.page-wrap { padding: 0 4px; }
.mode-banner { margin-bottom: 12px; }
.wb-filter-row { display: flex; gap: 14px; flex-wrap: wrap; align-items: center; }
.wb-filter-item {
  display: inline-flex; gap: 6px; align-items: center;
  font-size: 13px; color: var(--el-text-color-regular);
}
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.wb-cell-main { font-weight: 600; }

/* 患者横幅（与 PatientQcDetailView 同款视觉） */
.patient-banner {
  background: #f8fafc;
  border: 1px solid var(--el-border-color-lighter);
  border-left: 4px solid #0891b2;
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
}
.banner-top { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.banner-identity { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.banner-name { font-size: 18px; font-weight: 700; }
.banner-meta { margin-top: 6px; font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }

/* 缺陷卡 */
.issue-cards { display: grid; gap: 10px; margin-bottom: 12px; }
.issue-card {
  background: #fff; border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px; padding: 10px 12px;
}
.issue-card.is-issue { border-left: 3px solid #ef4444; }
.issue-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.issue-name { font-size: 14px; font-weight: 700; }
.issue-spacer { flex: 1; }
.issue-evidence { margin: 6px 0; font-size: 12px; line-height: 1.6; color: var(--el-text-color-regular); }
.issue-footer { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }

.tech-collapse { margin-top: 4px; }
.tech-title { font-size: 13px; font-weight: 600; }
.raw-json {
  margin: 0; max-height: 320px; overflow: auto; padding: 10px 12px; border-radius: 8px;
  background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
.pane-empty { color: var(--el-text-color-secondary); text-align: center; padding: 16px; font-size: 12px; }
.fp-reasons { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; }
@media (max-width: 640px) {
  .wb-filter-row { flex-direction: column; align-items: stretch; }
}
</style>
