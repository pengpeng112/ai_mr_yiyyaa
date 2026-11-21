import { describe, expect, it } from 'vitest'
import apiSource from '@/features/timeliness/api.ts?raw'
import typesSource from '@/features/timeliness/types.ts?raw'
import ledgerSource from '@/features/timeliness/ApprovalLedgerPage.vue?raw'
import monthlySource from '@/features/timeliness/MonthlyReportPage.vue?raw'
import {
  APPROVAL_FLAG_OPTIONS,
  DEFAULT_PENALTY_AMOUNT,
  approvalChannelLabel,
  approvalFlagLabel,
  approvalPenaltyText,
} from '@/features/timeliness/types'

// 2026-11-13 返工 §修复4.3：审批与扣罚台账前端契约
describe('返工：审批台账 API 契约', () => {
  it('api.ts 补齐审批三端点且全部走 /timeliness BFF 路径', () => {
    for (const path of [
      '/timeliness/approvals',
      '/exempt',
      '/approve',
    ]) {
      expect(apiSource).toContain(path)
    }
    expect(apiSource).toContain('fetchApprovalsApi')
    expect(apiSource).toContain('exemptApprovalApi')
    expect(apiSource).toContain('approveApprovalApi')
    // 不直连任何后端/JHEMR/中继地址
    expect(apiSource).not.toMatch(/https?:\/\//)
    expect(apiSource).not.toContain('10.20.1.153')
    expect(apiSource).not.toContain('10.10.8')
  })

  it('豁免/取消豁免与审批解锁的请求体契约（cancel 布尔、dry_run 布尔）', () => {
    expect(apiSource).toMatch(/cancel:\s*Boolean\(options\?\.cancel\)/)
    expect(apiSource).toMatch(/dry_run:\s*dryRun/)
    expect(apiSource).toContain('encodeURIComponent(String(approvalId))')
  })
})

describe('返工：审批台账类型与纯函数', () => {
  it('MonthlyRow/MonthlyTotals 补齐 4 个扣罚统计字段', () => {
    for (const field of [
      'approval_count',
      'approved_unlock_count',
      'exempt_count',
      'penalty_amount_total',
    ]) {
      expect(typesSource).toContain(field)
    }
  })

  it('TlApproval 类型与后端 _approval_dict 对齐（含 dept_code）', () => {
    for (const field of [
      'monitor_code',
      'apply_date_time',
      'flag',
      'approve_channel',
      'dept_code',
      'penalty_amount',
      'penalty_exempt',
      'exempt_reason',
    ]) {
      expect(typesSource).toContain(field)
    }
  })

  it('approvalFlagLabel：1=已申请解锁、2=审批通过、空=未申请', () => {
    expect(approvalFlagLabel('1')).toBe('已申请解锁')
    expect(approvalFlagLabel('2')).toBe('审批通过')
    expect(approvalFlagLabel(null)).toBe('未申请')
    expect(approvalFlagLabel('')).toBe('未申请')
    expect(APPROVAL_FLAG_OPTIONS.map((o) => o.value)).toEqual(['1', '2'])
  })

  it('approvalChannelLabel：三渠道中文 + 未知/空显示占位', () => {
    expect(approvalChannelLabel('JHEMR_NATIVE')).toBe('JHEMR 原生画布')
    expect(approvalChannelLabel('PC_WEB')).toBe('PC 网页端')
    expect(approvalChannelLabel('WECOM_H5')).toBe('企微 H5')
    expect(approvalChannelLabel(null)).toBe('—')
    expect(approvalChannelLabel('SOMETHING')).toBe('SOMETHING')
  })

  it('approvalPenaltyText：豁免显示已豁免；金额未配置按 200 元兜底', () => {
    expect(approvalPenaltyText({ penalty_amount: 300, penalty_exempt: false })).toBe('300 元')
    expect(approvalPenaltyText({ penalty_amount: null, penalty_exempt: false })).toBe(
      `${DEFAULT_PENALTY_AMOUNT} 元`,
    )
    expect(approvalPenaltyText({ penalty_amount: 300, penalty_exempt: true })).toBe('已豁免')
  })
})

describe('返工：ApprovalLedgerPage 页面契约', () => {
  it('筛选区支持科室/监控码/状态（flag）并带分页', () => {
    expect(ledgerSource).toContain('approval-filters')
    expect(ledgerSource).toContain('filters.dept')
    expect(ledgerSource).toContain('filters.monitor_code')
    expect(ledgerSource).toContain('filters.flag')
    expect(ledgerSource).toContain('APPROVAL_FLAG_OPTIONS')
    expect(ledgerSource).toContain('el-pagination')
  })

  it('豁免/取消豁免：原因必填、防误触禁用、403 降级提示', () => {
    expect(ledgerSource).toContain('扣罚豁免')
    expect(ledgerSource).toContain('取消豁免')
    expect(ledgerSource).toContain('exempt-reason-input')
    expect(ledgerSource).toContain(':disabled="!exemptReason.trim()"')
    expect(ledgerSource).toContain('timeliness_admin')
  })

  it('审批解锁：先 dry_run 预览再确认提交；网关未开 409 友好提示', () => {
    expect(ledgerSource).toContain('approve-dry-run')
    expect(ledgerSource).toContain('approve-confirm')
    expect(ledgerSource).toContain('approveApprovalApi(approveTarget.value.id, true)')
    expect(ledgerSource).toContain('approveApprovalApi(approveTarget.value.id, false)')
    expect(ledgerSource).toContain('409')
    expect(ledgerSource).toContain('超时审批')  // 提示走 JHEMR 原生画布
    expect(ledgerSource).toContain(':disabled="row.flag === \'2\'"')  // 已审批不再解锁
  })

  it('金额/豁免列渲染：豁免行划线 + 已配置金额优先', () => {
    expect(ledgerSource).toContain('approvalPenaltyText')
    expect(ledgerSource).toContain('is-exempt')
  })
})

describe('返工：MonthlyReportPage 扣罚口径展示', () => {
  it('新增 4 张汇总卡片与 4 个表格列（超时申请/解锁通过/豁免/应扣金额）', () => {
    expect(monthlySource).toContain('超时申请')
    expect(monthlySource).toContain('解锁通过')
    expect(monthlySource).toContain('豁免次数')
    expect(monthlySource).toContain('应扣金额(元)')
    expect(monthlySource).toContain('approval_count')
    expect(monthlySource).toContain('approved_unlock_count')
    expect(monthlySource).toContain('exempt_count')
    expect(monthlySource).toContain('penalty_amount_total')
  })

  it('WP04：移除页内「审批与扣罚台账」页签，审批集中在独立台账页（页头直达按钮保留）', () => {
    // 064-WP04：考核统计页不再内嵌 ApprovalLedgerPage 页签（避免同页重复挂载两份台账），
    // 审批入口收敛为页头「解锁审批台账 ->」跳转按钮（/timeliness/approvals）。
    expect(monthlySource).not.toContain('el-tabs')
    expect(monthlySource).not.toContain('ApprovalLedgerPage')
    expect(monthlySource).not.toContain('审批与扣罚台账')
    expect(monthlySource).toContain('解锁审批台账')
    expect(monthlySource).toContain('goApprovals')
    expect(monthlySource).toContain("'timeliness-approvals'")
  })

  it('既有契约保留：导出（CSV 契约后端保持，前端 WP04 默认 xlsx）+ 权限降级提示', () => {
    // WP04：统计请求升级为 fetchMonthlyRangeStatsApi（区间+分页），导出走 exportMonthlyApi。
    expect(monthlySource).toContain('fetchMonthlyRangeStatsApi')
    expect(monthlySource).toContain('exportMonthlyApi')
    expect(monthlySource).toContain('timeliness_export')
    expect(monthlySource).toContain('stats.value?.totals')
  })
})
