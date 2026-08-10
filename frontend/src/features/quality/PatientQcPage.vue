<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiGet } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage } from 'element-plus'

interface PatientRow {
  patient_id?: string
  visit_number?: string | number
  dept?: string
  severity?: string
  latest_log_id?: number
  status?: string
  [key: string]: unknown
}

const loading = ref(false)
const error = ref('')
const items = ref<PatientRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const filters = reactive({
  dept: '',
  severity: '',
  patient_id: '',
  keyword: '',
})

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<{ items?: PatientRow[]; total?: number }>('/patient-qc/patients', {
      params: {
        page: page.value,
        limit: pageSize.value,
        dept: filters.dept || undefined,
        severity: filters.severity || undefined,
        patient_id: filters.patient_id || undefined,
        keyword: filters.keyword || undefined,
      },
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    error.value = toUserMessage(e, '加载患者质控失败')
  } finally {
    loading.value = false
  }
}

function onSearch() {
  page.value = 1
  void load()
}

function reset() {
  filters.dept = ''
  filters.severity = ''
  filters.patient_id = ''
  filters.keyword = ''
  page.value = 1
  void load()
}

async function openDetail(row: PatientRow) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = (await apiGet('/patient-qc/patient-detail', {
      params: {
        patient_id: row.patient_id,
        visit_number: row.visit_number,
      },
    })) as Record<string, unknown>
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载患者详情失败'))
  } finally {
    detailLoading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-patient-qc">
    <PageHeader title="患者质控" description="病例维度主入口；遵守 current/superseded 与科室可见性。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <FilterPanel @search="onSearch" @reset="reset">
      <el-input v-model="filters.dept" clearable placeholder="科室" />
      <el-select v-model="filters.severity" clearable placeholder="最高风险">
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-input v-model="filters.keyword" clearable placeholder="关键字" />
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
        <el-table-column label="科室" min-width="120">
          <template #default="{ row }">{{ displayText(row.dept) }}</template>
        </el-table-column>
        <el-table-column label="就诊次" width="90">
          <template #default="{ row }">{{ displayText(row.visit_number) }}</template>
        </el-table-column>
        <el-table-column label="风险" width="100">
          <template #default="{ row }"><RiskTag :value="row.severity" /></template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }">{{ displayText(row.status) }}</template>
        </el-table-column>
        <el-table-column label="最近记录" width="100">
          <template #default="{ row }">{{ displayText(row.latest_log_id) }}</template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.updated_at as string) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>
    </DataTableShell>

    <DetailDrawer v-model="detailVisible" title="患者质控详情" :loading="detailLoading" size="640px">
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
