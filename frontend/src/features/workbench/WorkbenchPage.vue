<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
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
  fetchStatsSummary,
  fetchStatsToday,
} from '@/api/endpoints/stats'
import { fetchHealthApi } from '@/api/endpoints/health'
import { useNavigationStore } from '@/stores/navigation'

echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()
const nav = useNavigationStore()

// ── 深色科技配色 ──
const C = {
  text: '#e2f3ff',
  muted: '#8fb4d6',
  axis: 'rgba(148,163,184,.18)',
  split: 'rgba(148,163,184,.12)',
  tipBg: 'rgba(15,23,42,.96)',
  tipBorder: 'rgba(56,189,248,.25)',
  cyan: '#22d3ee',
  blue: '#3b82f6',
  green: '#22c55e',
  orange: '#f59e0b',
  red: '#ef4444',
}

const loading = ref(true)
const currentTime = ref('')
const updatedAt = ref('')
let clockTimer: ReturnType<typeof setInterval> | null = null

interface Kpis {
  date: string
  total: number
  todaySuccess: number
  todaySkipped: number
  successRate: number
  effectiveTotal: number
  inconsistencyRate: number | null
  inconsistency: number
  highRisk: number
  pendingFeedback: number
  relaySuccessRate: number | null
  relayRecentTotal: number
  relayFailed: number
  viewRate: number | null
  relayViewed: number
  relayUnviewed: number
}
const kpis = ref<Kpis>({
  date: '', total: 0, todaySuccess: 0, todaySkipped: 0, successRate: 0, effectiveTotal: 0,
  inconsistencyRate: null, inconsistency: 0, highRisk: 0, pendingFeedback: 0,
  relaySuccessRate: null, relayRecentTotal: 0, relayFailed: 0, viewRate: null,
  relayViewed: 0, relayUnviewed: 0,
})

const overallHealth = ref('healthy')
const healthComps = ref<Record<string, { status: string; latency_ms?: number }>>({})
const deptTop = ref<Array<{ dept: string; inconsistency_count: number }>>([])
const events = ref<Array<Record<string, unknown>>>([])
const relayRecent = ref<Array<Record<string, unknown>>>([])
const schedulerInfo = ref({ lastRunTime: '', nextRunTime: '', running: false })
const severityEmpty = ref(false)
const trendEmpty = ref(false)

// 图表 refs
const trendEl = ref<HTMLDivElement | null>(null)
const severityEl = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null
let severityChart: echarts.ECharts | null = null

const showRibbon = computed(() =>
  overallHealth.value !== 'healthy' ||
  kpis.value.relayFailed > 0 ||
  kpis.value.pendingFeedback > 0 ||
  kpis.value.relayUnviewed > 0,
)

function pct(v: number | null): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '--'
  return v.toFixed(1) + '%'
}

