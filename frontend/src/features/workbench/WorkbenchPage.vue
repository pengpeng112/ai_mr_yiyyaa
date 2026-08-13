<script setup lang="ts">
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { apiGet } from '@/api/client'
import {
  fetchAnomalyTop,
  fetchStatsDaily,
  fetchStatsSeverity,
  fetchStatsToday,
} from '@/api/endpoints/stats'
import { fetchHealthApi } from '@/api/endpoints/health'
import { useNavigationStore } from '@/stores/navigation'

echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()
const nav = useNavigationStore()

const C = {
  text: '#0f172a',
  muted: '#64748b',
  axis: '#cbd5e1',
  split: '#e2e8f0',
  tipBg: 'rgba(15,23,42,.94)',
  tipBorder: '#2563eb',
  cyan: '#0891b2',
  blue: '#2563eb',
  green: '#22c55e',
  orange: '#f59e0b',
  red: '#ef4444',
}

const loading = ref(true)
const loadError = ref('')
const currentTime = ref('')
const updatedAt = ref('')
let clockTimer: ReturnType<typeof setInterval> | null = null

const kpis = ref({
  date: '',
  total: 0,
  todaySuccess: 0,
  todaySkipped: 0,
  successRate: 0,
  effectiveTotal: 0,
  inconsistency: 0,
  inconsistencyRate: null as number | null,
  highRisk: 0,
  relayFailed: 0,
  relayUnviewed: 0,
  relaySuccessRate: null as number | null,
  viewRate: null as number | null,
})

const overallHealth = ref('healthy')
const healthComps = ref<Record<string, { status: string; latency_ms?: number }>>({})
const deptTop = ref<Array<{ dept: string; inconsistency_count: number }>>([])
const events = ref<Array<Record<string, unknown>>>([])
const schedulerInfo = ref({ lastRunTime: '', nextRunTime: '', running: false })
const severityEmpty = ref(false)
const trendEmpty = ref(false)
// 图表容器在重试耗尽后仍宽高为 0 时（极端：CSS 故障 / 祖先 display:none），标记渲染失败
const severityRenderFailed = ref(false)
const trendRenderFailed = ref(false)
const trendRows = ref<Array<{ date: string; total: number; success: number; failed: number; inconsistency: number }>>([])
const severityItems = ref<Array<{ severity: string; count: number }>>([])

const trendEl = ref<HTMLDivElement | null>(null)
const severityEl = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null
let severityChart: echarts.ECharts | null = null
let chartRo: ResizeObserver | null = null
let paintTimer: ReturnType<typeof setTimeout> | null = null

function pct(v: number | null): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '--'
  return `${v.toFixed(1)}%`
}

function todayStr(): string {
  const n = new Date()
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
}

function daysAgoStr(days: number): string {
  const n = new Date()
  n.setDate(n.getDate() - days)
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
}

function fmtDateTime(v: unknown): string {
  if (!v) return ''
  return String(v).replace('T', ' ').slice(0, 16)
}

function cname(key: string): string {
  const map: Record<string, string> = {
    app_db: '应用数据库',
    business_db: '业务数据库',
    oracle: 'Oracle',
    postgresql: 'PostgreSQL',
    scheduler: '调度器',
    dify: 'Dify',
  }
  return map[key] || key
}

function deptTopPct(val: number): number {
  const max = Math.max(...deptTop.value.map((d) => d.inconsistency_count || 0), 1)
  return max ? Math.min(100, ((val || 0) / max) * 100) : 0
}

function go(menuId: string, query: Record<string, string> = {}) {
  const item = nav.findByMenuId(menuId)
  if (item) void router.push({ name: item.entry.name, query })
}

function goAlert(item: Record<string, unknown>) {
  const id = Number(item.id)
  const query: Record<string, string> = { source: 'workbench', alert_level: 'red' }
  if (Number.isSafeInteger(id) && id > 0) query.log_id = String(id)
  const patientId = String(item.patient_id || '').trim()
  if (patientId) query.patient_id = patientId.slice(0, 120)
  void router.push({ name: 'quality-records', query })
}

