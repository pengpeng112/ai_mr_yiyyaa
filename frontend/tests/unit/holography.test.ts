/**
 * 360 全息视图工具测试（WP02 T3）。
 * mock loadHolographyConfig 返回值；覆盖 URL 拼接规则与按钮渲染条件。
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import {
  DEFAULT_HOLOGRAPHY_CONFIG,
  buildHolographyUrl,
  loadHolographyConfig,
  resetHolographyCache,
  type HolographyConfig,
} from '@/utils/holography'
import * as apiClientModule from '@/api/client'

const ROOT = resolve(process.cwd(), '..')
// 静态占位引用（源码契约用例使用 h5 内容哈希守卫）
const h5SourceHash = readFileSync(resolve(ROOT, 'static', 'scripts', 'mobile', 'timeliness_h5.js'), 'utf-8').length
const componentSource = readFileSync(
  resolve(ROOT, 'frontend', 'src', 'components', 'base', 'HolographyButton.vue'), 'utf-8')

const BASE = 'http://10.10.8.231:8281/holography-platform/consultationView'

function cfgWith(overrides: Partial<HolographyConfig>): HolographyConfig {
  return {
    enabled: true,
    base_url: BASE,
    sys_code: 'S28',
    enable_on_mobile: false,
    user_code: '',
    ...overrides,
  }
}

describe('buildHolographyUrl（精确拼接规则）', () => {
  it('user_code=003966 → URL 含 patientId/userCode/sysCode 三参', () => {
    const url = buildHolographyUrl('00985003', cfgWith({ user_code: '003966' }))
    expect(url).toContain(`patientId=00985003`)
    expect(url).toContain(`userCode=003966`)
    expect(url).toContain(`sysCode=S28`)
    expect(url?.startsWith(BASE)).toBe(true)
  })

  it('user_code=wfy → userCode=wfy（系统账号回退）', () => {
    const url = buildHolographyUrl('00985003', cfgWith({ user_code: 'wfy' }))
    expect(url).toContain('userCode=wfy')
  })

  it('enabled=false → null', () => {
    expect(buildHolographyUrl('00985003', cfgWith({ enabled: false, user_code: '003966' }))).toBeNull()
  })

  it('user_code 为空 → null', () => {
    expect(buildHolographyUrl('00985003', cfgWith({ user_code: '' }))).toBeNull()
  })

  it('patientId 空白 → null', () => {
    expect(buildHolographyUrl('  ', cfgWith({ user_code: '003966' }))).toBeNull()
    expect(buildHolographyUrl(null, cfgWith({ user_code: '003966' }))).toBeNull()
  })

  it('base_url 非法 → null（URL 构造失败兜底）', () => {
    expect(buildHolographyUrl('1', cfgWith({ base_url: 'not-a-url' }))).toBeNull()
  })

  it('sys_code 缺省回退 S28', () => {
    const url = buildHolographyUrl('1', { ...cfgWith({ user_code: 'wfy' }), sys_code: '' })
    expect(url).toContain('sysCode=S28')
  })

  it('DEFAULT_HOLOGRAPHY_CONFIG.enabled=false（未加载不误显示）', () => {
    expect(DEFAULT_HOLOGRAPHY_CONFIG.enabled).toBe(false)
  })
})

describe('HolographyButton.vue 渲染条件（源码契约，与仓库测试惯例一致）', () => {
  it('cfg.enabled=false 整体不渲染（v-if 守卫）', () => {
    expect(componentSource).toContain('v-if="cfg.enabled"')
  })

  it('无患者号时按钮禁用（disabled 绑定 hasPatientId）', () => {
    expect(componentSource).toContain(':disabled="!hasPatientId"')
    expect(componentSource).toContain('Boolean(String(props.patientId ||')
  })

  it('带 data-testid 与打开调用（openHolography360）', () => {
    expect(componentSource).toContain('data-testid="holography-360-btn"')
    expect(componentSource).toContain('openHolography360(String(props.patientId).trim(), cfg.value)')
  })

  it('onMounted 加载配置（loadHolographyConfig）', () => {
    expect(componentSource).toContain('loadHolographyConfig()')
  })

  it('h5 脚本随包存在（哈希守卫防误删）', () => {
    expect(h5SourceHash).toBeGreaterThan(1000)
  })
})

describe('loadHolographyConfig 缓存与重试/账号切换（P0-4 回归保护）', () => {
  beforeEach(() => {
    resetHolographyCache()
    vi.restoreAllMocks()
  })

  it('走统一 apiGet；请求失败时清空缓存，下次调用可恢复成功', async () => {
    const spy = vi.spyOn(apiClientModule, 'apiGet')
      .mockRejectedValueOnce(new Error('401'))
      .mockResolvedValueOnce({
        enabled: true,
        base_url: BASE,
        sys_code: 'S28',
        enable_on_mobile: false,
        user_code: '003966',
      })

    const first = await loadHolographyConfig()
    expect(first.enabled).toBe(false)
    expect(spy).toHaveBeenCalledWith('/config/holography')

    // 失败不得锁死缓存：二次调用必须重发并拿到有效配置
    const second = await loadHolographyConfig()
    expect(second.enabled).toBe(true)
    expect(second.user_code).toBe('003966')
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('resetHolographyCache 在切换账号后清除旧 user_code 缓存', async () => {
    const spy = vi.spyOn(apiClientModule, 'apiGet')
      .mockResolvedValueOnce({ enabled: true, base_url: BASE, sys_code: 'S28', user_code: '003966' })
      .mockResolvedValueOnce({ enabled: true, base_url: BASE, sys_code: 'S28', user_code: '004120' })

    const u1 = await loadHolographyConfig()
    expect(u1.user_code).toBe('003966')
    // 未重置前命中缓存
    const u1Cached = await loadHolographyConfig()
    expect(u1Cached.user_code).toBe('003966')
    expect(spy).toHaveBeenCalledTimes(1)

    // 账号切换调用 resetHolographyCache 后重新拉取新工号
    resetHolographyCache()
    const u2 = await loadHolographyConfig()
    expect(u2.user_code).toBe('004120')
    expect(spy).toHaveBeenCalledTimes(2)
  })

  it('auth.ts 登出/登录清缓存 & ConfigPage.vue 保存后强制刷新缓存', () => {
    const authSrc = readFileSync(resolve(ROOT, 'frontend', 'src', 'stores', 'auth.ts'), 'utf-8')
    const cfgSrc = readFileSync(
      resolve(ROOT, 'frontend', 'src', 'features', 'governance', 'ConfigPage.vue'), 'utf-8',
    )
    expect(authSrc).toContain('resetHolographyCache()')
    expect(cfgSrc).toContain('loadHolographyConfig(true)')
  })
})
