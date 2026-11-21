/**
 * WP06：AuditTypeWizardDrawer rawExtras 无损往返单测（任务书 §六 2）。
 * 读取真实 config/config.json.template 的全部 audit_types[]，执行
 * ruleToForm -> formToPayload 往返转换，断言关键底层字段（sources/query_sql/
 * jsonpath/field_mapping/未知扩展键）100% 一致零丢失（diff === []）。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { formToPayload, ruleToForm, DEFAULT_MESSAGE_TEMPLATE } from '@/utils/audit-type-form'
import pageSource from '@/features/governance/AuditTypesPage.vue?raw'
import prearchiveSource from '@/features/governance/PrearchiveRulesPage.vue?raw'
import ruleListSource from '@/features/timeliness/RuleListPage.vue?raw'

// 真实配置模板（vitest 工作目录=frontend/，模板在仓库根 config/ 下）
const TEMPLATE_PATH = resolve(process.cwd(), '../config/config.json.template')
const template = JSON.parse(readFileSync(TEMPLATE_PATH, 'utf-8')) as {
  audit_types: Array<Record<string, any>>
}

/** 递归收集「原对象中存在、重建后缺失或值变化」的路径（丢失=有 diff）。 */
function collectDiff(original: unknown, rebuilt: unknown, path = ''): string[] {
  const diffs: string[] = []
  if (Array.isArray(original)) {
    const rebuiltArr = Array.isArray(rebuilt) ? rebuilt : []
    original.forEach((item, index) => {
      diffs.push(...collectDiff(item, rebuiltArr[index], `${path}[${index}]`))
    })
    return diffs
  }
  if (original !== null && typeof original === 'object') {
    const originObj = original as Record<string, unknown>
    const rebuiltObj = (rebuilt !== null && typeof rebuilt === 'object'
      ? (rebuilt as Record<string, unknown>)
      : {}) as Record<string, unknown>
    for (const [key, value] of Object.entries(originObj)) {
      diffs.push(...collectDiff(value, rebuiltObj[key], path ? `${path}.${key}` : key))
    }
    return diffs
  }
  // 叶子值：NaN/undefined 容忍为等价；其余必须严格相等
  const same = original === rebuilt
    || (original === undefined && rebuilt === undefined)
    || (typeof original === 'number' && typeof rebuilt === 'number'
      && Number.isNaN(original) && Number.isNaN(rebuilt))
  if (!same) diffs.push(`${path}: ${JSON.stringify(original)} -> ${JSON.stringify(rebuilt)}`)
  return diffs
}

describe('WP06：真实模板 rawExtras 无损往返（ruleToForm -> formToPayload）', () => {
  it('config.json.template 存在且 audit_types 非空（6 条生产规则）', () => {
    expect(Array.isArray(template.audit_types)).toBe(true)
    expect(template.audit_types.length).toBeGreaterThanOrEqual(6)
    expect(template.audit_types.map((item) => item.code))
      .toContain('progress_vs_nursing')
  })

  it('全部 audit_types 往返后 diff === []（sources/sql/jsonpath/未知扩展键零丢失）', () => {
    for (const cfg of template.audit_types) {
      const { form, rawExtras } = ruleToForm(cfg)
      const rebuilt = formToPayload(form, rawExtras)
      const diffs = collectDiff(cfg, rebuilt)
      expect(diffs, `${cfg.code} 往返丢失: ${diffs.join('; ')}`).toEqual([])
    }
  })

  it('逐条规则关键底层字段逐项一致（sources/query_sql/jsonpath/field_mapping/display）', () => {
    for (const cfg of template.audit_types) {
      const { form, rawExtras } = ruleToForm(cfg)
      const rebuilt = formToPayload(form, rawExtras)
      // sources 全树（含 query_sql / field_mapping / fanout_params / document_kind）
      expect(rebuilt.sources, cfg.code).toEqual(cfg.sources)
      // response：原键（JSONPath 与未知扩展键）逐项一致（重建可新增接管键的空串默认值）
      const originalResponse = (cfg.response || {}) as Record<string, unknown>
      const rebuiltResponse = (rebuilt.response || {}) as Record<string, unknown>
      for (const [key, value] of Object.entries(originalResponse)) {
        expect(rebuiltResponse[key], `${cfg.code}.response.${key}`).toEqual(value)
      }
      // payload 扩展键（builder 之外的 dual_source/source_flags 等全保留）
      const originalPayload = cfg.payload || {}
      const rebuiltPayload = rebuilt.payload || {}
      for (const [key, value] of Object.entries(originalPayload)) {
        if (key === 'builder') {
          expect(rebuiltPayload.builder, `${cfg.code}.payload.builder`).toBe(value)
        } else {
          expect(rebuiltPayload[key], `${cfg.code}.payload.${key}`).toEqual(value)
        }
      }
      // display / group_key / join_rules / dimension_codes 等未接管的整对象
      for (const key of ['display', 'group_key', 'join_rules', 'dimension_codes',
        'default_for_schedule', 'sort_order']) {
        expect(rebuilt[key], `${cfg.code}.${key}`).toEqual(cfg[key])
      }
    }
  })

  it('jhemr_reminder_policy 缺省安全默认（template 原配置无该键，往返后补默认不破坏原值）', () => {
    for (const cfg of template.audit_types) {
      const { form, rawExtras } = ruleToForm(cfg)
      expect('jhemr_reminder_policy' in rawExtras).toBe(false)
      expect(form.reminder_enabled).toBe(false)
      const rebuilt = formToPayload(form, rawExtras)
      expect(rebuilt.jhemr_reminder_policy.enabled).toBe(false)
      expect(rebuilt.jhemr_reminder_policy.delivery_mode).toBe('pull_api')
      expect(rebuilt.jhemr_reminder_policy.severities).toEqual(['high'])
    }
  })

  it('rawExtras 深删除只移除接管键：dify.targets/extra_inputs、payload 扩展键保留', () => {
    const cfg = template.audit_types.find((c) => c.code === 'progress_vs_nursing')
      || template.audit_types[0]
    const { rawExtras } = ruleToForm(cfg)
    // dify 被接管的 6 键删除，其余（targets/extra_inputs/api_key_enc）保留
    for (const key of ['base_url', 'api_key', 'workflow_input_variable', 'workflow_output_key',
      'user_identifier', 'timeout_seconds']) {
      expect(rawExtras.dify?.[key]).toBeUndefined()
    }
    if ((cfg.dify as Record<string, unknown>)?.targets) {
      expect(rawExtras.dify.targets).toEqual((cfg.dify as Record<string, unknown>).targets)
    }
    if ((cfg.dify as Record<string, unknown>)?.extra_inputs) {
      expect(rawExtras.dify.extra_inputs).toEqual((cfg.dify as Record<string, unknown>).extra_inputs)
    }
    // payload：builder 移除，其余扩展键保留
    expect(rawExtras.payload?.builder).toBeUndefined()
    // 顶层标量键移除；sources/display 整对象保留
    expect(rawExtras.sources).toEqual(cfg.sources)
    expect(rawExtras.display).toEqual(cfg.display)
    expect(rawExtras.code).toBeUndefined()
  })

  it('模拟表单修改后保存：修改字段生效且未触碰的高级字段原样透传', () => {
    const cfg = JSON.parse(JSON.stringify(template.audit_types[0])) as Record<string, any>
    const { form, rawExtras } = ruleToForm(cfg)
    // 改名称 + 开启提醒（路线 B）+ 超时
    form.name = '改名后的规则'
    form.reminder_enabled = true
    form.delivery_mode = 'both'
    form.timeout_seconds = 120
    const rebuilt = formToPayload(form, rawExtras)
    expect(rebuilt.name).toBe('改名后的规则')
    expect(rebuilt.dify.timeout_seconds).toBe(120)
    expect(rebuilt.jhemr_reminder_policy).toMatchObject({ enabled: true, delivery_mode: 'both' })
    // 未修改的高级字段原样
    expect(rebuilt.sources).toEqual(cfg.sources)
    expect(rebuilt.display).toEqual(cfg.display)
    const diffs = collectDiff(
      { sources: cfg.sources, display: cfg.display, group_key: cfg.group_key },
      { sources: rebuilt.sources, display: rebuilt.display, group_key: rebuilt.group_key },
    )
    expect(diffs).toEqual([])
  })
})

