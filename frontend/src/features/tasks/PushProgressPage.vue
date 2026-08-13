<script setup lang="ts">
import { computed, onActivated, onDeactivated, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/base/PageHeader.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import StatusTag from '@/components/base/StatusTag.vue'
import DetailDrawer from '@/components/base/DetailDrawer.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import { apiGet, apiPost } from '@/api/client'
import { toUserMessage } from '@/api/errors'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useTaskStore } from '@/stores/task'
import { historyProcessed, isPollableStatus, mergeCurrentTask, normalizeCurrentTask, summarizeTaskRows, type CurrentTask, type TaskHistoryRow } from '@/utils/task-progress'

const router = useRouter(); const taskStore = useTaskStore()
const loading = ref(false); const currentError = ref(''); const historyError = ref(''); const current = ref<CurrentTask | null>(null); const history = ref<TaskHistoryRow[]>([])
const page = ref(1); const limit = ref(20); const total = ref(0); const active = ref(false); const visible = ref(true); const cancelLoading = ref(false); const detail = ref<TaskHistoryRow | null>(null); const detailVisible = ref(false)
const filters = ref({ status: '', trigger_type: '', date_from: '', date_to: '', audit_run_mode: '' })
let timer: ReturnType<typeof setInterval> | null = null; let initialized = false; let loadingCurrent = false

const rows = computed(() => mergeCurrentTask(current.value, history.value, filters.value, page.value))
const fatalError = computed(() => currentError.value && historyError.value ? '当前任务与调度历史均加载失败' : '')
const currentIncluded = computed(() => rows.value.some((row) => row.source === 'current'))
const pageSummary = computed(() => summarizeTaskRows(rows.value))
const summary = computed<SummaryItem[]>(() => [
  { key: 'scope', label: '当前页/聚合范围', value: `${rows.value.length}/${total.value + (currentIncluded.value ? 1 : 0)}` },
  { key: 'running', label: '运行中', value: pageSummary.value.running, tone: 'info' },
  { key: 'completed', label: '已完成', value: pageSummary.value.completed, tone: 'success' },
  { key: 'failed', label: '失败', value: pageSummary.value.failed, tone: 'danger' },
  { key: 'average', label: '平均耗时(秒)', value: pageSummary.value.averageDuration },
])

function historyParams() { const p: Record<string, string | number> = { page: page.value, limit: limit.value }; for (const [k, v] of Object.entries(filters.value)) if (v) p[k] = v; return p }
async function loadCurrent() {
  if (loadingCurrent) return; loadingCurrent = true
  try { const data = await apiGet<Record<string, unknown>>('/push/tasks/latest'); current.value = normalizeCurrentTask(data); taskStore.latest = data as any; currentError.value = '' } catch (e) { currentError.value = toUserMessage(e, '加载当前任务失败') } finally { loadingCurrent = false; refreshTimer() }
}
async function loadHistory() { try { const data = await apiGet<{ items?: TaskHistoryRow[]; total?: number }>('/scheduler/history', { params: historyParams() }); history.value = data.items || []; total.value = Number(data.total || 0); historyError.value = '' } catch (e) { historyError.value = toUserMessage(e, '加载调度历史失败') } }
async function load() { loading.value = true; await Promise.all([loadCurrent(), loadHistory()]); loading.value = false; refreshTimer() }
function stopTimer() { if (timer) { clearInterval(timer); timer = null } }
function refreshTimer() { stopTimer(); if (active.value && visible.value && current.value && isPollableStatus(current.value.status)) timer = setInterval(() => { void loadCurrent() }, 5000) }
function activate() { active.value = true; if (!initialized) { initialized = true; void load() } else { void loadCurrent() }; refreshTimer() }
function deactivate() { active.value = false; stopTimer() }
function onVisibility() { visible.value = document.visibilityState === 'visible'; if (visible.value && active.value) void loadCurrent(); refreshTimer() }
async function cancelTask() { if (!current.value?.task_id || cancelLoading.value) return; try { await ElMessageBox.confirm('确认取消当前运行中的推送任务？', '危险操作', { type: 'warning' }); cancelLoading.value = true; await apiPost(`/push/cancel/${current.value.task_id}`); ElMessage.success('已请求取消'); await loadCurrent() } catch (e) { if (e !== 'cancel' && e !== 'close') ElMessage.error(toUserMessage(e, '取消失败')) } finally { cancelLoading.value = false; refreshTimer() } }
function viewHistory(row: any) { detail.value = row as TaskHistoryRow; detailVisible.value = true }
function viewAudit(row: any) { const date = String(row.query_date || ''); const query: Record<string, string> = { source: 'task-progress', date_from: date, date_to: date }; if (row.audit_type_code) query.audit_type_code = String(row.audit_type_code); void router.push({ name: 'quality-records', query }) }
function applyFilters() { page.value = 1; void loadHistory() }
function resetFilters() { filters.value = { status: '', trigger_type: '', date_from: '', date_to: '', audit_run_mode: '' }; page.value = 1; void loadHistory() }
function rowProcessed(row: any) { return row.source === 'current' ? Number(row.processed || 0) : historyProcessed(row) }
function rowPercent(row: any) { const totalValue = Number(row.total_records || 0); return totalValue ? Math.min(100, Math.round((rowProcessed(row) / totalValue) * 100)) : 0 }