function onTileKeydown(event: KeyboardEvent, action: () => void) {
  if (event.key === 'Enter' || event.key === ' ') {
    event.preventDefault()
    action()
  }
}

function disposeCharts() {
  if (paintTimer) {
    clearTimeout(paintTimer)
    paintTimer = null
  }
  chartRo?.disconnect()
  chartRo = null
  trendChart?.dispose()
  severityChart?.dispose()
  trendChart = null
  severityChart = null
}

function bindChartResize() {
  chartRo?.disconnect()
  if (typeof ResizeObserver === 'undefined') return
  chartRo = new ResizeObserver(() => handleResize())
  if (trendEl.value) chartRo.observe(trendEl.value)
  if (severityEl.value) chartRo.observe(severityEl.value)
}

/** 图表容器可能在 loading 切换后短暂宽高为 0，需重试初始化 */
function schedulePaintCharts(attempt = 0) {
  if (paintTimer) {
    clearTimeout(paintTimer)
    paintTimer = null
  }
  paintTimer = setTimeout(() => {
    paintTimer = null
    void paintCharts(attempt)
  }, attempt === 0 ? 0 : 60)
}

async function paintCharts(attempt = 0) {
  await nextTick()
  const trendReady = !!trendEl.value && trendEl.value.clientWidth > 0
  const sevReady = !!severityEl.value && severityEl.value.clientWidth > 0
  if ((!trendReady || !sevReady) && attempt < 15) {
    schedulePaintCharts(attempt + 1)
    return
  }
  // 重试耗尽仍有容器未就绪：标记渲染失败，避免图表区静默空白（无任何提示）
  severityRenderFailed.value = !sevReady
  trendRenderFailed.value = !trendReady
  if (sevReady) renderSeverity(severityItems.value)
  if (trendReady) renderTrend(trendRows.value)
  bindChartResize()
  handleResize()
  // 二次 resize：布局稳定后强制重绘 canvas
  setTimeout(() => handleResize(), 120)
}

function asItems<T = Record<string, unknown>>(raw: unknown): T[] {
  if (!raw || typeof raw !== 'object') return []
  const obj = raw as { items?: T[]; data?: T[] }
  if (Array.isArray(obj.items)) return obj.items
  if (Array.isArray(obj.data)) return obj.data
  if (Array.isArray(raw)) return raw as T[]
  return []
}

function normalizeDaily(rows: Array<Record<string, unknown>>) {
  return [...rows]
    .map((r) => ({
      date: String(r.date || r.day || r.query_date || ''),
      total: Number(r.total ?? r.count ?? 0),
      success: Number(r.success ?? 0),
      failed: Number(r.failed ?? 0),
      inconsistency: Number(r.inconsistency ?? 0),
    }))
    .filter((r) => r.date)
    .sort((a, b) => a.date.localeCompare(b.date))
}

function normalizeSeverity(rows: Array<Record<string, unknown>>) {
  const labels = new Set(['high', 'medium', 'low'])
  return rows
    .map((r) => ({
      severity: String(r.severity || r.name || '').toLowerCase(),
      count: Number(r.count ?? r.value ?? 0),
    }))
    .filter((r) => r.count > 0 && (labels.has(r.severity) || r.severity))
}

function isHighRiskLog(i: Record<string, unknown>): boolean {
  const sev = String(i.severity || '').toLowerCase()
  const alert = String(i.alert_level || '').toLowerCase()
  const score = Number(i.risk_score || 0)
  const inconsist = Number(i.inconsistency || 0) === 1
  return sev === 'high' || alert === 'red' || score >= 80 || (inconsist && (sev === 'medium' || score >= 60))
}

