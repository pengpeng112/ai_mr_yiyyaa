import { describe, expect, it } from 'vitest'
import drawerSource from '@/features/timeliness/RuleEditorDrawer.vue?raw'
import dryRunSource from '@/features/timeliness/DryRunPanel.vue?raw'
import listPageSource from '@/features/timeliness/RuleListPage.vue?raw'
import ledgerSource from '@/features/timeliness/EventLedgerPage.vue?raw'
import monthlySource from '@/features/timeliness/MonthlyReportPage.vue?raw'
import apiSource from '@/features/timeliness/api.ts?raw'
import typesSource from '@/features/timeliness/types.ts?raw'
import { ROUTE_MANIFEST, getManifestByMenuId } from '@/router/route-manifest'

// T6 §三.1：规则编辑抽屉 5 个配置区块（§11.1）
describe('T6 RuleEditorDrawer：五区块结构（§11.1）', () => {
  it('区块 1 基本信息：编码只读 + 名称/分类/启用开关/适用科室（全院/多选）', () => {
    expect(drawerSource).toContain('区块 1 · 基本信息与分类')
    expect(drawerSource).toContain('rule-code-readonly')
    expect(drawerSource).toMatch(/el-input[^>]*:model-value="draft\.rule_code" disabled/)
    expect(drawerSource).toContain('RULE_CATEGORY_OPTIONS')
    expect(drawerSource).toMatch(/deptScopeAll/)
    expect(drawerSource).toContain('全院')
    expect(drawerSource).toContain('指定科室')
    expect(drawerSource).toMatch(/draft\.deptScopeCodes[^]*multiple/)
  })

  it('区块 2 触发源：trigger_type 下拉 + 字段/运算符/值 行编辑器，无手写 SQL 入口', () => {
    expect(drawerSource).toContain('区块 2 · 触发源')
    expect(drawerSource).toContain('draft.trigger_type')
    expect(drawerSource).toContain('row.field')
    expect(drawerSource).toContain('row.op')
    expect(drawerSource).toContain('row.value')
    expect(drawerSource).toContain('不允许手写 SQL')
    expect(drawerSource).not.toMatch(/type="textarea"[^]*filter/)
    expect(drawerSource).not.toContain('SELECT ')
  })

  it('区块 3 目标文书：mr_class 多选/标题关键词/职称关键词/时间要求/完成基准/时限+单位', () => {
    expect(drawerSource).toContain('区块 3 · 目标文书与完成标准')
    expect(drawerSource).toContain('draft.mrClass')
    expect(drawerSource).toContain('dicts?.mr_class')
    expect(drawerSource).toContain('draft.titleKeywords')
    expect(drawerSource).toContain('draft.signerTitleKeywords')
    expect(drawerSource).toContain('draft.timeGeT0')
    expect(drawerSource).toContain('FIRST_SIGN')
    expect(drawerSource).toContain('CREATE')
    expect(drawerSource).toContain('draft.limit.unit')
    expect(drawerSource).toContain('工作日')
    expect(drawerSource).toContain('limit-error')
  })

  it('区块 4 提醒：提前量 + 通道勾选，未授权通道禁用并显示「未授权」与原因', () => {
    expect(drawerSource).toContain('区块 4 · 事前提醒策略')
    expect(drawerSource).toContain('draft.warnBefore')
    expect(drawerSource).toContain(':disabled="!channel.authorized"')
    expect(drawerSource).toContain('未授权')
    expect(drawerSource).toContain('unauthorizedReason')
  })

  it('区块 5 超时处置：三档单选，LOCK_EMR 禁用绑定与原因提示；默认扣罚 200', () => {
    expect(drawerSource).toContain('区块 5 · 超时处置与考核')
    expect(drawerSource).toContain('value="SHADOW"')
    expect(drawerSource).toContain('value="WARN_ONLY"')
    expect(drawerSource).toContain('value="LOCK_EMR"')
    expect(drawerSource).toContain(':disabled="!lockEmr.allowed"')
    expect(drawerSource).toContain('lock-emr-reason')
    expect(drawerSource).toContain('DEFAULT_PENALTY_AMOUNT')
    expect(drawerSource).toContain('draft.annualTally')
  })

  it('底部按钮：试算（打开 DryRunPanel 传待保存口径）/ 保存为新版本（先弹差异）/ 取消', () => {
    expect(drawerSource).toContain('试算</el-button>')
    expect(drawerSource).toContain('保存为新版本')
    expect(drawerSource).toContain('取消</el-button>')
    expect(drawerSource).toContain('dryRunVisible')
    expect(drawerSource).toContain(':changes="draftToChanges(draft)"')
    expect(drawerSource).toContain('确认保存：与当前版本的差异')
    expect(drawerSource).toContain('diffVersions(')
    expect(drawerSource).toContain('createRuleVersionApi')
    expect(drawerSource).toContain('toggleRuleApi')
  })
})

