import { describe, expect, it } from 'vitest'
import apiSource from '@/features/timeliness/api.ts?raw'
import ledgerSource from '@/features/timeliness/EventLedgerPage.vue?raw'
import approvalSource from '@/features/timeliness/ApprovalLedgerPage.vue?raw'
import workbenchSource from '@/features/workbench/WorkbenchPage.vue?raw'
import {
  actionModeExecLabel,
  actionModeTagType,
  actionTypeLabel,
} from '@/features/timeliness/types'

// 2026-11-15 P0 断链修复 + P1 中文化：动作留痕映射 / 事件豁免闭环 / 首页带参跳转

describe('动作留痕中文化纯函数（P1-1）', () => {
  it('actionTypeLabel：通知/写入/审批回写/豁免全映射，未知原样，空显示占位', () => {
    expect(actionTypeLabel('NOTIFY')).toBe('企微预警通知')
    expect(actionTypeLabel('TIMELINESS_NOTIFY')).toBe('企微预警通知')
    expect(actionTypeLabel('JHEMR_INSERT_MONITOR')).toBe('写入病历锁定项')
    expect(actionTypeLabel('JHEMR_APPROVE')).toBe('回写解锁审批')
    expect(actionTypeLabel('APPROVAL_EXEMPT')).toBe('扣罚豁免')
    expect(actionTypeLabel('APPROVAL_EXEMPT_CANCEL')).toBe('取消扣罚豁免')
    expect(actionTypeLabel('EVENT_EXEMPT')).toBe('事件人工豁免')
    expect(actionTypeLabel('SOMETHING_NEW')).toBe('SOMETHING_NEW')
    expect(actionTypeLabel(null)).toBe('—')
    expect(actionTypeLabel('')).toBe('—')
  })

  it('actionModeExecLabel：四模式中文 + 未知原样；tag 色语义正确', () => {
    expect(actionModeExecLabel('EXECUTED')).toBe('已执行')
    expect(actionModeExecLabel('DRY_RUN')).toBe('演练预览')
    expect(actionModeExecLabel('LOG_ONLY')).toBe('仅记日志(影子)')
    expect(actionModeExecLabel('BLOCKED')).toBe('网关已拦截')
    expect(actionModeExecLabel('OTHER')).toBe('OTHER')

    expect(actionModeTagType('EXECUTED')).toBe('success')
    expect(actionModeTagType('DRY_RUN')).toBe('warning')
    expect(actionModeTagType('BLOCKED')).toBe('danger')
    expect(actionModeTagType('LOG_ONLY')).toBe('info')
    expect(actionModeTagType(undefined)).toBe('info')
  })
})

describe('事件豁免 API 契约（P0-2）', () => {
  it('api.ts 新增事件豁免端点且走 /timeliness BFF（encodeURIComponent，不直连）', () => {
    expect(apiSource).toContain('exemptEventApi')
    expect(apiSource).toContain('/timeliness/events/')
    expect(apiSource).toContain('/exempt')
    expect(apiSource).toContain("encodeURIComponent(String(eventId))")
    expect(apiSource).toContain('exempt_reason: exemptReason')
    // 不直连任何后端/JHEMR/中继地址
    expect(apiSource).not.toMatch(/https?:\/\//)
    expect(apiSource).not.toContain('10.20.1.153')
    expect(apiSource).not.toContain('10.10.8')
  })

  it('EventLedgerPage：豁免对话框（终态提示/原因必填/确认按钮）与 403 友好提示', () => {
    expect(ledgerSource).toContain('事件特殊豁免')
    expect(ledgerSource).toContain('豁免后该事件进入终态，不再发送预警或触发锁定')
    expect(ledgerSource).toContain('event-exempt-reason-input')
    expect(ledgerSource).toContain('event-exempt-confirm')
    expect(ledgerSource).toContain(':disabled="!exemptReason.trim()"')
    expect(ledgerSource).toContain('timeliness_admin')
    expect(ledgerSource).toContain('exemptEventApi')
    // 完成类/取消类/已豁免终态不再显示登记豁免按钮
    expect(ledgerSource).toContain("['COMPLETED_ON_TIME', 'COMPLETED_LATE', 'CANCELLED', 'EXEMPT']")
  })

  it('EventLedgerPage：APPLYING/APPROVED 提供「去审批」并预填患者与科室', () => {
    expect(ledgerSource).toContain('event-go-approve')
    expect(ledgerSource).toContain("name: 'timeliness-approvals', query: { patient_id: row.patient_id, dept: row.dept_code || '' }")
    expect(ledgerSource).toContain("'APPLYING' || (row as TlEvent).status === 'APPROVED'")
  })

  it('EventLedgerPage：keepAlive 带参跳转响应（applyRouteQuery + watch route.query）', () => {
    expect(ledgerSource).toContain('applyRouteQuery')
    expect(ledgerSource).toContain('watch(')
    expect(ledgerSource).toContain("route.name === 'quality-timeliness-events'")
    expect(ledgerSource).toContain('route.query.status')
    expect(ledgerSource).toContain('route.query.patient_id')
    expect(ledgerSource).toContain('route.query.rule_code')
    expect(ledgerSource).toContain('route.query.dept')
  })

  it('患者可读文本：姓名（住院号 · 住院次N）新格式（EventLedger + ApprovalLedger）', () => {
    for (const source of [ledgerSource, approvalSource]) {
      expect(source).toContain('patientText')
      expect(source).toContain('住院次')
      expect(source).toContain('row.patient_name')
    }
  })

  it('ApprovalLedgerPage：query watch 响应 flag/patient_id 且未传清空', () => {
    expect(approvalSource).toContain('applyRouteQuery')
    expect(approvalSource).toContain("route.name === 'timeliness-approvals'")
    expect(approvalSource).toContain('route.query.flag')
    expect(approvalSource).toContain('route.query.patient_id')
  })
})

describe('首页快捷卡带参跳转（P0-1）', () => {
  it('WorkbenchPage：待审批卡带 flag=1 精准筛选；无权限点击给出明确反馈', () => {
    // WP03 总览重构后：goPath(path, query) 承载带参跳转（原 go(menuId) 菜单门模式收编进路径直跳）
    expect(workbenchSource).toContain("'/timeliness/approvals', { flag: '1' }")
    expect(workbenchSource).toContain('HolographyButton')
    expect(workbenchSource).toContain('goPath(')
  })
})
