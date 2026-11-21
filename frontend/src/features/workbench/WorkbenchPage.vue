<script setup lang="ts">
// 质控总览（WP03，064 总计划）：首屏只调 1 次 GET /api/stats/workbench-overview，
// 四大态势卡（AI 内涵/病历时效/归档前核查/告警与健康）+ 双图 + 高危清单（360 全息按钮）。
// 保留 go(menuId) 无权限 ElMessage.info 反馈与 keepAlive/onActivated 行为。
import { computed, onActivated, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import PageHeader from '@/components/base/PageHeader.vue'
import SkeletonBlock from '@/components/feedback/SkeletonBlock.vue'
import ErrorState from '@/components/feedback/ErrorState.vue'
import RiskTag from '@/components/base/RiskTag.vue'
import HolographyButton from '@/components/base/HolographyButton.vue'
import {
  fetchWorkbenchOverview,
  type WorkbenchOverview,
} from '@/api/endpoints/workbench'

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const router = useRouter()

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
const data = ref<WorkbenchOverview | null>(null)
const updatedAt = ref('')
let lastLoadAt = 0
let trendChart: echarts.ECharts | null = null
let deptChart: echarts.ECharts | null = null
let chartRo: ResizeObserver | null = null

const trendEl = ref<HTMLDivElement | null>(null)
const deptEl = ref<HTMLDivElement | null>(null)

const scopeLabel = computed(() => data.value?.scope_label || '全院')
const healthOk = computed(() => data.value?.system.status === 'ok')
const prearchiveModeLabel = computed(() => {
  const mode = data.value?.prearchive.mode || 'unconfigured'
  const map: Record<string, string> = {
    shadow: '影子模式',
    shadow_idle: '影子待数据',
    unconfigured: '待接入',
  }
  return map[mode] || '运行中'
})
const highRiskRows = computed(() => data.value?.ai_qc.high_risk_recent || [])
const topDepts = computed(() => data.value?.ai_qc.top_depts || [])
const trendRows = computed(() => data.value?.ai_qc.daily_trend || [])

function fmtTime(v: string | null | undefined): string {
  if (!v) return ''
  return String(v).replace('T', ' ').slice(0, 16)
}

/** 板块卡/链接跳转（全部真实路由）。 */
function goPath(path: string, query: Record<string, string> = {}) {
  void router.push({ path, query })
}

function disposeCharts() {
  chartRo?.disconnect()
  chartRo = null
  trendChart?.dispose()
  deptChart?.dispose()
  trendChart = null
  deptChart = null
}

function renderTrend(rows: Array<{ date: string; total: number; high: number }>) {
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
      tooltip: { trigger: 'axis', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: '#f8fafc' } },
      legend: { data: ['核查量', '高危'], textStyle: { color: C.muted, fontSize: 11 }, top: 0 },
      grid: { left: 44, right: 16, top: 32, bottom: 26 },
      xAxis: {
        type: 'category',
        data: rows.map((r) => String(r.date).slice(5)),
        axisLine: { lineStyle: { color: C.axis } },
        axisLabel: { color: C.muted, fontSize: 10 },
      },
      yAxis: { type: 'value', splitLine: { lineStyle: { color: C.split } }, axisLabel: { color: C.muted, fontSize: 10 } },
      series: [
        { name: '核查量', type: 'bar', data: rows.map((r) => r.total), itemStyle: { color: C.blue }, barMaxWidth: 18 },
        { name: '高危', type: 'line', data: rows.map((r) => r.high), itemStyle: { color: C.red }, lineStyle: { width: 2 } },
      ],
    },
    { notMerge: true },
  )
}