async function loadHighRiskEvents(): Promise<Array<Record<string, unknown>>> {
  const from = daysAgoStr(7)
  const to = todayStr()
  const tries = [
    { page: 1, limit: 40, severity: 'high', push_time_from: from, push_time_to: to },
    { page: 1, limit: 50, inconsistency: 1, push_time_from: from, push_time_to: to },
    { page: 1, limit: 50, push_time_from: from, push_time_to: to },
    { page: 1, limit: 40 },
  ]
  for (const params of tries) {
    try {
      const res = await apiGet<{ items?: Array<Record<string, unknown>> }>('/logs', { params })
      const items = res.items || []
      const high = items.filter(isHighRiskLog)
      if (high.length) return high.slice(0, 8)
      // 最后一轮即使没有 high 也返回 inconsistency 样本
      if (params === tries[tries.length - 1] && items.length) {
        return items
          .filter((i) => Number(i.inconsistency || 0) === 1 || Number(i.risk_score || 0) > 0)
          .slice(0, 8)
      }
    } catch {
      /* next */
    }
  }
  return []
}

async function load() {
  loading.value = true
  loadError.value = ''
  disposeCharts()
  try {
    const today = todayStr()
    const [healthR, todayR, dailyR, severityR, deptTopR, schedR, relaySumR] = await Promise.all([
      fetchHealthApi().catch(() => ({ status: 'unknown', components: {} })),
      fetchStatsToday().catch(() => ({})),
      fetchStatsDaily(30).catch(() => ({ items: [] })),
      fetchStatsSeverity().catch(() => ({ items: [] })),
      fetchAnomalyTop('dept').catch(() => ({ items: [] })),
      apiGet<Record<string, unknown>>('/scheduler/status').catch(() => ({})),
      apiGet<Record<string, unknown>>('/patient-qc/relay-alert/summary').catch(() => ({})),
    ])

    const rawComps = (healthR as { components?: Record<string, { status: string; latency_ms?: number }> }).components || {}
    healthComps.value = Object.fromEntries(Object.entries(rawComps).filter(([k]) => k !== 'dify'))
    overallHealth.value = (healthR as { status?: string }).status || 'healthy'

    const tTotal = Number((todayR as { total?: number }).total || 0)
    const tSuccess = Number((todayR as { success?: number }).success || 0)
    const tSkipped = Number((todayR as { skipped?: number }).skipped || 0)
    const tInconsist = Number((todayR as { inconsistency?: number }).inconsistency || 0)
    const effTotal = Math.max(0, tTotal - tSkipped)

    let sevItems = normalizeSeverity(asItems(severityR))
    // 后端无数据时，从近 7 日日志本地聚合风险等级
    if (!sevItems.length) {
      try {
        const logs = await apiGet<{ items?: Array<Record<string, unknown>> }>('/logs', {
          params: { page: 1, limit: 200, push_time_from: daysAgoStr(7), push_time_to: today },
        })
        const counts: Record<string, number> = { high: 0, medium: 0, low: 0 }
        for (const row of logs.items || []) {
          const sev = String(row.severity || '').toLowerCase()
          if (sev in counts) counts[sev] += 1
          else if (Number(row.inconsistency || 0) === 1) counts.medium += 1
        }
        sevItems = Object.entries(counts)
          .filter(([, c]) => c > 0)
          .map(([severity, count]) => ({ severity, count }))
      } catch {
        /* ignore */
      }
    }
    const highRiskCount = Number(sevItems.find((i) => i.severity === 'high')?.count || 0)

    const relaySum = relaySumR as Record<string, number>
    const rTotal = Number(relaySum.total || 0)
    const rSuccess = Number(relaySum.success || 0)
    const rFailed = Number(relaySum.failed || 0)
    const rViewed = Number(relaySum.viewed || 0)
    const rUnviewed = Number(relaySum.unviewed || 0)

    kpis.value = {
      date: String((todayR as { date?: string }).date || today),
      total: tTotal,
      todaySuccess: tSuccess,
      todaySkipped: tSkipped,
      successRate: effTotal ? (tSuccess / effTotal) * 100 : 0,
      effectiveTotal: effTotal,
      inconsistencyRate: effTotal ? (tInconsist / effTotal) * 100 : null,
      inconsistency: tInconsist,
      highRisk: highRiskCount,
      relayFailed: rFailed,
      relayUnviewed: rUnviewed,
      relaySuccessRate: (relaySum.success_rate as number) ?? (rTotal ? (rSuccess / rTotal) * 100 : null),
      viewRate: (relaySum.view_rate as number) ?? (rTotal ? (rViewed / rTotal) * 100 : null),
    }

    const deptItems = asItems<{ dept?: string; inconsistency_count?: number; count?: number }>(deptTopR)
    deptTop.value = deptItems
      .map((d) => ({
        dept: String(d.dept || '未知'),
        inconsistency_count: Number(d.inconsistency_count ?? d.count ?? 0),
      }))
      .filter((d) => d.inconsistency_count > 0)
      .slice(0, 8)

    const highLogs = await loadHighRiskEvents()
    events.value = highLogs.slice(0, 8).map((i) => ({
      id: i.id,
      patient_name: i.patient_name || '--',
      patient_id: i.patient_id || '--',
      dept: i.dept || '--',
      risk_score: Number(i.risk_score || 0),
      severity: i.severity || '',
      push_time: fmtDateTime(i.push_time),
    }))

    const sched = schedR as Record<string, unknown>
    schedulerInfo.value = {
      running: !!sched.running || String(sched.status || '') === 'running',
      lastRunTime: fmtDateTime((sched.last_run as Record<string, string>)?.run_time || sched.last_run),
      nextRunTime: fmtDateTime(sched.next_run),
    }

    let dailyItems = normalizeDaily(asItems(dailyR))
    // 无趋势数据时用日志按日粗聚合兜底
    if (!dailyItems.length) {
      try {
        const logs = await apiGet<{ items?: Array<Record<string, unknown>> }>('/logs', {
          params: { page: 1, limit: 200, push_time_from: daysAgoStr(14), push_time_to: today },
        })
        const map = new Map<string, { date: string; total: number; success: number; failed: number; inconsistency: number }>()
        for (const row of logs.items || []) {
          const day = String(row.query_date || fmtDateTime(row.push_time).slice(0, 10) || '')
          if (!day) continue
          const cur = map.get(day) || { date: day, total: 0, success: 0, failed: 0, inconsistency: 0 }
          cur.total += 1
          if (row.status === 'success') cur.success += 1
          if (row.status === 'failed') cur.failed += 1
          if (Number(row.inconsistency || 0) === 1) cur.inconsistency += 1
          map.set(day, cur)
        }
        dailyItems = [...map.values()].sort((a, b) => a.date.localeCompare(b.date))
      } catch {
        /* ignore */
      }
    }

    severityItems.value = sevItems
    trendRows.value = dailyItems
    severityEmpty.value = sevItems.length === 0
    trendEmpty.value = dailyItems.length === 0
    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })

    // 先结束 loading，让图表 DOM 挂载；
    // 绘制交由 watch(loading) 统一触发——try 成功与 catch 失败两条路径都会经过，避免在此重复触发
    loading.value = false
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '工作台加载失败'
    loading.value = false
  }
}

