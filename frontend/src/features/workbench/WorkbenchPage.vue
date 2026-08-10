<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { LineChart, PieChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import PageHeader from '@/components/base/PageHeader.vue'
import SummaryStrip, { type SummaryItem } from '@/components/base/SummaryStrip.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import {
  fetchAnomalyTop,
  fetchStatsDaily,
  fetchStatsSeverity,
  fetchStatsSummary,
  fetchStatsToday,
} from '@/api/endpoints/stats'
import { fetchHealthApi } from '@/api/endpoints/health'
import { toUserMessage } from '@/api/errors'
import { useNavigationStore } from '@/stores/navigation'

echarts.use([LineChart, PieChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()
const nav = useNavigationStore()

const loading = ref(false)
const error = ref('')
const summary = ref<Record<string, unknown>>({})
const today = ref<Record<string, unknown>>({})
const healthStatus = ref('—')
const trendEl = ref<HTMLDivElement | null>(null)
const pieEl = ref<HTMLDivElement | null>(null)
let trendChart: echarts.ECharts | null = null
let pieChart: echarts.ECharts | null = null

const items = computed<SummaryItem[]>(() => [
  { key: 'total', label: '累计推送', value: Number(summary.value.total ?? 0) },
  { key: 'success', label: '成功', value: Number(summary.value.success ?? 0), tone: 'success' },
  { key: 'failed', label: '失败', value: Number(summary.value.failed ?? 0), tone: 'danger' },
  { key: 'today', label: '今日总量', value: Number(today.value.total ?? 0), tone: 'info' },
  {
    key: 'today_skip',
    label: '今日跳过',
    value: Number(today.value.skipped ?? 0),
    tone: 'warning',
  },
  { key: 'health', label: '系统健康', value: healthStatus.value },
])

function disposeCharts() {
  trendChart?.dispose()
  pieChart?.dispose()
  trendChart = null
  pieChart = null
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [s, t, daily, severity, health] = await Promise.all([
      fetchStatsSummary().catch(() => ({})),
      fetchStatsToday().catch(() => ({})),
      fetchStatsDaily(30).catch(() => ({ items: [] })),
      fetchStatsSeverity().catch(() => ({ items: [] })),
      fetchHealthApi().catch(() => ({ status: 'unknown' })),
    ])
    summary.value = (s || {}) as Record<string, unknown>
    today.value = (t || {}) as Record<string, unknown>
    healthStatus.value = String((health as { status?: string }).status || 'unknown')

    await fetchAnomalyTop('dept').catch(() => ({ items: [] }))

    // charts
    if (trendEl.value) {
      trendChart?.dispose()
      trendChart = echarts.init(trendEl.value)
      const rows = Array.isArray((daily as { items?: unknown[] }).items)
        ? ((daily as { items: Array<Record<string, unknown>> }).items)
        : []
      trendChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 40, right: 16, top: 24, bottom: 28 },
        xAxis: {
          type: 'category',
          data: rows.map((r) => String(r.date || r.day || '')),
        },
        yAxis: { type: 'value' },
        series: [
          {
            type: 'line',
            smooth: true,
            name: '总量',
            data: rows.map((r) => Number(r.total ?? r.count ?? 0)),
          },
        ],
      })
    }
    if (pieEl.value) {
      pieChart?.dispose()
      pieChart = echarts.init(pieEl.value)
      const rows = Array.isArray((severity as { items?: unknown[] }).items)
        ? ((severity as { items: Array<Record<string, unknown>> }).items)
        : []
      pieChart.setOption({
        tooltip: { trigger: 'item' },
        series: [
          {
            type: 'pie',
            radius: ['40%', '68%'],
            data: rows.map((r) => ({
              name: String(r.severity || r.name || 'unknown'),
              value: Number(r.count ?? r.total ?? 0),
            })),
          },
        ],
      })
    }
  } catch (e) {
    error.value = toUserMessage(e, '加载工作台失败')
  } finally {
    loading.value = false
  }
}

function go(menuId: string) {
  const item = nav.findByMenuId(menuId)
  if (item) void router.push({ name: item.entry.name })
}

onMounted(() => {
  void load()
  window.addEventListener('resize', () => {
    trendChart?.resize()
    pieChart?.resize()
  })
})

onUnmounted(() => {
  disposeCharts()
})
</script>

<template>
  <div class="page-workbench">
    <PageHeader title="工作台" description="待办概览、异常趋势与系统链路状态。ECharts 仅在本页加载。">
      <template #actions>
        <el-button :loading="loading" @click="load">刷新</el-button>
        <el-button v-if="nav.isMenuAllowed('patient-qc')" @click="go('patient-qc')">患者质控</el-button>
        <el-button v-if="nav.isMenuAllowed('feedback')" @click="go('feedback')">整改反馈</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="error && !loading" :message="error" @retry="load" />
    <template v-else>
      <SummaryStrip :items="items" :loading="loading" />
      <el-row :gutter="12">
        <el-col :xs="24" :lg="14">
          <el-card shadow="never" class="chart-card">
            <template #header>近 30 日趋势</template>
            <div ref="trendEl" class="chart" />
          </el-card>
        </el-col>
        <el-col :xs="24" :lg="10">
          <el-card shadow="never" class="chart-card">
            <template #header>严重度分布</template>
            <div ref="pieEl" class="chart" />
          </el-card>
        </el-col>
      </el-row>
    </template>
  </div>
</template>

<style scoped>
.chart-card {
  margin-bottom: 12px;
  border-radius: 12px;
}
.chart {
  height: 300px;
  width: 100%;
}
</style>