function renderDept(rows: Array<{ name: string; anomaly_count: number }>) {
  if (!deptEl.value) return
  if (!deptChart || deptChart.getDom() !== deptEl.value) {
    deptChart?.dispose()
    deptChart = echarts.init(deptEl.value, undefined, { renderer: 'canvas' })
  }
  if (!rows.length) {
    deptChart.clear()
    return
  }
  const ordered = [...rows].reverse() // 横向柱 inverse 后自上而下
  deptChart.setOption(
    {
      backgroundColor: 'transparent',
      tooltip: { trigger: 'item', backgroundColor: C.tipBg, borderColor: C.tipBorder, textStyle: { color: '#f8fafc' } },
      grid: { left: 90, right: 44, top: 10, bottom: 24 },
      xAxis: { type: 'value', splitLine: { lineStyle: { color: C.split } }, axisLabel: { color: C.muted, fontSize: 10 } },
      yAxis: {
        type: 'category',
        data: ordered.map((r) => r.name),
        inverse: true,
        axisLine: { lineStyle: { color: C.axis } },
        axisLabel: { color: C.text, fontSize: 11 },
      },
      series: [{
        type: 'bar',
        data: ordered.map((r) => r.anomaly_count),
        itemStyle: { color: C.cyan },
        barMaxWidth: 16,
        label: { show: true, position: 'right', color: C.muted, fontSize: 10 },
      }],
    },
    { notMerge: true },
  )
}

function bindChartResize() {
  chartRo?.disconnect()
  if (typeof ResizeObserver === 'undefined') return
  chartRo = new ResizeObserver(() => {
    trendChart?.resize()
    deptChart?.resize()
  })
  if (trendEl.value) chartRo.observe(trendEl.value)
  if (deptEl.value) chartRo.observe(deptEl.value)
}

async function load(force = false) {
  loading.value = true
  loadError.value = ''
  disposeCharts()
  try {
    data.value = await fetchWorkbenchOverview({ days: 30, force_refresh: force })
    updatedAt.value = new Date().toLocaleTimeString('zh-CN', { hour12: false })
    lastLoadAt = Date.now()
    renderTrend(trendRows.value)
    renderDept(topDepts.value)
    bindChartResize()
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : '总览聚合加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  // keepAlive 距上次加载 >30s 才重新拉
  if (Date.now() - lastLoadAt > 30_000) void load()
})

