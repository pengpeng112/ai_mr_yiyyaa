<template>
  <section class="tl-page">
    <el-card shadow="never">
      <template #header>
        <div class="tl-card-header">
          <div>
            <h3 class="tl-title">病历时效事件台账</h3>
            <p class="tl-subtitle">
              规则命中事件（只读）；列表与详情受科室可见性约束；状态流转与通知动作全量留痕。
            </p>
          </div>
          <el-button size="small" @click="loadEvents">刷新</el-button>
        </div>
      </template>

      <el-form inline size="small" class="tl-filters">
        <el-form-item label="科室">
          <el-select
            v-model="filters.dept"
            filterable
            clearable
            placeholder="全部可见科室"
            style="width: 200px"
          >
            <el-option
              v-for="dept in departments"
              :key="dept.id"
              :label="dept.code ? `${dept.code} ${dept.name}` : dept.name"
              :value="dept.code || dept.name"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="规则">
          <el-select v-model="filters.rule_code" filterable clearable placeholder="全部规则" style="width: 200px">
            <el-option v-for="rule in rules" :key="rule.rule_code" :label="`${rule.rule_code} ${rule.rule_name}`" :value="rule.rule_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 150px">
            <el-option
              v-for="status in dicts?.event_statuses || []"
              :key="status"
              :label="eventStatusLabel(status)"
              :value="status"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="患者ID">
          <el-input v-model="filters.patient_id" clearable placeholder="精确匹配" style="width: 140px" />
        </el-form-item>
        <el-form-item label="起算日期">
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始"
            end-placeholder="结束"
            style="width: 240px"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
        </el-form-item>
      </el-form>

      <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

      <el-table v-loading="loading" :data="events" size="small" border>
        <el-table-column prop="event_uid" label="事件唯一号" min-width="220" show-overflow-tooltip />
        <el-table-column prop="rule_code" label="规则" width="150" />
        <el-table-column prop="patient_id" label="患者ID" width="100" />
        <el-table-column prop="visit_id" label="住院次" width="70" />
        <el-table-column prop="dept_code" label="科室编码" width="100" />
        <el-table-column prop="responsible_doctor_id" label="责任医生" width="100" />
        <el-table-column label="起算 T0" width="150">
          <template #default="{ row }">{{ fmtTime(row.t0) }}</template>
        </el-table-column>
        <el-table-column label="截止" width="150">
          <template #default="{ row }">{{ fmtTime(row.deadline) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="statusTagType(row.status)">{{ eventStatusLabel(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="超时(分)" width="85">
          <template #default="{ row }">{{ row.overdue_minutes ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" text data-testid="event-detail" @click="openDetail(row as TlEvent)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="tl-pagination">
        <el-pagination
          v-model:current-page="page"
          :page-size="limit"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="loadEvents"
        />
      </div>
    </el-card>

    <el-dialog v-model="detailVisible" title="事件详情（状态历史 + 动作日志）" width="min(94vw, 880px)">
      <template v-if="detail">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="事件唯一号" :span="2">{{ detail.event_uid }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ eventStatusLabel(detail.status) }}</el-descriptions-item>
          <el-descriptions-item label="规则">{{ detail.rule_code }}</el-descriptions-item>
          <el-descriptions-item label="患者/住院次">{{ detail.patient_id }} / {{ detail.visit_id }}</el-descriptions-item>
          <el-descriptions-item label="科室">{{ detail.dept_code || '—' }}</el-descriptions-item>
          <el-descriptions-item label="起算 T0">{{ fmtTime(detail.t0) }}</el-descriptions-item>
          <el-descriptions-item label="截止">{{ fmtTime(detail.deadline) }}</el-descriptions-item>
          <el-descriptions-item label="完成时间">{{ fmtTime(detail.completed_at) }}</el-descriptions-item>
          <el-descriptions-item label="超时(分)">{{ detail.overdue_minutes ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="责任医生">{{ detail.responsible_doctor_id || '—' }}</el-descriptions-item>
        </el-descriptions>

        <h4 class="tl-section-title">状态流转历史</h4>
        <el-table :data="detail.history" size="small" border max-height="200">
          <el-table-column label="从" width="120">
            <template #default="{ row }">{{ row.from_status ? eventStatusLabel(row.from_status) : '（新建）' }}</template>
          </el-table-column>
          <el-table-column label="至" width="120">
            <template #default="{ row }">{{ eventStatusLabel(row.to_status) }}</template>
          </el-table-column>
          <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
          <el-table-column prop="scan_run_id" label="扫描批次" width="90" />
          <el-table-column prop="created_at" label="时间" min-width="150" />
        </el-table>

        <h4 class="tl-section-title">动作日志（通知/写入全量留痕）</h4>
        <el-table :data="detail.action_logs" size="small" border max-height="200">
          <el-table-column prop="action_type" label="动作" width="170" />
          <el-table-column prop="mode" label="模式" width="90" />
          <el-table-column prop="target" label="目标" width="120" />
          <el-table-column prop="operator" label="操作人" width="110" />
          <el-table-column prop="result" label="结果" min-width="180" show-overflow-tooltip />
          <el-table-column prop="created_at" label="时间" min-width="150" />
        </el-table>
      </template>
      <div v-else-if="detailLoading" v-loading="true" class="tl-detail-loading" />
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
// T6 事件台账页（只读）：过滤条件与 GET /timeliness/events 参数一一对应；
// dateRange 拆为 date_from / date_to（后端对纯日期 date_to 取当天 23:59:59 含当日）。
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  fetchDepartmentsApi,
  fetchTimelinessEventApi,
  fetchTimelinessEventsApi,
  fetchTimelinessDictsApi,
  fetchTimelinessRulesApi,
} from './api'
import { eventStatusLabel, type DepartmentOption, type TlDicts, type TlEvent, type TlEventDetail, type TlRule } from './types'

const loading = ref(false)
const loadError = ref('')
const events = ref<TlEvent[]>([])
const total = ref(0)
const page = ref(1)
const limit = 50

const dicts = ref<TlDicts | null>(null)
const rules = ref<TlRule[]>([])
const departments = ref<DepartmentOption[]>([])

const filters = reactive({
  dept: '',
  rule_code: '',
  status: '',
  patient_id: '',
})
const dateRange = ref<[string, string] | null>(null)

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref<TlEventDetail | null>(null)

onMounted(async () => {
  await Promise.allSettled([
    fetchTimelinessDictsApi().then((res) => (dicts.value = res)),
    fetchTimelinessRulesApi().then((res) => (rules.value = res.items)),
    fetchDepartmentsApi().then((res) => (departments.value = res)),
  ])
  await loadEvents()
})

function search(): void {
  page.value = 1
  loadEvents()
}

async function loadEvents(): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const res = await fetchTimelinessEventsApi({
      page: page.value,
      limit,
      dept: filters.dept || undefined,
      rule_code: filters.rule_code || undefined,
      status: filters.status || undefined,
      patient_id: filters.patient_id || undefined,
      date_from: dateRange.value?.[0] || undefined,
      date_to: dateRange.value?.[1] || undefined,
    })
    events.value = res.items
    total.value = res.total
  } catch (exc) {
    loadError.value = exc instanceof Error ? exc.message : '事件台账加载失败'
  } finally {
    loading.value = false
  }
}

async function openDetail(row: TlEvent): Promise<void> {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await fetchTimelinessEventApi(row.id)
  } catch (exc) {
    ElMessage.error(exc instanceof Error ? exc.message : '事件详情加载失败')
  } finally {
    detailLoading.value = false
  }
}

function fmtTime(value: string | null): string {
  return value ? value.replace('T', ' ').slice(0, 19) : '—'
}

function statusTagType(status: string): 'danger' | 'warning' | 'success' | 'info' {
  if (status === 'OVERDUE' || status === 'COMPLETED_LATE') return 'danger'
  if (status === 'WARNING' || status === 'APPLYING') return 'warning'
  if (status === 'COMPLETED_ON_TIME' || status === 'APPROVED' || status === 'EXEMPT') return 'success'
  return 'info'
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
.tl-title {
  margin: 0;
  font-size: 15px;
}
.tl-subtitle {
  margin: 4px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.tl-filters {
  margin-bottom: 4px;
}
.tl-alert {
  margin-bottom: 10px;
}
.tl-pagination {
  margin-top: 10px;
  display: flex;
  justify-content: flex-end;
}
.tl-section-title {
  margin: 14px 0 6px;
  font-size: 13px;
}
.tl-detail-loading {
  min-height: 120px;
}
</style>