// T6 §三.3：试算结果渲染（DryRunPanel）
describe('T6 DryRunPanel：试算结果渲染', () => {
  it('渲染 dryRunSummary 摘要、状态直方图、样例表与截断提示', () => {
    expect(dryRunSource).toContain('dryRunSummary')
    expect(dryRunSource).toContain('dry-run-headline')
    expect(dryRunSource).toContain('summary.histogram')
    expect(dryRunSource).toContain('result.samples')
    expect(dryRunSource).toContain('sample_truncated')
    expect(dryRunSource).toContain('绝不写库')
  })

  it('数据源不可用降级提示（data_source=unavailable）与失败分支', () => {
    expect(dryRunSource).toContain('dataSourceNote')
    expect(typesSource).toContain("data_source === 'unavailable'")
    expect(typesSource).toContain('空数据试算')
    expect(dryRunSource).toContain('dry-run-error')
  })

  it('调用 dry-run 接口且经 BFF 前缀（不直连）', () => {
    expect(dryRunSource).toContain('dryRunRuleApi')
    expect(dryRunSource).not.toMatch(/https?:\/\//)
    expect(dryRunSource).not.toContain('10.20.1.153')
  })
})

// T6 §二：四个页面与 API 契约
describe('T6 页面与 API 契约', () => {
  it('api.ts 全部走 /timeliness BFF 路径并编码路径参数', () => {
    for (const path of [
      '/timeliness/dicts',
      '/timeliness/rules',
      '/versions',
      '/toggle',
      '/dry-run',
      '/timeliness/events',
      '/timeliness/stats/monthly',
      '/timeliness/export/monthly',
    ]) {
      expect(apiSource).toContain(path)
    }
    expect(apiSource).toContain('encodeURIComponent')
    expect(apiSource).toContain("'/departments'")
    expect(apiSource).not.toMatch(/https?:\/\//)
    expect(apiSource).not.toContain(':8')
  })

  it('RuleListPage：列表/启停/编辑/试算/版本历史入口', () => {
    expect(listPageSource).toContain('fetchTimelinessRulesApi')
    expect(listPageSource).toContain('toggleRuleApi')
    expect(listPageSource).toContain('RuleEditorDrawer')
    expect(listPageSource).toContain('DryRunPanel')
    expect(listPageSource).toContain('fetchRuleVersionsApi')
    expect(listPageSource).toContain('d8_note')
  })

  it('EventLedgerPage：过滤参数与后端 /events 一致 + 详情历史/动作日志', () => {
    for (const key of ['dept', 'rule_code', 'status', 'patient_id', 'date_from', 'date_to']) {
      expect(ledgerSource).toContain(key)
    }
    expect(ledgerSource).toContain('fetchTimelinessEventApi')
    expect(ledgerSource).toContain('detail.history')
    expect(ledgerSource).toContain('detail.action_logs')
  })

  it('MonthlyReportPage：月度统计 + 导出（apiDownload + 触发浏览器下载；WP04 改区间版 API）', () => {
    // WP04：统计请求升级为 fetchMonthlyRangeStatsApi（区间+分页），导出走 exportMonthlyApi。
    expect(monthlySource).toContain('fetchMonthlyRangeStatsApi')
    expect(monthlySource).toContain('exportMonthlyApi')
    expect(monthlySource).toContain('timeliness_export')
    expect(monthlySource).toContain('stats.value?.totals')
  })
})

// T6 §允许修改：route-manifest 追加 3 个菜单项与风险级
describe('T6 route-manifest：3 个时效菜单项', () => {
  it('规则配置 system-write；事件台账/月度统计 readonly', () => {
    const rules = getManifestByMenuId('timeliness-rules')!
    expect(rules.risk).toBe('system-write')
    expect(rules.group).toBe('governance')
    expect(rules.mutationsEnabled).toBe(true)
    expect(rules.component).toBeTypeOf('function')

    const events = getManifestByMenuId('timeliness-events')!
    expect(events.risk).toBe('readonly')
    expect(events.group).toBe('timeliness')  // 2026-11-15 菜单重构：quality → timeliness

    const monthly = getManifestByMenuId('timeliness-monthly')!
    expect(monthly.risk).toBe('readonly')
    expect(monthly.group).toBe('timeliness')
  })

  it('menuId/name 全局仍唯一（不破坏既有 fail-closed 契约）', () => {
    const menuIds = ROUTE_MANIFEST.map((e) => e.menuId)
    const names = ROUTE_MANIFEST.map((e) => e.name)
    expect(new Set(menuIds).size).toBe(menuIds.length)
    expect(new Set(names).size).toBe(names.length)
  })
})

// ---- 2026-11-14 P0：台账中文字段绑定渲染 ----
describe('P0：台账中文字段绑定', () => {
  it('EventLedgerPage：规则名/科室名/医生姓名（工号）渲染，长 uid 收折到展开行', () => {
    expect(ledgerSource).toContain('row.rule_name || row.rule_code')
    expect(ledgerSource).toContain('row.dept_name || row.dept_code')
    expect(ledgerSource).toContain('responsible_doctor_name')
    expect(ledgerSource).toContain('row.event_uid')        // 展开行收折展示
    expect(ledgerSource).not.toMatch(/prop="event_uid" label/)
  })

  it('ApprovalLedgerPage：申请医生姓名（工号）渲染', async () => {
    const approvalSource = (await import('@/features/timeliness/ApprovalLedgerPage.vue?raw')).default
    expect(approvalSource).toContain('apply_user_name')
    expect(approvalSource).toContain('apply_user_id')
    expect(approvalSource).toContain('dept_name || row.dept_code')
  })

  it('MonthlyReportPage：科室名/医生姓名（工号）渲染', () => {
    expect(monthlySource).toContain('row.dept_name || row.dept_code')
    expect(monthlySource).toContain('responsible_doctor_name')
  })

  it('types.ts：TlEvent/TlApproval/MonthlyRow 声明 4 个中文展示字段', () => {
    for (const key of [
      'dept_name?: string',
      'responsible_doctor_name?: string',
      'rule_name?: string',
      'apply_user_name?: string',
    ]) {
      expect(typesSource).toContain(key)
    }
  })
})
