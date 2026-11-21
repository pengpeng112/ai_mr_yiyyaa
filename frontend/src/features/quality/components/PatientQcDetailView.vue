<template>
  <div class="pq-detail-view" :class="{ 'in-drawer': inDrawer }">
    <ErrorState v-if="loadError && !loading" :message="loadError" @retry="load" />
    <div v-else v-loading="loading" class="pqdv-body">
      <template v-if="detail">
        <!-- ── 区块 1：吸顶患者临床摘要卡 ── -->
        <div class="patient-banner">
          <div class="banner-top">
            <div class="banner-identity">
              <span class="banner-name">{{ cs.patient_name || patientId }}</span>
              <span class="banner-grey">
                {{ cs.sex || '—' }}<template v-if="ageText"> · {{ ageText }}</template>
              </span>
              <RiskTag :value="riskLevel" />
            </div>
            <div class="banner-id" title="点击复制住院号/患者号" @click="copyIds">
              患者号 {{ cs.patient_id || patientId }}
              <template v-if="cs.admission_no"> · 住院号 {{ cs.admission_no }}</template>
              <el-icon class="banner-copy"><CopyDocument /></el-icon>
            </div>
            <div class="banner-actions no-print">
              <HolographyButton :patient-id="patientId" size="default" label="打开 360 全息视图" />
              <el-button v-if="inDrawer" size="default" @click="openStandalone">全屏查看</el-button>
              <el-button v-else size="default" class="print-btn" @click="printPage">打印质控单</el-button>
            </div>
          </div>
          <div class="banner-grid">
            <div class="banner-item"><span class="bi-label">所属科室</span><span class="bi-value">{{ cs.dept_name || '—' }}<template v-if="cs.discharge_dept_name && cs.discharge_dept_name !== cs.dept_name">（出院 {{ cs.discharge_dept_name }}）</template></span></div>
            <div class="banner-item"><span class="bi-label">管床医生</span><span class="bi-value">{{ cs.doctor_in_charge || '—' }}</span></div>
            <div class="banner-item"><span class="bi-label">入院日期</span><span class="bi-value">{{ formatDateTime(cs.admission_date) || '—' }}</span></div>
            <div class="banner-item"><span class="bi-label">出院日期</span><span class="bi-value">{{ formatDateTime(cs.discharge_date) || '在院' }}</span></div>
            <div class="banner-item banner-item--wide">
              <span class="bi-label">主要诊断</span>
              <span class="bi-value" :title="mainDiagnosis">{{ mainDiagnosis || '—' }}</span>
            </div>
            <div v-if="cs.surgery_name" class="banner-item banner-item--wide">
              <span class="bi-label">手术</span>
              <span class="bi-value">{{ cs.surgery_name }}<template v-if="cs.surgery_date">（{{ formatDateTime(cs.surgery_date) }}）</template></span>
            </div>
          </div>
        </div>

        <!-- ── 区块 2：总体质控结论与闭环进度 ── -->
        <div class="conclusion-block">
          <div class="conclusion-badges">
            <span class="cbadge cbadge-high">累计高危 <b>{{ summary.high_count ?? 0 }}</b> 项</span>
            <span class="cbadge cbadge-medium">累计中危 <b>{{ summary.medium_count ?? 0 }}</b> 项</span>
            <span class="cbadge cbadge-low">累计低危 <b>{{ summary.low_count ?? 0 }}</b> 项</span>
          </div>
          <p v-if="overallSummary" class="conclusion-text">{{ overallSummary }}</p>
          <p v-else class="conclusion-text conclusion-empty">本次住院暂无 AI 总体质控结论。</p>
        </div>

        <!-- ── 区块 3：缺陷问题可视化对照卡片 ── -->
        <div class="issues-block">
          <div class="issues-toolbar">
            <span class="issues-title">缺陷问题（{{ allIssues.length }}）</span>
            <el-radio-group v-model="issueMode" size="small">
              <el-radio-button value="focus">仅看高/中危</el-radio-button>
              <el-radio-button value="all">查看全部维度</el-radio-button>
            </el-radio-group>
          </div>
          <div v-if="!visibleIssues.length" class="issues-empty">该患者暂无{{ issueMode === 'focus' ? '高/中危' : '' }}问题维度</div>
          <div
            v-for="(issue, i) in visibleIssues"
            :key="`${issue.push_log_id}-${issue.dimension_code || issue.dimension_name}-${i}`"
            class="issue-card"
            :class="`issue-${String(issue.severity || 'low')}`"
          >
            <div class="issue-head">
              <RiskTag :value="String(issue.severity || '')" />
              <span class="issue-dim">{{ issue.dimension_name || issue.dimension_code || '质控维度' }}</span>
              <el-tag size="small" type="info" effect="plain">{{ issue.audit_type_name }}</el-tag>
              <span class="issue-spacer" />
              <span v-if="canQuickAction(issue.feedback_status)" class="issue-actions no-print">
                <el-button size="small" type="primary" plain :loading="issueBusy(issue.push_log_id)" @click.stop="confirmIssue(issue, 'acknowledged')">确认属实</el-button>
                <el-button size="small" type="success" plain :loading="issueBusy(issue.push_log_id)" @click.stop="confirmIssue(issue, 'rectified')">已整改</el-button>
                <el-button size="small" type="info" plain :loading="issueBusy(issue.push_log_id)" @click.stop="confirmIssue(issue, 'closed')">误报</el-button>
              </span>
            </div>
            <p class="issue-text">{{ issue.issue_summary || issue.explanation || '（无问题摘要）' }}</p>
            <!-- 左右双栏证据对比：单侧证据优雅展示为全宽引用盒，不出现空白半栏 -->
            <div
              v-if="hasEvidence(issue.medical_evidence) || hasEvidence(issue.nursing_evidence)"
              class="evidence-grid"
              :class="{ 'evidence-single': !hasEvidence(issue.medical_evidence) || !hasEvidence(issue.nursing_evidence) }"
            >
              <div v-if="hasEvidence(issue.medical_evidence)" class="ev-box ev-medical">
                <div class="ev-title">病历 / 医嘱摘录</div>
                <pre class="ev-text">{{ formatEvidence(issue.medical_evidence) }}</pre>
              </div>
              <div v-if="hasEvidence(issue.nursing_evidence)" class="ev-box ev-nursing">
                <div class="ev-title">佐证材料（护理 / 检验 / 手术）</div>
                <pre class="ev-text">{{ formatEvidence(issue.nursing_evidence) }}</pre>
              </div>
            </div>
            <div v-if="issue.recommendation" class="issue-advice">整改建议：{{ issue.recommendation }}</div>
          </div>
        </div>

        <!-- ── 区块 4：历次核查 / 企微推送 / 技术报文 ── -->
        <el-tabs v-model="activeTab" class="history-tabs">
          <el-tab-pane label="历次核查历史" name="history">
            <el-timeline v-if="historyItems.length">
              <el-timeline-item
                v-for="(h, i) in historyItems"
                :key="`${h.push_log_id}-${i}`"
                :timestamp="formatDateTime(h.push_time)"
                :type="h.success ? 'success' : 'danger'"
                placement="top"
              >
                <div class="tl-card">
                  <div class="tl-head">
                    <span class="tl-type">{{ h.audit_type_name }}</span>
                    <StatusTag :value="h.status" />
                    <RiskTag :value="String(h.severity || '')" />
                    <span class="tl-spacer" />
                    <el-button v-if="h.push_log_id" size="small" link type="primary" class="no-print" @click="retryOne(h.push_log_id)">单条重推</el-button>
                  </div>
                  <div v-if="h.overall_conclusion" class="tl-conclusion">{{ h.overall_conclusion }}</div>
                  <div v-if="h.feedback_text" class="tl-feedback">医生反馈：{{ h.feedback_text }}</div>
                </div>
              </el-timeline-item>
            </el-timeline>
            <div v-else class="pane-empty">暂无核查历史</div>
          </el-tab-pane>

          <el-tab-pane label="企微推送与医生反馈" name="relay">
            <template v-if="relayItems.length">
              <div v-for="(r, i) in relayItems" :key="`${r.id}-${i}`" class="relay-card">
                <div class="relay-head">
                  <span class="relay-time">{{ formatDateTime(r.created_at) }}</span>
                  <StatusTag :value="String(r.status || '')" />
                  <RiskTag :value="String(r.severity || '')" />
                  <span class="relay-meta">医生查看 {{ r.view_count || 0 }} 次<template v-if="r.viewed_at">（{{ formatDateTime(r.viewed_at) }}）</template></span>
                </div>
                <div v-if="r.evidence_summary" class="relay-evidence">{{ r.evidence_summary }}</div>
                <div v-if="r.feedback_action" class="relay-feedback">
                  医生反馈：{{ r.feedback_action }}<template v-if="r.feedback_reason">（{{ r.feedback_reason }}）</template>
                </div>
              </div>
            </template>
            <div v-else class="pane-empty">暂无企微推送记录（或当前账号无查看权限）</div>
          </el-tab-pane>

          <el-tab-pane label="技术排障报文" name="payload">
            <el-alert
              type="info"
              :closable="false"
              class="payload-hint"
              title="技术报文默认折叠：点击展开后按需查看请求上下文 / AI 原始输出 / 脱敏病历原文，可复制用于排障。"
            />
            <el-collapse v-if="payloadEntries.length" class="payload-collapse">
              <el-collapse-item
                v-for="entry in payloadEntries"
                :key="entry.push_log_id"
                :name="entry.push_log_id"
                @change="(names: string | unknown) => onPayloadToggle(entry, names)"
              >
                <template #title>
                  <span class="pl-title">{{ formatDateTime(entry.push_time) }} · {{ entry.audit_type_name }}（记录 #{{ entry.push_log_id }}）</span>
                </template>
                <div v-if="payloadStates[entry.push_log_id]?.loading" v-loading="true" class="pl-loading" />
                <div v-else-if="payloadStates[entry.push_log_id]?.error" class="pane-empty">{{ payloadStates[entry.push_log_id].error }}</div>
                <template v-else-if="payloadStates[entry.push_log_id]?.data">
                  <div v-for="block in payloadBlocks(entry.push_log_id)" :key="block.key" class="pl-block">
                    <div class="pl-block-head">
                      <span class="pl-block-title">{{ block.title }}</span>
                      <el-button size="small" link type="primary" :disabled="!block.content" @click="copyText(block.content, block.title)">复制</el-button>
                    </div>
                    <pre v-if="block.content" class="pl-pre">{{ block.content }}</pre>
                    <div v-else class="pane-empty">（无内容）</div>
                  </div>
                </template>
                <div v-else class="pane-empty">点击展开后加载报文</div>
              </el-collapse-item>
            </el-collapse>
            <div v-else class="pane-empty">暂无核查记录报文</div>
          </el-tab-pane>
        </el-tabs>
      </template>
      <div v-else-if="!loadError && !loading" class="pane-empty">未找到患者质控详情</div>
    </div>
  </div>
