<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

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
      time: d.dispatched_at ? formatDateTime(d.dispatched_at as string) : '',
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
  if (!summary.total) return '-'
  return ((summary.success / summary.total) * 100).toFixed(1) + '%'
})
const viewRate = computed(() => {
  if (!summary.total) return '-'
  return ((summary.viewed / summary.total) * 100).toFixed(1) + '%'
})

async function loadSummary() {
  try {
    const s = await apiGet<Record<string, number>>('/patient-qc/relay-alert/summary')
    summary.total = s.total || 0
    summary.success = s.success || 0
    summary.failed = s.failed || 0
    summary.pending = s.pending || 0
    summary.viewed = s.viewed || 0
    summary.unviewed = s.unviewed || 0
  } catch { /* 静默 */ }
}

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
    total.value = data.total || 0
    void loadSummary()
  } catch (e) {
    error.value = toUserMessage(e, '加载告警记录失败')
  } finally {
    loading.value = false
  }
}

function onSearch() { page.value = 1; void load() }
function reset() {
  Object.assign(filters, { status: '', severity: '', patient_id: '', dept: '', viewed_flag: '' })
  page.value = 1; void load()
}

async function openDetail(row: unknown) {
  const r = row as Record<string, unknown>
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await apiGet<Record<string, unknown>>(`/patient-qc/relay-alert/logs/${Number(r.id)}`)
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function retryAlert(row: unknown) {
  const r = row as Record<string, unknown>
  const id = Number(r.id)
  if (!id) return
  try {
    await ElMessageBox.confirm('确认重试该告警推送？', '请确认', { type: 'warning' })
    await apiPost(`/patient-qc/relay-alert/retry/${id}`)
    ElMessage.success('已提交重试')
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '重试失败'))
  }
}

onMounted(() => { void load() })
</script>

<template>
  <div class="page-alerts">
    <PageHeader title="告警记录" description="质控高危告警的生成、发送、查看、反馈闭环链路。">
      <template #actions><el-button :loading="loading" @click="load">刷新</el-button></template>
    </PageHeader>

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
      <el-table-column label="时间" width="135"><template #default="{ row }">{{ formatDateTime(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" width="100" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click.stop="openDetail(row)">详情</el-button>
          <el-button link type="warning" size="small" :disabled="row.status !== 'failed'" @click.stop="retryAlert(row)">重试</el-button>
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
          <el-button type="warning" size="small" @click="retryAlert(detail)">重试推送</el-button>
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