function todayStr(): string {
  const n = new Date()
  return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}-${String(n.getDate()).padStart(2, '0')}`
}

function fmtDateTime(v: unknown): string {
  if (!v) return ''
  const s = String(v)
  // 只取 yyyy-mm-dd hh:mm 部分
  return s.replace('T', ' ').slice(0, 16)
}

function cname(key: string): string {
  const map: Record<string, string> = {
    app_db: '应用数据库', business_db: '业务数据库', oracle: 'Oracle', postgresql: 'PostgreSQL',
    scheduler: '调度器', dify: 'Dify',
  }
  return map[key] || key
}

function deptTopPct(val: number): number {
  const max = Math.max(...deptTop.value.map((d) => d.inconsistency_count || 0), 1)
  return max ? Math.min(100, ((val || 0) / max) * 100) : 0
}

function go(menuId: string) {
  const item = nav.findByMenuId(menuId)
  if (item) void router.push({ name: item.entry.name })
}

function goAlert(_item: Record<string, unknown>) {
  // 高风险事件 → 质控记录详情
  void router.push({ name: 'quality-records' })
}

function disposeCharts() {
  trendChart?.dispose(); severityChart?.dispose()
  trendChart = severityChart = null
}

async function load() {
  loading.value = true
  try {
    const today = todayStr()
    const [, healthR, todayR, dailyR, severityR, todayLogsR, deptTopR,
      pendingR, schedR, relaySumR, relayRecentR] = await Promise.all([
      fetchStatsSummary().catch(() => ({})),
      fetchHealthApi().catch(() => ({ status: 'unknown', components: {} })),
      fetchStatsToday().catch(() => ({})),
      fetchStatsDaily(30).catch(() => ({ items: [] })),
      fetchStatsSeverity().catch(() => ({ items: [] })),
      apiGet<{ items?: Array<Record<string, unknown>> }>('/api/logs', { params: { page: 1, limit: 200, push_time_from: today, push_time_to: today } }).catch(() => ({ items: [] })),
      fetchAnomalyTop('dept').catch(() => ({ items: [] })),
      apiGet<{ total?: number }>('/api/qc/feedback/cases', { params: { page: 1, limit: 1, status: 'pending', days: 30 } }).catch(() => ({ total: 0 })),
      apiGet<Record<string, unknown>>('/api/scheduler/status').catch(() => ({})),
      apiGet<Record<string, unknown>>('/api/patient-qc/relay-alert/summary').catch(() => ({})),
      apiGet<{ items?: Array<Record<string, unknown>> }>('/api/patient-qc/relay-alert/logs', { params: { page: 1, limit: 5 } }).catch(() => ({ items: [] })),
    ])

    // 健康组件（过滤 dify）
    const rawComps = (healthR as { components?: Record<string, { status: string; latency_ms?: number }> }).components || {}
    healthComps.value = Object.fromEntries(Object.entries(rawComps).filter(([k]) => k !== 'dify'))
    overallHealth.value = (healthR as { status?: string }).status || 'healthy'

    // 今日 KPI
    const tTotal = Number((todayR as { total?: number }).total || 0)
    const tSuccess = Number((todayR as { success?: number }).success || 0)
    const tSkipped = Number((todayR as { skipped?: number }).skipped || 0)
    const tInconsist = Number((todayR as { inconsistency?: number }).inconsistency || 0)
    const effTotal = Math.max(0, tTotal - tSkipped)
    const pendingCases = Number((pendingR as { total?: number }).total || 0)

    const sevItems = (severityR as { items?: Array<{ severity?: string; count?: number }> }).items || []
    const highRiskItem = sevItems.find((i) => i.severity === 'high')
    const highRiskCount = Number(highRiskItem?.count || 0)

    const relaySum = relaySumR as Record<string, number>
    const rTotal = Number(relaySum.total || 0)
    const rSuccess = Number(relaySum.success || 0)
    const rFailed = Number(relaySum.failed || 0)
    const rViewed = Number(relaySum.viewed || 0)
    const rUnviewed = Number(relaySum.unviewed || 0)

    kpis.value = {
      date: today,
      total: tTotal,
      todaySuccess: tSuccess,
      todaySkipped: tSkipped,
      successRate: effTotal ? (tSuccess / effTotal) * 100 : 0,
      effectiveTotal: effTotal,
      inconsistencyRate: effTotal ? (tInconsist / effTotal) * 100 : null,
      inconsistency: tInconsist,
      highRisk: highRiskCount,
      pendingFeedback: pendingCases,
      relaySuccessRate: (relaySum.success_rate as number) ?? (rTotal ? (rSuccess / rTotal) * 100 : null),
      relayRecentTotal: rTotal,
      relayFailed: rFailed,
      viewRate: (relaySum.view_rate as number) ?? (rTotal ? (rViewed / rTotal) * 100 : null),
      relayViewed: rViewed,
      relayUnviewed: rUnviewed,
    }

    // 科室 TOP
    deptTop.value = ((deptTopR as { items?: Array<{ dept: string; inconsistency_count: number }> }).items || [])
      .slice(0, 8)

    // 高风险事件
    const tLogs = (todayLogsR as { items?: Array<Record<string, unknown>> }).items || []
    let highLogs = tLogs.filter((i) =>
      Number(i.inconsistency || 0) === 1 && (i.severity === 'high' || Number(i.risk_score || 0) >= 80))
    if (highLogs.length === 0) {
      try {
        const recent = await apiGet<{ items?: Array<Record<string, unknown>> }>('/api/logs', { params: { page: 1, limit: 50 } })
        highLogs = (recent.items || []).filter((i) =>
          Number(i.inconsistency || 0) === 1 && (i.severity === 'high' || Number(i.risk_score || 0) >= 80))
      } catch { /* ignore */ }
    }
    events.value = highLogs.slice(0, 5).map((i) => ({
      id: i.id, patient_name: i.patient_name || '--', patient_id: i.patient_id || '--',
      dept: i.dept || '--', risk_score: Number(i.risk_score || 0),
      push_time: fmtDateTime(i.push_time),
    }))

    // 前置机最近告警
    relayRecent.value = ((relayRecentR as { items?: Array<Record<string, unknown>> }).items || []).slice(0, 5)

    // 调度状态
    const sched = schedR as Record<string, unknown>
    schedulerInfo.value = {
      running: !!sched.running,
      lastRunTime: fmtDateTime((sched.last_run as Record<string, string>)?.run_time || sched.last_run),
      nextRunTime: fmtDateTime(sched.next_run),
    }

    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })

    // 空状态判断
    const dailyItems = (dailyR as { items?: Array<Record<string, unknown>> }).items || []
    severityEmpty.value = sevItems.length === 0
    trendEmpty.value = dailyItems.length === 0

    // 渲染图表
    await nextTick()
    renderTrend(dailyItems)
    renderSeverity(sevItems)
  } finally {
    loading.value = false
  }
}

function renderTrend(rows: Array<Record<string, unknown>>) {
  if (!trendEl.value) return
  trendChart?.dispose()
  trendChart = echarts.init(trendEl.value, undefined, { renderer: 'canvas' })
  trendChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: C.text, fontSize: 12 } },
    legend: { data: ['总量', '成功', '不一致', '失败'], textStyle: { color: C.muted, fontSize: 11 }, top: 0 },
    grid: { left: 40, right: 16, top: 32, bottom: 28 },
    xAxis: { type: 'category', data: rows.map((r) => String(r.date || r.day || '').slice(5)), axisLine: { lineStyle: { color: C.axis } }, axisLabel: { color: C.muted, fontSize: 10 } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: C.split } }, axisLabel: { color: C.muted, fontSize: 10 } },
    series: [
      { name: '总量', type: 'line', smooth: true, data: rows.map((r) => Number(r.total ?? r.count ?? 0)), itemStyle: { color: C.cyan } },
      { name: '成功', type: 'line', smooth: true, data: rows.map((r) => Number(r.success ?? 0)), itemStyle: { color: C.green } },
      { name: '不一致', type: 'line', smooth: true, data: rows.map((r) => Number(r.inconsistency ?? 0)), itemStyle: { color: C.red } },
      { name: '失败', type: 'line', smooth: true, data: rows.map((r) => Number(r.failed ?? 0)), itemStyle: { color: C.orange } },
    ],
  })
}

function renderSeverity(items: Array<{ severity?: string; count?: number }>) {
  if (!severityEl.value) return
  severityChart?.dispose()
  severityChart = echarts.init(severityEl.value)
  const cmap: Record<string, string> = { high: C.red, medium: C.orange, low: C.blue }
  const labels: Record<string, string> = { high: '高危', medium: '中危', low: '低危' }
  severityChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: C.text } },
    series: [{
      type: 'pie', radius: ['42%', '68%'],
      label: { color: C.muted, fontSize: 11 },
      data: items.map((i) => {
        const sev = String(i.severity || '')
        return {
          name: labels[sev] || sev || '未知',
          value: Number(i.count || 0),
          itemStyle: { color: cmap[sev] || C.cyan },
        }
      }),
    }],
  })
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

watch(loading, async (v) => {
  if (!v) {
    await nextTick()
    handleResize()
  }
})
</script>

<template>
  <div class="dash-tech">
    <!-- 骨架屏 -->
    <div v-if="loading" class="dash-skel">
      <div class="dash-hero"><div class="sk l"></div><div class="sk s"></div></div>
      <div class="dash-strip"><div class="sk s" v-for="n in 4" :key="n" /></div>
      <div class="dash-kpi"><div class="sk tall" v-for="n in 4" :key="n" /></div>
    </div>

    <template v-else>
      <!-- Hero -->
      <div class="dash-hero">
        <div>
          <div class="dash-kicker">AI Medical Quality Control</div>
          <div class="dash-title">AI质控运营态势指挥中心</div>
          <div class="dash-sub">住院病历一致性质控 · 风险预警 · 推送闭环 · 系统运行状态</div>
        </div>
        <div class="dash-hero-r">
          <div class="dash-time">{{ currentTime }}</div>
          <div v-if="updatedAt" class="dash-updated">更新 {{ updatedAt }}</div>
          <el-tag :type="overallHealth === 'healthy' ? 'success' : overallHealth === 'degraded' ? 'warning' : 'danger'" size="small">
            {{ overallHealth === 'healthy' ? '系统正常' : overallHealth === 'degraded' ? '部分异常' : '系统异常' }}
          </el-tag>
          <el-button size="small" class="dash-refresh" @click="load" :loading="loading">刷新</el-button>
        </div>
      </div>

      <!-- 指挥条 -->
      <div class="dash-strip">
        <div class="cmd-item" @click="go('patient-qc')">
          <span class="cmd-label">今日不一致率</span>
          <b>{{ kpis.inconsistencyRate !== null ? pct(kpis.inconsistencyRate) : '--' }}</b>
        </div>
        <div class="cmd-item" @click="go('relay-alert-logs')">
          <span class="cmd-label">前置机失败</span>
          <b class="cmd-danger">{{ kpis.relayFailed || 0 }}</b>
        </div>
        <div class="cmd-item" @click="go('relay-alert-logs')">
          <span class="cmd-label">医生未查看</span>
          <b class="cmd-warn">{{ kpis.relayUnviewed || 0 }}</b>
        </div>
        <div class="cmd-item" @click="go('scheduler')">
          <span class="cmd-label">调度状态</span>
          <b class="cmd-cyan">{{ schedulerInfo.running ? '运行中' : schedulerInfo.lastRunTime ? '已启用' : '已停用' }}</b>
        </div>
      </div>

      <!-- 告警横幅 -->
      <div v-if="showRibbon" class="dash-ribbon">
        <div class="ribbon-main"><span class="ribbon-dot" /><span>当前存在需要关注的运行或闭环事项</span></div>
        <div class="ribbon-actions">
          <button v-if="overallHealth !== 'healthy'" @click="go('health')">查看系统健康</button>
          <button v-if="kpis.relayFailed > 0 || kpis.relayUnviewed > 0" @click="go('relay-alert-logs')">查看前置机告警</button>
          <button v-if="kpis.pendingFeedback > 0" @click="go('feedback')">处理质控反馈</button>
        </div>
      </div>

      <!-- 核心 KPI -->
      <div class="sect-title"><span class="sect-dot" />今日核心态势</div>
      <div class="kpi-core">
        <div class="kpi-card kpi-big" @click="go('audit')">
          <div class="kpi-label">今日核查量</div>
          <div class="kpi-val kpi-cyan">{{ kpis.total || 0 }}</div>
          <div class="kpi-sub">日期 {{ kpis.date || '--' }}</div>
        </div>
        <div class="kpi-card kpi-big" @click="go('patient-qc')">
          <div class="kpi-label"><span class="badge badge-red">不一致</span></div>
          <div class="kpi-val kpi-danger">{{ kpis.inconsistency || 0 }}</div>
          <div class="kpi-sub kpi-sub-w">点击查看患者质控</div>
        </div>
        <div class="kpi-card kpi-big" @click="go('patient-qc')">
          <div class="kpi-label"><span class="badge badge-red">累计高危</span></div>
          <div class="kpi-val kpi-danger">{{ kpis.highRisk || 0 }}</div>
          <div class="kpi-sub">高危维度数</div>
        </div>
        <div class="kpi-card kpi-big" @click="go('feedback')">
          <div class="kpi-label"><span class="badge badge-orange">待处理</span></div>
          <div class="kpi-val kpi-warn">{{ kpis.pendingFeedback || 0 }}</div>
          <div class="kpi-sub">点击进入质控反馈</div>
        </div>
      </div>

      <!-- 辅助 KPI -->
      <div class="kpi-aux">
        <div class="aux-item" @click="go('audit')">
          <span class="aux-label">AI成功率</span>
          <b class="kpi-success">{{ kpis.effectiveTotal ? pct(kpis.successRate) : '--' }}</b>
          <span class="aux-sub">有效 {{ kpis.effectiveTotal || 0 }} 例</span>
        </div>
        <div class="aux-item" @click="go('audit')">
          <span class="aux-label">今日推送成功</span>
          <b class="kpi-success">{{ kpis.todaySuccess || 0 }}</b>
          <span class="aux-sub">跳过 {{ kpis.todaySkipped || 0 }} 例</span>
        </div>
        <div class="aux-item" @click="go('relay-alert-logs')">
          <span class="aux-label">前置机成功率</span>
          <b :class="kpis.relayFailed > 0 ? 'kpi-warn' : 'kpi-success'">{{ kpis.relaySuccessRate !== null ? pct(kpis.relaySuccessRate) : '--' }}</b>
          <span class="aux-sub">失败 {{ kpis.relayFailed || 0 }} 条</span>
        </div>
        <div class="aux-item" @click="go('relay-alert-logs')">
          <span class="aux-label">医生查看率</span>
          <b :class="kpis.relayUnviewed > 0 ? 'kpi-warn' : 'kpi-success'">{{ kpis.viewRate !== null ? pct(kpis.viewRate) : '--' }}</b>
          <span class="aux-sub">未查看 {{ kpis.relayUnviewed || 0 }} 条</span>
        </div>
      </div>

      <!-- 面板网格 -->
      <div class="dash-grid">
        <div class="panel">
          <div class="panel-title">风险等级分布</div>
          <div ref="severityEl" class="chart chart-sm" />
          <div v-if="severityEmpty" class="dash-empty">暂无不一致风险数据</div>
        </div>
        <div class="panel">
          <div class="panel-title">系统健康矩阵</div>
          <div v-if="Object.keys(healthComps).length" class="health-grid">
            <div v-for="(comp, key) in healthComps" :key="key" class="health-mini">
              <span class="health-dot" :class="comp.status === 'up' || comp.status === 'running' ? 'up' : comp.status === 'disabled' ? 'disabled' : 'down'" />
              <span class="health-name">{{ cname(String(key)) }}</span>
              <span class="health-latency">{{ comp.latency_ms ? comp.latency_ms + 'ms' : '--' }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无组件状态" :image-size="50" />
        </div>
        <div class="panel panel-wide">
          <div class="panel-title">近30天质控趋势</div>
          <div ref="trendEl" class="chart" />
          <div v-if="trendEmpty" class="dash-empty">暂无近30天趋势数据</div>
        </div>
        <div class="panel">
          <div class="panel-title">科室风险 TOP</div>
          <div v-if="deptTop.length" class="dept-list">
            <div v-for="(item, idx) in deptTop" :key="item.dept" class="dept-row" @click="go('patient-qc')">
              <span class="dept-rank" :class="'rank-' + Math.min(idx + 1, 3)">{{ idx + 1 }}</span>
              <span class="dept-name">{{ item.dept || '未知' }}</span>
              <div class="dept-bar"><div class="dept-bar-fill" :style="{ width: deptTopPct(item.inconsistency_count) + '%' }" /></div>
              <span class="dept-count">{{ item.inconsistency_count || 0 }}</span>
            </div>
          </div>
          <el-empty v-else description="暂无数据" :image-size="50" />
        </div>
        <div class="panel">
          <div class="panel-title">高风险事件流</div>
          <div class="event-section">
            <div v-if="events.length" class="event-list">
              <div v-for="item in events" :key="String(item.id)" class="event-item" @click="goAlert(item)">
                <div class="event-dot" />
                <div class="event-content">
                  <div class="event-head"><span class="event-time">{{ item.push_time }}</span><el-tag size="small" type="danger">高风险</el-tag></div>
                  <div class="event-body">患者 {{ item.patient_name }}（{{ item.patient_id }}）｜{{ item.dept }}｜风险分 {{ item.risk_score || 0 }}</div>
                </div>
              </div>
            </div>
            <el-empty v-else description="最近暂无高风险告警" :image-size="50" />
            <div v-if="relayRecent.length" class="relay-mini-feed">
              <div class="relay-mini-title">前置机最近告警</div>
              <div v-for="item in relayRecent" :key="String(item.id)" class="relay-mini-item">
                <span class="relay-mini-status" :class="'is-' + (item.status || 'unknown')" />
                <span class="relay-mini-text">{{ item.patient_id }}｜{{ item.dept }}</span>
                <span class="relay-mini-time">{{ fmtDateTime(item.created_at) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 调度条 -->
      <div v-if="schedulerInfo.lastRunTime" class="sched-bar">
        最近调度：{{ schedulerInfo.lastRunTime }}
        <span v-if="schedulerInfo.nextRunTime">｜下次：{{ schedulerInfo.nextRunTime }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ===== 深色科技驾驶舱 ===== */
.dash-tech {
  --bg: #020617;
  --panel: rgba(15, 23, 42, 0.82);
  --panel-strong: rgba(8, 15, 32, 0.92);
  --border: rgba(56, 189, 248, 0.22);
  --border-strong: rgba(56, 189, 248, 0.42);
  --text: #e2f3ff;
  --muted: #8fb4d6;
  --cyan: #22d3ee;
  --blue: #3b82f6;
  --green: #22c55e;
  --orange: #f59e0b;
  --red: #ef4444;
  --shadow: 0 18px 60px rgba(8, 47, 73, 0.24);

  position: relative;
  padding: 18px 20px 12px;
  margin: -16px -20px;
  background:
    radial-gradient(ellipse at 50% 0%, rgba(37, 99, 235, 0.10) 0%, transparent 55%),
    radial-gradient(ellipse at 80% 20%, rgba(6, 182, 212, 0.06) 0%, transparent 45%),
    radial-gradient(ellipse at 20% 80%, rgba(59, 130, 246, 0.05) 0%, transparent 45%),
    linear-gradient(180deg, #020617 0%, #0a1122 40%, #0c1529 100%);
  min-height: calc(100vh - 68px);
  color: var(--text);
}
.dash-tech::before {
  content: ''; position: absolute; inset: 0; z-index: 0; pointer-events: none;
  background: repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(56, 189, 248, 0.015) 2px, rgba(56, 189, 248, 0.015) 4px);
  mask-image: linear-gradient(180deg, transparent 0%, rgba(0,0,0,.3) 30%, rgba(0,0,0,.3) 70%, transparent 100%);
  animation: dash-scan 8s linear infinite;
}
@keyframes dash-scan { 0% { transform: translateY(0); } 100% { transform: translateY(4px); } }
.dash-tech > * { position: relative; z-index: 1; }
.dash-tech :deep(.el-empty__description) { color: #64748b; }

/* Hero */
.dash-hero { display: flex; justify-content: space-between; align-items: center; padding: 20px 26px; margin-bottom: 20px; border: 1px solid var(--border); border-radius: 16px; background: var(--panel-strong); backdrop-filter: blur(12px); box-shadow: 0 0 40px rgba(56, 189, 248, 0.04), inset 0 1px 0 rgba(56, 189, 248, 0.08); }
.dash-kicker { font-size: 12px; color: var(--muted); letter-spacing: .4px; margin-bottom: 4px; }
.dash-title { font-size: 26px; font-weight: 700; color: var(--text); line-height: 1.3; }
.dash-sub { font-size: 13px; color: var(--muted); margin-top: 4px; max-width: 500px; }
.dash-hero-r { display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
.dash-time { font-size: 14px; color: var(--muted); }
.dash-updated { font-size: 12px; color: var(--muted); padding: 3px 8px; border: 1px solid rgba(148,163,184,.18); border-radius: 999px; background: rgba(15,23,42,.5); }
.dash-refresh { border-color: var(--border) !important; color: var(--muted) !important; background: rgba(15,23,42,.6) !important; }

/* 指挥条 */
.dash-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
.cmd-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 48px; padding: 10px 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); backdrop-filter: blur(8px); cursor: pointer; transition: border-color .2s, background .2s, transform .2s; }
.cmd-item:hover { border-color: var(--border-strong); background: rgba(56,189,248,.06); transform: translateY(-1px); }
.cmd-label { font-size: 12px; color: var(--muted); }
.cmd-item b { font-size: 15px; color: var(--text); }
.cmd-danger { color: var(--red) !important; }
.cmd-warn { color: var(--orange) !important; }
.cmd-cyan { color: var(--cyan) !important; }

/* 告警横幅 */
.dash-ribbon { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -8px 0 18px; padding: 10px 14px; border: 1px solid rgba(245,158,11,.28); border-radius: 12px; background: rgba(245,158,11,.08); }
.ribbon-main { display: inline-flex; align-items: center; gap: 8px; color: var(--text); font-size: 13px; font-weight: 600; }
.ribbon-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--orange); box-shadow: 0 0 10px rgba(245,158,11,.6); }
.ribbon-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.ribbon-actions button { min-height: 26px; padding: 0 10px; border: 1px solid rgba(245,158,11,.35); border-radius: 999px; background: rgba(15,23,42,.46); color: var(--orange); font-size: 12px; cursor: pointer; }
.ribbon-actions button:hover { border-color: rgba(245,158,11,.7); background: rgba(245,158,11,.12); }

/* 标题 */
.sect-title { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
.sect-dot { width: 4px; height: 18px; border-radius: 2px; background: var(--cyan); box-shadow: 0 0 8px var(--cyan); }

/* 核心 KPI */
.kpi-core { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 14px; }
.kpi-big { padding: 22px !important; }
.kpi-card { position: relative; overflow: hidden; padding: 18px 20px; border-radius: 14px; background: var(--panel); border: 1px solid var(--border); backdrop-filter: blur(8px); box-shadow: var(--shadow), inset 0 1px 0 rgba(56, 189, 248, 0.06); cursor: pointer; transition: border-color .3s, box-shadow .3s, transform .2s; }
.kpi-card:hover { border-color: var(--border-strong); box-shadow: 0 0 36px rgba(56, 189, 248, 0.10); transform: translateY(-2px); }
.kpi-label { font-size: 13px; color: var(--muted); margin-bottom: 8px; display: flex; align-items: center; gap: 6px; }
.kpi-val { font-size: 38px; font-weight: 700; color: var(--text); line-height: 1.1; }
.kpi-sub { font-size: 12px; color: #64748b; margin-top: 6px; }
.kpi-sub-w { color: var(--orange); }
.kpi-cyan { color: var(--cyan); }
.kpi-success { color: var(--green); }
.kpi-warn { color: var(--orange); }
.kpi-danger { color: var(--red); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge-red { background: rgba(239,68,68,.15); color: var(--red); }
.badge-orange { background: rgba(245,158,11,.15); color: var(--orange); }

/* 辅助 KPI */
.kpi-aux { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin-bottom: 20px; }
.aux-item { display: flex; flex-direction: column; gap: 4px; padding: 12px 16px; border: 1px solid var(--border); border-radius: 10px; background: var(--panel); backdrop-filter: blur(8px); cursor: pointer; transition: border-color .3s, background .2s; }
.aux-item:hover { border-color: var(--border-strong); background: rgba(56,189,248,.06); }
.aux-label { font-size: 12px; color: var(--muted); }
.aux-item b { font-size: 20px; font-weight: 700; }
.aux-sub { font-size: 11px; color: #64748b; }

/* 面板网格 */
.dash-grid { display: grid; grid-template-columns: 1fr 1.3fr 1fr; gap: 16px; margin-bottom: 16px; }
.panel { border-radius: 14px; padding: 18px 20px; background: var(--panel); border: 1px solid var(--border); backdrop-filter: blur(8px); box-shadow: 0 0 24px rgba(56, 189, 248, 0.03); margin-bottom: 16px; transition: border-color .3s, box-shadow .3s; }
.panel:hover { border-color: var(--border-strong); }
.panel-wide { grid-column: span 2; }
.panel-title { font-size: 15px; font-weight: 600; color: var(--text); margin-bottom: 12px; display: flex; align-items: center; gap: 8px; }
.chart { height: 300px; min-height: 240px; width: 100%; }
.chart-sm { height: 240px; min-height: 200px; }
.dash-empty { text-align: center; padding: 20px 12px; font-size: 13px; color: #64748b; border: 1px dashed rgba(56, 189, 248, 0.16); border-radius: 10px; margin-top: 8px; }

/* 健康矩阵 */
.health-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.health-mini { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px; background: var(--panel-strong); border: 1px solid var(--border); }
.health-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
.health-dot.up, .health-dot.running { background: var(--green); box-shadow: 0 0 6px rgba(34,197,94,.35); }
.health-dot.down { background: var(--red); box-shadow: 0 0 6px rgba(239,68,68,.35); }
.health-dot.disabled { background: #475569; }
.health-name { font-size: 12px; color: var(--muted); flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.health-latency { font-size: 11px; color: #64748b; }

/* 科室 TOP */
.dept-list { display: flex; flex-direction: column; gap: 6px; }
.dept-row { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 10px; background: var(--panel-strong); border: 1px solid var(--border); cursor: pointer; transition: border-color .2s, background .2s; }
.dept-row:hover { border-color: var(--border-strong); background: rgba(56,189,248,.06); }
.dept-rank { width: 24px; height: 24px; border-radius: 6px; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700; color: #fff; background: #475569; flex-shrink: 0; }
.dept-rank.rank-1 { background: var(--red); box-shadow: 0 0 8px rgba(239,68,68,.3); }
.dept-rank.rank-2 { background: var(--orange); box-shadow: 0 0 8px rgba(245,158,11,.3); }
.dept-rank.rank-3 { background: #e6a23c; }
.dept-name { flex: 1; font-size: 13px; color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dept-bar { flex: 1; max-width: 90px; height: 6px; border-radius: 3px; background: rgba(148,163,184,.16); overflow: hidden; margin: 0 8px; }
.dept-bar-fill { height: 100%; border-radius: 3px; background: linear-gradient(90deg, var(--orange), var(--red)); transition: width .4s; }
.dept-count { font-size: 13px; font-weight: 600; color: var(--orange); }

/* 事件流 */
.event-section { display: flex; flex-direction: column; gap: 12px; }
.event-list { display: flex; flex-direction: column; gap: 8px; }
.event-item { position: relative; display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px; border: 1px solid rgba(239,68,68,.25); border-radius: 10px; background: rgba(239,68,68,.06); cursor: pointer; transition: background .2s, border-color .2s; }
.event-item:hover { background: rgba(239,68,68,.10); border-color: rgba(239,68,68,.4); }
.event-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--red); margin-top: 5px; flex-shrink: 0; box-shadow: 0 0 8px rgba(239,68,68,.5); animation: event-pulse 2s ease-in-out infinite; }
@keyframes event-pulse { 0%,100%{opacity:.8} 50%{opacity:1; box-shadow:0 0 14px rgba(239,68,68,.7)} }
.event-content { flex: 1; min-width: 0; }
.event-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 4px; }
.event-time { font-size: 12px; color: #64748b; }
.event-body { font-size: 12px; color: var(--muted); line-height: 1.5; word-break: break-word; }

/* 前置机 mini feed */
.relay-mini-feed { border-top: 1px solid rgba(56, 189, 248, 0.14); padding-top: 10px; display: flex; flex-direction: column; gap: 6px; }
.relay-mini-title { font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 2px; }
.relay-mini-item { display: grid; grid-template-columns: 10px minmax(0, 1fr) auto; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 9px; background: var(--panel-strong); border: 1px solid var(--border); }
.relay-mini-status { width: 7px; height: 7px; border-radius: 50%; background: var(--muted); }
.relay-mini-status.is-success { background: var(--green); box-shadow: 0 0 8px rgba(34,197,94,.35); }
.relay-mini-status.is-failed { background: var(--red); box-shadow: 0 0 8px rgba(239,68,68,.35); }
.relay-mini-status.is-pending { background: var(--orange); box-shadow: 0 0 8px rgba(245,158,11,.35); }
.relay-mini-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--muted); font-size: 12px; }
.relay-mini-time { color: #64748b; font-size: 11px; white-space: nowrap; }

/* 调度条 */
.sched-bar { text-align: center; padding: 14px 0 6px; font-size: 12px; color: #64748b; border-top: 1px solid rgba(56, 189, 248, 0.12); margin-top: 8px; }

/* 骨架屏 */
.dash-skel { padding: 20px; }
.dash-skel .sk { height: 14px; background: rgba(148,163,184,.15); border-radius: 6px; margin-bottom: 8px; animation: sk-pulse 1.5s ease-in-out infinite; }
.dash-skel .l { width: 180px; } .dash-skel .s { width: 80px; } .dash-skel .tall { height: 28px; width: 100%; margin-top: 8px; }
.dash-skel .dash-hero { padding: 20px; } .dash-skel .dash-strip { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 16px 0; }
.dash-skel .dash-kpi { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-top: 16px; }
.dash-skel .dash-kpi > div { height: 100px; border-radius: 14px; background: var(--panel); border: 1px solid var(--border); }
@keyframes sk-pulse { 0%,100%{opacity:.3} 50%{opacity:.6} }

/* 响应式 */
@media (max-width: 1280px) {
  .kpi-core, .kpi-aux, .dash-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .dash-grid { grid-template-columns: 1fr; }
  .panel-wide { grid-column: auto; }
  .flow-line { flex-wrap: wrap; gap: 8px; }
}
@media (max-width: 768px) {
  .dash-tech { padding: 12px; margin: -12px; }
  .dash-hero { flex-direction: column; align-items: flex-start; gap: 10px; }
  .kpi-core, .kpi-aux, .dash-strip { grid-template-columns: 1fr; }
  .kpi-val { font-size: 30px; }
  .flow-node { padding: 8px 12px; }
}

@media (prefers-reduced-motion: reduce) {
  .dash-tech::before, .flow-arrow, .event-dot { animation: none; }
  .kpi-card, .cmd-item { transition: none; }
}
</style>