</template>

<script setup lang="ts">
// PatientQcDetailView（WP05）：患者质控详情高可读性组件——抽屉与独立页共用。
// 四区块：①吸顶临床摘要卡（360 全息/全屏/打印）②总体结论徽章 ③左右双栏证据对照
// 问题卡（行内一键闭环）④历次核查/企微推送/技术报文三 Tab（报文默认全折叠懒加载）。
// 技术排障报文绝不铺满主界面：统一收进 Tab3 el-collapse，点开才调 /logs/{id}。
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { CopyDocument } from '@element-plus/icons-vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import HolographyButton from '@/components/base/HolographyButton.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { copyTextToClipboard } from '@/utils/clipboard'
import { canQuickAction, formatEvidence, hasEvidence, normalizePushLogId } from '@/utils/patient-qc-contracts'
import { ElMessage, ElMessageBox } from 'element-plus'

interface DimensionRow {
  dimension_code?: string
  dimension_name?: string
  dimension?: string
  status?: string
  severity?: string
  issue_summary?: string
  explanation?: string
  recommendation?: string
  medical_evidence?: unknown
  nursing_evidence?: unknown
}

interface LogRow {
  push_log_id?: number
  id?: number
  push_time?: string
  status?: string
  severity?: string
  overall_conclusion?: string
  overall_qc_summary?: string
  dimensions?: DimensionRow[]
  feedback?: { status?: string; feedback_text?: string; assigned_to_name?: string }
}

