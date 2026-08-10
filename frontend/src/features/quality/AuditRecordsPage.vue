<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import FilterPanel from '@/components/base/FilterPanel.vue'
import DataTableShell from '@/components/base/DataTableShell.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import { apiDownload, apiGet, triggerBrowserDownload } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import type { PaginatedResponse, PushLogListItem } from '@/api/types'
import { displayText, formatDateTime } from '@/utils/format'
import { ElMessage } from 'element-plus'

const loading = ref(false)
const error = ref('')
const items = ref<PushLogListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({
  status: '',
  severity: '',
  patient_id: '',
  dept: '',
  date_from: '',
  date_to: '',
  audit_type_code: '',
  skip_reason: '',
})

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<Record<string, unknown> | null>(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet<PaginatedResponse<PushLogListItem>>('/logs', {
      params: {
        page: page.value,
        limit: pageSize.value,
        status: filters.status || undefined,
        severity: filters.severity || undefined,
        patient_id: filters.patient_id || undefined,
        dept: filters.dept || undefined,
        date_from: filters.date_from || undefined,
        date_to: filters.date_to || undefined,
        audit_type_code: filters.audit_type_code || undefined,
        skip_reason: filters.skip_reason || undefined,
      },
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    error.value = toUserMessage(e, '加载质控记录失败')
  } finally {
    loading.value = false
  }
}

function reset() {
  filters.status = ''
  filters.severity = ''
  filters.patient_id = ''
  filters.dept = ''
  filters.date_from = ''
  filters.date_to = ''
  filters.audit_type_code = ''
  filters.skip_reason = ''
  page.value = 1
  void load()
}

function onSearch() {
  page.value = 1
  void load()
}

async function openDetail(row: PushLogListItem) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = (await apiGet(`/logs/${row.id}`)) as Record<string, unknown>
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载详情失败'))
  } finally {
    detailLoading.value = false
  }
}

async function exportCsv() {
  try {
    const { blob, filename } = await apiDownload('/logs/export/csv', {
      params: { ...filters, page: 1, limit: 5000 },
    })
    triggerBrowserDownload(blob, filename)
    ElMessage.success('导出已开始（后端会记录导出审计）')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '导出失败'))
  }
}

function openLegacyDetail(row: PushLogListItem) {
  // 独立日志详情页保留
  window.open(`/log_detail.html?id=${row.id}`, '_blank', 'noopener')
}

onMounted(() => {
  void load()
})
</script>

<template>
  <div class="page-audit">
    <PageHeader title="质控记录" description="推送/质控结果列表。兼容历史 NULL；导出保留审计。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button type="primary" @click="exportCsv">导出 CSV</el-button>
      </template>
    </PageHeader>

    <FilterPanel @search="onSearch" @reset="reset">
      <el-select v-model="filters.status" clearable placeholder="状态">
        <el-option label="成功" value="success" />
        <el-option label="失败" value="failed" />
        <el-option label="跳过" value="skipped" />
      </el-select>
      <el-select v-model="filters.severity" clearable placeholder="严重度">
        <el-option label="高危" value="high" />
        <el-option label="中危" value="medium" />
        <el-option label="低危" value="low" />
      </el-select>
      <el-input v-model="filters.dept" clearable placeholder="科室" />
      <el-input v-model="filters.audit_type_code" clearable placeholder="审计类型 code" />
      <template #more>
        <el-input v-model="filters.patient_id" clearable placeholder="患者 ID（仅筛选，勿写入截图）" />
        <el-input v-model="filters.date_from" clearable placeholder="开始日期 YYYY-MM-DD" />
        <el-input v-model="filters.date_to" clearable placeholder="结束日期 YYYY-MM-DD" />
        <el-input v-model="filters.skip_reason" clearable placeholder="跳过原因" />
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
      <el-table v-loading="loading" :data="items" stripe border size="small" style="width: 100%">
        <el-table-column prop="id" label="ID" width="80" />
        <el-table-column label="科室" min-width="120">
          <template #default="{ row }">{{ displayText(row.dept) }}</template>
        </el-table-column>
        <el-table-column label="类型" min-width="140">
          <template #default="{ row }">{{ displayText(row.audit_type_code) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }"><StatusTag :value="row.status" /></template>
        </el-table-column>
        <el-table-column label="风险" width="100">
          <template #default="{ row }"><RiskTag :value="row.severity" /></template>
        </el-table-column>
        <el-table-column label="跳过原因" min-width="120">
          <template #default="{ row }">{{ displayText(row.skip_reason) }}</template>
        </el-table-column>
        <el-table-column label="时间" min-width="160">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openDetail(row as PushLogListItem)">详情</el-button>
            <el-button link @click="openLegacyDetail(row as PushLogListItem)">独立页</el-button>
          </template>
        </el-table-column>
      </el-table>
    </DataTableShell>

    <DetailDrawer v-model="detailVisible" title="质控记录详情" :loading="detailLoading">
      <el-descriptions v-if="detail" :column="1" border size="small">
        <el-descriptions-item label="ID">{{ detail.id }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ displayText(detail.status) }}</el-descriptions-item>
        <el-descriptions-item label="严重度">{{ displayText(detail.severity) }}</el-descriptions-item>
        <el-descriptions-item label="科室">{{ displayText(detail.dept) }}</el-descriptions-item>
        <el-descriptions-item label="审计类型">{{ displayText(detail.audit_type_code) }}</el-descriptions-item>
        <el-descriptions-item label="reviewed_flag">{{ displayText(detail.reviewed_flag) }}</el-descriptions-item>
        <el-descriptions-item label="manual_override">{{ displayText(detail.manual_override) }}</el-descriptions-item>
        <el-descriptions-item label="skip_reason">{{ displayText(detail.skip_reason) }}</el-descriptions-item>
        <el-descriptions-item label="source_record_key">{{ displayText(detail.source_record_key) }}</el-descriptions-item>
        <el-descriptions-item label="superseded_by">{{ displayText(detail.superseded_by) }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        class="mt"
        type="info"
        :closable="false"
        title="脱敏说明"
        description="详情展示以后端脱敏结果为准；不在此展开 request_json/response_json 原文。"
      />
    </DetailDrawer>
  </div>
</template>

<style scoped>
.mt {
  margin-top: 12px;
}
</style>