function renderTrend(rows: Array<{ date: string; total: number; success: number; failed: number; inconsistency: number }>) {
  if (!trendEl.value) return
  if (!trendChart || trendChart.getDom() !== trendEl.value) {
    trendChart?.dispose()
    trendChart = echarts.init(trendEl.value, undefined, { renderer: 'canvas' })
  }
  if (!rows.length) {
    trendChart.clear()
    return
  }
  trendChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: {
        trigger: 'axis',
        backgroundColor: C.tipBg,
        borderColor: C.tipBorder,
        textStyle: { color: '#f8fafc', fontSize: 12 },
      },
      legend: { data: ['总量', '成功', '不一致', '失败'], textStyle: { color: C.muted, fontSize: 11 }, top: 0 },
      grid: { left: 44, right: 16, top: 36, bottom: 28 },
      xAxis: {
        type: 'category',
        data: rows.map((r) => String(r.date).slice(5)),
        axisLine: { lineStyle: { color: C.axis } },
        axisLabel: { color: C.muted, fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        splitLine: { lineStyle: { color: C.split } },
        axisLabel: { color: C.muted, fontSize: 10 },
      },
      series: [
        { name: '总量', type: 'line', smooth: true, showSymbol: false, data: rows.map((r) => r.total), itemStyle: { color: C.cyan }, lineStyle: { width: 2.5 } },
        { name: '成功', type: 'line', smooth: true, showSymbol: false, data: rows.map((r) => r.success), itemStyle: { color: C.green }, lineStyle: { width: 2 } },
        { name: '不一致', type: 'line', smooth: true, showSymbol: false, data: rows.map((r) => r.inconsistency), itemStyle: { color: C.red }, lineStyle: { width: 2 } },
        { name: '失败', type: 'line', smooth: true, showSymbol: false, data: rows.map((r) => r.failed), itemStyle: { color: C.orange }, lineStyle: { width: 2 } },
      ],
    },
    { notMerge: true },
  )
}

