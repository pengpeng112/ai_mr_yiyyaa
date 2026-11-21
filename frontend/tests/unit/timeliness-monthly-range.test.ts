/**
 * WP04 月度考核升级测试：任意日期区间 + 快捷区间联动 + 真分页 + xlsx 导出按钮 +
 * 固定表头/冻结列 + status_counts 汇总卡。源码契约断言（与仓库既有 timeliness
 * 测试惯例一致，避免 jsdom 下 ECharts/Element Plus 全量加载）。
 */
import { describe, expect, it } from 'vitest'
import monthlySource from '@/features/timeliness/MonthlyReportPage.vue?raw'
import eventLedgerSource from '@/features/timeliness/EventLedgerPage.vue?raw'
import approvalLedgerSource from '@/features/timeliness/ApprovalLedgerPage.vue?raw'
import approvalCenterSource from '@/features/timeliness/ApprovalCenterPage.vue?raw'
import apiSource from '@/features/timeliness/api.ts?raw'
import typesSource from '@/features/timeliness/types.ts?raw'

describe('WP04：MonthlyReportPage 任意区间与快捷区间', () => {
  it('快捷区间六档（本月默认/上月/近7/近10/近30/自定义）', () => {
    for (const mode of ['month', 'prevMonth', 'last7', 'last10', 'last30', 'custom']) {
      expect(monthlySource).toContain(`value="${mode}"`)
    }
    expect(monthlySource).toContain(`ref="quickRange"`.replace('ref=', 'v-model='))
    // 本月默认：初始值 month
    expect(monthlySource).toMatch(/const quickRange = ref<QuickRange>\('month'\)/)
    // 非自定义自动算起止写回日期框；手动改日期切自定义
    expect(monthlySource).toContain('applyQuickRange')
    expect(monthlySource).toContain('onDateManualChange')
    expect(monthlySource).toContain(`quickRange.value = 'custom'`)
  })

  it('daterange 必填（:clearable="false"）且请求带 date_from/date_to/page/limit/dept/doctor', () => {
    expect(monthlySource).toContain(':clearable="false"')
    for (const key of ['date_from', 'date_to', 'dept', 'doctor', 'page', 'limit']) {
      expect(monthlySource).toContain(`${key}:`)
    }
    // 请求走区间版 API
    expect(monthlySource).toContain('fetchMonthlyRangeStatsApi')
    expect(monthlySource).toMatch(/limit: pageSize\.value/)
  })

  it('真分页：DataTableShell 分页事件 + total_rows 回填 + totals 全量', () => {
    expect(monthlySource).toContain('DataTableShell')
    expect(monthlySource).toContain('onPageChange')
    expect(monthlySource).toContain('onPageSizeChange')
    expect(monthlySource).toContain('total_rows')
    expect(monthlySource).toContain('stats.value?.totals')
  })

  it('xlsx 导出按钮（format=xlsx）+ 导出权限降级提示', () => {
    expect(monthlySource).toContain('导出 Excel')
    expect(monthlySource).toContain(`format: 'xlsx'`)
    expect(monthlySource).toContain('exportMonthlyApi')
    expect(monthlySource).toContain('timeliness_export')
  })

  it('固定表头 + 冻结左侧科室/医生列 + 合计行取全量 totals', () => {
    expect(monthlySource).toContain(':max-height="tableMaxHeight"')
    expect(monthlySource).toContain('calc(100vh - 380px)')
    expect(monthlySource).toContain('fixed="left"')
    expect(monthlySource).toContain('show-summary')
    expect(monthlySource).toContain('summary-method')
    expect(monthlySource).toContain('全期合计')
    expect(monthlySource).toContain('ma-sticky-th')
  })

  it('SummaryStrip 六卡含按时率（totals 计算）与锁定(超时申请)/豁免次数/应扣金额', () => {
    expect(monthlySource).toContain('SummaryStrip')
    for (const label of ['事件总数', '按时完成率', '超时未完成', '锁定(超时申请)次数', '豁免次数', '应扣金额(元)']) {
      expect(monthlySource).toContain(label)
    }
    expect(monthlySource).toContain('totals.completed_on_time')
    expect(monthlySource).toContain('totals.completed_late')
  })

  it('手机端入口弹窗保留（WP04 红线：不删手机端入口）', () => {
    expect(monthlySource).toContain('open-mobile-entry')
    expect(monthlySource).toContain('mobileEntryVisible')
  })
})

