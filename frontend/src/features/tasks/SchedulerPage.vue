<template>
  <div class="page-scheduler">
    <PageHeader title="定时任务" description="每日增量/出院终末双调度，配置启停、手动触发、诊断可视化与运行完整性。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </template>
    </PageHeader>

    <!-- WP09：SummaryStrip 四状态卡 -->
    <SummaryStrip :items="statusCards" :loading="loading" />

    <!-- 运行锁警示（保留 046 ST-003 语义） -->
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

    <el-tabs v-model="activeTab" class="sched-tabs">
      <!-- ── 页签 1：每日在院质控 ── -->
      <el-tab-pane label="每日在院质控" name="daily">
        <div class="sched-grid">
          <el-card shadow="never" class="cfg-card">
            <div class="cfg-head">
              <span class="cfg-title">每日增量配置（daily_increment）</span>
              <div>
                <el-button v-if="!dailyCfg.enabled" size="small" type="success" :loading="jobAction === 'daily_push'" :disabled="!!jobAction" @click="startJob('daily_push')">启动</el-button>
                <el-button v-else size="small" type="danger" plain :loading="jobAction === 'daily_push'" :disabled="!!jobAction" @click="stopJob('daily_push')">停止</el-button>
              </div>
            </div>
            <div class="cfg-body">
              <div class="cfg-row"><label>启用</label><el-switch v-model="dailyCfg.enabled" size="small" /></div>
              <div class="cfg-row">
                <label>频率</label>
                <el-radio-group v-model="dailyCfg.schedule_mode" size="small">
                  <el-radio value="every_n_minutes">每 10/30 分钟</el-radio>
                  <el-radio value="daily">每天定时</el-radio>
                  <el-radio value="every_n_hours">每 N 小时</el-radio>
                  <el-radio value="cron">自定义 Cron</el-radio>
                </el-radio-group>
              </div>
              <div v-if="dailyCfg.schedule_mode === 'every_n_minutes'" class="cfg-row">
                <label>间隔(分钟)</label>
                <el-select v-model="dailyCfg.interval_value" size="small" style="width: 120px">
                  <el-option :value="10" label="每 10 分钟" />
                  <el-option :value="30" label="每 30 分钟" />
                </el-select>
              </div>
              <div v-if="dailyCfg.schedule_mode === 'daily'" class="cfg-row">
                <label>执行时间</label>
                <el-time-picker v-model="dailyCfg.daily_time" format="HH:mm" value-format="HH:mm" placeholder="时间" size="small" style="width: 120px" />
              </div>
              <div v-if="dailyCfg.schedule_mode === 'every_n_hours'" class="cfg-row">
                <label>间隔(小时)</label>
                <el-input-number v-model="dailyCfg.interval_value" :min="1" :max="23" size="small" />
              </div>
              <div v-if="dailyCfg.schedule_mode === 'cron'" class="cfg-row">
                <label>Cron 表达式</label>
                <el-input v-model="dailyCfg.cron" size="small" style="width: 200px" placeholder="0 10 * * *" />
                <span class="cfg-hint">5 段 cron（分 时 日 月 周）</span>
              </div>
              <div class="cfg-row">
                <label>查询日期偏移</label>
                <span class="cfg-hint">每日任务按系统调度日期取数（调度器内部处理）；出院终末按出院日期。</span>
              </div>
              <div class="cfg-row">
                <label>质控类型</label>
                <el-select v-model="dailyCfg.audit_type_codes" multiple collapse-tags collapse-tags-tooltip filterable size="small" style="width: 100%" placeholder="留空用默认类型">
                  <el-option v-for="a in auditTypeOptions" :key="a.value" :label="`${a.label}（${a.value}）`" :value="a.value" />
                </el-select>
              </div>
              <div class="cfg-row">
                <label>科室范围</label>
                <el-select
                  v-model="dailyDeptSelected"
                  multiple
                  filterable
                  clearable
                  collapse-tags
                  collapse-tags-tooltip
                  allow-create
                  default-first-option
                  size="small"
                  style="width: 100%"
                  placeholder="全部科室（可搜索/自定义）"
                >
                  <el-option v-for="name in deptCandidates" :key="name" :label="name" :value="name" />
                </el-select>
              </div>
              <div class="cfg-row">
                <label>并发数</label>
                <span class="cfg-hint">—（调度接口暂未开放 max_workers 并发参数）</span>
              </div>
              <el-button size="small" type="primary" :loading="savingDaily" @click="saveDaily">保存每日配置</el-button>
            </div>
          </el-card>

          <el-card shadow="never" class="cfg-card">
            <div class="cfg-head"><span class="cfg-title">立即执行一次（手动触发）</span></div>
            <div class="cfg-body">
              <div class="cfg-row">
                <label>运行模式</label>
                <el-radio-group v-model="triggerForm.audit_run_mode" size="small">
                  <el-radio value="daily_increment">每日增量</el-radio>
                  <el-radio value="discharge_final">出院终末</el-radio>
                </el-radio-group>
              </div>
              <div class="cfg-row">
                <label>查询日期</label>
                <el-date-picker v-model="triggerForm.query_date" type="date" value-format="YYYY-MM-DD" placeholder="留空=今天" size="small" style="width: 150px" />
              </div>
              <div class="cfg-row">
                <label>审计类型</label>
                <el-select v-model="triggerForm.audit_type_codes" multiple collapse-tags size="small" style="width: 100%" placeholder="留空为全部">
                  <el-option v-for="a in auditTypeOptions" :key="a.value" :label="a.label" :value="a.value" />
                </el-select>
              </div>
              <div class="cfg-row">
                <label>科室过滤</label>
                <el-input v-model="triggerForm.dept_filter_text" size="small" style="width: 100%" placeholder="逗号分隔" />
              </div>
              <el-button type="warning" :loading="triggerLoading" @click="triggerNow">立即触发</el-button>
              <el-divider content-position="left">最近一次执行</el-divider>
              <template v-if="statusData.last_run">
                <div class="cfg-row"><label>完成时间</label><span>{{ formatDateTime((statusData.last_run as AnyRecord).finished_at) || '—' }}</span></div>
                <div class="cfg-row"><label>状态</label><StatusTag :value="String((statusData.last_run as AnyRecord).status || '')" /></div>
                <div v-if="(statusData.last_run as AnyRecord).completeness_hint === 'needs_run_summary'" class="cfg-hint">完整性提示：需在「执行历史」页签查询运行汇总。</div>
              </template>
              <p v-else class="cfg-hint">暂无执行记录。</p>
            </div>
          </el-card>
        </div>

        <!-- 遗留单任务配置折叠 -->
        <el-collapse v-if="hasDual" class="legacy-collapse">
          <el-collapse-item name="legacy">
            <template #title><span class="legacy-title">旧版单任务配置（已启用双调度，旧配置不生效）</span></template>
            <el-alert type="info" :closable="false" show-icon class="mt-sm"
              title="已启用双调度，旧版单任务配置不生效。" />
            <el-descriptions :column="2" border size="small" class="mt-sm">
              <el-descriptions-item label="启用">{{ (statusData.legacy as AnyRecord)?.enabled ? '是' : '否' }}</el-descriptions-item>
              <el-descriptions-item label="调度模式">{{ modeLabel(String((statusData.legacy as AnyRecord)?.schedule_mode || '')) }}</el-descriptions-item>
              <el-descriptions-item label="执行时间">{{ (statusData.legacy as AnyRecord)?.daily_time || '—' }}</el-descriptions-item>
              <el-descriptions-item label="Cron">{{ (statusData.legacy as AnyRecord)?.cron || '—' }}</el-descriptions-item>
            </el-descriptions>
          </el-collapse-item>
        </el-collapse>
      </el-tab-pane>

      <!-- ── 页签 2：出院终末质控 ── -->
      <el-tab-pane label="出院终末质控" name="discharge">
        <template v-if="hasDual">
          <!-- WP09：discharge_effectiveness 诊断卡（035/RP2 契约保留） -->
          <div class="eff-card">
            <el-alert
              v-if="effectivenessOk"
              type="success"
              :closable="false"
              show-icon
              title="所选质控类型均支持出院终末路径"
            />
            <el-alert
              v-for="(w, i) in effectivenessWarnings"
              :key="i"
              type="warning"
              :closable="false"
              show-icon
              class="mt-sm"
              :title="`所选类型存在出院终末生效性告警：${w.code}${w.source ? '.' + w.source : ''}`"
              :description="w.detail"
            />
          </div>
          <div class="sched-grid">
            <el-card shadow="never" class="cfg-card">
              <div class="cfg-head">
                <span class="cfg-title">出院终末配置（discharge_final）</span>
                <div>
                  <el-button v-if="!dischargeCfg.enabled" size="small" type="success" :loading="jobAction === 'discharge_push'" :disabled="!!jobAction" @click="startJob('discharge_push')">启动</el-button>
                  <el-button v-else size="small" type="danger" plain :loading="jobAction === 'discharge_push'" :disabled="!!jobAction" @click="stopJob('discharge_push')">停止</el-button>
                </div>
              </div>
              <div class="cfg-body">
                <div class="cfg-row"><label>启用</label><el-switch v-model="dischargeCfg.enabled" size="small" /></div>
                <div class="cfg-row">
                  <label>频率</label>
                  <el-radio-group v-model="dischargeCfg.schedule_mode" size="small">
                    <el-radio value="daily">每天定时</el-radio>
                    <el-radio value="every_n_hours">每 N 小时</el-radio>
                    <el-radio value="every_n_minutes">每 N 分钟</el-radio>
                    <el-radio value="cron">自定义 Cron</el-radio>
                  </el-radio-group>
                </div>
                <div v-if="dischargeCfg.schedule_mode === 'daily'" class="cfg-row">
                  <label>执行时间</label>
                  <el-time-picker v-model="dischargeCfg.daily_time" format="HH:mm" value-format="HH:mm" placeholder="时间" size="small" style="width: 120px" />
                </div>
                <div v-if="dischargeCfg.schedule_mode === 'every_n_minutes'" class="cfg-row">
                  <label>间隔(分钟)</label>
                  <el-input-number v-model="dischargeCfg.interval_value" :min="1" :max="59" size="small" />
                </div>
                <div v-if="dischargeCfg.schedule_mode === 'every_n_hours'" class="cfg-row">
                  <label>间隔(小时)</label>
                  <el-input-number v-model="dischargeCfg.interval_value" :min="1" :max="23" size="small" />
                </div>
                <div v-if="dischargeCfg.schedule_mode === 'cron'" class="cfg-row">
                  <label>Cron 表达式</label>
                  <el-input v-model="dischargeCfg.cron" size="small" style="width: 200px" placeholder="0 11 * * *" />
                  <span class="cfg-hint">5 段 cron（分 时 日 月 周）</span>
                </div>
                <div class="cfg-row">
                  <label>质控类型</label>
                  <el-select v-model="dischargeCfg.audit_type_codes" multiple collapse-tags collapse-tags-tooltip filterable size="small" style="width: 100%" placeholder="留空用默认类型">
                    <el-option v-for="a in auditTypeOptions" :key="a.value" :label="`${a.label}（${a.value}）`" :value="a.value" />
                  </el-select>
                </div>
                <div class="cfg-row">
                  <label>科室范围</label>
                  <el-select
                    v-model="dischargeDeptSelected"
                    multiple
                    filterable
                    clearable
                    collapse-tags
                    collapse-tags-tooltip
                    allow-create
                    default-first-option
                    size="small"
                    style="width: 100%"
                    placeholder="全部科室（可搜索/自定义）"
                  >
                    <el-option v-for="name in deptCandidates" :key="name" :label="name" :value="name" />
                  </el-select>
                </div>
                <el-button size="small" type="primary" :loading="savingDischarge" @click="saveDischarge">保存出院配置</el-button>
                <el-alert
                  v-for="(w, i) in saveEffectivenessWarnings"
                  :key="`save-${i}`"
                  type="warning"
                  :closable="false"
                  show-icon
                  class="mt-sm"
                  :title="`保存成功，但存在生效性告警：${w.code}${w.source ? '.' + w.source : ''}`"
                  :description="w.detail"
                />
              </div>
            </el-card>
            <el-card shadow="never" class="cfg-card">
              <div class="cfg-head"><span class="cfg-title">出院终末说明</span></div>
              <div class="cfg-body">
                <p class="cfg-hint">
                  出院终末按「出院日期」取数（非病历创建日期），面向已出院病历的终末核查；
                  4 类规则有专用转换分支，其余走通用回退。所选类型若不满足专用分支或
                  <code>dept_filter</code> SQL 条件，将在上方诊断卡逐条列出（合法但不生效，保存不拒绝）。
                </p>
                <p class="cfg-hint">下次运行：{{ formatDateTime((statusData.discharge as AnyRecord)?.next_run) || '—' }}</p>
              </div>
            </el-card>
          </div>
        </template>
        <el-empty v-else description="当前未启用出院终末调度（status 未返回 discharge 配置）" />
      </el-tab-pane>

      <!-- ── 页签 3：执行历史 ── -->
      <el-tab-pane label="执行历史" name="history" lazy>
        <el-card shadow="never" class="section-card">
          <div class="section-title">执行历史</div>
          <el-table :data="history" stripe border size="small" style="width: 100%">
            <el-table-column label="开始时间" width="135"><template #default="{ row }">{{ formatDateTime(row.run_time) }}</template></el-table-column>
            <el-table-column label="模式" width="90"><template #default="{ row }">{{ auditRunModeLabel(row.audit_run_mode) }}</template></el-table-column>
            <el-table-column prop="query_date" label="查询日期" width="100" />
            <el-table-column prop="audit_type_code" label="类型" width="140" show-overflow-tooltip />
            <el-table-column label="耗时" width="70" align="center"><template #default="{ row }">{{ row.duration_seconds }}s</template></el-table-column>
            <el-table-column label="成功" width="55" align="center"><template #default="{ row }"><span style="color: var(--el-color-success)">{{ row.success_count }}</span></template></el-table-column>
            <el-table-column label="失败" width="55" align="center"><template #default="{ row }"><span :style="row.failed_count > 0 ? 'color: var(--el-color-danger)' : ''">{{ row.failed_count }}</span></template></el-table-column>
            <el-table-column label="跳过" width="55" align="center"><template #default="{ row }">{{ Math.max(0, Number(row.total_records || 0) - Number(row.success_count || 0) - Number(row.failed_count || 0)) }}</template></el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-popover v-if="row.error_code" placement="top" :width="320" trigger="hover">
                  <template #reference><StatusTag :value="row.status" /></template>
                  <pre class="err-pop">{{ row.error_code }}</pre>
                </el-popover>
                <StatusTag v-else :value="row.status" />
              </template>
            </el-table-column>
          </el-table>
          <el-pagination v-model:current-page="historyPage" v-model:page-size="historyPageSize" :total="historyTotal" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="mt-sm" @current-change="loadHistory" @size-change="() => { historyPage = 1; loadHistory() }" />
        </el-card>

        <el-card shadow="never" class="section-card">
          <div class="section-title">运行完整性（run-summary）</div>
          <div class="rs-controls">
            <label class="cfg-row-label">查询日期</label>
            <el-date-picker v-model="runSummaryQueryDate" type="date" value-format="YYYY-MM-DD" placeholder="查询日期" size="small" style="width: 140px" />
            <label class="cfg-row-label">模式</label>
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
            <el-table-column label="历史状态" width="90"><template #default="{ row }"><StatusTag :value="String(row.history_status || '')" /></template></el-table-column>
            <el-table-column prop="candidate_total" label="候选" width="70" align="center" />
            <el-table-column prop="transport_success" label="传输成功" width="80" align="center" />
            <el-table-column prop="qc_usable" label="质控可用" width="80" align="center" />
            <el-table-column prop="parse_failed" label="解析失败" width="80" align="center" />
            <el-table-column prop="high" label="高危" width="60" align="center" />
          </el-table>
        </el-card>

        <el-card v-if="runtimeWarnings.length" shadow="never" class="section-card">
          <div class="section-title">调度配置告警（runtime-summary）</div>
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
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
// WP09（064 总计划）：定时调度页重构——SummaryStrip 四卡 + 三页签（每日在院/出院
// 终末/执行历史）。全部既有端点与契约保留：
// - status.discharge_effectiveness{checked,warnings[{code,source,detail}]} 诊断卡
//   与保存响应 MessageResponse.data.effectiveness_warnings 双路展示（035/RP2 红线）；
// - run_locks/staleLock 心跳中断警示；legacy 单任务折叠说明（双调度启用时灰显）；
// - trigger/history/run-summary/runtime-summary 端点与字段不变。
// 并发数（max_workers）后端调度配置暂未开放 → 显示「—」（任务书许可）。
import { computed, onMounted, reactive, ref } from 'vue'
import PageHeader from '@/components/base/PageHeader.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { formatDateTime } from '@/utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

