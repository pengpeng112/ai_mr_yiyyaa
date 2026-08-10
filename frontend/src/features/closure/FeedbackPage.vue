<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface FeedbackCase {
  log_id?: number
  id?: number
  status?: string
  dept?: string
  severity?: string
  updated_at?: string
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<FeedbackCase[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summaryItems = ref<SummaryItem[]>([])
const filters = reactive({
  status: '',
  dept: '',
})
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)
const mutationsEnabled = true

async function loadSummary() {
  try {
    const s = await apiGet<Record<string, number>>('/qc/feedback/stats/summary')
    summaryItems.value = [
      { key: 'total', label: '总量', value: Number(s.total ?? 0) },
      { key: 'pending', label: '待处理', value: Number(s.pending ?? 0), tone: 'warning' },
      { key: 'processing', label: '处理中', value: Number(s.processing ?? 0), tone: 'info' },
      { key: 'closed', label: '已关闭', value: Number(s.closed ?? 0), tone: 'success' },
    ]
  } catch {
    summaryItems.value = []
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<{ items?: FeedbackCase[]; total?: number }>('/qc/feedback/cases', {
      params: {
        page: page.value,
        limit: pageSize.value,
        status: filters.status || undefined,
        dept: filters.dept || undefined,
      },
    })
    items.value = data.items || []
    total.value = data.total || 0
    await loadSummary()
  } catch (e) {
    error.value = toUserMessage(e, '加载整改反馈失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  void load()
}

function reset() {
  filters.status = ''
  filters.dept = ''
  page.value = 1
  void load()
}

async function openDetail(row: FeedbackCase) {
  const id = row.log_id ?? row.id
  if (!id) return
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = (await apiGet(`/qc/feedback/cases/${id}`)) as Record<string, unknown>
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载反馈详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function confirmCase(row: FeedbackCase) {
  if (!mutationsEnabled) {
    ElMessage.warning('写操作未启用')
    return
  }
  const id = row.log_id ?? row.id
  if (!id) return
  try {
    await ElMessageBox.confirm('确认将该反馈案件标记为已确认？', '请确认', { type: 'warning' })
    await apiPost(`/qc/feedback/cases/${id}/confirm`)
    ElMessage.success('已确认')
    await load()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(toUserMessage(e, '确认失败'))
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-feedback">
    <PageHeader title="整改反馈" description="待处理/处理中/已关闭；科室权限与 suppress 语义保持不变。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <SummaryStrip :items="summaryItems" :loading="loading" />

    <FilterPanel @search="onSearch" @reset="reset">
      <el-select v-model="filters.status" clearable placeholder="状态">
        <el-option label="待处理" value="pending" />
        <el-option label="处理中" value="processing" />
        <el-option label="已关闭" value="closed" />
      </el-select>
      <el-input v-model="filters.dept" clearable placeholder="科室" />
    </FilterPanel>

    <DataTableShell
      :loading="loading"
      :error="error"
      :empty="!items.length"
      :total="total"
      :page="page"
      :page-size="pageSize"
      @retry="load"
      @update:page="(p) => { page = p; load() }"
      @update:page-size="(s) => { pageSize = s; page = 1; load() }"
    >
      <el-table v-loading="loading" :data="items" stripe border size="small">
        <el-table-column label="记录" width="100">
          <template #default="{ row }">{{ displayText(row.log_id ?? row.id) }}</template>
        </el-table-column>
        <el-table-column label="科室" min-width="120">
          <template #default="{ row }">{{ displayText(row.dept) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :value="row.status" /></template>
        </el-table-column>
        <el-table-column label="风险" width="100">
          <template #default="{ row }">{{ displayText(row.severity) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
            <el-button
              v-if="mutationsEnabled"
              link
              type="warning"
              @click="confirmCase(row)"
            >
              确认
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </DataTableShell>

    <DetailDrawer v-model="detailVisible" title="反馈详情" :loading="detailLoading">
      <pre v-if="detail" class="json-pre">{{ JSON.stringify(detail, null, 2) }}</pre>
    </DetailDrawer>
  </div>
</template>

<style scoped>
.json-pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 70vh;
  overflow: auto;
}
</style>
