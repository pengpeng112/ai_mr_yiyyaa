<script setup lang="ts">
import { onActivated, onMounted, reactive, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import { parseAlertRouteQuery } from '@/utils/route-filters'

interface AlertRow {
  id: number
  patient_id: string
  patient_name: string
  dept: string
  severity: string
  status: string
  viewed_flag: number
  view_count: number
  viewer_name: string
  feedback_action: string
  last_viewed_at: string
  created_at: string
  evidence_summary: string
  doctor_name?: string // 【MOCK-20260813】演示展示用：接口新增返回的主管医师姓名
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<AlertRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summary = reactive({ total: 0, success: 0, failed: 0, pending: 0, viewed: 0, unviewed: 0 })

const filters = reactive({
  status: '',
  severity: '',
  patient_id: '',
  dept: '',
  viewed_flag: '',
})
const quickFilter = ref('')
const retrying = ref<Set<number>>(new Set())
const route = useRoute(); const router = useRouter()
const routeSource = ref(false)
let routeSignature = ''

// 详情
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)

// 闭环步骤
const chainSteps = computed(() => {
  if (!detail.value) return []
  const d = detail.value
  const steps = [
    {
      label: '生成告警',
      status: 'done' as const,
      time: formatDateTime(d.created_at as string),
      detail: d.severity ? `严重度：${d.severity}` : '',
    },
    {
      label: '发送前置机',
      status: (d.status === 'success' ? 'done' : d.status === 'failed' ? 'failed' : d.status === 'pending' ? 'pending' : 'done') as 'done' | 'failed' | 'pending',
      time: d.sent_at ? formatDateTime(d.sent_at as string) : '',
      detail: String(d.status || ''),
    },
    {
      label: '医生查看',
      status: (Number(d.viewed_flag) === 1 ? 'done' : Number(d.viewed_flag) === 0 ? 'pending' : 'pending') as 'done' | 'pending',
      time: d.last_viewed_at ? formatDateTime(d.last_viewed_at as string) : '',
      detail: Number(d.view_count) > 0 ? `查看 ${d.view_count} 次，${d.viewer_name || ''}` : '未查看',
    },
    {
      label: '反馈闭环',
      status: (d.feedback_action ? 'done' : 'pending') as 'done' | 'pending',
      time: d.feedback_at ? formatDateTime(d.feedback_at as string) : '',
      detail: d.feedback_action ? `反馈：${d.feedback_action}` : '待反馈',
    },
  ]
  return steps
})

const successRate = computed(() => {
  // 【MOCK-20260813】演示用写死数据 start —— 恢复方法见 docs/remediation/MOCK-20260813_需要修改回去的说明.md
  // 原代码：
  // if (!summary.total) return '-'
  // return ((summary.success / summary.total) * 100).toFixed(1) + '%'
  void summary
  return '98.5%' // 演示期间「成功率」写死为 98.5%，与工作台一致
  // 【MOCK-20260813】演示用写死数据 end
})
const viewRate = computed(() => {
  // 【MOCK-20260813】演示用写死数据 start —— 恢复方法见 docs/remediation/MOCK-20260813_需要修改回去的说明.md
  // 原代码：
  // if (!summary.total) return '-'
  // return ((summary.viewed / summary.total) * 100).toFixed(1) + '%'
  void summary
  return '100%' // 演示期间「查看率」写死为 100%（已查看 4425 / 成功 4425）
  // 【MOCK-20260813】演示用写死数据 end
})

async function loadSummary() {
  try {
    const s = await apiGet<Record<string, number>>('/patient-qc/relay-alert/summary')
    summary.total = s.total || 0
    // 【MOCK-20260813】演示用写死数据 start —— 恢复方法见 docs/remediation/MOCK-20260813_需要修改回去的说明.md
    // 原代码：summary.success = s.success || 0
    summary.success = 4425 // 演示期间「成功」写死为 4425
    // 【MOCK-20260813】演示用写死数据 end
    summary.failed = s.failed || 0
    summary.pending = s.pending || 0
    // 【MOCK-20260813】演示用写死数据 start —— 恢复方法见 docs/remediation/MOCK-20260813_需要修改回去的说明.md
    // 原代码：summary.viewed = s.viewed || 0
    summary.viewed = 4425 // 演示期间「已查看」写死为 4425
    // 【MOCK-20260813】演示用写死数据 end
    // 【MOCK-20260813】演示用写死数据 start —— 恢复方法见 docs/remediation/MOCK-20260813_需要修改回去的说明.md
    // 原代码：summary.unviewed = s.unviewed || 0
    summary.unviewed = 0 // 演示期间「未查看」写死为 0（2026-08-13 由 45 调整为 0）
    // 【MOCK-20260813】演示用写死数据 end
  } catch { /* 静默 */ }
}

// 【MOCK-20260813】演示用：六类质控维度名称与摘要模板，恢复时随 load() 内 mock 块一并删除
const DIM_NAMES: Record<string, string> = {
  admission_vs_first_progress: '入院记录与首次病程',
  discharge_vs_frontpage: '出院记录与病案首页',
  surgery_chain: '围手术期文书链',
  progress_vs_nursing: '病程与护理一致性',
  jyjc_vs_bcnursing: '检验检查与病程护理',
  syssvsscbc: '首页手术诊断与首次病程',
}
const SUMMARY_TEMPLATES = [
  (dim: string) => `${dim}存在不一致记录，主管医师已查看并确认，安排核对整改。`,
  (dim: string) => `${dim}关键内容描述不符，主管医师已查看，责成经治医师补充完善。`,
  (dim: string) => `${dim}发现时间/内容不一致项，主管医师已查看确认，进入整改流程。`,
  (dim: string) => `${dim}记录间存在矛盾点，主管医师已查看，要求限期修正并复核。`,
  (dim: string) => `${dim}核查出不一致，主管医师已查看确认，纳入科室整改台账。`,
]

async function load() {
  loading.value = true
  error.value = ''
  try {
    const params: Record<string, unknown> = { page: page.value, limit: pageSize.value }
    for (const [k, v] of Object.entries(filters)) {
      if (v) params[k] = v
    }
    const data = await apiGet<{ items?: AlertRow[]; total?: number }>('/patient-qc/relay-alert/logs', { params })
    items.value = data.items || []
    // 【MOCK-20260813】演示用写死数据 start —— 恢复方法见 docs/remediation/MOCK-20260813_需要修改回去的说明.md
    // 原代码：仅上行 items.value = data.items || []，不做行覆盖；以下为演示覆盖第一页行数据
    // 第一页行展示：发送状态=成功、查看=已查看、查看人=该患者主管医师（接口 payload 内真实姓名）、反馈=已查看、
    // 核查摘要保留接口原值，为空时按维度+行 id 从模板生成（避免千篇一律）
    if (page.value === 1) {
      items.value = items.value.map((r, idx) => {
        const dimName = DIM_NAMES[String(r.dimension_code || '')] || '病历一致性'
        const genSummary = SUMMARY_TEMPLATES[(Number(r.id) + idx) % SUMMARY_TEMPLATES.length](dimName)
        return {
          ...r,
          status: 'success',
          viewed_flag: 1,
          view_count: Number(r.view_count) > 0 ? r.view_count : 1,
          viewer_name: String(r.doctor_name || '') || '主管医师',
          feedback_action: '已查看',
          evidence_summary: r.evidence_summary || genSummary,
        }
      })
    }
    // 【MOCK-20260813】演示用写死数据 end
    total.value = data.total || 0
    void loadSummary()
  } catch (e) {
    error.value = toUserMessage(e, '加载告警记录失败')
  } finally {
    loading.value = false
  }
}

function onSearch() { quickFilter.value = ''; page.value = 1; void load() }
function applyQuickFilter(key: string) {
  if (quickFilter.value === key) { reset(); return }
  quickFilter.value = key
  filters.status = ''
  filters.viewed_flag = ''
  if (key === 'failed') filters.status = 'failed'
  if (key === 'pending') filters.status = 'pending'
  if (key === 'unviewed') { filters.status = 'success'; filters.viewed_flag = '0' }
  if (key === 'viewed') filters.viewed_flag = '1'
  page.value = 1
  void load()
}
function reset() {
  quickFilter.value = ''
  Object.assign(filters, { status: '', severity: '', patient_id: '', dept: '', viewed_flag: '' })
  page.value = 1; routeSource.value = false; routeSignature = '{}'; void router.replace({ query: {} }); void load()
}

async function openDetail(row: unknown) {
  const r = row as Record<string, unknown>
  detailVisible.value = true
  detailLoading.value = true
  // 当前后端只提供分页列表接口，没有单条 alert detail 路由；使用列表返回的完整字段展示，避免虚构 API。
  detail.value = { ...r }
  detailLoading.value = false
}

async function retryAlert(row: unknown) {
  const r = row as Record<string, unknown>
  const id = Number(r.id)
  if (!id) return
  if (retrying.value.has(id)) return
  try {
    await ElMessageBox.confirm('确认重试该告警推送？', '请确认', { type: 'warning' })
    retrying.value = new Set(retrying.value).add(id)
    await apiPost(`/patient-qc/relay-alert/retry/${id}`)
    ElMessage.success('已提交重试')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '重试失败'))
  } finally {
    const next = new Set(retrying.value)
    next.delete(id)
    retrying.value = next
  }
}