type AnyRecord = Record<string, any>

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
const activeTab = ref('daily')
const statusData = ref<AnyRecord>({})
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
const dailyDeptSelected = ref<string[]>([])
const dischargeDeptSelected = ref<string[]>([])
const saveEffectivenessWarnings = ref<Array<{ code: string; source?: string; detail: string }>>([])

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
const runSummary = ref<AnyRecord | null>(null)

// runtime warnings
const runtimeWarnings = ref<Array<AnyRecord>>([])

const hasDual = computed(() => !!(statusData.value as AnyRecord).has_dual)
const schedulerRunning = computed(() => !!statusData.value.running)
const runLocks = computed<Array<{ name: string; label: string; info: RunLockInfo }>>(() => {
  const raw = (statusData.value.run_locks || {}) as Record<string, RunLockInfo>
  return [
    { name: 'daily_push', label: '每日增量', info: raw.daily_push || {} },
    { name: 'discharge_push', label: '出院终末', info: raw.discharge_push || {} },
  ]
})
const staleLocks = computed(() => runLocks.value.filter((item) => item.info.status === 'running' && item.info.is_stale))

/** SummaryStrip 四卡（病历时效扫描 /status 无字段 → 「—」）。 */
const statusCards = computed<SummaryItem[]>(() => {
  const dailyNext = (statusData.value.daily as AnyRecord)?.next_run
  const dischargeNext = (statusData.value.discharge as AnyRecord)?.next_run
  return [
    {
      key: 'scheduler', label: '调度器',
      value: schedulerRunning.value ? '运行中' : '已停止',
      tone: schedulerRunning.value ? 'success' : 'info',
    },
    {
      key: 'daily', label: '每日在院任务',
      value: dailyCfg.enabled ? (dailyModeLabel.value || '已启用') : '未启用',
      tone: dailyCfg.enabled ? 'success' : 'info',
      hint: dailyNext ? `下次 ${formatDateTime(String(dailyNext))}` : undefined,
    },
    {
      key: 'discharge', label: '出院终末任务',
      value: hasDual.value ? (dischargeCfg.enabled ? (dischargeModeLabel.value || '已启用') : '未启用') : '未配置',
      tone: dischargeCfg.enabled ? 'success' : 'info',
      hint: dischargeNext ? `下次 ${formatDateTime(String(dischargeNext))}` : undefined,
    },
    {
      key: 'scan', label: '病历时效扫描',
      value: '—',
      hint: '每 5 分钟（时效扫描独立于本调度器，耗时字段接口未下发）',
    },
  ]
})

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
  const m: Record<string, string> = { daily: '每天定时', every_n_minutes: '每N分钟', every_n_hours: '每N小时', cron: 'Cron' }
  return m[mode] || mode
}

