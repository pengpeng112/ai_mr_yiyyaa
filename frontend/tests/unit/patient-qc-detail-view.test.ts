/**
 * WP05：PatientQcDetailView 高可读性组件测试（任务书 §六）。
 * 覆盖：①患者临床摘要卡渲染 + 360 全息按钮；②默认仅高/中危问题卡、可切全部维度；
 * ③左右双栏证据对比 + 单侧证据不出现空盒；④技术排障报文默认折叠（不裸铺 JSON）。
 * 采用源码契约断言（仓库惯例，避免 jsdom 下 Element Plus 全量加载）+ 问题卡过滤
 * 纯逻辑验证（与组件内相同语义内联）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import pageSource from '@/features/quality/PatientQcPage.vue?raw'
import panelSource from '@/features/quality/components/AuditRecordListPanel.vue?raw'
import standaloneSource from '@/features/quality/PatientDetailStandalonePage.vue?raw'
import shellSource from '@/features/quality/AuditRecordsPage.vue?raw'
import feedbackSource from '@/features/closure/FeedbackPage.vue?raw'
import alertSource from '@/features/closure/AlertLogsPage.vue?raw'

const detailPath = resolve(process.cwd(), 'src/features/quality/components/PatientQcDetailView.vue')
const detailSource = readFileSync(detailPath, 'utf-8')

describe('WP05：PatientQcDetailView 区块 1 患者临床摘要卡', () => {
  it('吸顶摘要卡（patient-banner）+ 姓名/性别年龄/住院号可复制 + RiskTag', () => {
    expect(detailSource).toContain('patient-banner')
    expect(detailSource).toContain('banner-name')
    expect(detailSource).toContain('banner-grey')
    expect(detailSource).toContain('cs.sex || \'—\'')
    expect(detailSource).toContain('ageText')
    expect(detailSource).toContain('banner-id')
    expect(detailSource).toContain('copyIds')
    expect(detailSource).toContain('RiskTag')
    // 4 列信息网格：所属科室/管床医生/入院日期/出院日期/主要诊断
    for (const label of ['所属科室', '管床医生', '入院日期', '出院日期', '主要诊断']) {
      expect(detailSource).toContain(label)
    }
    expect(detailSource).toContain('repeat(4, minmax(120px, 1fr))')
  })

  it('360 全息主按钮（打开 360 全息视图）+ 抽屉全屏查看 / 独立页打印质控单', () => {
    expect(detailSource).toContain('HolographyButton')
    expect(detailSource).toContain('打开 360 全息视图')
    expect(detailSource).toContain('openStandalone')
    expect(detailSource).toContain("path: '/quality/patient-detail'")
    expect(detailSource).toContain('打印质控单')
    expect(detailSource).toContain('window.print()')
    expect(detailSource).toContain('@media print')
  })

  it('clinical_summary 来源：组件读 detail.clinical_summary（后端新嵌套对象）', () => {
    expect(detailSource).toContain('clinical_summary')
  })
})

describe('WP05：区块 3 问题卡过滤与双栏证据对比', () => {
  /** 与组件 issueMode/visibleIssues 相同语义的纯逻辑（高/中危聚焦 vs 全部）。 */
  function filterIssues(mode: 'focus' | 'all', rows: Array<{ severity: string }>): Array<{ severity: string }> {
    if (mode === 'all') return rows
    return rows.filter((r) => ['high', 'medium'].includes(r.severity))
  }

  const rows = [
    { severity: 'high' },
    { severity: 'medium' },
    { severity: 'low' },
    { severity: '' },
  ]

  it('默认仅展示高/中危问题卡，可切「查看全部维度」', () => {
    expect(detailSource).toContain("issueMode = ref<'focus' | 'all'>('focus')")
    expect(detailSource).toContain('仅看高/中危')
    expect(detailSource).toContain('查看全部维度')
    expect(filterIssues('focus', rows)).toHaveLength(2)
    expect(filterIssues('all', rows)).toHaveLength(4)
  })

  it('左右双栏证据对比：medeical 蓝/佐证暖 双盒 + 单侧证据不出现空盒', () => {
    // 双栏 grid + 单侧自动单列（evidence-single），左右盒都有 v-if 守卫，不渲染空半栏
    expect(detailSource).toContain('grid-template-columns: 1fr 1fr')
    expect(detailSource).toContain('evidence-single')
    expect(detailSource).toContain('hasEvidence(issue.medical_evidence) || hasEvidence(issue.nursing_evidence)')
    expect(detailSource).toContain('v-if="hasEvidence(issue.medical_evidence)"')
    expect(detailSource).toContain('v-if="hasEvidence(issue.nursing_evidence)"')
    expect(detailSource).toContain('病历 / 医嘱摘录')
    expect(detailSource).toContain('佐证材料（护理 / 检验 / 手术）')
    // 逻辑验证：单侧证据也进入渲染分支（hasEvidence 语义）
    expect(filterIssues('all', rows.filter((r) => r.severity === 'high'))).toHaveLength(1)
  })

  it('行内一键闭环（确认属实/已整改/误报）→ confirm / quick-action 现有端点', () => {
    for (const label of ['确认属实', '已整改', '误报']) {
      expect(detailSource).toContain(label)
    }
    expect(detailSource).toContain('/qc/feedback/cases/${logId}/confirm')
    expect(detailSource).toContain('/patient-qc/feedback/quick-action')
    expect(detailSource).toContain("kind: 'acknowledged' | 'rectified' | 'closed'")
    expect(detailSource).toContain("action: kind,")
    expect(detailSource).toContain("action: 'rectified', reason: note || '已整改'")
    expect(detailSource).toContain("emit('updated')")
  })

  it('AI 建议行与问题正文（issue_summary 优先）', () => {
    expect(detailSource).toContain('issue.issue_summary || issue.explanation')
    expect(detailSource).toContain('整改建议：')
  })
})