interface GroupRow {
  audit_type_code?: string
  audit_type_name?: string
  latest_push_time?: string
  overall_conclusion?: string
  overall_qc_summary?: string
  severity?: string
  logs?: LogRow[]
}

interface DetailData {
  patient: Record<string, unknown>
  clinical_summary?: Record<string, unknown>
  summary: Record<string, unknown>
  audit_groups: GroupRow[]
}

interface RelayRow {
  id?: number
  created_at?: string
  status?: string
  severity?: string
  evidence_summary?: string
  view_count?: number
  viewed_at?: string
  feedback_action?: string
  feedback_reason?: string
}

const props = withDefaults(defineProps<{
  patientId: string
  visitNumber: string
  dept?: string
  inDrawer?: boolean
}>(), {
  dept: '',
  inDrawer: false,
})

const emit = defineEmits<{ updated: [] }>()

const router = useRouter()
const loading = ref(false)
const loadError = ref('')
const detail = ref<DetailData | null>(null)
const activeTab = ref('history')
const issueMode = ref<'focus' | 'all'>('focus')

const cs = computed<Record<string, any>>(() => (detail.value?.clinical_summary || detail.value?.patient || {}) as Record<string, any>)
const summary = computed<Record<string, unknown>>(() => detail.value?.summary || {})