onActivated(() => {
  if (Date.now() - lastLoadAt > 30_000) void load()
  else {
    renderTrend(trendRows.value)
    renderDept(topDepts.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', () => undefined)
  disposeCharts()
})
</script>

<template>
  <div class="wb-page">
    <PageHeader
      title="质控总览"
      :description="`实时态势 · 数据范围：${scopeLabel} · 更新于 ${updatedAt || '—'}`"
    >
      <template #actions>
        <el-button :loading="loading" @click="load(true)">刷新数据</el-button>
        <el-button type="primary" @click="goPath('/quality/patients', { severity: 'high' })">处理高危病历</el-button>
      </template>
    </PageHeader>

    <ErrorState v-if="loadError && !loading" :message="loadError" @retry="load(true)" />
    <SkeletonBlock v-else-if="loading && !data" :rows="8" />
    <template v-else-if="data">
      <!-- 四大板块态势卡 -->
      <section class="pillar-grid" aria-label="业务板块态势">
        <!-- AI 内涵质控 -->
        <article
          class="pillar-card pillar-card--blue"
          role="button"
          tabindex="0"
          @click="goPath('/quality/patients')"
          @keydown.enter="goPath('/quality/patients')"
        >
          <div class="pillar-card__head">
            <h3>AI 内涵质控</h3>
            <el-tag size="small" effect="light" type="primary">今日核查</el-tag>
          </div>
          <div class="pillar-card__num">{{ data.ai_qc.today_pushed }}<small> 条</small></div>
          <div class="pillar-card__metrics">
            <span>近30天高危 {{ data.ai_qc.severity_counts.high }}</span>
            <span>中危 {{ data.ai_qc.severity_counts.medium }}</span>
            <span>今日成功 {{ data.ai_qc.today_success }}</span>
          </div>
          <div class="pillar-card__links" @click.stop>
            <el-button link size="small" type="danger" @click="goPath('/quality/patients', { severity: 'high' })">高危清单</el-button>
            <el-button link size="small" @click="goPath('/closure/feedback')">整改闭环</el-button>
          </div>
        </article>

        <!-- 病历时效 -->
        <article
          class="pillar-card pillar-card--amber"
          role="button"
          tabindex="0"
          @click="goPath('/timeliness/stats')"
          @keydown.enter="goPath('/timeliness/stats')"
        >
          <div class="pillar-card__head">
            <h3>病历时效</h3>
            <el-tag size="small" effect="light" :type="data.timeliness.locked_pending > 0 ? 'warning' : 'info'">
              待审批 {{ data.timeliness.locked_pending }}
            </el-tag>
          </div>
          <div class="pillar-card__num">{{ data.timeliness.inpatient_overdue }}<small> 例超时</small></div>
          <div class="pillar-card__metrics">
            <span>临期预警 {{ data.timeliness.inpatient_warning }}</span>
            <span>本月锁定 {{ data.timeliness.month_locked_total }}</span>
            <span>按时率 {{ data.timeliness.month_on_time_rate }}%</span>
          </div>
          <div class="pillar-card__links" @click.stop>
            <el-button link size="small" @click="goPath('/timeliness/stats')">时效统计</el-button>
            <el-button link size="small" type="danger" @click="goPath('/quality/timeliness-events', { status: 'OVERDUE' })">超时台账</el-button>
            <el-button link size="small" @click="goPath('/timeliness/approvals', { flag: '1' })">解锁审批</el-button>
          </div>
        </article>

        <!-- 归档前核查 -->
        <article
          class="pillar-card pillar-card--cyan"
          role="button"
          tabindex="0"
          @click="goPath('/governance/workbench')"
          @keydown.enter="goPath('/governance/workbench')"
        >
          <div class="pillar-card__head">
            <h3>归档前核查</h3>
            <el-tag size="small" effect="light" :type="data.prearchive.available ? 'success' : 'info'">
              {{ prearchiveModeLabel }}
            </el-tag>
          </div>
          <div class="pillar-card__num">{{ data.prearchive.available ? data.prearchive.total_checked : '—' }}<small v-if="data.prearchive.available"> 例</small></div>
          <div class="pillar-card__metrics">
            <template v-if="data.prearchive.available">
              <span>缺陷 {{ data.prearchive.issue_records }}</span>
              <span>待整改 {{ data.prearchive.pending_review }}</span>
              <span>规则 {{ data.prearchive.rules_active }}</span>
            </template>
            <template v-else>
              <span>{{ data.prearchive.status_message }}</span>
            </template>
          </div>
          <div class="pillar-card__links" @click.stop>
            <el-button link size="small" @click="goPath('/governance/workbench')">进入核查台</el-button>
            <el-button link size="small" @click="goPath('/governance/prearchive-rules')">形式规则</el-button>
          </div>
        </article>

        <!-- 告警与健康 -->
        <article
          class="pillar-card pillar-card--emerald"
          :class="{ 'pillar-card--alert': !healthOk }"
          role="button"
          tabindex="0"
          @click="goPath('/tasks/scheduler')"
          @keydown.enter="goPath('/tasks/scheduler')"
        >
          <div class="pillar-card__head">
            <h3>告警与健康</h3>
            <el-tag size="small" effect="light" :type="healthOk ? 'success' : 'danger'">
              {{ healthOk ? '运行正常' : '存在异常' }}
            </el-tag>
          </div>
          <div class="pillar-card__num">{{ data.relay.unviewed }}<small> 条未读告警</small></div>
          <div class="pillar-card__metrics">
            <span>已送达 {{ data.relay.success }}</span>
            <span>失败 {{ data.relay.failed }}</span>
            <span>调度 {{ data.system.scheduler_running ? '运行中' : '未启动' }}</span>
          </div>
          <div class="pillar-card__links" @click.stop>
            <el-button link size="small" type="danger" @click="goPath('/closure/alerts', { quick: 'unviewed' })">未读告警</el-button>
            <el-button link size="small" @click="goPath('/tasks/scheduler')">调度管理</el-button>
          </div>
        </article>
      </section>

      <!-- 双图区 -->
      <section class="chart-grid" aria-label="趋势与科室分布">
        <div class="chart-card">
          <div class="chart-card__head"><h3>近 30 天 AI 质控量与高危趋势</h3></div>
          <div ref="trendEl" class="chart-box" />
        </div>
        <div class="chart-card">
          <div class="chart-card__head"><h3>异常高发科室 TOP10</h3></div>
          <div ref="deptEl" class="chart-box" />
        </div>
      </section>

      <!-- 最新高危待处理患者 -->
      <section class="risk-card" aria-label="最新高危待处理患者">
        <div class="risk-card__head"><h3>最新高危待处理患者</h3></div>
        <el-table v-if="highRiskRows.length" :data="highRiskRows" border stripe size="small" max-height="380">
          <el-table-column label="患者" fixed="left" min-width="150">
            <template #default="{ row }">
              <div class="patient-cell">
                <b>{{ row.patient_name || '—' }}</b>
                <span>{{ row.patient_id }} · 第{{ row.visit_number }}次</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="科室" min-width="110">
            <template #default="{ row }">{{ row.dept || '—' }}</template>
          </el-table-column>
          <el-table-column label="质控类型" min-width="150">
            <template #default="{ row }">{{ row.audit_type_name || row.audit_type_code }}</template>
          </el-table-column>
          <el-table-column label="风险" width="80">
            <template #default="{ row }"><RiskTag :value="row.severity" /></template>
          </el-table-column>
          <el-table-column label="核心缺陷摘要" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">{{ row.summary || '—' }}</template>
          </el-table-column>
          <el-table-column label="核查时间" width="140">
            <template #default="{ row }">{{ fmtTime(row.push_time) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="170" fixed="right">
            <template #default="{ row }">
              <el-button
                link type="primary" size="small"
                @click="goPath('/quality/patient-detail', { patient_id: row.patient_id, visit_number: String(row.visit_number) })"
              >查看详情</el-button>
              <HolographyButton :patient-id="row.patient_id" link />
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="risk-card__empty">当前数据范围内暂无高危待处理病历</div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.wb-page { padding: 4px 2px 20px; color: var(--ma-text-primary); }
.pillar-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(220px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}
@media (max-width: 1200px) {
  .pillar-grid { grid-template-columns: repeat(2, 1fr); }
}
.pillar-card {
  background: #fff;
  border: 1px solid var(--ma-border);
  border-top: 3px solid var(--ma-blue-600);
  border-radius: var(--ma-radius);
  padding: 16px;
  cursor: pointer;
  transition: transform .15s, box-shadow .15s;
}
.pillar-card:hover { transform: translateY(-2px); box-shadow: var(--ma-shadow); }
.pillar-card--blue { border-top-color: var(--ma-blue-600); }
.pillar-card--amber { border-top-color: var(--ma-orange-500); }
.pillar-card--cyan { border-top-color: var(--ma-cyan-600); }
.pillar-card--emerald { border-top-color: var(--ma-green-500); }
.pillar-card--alert { border-top-color: var(--ma-red-500); }
.pillar-card__head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.pillar-card__head h3 { margin: 0; font-size: 14px; font-weight: 700; }
.pillar-card__num { font-size: 28px; font-weight: 700; line-height: 1.15; }
.pillar-card__num small { font-size: 12px; font-weight: 500; color: var(--ma-text-secondary); margin-left: 2px; }
.pillar-card__metrics {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: var(--ma-text-secondary);
  margin-top: 6px;
  flex-wrap: wrap;
}
.pillar-card__links { display: flex; gap: 4px; margin-top: 10px; }
.chart-grid { display: grid; grid-template-columns: 3fr 2fr; gap: 16px; margin-bottom: 16px; }
@media (max-width: 1024px) { .chart-grid { grid-template-columns: 1fr; } }
.chart-card, .risk-card {
  background: #fff;
  border: 1px solid var(--ma-border);
  border-radius: var(--ma-radius);
  padding: 14px;
}
.chart-card__head, .risk-card__head { margin-bottom: 8px; }
.chart-card__head h3, .risk-card__head h3 { margin: 0; font-size: 14px; font-weight: 700; }
.chart-box { height: 300px; }
.patient-cell { display: flex; flex-direction: column; }
.patient-cell b { font-size: 13px; }
.patient-cell span { font-size: 11px; color: var(--ma-text-secondary); }
.risk-card__empty { text-align: center; color: var(--ma-text-secondary); padding: 24px 0; font-size: 13px; }
</style>
