<template>
  <section class="tl-stats-page">
    <PageHeader
      title="病历时效统计分析"
      description="科室与医生锁定排名、规则节点超时分布与趋势"
    >
      <template #actions>
        <el-button :loading="loading" @click="reload(true)">刷新</el-button>
        <el-button type="primary" plain @click="$router.push('/quality/timeliness-monthly')">
          前往月度考核
        </el-button>
      </template>
    </PageHeader>

    <!-- 筛选区（每个控件带持久中文标签） -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-row">
        <div class="ma-field">
          <label class="ma-field__label">快捷周期</label>
          <el-radio-group v-model="quickMode" size="small" @change="applyQuickMode">
            <el-radio-button value="last7">近7天</el-radio-button>
            <el-radio-button value="month">本月</el-radio-button>
            <el-radio-button value="prevMonth">上月</el-radio-button>
            <el-radio-button value="last30">近30天</el-radio-button>
            <el-radio-button value="custom">自定义</el-radio-button>
          </el-radio-group>
        </div>
        <div class="ma-field">
          <label class="ma-field__label">统计周期</label>
          <el-date-picker
            v-model="dateRange"
            type="daterange"
            value-format="YYYY-MM-DD"
            range-separator="至"
            start-placeholder="开始日期"
            end-placeholder="结束日期"
            size="small"
            :disabled="quickMode !== 'custom'"
            @change="reload(true)"
          />
        </div>
        <div class="ma-field">
          <label class="ma-field__label">科室</label>
          <el-select
            v-model="deptFilter"
            filterable
            clearable
            placeholder="全部可见科室"
            size="small"
            style="width: 200px"
            @change="reload(true)"
          >
            <el-option
              v-for="d in departments"
              :key="d.id"
              :label="d.name"
              :value="d.code || d.name"
            />
          </el-select>
        </div>
      </div>
    </el-card>

    <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="stats-alert" />

    <!-- KPI 六卡 -->
    <SummaryStrip :items="summaryItems" :loading="loading" />

    <!-- 双图 -->
    <div v-if="hasData" class="chart-grid">
      <div class="chart-card">
        <div class="chart-card__head">
          <h3>科室锁定排名 TOP{{ topN }}</h3>
          <el-radio-group v-model="deptSort" size="small" @change="renderDeptChart">
            <el-radio-button value="locked">按锁定次数</el-radio-button>
            <el-radio-button value="overdue">按超时未完成</el-radio-button>
            <el-radio-button value="penalty">按扣罚金额</el-radio-button>
          </el-radio-group>
        </div>
        <div ref="deptChartEl" class="chart-box-lg" />
        <p class="chart-hint">点击柱形可跳转该科室的在院时效台账</p>
      </div>
      <div class="chart-card">
        <div class="chart-card__head"><h3>规则节点超时分布</h3></div>
        <div ref="ruleChartEl" class="chart-box-lg" />
        <p class="chart-hint">红=超时未完成、橙=超时完成；点击柱形跳转对应规则台账</p>
      </div>
    </div>

    <!-- 医生锁定排名 -->
    <div v-if="hasData" class="chart-card doctor-card">
      <div class="chart-card__head">
        <h3>医生锁定排名</h3>
        <div class="doctor-toolbar">
          <el-radio-group v-model="doctorSort" size="small" @change="page = 1">
            <el-radio-button value="locked">按锁定次数</el-radio-button>
            <el-radio-button value="overdue">按超时未完成</el-radio-button>
            <el-radio-button value="penalty">按扣罚金额</el-radio-button>
          </el-radio-group>
          <div class="ma-field">
            <label class="ma-field__label">医生搜索</label>
            <el-input
              v-model="doctorKeyword"
              clearable
              placeholder="输入医生姓名或工号"
              size="small"
              style="width: 200px"
            />
          </div>
        </div>
      </div>
      <el-table :data="pagedDoctors" border stripe size="small" max-height="420">
        <el-table-column label="排名" width="70" align="center">
          <template #default="scope">
            <span class="rank-badge" :class="'rank-' + Math.min(scope.$index + 1, 3)">
              {{ scope.$index + 1 }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="医生" min-width="120">
          <template #default="{ row }">{{ row.doctor_name || '未登记医师' }}</template>
        </el-table-column>
        <el-table-column label="工号" width="100">
          <template #default="{ row }">{{ row.doctor_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="科室" min-width="130">
          <template #default="{ row }">{{ row.dept_name || row.dept_code || '—' }}</template>
        </el-table-column>
        <el-table-column label="锁定次数" width="100" align="center">
          <template #default="{ row }">
            <b class="locked-num">{{ row.locked_count }}</b>
          </template>
        </el-table-column>
        <el-table-column label="超时未完成" width="100" align="center">
          <template #default="{ row }">{{ row.overdue_count }}</template>
        </el-table-column>
        <el-table-column label="事件总数" width="90" align="center">
          <template #default="{ row }">{{ row.total_events }}</template>
        </el-table-column>
        <el-table-column label="按时率" width="140">
          <template #default="{ row }">
            <el-progress :percentage="row.on_time_rate" :stroke-width="8" />
          </template>
        </el-table-column>
        <el-table-column label="平均超时(小时)" width="120" align="center">
          <template #default="{ row }">{{ row.avg_overdue_hours }}</template>
        </el-table-column>
        <el-table-column label="有效扣罚(元)" width="110" align="center">
          <template #default="{ row }">{{ fmtMoney(row.penalty_amount_total) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button
              link type="primary" size="small"
              @click="goDeptLedger(row.dept_code, row.doctor_code)"
            >查看台账</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page"
        :page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="filteredDoctors.length"
        layout="total, sizes, prev, pager, next"
        class="doctor-pagination"
        @update:page-size="(s: number) => (pageSize = s)"
      />
    </div>

    <!-- 每日趋势 -->
    <div v-if="hasData" class="chart-card trend-card">
      <div class="chart-card__head"><h3>每日趋势</h3></div>
      <div ref="trendChartEl" class="chart-box-trend" />
    </div>
  </section>
</template>

<script setup lang="ts">
// 病历时效统计分析专页（WP03 T2，064 总计划需求 4）。
// 数据源：GET /api/timeliness/stats/analytics（WP03 后端聚合，口径与 stats/monthly 一致）。
import { computed, onBeforeUnmount, onMounted, ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import PageHeader from '@/components/base/PageHeader.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import { fetchTimelinessAnalytics, type TimelinessAnalytics } from '@/api/endpoints/timelinessStats'
import { fetchTimelinessDictsApi } from './api'
import type { DepartmentOption } from './types'

// daterange value-format 绑定需要 dayjs 兼容；这里用字符串处理
type DateRange = [string, string] | null

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()

const loading = ref(false)
const loadError = ref('')
const analytics = ref<TimelinessAnalytics | null>(null)
const departments = ref<DepartmentOption[]>([])
const topN = 15

const quickMode = ref<'last7' | 'month' | 'prevMonth' | 'last30' | 'custom'>('month')
const dateRange = ref<DateRange>(null)
const deptFilter = ref('')
const deptSort = ref<'locked' | 'overdue' | 'penalty'>('locked')
const doctorSort = ref<'locked' | 'overdue' | 'penalty'>('locked')
const doctorKeyword = ref('')
const page = ref(1)
const pageSize = ref(20)

const deptChartEl = ref<HTMLDivElement | null>(null)
const ruleChartEl = ref<HTMLDivElement | null>(null)
const trendChartEl = ref<HTMLDivElement | null>(null)
let deptChart: echarts.ECharts | null = null
let ruleChart: echarts.ECharts | null = null
let trendChart: echarts.ECharts | null = null
let chartRo: ResizeObserver | null = null

const C = {
  muted: '#64748b',
  axis: '#cbd5e1',
  split: '#e2e8f0',
  tipBg: 'rgba(15,23,42,.94)',
  tipBorder: '#2563eb',
  blue: '#2563eb',
  red: '#ef4444',
  orange: '#f59e0b',
  cyan: '#0891b2',
}

function fmtMoney(v: number): string {
  return Number(v || 0).toLocaleString('zh-CN')
}

function computeRange(mode: typeof quickMode.value): DateRange {
  const now = new Date()
  const fmt = (d: Date) =>
    `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  if (mode === 'last7') {
    const from = new Date(now)
    from.setDate(from.getDate() - 6)
    return [fmt(from), fmt(now)]
  }
  if (mode === 'month') {
    return [fmt(new Date(now.getFullYear(), now.getMonth(), 1)), fmt(now)]
  }
  if (mode === 'prevMonth') {
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1)
    const last = new Date(now.getFullYear(), now.getMonth(), 0)
    return [fmt(first), fmt(last)]
  }
  if (mode === 'last30') {
    const from = new Date(now)
    from.setDate(from.getDate() - 29)
    return [fmt(from), fmt(now)]
  }
  return dateRange.value
}

function applyQuickMode(): void {
  if (quickMode.value !== 'custom') {
    dateRange.value = computeRange(quickMode.value)
    reload(true)
  }
}

async function reload(force = false): Promise<void> {
  loading.value = true
  loadError.value = ''
  try {
    const range = dateRange.value || computeRange(quickMode.value) || []
    analytics.value = await fetchTimelinessAnalytics({
      date_from: range[0],
      date_to: range[1],
      dept: deptFilter.value || undefined,
      top_n: topN,
    })
    await nextTick()
    renderAllCharts()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '时效统计加载失败'
  } finally {
    loading.value = false
    void force
  }
}

const summaryItems = computed<SummaryItem[]>(() => {
  const s = analytics.value?.summary
  if (!s) return []
  return [
    { key: 'total', label: '事件总数', value: s.total_events, tone: 'info' },
    { key: 'rate', label: '按时完成率', value: `${s.on_time_rate}%`, tone: 'success' },
    { key: 'locked', label: '锁定次数', value: s.locked_count, tone: 'danger' },
    { key: 'pending', label: '待审批锁定', value: s.locked_pending, tone: 'warning' },
    { key: 'overdue', label: '超时未完成', value: s.overdue_count, tone: 'danger' },
    { key: 'penalty', label: '有效扣罚(元)', value: fmtMoney(s.penalty_amount_total), tone: 'warning' },
  ]
})

const hasData = computed(() => Boolean(analytics.value))

const sortedDeptRanking = computed(() => {
  const rows = [...(analytics.value?.dept_ranking || [])]
  const sort = deptSort.value
  rows.sort((a, b) => {
    if (sort === 'overdue') return b.overdue_count - a.overdue_count
    if (sort === 'penalty') return b.penalty_amount_total - a.penalty_amount_total
    return b.locked_count - a.locked_count
  })
  return rows
})

const filteredDoctors = computed(() => {
  const rows = [...(analytics.value?.doctor_ranking || [])]
  const sort = doctorSort.value
  rows.sort((a, b) => {
    if (sort === 'overdue') return b.overdue_count - a.overdue_count
    if (sort === 'penalty') return b.penalty_amount_total - a.penalty_amount_total
    return b.locked_count - a.locked_count
  })
  const kw = doctorKeyword.value.trim().toLowerCase()
  if (!kw) return rows
  return rows.filter(
    (r) => r.doctor_name.toLowerCase().includes(kw) || r.doctor_code.toLowerCase().includes(kw),
  )
})

const pagedDoctors = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredDoctors.value.slice(start, start + pageSize.value)
})

function goDeptLedger(deptCode: string, doctorCode: string): void {
  const query: Record<string, string> = { dept: deptCode }
  if (doctorCode) query.doctor_code = doctorCode
  void router.push({ path: '/quality/timeliness-events', query })
}

function renderDeptChart(): void {
  const rows = sortedDeptRanking.value.slice(0, topN)
  if (!deptChartEl.value || !rows.length) return
  if (!deptChart || deptChart.getDom() !== deptChartEl.value) {
    deptChart?.dispose()
    deptChart = echarts.init(deptChartEl.value, undefined, { renderer: 'canvas' })
  }
  const ordered = [...rows].reverse()
  const metricKey =
    deptSort.value === 'overdue' ? 'overdue_count'
    : deptSort.value === 'penalty' ? 'penalty_amount_total'
    : 'locked_count'
  deptChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: '#f8fafc' } },
      grid: { left: 90, right: 50, top: 10, bottom: 24 },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: C.split } }, axisLabel: { color: C.muted, fontSize: 10 } },
      yAxis: {
        type: 'category',
        data: ordered.map((r) => r.dept_name),
        inverse: true,
        axisLine: { lineStyle: { color: C.axis } },
        axisLabel: { color: '#0f172a', fontSize: 11 },
      },
      series: [{
        type: 'bar',
        data: ordered.map((r) => r[metricKey as 'locked_count']),
        itemStyle: { color: C.blue },
        barMaxWidth: 16,
        label: { show: true, position: 'right', color: C.muted, fontSize: 10 },
      }],
    },
    { notMerge: true },
  )
  deptChart.off('click')
  deptChart.on('click', (params) => {
    const row = rows[ordered.length - 1 - params.dataIndex]
    if (row) void router.push({ path: '/quality/timeliness-events', query: { dept: row.dept_code } })
  })
}

function renderRuleChart(): void {
  const rows = analytics.value?.rule_breakdown || []
  if (!ruleChartEl.value || !rows.length) return
  if (!ruleChart || ruleChart.getDom() !== ruleChartEl.value) {
    ruleChart?.dispose()
    ruleChart = echarts.init(ruleChartEl.value, undefined, { renderer: 'canvas' })
  }
  const ordered = [...rows].reverse()
  ruleChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: '#f8fafc' } },
      legend: { data: ['超时未完成', '超时完成'], textStyle: { color: C.muted, fontSize: 11 }, top: 0 },
      grid: { left: 130, right: 40, top: 28, bottom: 24 },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: C.split } }, axisLabel: { color: C.muted, fontSize: 10 } },
      yAxis: {
        type: 'category',
        data: ordered.map((r) => r.rule_name),
        inverse: true,
        axisLine: { lineStyle: { color: C.axis } },
        axisLabel: { color: '#0f172a', fontSize: 11 },
      },
      series: [
        { name: '超时未完成', type: 'bar', stack: 'total', data: ordered.map((r) => r.overdue_count), itemStyle: { color: C.red }, barMaxWidth: 16 },
        { name: '超时完成', type: 'bar', stack: 'total', data: ordered.map((r) => r.late_completed_count), itemStyle: { color: C.orange }, barMaxWidth: 16 },
      ],
    },
    { notMerge: true },
  )
  ruleChart.off('click')
  ruleChart.on('click', (params) => {
    const row = rows[ordered.length - 1 - params.dataIndex]
    if (row) void router.push({ path: '/quality/timeliness-events', query: { rule_code: row.rule_code } })
  })
}

function renderTrendChart(): void {
  const rows = analytics.value?.daily_trend || []
  if (!trendChartEl.value || !rows.length) return
  if (!trendChart || trendChart.getDom() !== trendChartEl.value) {
    trendChart?.dispose()
    trendChart = echarts.init(trendChartEl.value, undefined, { renderer: 'canvas' })
  }
  trendChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'axis', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: '#f8fafc' } },
      legend: { data: ['每日超时', '每日锁定', '按时率%'], textStyle: { color: C.muted, fontSize: 11 }, top: 0 },
      grid: { left: 46, right: 46, top: 32, bottom: 26 },
      xAxis: {
        type: 'category',
        data: rows.map((r) => r.date.slice(5)),
        axisLine: { lineStyle: { color: C.axis } },
        axisLabel: { color: C.muted, fontSize: 10 },
      },
      yAxis: [
        { type: 'value', name: '次数', splitLine: { lineStyle: { color: C.split } }, axisLabel: { color: C.muted, fontSize: 10 } },
        { type: 'value', name: '按时率%', max: 100, splitLine: { show: false }, axisLabel: { color: C.muted, fontSize: 10 } },
      ],
      series: [
        { name: '每日超时', type: 'bar', data: rows.map((r) => r.overdue), itemStyle: { color: C.red }, barMaxWidth: 16 },
        { name: '每日锁定', type: 'bar', data: rows.map((r) => r.locked), itemStyle: { color: C.blue }, barMaxWidth: 16 },
        {
          name: '按时率%', type: 'line', yAxisIndex: 1,
          data: rows.map((r) => r.on_time_rate),
          itemStyle: { color: C.cyan }, lineStyle: { width: 2 },
        },
      ],
    },
    { notMerge: true },
  )
}

function renderAllCharts(): void {
  renderDeptChart()
  renderRuleChart()
  renderTrendChart()
  if (typeof ResizeObserver !== 'undefined') {
    chartRo?.disconnect()
    chartRo = new ResizeObserver(() => {
      deptChart?.resize()
      ruleChart?.resize()
      trendChart?.resize()
    })
    for (const el of [deptChartEl.value, ruleChartEl.value, trendChartEl.value]) {
      if (el) chartRo.observe(el)
    }
  }
}

function disposeCharts(): void {
  chartRo?.disconnect()
  chartRo = null
  deptChart?.dispose()
  ruleChart?.dispose()
  trendChart?.dispose()
  deptChart = ruleChart = trendChart = null
}

onMounted(async () => {
  // 科室下拉复用台账页同一接口来源
  void fetchTimelinessDictsApi()
    .then((res) => (departments.value = res.departments || []))
    .catch(() => undefined)
  dateRange.value = computeRange('month')
  await reload(true)
})

onBeforeUnmount(() => {
  disposeCharts()
})
</script>

<style scoped>
.tl-stats-page { padding: 4px 2px 20px; color: var(--ma-text-primary); }
.filter-card { margin-bottom: 12px; }
.filter-row { display: flex; gap: 16px; flex-wrap: wrap; align-items: flex-end; }
.ma-field { display: flex; flex-direction: column; gap: 4px; }
.ma-field__label { font-size: 12px; color: var(--ma-text-secondary); }
.stats-alert { margin-bottom: 12px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.chart-card { background: #fff; border: 1px solid var(--ma-border); border-radius: var(--ma-radius); padding: 14px; }
.chart-card__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; flex-wrap: wrap; gap: 8px; }
.chart-card__head h3 { margin: 0; font-size: 14px; font-weight: 700; }
.chart-box-lg { height: 360px; }
.chart-box-trend { height: 280px; }
.chart-hint { margin: 6px 0 0; font-size: 11px; color: var(--ma-text-secondary); }
.doctor-card { margin-bottom: 16px; }
.doctor-toolbar { display: flex; gap: 12px; align-items: flex-end; flex-wrap: wrap; }
.rank-badge {
  display: inline-grid; place-items: center;
  width: 24px; height: 24px; border-radius: 50%;
  background: #94a3b8; color: #fff; font-weight: 700; font-size: 12px;
}
.rank-badge.rank-1 { background: #ef4444; }
.rank-badge.rank-2 { background: #f59e0b; }
.rank-badge.rank-3 { background: #0891b2; }
.locked-num { color: var(--el-color-danger, #ef4444); font-size: 15px; }
.doctor-pagination { margin-top: 10px; justify-content: flex-end; display: flex; }
</style>
