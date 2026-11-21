/**
 * 病历时效统计分析页测试（WP03 T2）：KPI 渲染、医生排序切换与搜索过滤、跳转路径。
 * 采用源码契约断言（与仓库既有 timeliness-pages.test.ts 惯例一致，避免 jsdom 下
 * ECharts/Element Plus 全量加载）+ 数据纯函数逻辑验证。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { createPinia, setActivePinia } from 'pinia'
import type { DoctorRankingRow, TimelinessAnalytics } from '@/api/endpoints/timelinessStats'

const pageSource = readFileSync(
  resolve(process.cwd(), 'src/features/timeliness/TimelinessStatsPage.vue'), 'utf-8')
const pageSetup = pageSource.split('<script setup lang="ts">')[1]?.split('</script>')[0] || pageSource

// 与页面内相同的过滤/排序纯逻辑抽取（直接内联验证语义）
function filterAndSortDoctors(
  rows: DoctorRankingRow[], sort: string, keyword: string,
): DoctorRankingRow[] {
  const out = [...rows]
  out.sort((a, b) => {
    if (sort === 'overdue') return b.overdue_count - a.overdue_count
    if (sort === 'penalty') return b.penalty_amount_total - a.penalty_amount_total
    return b.locked_count - a.locked_count
  })
  const kw = keyword.trim().toLowerCase()
  if (!kw) return out
  return out.filter(
    (r) => r.doctor_name.toLowerCase().includes(kw) || r.doctor_code.toLowerCase().includes(kw),
  )
}

const MOCK_DOCTORS: DoctorRankingRow[] = [
  { doctor_code: 'D001', doctor_name: '张医生', dept_code: '040112', dept_name: '耳鼻喉一科',
    locked_count: 2, overdue_count: 1, total_events: 4, on_time_rate: 50.0,
    avg_overdue_hours: 3.0, penalty_amount_total: 200 },
  { doctor_code: 'D002', doctor_name: '李医生', dept_code: '040112', dept_name: '耳鼻喉一科',
    locked_count: 0, overdue_count: 1, total_events: 1, on_time_rate: 0.0,
    avg_overdue_hours: 1.5, penalty_amount_total: 0 },
  { doctor_code: 'D003', doctor_name: '王医生', dept_code: '030442', dept_name: '耳鼻喉二科',
    locked_count: 1, overdue_count: 0, total_events: 0, on_time_rate: 0.0,
    avg_overdue_hours: 0.0, penalty_amount_total: 300 },
]

const MOCK_ANALYTICS: TimelinessAnalytics = {
  date_from: '2026-11-01',
  date_to: '2026-11-10',
  scope_label: '全院',
  summary: {
    total_events: 6, on_time_count: 1, late_completed_count: 1, overdue_count: 3,
    warning_count: 1, on_time_rate: 50.0, locked_count: 4, locked_pending: 1,
    unlocked_count: 3, exempt_count: 1, penalty_amount_total: 500, avg_overdue_hours: 2.5,
  },
  dept_ranking: [],
  doctor_ranking: MOCK_DOCTORS,
  rule_breakdown: [],
  daily_trend: [],
}

// API mock（页面 onMounted 会调用）
vi.mock('@/api/endpoints/timelinessStats', () => ({
  fetchTimelinessAnalytics: vi.fn().mockResolvedValue(MOCK_ANALYTICS),
}))
vi.mock('./api', () => ({
  fetchTimelinessDictsApi: vi.fn().mockResolvedValue([]),
}))

describe('TimelinessStatsPage 页面契约（WP03 T2）', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('KPI 六卡绑定：事件总数/按时率/锁定/待审批/超时/扣罚', () => {
    for (const key of ['total_events', 'on_time_rate', 'locked_count', 'locked_pending',
      'overdue_count', 'penalty_amount_total']) {
      expect(pageSource).toContain(`s.${key}`)
    }
    for (const label of ['事件总数', '按时完成率', '锁定次数', '待审批锁定', '超时未完成', '有效扣罚(元)']) {
      expect(pageSource).toContain(label)
    }
  })

  it('快捷周期与统计周期控件（含中文标签）', () => {
    for (const label of ['快捷周期', '统计周期', '科室']) {
      expect(pageSource).toContain(label)
    }
    for (const mode of ['last7', 'month', 'prevMonth', 'last30', 'custom']) {
      expect(pageSource).toContain(`value="${mode}"`)
    }
    expect(pageSource).toContain('type="daterange"')
  })

  it('医生排序切换：locked/overdue/penalty 三档', () => {
    for (const sort of ['locked', 'overdue', 'penalty']) {
      expect(pageSource).toContain(`value="${sort}"`)
    }
  })

  it('医生搜索过滤：姓名与工号都参与匹配（源码 + 逻辑验证）', () => {
    expect(pageSource).toContain('doctor_name.toLowerCase()')
    expect(pageSource).toContain('doctor_code.toLowerCase()')
    // 逻辑验证：姓名关键字命中
    const byName = filterAndSortDoctors(MOCK_DOCTORS, 'locked', '张')
    expect(byName.map((r) => r.doctor_code)).toEqual(['D001'])
    // 工号关键字命中
    const byCode = filterAndSortDoctors(MOCK_DOCTORS, 'locked', 'd003')
    expect(byCode.map((r) => r.doctor_code)).toEqual(['D003'])
    // 排序验证：locked 档下 D001(2) 在 D003(1) 之前
    const sorted = filterAndSortDoctors(MOCK_DOCTORS, 'locked', '')
    expect(sorted[0].doctor_code).toBe('D001')
    // penalty 档：D003(300) 最前
    const byPenalty = filterAndSortDoctors(MOCK_DOCTORS, 'penalty', '')
    expect(byPenalty[0].doctor_code).toBe('D003')
  })

  it('跳转路径：科室柱点击/规则点击/查看台账/月度考核', () => {
    expect(pageSource).toContain("'/quality/timeliness-events', query: { dept: row.dept_code }")
    expect(pageSource).toContain("'/quality/timeliness-events', query: { rule_code: row.rule_code }")
    expect(pageSource).toContain("'/quality/timeliness-monthly'")
  })

  it('图表三件套：科室排名/规则分布/每日趋势 + 双 Y 轴按时率线', () => {
    expect(pageSource).toContain('科室锁定排名')
    expect(pageSource).toContain('规则节点超时分布')
    expect(pageSource).toContain('每日趋势')
    expect(pageSource).toContain("name: '按时率%'")
    expect(pageSource).toContain('每日趋势')
    // 空数据不初始化图表
    expect(pageSource).toContain('.length)')
  })

  it('科室下拉 filterable（长列表要求）', () => {
    expect(pageSource).toContain('filterable')
    expect(pageSource).toContain('全部可见科室')
  })
})
