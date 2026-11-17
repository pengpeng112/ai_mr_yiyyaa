import { describe, expect, it } from 'vitest'
import { apiClient, normalizeApiPath } from '@/api/client'

describe('normalizeApiPath', () => {
  it('keeps canonical relative API paths', () => {
    expect(normalizeApiPath('/logs')).toBe('/logs')
    expect(normalizeApiPath('scheduler/status')).toBe('/scheduler/status')
  })

  it('removes a duplicated API prefix from migrated calls', () => {
    expect(normalizeApiPath('/api/logs')).toBe('/logs')
    expect(normalizeApiPath('/api/patient-qc/relay-alert/summary')).toBe('/patient-qc/relay-alert/summary')
  })
})

// 2026-11-15 P0-4：与 app/security_middleware.py 的 Cookie-CSRF 规则对齐
describe('CSRF header (X-Requested-With)', () => {
  it('sends X-Requested-With: XMLHttpRequest on every request', async () => {
    // axios 1.x 会把自定义默认头归一化到方法级 defaults；
    // 这里用临时 adapter 发一次真实请求，断言最终请求头确实携带该头。
    let captured: Record<string, unknown> = {}
    apiClient.defaults.adapter = async (config) => {
      captured = Object.fromEntries(
        Object.entries((config.headers as unknown as Record<string, unknown>) || {}).map(
          ([k, v]) => [k.toLowerCase(), v],
        ),
      )
      return {
        data: {},
        status: 200,
        statusText: 'OK',
        headers: {},
        config,
      }
    }
    await apiClient.get('/logs')
    expect(captured['x-requested-with']).toBe('XMLHttpRequest')
  })
})