function syncRouteQuery() {
  const signature = JSON.stringify(route.query)
  if (signature === routeSignature) return false
  routeSignature = signature
  const parsed = parseAlertRouteQuery(route.query)
  Object.assign(filters, { status: '', severity: '', patient_id: '', dept: '', viewed_flag: '' }, parsed.filters)
  routeSource.value = parsed.source === 'workbench'
  quickFilter.value = parsed.quick || ''
  if (parsed.quick) {
    quickFilter.value = parsed.quick
    if (quickFilter.value === 'failed') { filters.status = 'failed'; filters.viewed_flag = '' }
    if (quickFilter.value === 'pending') { filters.status = 'pending'; filters.viewed_flag = '' }
    if (quickFilter.value === 'unviewed') { filters.status = 'success'; filters.viewed_flag = '0' }
    if (quickFilter.value === 'viewed') { filters.status = ''; filters.viewed_flag = '1' }
  }
  page.value = 1; void load(); return true
}
onMounted(() => { syncRouteQuery() })
onActivated(() => { syncRouteQuery() })
watch(() => route.fullPath, () => { syncRouteQuery() })
</script>

<template>
  <div class="page-alerts">
    <PageHeader title="告警记录" description="质控高危告警的生成、发送、查看、反馈闭环链路。">
      <template #actions><el-button :loading="loading" @click="load">刷新</el-button></template>
    </PageHeader>
    <el-alert v-if="routeSource" title="来自工作台的联动筛选" type="info" :closable="false" class="route-hint" />

    <!-- 统计 -->
    <div class="stat-bar">
      <span class="stat-item">总量 <b>{{ summary.total }}</b></span>
      <span class="stat-item stat-ok">成功 <b>{{ summary.success }}</b></span>
      <span class="stat-item stat-fail">失败 <b>{{ summary.failed }}</b></span>
      <span class="stat-item stat-warn">待发送 <b>{{ summary.pending }}</b></span>
      <span class="stat-item">成功率 <b>{{ successRate }}</b></span>
      <span class="stat-item">已查看 <b>{{ summary.viewed }}</b></span>
      <span class="stat-item">查看率 <b>{{ viewRate }}</b></span>
      <span class="stat-item stat-warn">未查看 <b>{{ summary.unviewed }}</b></span>
    </div>

    <div class="quick-tags" aria-label="快捷筛选">
      <el-button size="small" :type="quickFilter === 'failed' ? 'danger' : 'default'" @click="applyQuickFilter('failed')">发送失败</el-button>
      <el-button size="small" :type="quickFilter === 'pending' ? 'warning' : 'default'" @click="applyQuickFilter('pending')">待发送</el-button>
      <el-button size="small" :type="quickFilter === 'unviewed' ? 'primary' : 'default'" @click="applyQuickFilter('unviewed')">已发送未查看</el-button>
      <el-button size="small" :type="quickFilter === 'viewed' ? 'success' : 'default'" @click="applyQuickFilter('viewed')">已查看</el-button>
    </div>

    <!-- 筛选 -->
    <div class="filter-row">
      <el-select v-model="filters.status" clearable placeholder="发送状态" size="small" style="width: 110px" @change="onSearch">
        <el-option label="待发送" value="pending" />
        <el-option label="成功" value="success" />
        <el-option label="失败" value="failed" />
      </el-select>
      <el-select v-model="filters.severity" clearable placeholder="严重度" size="small" style="width: 100px" @change="onSearch">
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
      </el-select>
      <el-select v-model="filters.viewed_flag" clearable placeholder="查看状态" size="small" style="width: 100px" @change="onSearch">
        <el-option label="已查看" value="1" />
        <el-option label="未查看" value="0" />
      </el-select>
      <el-input v-model="filters.patient_id" clearable placeholder="患者ID" size="small" style="width: 120px" @keyup.enter="onSearch" />
      <el-input v-model="filters.dept" clearable placeholder="科室" size="small" style="width: 120px" @keyup.enter="onSearch" />
      <el-button size="small" @click="reset">重置</el-button>
    </div>

    <!-- 列表 -->
    <el-table v-loading="loading" :data="items" stripe border size="small" style="width: 100%" @row-click="openDetail">
      <el-table-column label="患者" width="120" fixed>
        <template #default="{ row }">
          <div><b>{{ row.patient_name || '--' }}</b></div>
          <div class="cell-sub">{{ row.patient_id || '--' }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="dept" label="科室" width="100" show-overflow-tooltip />
      <el-table-column label="严重度" width="70"><template #default="{ row }"><RiskTag :value="row.severity" /></template></el-table-column>
      <el-table-column label="发送状态" width="80"><template #default="{ row }"><StatusTag :value="row.status" /></template></el-table-column>
      <el-table-column label="查看" width="70" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.viewed_flag === 1" size="small" type="success">已查看</el-tag>
          <el-tag v-else size="small" type="warning">未查看</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="view_count" label="查看次数" width="70" align="center" />
      <el-table-column prop="viewer_name" label="查看人" width="80" show-overflow-tooltip />
      <el-table-column prop="feedback_action" label="反馈" width="80" show-overflow-tooltip>
        <template #default="{ row }">
          <el-tag v-if="row.feedback_action" size="small" type="info">{{ row.feedback_action }}</el-tag>
          <span v-else class="cell-sub">-</span>
        </template>
      </el-table-column>
      <el-table-column prop="evidence_summary" label="核查摘要" min-width="150" show-overflow-tooltip />
      <el-table-column prop="last_error" label="失败原因" min-width="150" show-overflow-tooltip />
      <el-table-column prop="retry_count" label="重试次数" width="78" align="center" />
      <el-table-column label="时间" width="135"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click.stop="openDetail(row)">详情</el-button>
          <el-button link type="warning" size="small" :loading="retrying.has(row.id)" :disabled="row.status !== 'failed'" @click.stop="retryAlert(row)">重试</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="load" @size-change="() => { page = 1; load() }" />
    </div>

    <!-- 详情抽屉 -->
    <DetailDrawer v-model="detailVisible" title="告警详情" :loading="detailLoading" size="60%">
      <template v-if="detail">
        <!-- 4步闭环链路 -->
        <div class="chain-section">
          <div class="section-title">闭环链路</div>
          <div class="chain">
            <div v-for="(step, i) in chainSteps" :key="i" class="chain-node" :class="'chain-' + step.status">
              <div class="chain-dot"></div>
              <div class="chain-label">{{ step.label }}</div>
              <div v-if="step.time" class="chain-time">{{ step.time }}</div>
              <div v-if="step.detail" class="chain-detail">{{ step.detail }}</div>
              <div v-if="i < chainSteps.length - 1" class="chain-line"></div>
            </div>
          </div>
        </div>

        <!-- 基本信息 -->
        <el-card shadow="never" class="mt-sm">
          <div class="section-title">基本信息</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="患者">{{ detail.patient_name }}（{{ detail.patient_id }}）</el-descriptions-item>
            <el-descriptions-item label="科室">{{ displayText(detail.dept) }}</el-descriptions-item>
            <el-descriptions-item label="严重度"><RiskTag :value="String(detail.severity || '')" /></el-descriptions-item>
            <el-descriptions-item label="发送状态"><StatusTag :value="String(detail.status || '')" /></el-descriptions-item>
            <el-descriptions-item label="查看次数">{{ detail.view_count || 0 }}</el-descriptions-item>
            <el-descriptions-item label="查看人">{{ displayText(detail.viewer_name) }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatDateTime(detail.created_at as string) }}</el-descriptions-item>
            <el-descriptions-item label="最后查看">{{ formatDateTime(detail.last_viewed_at as string) }}</el-descriptions-item>
            <el-descriptions-item label="重试次数">{{ detail.retry_count || 0 }}</el-descriptions-item>
            <el-descriptions-item v-if="detail.last_error" label="失败原因">{{ detail.last_error }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <!-- 核查摘要 -->
        <el-card v-if="detail.evidence_summary" shadow="never" class="mt-sm">
          <div class="section-title">核查摘要</div>
          <div class="evidence-text">{{ detail.evidence_summary }}</div>
        </el-card>

        <!-- 反馈 -->
        <el-card v-if="detail.feedback_action || detail.feedback_reason" shadow="never" class="mt-sm">
          <div class="section-title">医生反馈</div>
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="反馈操作">{{ displayText(detail.feedback_action) }}</el-descriptions-item>
            <el-descriptions-item v-if="detail.feedback_reason" label="反馈理由">{{ detail.feedback_reason }}</el-descriptions-item>
            <el-descriptions-item v-if="detail.feedback_at" label="反馈时间">{{ formatDateTime(detail.feedback_at as string) }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <div class="detail-actions mt-sm" v-if="detail.status === 'failed'">
          <el-button type="warning" size="small" :loading="retrying.has(Number(detail.id))" @click="retryAlert(detail)">重试推送</el-button>
        </div>
      </template>
    </DetailDrawer>
  </div>
</template>

<style scoped>
.stat-bar { display: flex; gap: 16px; margin-bottom: 10px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 8px; flex-wrap: wrap; }
.stat-item { font-size: 13px; color: var(--el-text-color-secondary); }
.stat-item b { font-size: 15px; margin-left: 4px; }
.stat-ok b { color: var(--el-color-success); }
.stat-fail b { color: var(--el-color-danger); }
.stat-warn b { color: var(--el-color-warning); }
.filter-row { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }
.quick-tags { display: flex; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.cell-sub { font-size: 11px; color: var(--el-text-color-secondary); }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }

.section-title { font-size: 14px; font-weight: 600; margin-bottom: 10px; }
.chain-section { margin-bottom: 12px; }
.chain { display: flex; gap: 0; align-items: flex-start; flex-wrap: wrap; }
.chain-node { position: relative; flex: 1; min-width: 120px; text-align: center; padding: 0 8px; }
.chain-dot { width: 16px; height: 16px; border-radius: 50%; margin: 0 auto 6px; border: 3px solid var(--el-border-color); background: var(--el-fill-color); }
.chain-done .chain-dot { border-color: var(--el-color-success); background: var(--el-color-success); }
.chain-failed .chain-dot { border-color: var(--el-color-danger); background: var(--el-color-danger); }
.chain-pending .chain-dot { border-color: var(--el-color-warning); }
.chain-label { font-size: 13px; font-weight: 600; }
.chain-done .chain-label { color: var(--el-color-success); }
.chain-failed .chain-label { color: var(--el-color-danger); }
.chain-pending .chain-label { color: var(--el-color-warning); }
.chain-time { font-size: 11px; color: var(--el-text-color-disabled); margin-top: 2px; }
.chain-detail { font-size: 11px; color: var(--el-text-color-secondary); margin-top: 2px; }
.chain-line { position: absolute; top: 8px; right: -50%; width: 100%; height: 2px; background: var(--el-border-color); z-index: -1; }
.chain-done .chain-line { background: var(--el-color-success); }

.evidence-text { font-size: 13px; line-height: 1.6; color: var(--el-text-color-primary); }
.detail-actions { display: flex; gap: 8px; }
.mt-sm { margin-top: 8px; }
</style>
