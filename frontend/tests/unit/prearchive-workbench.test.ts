/**
 * WP07：病案室辅助核查台测试——模式横幅/五卡/FilterPanel/聚合主表/核查抽屉
 * 行内闭环与 360 按钮（源码契约断言，仓库惯例）。
 */
import { describe, expect, it } from 'vitest'
import pageSource from '@/features/governance/WorkbenchPage.vue?raw'

describe('WP07：病案室辅助核查台（WorkbenchPage）', () => {
  it('PageHeader 标题/描述与模式横幅双态（影子待启用 warning / 影子辅助 info）', () => {
    expect(pageSource).toContain('title="归档前形式核查"')
    expect(pageSource).toContain('出院病历归档前自动检查缺失文书、签名与形式规范，辅助病案室质控')
    expect(pageSource).toContain('影子模式待启用，详见 123 操作手册')
    expect(pageSource).toContain('当前为影子辅助模式：结果仅供病案室在本系统内核对，不会推送给临床或无纸化系统')
    expect(pageSource).toMatch(/type="warning"[\s\S]{0,400}影子模式待启用/)
    expect(pageSource).toMatch(/type="info"[\s\S]{0,200}影子辅助模式/)
    expect(pageSource).toContain(':closable="false"')
    expect(pageSource).toContain('show-icon')
  })

  it('SummaryStrip 五卡（已检查/检出缺陷/待确认/整改中/误报占比·按当前页 hint）', () => {
    expect(pageSource).toContain('SummaryStrip')
    for (const label of ['已检查病历', '检出缺陷病历', '待病案室确认', '误报占比']) {
      expect(pageSource).toContain(label)
    }
    expect(pageSource).toContain('按当前页')
    expect(pageSource).toContain('误报占比')
  })

  it('FilterPanel：出院日期范围/科室 filterable/复核状态/患者筛选 + #more 规则分类', () => {
    expect(pageSource).toContain('FilterPanel')
    expect(pageSource).toContain('出院日期范围')
    expect(pageSource).toContain('type="daterange"')
    expect(pageSource).toContain('出院科室')
    expect(pageSource).toContain('filterable')
    expect(pageSource).toContain('复核状态')
    expect(pageSource).toContain('患者姓名或住院号')
    expect(pageSource).toContain('规则分类')
    // 主行筛选有持久中文标签（不靠 placeholder 充当字段名）
    for (const label of ['复核状态', '出院科室']) {
      expect(pageSource).toContain(label)
    }
    expect(pageSource).toContain('wb-filter-item')
  })

  it('主表按患者聚合：检出缺陷胶囊/最高严重度 RiskTag/复核状态/无纸化推送预留灰标/360', () => {
    expect(pageSource).toContain('DataTableShell')
    expect(pageSource).toContain('calc(100vh - 380px)')
    expect(pageSource).toContain('fixed="left"')
    expect(pageSource).toContain('检出缺陷')
    expect(pageSource).toContain('RiskTag')
    expect(pageSource).toContain('复核状态')
    expect(pageSource).toContain('影子模式 · 未推送')
    expect(pageSource).toContain('HolographyButton')
    expect(pageSource).toContain('核查处理')
  })

  it('核查抽屉 780px：患者卡 + 360 主按钮 + 缺陷卡行内三按钮 + 技术证据折叠', () => {
    expect(pageSource).toContain('size="780px"')
    expect(pageSource).toContain('打开 360 全息核对病历')
    for (const label of ['确认缺陷', '标为误报', '已补齐']) {
      expect(pageSource).toContain(label)
    }
    expect(pageSource).toContain('el-collapse')
    expect(pageSource).toContain('技术证据（运行批次 / 原始结论 JSON）')
    expect(pageSource).toContain('raw-json')
  })

  it('误报必须选原因（四项中文枚举），提交走既有 BFF issues actions', () => {
    for (const reason of ['文书其实存在', '规则不适用本科室', '时间判断错误', '其他']) {
      expect(pageSource).toContain(reason)
    }
    expect(pageSource).toContain('请选择误报原因（必填）')
    // 提交到既有 BFF 端点封装（wbIssueActionApi → /prearchive-admin/issues/{id}/actions）
    expect(pageSource).toContain('wbIssueActionApi')
    expect(pageSource).toContain('expect_issue_version')
  })

  it('既有能力保留：BFF 取数/序号守卫/权限 fail-closed/试运行观察', () => {
    expect(pageSource).toContain('wbChecksApi')
    expect(pageSource).toContain('wbCheckDetailApi')
    expect(pageSource).toContain('prcTrialRunsApi')
    expect(pageSource).toContain('listSeq')            // 旧请求晚到守卫
    expect(pageSource).toContain('permsStateOf')       // 权限 fail-closed
    expect(pageSource).toContain('prearchive_issue_review')
    expect(pageSource).toContain('prearchive_issue_feedback')
    expect(pageSource).toContain('recheck_passed')     // 复核权限动作保留
    // 不裸铺整页 JSON（技术报文收进折叠）
    const mainArea = pageSource.split('技术证据')[0] || pageSource
    expect(mainArea).not.toContain('JSON.stringify(detail')
  })
})