function auditRunModeLabel(mode: string): string {
  return ({ daily_increment: '每日增量', discharge_final: '出院终末' })[mode] || mode
}

/** discharge_effectiveness 诊断（035/RP2）。 */
const effectivenessWarnings = computed<Array<{ code: string; source?: string; detail: string }>>(() => {
  const eff = (statusData.value.discharge_effectiveness || {}) as AnyRecord
  return (eff.warnings || []) as Array<{ code: string; source?: string; detail: string }>
})
const effectivenessOk = computed(() => {
  const eff = (statusData.value.discharge_effectiveness || {}) as AnyRecord
  return eff.checked !== false && effectivenessWarnings.value.length === 0
})

function normalizeDeptList(text: string): string[] {
  return Array.from(new Set(
    text.split(/[\n,，;；]+/).map((s) => s.trim()).filter(Boolean)
  ))
}

function buildPayload(cfg: typeof dailyCfg, runMode: string, deptSelected: string[]): Record<string, unknown> {
  let cron = cfg.cron
  if (cfg.schedule_mode === 'daily') {
    const [h, m] = (cfg.daily_time || '10:00').split(':')
    cron = `${Number(m) || 0} ${Number(h) || 10} * * *`
  } else if (cfg.schedule_mode === 'every_n_minutes') {
    cron = `*/${cfg.interval_value || 30} * * * *`
  } else if (cfg.schedule_mode === 'every_n_hours') {
    cron = `0 */${cfg.interval_value || 1} * * *`
  }
  const depts = deptSelected.length ? deptSelected : normalizeDeptList(cfg.dept_filter_text)
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

function applyConfig(cfg: typeof dailyCfg, data: AnyRecord): void {
  cfg.enabled = !!data.enabled
  cfg.schedule_mode = String(data.schedule_mode || 'daily')
  cfg.daily_time = String(data.daily_time || '10:00')
  cfg.interval_value = Number(data.interval_value || 30)
  cfg.cron = String(data.cron || '0 10 * * *')
  cfg.audit_type_codes = (data.audit_type_codes as string[]) || []
  cfg.dept_filter_text = Array.isArray(data.dept_filter) ? (data.dept_filter as string[]).join(', ') : ''
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [status, hist, dailyData, dischargeData, auditTypes, depts] = await Promise.all([
      apiGet<AnyRecord>('/scheduler/status').catch(() => ({})),
      apiGet<{ items?: HistoryRow[]; total?: number }>('/scheduler/history', { params: { page: 1, limit: historyPageSize.value } }).catch(() => ({ items: [], total: 0 })),
      apiGet<AnyRecord>('/config/scheduler-daily').catch(() => ({})),
      hasDual.value ? apiGet<AnyRecord>('/config/scheduler-discharge').catch(() => ({})) : Promise.resolve({}),
      apiGet<{ items?: Array<{ code: string; name: string }> }>('/audit-types/options').catch(() => ({ items: [] })),
      apiGet<{ items?: string[] }>('/config/departments/list').catch(() => ({ items: [] })),
    ])
    statusData.value = status
    history.value = hist.items || []
    historyTotal.value = hist.total || 0

    if ((status as AnyRecord).has_dual && !(dischargeData as AnyRecord).enabled) {
      const d = await apiGet<AnyRecord>('/config/scheduler-discharge').catch(() => ({}))
      applyConfig(dischargeCfg, d)
    } else {
      applyConfig(dischargeCfg, dischargeData)
    }
    applyConfig(dailyCfg, dailyData)
    dailyDeptSelected.value = Array.isArray((dailyData as AnyRecord).dept_filter)
      ? [...((dailyData as AnyRecord).dept_filter as string[])] : []
    dischargeDeptSelected.value = Array.isArray((dischargeData as AnyRecord).dept_filter)
      ? [...((dischargeData as AnyRecord).dept_filter as string[])] : []

    auditTypeOptions.value = (auditTypes.items || []).map((a) => ({ value: a.code, label: a.name }))
    deptCandidates.value = (depts.items || []) as string[]

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

async function loadHistory(): Promise<void> {
  try {
    const data = await apiGet<{ items?: HistoryRow[]; total?: number }>('/scheduler/history', {
      params: { page: historyPage.value, limit: historyPageSize.value },
    })
    history.value = data.items || []
    historyTotal.value = data.total || 0
  } catch { /* 静默 */ }
}

async function saveDaily(): Promise<void> {
  savingDaily.value = true
  try {
    await apiPost('/config/scheduler-daily', buildPayload(dailyCfg, 'daily_increment', dailyDeptSelected.value))
    ElMessage.success('每日增量配置已保存')
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    savingDaily.value = false
  }
}

async function saveDischarge(): Promise<void> {
  savingDischarge.value = true
  saveEffectivenessWarnings.value = []
  try {
    const resp = await apiPost<AnyRecord>('/config/scheduler-discharge', buildPayload(dischargeCfg, 'discharge_final', dischargeDeptSelected.value))
    // 035/RP2：保存响应可能携带 data.effectiveness_warnings（合法但不生效类型逐条展示）
    const warnings = (resp?.data as AnyRecord | undefined)?.effectiveness_warnings
    if (Array.isArray(warnings) && warnings.length) {
      saveEffectivenessWarnings.value = warnings as Array<{ code: string; source?: string; detail: string }>
      ElMessage.warning('出院终末配置已保存，但存在生效性告警（见下方逐条提示）')
    } else {
      ElMessage.success('出院终末配置已保存')
    }
    await load()
  } catch (e) {
    ElMessage.error(toUserMessage(e, '保存失败'))
  } finally {
    savingDischarge.value = false
  }
}

async function startJob(jobId: string): Promise<void> {
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

async function stopJob(jobId: string): Promise<void> {
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

async function triggerNow(): Promise<void> {
  if (triggerLoading.value) return
  try {
    const params: Record<string, string> = { audit_run_mode: triggerForm.audit_run_mode }
    if (triggerForm.query_date) params.query_date = triggerForm.query_date
    if (triggerForm.audit_type_codes.length) params.audit_type_codes = triggerForm.audit_type_codes.join(',')
    const depts = normalizeDeptList(triggerForm.dept_filter_text)
    if (depts.length) params.dept_filter = depts.join(',')
    await ElMessageBox.confirm(
      `确认立即触发 ${auditRunModeLabel(triggerForm.audit_run_mode)}？${triggerForm.query_date ? '日期 ' + triggerForm.query_date : ''}，${triggerForm.audit_type_codes.length} 个类型。这可能调用 Dify。`,
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

async function loadRunSummary(): Promise<void> {
  if (!runSummaryQueryDate.value) return
  runSummaryLoading.value = true
  runSummary.value = null
  try {
    runSummary.value = await apiGet<AnyRecord>('/scheduler/run-summary', {
      params: { query_date: runSummaryQueryDate.value, audit_run_mode: runSummaryMode.value },
    })
  } catch (e) {
    ElMessage.error(toUserMessage(e, '加载运行汇总失败'))
  } finally {
    runSummaryLoading.value = false
  }
}

async function loadRuntimeWarnings(): Promise<void> {
  try {
    const data = await apiGet<{ warnings?: Array<AnyRecord> }>('/config/runtime-summary')
    const all = data.warnings || []
    runtimeWarnings.value = all.filter((w) => {
      const path = String(w.path || w.code || '')
      return path.startsWith('scheduler_daily.') || path.startsWith('scheduler_discharge.') || path.includes('dept_filter')
    })
  } catch { /* 静默 */ }
}

const runSummaryRows = computed(() => {
  if (!runSummary.value) return []
  return (runSummary.value.items as Array<AnyRecord>) || []
})
const runSummaryIncomplete = computed(() => runSummary.value?.incomplete as boolean || false)
const runSummaryTotals = computed(() => runSummary.value?.totals as Record<string, number> | undefined)

const warningGroups = computed(() => {
  const groups: Record<string, Array<AnyRecord>> = { error: [], warning: [], info: [] }
  for (const w of runtimeWarnings.value) {
    const lv = String(w.level || 'info')
    if (groups[lv]) groups[lv].push(w)
  }
  return groups
})

onMounted(() => { void load() })
</script>

<style scoped>
.page-scheduler { padding: 4px; }
.sched-tabs { margin-top: 4px; }
.lock-alert { margin-bottom: 10px; }
.lock-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-bottom: 12px; }
.lock-item { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border: 1px solid var(--el-border-color-lighter); border-radius: 8px; background: var(--el-fill-color-extra-light); }
.lock-item.is-stale { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); }
.lock-name { font-size: 13px; font-weight: 600; }
.lock-heartbeat { margin-left: auto; color: var(--el-text-color-secondary); font-size: 12px; }
.sched-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(380px, 1fr)); gap: 12px; margin-bottom: 12px; }
.cfg-card { border-radius: 10px; }
.cfg-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.cfg-title { font-size: 14px; font-weight: 600; }
.cfg-body { display: flex; flex-direction: column; gap: 8px; }
.cfg-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.cfg-row > label, .cfg-row-label { font-size: 12px; color: var(--el-text-color-secondary); min-width: 90px; flex-shrink: 0; }
.cfg-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.6; }
.eff-card { margin-bottom: 12px; }
.section-card { margin-bottom: 12px; border-radius: 10px; }
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.rs-controls { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.rs-totals { display: flex; gap: 16px; font-size: 13px; }
.rs-totals b { margin-left: 4px; font-size: 15px; }
.mt-sm { margin-top: 8px; }
.legacy-collapse { margin-top: 4px; }
.legacy-title { font-size: 13px; font-weight: 600; color: var(--el-text-color-secondary); }
.warn-path { font-size: 11px; color: var(--el-text-color-disabled); font-family: monospace; }
.err-pop { max-height: 180px; overflow: auto; font-size: 12px; white-space: pre-wrap; margin: 0; }
@media (max-width: 700px) {
  .lock-grid { grid-template-columns: 1fr; }
  .lock-item { align-items: flex-start; flex-wrap: wrap; }
  .lock-heartbeat { width: 100%; margin-left: 0; }
}
</style>
