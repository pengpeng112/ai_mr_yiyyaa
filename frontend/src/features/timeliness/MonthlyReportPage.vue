<template>
  <section class="tl-page">
    <el-card shadow="never">
      <template #header>
        <div class="tl-card-header">
          <div>
            <h3 class="tl-title">病历时效月度统计</h3>
            <p class="tl-subtitle">
              按科室 × 责任医生聚合当月事件（口径与台账一致，受科室可见性约束）；导出写导出审计。
            </p>
          </div>
          <div class="tl-actions">
            <el-date-picker
              v-model="monthValue"
              type="month"
              value-format="YYYY-MM"
              placeholder="选择月份"
              :clearable="false"
              style="width: 140px"
              @change="loadStats"
            />
            <el-button size="small" type="primary" :loading="exporting" data-testid="export-monthly" @click="exportCsv">
              导出 CSV
            </el-button>
          </div>
        </div>
      </template>

      <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

      <el-row v-if="stats" :gutter="8" class="tl-totals">
        <el-col v-for="card in totalCards" :key="card.label" :span="4">
          <el-card shadow="never" class="tl-total-card">
            <div class="tl-total-value" :class="card.cls">{{ card.value }}</div>
            <div class="tl-total-label">{{ card.label }}</div>
          </el-card>
        </el-col>
        <el-col :span="4">
          <el-card shadow="never" class="tl-total-card">
            <div class="tl-total-value">{{ stats.month }}</div>
            <div class="tl-total-label">统计月份</div>
          </el-card>
        </el-col>
      </el-row>

      <el-table v-loading="loading" :data="stats?.rows || []" size="small" border>
        <el-table-column prop="dept_code" label="科室编码" min-width="110" />
        <el-table-column prop="responsible_doctor_id" label="责任医生" min-width="110">
          <template #default="{ row }">{{ row.responsible_doctor_id || '（未指定）' }}</template>
        </el-table-column>
        <el-table-column prop="total" label="事件总数" width="90" sortable />
        <el-table-column prop="completed_on_time" label="按时完成" width="90" sortable />
        <el-table-column prop="completed_late" label="超时完成" width="90" sortable />
        <el-table-column prop="overdue" label="超时未完成" width="100" sortable />
        <el-table-column prop="pending" label="未到期" width="85" sortable />
        <el-table-column prop="warning" label="预警中" width="85" sortable />
        <el-table-column prop="other" label="其他状态" width="90" sortable />
      </el-table>
      <p v-if="stats && stats.rows.length === 0" class="tl-subtitle">当月无事件数据（或当前账号无可见科室）。</p>
    </el-card>
  </section>
</template>

<script setup lang="ts">
// T6 月度统计页（只读 + 导出）：GET /stats/monthly?month=YYYY-MM；
// 导出走 apiDownload（blob），无 timeliness_export 权限时后端 403 → 提示降级。
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { exportMonthlyApi, fetchMonthlyStatsApi } from './api'
import type { MonthlyStats } from './types'

const loading = ref(false)
const exporting = ref(false)
const loadError = ref('')
const stats = ref<MonthlyStats | null>(null)
const monthValue = ref(defaultMonth())

function defaultMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

const totalCards = computed(() => {
  const totals = stats.value?.totals
  if (!totals) return []
  return [
    { label: '事件总数', value: totals.total, cls: '' },
    { label: '按时完成', value: totals.completed_on_time, cls: 'is-ok' },
    { label: '超时完成', value: totals.completed_late, cls: 'is-bad' },
    { label: '超时未完成', value: totals.overdue, cls: 'is-bad' },
    { label: '未到期', value: totals.pending, cls: '' },
    { label: '预警中', value: totals.warning, cls: 'is-warn' },
  ]
})

onMounted(loadStats)

async function loadStats(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    stats.value = await fetchMonthlyStatsApi(monthValue.value)
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '月度统计加载失败'
  } finally {
    loading.value = false
  }
}

async function exportCsv(): Promise<void> {
  exporting.value = true
  try {
    await exportMonthlyApi(monthValue.value)
    ElMessage.success(`已导出 ${monthValue.value} 月度统计 CSV`)
  } catch (exc) {
    const message = exc instanceof Error ? exc.message : '导出失败'
    ElMessage.error(message.includes('403') ? '无导出权限（timeliness_export）' : message)
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
.tl-page {
  padding: 4px;
}
.tl-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.tl-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.tl-title {
  margin: 0;
  font-size: 15px;
}
.tl-subtitle {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tl-alert {
  margin-bottom: 10px;
}
.tl-totals {
  margin-bottom: 10px;
}
.tl-total-card {
  text-align: center;
}
.tl-total-value {
  font-size: 20px;
  font-weight: 600;
}
.tl-total-value.is-bad {
  color: var(--el-color-danger);
}
.tl-total-value.is-warn {
  color: var(--el-color-warning);
}
.tl-total-value.is-ok {
  color: var(--el-color-success);
}
.tl-total-label {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 2px;
}
</style>