describe('WP06：三轨页面结构契约', () => {
  it('RuleListPage：第一轨横幅 + 阶段胶囊 + 7 列锁控徽章 + 既有入口保留', () => {
    expect(ruleListSource).toContain('第一轨 · 时效锁定规则')
    expect(ruleListSource).toContain('track-banner--amber')
    for (const chip of ['入院类', '查房类', '手术/麻醉', '抢救/死亡', '会诊/输血', '出院类']) {
      expect(ruleListSource).toContain(chip)
    }
    expect(ruleListSource).toContain('lockBadge')
    expect(ruleListSource).toContain('原生已锁')
    expect(ruleListSource).toContain('影子观察')
    expect(ruleListSource).toContain('预警模式')
    expect(ruleListSource).toContain('临床禁锁(D8)')
    // 既有契约保留
    expect(ruleListSource).toContain('RuleEditorDrawer')
    expect(ruleListSource).toContain('DryRunPanel')
    expect(ruleListSource).toContain('toggleRuleApi')
    expect(ruleListSource).toContain('d8_note')
  })

  it('AuditTypesPage：第二轨横幅 + 生产规则网格 + 草稿折叠 + 移除预检 Tab + wizard 接入', () => {
    expect(pageSource).toContain('第二轨 · AI 内涵质控规则')
    expect(pageSource).toContain('track-banner--blue')
    expect(pageSource).toContain('运行中生产规则')
    expect(pageSource).toContain('草稿与待扩展规则模板')
    expect(pageSource).toContain('AuditTypeWizardDrawer')
    expect(pageSource).toContain('reminderBadge')
    expect(pageSource).toContain('已开启·路线B拉取')
    expect(pageSource).toContain('已预留·未开启')
    // 预检 Tab 已剥离（不再混排），留跳转轻链接
    expect(pageSource).not.toContain('el-tab-pane label="归档前形式预检规则"')
    expect(pageSource).not.toContain('PrcRuleEditDrawer')
    expect(pageSource).toContain('前往归档前形式预检规则')
    expect(pageSource).toContain('/governance/prearchive-rules')
  })

  it('PrearchiveRulesPage：第三轨横幅 + SummaryStrip 四卡 + 三 Tab + 引擎类型/扩展位', () => {
    expect(prearchiveSource).toContain('第三轨 · 归档前形式预检规则')
    expect(prearchiveSource).toContain('track-banner--cyan')
    for (const label of ['生效中形式规则', '无纸化项已规则化(A类)', '规划转AI语义辅助(B类)', '系统推送报告类规则']) {
      expect(prearchiveSource).toContain(label)
    }
    for (const tab of ['无纸化打回形式规则', '系统推送类报告规则', '规则版本与发布管理']) {
      expect(prearchiveSource).toContain(tab)
    }
    expect(prearchiveSource).toContain('engine_mode')
    expect(prearchiveSource).toContain('AI 混合规则')
    expect(prearchiveSource).toContain('AI 辅助混合引擎')
    expect(prearchiveSource).toContain('PrcRuleEditDrawer')
    expect(prearchiveSource).toContain('查看高级规则定义')
  })
})
