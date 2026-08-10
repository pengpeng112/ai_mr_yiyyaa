<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiDownload, apiGet, apiPost, triggerBrowserDownload } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage } from 'element-plus'

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
const detailIndex = ref(-1)
const detailSection = ref('overview')
const otherReasonVisible = ref(false)
const otherReasonText = ref('')
const otherReasonLogId = ref(0)
const actionLoading = ref<Record<number, boolean>>({})

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
            push_log_id: log.id,
            dimension_name: dim.dimension || dim.dimension_name || dim.dimension_code,
            dimension_code: dim.dimension_code,
            audit_type_name: g.audit_type_name,
            severity: dim.severity || log.severity || g.severity,
            status: st,
            issue_summary: dim.issue_summary,
            recommendation: dim.recommendation,
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

function riskLevel(): string {
  if (!detail.value) return ''
  const s = detail.value.summary
  if (Number(s.high_count) > 0) return 'high'
  if (Number(s.medium_count) > 0) return 'medium'
  if (Number(s.issue_count) > 0) return 'low'
  return ''
}

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
  void load()
}

function onSearch() { page.value = 1; void load() }

async function openDetail(row: PatientRow) {
  detailIndex.value = items.value.findIndex(
    (r) => r.patient_id === row.patient_id && r.visit_number === row.visit_number)
  await fetchDetail(row.patient_id, row.visit_number, row.dept)
}

async function fetchDetail(patientId: string, visitNumber: string, dept: string) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  detailSection.value = 'overview'
  try {
    detail.value = (await apiGet<DetailData>('/patient-qc/patient-detail', {
      params: { patient_id: patientId, visit_number: visitNumber, dept },
    })) as DetailData
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
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
  otherReasonLogId.value = pushLogId
  otherReasonText.value = ''
  otherReasonVisible.value = true
}

async function submitOtherReason() {
  if (!otherReasonText.value.trim()) {
    ElMessage.warning('请填写原因')
    return
  }
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
  }
}

async function copyPatientId(pid: string) {
  if (!pid) return
  try { await navigator.clipboard.writeText(pid); ElMessage.success('已复制患者ID') }
  catch { ElMessage.warning('复制失败') }
}

async function exportXlsx() {
  try {
    const { blob, filename } = await apiDownload('/patient-qc/export/patient-visit-summary')
    triggerBrowserDownload(blob, filename)
    ElMessage.success('导出已开始')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '导出失败'))
  }
}

onMounted(() => {
  void load()
  void loadDeptOptions()
})
</script>