function renderSeverity(items: Array<{ severity: string; count: number }>) {
  if (!severityEl.value) return
  if (!severityChart || severityChart.getDom() !== severityEl.value) {
    severityChart?.dispose()
    severityChart = echarts.init(severityEl.value, undefined, { renderer: 'canvas' })
  }
  if (!items.length) {
    severityChart.clear()
    return
  }
  const cmap: Record<string, string> = { high: C.red, medium: C.orange, low: C.blue }
  const labels: Record<string, string> = { high: '高危', medium: '中危', low: '低危' }
  severityChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: '#f8fafc' } },
      legend: { bottom: 0, textStyle: { color: C.muted, fontSize: 11 } },
      series: [{
        type: 'pie',
        radius: ['40%', '66%'],
        center: ['50%', '46%'],
        label: { color: C.muted, fontSize: 11, formatter: '{b}\n{c}' },
        data: items.map((i) => ({
          name: labels[i.severity] || i.severity || '未知',
          value: i.count,
          itemStyle: { color: cmap[i.severity] || C.cyan },
        })),
      }],
    },
    { notMerge: true },
  )
}

function updateClock() {
  currentTime.value = new Date().toLocaleString('zh-CN', { hour12: false }).replace(/\//g, '-')
}

function handleResize() {
  trendChart?.resize()
  severityChart?.resize()
}

onMounted(() => {
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  void load()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
  disposeCharts()
  window.removeEventListener('resize', handleResize)
})

watch(loading, (v) => {
  // 图表容器用 v-show 常驻 DOM；loading 结束后再画图
  if (!v) schedulePaintCharts(0)
})
</script>

<template>
  <div class="wb">
    <div v-show="loading" class="wb-skel" aria-hidden="true">
      <div class="sk hero" />
      <div class="sk-row"><div v-for="n in 4" :key="n" class="sk card" /></div>
      <div class="sk-row"><div class="sk panel" /><div class="sk panel" /></div>
    </div>

    <!-- 图表 DOM 始终挂载（v-show），避免 ECharts 初始化时 ref/宽高为 0 -->
    <div v-show="!loading" class="wb-body">
      <header class="wb-hero">
        <div>
          <div class="wb-kicker">山东省第二人民医院</div>
          <h1 class="wb-title">AI 质控工作台</h1>
          <p class="wb-sub">今日核查态势 · 风险分布 · 趋势与事件</p>
        </div>
        <div class="wb-hero-r">
          <div class="wb-time">{{ currentTime }}</div>
          <div v-if="updatedAt" class="wb-updated">更新 {{ updatedAt }}</div>
          <el-tag size="small" :type="overallHealth === 'healthy' ? 'success' : overallHealth === 'degraded' ? 'warning' : 'danger'">
            {{ overallHealth === 'healthy' ? '系统正常' : overallHealth === 'degraded' ? '部分异常' : '系统异常' }}
          </el-tag>
          <el-button size="small" :loading="loading" @click="load">刷新</el-button>
        </div>
      </header>

      <el-alert v-if="loadError" type="error" :title="loadError" show-icon :closable="false" class="wb-alert" />

      <section class="kpi-grid" aria-label="今日核心指标">
        <button class="kpi" type="button" @click="go('audit', { source: 'workbench', date_from: todayStr(), date_to: todayStr() })">
          <span class="kpi-label">今日核查量</span>
          <strong class="kpi-val cyan">{{ kpis.total }}</strong>
          <span class="kpi-hint">{{ kpis.date || todayStr() }}</span>
        </button>
        <button class="kpi" type="button" @click="go('patient-qc', { source: 'workbench', date_from: todayStr(), date_to: todayStr() })">
          <span class="kpi-label">今日不一致</span>
          <strong class="kpi-val red">{{ kpis.inconsistency }}</strong>
          <span class="kpi-hint">率 {{ kpis.inconsistencyRate !== null ? pct(kpis.inconsistencyRate) : '--' }}</span>
        </button>
        <button class="kpi" type="button" @click="go('patient-qc', { source: 'workbench', severity: 'high' })">
          <span class="kpi-label">高危结果</span>
          <strong class="kpi-val red">{{ kpis.highRisk }}</strong>
          <span class="kpi-hint">点击查看患者质控</span>
        </button>
        <button class="kpi" type="button" @click="go('audit', { source: 'workbench', date_from: todayStr(), date_to: todayStr(), status: 'success' })">
          <span class="kpi-label">AI 成功率</span>
          <strong class="kpi-val green">{{ kpis.effectiveTotal ? pct(kpis.successRate) : '--' }}</strong>
          <span class="kpi-hint">成功 {{ kpis.todaySuccess }} · 跳过 {{ kpis.todaySkipped }}</span>
        </button>
      </section>

      <section class="meta-grid" aria-label="运行状态">
        <button class="meta" type="button" @click="go('relay-alert-logs', kpis.relayFailed > 0 ? { source: 'workbench', quick: 'failed' } : { source: 'workbench' })">
          <span>前置机失败</span><b :class="{ danger: kpis.relayFailed > 0 }">{{ kpis.relayFailed }}</b>
        </button>
        <button class="meta" type="button" @click="go('relay-alert-logs', kpis.relayUnviewed > 0 ? { source: 'workbench', quick: 'unviewed' } : { source: 'workbench' })">
          <span>医生未查看</span><b :class="{ warn: kpis.relayUnviewed > 0 }">{{ kpis.relayUnviewed }}</b>
        </button>
        <button class="meta" type="button" @click="go('scheduler')">
          <span>调度</span><b class="cyan">{{ schedulerInfo.running ? '运行中' : '已配置' }}</b>
        </button>
        <button class="meta" type="button" @click="go('health')">
          <span>前置机成功率</span><b>{{ kpis.relaySuccessRate !== null ? pct(kpis.relaySuccessRate) : '--' }}</b>
        </button>
      </section>

      <section class="main-grid">
        <div class="card">
          <div class="card-h">
            <h3>风险等级分布</h3>
            <span class="card-sub">不一致结果严重度</span>
          </div>
          <div class="chart-box">
            <div ref="severityEl" class="chart chart-sm" />
            <div v-if="severityRenderFailed || severityEmpty" class="empty-overlay">
              {{ severityRenderFailed ? '图表初始化失败，请刷新页面重试' : '暂无风险分布数据' }}
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-h">
            <h3>近 30 天质控趋势</h3>
            <span class="card-sub">按查询日期汇总</span>
          </div>
          <div class="chart-box">
            <div ref="trendEl" class="chart" />
            <div v-if="trendRenderFailed || trendEmpty" class="empty-overlay">
              {{ trendRenderFailed ? '图表初始化失败，请刷新页面重试' : '暂无趋势数据' }}
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-h">
            <h3>科室风险 TOP</h3>
            <span class="card-sub">不一致高发科室</span>
          </div>
          <div v-if="deptTop.length" class="dept-list">
            <button
              v-for="(item, idx) in deptTop"
              :key="item.dept"
              type="button"
              class="dept-row"
              @click="go('patient-qc', { source: 'workbench', dept: item.dept })"
            >
              <span class="rank" :class="'r' + Math.min(idx + 1, 3)">{{ idx + 1 }}</span>
              <span class="name">{{ item.dept || '未知' }}</span>
              <span class="bar"><i :style="{ width: deptTopPct(item.inconsistency_count) + '%' }" /></span>
              <span class="cnt">{{ item.inconsistency_count }}</span>
            </button>
          </div>
          <div v-else class="empty">暂无科室排行</div>
        </div>

        <div class="card">
          <div class="card-h">
            <h3>高风险事件</h3>
            <span class="card-sub">近 7 日高危 / 高分结果</span>
          </div>
          <div v-if="events.length" class="event-list">
            <button
              v-for="item in events"
              :key="String(item.id)"
              type="button"
              class="event"
              :aria-label="`高风险事件：${item.patient_name || '未知患者'}，${item.dept || '未知科室'}，日志 ${item.id || '未知'}`"
              @click="goAlert(item)"
              @keydown="onTileKeydown($event, () => goAlert(item))"
            >
              <div class="event-top">
                <time>{{ item.push_time }}</time>
                <el-tag size="small" type="danger">高风险</el-tag>
              </div>
              <div class="event-body">
                {{ item.patient_name }} · {{ item.dept }}
                <span v-if="item.risk_score"> · 分 {{ item.risk_score }}</span>
              </div>
            </button>
          </div>
          <div v-else class="empty">暂无高风险事件</div>
        </div>
      </section>

      <section class="health-card card">
        <div class="card-h"><h3>系统健康</h3></div>
        <div v-if="Object.keys(healthComps).length" class="health-grid">
          <div v-for="(comp, key) in healthComps" :key="key" class="health-item">
            <span class="dot" :class="comp.status === 'up' || comp.status === 'running' ? 'up' : comp.status === 'disabled' ? 'off' : 'down'" />
            <span>{{ cname(String(key)) }}</span>
            <em>{{ comp.latency_ms ? comp.latency_ms + 'ms' : '--' }}</em>
          </div>
        </div>
        <div v-else class="empty">暂无组件状态</div>
        <p v-if="schedulerInfo.nextRunTime || schedulerInfo.lastRunTime" class="sched">
          <span v-if="schedulerInfo.lastRunTime">最近调度 {{ schedulerInfo.lastRunTime }}</span>
          <span v-if="schedulerInfo.nextRunTime"> · 下次 {{ schedulerInfo.nextRunTime }}</span>
        </p>
      </section>
    </div>
  </div>
</template>

<style scoped>
.wb {
  --panel: #fff;
  --line: #e2e8f0;
  --text: #0f172a;
  --muted: #64748b;
  --cyan: #0891b2;
  --blue: #2563eb;
  --green: #16a34a;
  --orange: #d97706;
  --red: #dc2626;
  padding: 4px 2px 20px;
  color: var(--text);
}
.wb-hero {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;
  padding: 18px 20px;
  border-radius: 16px;
  background: linear-gradient(135deg, #eff6ff 0%, #f8fafc 55%, #ecfeff 100%);
  border: 1px solid #dbeafe;
}
.wb-kicker { font-size: 12px; color: #0369a1; font-weight: 600; margin-bottom: 4px; }
.wb-title { margin: 0; font-size: 22px; font-weight: 800; letter-spacing: 0.01em; }
.wb-sub { margin: 6px 0 0; color: var(--muted); font-size: 13px; }
.wb-hero-r { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; justify-content: flex-end; }
.wb-time { font-size: 13px; color: #334155; font-variant-numeric: tabular-nums; }
.wb-updated { font-size: 12px; color: var(--muted); }
.wb-alert { margin-bottom: 12px; }

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 12px;
}
.kpi {
  text-align: left;
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 14px;
  padding: 16px;
  cursor: pointer;
  transition: border-color .2s, box-shadow .2s;
}
.kpi:hover { border-color: #93c5fd; box-shadow: 0 8px 20px rgba(37, 99, 235, 0.08); }
.kpi-label { display: block; font-size: 12px; color: var(--muted); margin-bottom: 8px; }
.kpi-val { display: block; font-size: 28px; font-weight: 800; line-height: 1.1; }
.kpi-val.cyan { color: var(--cyan); }
.kpi-val.red { color: var(--red); }
.kpi-val.green { color: var(--green); }
.kpi-hint { display: block; margin-top: 8px; font-size: 12px; color: #94a3b8; }

.meta-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--line);
  background: #f8fafc;
  border-radius: 12px;
  padding: 12px 14px;
  cursor: pointer;
  font-size: 13px;
  color: var(--muted);
}
.meta b { color: var(--text); font-size: 16px; }
.meta b.danger { color: var(--red); }
.meta b.warn { color: var(--orange); }
.meta b.cyan { color: var(--cyan); }

.main-grid {
  display: grid;
  grid-template-columns: 1fr 1.4fr;
  grid-template-rows: auto auto;
  gap: 14px;
  margin-bottom: 14px;
}
.card {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 16px 16px 12px;
  min-height: 280px;
}
.card-h {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}
.card-h h3 { margin: 0; font-size: 15px; font-weight: 700; }
.card-sub { font-size: 12px; color: var(--muted); }
.chart-box { position: relative; width: 100%; min-height: 240px; }
.chart { width: 100%; height: 280px; min-height: 240px; }
.chart-sm { height: 240px; }
.empty {
  text-align: center;
  color: var(--muted);
  font-size: 13px;
  padding: 28px 12px;
  border: 1px dashed #e2e8f0;
  border-radius: 10px;
  margin-top: 8px;
}
.empty-overlay {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px dashed #e2e8f0;
  border-radius: 10px;
  pointer-events: none;
}

.dept-list { display: flex; flex-direction: column; gap: 8px; }
.dept-row {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) minmax(60px, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 1px solid var(--line);
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
  text-align: left;
}
.dept-row:hover { border-color: #93c5fd; background: #eff6ff; }
.rank {
  width: 24px; height: 24px; border-radius: 7px; display: grid; place-items: center;
  font-size: 12px; font-weight: 700; color: #fff; background: #64748b;
}
.rank.r1 { background: var(--red); }
.rank.r2 { background: var(--orange); }
.rank.r3 { background: #ca8a04; }
.name { font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar { height: 6px; background: #e2e8f0; border-radius: 99px; overflow: hidden; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #f59e0b, #ef4444); border-radius: inherit; }
.cnt { font-size: 13px; font-weight: 700; color: var(--orange); }

.event-list { display: flex; flex-direction: column; gap: 8px; }
.event {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(239, 68, 68, 0.2);
  background: rgba(254, 242, 242, 0.7);
  border-radius: 10px;
  padding: 10px 12px;
  cursor: pointer;
}
.event:hover { border-color: rgba(239, 68, 68, 0.45); background: #fef2f2; }
.event-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }
.event-top time { font-size: 12px; color: var(--muted); }
.event-body { font-size: 13px; color: #334155; line-height: 1.45; }

.health-card { min-height: auto; }
.health-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.health-item {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px; border-radius: 10px; background: #f8fafc; border: 1px solid var(--line);
  font-size: 13px;
}
.health-item em { margin-left: auto; font-style: normal; color: var(--muted); font-size: 12px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #94a3b8; }
.dot.up { background: var(--green); box-shadow: 0 0 0 3px rgba(22, 163, 74, 0.15); }
.dot.down { background: var(--red); }
.dot.off { background: #94a3b8; }
.sched { margin: 12px 0 0; font-size: 12px; color: var(--muted); }

.wb-skel { display: grid; gap: 12px; }
.sk { background: linear-gradient(90deg, #f1f5f9, #e2e8f0, #f1f5f9); background-size: 200% 100%; animation: sh 1.2s linear infinite; border-radius: 12px; }
.sk.hero { height: 96px; }
.sk-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.sk.card { height: 110px; }
.sk.panel { height: 260px; }
@keyframes sh { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }

@media (max-width: 1100px) {
  .kpi-grid, .meta-grid, .main-grid, .health-grid, .sk-row { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 720px) {
  .wb-hero { flex-direction: column; }
  .kpi-grid, .meta-grid, .main-grid, .health-grid, .sk-row { grid-template-columns: 1fr; }
  .dept-row { grid-template-columns: 28px minmax(0, 1fr) auto; }
  .bar { display: none; }
}
</style>