const ageText = computed(() => {
  const age = cs.value.age
  if (age === '' || age === null || age === undefined) return ''
  return `${age}岁`
})

const mainDiagnosis = computed(() =>
  displayText(cs.value.discharge_diagnosis) !== '—'
    ? displayText(cs.value.discharge_diagnosis)
    : displayText(cs.value.admission_diagnosis),
)

const riskLevel = computed(() => {
  const s = summary.value
  if (Number(s.high_count) > 0) return 'high'
  if (Number(s.medium_count) > 0) return 'medium'
  if (Number(s.issue_count) > 0) return 'low'
  return ''
})

const overallSummary = computed(() => {
  for (const g of detail.value?.audit_groups || []) {
    const text = String(g.overall_qc_summary || g.overall_conclusion || '').trim()
    if (text) return text
  }
  return ''
})

/** 全量问题卡（跨 audit_groups 展平，按风险从高到低）。 */
const allIssues = computed(() => {
  const issues: Array<Record<string, any>> = []
  for (const g of detail.value?.audit_groups || []) {
    for (const log of g.logs || []) {
      for (const dim of log.dimensions || []) {
        const st = String(dim.status || '')
        const isIssue = ['fail', 'risk', 'warning', 'warn'].includes(st) || !!dim.issue_summary
        if (!isIssue) continue
        issues.push({
          push_log_id: normalizePushLogId(log as Record<string, unknown>) as number,
          dimension_code: dim.dimension_code,
          dimension_name: dim.dimension || dim.dimension_name || dim.dimension_code,
          audit_type_name: g.audit_type_name || g.audit_type_code || '',
          severity: dim.severity || log.severity || g.severity || '',
          status: st,
          issue_summary: dim.issue_summary || '',
          explanation: dim.explanation || '',
          recommendation: dim.recommendation || '',
          medical_evidence: dim.medical_evidence,
          nursing_evidence: dim.nursing_evidence,
          push_time: log.push_time || '',
          feedback_status: log.feedback?.status || 'pending',
        })
      }
    }
  }
  const order: Record<string, number> = { high: 0, medium: 1, low: 2 }
  return issues.sort((a, b) => (order[String(a.severity)] ?? 3) - (order[String(b.severity)] ?? 3))
})

const visibleIssues = computed(() => {
  if (issueMode.value === 'all') return allIssues.value
  return allIssues.value.filter((i) => ['high', 'medium'].includes(String(i.severity || '')))
})

/** 历次核查时间线（倒序，含质控类型/风险/成功态/医生反馈）。 */
const historyItems = computed(() => {
  const rows: Array<Record<string, any>> = []
  for (const g of detail.value?.audit_groups || []) {
    for (const log of g.logs || []) {
      rows.push({
        push_log_id: normalizePushLogId(log as Record<string, unknown>) as number,
        push_time: log.push_time || '',
        audit_type_name: g.audit_type_name || g.audit_type_code || '',
        status: log.status || '',
        severity: log.severity || g.severity || '',
        overall_conclusion: log.overall_conclusion || '',
        feedback_text: log.feedback?.feedback_text || '',
        success: String(log.status || '') === 'success',
      })
    }
  }
  return rows.sort((a, b) => String(b.push_time).localeCompare(String(a.push_time)))
})