<template>
  <div class="page-pq">
    <PageHeader title="患者质控" description="按患者维度查看质控结果、维度详情和整改闭环。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="exportXlsx">导出汇总</el-button>
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

    <el-table v-loading="loading" :data="items" stripe border size="small" style="width: 100%" @row-click="openDetail">
      <el-table-column label="患者姓名" width="105" fixed>
        <template #default="{ row }">
          <div><b>{{ row.patient_name }}</b></div>
          <div class="cell-sub">{{ row.patient_id }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="visit_number" label="住院次" width="70" />
      <el-table-column prop="admission_no" label="住院号" width="110" show-overflow-tooltip />
      <el-table-column prop="dept" label="在院科室" width="110" show-overflow-tooltip />
      <el-table-column prop="discharge_dept_name" label="出院科室" width="110" show-overflow-tooltip />
      <el-table-column label="最高严重度" width="95">
        <template #default="{ row }"><RiskTag :value="row.highest_severity" /></template>
      </el-table-column>
      <el-table-column label="高危" width="60">
        <template #default="{ row }"><span :class="{ 'count-danger': row.high_count > 0 }">{{ row.high_count }}</span></template>
      </el-table-column>
      <el-table-column prop="medium_count" label="中危" width="60" />
      <el-table-column label="问题数" width="65">
        <template #default="{ row }"><b>{{ row.issue_count }}</b></template>
      </el-table-column>
      <el-table-column prop="pending_count" label="待处理" width="70" />
      <el-table-column prop="resolved_count" label="已闭环" width="70" />
      <el-table-column prop="audit_type_count" label="类型数" width="70" />
      <el-table-column prop="push_log_count" label="推送次" width="70" />
      <el-table-column label="最近推送" width="145">
        <template #default="{ row }">{{ formatDateTime(row.latest_push_time) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="80" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click.stop="openDetail(row as PatientRow)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :page-sizes="[20, 50, 100]" :total="total" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="() => { page = 1; load() }" />
    </div>

    <DetailDrawer v-model="detailVisible" title="患者质控详情" :loading="detailLoading" size="80%">
      <template #actions>
        <el-button v-if="hasPrev" link @click="prevDetail">上一条</el-button>
        <span v-if="detailIndex >= 0" class="nav-pos">{{ detailIndex + 1 }} / {{ items.length }}</span>
        <el-button v-if="hasNext" link @click="nextDetail">下一条</el-button>
      </template>

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
          <el-card v-if="pendingIssues.length" class="mt" shadow="never">
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
        </div>

        <div v-show="detailSection === 'dimensions'">
          <div v-if="!issueList.length" class="empty-text">暂无问题维度</div>
          <div v-for="(issue, i) in issueList" :key="i" class="dim-card">
            <div class="dim-head">
              <span class="dim-name">{{ issue.dimension_name }}</span>
              <el-tag size="small" :type="String(issue.status) === 'fail' ? 'danger' : 'warning'">{{ issue.status }}</el-tag>
              <RiskTag :value="String(issue.severity || '')" />
              <el-tag size="small" type="info">{{ issue.audit_type_name }}</el-tag>
            </div>
            <div v-if="issue.issue_summary" class="dim-issue">{{ issue.issue_summary }}</div>
            <div v-if="issue.recommendation" class="dim-rec">建议：{{ issue.recommendation }}</div>
          </div>
        </div>

        <div v-show="detailSection === 'logs'">
          <el-collapse :model-value="detail.audit_groups.map((_, i) => i)">
            <el-collapse-item v-for="(g, gi) in detail.audit_groups" :key="gi" :name="gi">
              <template #title>
                <div class="group-title">
                  <el-tag size="small" type="info">{{ g.audit_type_name }}</el-tag>
                  <RiskTag :value="String(g.severity || '')" />
                  <span>{{ (g.logs as unknown[])?.length }} 次推送</span>
                </div>
              </template>
              <div v-for="log in (g.logs as Array<Record<string, unknown>>)" :key="String(log.id)" class="log-card">
                <div class="log-head">
                  <span>{{ formatDateTime(log.push_time as string) }}</span>
                  <RiskTag :value="String(log.severity || '')" />
                  <StatusTag :value="String(log.status || '')" />
                  <span v-if="log.feedback_status" class="cell-sub">反馈：{{ log.feedback_status }}</span>
                </div>
                <div v-if="log.overall_conclusion" class="log-conclusion">{{ log.overall_conclusion }}</div>
                <div v-for="(dim, di) in ((log.dimensions as Array<Record<string, unknown>>) || [])" :key="di" class="dim-mini">
                  <span class="dim-mini-name">{{ dim.dimension || dim.dimension_name }}</span>
                  <el-tag size="small" :type="String(dim.status) === 'fail' ? 'danger' : 'warning'">{{ dim.status }}</el-tag>
                  <span v-if="dim.issue_summary" class="dim-mini-text">{{ dim.issue_summary }}</span>
                </div>
                <div v-if="log.feedback_status !== 'rectified' && log.feedback_status !== 'closed'" class="log-actions">
                  <el-button size="small" type="success" :loading="actionLoading[log.id as number]" @click="quickAction(log.id as number, 'rectified')">已整改</el-button>
                  <el-button size="small" :loading="actionLoading[log.id as number]" @click="quickAction(log.id as number, 'pending')">标记未处理</el-button>
                  <el-button size="small" @click="openOtherReason(log.id as number)">其他原因</el-button>
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
            <el-descriptions-item label="出院科室">{{ displayText(detail.patient.discharge_dept_name) }}</el-descriptions-item>
            <el-descriptions-item label="入院日期">{{ displayText(detail.patient.admission_date) }}</el-descriptions-item>
            <el-descriptions-item label="出院日期">{{ displayText(detail.patient.discharge_date) }}</el-descriptions-item>
            <el-descriptions-item label="入院诊断" :span="2">{{ displayText(detail.patient.admission_diagnosis) }}</el-descriptions-item>
            <el-descriptions-item label="出院主诊断" :span="2">{{ displayText(detail.patient.discharge_diagnosis) }}</el-descriptions-item>
          </el-descriptions>
          <div class="mt">
            <el-button size="small" @click="copyPatientId(String(detail.patient.patient_id))">复制患者ID</el-button>
          </div>
        </div>
      </template>
    </DetailDrawer>

    <el-dialog v-model="otherReasonVisible" title="其他原因" width="400px">
      <el-input v-model="otherReasonText" type="textarea" :rows="3" placeholder="请填写原因（必填）" />
      <template #footer>
        <el-button @click="otherReasonVisible = false">取消</el-button>
        <el-button type="primary" @click="submitOtherReason">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
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
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.pq-header { margin-bottom: 16px; }
.pq-title { display: flex; align-items: center; gap: 8px; }
.pq-title h3 { margin: 0; font-size: 18px; }
.pq-meta { font-size: 13px; color: var(--el-text-color-secondary); margin-top: 4px; }
.pq-counts { display: flex; gap: 16px; margin-top: 8px; font-size: 13px; }
.pq-counts b { margin-left: 4px; }
.pq-nav { display: flex; gap: 4px; margin-bottom: 16px; border-bottom: 1px solid var(--el-border-color); padding-bottom: 8px; }
.nav-pos { font-size: 12px; color: var(--el-text-color-secondary); margin: 0 8px; }
.metric-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.metric-card { padding: 12px; border: 1px solid var(--el-border-color); border-radius: 8px; text-align: center; }
.metric-card span { display: block; font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.metric-card b { font-size: 22px; }
.issue-item { padding: 8px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.issue-head { display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }
.issue-dim { font-weight: 600; font-size: 13px; }
.issue-text { font-size: 12px; color: var(--el-text-color-secondary); }
.empty-text { text-align: center; padding: 30px; color: var(--el-text-color-disabled); }
.dim-card { padding: 10px 0; border-bottom: 1px solid var(--el-border-color-lighter); }
.dim-head { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.dim-name { font-weight: 600; }
.dim-issue { font-size: 13px; margin-bottom: 4px; }
.dim-rec { font-size: 12px; color: var(--el-text-color-secondary); }
.group-title { display: flex; align-items: center; gap: 8px; }
.log-card { padding: 10px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; margin-bottom: 8px; }
.log-head { display: flex; align-items: center; gap: 8px; font-size: 12px; margin-bottom: 6px; }
.log-conclusion { font-size: 13px; margin-bottom: 6px; }
.dim-mini { font-size: 12px; margin: 4px 0; display: flex; align-items: center; gap: 6px; }
.dim-mini-name { font-weight: 500; }
.dim-mini-text { color: var(--el-text-color-secondary); }
.log-actions { margin-top: 8px; display: flex; gap: 6px; }
.mt { margin-top: 12px; }
</style>