onMounted(() => { document.addEventListener('visibilitychange', onVisibility); activate() })
onActivated(() => activate()); onDeactivated(() => deactivate()); onUnmounted(() => { deactivate(); document.removeEventListener('visibilitychange', onVisibility) })
</script>

<template>
  <div class="page-progress">
    <PageHeader title="任务进度" description="当前手动任务与调度执行历史聚合展示；历史记录只读。">
      <template #actions><el-button :loading="loading" @click="load">刷新</el-button><el-button type="danger" :loading="cancelLoading" :disabled="!current || !isPollableStatus(current.status)" @click="cancelTask">取消当前任务</el-button></template>
    </PageHeader>
    <ErrorState v-if="fatalError && !loading" :message="fatalError" @retry="load" />
    <template v-else>
      <SummaryStrip :items="summary" :loading="loading" />
      <el-card shadow="never" class="card">
        <template #header><div class="filter-head"><span>任务列表</span><span class="scope-note">当前页 / 当前筛选聚合范围</span></div></template>
        <div class="filters"><el-select v-model="filters.status" clearable placeholder="状态" size="small"><el-option label="运行中" value="running"/><el-option label="已完成" value="completed"/><el-option label="失败" value="failed"/><el-option label="已取消" value="cancelled"/></el-select><el-select v-model="filters.trigger_type" clearable placeholder="触发类型" size="small"><el-option label="自动" value="auto"/><el-option label="手动" value="manual"/><el-option label="重试" value="retry"/></el-select><el-date-picker v-model="filters.date_from" value-format="YYYY-MM-DD" type="date" placeholder="执行开始" size="small"/><el-date-picker v-model="filters.date_to" value-format="YYYY-MM-DD" type="date" placeholder="执行结束" size="small"/><el-select v-model="filters.audit_run_mode" clearable placeholder="运行模式" size="small"><el-option label="日常增量" value="daily_increment"/><el-option label="出院终结" value="discharge_final"/></el-select><el-button size="small" type="primary" @click="applyFilters">查询</el-button><el-button size="small" @click="resetFilters">重置</el-button></div>
        <el-alert v-if="currentError || historyError" :title="[currentError, historyError].filter(Boolean).join('；')" type="warning" :closable="false" />
        <el-table :data="rows" stripe border size="small" max-height="520"><el-table-column label="类型" width="90"><template #default="{ row }">{{ row.source === 'current' ? '当前手动' : row.trigger_type }}</template></el-table-column><el-table-column label="时间/业务日期" min-width="150"><template #default="{ row }">{{ row.run_time || row.query_date || '—' }}</template></el-table-column><el-table-column label="模式/类型" min-width="180"><template #default="{ row }">{{ row.audit_run_mode || '—' }} / {{ row.audit_type_code || '—' }}</template></el-table-column><el-table-column label="状态" width="100"><template #default="{ row }"><StatusTag :value="row.status"/></template></el-table-column><el-table-column label="进度" width="120"><template #default="{ row }">{{ rowProcessed(row) }} / {{ row.total_records }}<el-progress :percentage="rowPercent(row)" :show-text="false"/></template></el-table-column><el-table-column label="成功/失败/跳过" width="130"><template #default="{ row }">{{ row.success_count || 0 }} / {{ row.failed_count || 0 }} / {{ row.skipped || 0 }}</template></el-table-column><el-table-column prop="duration_seconds" label="耗时(秒)" width="90"/><el-table-column label="错误摘要" min-width="180" show-overflow-tooltip><template #default="{ row }">{{ row.error_msg || '—' }}</template></el-table-column><el-table-column label="操作" width="150" fixed="right"><template #default="{ row }"><el-button size="small" @click="viewHistory(row)">详情</el-button><el-button v-if="row.query_date" size="small" type="primary" link @click="viewAudit(row)">查看质控记录</el-button></template></el-table-column></el-table>
        <el-pagination v-model:current-page="page" v-model:page-size="limit" class="pager" layout="total, prev, pager, next, sizes" :total="total" :page-sizes="[20, 50, 100]" @current-change="loadHistory" @size-change="loadHistory" />
      </el-card>
    </template>
    <DetailDrawer v-model="detailVisible" title="任务详情" size="620px"><el-descriptions v-if="detail" :column="1" border size="small"><el-descriptions-item label="状态"><StatusTag :value="detail.status"/></el-descriptions-item><el-descriptions-item label="触发类型">{{ detail.trigger_type }}</el-descriptions-item><el-descriptions-item label="执行时间">{{ detail.run_time || '—' }}</el-descriptions-item><el-descriptions-item label="业务日期">{{ detail.query_date || '—' }}</el-descriptions-item><el-descriptions-item label="错误摘要">{{ detail.error_msg || '—' }}</el-descriptions-item></el-descriptions></DetailDrawer>
  </div>
</template>

<style scoped>.card{border-radius:12px}.filter-head{display:flex;justify-content:space-between;gap:12px}.scope-note{font-size:12px;color:var(--ma-text-muted)}.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px}.filters>*{min-width:130px}.pager{margin-top:12px;justify-content:flex-end}@media(max-width:640px){.filter-head{align-items:flex-start;flex-direction:column}.filters>*{width:100%}}</style>