/** 技术报文条目（每条推送一个折叠项，默认全折叠）。 */
const payloadEntries = computed(() => {
  const entries: Array<{ push_log_id: number; push_time: string; audit_type_name: string }> = []
  for (const g of detail.value?.audit_groups || []) {
    for (const log of g.logs || []) {
      const id = normalizePushLogId(log as Record<string, unknown>)
      if (!id) continue
      entries.push({
        push_log_id: id,
        push_time: log.push_time || '',
        audit_type_name: g.audit_type_name || g.audit_type_code || '',
      })
    }
  }
  return entries.sort((a, b) => String(b.push_time).localeCompare(String(a.push_time)))
})

const relayItems = ref<RelayRow[]>([])

const issueBusyStates = reactive<Record<number, boolean>>({})
function issueBusy(pushLogId: number | undefined): boolean {
  return Boolean(pushLogId && issueBusyStates[pushLogId])
}

const payloadStates = reactive<Record<number, { loading: boolean; error: string; data: Record<string, unknown> | null }>>({})

async function load(): Promise<void> {
  if (!props.patientId) {
    loadError.value = '缺少 patient_id 参数'
    return
  }
  loading.value = true
  loadError.value = ''
  try {
    detail.value = (await apiGet<DetailData>('/patient-qc/patient-detail', {
      params: {
        patient_id: props.patientId,
        visit_number: props.visitNumber,
        dept: props.dept || undefined,
      },
    })) as DetailData
    void loadRelay()
  } catch (e) {
    loadError.value = toUserMessage(e, '加载患者详情失败')
  } finally {
    loading.value = false
  }
}

/** 企微推送与医生反馈（admin 接口，403 静默降级为空态）。 */
async function loadRelay(): Promise<void> {
  try {
    const data = await apiGet<{ items?: RelayRow[] }>('/patient-qc/relay-alert/logs', {
      params: { patient_id: props.patientId, page: 1, limit: 20 },
    })
    relayItems.value = data.items || []
  } catch {
    relayItems.value = []
  }
}

/** 一键闭环：确认属实=confirm acknowledged；已整改=quick-action rectified；误报=confirm closed。 */
async function confirmIssue(issue: Record<string, any>, kind: 'acknowledged' | 'rectified' | 'closed'): Promise<void> {
  const logId = Number(issue.push_log_id || 0)
  if (!Number.isSafeInteger(logId) || logId <= 0 || issueBusy(logId)) return
  const tipMap: Record<string, string> = {
    acknowledged: '确认属实',
    rectified: '标记已整改',
    closed: '登记误报并关闭',
  }
  let note = ''
  try {
    const result = await ElMessageBox.prompt(
      `${tipMap[kind]}：「${issue.dimension_name || '该维度'}」（备注选填，写入审计留痕）`,
      '行内闭环确认',
      { confirmButtonText: '确定', cancelButtonText: '取消', inputPlaceholder: '备注（选填）', type: 'warning' },
    )
    note = String((result as { value?: string }).value || '').trim()
  } catch {
    return
  }
  issueBusyStates[logId] = true
  try {
    if (kind === 'rectified') {
      await apiPost('/patient-qc/feedback/quick-action', { push_log_id: logId, action: 'rectified', reason: note || '已整改' })
    } else {
      await apiPost(`/qc/feedback/cases/${logId}/confirm`, {
        action: kind,
        review_comment: kind === 'closed' ? (note ? `误报：${note}` : '误报') : note,
      })
    }
    ElMessage.success(`${tipMap[kind]}已完成`)
    await load()
    emit('updated')
  } catch (e) {
    const message = toUserMessage(e, '操作失败')
    ElMessage.error(message.includes('403') ? '需要审批权限（approve_feedback）或由质控员操作' : message)
  } finally {
    issueBusyStates[logId] = false
  }
}

async function retryOne(pushLogId: number): Promise<void> {
  try {
    await ElMessageBox.confirm(`确认重推该核查记录？(ID: ${pushLogId})`, '重推确认', { type: 'warning' })
    await apiPost(`/logs/${pushLogId}/retry`)
    ElMessage.success('重推已提交')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '重推失败'))
  }
}

