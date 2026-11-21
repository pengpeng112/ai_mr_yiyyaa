/**
 * WP09：定时调度页三页签重构测试（任务书 §六）。
 * 诊断警告渲染（discharge_effectiveness + 保存响应 warnings）、Cron 选项才显示
 * 输入框、SummaryStrip 四卡、遗留单任务折叠说明。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import pageSource from '@/features/tasks/SchedulerPage.vue?raw'

const pagePath = resolve(process.cwd(), 'src/features/tasks/SchedulerPage.vue')
const page = readFileSync(pagePath, 'utf-8')

describe('WP09：SchedulerPage 三页签重构', () => {
  it('SummaryStrip 四状态卡（调度器/每日任务/出院任务/病历时效扫描无字段显示 —）', () => {
    expect(page).toContain('SummaryStrip')
    for (const label of ['调度器', '每日在院任务', '出院终末任务', '病历时效扫描']) {
      expect(page).toContain(label)
    }
    expect(page).toContain("value: '—'")
    expect(page).toContain('每 5 分钟（时效扫描独立于本调度器')
  })

  it('el-tabs 三页签（每日在院质控/出院终末质控/执行历史）', () => {
    for (const label of ['每日在院质控', '出院终末质控', '执行历史']) {
      expect(page).toContain(label)
    }
    expect(page).toContain('el-tabs v-model="activeTab"')
  })

  it('Cron 选项才显示输入框并提示格式（三处条件渲染）', () => {
    // 每日卡 + 出院卡两处 cron 条件渲染 + 格式提示
    const cronBlocks = page.split("schedule_mode === 'cron'").length - 1
    expect(cronBlocks).toBeGreaterThanOrEqual(2)  // 每日卡与出院卡各一处 v-if
    expect(page).toContain('5 段 cron（分 时 日 月 周）')
    // 频率单选含「自定义 Cron」
    expect(page).toContain('自定义 Cron')
  })

  it('discharge_effectiveness 诊断卡：全部有效绿色 alert / 否则橙色逐条 code+detail', () => {
    expect(page).toContain('discharge_effectiveness')
    expect(page).toContain('所选质控类型均支持出院终末路径')
    expect(page).toMatch(/type="success"[\s\S]{0,220}出院终末路径/)
    expect(page).toContain('effectivenessWarnings')
    expect(page).toContain('w.code')
    expect(page).toContain('w.source')
    expect(page).toContain('w.detail')
  })

  it('保存响应 effectiveness_warnings 逐条展示（橙色）', () => {
    expect(page).toContain('saveEffectivenessWarnings')
    expect(page).toContain('data.effectiveness_warnings')
    expect(page).toContain('保存成功，但存在生效性告警')
  })

  it('执行历史：模式中文 + 跳过列 + 失败行错误 popover', () => {
    expect(page).toContain('auditRunModeLabel')
    expect(page).toContain('每日增量')
    expect(page).toContain('出院终末')
    expect(page).toContain('跳过')
    expect(page).toContain('el-popover')
    expect(page).toContain('row.error_code')
  })

  it('遗留单任务：双调度启用时灰色说明折叠（status.legacy）', () => {
    expect(page).toContain('已启用双调度，旧版单任务配置不生效')
    expect(page).toContain('legacy-collapse')
    expect(page).toContain('statusData.legacy')
  })

  it('既有端点与契约保留：status/run_locks/trigger/run-summary/runtime-summary', () => {
    for (const endpoint of [
      "'/scheduler/status'", "'/scheduler/history'",
      'apiPost(`/scheduler/start`', 'apiPost(`/scheduler/stop`', "'/scheduler/trigger'", "'/scheduler/run-summary'",
      "'/config/scheduler-daily'", "'/config/scheduler-discharge'",
      "'/config/runtime-summary'", "'/audit-types/options'", "'/config/departments/list'",
    ]) {
      expect(page).toContain(endpoint)
    }
    expect(page).toContain('staleLocks')
    expect(page).toContain('run_locks')
  })
})