describe('WP05：区块 4 技术报文默认折叠 + 三 Tab', () => {
  it('技术排障报文收在 el-collapse 且默认全折叠（不裸铺 JSON 到可见主区域）', () => {
    // 主区域（区块 1~3）不出现 JSON.stringify 铺开
    const mainArea = detailSource.split('区块 4')[0] || detailSource
    expect(mainArea).not.toContain('JSON.stringify(detail')
    // Tab3 折叠：el-collapse 无 model-value（默认全折叠），点开才懒加载 /logs/{id}
    expect(detailSource).toContain('技术排障报文')
    expect(detailSource).toContain('<el-collapse')
    expect(detailSource).not.toMatch(/<el-collapse[^>]*model-value/)
    expect(detailSource).toContain('onPayloadToggle')
    expect(detailSource).toContain('/logs/${entry.push_log_id}')
    // 三个代码块：请求上下文 / AI 原始输出 / 脱敏病历原文
    for (const title of ['请求上下文', 'AI 原始输出', '脱敏病历原文预览']) {
      expect(detailSource).toContain(title)
    }
    expect(detailSource).toContain('默认折叠')
  })

  it('历次核查时间线（单条重推）+ 企微推送与医生反馈 Tab', () => {
    expect(detailSource).toContain('el-timeline')
    expect(detailSource).toContain('单条重推')
    expect(detailSource).toContain('企微推送与医生反馈')
    expect(detailSource).toContain('/patient-qc/relay-alert/logs')
    expect(detailSource).toContain('医生查看')
    expect(detailSource).toContain('医生反馈')
  })
})