/** 技术报文懒加载：折叠项首次展开才拉 /logs/{id}，缓存后不重复请求。 */
function onPayloadToggle(entry: { push_log_id: number }, names: string | unknown): void {
  const active = Array.isArray(names) ? names : (names ? [names] : [])
  if (!active.includes(entry.push_log_id as never) && !active.includes(String(entry.push_log_id))) return
  if (payloadStates[entry.push_log_id]) return
  payloadStates[entry.push_log_id] = { loading: true, error: '', data: null }
  apiGet<Record<string, unknown>>(`/logs/${entry.push_log_id}`)
    .then((data) => {
      payloadStates[entry.push_log_id] = { loading: false, error: '', data }
    })
    .catch((e) => {
      payloadStates[entry.push_log_id] = { loading: false, error: toUserMessage(e, '报文加载失败'), data: null }
    })
}

function prettyJson(value: unknown): string {
  if (value == null || value === '') return ''
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return ''
    try {
      return JSON.stringify(JSON.parse(text), null, 2)
    } catch {
      return text
    }
  }
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function payloadBlocks(pushLogId: number): Array<{ key: string; title: string; content: string }> {
  const state = payloadStates[pushLogId]
  const data = state?.data
  if (!data) return []
  return [
    { key: 'request', title: '请求上下文（request_json）', content: prettyJson(data.request_json) },
    { key: 'response', title: 'AI 原始输出（response_json / ai_result）', content: prettyJson(data.response_json || data.ai_result) },
    { key: 'mr', title: '脱敏病历原文预览（mr_text）', content: String(data.mr_text || '').trim() },
  ]
}

async function copyText(text: string, label: string): Promise<void> {
  const content = String(text || '').trim()
  if (!content) return
  const ok = await copyTextToClipboard(content)
  if (ok) ElMessage.success(`${label}已复制`)
  else ElMessage.warning('当前浏览器不支持复制')
}

async function copyIds(): Promise<void> {
  const text = `${cs.value.admission_no || cs.value.patient_id || props.patientId}`
  if (!text) return
  const ok = await copyTextToClipboard(text)
  if (ok) ElMessage.success('已复制住院号/患者号')
  else ElMessage.warning('复制失败，请手动复制')
}

function openStandalone(): void {
  const href = router.resolve({
    path: '/quality/patient-detail',
    query: { patient_id: props.patientId, visit_number: props.visitNumber },
  }).href
  window.open(href, '_blank', 'noopener')
}

function printPage(): void {
  window.print()
}

onMounted(load)

defineExpose({ reload: load })
</script>

<style scoped>
.pq-detail-view { font-size: 13px; }
.pqdv-body { min-height: 120px; }

