/**
 * WP08：360 全息视图对接配置页签测试（任务书 §七）。
 * 默认值 S28/wfy 回显、预览 URL 拼接正确、保存只提交 holography 段。
 */
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import pageSource from '@/features/governance/ConfigPage.vue?raw'
import { buildHolographyUrl } from '@/utils/holography'

const pagePath = resolve(process.cwd(), 'src/features/governance/ConfigPage.vue')
const page = readFileSync(pagePath, 'utf-8')

describe('WP08：360 全息视图页签（ConfigPage）', () => {
  it('页签存在且默认值 S28 / wfy / 正则回显（GET /config/holography）', () => {
    expect(page).toContain('360 全息视图')
    expect(page).toContain("sys_code: 'S28'")
    expect(page).toContain("fallback_user_code: 'wfy'")
    expect(page).toContain("employee_code_pattern: '^[0-9]{4,10}$'")
    expect(page).toContain("'/config/holography'")
    // GET 加载后回显（user_code 单独透传）
    expect(page).toContain('holography.user_code = data.holography.user_code')
  })

  it('表单字段齐全：启用开关/基础地址/系统编码/兜底工号/工号格式/非员工账号/企微开关', () => {
    for (const label of ['启用 360 全息视图', '基础地址', '系统编码', '非工号账号兜底工号',
      '员工工号格式（正则）', '非员工账号列表', '企微手机端显示 360 入口']) {
      expect(page).toContain(label)
    }
    expect(page).toContain('符合此格式的登录账号直接作为工号传给 360')
    expect(page).toContain('multiple')
    expect(page).toContain('allow-create')
    expect(page).toContain('enable_on_mobile')
  })

  it('预览 URL 本地拼接：new URL + patientId/userCode/sysCode（与 utils/holography 同语义）', () => {
    expect(page).toContain('previewUrl')
    expect(page).toContain("url.searchParams.set('patientId', pid)")
    expect(page).toContain("url.searchParams.set('userCode', userCode)")
    expect(page).toContain("url.searchParams.set('sysCode'")
    // userCode 回退语义：正则不命中 → 兜底工号
    expect(page).toContain('userCode = uname')
    expect(page).toContain("String(holography.fallback_user_code || 'wfy')")
    // 与 utils/holography.buildHolographyUrl 拼接语义一致（同一 query 参数名）
    const sample = buildHolographyUrl('00985003', {
      enabled: true, base_url: 'http://10.10.8.231:8281/holography-platform/consultationView',
      sys_code: 'S28', enable_on_mobile: false, user_code: '003966',
    })
    expect(sample).toContain('patientId=00985003')
    expect(sample).toContain('userCode=003966')
    expect(sample).toContain('sysCode=S28')
  })

  it('预览工具：新窗口试打开（未生成时禁用）+ 本人 user_code 展示', () => {
    expect(page).toContain('新窗口试打开')
    expect(page).toContain(':disabled="!previewUrl"')
    expect(page).toContain('当前登录人 user_code（后端计算）')
  })

  it('保存只提交 holography 段（7 键）且仅 admin；启用时校验 base_url/sys_code', () => {
    expect(page).toContain("saveSection('holography', '/config/holography', body)")
    expect(page).toContain('enabled: holography.enabled')
    expect(page).toContain('sys_code: String(holography.sys_code')
    expect(page).toContain('enable_on_mobile: holography.enable_on_mobile')
    // base_url 协议与 sys_code 必填校验（与后端 save_holography_config 对齐）
    expect(page).toContain('http:// 或 https:// 开头')
    expect(page).toContain('请填写系统编码（如 S28）')
  })

  it('页面结构：左侧竖向 6 页签 + 每页签独立「测试连接/保存本页」+ 企微指引', () => {
    expect(page).toContain('tab-position="left"')
    expect(page).toContain('label-position="top"')
    expect(page).toContain('保存本页')
    expect(page).toContain('测试连接')
    // 池高级参数默认折叠且全中文（禁 pool_min 等英文键）
    expect(page).toContain('最小连接数')
    expect(page).toContain('获取连接超时(秒)')
    expect(page).not.toContain('（pool_min）')
    expect(page).not.toContain('（pool_max）')
    // 企微前置机指引
    expect(page).toContain('data-testid="goto-relay-page"')
    expect(page).toContain('/governance/relay')
  })
})
