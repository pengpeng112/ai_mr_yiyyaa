/**
 * Workbench 总览重构测试（WP03）：只调 1 次聚合接口 + 四卡跳转路径。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import workbenchSource from '@/features/workbench/WorkbenchPage.vue?raw'
import workbenchApiSource from '@/api/endpoints/workbench.ts?raw'

describe('Workbench 总览重构（WP03）', () => {
  it('数据源契约：仅调用 /stats/workbench-overview（workbench.ts 端点）', () => {
    expect(workbenchApiSource).toContain('/stats/workbench-overview')
    expect(workbenchApiSource).toContain('fetchWorkbenchOverview')
    // 页面内不再出现旧分散接口调用
    for (const banned of [
      'fetchStatsToday', 'fetchStatsDaily', 'fetchStatsSeverity', 'fetchAnomalyTop',
      '/scheduler/status', '/patient-qc/relay-alert/summary', "apiGet('/logs'",
    ]) {
      expect(workbenchSource).not.toContain(banned)
    }
  })

  it('四大态势卡齐全且带跳转路径（任务书 §4.1 路由表）', () => {
    const cases: Array<[string, string]> = [
      ['AI 内涵质控', "'/quality/patients'"],
      ['病历时效', "'/timeliness/stats'"],
      ['归档前核查', "'/governance/workbench'"],
      ['告警与健康', "'/tasks/scheduler'"],
    ]
    for (const [title, path] of cases) {
      expect(workbenchSource).toContain(title)
      expect(workbenchSource).toContain(path)
    }
  })

  it('高危清单链接与子链接路径', () => {
    expect(workbenchSource).toContain("'/quality/patients', { severity: 'high' }")
    expect(workbenchSource).toContain("'/closure/feedback'")
    expect(workbenchSource).toContain("'/quality/timeliness-events', { status: 'OVERDUE' }")
    expect(workbenchSource).toContain("'/timeliness/approvals', { flag: '1' }")
    expect(workbenchSource).toContain("'/governance/prearchive-rules'")
    expect(workbenchSource).toContain("'/closure/alerts', { quick: 'unviewed' }")
    expect(workbenchSource).toContain("'/tasks/scheduler'")
  })

  it('高危表带 360 全息按钮与查看详情', () => {
    expect(workbenchSource).toContain('HolographyButton')
    expect(workbenchSource).toContain('/quality/patient-detail')
    expect(workbenchSource).toContain('RiskTag')
  })

  it('keepAlive 30s 节流保留（onActivated）', () => {
    expect(workbenchSource).toContain('onActivated')
    expect(workbenchSource).toContain('30_000')
  })

  it('无权限提示与阶段加载保留', () => {
    expect(workbenchSource).toContain('ErrorState')
    expect(workbenchSource).toContain('SkeletonBlock')
  })
})

describe('workbench.ts 端点契约', () => {
  it('days/force_refresh 参数与契约键', () => {
    expect(workbenchApiSource).toContain('days')
    expect(workbenchApiSource).toContain('force_refresh')
    expect(workbenchApiSource).toContain('ai_qc')
    expect(workbenchApiSource).toContain('timeliness')
    expect(workbenchApiSource).toContain('prearchive')
    expect(workbenchApiSource).toContain('relay')
    expect(workbenchApiSource).toContain('system')
  })
})