/* 区块 1：吸顶患者临床摘要卡 */
.patient-banner {
  position: sticky;
  top: 0;
  z-index: 5;
  background: #f8fafc;
  border: 1px solid var(--ma-border, #e2e8f0);
  border-left: 4px solid var(--ma-blue-600, #2563eb);
  border-radius: var(--ma-radius, 10px);
  padding: 14px 16px;
  margin-bottom: 16px;
}
.banner-top { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.banner-identity { display: flex; align-items: center; gap: 10px; min-width: 0; }
.banner-name { font-size: 20px; font-weight: 700; color: var(--ma-text-strong, #0f172a); }
.banner-grey { color: var(--el-text-color-secondary); font-size: 13px; }
.banner-id {
  margin-left: 4px; padding: 2px 10px; border-radius: 999px;
  background: #fff; border: 1px dashed var(--el-border-color);
  font-size: 12px; color: var(--el-text-color-secondary); cursor: pointer;
}
.banner-id:hover { color: var(--el-color-primary); border-color: var(--el-color-primary); }
.banner-copy { margin-left: 2px; vertical-align: -2px; }
.banner-spacer { flex: 1; }
.banner-actions { margin-left: auto; display: flex; gap: 8px; align-items: center; }
.banner-grid {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 8px 14px;
}
.banner-item { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.banner-item--wide { grid-column: span 2; }
.bi-label { font-size: 12px; color: var(--el-text-color-secondary); }
.bi-value { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* 区块 2：总体结论 */
.conclusion-block { margin-bottom: 16px; }
.conclusion-badges { display: flex; gap: 10px; flex-wrap: wrap; }
.cbadge {
  padding: 4px 12px; border-radius: 999px; font-size: 12px;
  border: 1px solid var(--el-border-color); background: #fff; color: var(--el-text-color-secondary);
}
.cbadge b { margin: 0 2px; font-size: 14px; }
.cbadge-high { border-color: #fecaca; background: #fef2f2; color: #b91c1c; }
.cbadge-medium { border-color: #fde68a; background: #fffbeb; color: #b45309; }
.cbadge-low { border-color: #bbf7d0; background: #f0fdf4; color: #15803d; }
.conclusion-text { margin: 10px 0 0; line-height: 1.65; color: var(--el-text-color-primary); }
.conclusion-empty { color: var(--el-text-color-secondary); }

/* 区块 3：问题卡 */
.issues-block { margin-bottom: 16px; }
.issues-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
.issues-title { font-size: 14px; font-weight: 700; }
.issues-empty { color: var(--el-text-color-secondary); text-align: center; padding: 18px; border: 1px dashed var(--el-border-color); border-radius: 8px; }
.issue-card {
  background: #fff; border: 1px solid var(--el-border-color-lighter);
  border-left: 3px solid var(--el-border-color); border-radius: 10px;
  padding: 12px 14px; margin-bottom: 10px;
}
.issue-high { border-left-color: #ef4444; }
.issue-medium { border-left-color: #f59e0b; }
.issue-low { border-left-color: #22c55e; }
.issue-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.issue-dim { font-size: 15px; font-weight: 700; }
.issue-spacer { flex: 1; }
.issue-actions { display: inline-flex; gap: 6px; flex-wrap: wrap; }
.issue-text { margin: 8px 0; line-height: 1.6; }
.evidence-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 8px 0; }
.evidence-grid.evidence-single { grid-template-columns: 1fr; }
.ev-box { border-radius: 8px; padding: 10px 12px; min-width: 0; }
.ev-medical { background: #f1f5f9; border: 1px solid #e2e8f0; }
.ev-nursing { background: #fffbeb; border: 1px solid #fde68a; }
.ev-title { font-size: 12px; font-weight: 600; color: var(--el-text-color-secondary); margin-bottom: 6px; }
.ev-text { margin: 0; white-space: pre-wrap; word-break: break-word; font-size: 12px; line-height: 1.55; font-family: inherit; }
.issue-advice {
  margin-top: 6px; padding: 6px 10px; border-radius: 8px;
  background: #f0fdf4; border: 1px solid #bbf7d0; color: #166534; font-size: 12px; line-height: 1.5;
}

/* 区块 4：三 Tab */
.history-tabs { margin-top: 4px; }
.pane-empty { color: var(--el-text-color-secondary); text-align: center; padding: 18px; }
.tl-card { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 8px 12px; }
.tl-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tl-type { font-weight: 600; }
.tl-spacer { flex: 1; }
.tl-conclusion { margin-top: 6px; font-size: 12px; line-height: 1.55; color: var(--el-text-color-regular); }
.tl-feedback { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.relay-card { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 10px 12px; margin-bottom: 10px; }
.relay-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.relay-time { font-weight: 600; }
.relay-meta { font-size: 12px; color: var(--el-text-color-secondary); }
.relay-evidence { margin-top: 6px; font-size: 12px; line-height: 1.55; }
.relay-feedback { margin-top: 4px; font-size: 12px; color: var(--el-text-color-secondary); }
.payload-hint { margin-bottom: 10px; }
.pl-title { font-size: 12px; color: var(--el-text-color-secondary); }
.pl-loading { min-height: 80px; }
.pl-block { margin-bottom: 10px; }
.pl-block-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; }
.pl-block-title { font-size: 12px; font-weight: 600; color: var(--el-text-color-secondary); }
.pl-pre {
  margin: 0; max-height: 300px; overflow: auto; padding: 10px 12px; border-radius: 8px;
  background: #0f172a; color: #e2e8f0; font-size: 12px; line-height: 1.5;
  white-space: pre-wrap; word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

/* 打印：隐藏交互按钮 */
@media print {
  .no-print { display: none !important; }
  .patient-banner { position: static; }
}
</style>