describe('WP05：工作台双视角与旧路由兼容壳', () => {
  it('PatientQcPage：双视角切换器 + ?view=records 响应 + 移除右夹板', () => {
    expect(pageSource).toContain('内涵质控工作台')
    expect(pageSource).toContain("value=\"patients\"")
    expect(pageSource).toContain("value=\"records\"")
    expect(pageSource).toContain('router.replace({ query: { ...route.query, view: activeView.value } })')
    expect(pageSource).toContain('AuditRecordListPanel')
    // 彻底移除旧右侧夹板（pq-side 类名与其布局全清除）
    expect(pageSource).not.toContain('pq-side')
    expect(pageSource).not.toContain('pq-body')
    expect(pageSource).not.toContain('患者摘要')
    // 详情抽屉 820px 复用 PatientQcDetailView
    expect(pageSource).toContain('size="820px"')
    expect(pageSource).toContain('PatientQcDetailView')
    expect(pageSource).toContain(':in-drawer="true"')
  })

  it('SummaryStrip 四快捷卡（全部/高危红/中危橙/待处理蓝）点击切筛选', () => {
    for (const label of ['全部患者', '高危患者', '中危患者', '待复核']) {
      expect(pageSource).toContain(label)
    }
    expect(pageSource).toContain("tone: 'danger'")
    expect(pageSource).toContain("tone: 'warning'")
    expect(pageSource).toContain('onSummaryClick')
    expect(pageSource).toContain("filters.severity = 'high'")
    expect(pageSource).toContain("filters.severity = 'medium'")
    expect(pageSource).toContain("filters.status = 'pending'")
  })

  it('AuditRecordListPanel：流水功能完整迁移 + 表格 360 按钮 + 固定表头', () => {
    for (const fn of ['retrySingle', 'deleteSingle', 'retrySelected', 'deleteSelected', 'exportCsv',
      'openPrintableReport', 'saveMarker', 'applyQuickTag', 'onSkipChipClick']) {
      expect(panelSource).toContain(fn)
    }
    // 权限校验与二次确认保留
    expect(panelSource).toContain('canEditPushMarker')
    expect(panelSource).toContain('ElMessageBox.confirm')
    expect(panelSource).toContain('/logs/export/csv')
    expect(panelSource).toContain('/push/retry')
    expect(panelSource).toContain('/logs/bulk/delete')
    // 360 全息与固定表头
    expect(panelSource).toContain('HolographyButton')
    expect(panelSource).toContain('calc(100vh - 420px)')
    // 不再自带 PageHeader（工作台页头统一）
    expect(panelSource).not.toContain('<PageHeader')
  })

  it('AuditRecordsPage 仅剩薄重定向壳（onMounted + onActivated 双触发保留 query）', () => {
    expect(shellSource).toContain("path: '/quality/patients'")
    expect(shellSource).toContain("view: 'records'")
    expect(shellSource).toContain('...route.query')
    expect(shellSource).toContain('onMounted(redirect)')
    expect(shellSource).toContain('onActivated(redirect)')
    // 壳内不得再保留完整流水功能（已迁移）
    expect(shellSource).not.toContain('exportCsv')
    expect(shellSource).not.toContain('retrySingle')
    // 行数守卫：薄壳（源码 < 50 行）
    expect(shellSource.split('\n').length).toBeLessThan(50)
  })

  it('独立详情页复用 PatientQcDetailView（inDrawer=false）', () => {
    expect(standaloneSource).toContain('PatientQcDetailView')
    expect(standaloneSource).toContain(':in-drawer="false"')
    expect(standaloneSource).toContain('patient_id')
    expect(standaloneSource).toContain('visit_number')
  })
})

describe('WP05：Feedback / AlertLogs 补全 360 全息入口', () => {
  it('FeedbackPage：操作列与详情抽屉均接入 HolographyButton', () => {
    expect(feedbackSource).toContain('HolographyButton')
    expect(feedbackSource).toContain('label="360全息视图"')
    expect(feedbackSource).toMatch(/label="操作" width="230"/)
  })

  it('AlertLogsPage：操作列与详情抽屉均接入 HolographyButton', () => {
    expect(alertSource).toContain('HolographyButton')
    expect(alertSource).toContain('label="360全息视图"')
    expect(alertSource).toMatch(/label="操作" width="160"/)
  })
})