describe('WP04：ApprovalLedgerPage 状态汇总与新筛选', () => {
  it('SummaryStrip 四卡（申请总数/锁定待审批/已解锁/已豁免）来自 status_counts', () => {
    expect(approvalLedgerSource).toContain('SummaryStrip')
    for (const label of ['申请总数', '锁定待审批', '已解锁', '已豁免']) {
      expect(approvalLedgerSource).toContain(label)
    }
    expect(approvalLedgerSource).toContain('statusCounts.value = body.status_counts')
  })

  it('申请日期范围 daterange + 申请人筛选（工号/姓名）', () => {
    expect(approvalLedgerSource).toContain('type="daterange"')
    expect(approvalLedgerSource).toContain('apply_date_from')
    expect(approvalLedgerSource).toContain('apply_date_to')
    expect(approvalLedgerSource).toContain('applicant:')
    expect(approvalLedgerSource).toContain('申请人')
  })

  it('固定表头 + 患者信息列冻结 + 360 全息按钮 + 超时小时展示', () => {
    expect(approvalLedgerSource).toContain('calc(100vh - 380px)')
    expect(approvalLedgerSource).toContain('fixed="left"')
    expect(approvalLedgerSource).toContain('fixed="right"')
    expect(approvalLedgerSource).toContain('HolographyButton')
    expect(approvalLedgerSource).toContain('formatOverdueHours')
  })

  it('既有契约保留：filters/flag/approve/exempt 全链（不削弱）', () => {
    expect(approvalLedgerSource).toContain('approval-filters')
    expect(approvalLedgerSource).toContain('filters.monitor_code')
    expect(approvalLedgerSource).toContain('filters.flag')
    expect(approvalLedgerSource).toContain('APPROVAL_FLAG_OPTIONS')
    expect(approvalLedgerSource).toContain('el-pagination')
    expect(approvalLedgerSource).toContain('approve-dry-run')
    expect(approvalLedgerSource).toContain('approve-confirm')
    expect(approvalLedgerSource).toContain(`:disabled="row.flag === '2'"`)
    expect(approvalLedgerSource).toContain('approvalPenaltyText')
    expect(approvalLedgerSource).toContain('is-exempt')
    expect(approvalLedgerSource).toContain('apply_user_name')
    expect(approvalLedgerSource).toContain('approve_user_name')
    expect(approvalLedgerSource).toContain('豁免原因')
  })
})

describe('WP04：ApprovalCenterPage 立即同步', () => {
  it('页头「立即同步 JHEMR 审批」按钮 + syncApprovalsApi + key 自增刷新子组件', () => {
    expect(approvalCenterSource).toContain('立即同步 JHEMR 审批')
    expect(approvalCenterSource).toContain('syncApprovalsApi')
    expect(approvalCenterSource).toContain('已同步 ${result.synced} 条')
    expect(approvalCenterSource).toContain('ledgerKey.value += 1')
    // 503（只读源未配置）与 403 权限友好提示
    expect(approvalCenterSource).toContain("message.includes('503')")
    expect(approvalCenterSource).toContain("message.includes('403')")
  })

  it('手机端入口弹窗保留（既有契约不删除）', () => {
    expect(approvalCenterSource).toContain('open-mobile-entry')
    expect(approvalCenterSource).toContain('copyMobileUrl')
  })
})

describe('WP04：api/types 契约扩展', () => {
  it('api.ts：fetchMonthlyRangeStatsApi/exportMonthlyApi format/syncApprovalsApi 走 /timeliness BFF', () => {
    expect(apiSource).toContain('fetchMonthlyRangeStatsApi')
    expect(apiSource).toContain(`'/timeliness/stats/monthly'`)
    expect(apiSource).toContain(`'/timeliness/approvals/sync'`)
    expect(apiSource).toContain(`options?.format || 'csv'`)
    // 既有端点路径不被破坏
    expect(apiSource).toContain('/timeliness/export/monthly?${params}')
  })

  it('types.ts：TlEvent 临床字段/remaining/latest_approval + TlApproval 审批人/事件关联 + MonthlyRow.on_time_rate', () => {
    for (const key of [
      'remaining_minutes?: number | null',
      'latest_approval?: LatestApprovalSummary | null',
      'admission_diagnosis?: string',
      'nursing_level?: string',
      'approve_user_name?: string',
      'event_overdue_minutes?: number | null',
      'admission_date?: string | null',
      'apply_date_from?: string',
      'applicant?: string',
      'on_time_rate: number',
      'ApprovalStatusCounts',
      'date_from?: string',
      'total_rows?: number',
    ]) {
      expect(typesSource).toContain(key)
    }
  })

  it('EventLedgerPage：doctor 路由参数与 countdownBadge 纯函数（源码契约）', () => {
    expect(eventLedgerSource).toContain('doctor')
    expect(eventLedgerSource).toContain('filters.doctor')
    expect(eventLedgerSource).toContain('countdownBadge')
    expect(eventLedgerSource).toContain('formatDuration')
    expect(eventLedgerSource).toContain('latest_approval')
    expect(eventLedgerSource).toContain('remaining_minutes')
    expect(eventLedgerSource).toContain('HolographyButton')
  })
})
