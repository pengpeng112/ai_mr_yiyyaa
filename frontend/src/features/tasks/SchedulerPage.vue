<script setup lang="ts">
import { onMounted, reactive, ref, computed } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

interface HistoryRow {
  run_time: string
  trigger_type: string
  query_date: string
  audit_type_code: string
  audit_run_mode: string
  total_records: number
  success_count: number
  failed_count: number
  duration_seconds: number
  status: string
  error_code: string
}

interface RunLockInfo {
  status?: string
  owner_id?: string
  acquired_at?: string | null
  heartbeat_at?: string | null
  heartbeat_age_seconds?: number | null
  stale_threshold_seconds?: number
  is_stale?: boolean
}

const loading = ref(false)
const statusData = ref<Record<string, unknown>>({})
const history = ref<HistoryRow[]>([])
const historyTotal = ref(0)
const historyPage = ref(1)
const historyPageSize = ref(20)
const auditTypeOptions = ref<Array<{ value: string; label: string }>>([])
const deptCandidates = ref<string[]>([])

// 调度配置（daily + discharge）
function makeSchedState() {
  return reactive({
    enabled: false,
    schedule_mode: 'daily',
    daily_time: '10:00',
    interval_value: 30,
    cron: '0 10 * * *',
    audit_type_codes: [] as string[],
    dept_filter_text: '',
  })
}
const dailyCfg = makeSchedState()
const dischargeCfg = makeSchedState()
const savingDaily = ref(false)
const savingDischarge = ref(false)
const jobAction = ref('')

// 触发表单
const triggerForm = reactive({
  audit_run_mode: 'daily_increment',
  query_date: '',
  audit_type_codes: [] as string[],
  dept_filter_text: '',
})
const triggerLoading = ref(false)

// run-summary
const runSummaryQueryDate = ref('')
const runSummaryMode = ref('daily_increment')
const runSummaryLoading = ref(false)
const runSummary = ref<Record<string, unknown> | null>(null)

// runtime warnings
const runtimeWarnings = ref<Array<Record<string, unknown>>>([])

const hasDual = computed(() => !!((statusData.value as Record<string, unknown>).has_dual))
const schedulerRunning = computed(() => !!statusData.value.running)
const runLocks = computed<Array<{ name: string; label: string; info: RunLockInfo }>>(() => {
  const raw = (statusData.value.run_locks || {}) as Record<string, RunLockInfo>
  return [
    { name: 'daily_push', label: '每日增量', info: raw.daily_push || {} },
    { name: 'discharge_push', label: '出院终末', info: raw.discharge_push || {} },
  ]
})
const staleLocks = computed(() => runLocks.value.filter((item) => item.info.status === 'running' && item.info.is_stale))

function lockStatusText(info: RunLockInfo): string {
  if (info.status !== 'running') return '空闲'
  if (info.is_stale) return '心跳中断，等待安全接管'
  return '运行中'
}

