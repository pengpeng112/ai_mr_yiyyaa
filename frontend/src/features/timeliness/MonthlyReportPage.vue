<template>
  <section class="tl-page">
    <PageHeader
      title="时效月度考核"
      description="按科室 × 责任医生聚合当月按时完成率、预警与超时锁定次数及扣罚口径（受科室可见性约束）；导出写导出审计。"
    >
      <template #actions>
        <el-button
          size="small"
          type="primary"
          plain
          data-testid="goto-approvals"
          @click="goApprovals"
        >
          前往待办解锁审批 -&gt;
        </el-button>
        <el-button size="small" data-testid="open-mobile-entry" @click="mobileEntryVisible = true">
          📱 手机端入口
        </el-button>
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
      </template>
    </PageHeader>

    <!-- 2026-11-16：企微手机端访问入口便捷弹窗 -->
    <el-dialog v-model="mobileEntryVisible" title="企业微信手机端访问入口" width="min(92vw, 520px)">
      <p class="mobile-entry-tip">
        可将此链接配置到企业微信工作台自建应用主页，或发送至企业微信收藏夹，手机点开即可查询超时解锁与统计报表。
      </p>
      <el-input :model-value="mobileUrl" readonly>
        <template #append>
          <el-button @click="copyMobileUrl">一键复制链接</el-button>
        </template>
      </el-input>
      <template #footer>
        <el-button @click="mobileEntryVisible = false">关闭</el-button>
        <el-button type="primary" @click="mobileEntryVisible = false">
          <a :href="mobileUrl" target="_blank" rel="noopener" class="mobile-entry-link">新窗口预览手机端</a>
        </el-button>
      </template>
    </el-dialog>

    <el-card shadow="never">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="月度统计" name="monthly">
          <el-alert v-if="loadError" type="error" :title="loadError" :closable="false" class="tl-alert" />

          <el-row v-if="stats" :gutter="8" class="tl-totals">
            <el-col v-for="card in totalCards" :key="card.label" :span="cardSpan">
              <el-card shadow="never" class="tl-total-card">
                <div class="tl-total-value" :class="card.cls">{{ card.value }}</div>
                <div class="tl-total-label">{{ card.label }}</div>
              </el-card>
            </el-col>
            <el-col :span="cardSpan">
              <el-card shadow="never" class="tl-total-card">
                <div class="tl-total-value">{{ stats.month }}</div>
                <div class="tl-total-label">统计月份</div>
              </el-card>
            </el-col>
          </el-row>

          <el-table v-loading="loading" :data="stats?.rows || []" size="small" border>
            <el-table-column label="科室" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">{{ row.dept_name || row.dept_code || '—' }}</template>
            </el-table-column>
            <el-table-column label="责任医生" min-width="130" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.responsible_doctor_name ? `${row.responsible_doctor_name}（${row.responsible_doctor_id || '—'}）` : (row.responsible_doctor_id || '（未指定）') }}
              </template>
            </el-table-column>
            <el-table-column prop="total" label="事件总数" width="90" sortable />
            <el-table-column prop="completed_on_time" label="按时完成" width="90" sortable />
            <el-table-column prop="completed_late" label="超时完成" width="90" sortable />
            <el-table-column prop="overdue" label="超时未完成" width="100" sortable />
            <el-table-column prop="pending" label="未到期" width="85" sortable />
            <el-table-column prop="warning" label="预警中" width="85" sortable />
            <el-table-column prop="other" label="其他状态" width="90" sortable />
            <!-- 2026-11-13 返工：当月超时申请/扣罚口径 4 列（与 tl_approval 对齐） -->
            <el-table-column prop="approval_count" label="超时申请" width="90" sortable />
            <el-table-column prop="approved_unlock_count" label="解锁通过" width="90" sortable />
            <el-table-column prop="exempt_count" label="豁免次数" width="90" sortable />
            <el-table-column prop="penalty_amount_total" label="应扣金额(元)" width="110" sortable />
          </el-table>
          <p v-if="stats && stats.rows.length === 0" class="tl-subtitle">当月无事件数据（或当前账号无可见科室）。</p>
        </el-tab-pane>

        <el-tab-pane label="审批与扣罚台账" name="approvals" lazy>
          <ApprovalLedgerPage />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </section>
</template>

<script setup lang="ts">
// T6 月度统计页（只读 + 导出）+ 2026-11-13 返工 + 2026-11-15 P1-2 视觉统一：
// - GET /stats/monthly?month=YYYY-MM（含 4 个扣罚统计字段）；
// - 页签保留 ApprovalLedgerPage（审批与扣罚台账：筛选/豁免/审批解锁 dry-run 预览）；
// - 右上角快捷按钮改为「前往待办解锁审批 ->」（跳独立审批中心并预填 flag=1 待办）；
// - 导出走 apiDownload（blob），无 timeliness_export 权限时后端 403 → 提示降级。
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import PageHeader from '@/components/base/PageHeader.vue'
import ApprovalLedgerPage from './ApprovalLedgerPage.vue'
import { exportMonthlyApi, fetchMonthlyStatsApi } from './api'
import type { MonthlyStats } from './types'

const router = useRouter()

// 2026-11-16：企微手机端入口弹窗（与 ApprovalCenterPage 同款）
const mobileEntryVisible = ref(false)
const mobileUrl = computed(() => `${window.location.origin}/mobile/qc/timeliness`)

async function copyMobileUrl(): Promise<void> {
  try {
    await navigator.clipboard.writeText(mobileUrl.value)
    ElMessage.success('手机端链接已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择链接复制')
  }
}

const loading = ref(false)
const exporting = ref(false)
const loadError = ref('')
const stats = ref<MonthlyStats | null>(null)
const monthValue = ref(defaultMonth())
const activeTab = ref('monthly')

function defaultMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

// 9 张卡片（8 指标 + 月份）按每行 4 张（span=6）自动换行。
const cardSpan = 6

const totalCards = computed(() => {
  const totals = stats.value?.totals
  if (!totals) return []
  return [
    { label: '事件总数', value: totals.total, cls: '' },
    { label: '按时完成', value: totals.completed_on_time, cls: 'is-ok' },
    { label: '超时完成', value: totals.completed_late, cls: 'is-bad' },
    { label: '超时未完成', value: totals.overdue, cls: 'is-bad' },
    // 2026-11-13 返工新增：扣罚口径汇总卡片
    { label: '超时申请', value: totals.approval_count, cls: '' },
    { label: '解锁通过', value: totals.approved_unlock_count, cls: '' },
    { label: '豁免次数', value: totals.exempt_count, cls: 'is-warn' },
    { label: '应扣金额(元)', value: totals.penalty_amount_total, cls: 'is-bad' },
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

function goApprovals(): void {
  // 快捷直达独立审批中心（2026-11-15 拆分：待办审批集中在解锁审批页处理，预填 flag=1 待办）。
  void router.push({ name: 'timeliness-approvals', query: { flag: '1' } })
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
  font-size: 18px;
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
.tl-subtitle {
  margin: 4px 0 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.mobile-entry-tip {
  margin: 0 0 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--el-text-color-secondary);
}
.mobile-entry-link {
  color: inherit;
  text-decoration: none;
}
</style>
