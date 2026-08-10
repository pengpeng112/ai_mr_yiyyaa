<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface AlertRow {
  id?: number
  patient_id?: string
  status?: string
  dept?: string
  severity?: string
  created_at?: string
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<AlertRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const summaryItems = ref<SummaryItem[]>([])
const filters = reactive({
  status: '',
  patient_id: '',
  viewed_flag: '',
})

async function loadSummary() {
  try {
    const s = await apiGet<Record<string, number>>('/patient-qc/relay-alert/summary')
    summaryItems.value = [
      { key: 'total', label: '总量', value: Number(s.total ?? 0) },
      { key: 'success', label: '发送成功', value: Number(s.success ?? 0), tone: 'success' },
      { key: 'failed', label: '发送失败', value: Number(s.failed ?? 0), tone: 'danger' },
      { key: 'pending', label: '待发送', value: Number(s.pending ?? 0), tone: 'warning' },
    ]
  } catch {
    summaryItems.value = []
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<{ items?: AlertRow[]; total?: number }>('/patient-qc/relay-alert/logs', {
      params: {
        page: page.value,
        limit: pageSize.value,
        status: filters.status || undefined,
        patient_id: filters.patient_id || undefined,
        viewed_flag: filters.viewed_flag || undefined,
      },
    })
    items.value = data.items || []
    total.value = data.total || 0
    await loadSummary()
  } catch (e) {
    error.value = toUserMessage(e, '加载告警记录失败')
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
  filters.patient_id = ''
  filters.viewed_flag = ''
  page.value = 1
  void load()
}

async function retryAlert(row: AlertRow) {
  if (!row.id) return
  try {
    await ElMessageBox.confirm('确认重试该告警推送？不会自动批量重发。', '请确认', {
      type: 'warning',
    })
    await apiPost(`/patient-qc/relay-alert/retry/${row.id}`)
    ElMessage.success('已提交重试')
    await load()
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(toUserMessage(e, '重试失败'))
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-alerts">
    <PageHeader title="告警记录" description="生成、发送、查看、反馈链路；默认不自动重发。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <SummaryStrip :items="summaryItems" :loading="loading" />

    <FilterPanel @search="onSearch" @reset="reset">
      <el-select v-model="filters.status" clearable placeholder="发送状态">
        <el-option label="pending" value="pending" />
        <el-option label="success" value="success" />
        <el-option label="failed" value="failed" />
      </el-select>
      <el-select v-model="filters.viewed_flag" clearable placeholder="是否查看">
        <el-option label="已查看" value="1" />
        <el-option label="未查看" value="0" />
      </el-select>
      <template #more>
        <el-input v-model="filters.patient_id" clearable placeholder="患者 ID（筛选）" />
      </template>
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
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="科室" min-width="120">
          <template #default="{ row }">{{ displayText(row.dept) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }"><StatusTag :value="row.status" /></template>
        </el-table-column>
        <el-table-column label="严重度" width="100">
          <template #default="{ row }">{{ displayText(row.severity) }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              link
              type="warning"
              :disabled="String(row.status) !== 'failed'"
              @click="retryAlert(row)"
            >
              重试
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </DataTableShell>
  </div>
</template>