function lockHeartbeatText(info: RunLockInfo): string {
  if (info.heartbeat_age_seconds === null || info.heartbeat_age_seconds === undefined) return '--'
  const seconds = Number(info.heartbeat_age_seconds)
  if (seconds < 60) return `${seconds} 秒前`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`
  return `${Math.floor(seconds / 3600)} 小时前`
}

const dailyModeLabel = computed(() => modeLabel(dailyCfg.schedule_mode))
const dischargeModeLabel = computed(() => modeLabel(dischargeCfg.schedule_mode))

function modeLabel(mode: string): string {
  const m: Record<string, string> = { daily: '每日', every_n_minutes: '每N分钟', every_n_hours: '每N小时', cron: 'Cron' }
  return m[mode] || mode
}

function successRate(row: Record<string, unknown>): string {
  const total = Number(row.total_records || 0)
  if (!total) return '-'
  return ((Number(row.success_count || 0) / total) * 100).toFixed(1) + '%'
}
function successRateType(row: Record<string, unknown>): 'success' | 'warning' | 'danger' | 'info' {
  const total = Number(row.total_records || 0)
  if (!total) return 'info'
  const r = Number(row.success_count || 0) / total
  return r >= 0.95 ? 'success' : r >= 0.8 ? 'warning' : 'danger'
}

function normalizeDeptList(text: string): string[] {
  return Array.from(new Set(
    text.split(/[\n,，;；]+/).map((s) => s.trim()).filter(Boolean)
  ))
}

function buildPayload(cfg: typeof dailyCfg, runMode: string): Record<string, unknown> {
  let cron = cfg.cron
  if (cfg.schedule_mode === 'daily') {
    const [h, m] = (cfg.daily_time || '10:00').split(':')
    cron = `${Number(m) || 0} ${Number(h) || 10} * * *`
  } else if (cfg.schedule_mode === 'every_n_minutes') {
    cron = `*/${cfg.interval_value || 30} * * * *`
  } else if (cfg.schedule_mode === 'every_n_hours') {
    cron = `0 */${cfg.interval_value || 1} * * *`
  }
  const depts = normalizeDeptList(cfg.dept_filter_text)
  return {
    enabled: cfg.enabled,
    cron,
    schedule_mode: cfg.schedule_mode,
    daily_time: cfg.daily_time,
    interval_value: cfg.interval_value,
    audit_run_mode: runMode,
    audit_type_codes: cfg.audit_type_codes.length ? cfg.audit_type_codes : null,
    dept_filter: depts.length ? depts : [],
  }
}

function applyConfig(cfg: typeof dailyCfg, data: Record<string, unknown>) {
  cfg.enabled = !!data.enabled
  cfg.schedule_mode = String(data.schedule_mode || 'daily')
  cfg.daily_time = String(data.daily_time || '10:00')
  cfg.interval_value = Number(data.interval_value || 30)
  cfg.cron = String(data.cron || '0 10 * * *')
  cfg.audit_type_codes = (data.audit_type_codes as string[]) || []
  cfg.dept_filter_text = Array.isArray(data.dept_filter) ? (data.dept_filter as string[]).join(', ') : ''
}

async function load() {
  loading.value = true
  try {
    const [status, hist, dailyData, dischargeData, auditTypes, depts] = await Promise.all([
      apiGet<Record<string, unknown>>('/scheduler/status').catch(() => ({})),
      apiGet<{ items?: HistoryRow[]; total?: number }>('/scheduler/history', { params: { page: 1, limit: historyPageSize.value } }).catch(() => ({ items: [], total: 0 })),
      apiGet<Record<string, unknown>>('/config/scheduler-daily').catch(() => ({})),
      hasDual.value ? apiGet<Record<string, unknown>>('/config/scheduler-discharge').catch(() => ({})) : Promise.resolve({}),
      apiGet<{ items?: Array<{ code: string; name: string }> }>('/audit-types/options').catch(() => ({ items: [] })),
      apiGet<{ items?: string[] }>('/config/departments/list').catch(() => ({ items: [] })),
    ])
    statusData.value = status
    history.value = hist.items || []
    historyTotal.value = hist.total || 0

    // 如果 status 返回 has_dual，重新加载 discharge
    if ((status as Record<string, unknown>).has_dual && !(dischargeData as Record<string, unknown>).enabled) {
      const d = await apiGet<Record<string, unknown>>('/config/scheduler-discharge').catch(() => ({}))
      applyConfig(dischargeCfg, d)
    } else {
      applyConfig(dischargeCfg, dischargeData)
    }
    applyConfig(dailyCfg, dailyData)

    auditTypeOptions.value = (auditTypes.items || []).map((a) => ({ value: a.code, label: a.name }))
    deptCandidates.value = (depts.items || []) as string[]

    // 默认 run-summary 用最近 history 的 query_date
    if (history.value.length && !runSummaryQueryDate.value) {
      runSummaryQueryDate.value = history.value[0].query_date
      void loadRunSummary()
    }
    void loadRuntimeWarnings()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载调度状态失败'))
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  try {
    const data = await apiGet<{ items?: HistoryRow[]; total?: number }>('/scheduler/history', {
      params: { page: historyPage.value, limit: historyPageSize.value },
    })
    history.value = data.items || []
    historyTotal.value = data.total || 0
  } catch { /* 静默 */ }
}

async function saveDaily() {
  savingDaily.value = true
  try {
    await apiPost('/config/scheduler-daily', buildPayload(dailyCfg, 'daily_increment'))
    ElMessage.success('每日增量配置已保存')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    savingDaily.value = false
  }
}

async function saveDischarge() {
  savingDischarge.value = true
  try {
    await apiPost('/config/scheduler-discharge', buildPayload(dischargeCfg, 'discharge_final'))
    ElMessage.success('出院终末配置已保存')
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    savingDischarge.value = false
  }
}

async function startJob(jobId: string) {
  if (jobAction.value) return
  try {
    await ElMessageBox.confirm(`确认启动 ${jobId}？将按现有配置执行，可能触发 Dify。`, '启动确认', { type: 'warning' })
    jobAction.value = jobId
    await apiPost(`/scheduler/start`, null, { params: { job_id: jobId } })
    ElMessage.success(`${jobId} 已启动`)
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '启动失败'))
  } finally {
    jobAction.value = ''
  }
}

async function stopJob(jobId: string) {
  if (jobAction.value) return
  try {
    await ElMessageBox.confirm(`确认停止 ${jobId}？`, '停止确认', { type: 'warning' })
    jobAction.value = jobId
    await apiPost(`/scheduler/stop`, null, { params: { job_id: jobId } })
    ElMessage.success(`${jobId} 已停止`)
    void load()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '停止失败'))
  } finally {
    jobAction.value = ''
  }
}

async function triggerNow() {
  if (triggerLoading.value) return
  try {
    const params: Record<string, string> = { audit_run_mode: triggerForm.audit_run_mode }
    if (triggerForm.query_date) params.query_date = triggerForm.query_date
    if (triggerForm.audit_type_codes.length) params.audit_type_codes = triggerForm.audit_type_codes.join(',')
    const depts = normalizeDeptList(triggerForm.dept_filter_text)
    if (depts.length) params.dept_filter = depts.join(',')
    await ElMessageBox.confirm(
      `确认立即触发 ${triggerForm.audit_run_mode}？${triggerForm.query_date ? '日期 ' + triggerForm.query_date : ''}，${triggerForm.audit_type_codes.length} 个类型。这可能调用 Dify。`,
      '触发确认', { type: 'warning' },
    )
    triggerLoading.value = true
    await apiPost('/scheduler/trigger', null, { params })
    ElMessage.success('触发已提交')
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(toUserMessage(e, '触发失败'))
  } finally {
    triggerLoading.value = false
  }
}

async function loadRunSummary() {
  if (!runSummaryQueryDate.value) return
  runSummaryLoading.value = true
  runSummary.value = null
  try {
    runSummary.value = await apiGet<Record<string, unknown>>('/scheduler/run-summary', {
      params: { query_date: runSummaryQueryDate.value, audit_run_mode: runSummaryMode.value },
    })
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载运行汇总失败'))
  } finally {
    runSummaryLoading.value = false
  }
}

async function loadRuntimeWarnings() {
  try {
    const data = await apiGet<{ warnings?: Array<Record<string, unknown>> }>('/config/runtime-summary')
    const all = data.warnings || []
    runtimeWarnings.value = all.filter((w) => {
      const path = String(w.path || w.code || '')
      return path.startsWith('scheduler_daily.') || path.startsWith('scheduler_discharge.') || path.includes('dept_filter')
    })
  } catch { /* 静默 */ }
}

const runSummaryRows = computed(() => {
  if (!runSummary.value) return []
  return (runSummary.value.items as Array<Record<string, unknown>>) || []
})
const runSummaryIncomplete = computed(() => runSummary.value?.incomplete as boolean || false)
const runSummaryTotals = computed(() => runSummary.value?.totals as Record<string, number> | undefined)

const warningGroups = computed(() => {
  const groups: Record<string, Array<Record<string, unknown>>> = { error: [], warning: [], info: [] }
  for (const w of runtimeWarnings.value) {
    const lv = String(w.level || 'info')
    if (groups[lv]) groups[lv].push(w)
  }
  return groups
})

onMounted(() => { void load() })
</script>

<template>
  <div class="page-scheduler">
    <PageHeader title="定时任务" description="每日增量/出院终末双调度，配置启停、手动触发与运行完整性。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <!-- 状态条 -->
    <div class="status-bar">
      <span class="status-item">调度器：<el-tag size="small" :type="schedulerRunning ? 'success' : 'info'">{{ schedulerRunning ? '运行中' : '已停用' }}</el-tag></span>
      <span class="status-item">每日增量：<el-tag size="small" :type="dailyCfg.enabled ? 'success' : 'info'">{{ dailyCfg.enabled ? dailyModeLabel : '未启用' }}</el-tag></span>
      <span v-if="hasDual" class="status-item">出院终末：<el-tag size="small" :type="dischargeCfg.enabled ? 'success' : 'info'">{{ dischargeCfg.enabled ? dischargeModeLabel : '未启用' }}</el-tag></span>
      <span v-if="statusData.next_run" class="status-item">下次运行：{{ formatDateTime(statusData.next_run as string) }}</span>
    </div>

    <el-alert
      v-if="staleLocks.length"
      type="error"
      :closable="false"
      show-icon
      class="lock-alert"
      :title="`${staleLocks.map((item) => item.label).join('、')}调度锁心跳已中断`"
      description="不要手工直接清锁；下一次同名任务会通过原子比较接管，并避免两个恢复者同时启动。"
    />
    <div class="lock-grid">
      <div v-for="item in runLocks" :key="item.name" class="lock-item" :class="{ 'is-stale': item.info.is_stale }">
        <span class="lock-name">{{ item.label }}运行锁</span>
        <el-tag size="small" :type="item.info.is_stale ? 'danger' : item.info.status === 'running' ? 'warning' : 'success'">
          {{ lockStatusText(item.info) }}
        </el-tag>
        <span class="lock-heartbeat">最近心跳：{{ lockHeartbeatText(item.info) }}</span>
      </div>
    </div>

    <!-- 双栏配置 -->
    <div class="cfg-grid">
      <!-- 每日增量 -->
      <el-card shadow="never" class="cfg-card">
        <div class="cfg-head">
          <span class="cfg-title">每日增量（daily_increment）</span>
          <div>
            <el-button v-if="!dailyCfg.enabled" size="small" type="success" :loading="jobAction === 'daily_push'" :disabled="!!jobAction" @click="startJob('daily_push')">启动</el-button>
            <el-button v-else size="small" type="danger" plain :loading="jobAction === 'daily_push'" :disabled="!!jobAction" @click="stopJob('daily_push')">停止</el-button>
          </div>
        </div>
        <div class="cfg-body">
          <div class="cfg-row">
            <label>启用</label>
            <el-switch v-model="dailyCfg.enabled" size="small" />
          </div>
          <div class="cfg-row">
            <label>调度模式</label>
            <el-radio-group v-model="dailyCfg.schedule_mode" size="small">
              <el-radio value="daily">每日</el-radio>
              <el-radio value="every_n_minutes">每N分钟</el-radio>
              <el-radio value="every_n_hours">每N小时</el-radio>
              <el-radio value="cron">Cron</el-radio>
            </el-radio-group>
          </div>
          <div v-if="dailyCfg.schedule_mode === 'daily'" class="cfg-row">
            <label>执行时间</label>
            <el-time-picker v-model="dailyCfg.daily_time" format="HH:mm" value-format="HH:mm" placeholder="时间" size="small" style="width: 100px" />
          </div>
          <div v-if="dailyCfg.schedule_mode === 'every_n_minutes'" class="cfg-row">
            <label>间隔(分钟)</label>
            <el-input-number v-model="dailyCfg.interval_value" :min="1" :max="59" size="small" />
          </div>
          <div v-if="dailyCfg.schedule_mode === 'every_n_hours'" class="cfg-row">
            <label>间隔(小时)</label>
            <el-input-number v-model="dailyCfg.interval_value" :min="1" :max="23" size="small" />
          </div>
          <div v-if="dailyCfg.schedule_mode === 'cron'" class="cfg-row">
            <label>Cron 表达式</label>
            <el-input v-model="dailyCfg.cron" size="small" style="width: 180px" placeholder="0 10 * * *" />
          </div>
          <div class="cfg-row">
            <label>审计类型</label>
            <el-select v-model="dailyCfg.audit_type_codes" multiple collapse-tags size="small" style="width: 100%" placeholder="留空用默认">
              <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
            </el-select>
          </div>
          <div class="cfg-row">
            <label>科室过滤</label>
            <el-input v-model="dailyCfg.dept_filter_text" size="small" placeholder="逗号分隔，留空为全部" />
          </div>
          <el-button size="small" type="primary" :loading="savingDaily" @click="saveDaily">保存配置</el-button>
        </div>
      </el-card>

      <!-- 出院终末 -->
      <el-card v-if="hasDual" shadow="never" class="cfg-card">
        <div class="cfg-head">
          <span class="cfg-title">出院终末（discharge_final）</span>
          <div>
            <el-button v-if="!dischargeCfg.enabled" size="small" type="success" :loading="jobAction === 'discharge_push'" :disabled="!!jobAction" @click="startJob('discharge_push')">启动</el-button>
            <el-button v-else size="small" type="danger" plain :loading="jobAction === 'discharge_push'" :disabled="!!jobAction" @click="stopJob('discharge_push')">停止</el-button>
          </div>
        </div>
        <div class="cfg-body">
          <div class="cfg-row"><label>启用</label><el-switch v-model="dischargeCfg.enabled" size="small" /></div>
          <div class="cfg-row">
            <label>执行时间</label>
            <el-time-picker v-model="dischargeCfg.daily_time" format="HH:mm" value-format="HH:mm" placeholder="时间" size="small" style="width: 100px" />
          </div>
          <div class="cfg-row">
            <label>审计类型</label>
            <el-select v-model="dischargeCfg.audit_type_codes" multiple collapse-tags size="small" style="width: 100%" placeholder="留空用默认">
              <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
            </el-select>
          </div>
          <div class="cfg-row">
            <label>科室过滤</label>
            <el-input v-model="dischargeCfg.dept_filter_text" size="small" placeholder="逗号分隔，留空为全部" />
          </div>
          <el-button size="small" type="primary" :loading="savingDischarge" @click="saveDischarge">保存配置</el-button>
        </div>
      </el-card>
    </div>

    <!-- 手动触发 -->
    <el-card shadow="never" class="section-card">
      <div class="section-title">手动触发</div>
      <div class="trigger-grid">
        <div class="cfg-row">
          <label>运行模式</label>
          <el-radio-group v-model="triggerForm.audit_run_mode" size="small">
            <el-radio value="daily_increment">每日增量</el-radio>
            <el-radio value="discharge_final">出院终末</el-radio>
          </el-radio-group>
        </div>
        <div class="cfg-row">
          <label>查询日期</label>
          <el-date-picker v-model="triggerForm.query_date" type="date" value-format="YYYY-MM-DD" placeholder="日期" size="small" style="width: 150px" />
        </div>
        <div class="cfg-row">
          <label>审计类型</label>
          <el-select v-model="triggerForm.audit_type_codes" multiple collapse-tags size="small" style="width: 250px" placeholder="留空为全部">
            <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </div>
        <div class="cfg-row">
          <label>科室过滤</label>
          <el-input v-model="triggerForm.dept_filter_text" size="small" style="width: 200px" placeholder="逗号分隔" />
        </div>
      </div>
      <el-button type="warning" :loading="triggerLoading" @click="triggerNow" class="mt-sm">立即触发</el-button>
    </el-card>

    <!-- 执行历史 -->
    <el-card shadow="never" class="section-card">
      <div class="section-title">执行历史</div>
      <el-table :data="history" stripe border size="small" style="width: 100%">
        <el-table-column label="执行时间" width="135"><template #default="{ row }">{{ formatDateTime(row.run_time) }}</template></el-table-column>
        <el-table-column label="触发" width="60"><template #default="{ row }">{{ row.trigger_type === 'manual' ? '手动' : '自动' }}</template></el-table-column>
        <el-table-column prop="query_date" label="查询日期" width="100" />
        <el-table-column prop="audit_type_code" label="类型" width="140" show-overflow-tooltip />
        <el-table-column prop="total_records" label="总数" width="55" align="center" />
        <el-table-column label="成功" width="55" align="center"><template #default="{ row }"><span style="color: var(--el-color-success)">{{ row.success_count }}</span></template></el-table-column>
        <el-table-column label="失败" width="55" align="center"><template #default="{ row }"><span :style="row.failed_count > 0 ? 'color: var(--el-color-danger)' : ''">{{ row.failed_count }}</span></template></el-table-column>
        <el-table-column label="成功率" width="70" align="center"><template #default="{ row }"><el-tag size="small" :type="successRateType(row)">{{ successRate(row) }}</el-tag></template></el-table-column>
        <el-table-column prop="duration_seconds" label="耗时" width="60" align="center"><template #default="{ row }">{{ row.duration_seconds }}s</template></el-table-column>
        <el-table-column label="状态" width="80"><template #default="{ row }"><StatusTag :value="row.status" /></template></el-table-column>
        <el-table-column prop="error_code" label="错误码" width="120" show-overflow-tooltip />
      </el-table>
      <el-pagination v-model:current-page="historyPage" v-model:page-size="historyPageSize" :total="historyTotal" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="mt-sm" @current-change="loadHistory" @size-change="() => { historyPage = 1; loadHistory() }" />
    </el-card>

    <!-- 运行完整性 -->
    <el-card shadow="never" class="section-card">
      <div class="section-title">运行完整性</div>
      <div class="rs-controls">
        <el-date-picker v-model="runSummaryQueryDate" type="date" value-format="YYYY-MM-DD" placeholder="查询日期" size="small" style="width: 140px" />
        <el-radio-group v-model="runSummaryMode" size="small">
          <el-radio value="daily_increment">每日增量</el-radio>
          <el-radio value="discharge_final">出院终末</el-radio>
        </el-radio-group>
        <el-button size="small" :loading="runSummaryLoading" @click="loadRunSummary">查询</el-button>
      </div>
      <el-alert v-if="runSummaryIncomplete" type="error" :closable="false" show-icon class="mt-sm" title="存在不完整的运行记录" description="部分审计类型可能未正常完成或落库前失败，请核查历史和日志。" />
      <div v-if="runSummaryTotals" class="rs-totals mt-sm">
        <span>质控可用 <b>{{ runSummaryTotals.qc_usable || 0 }}</b></span>
        <span>传输成功 <b>{{ runSummaryTotals.transport_success || 0 }}</b></span>
        <span>解析失败 <b>{{ runSummaryTotals.parse_failed || 0 }}</b></span>
      </div>
      <el-table v-if="runSummaryRows.length" :data="runSummaryRows" border size="small" class="mt-sm" style="width: 100%">
        <el-table-column prop="audit_type_code" label="类型" width="140" show-overflow-tooltip />
        <el-table-column label="历史状态" width="80"><template #default="{ row }"><StatusTag :value="String(row.history_status || '')" /></template></el-table-column>
        <el-table-column prop="candidate_total" label="候选" width="60" align="center" />
        <el-table-column prop="transport_success" label="传输成功" width="70" align="center" />
        <el-table-column prop="qc_usable" label="质控可用" width="70" align="center" />
        <el-table-column prop="parse_failed" label="解析失败" width="70" align="center" />
        <el-table-column prop="high" label="高危" width="55" align="center" />
      </el-table>
    </el-card>

    <!-- 运行时告警 -->
    <el-card v-if="runtimeWarnings.length" shadow="never" class="section-card">
      <div class="section-title">调度配置告警</div>
      <el-alert v-for="(w, i) in warningGroups.error" :key="'e'+i" type="error" :closable="false" show-icon class="mt-sm">
        <template #title>{{ w.message }}</template>
        <template #default><span class="warn-path">{{ w.code }} · {{ w.path }}</span></template>
      </el-alert>
      <el-alert v-for="(w, i) in warningGroups.warning" :key="'w'+i" type="warning" :closable="false" show-icon class="mt-sm">
        <template #title>{{ w.message }}</template>
        <template #default><span class="warn-path">{{ w.code }} · {{ w.path }}</span></template>
      </el-alert>
      <el-alert v-for="(w, i) in warningGroups.info" :key="'i'+i" type="info" :closable="false" show-icon class="mt-sm">
        <template #title>{{ w.message }}</template>
      </el-alert>
    </el-card>
  </div>
</template>

<style scoped>
.status-bar { display: flex; gap: 16px; margin-bottom: 12px; padding: 8px 12px; background: var(--el-fill-color-light); border-radius: 8px; flex-wrap: wrap; align-items: center; }
.status-item { font-size: 13px; color: var(--el-text-color-secondary); display: flex; align-items: center; gap: 4px; }
.lock-alert { margin-bottom: 10px; }
.lock-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.lock-item { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-extra-light); }
.lock-item.is-stale { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); }
.lock-name { font-size: 13px; font-weight: 600; }
.lock-heartbeat { margin-left: auto; color: var(--el-text-color-secondary); font-size: 12px; }
.cfg-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 12px; margin-bottom: 12px; }
.cfg-card { border-radius: 10px; }
.cfg-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.cfg-title { font-size: 14px; font-weight: 600; }
.cfg-body { display: flex; flex-direction: column; gap: 8px; }
.cfg-row { display: flex; align-items: center; gap: 8px; }
.cfg-row label { font-size: 12px; color: var(--el-text-color-secondary); min-width: 70px; flex-shrink: 0; }
.section-card { margin-bottom: 12px; border-radius: 10px; }
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.trigger-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 8px; }
.rs-controls { display: flex; gap: 8px; align-items: center; }
.rs-totals { display: flex; gap: 16px; font-size: 13px; }
.rs-totals b { margin-left: 4px; font-size: 15px; }
.mt-sm { margin-top: 8px; }
.warn-path { font-size: 11px; color: var(--el-text-color-disabled); font-family: monospace; }
@media (max-width: 700px) {
  .lock-grid { grid-template-columns: 1fr; }
  .lock-item { align-items: flex-start; flex-wrap: wrap; }
  .lock-heartbeat { width: 100%; margin-left: 0; }
}
</style>
