import { describe, expect, it } from 'vitest'
import { buildDifyTargetPayload, buildRelayConfigBody, omitBlankSecret, parseDeptCandidates, parseNotifyConfig } from '@/utils/config-contracts'

describe('config contracts', () => {
  it('omits empty secrets and preserves schema fields', () => {
    expect(omitBlankSecret({ password: '', db_schema: 'jhemr' }, 'password')).toEqual({ db_schema: 'jhemr' })
    expect(omitBlankSecret({ api_key: '  ' }, 'api_key')).not.toHaveProperty('api_key')
  })
  it('rejects non-object notify config', () => {
    expect(() => parseNotifyConfig('[]')).toThrow('config 必须是 JSON 对象')
    expect(parseNotifyConfig('{"url":"x"}')).toEqual({ url: 'x' })
  })
  it('parses departments/items/array responses', () => {
    expect(parseDeptCandidates({ departments: ['A'] })).toEqual(['A'])
    expect(parseDeptCandidates({ items: ['B'] })).toEqual(['B'])
    expect(parseDeptCandidates(['C'])).toEqual(['C'])
  })
  it('blocks renamed Dify target with omitted existing key', () => {
    expect(() => buildDifyTargetPayload({ name: 'new', base_url: 'x', api_key: '', has_secret: true, timeout_seconds: 90, weight: 1, enabled: true }, 'old')).toThrow('必须输入新密钥')
  })
  it('omits empty relay secret and base url', () => {
    const body = buildRelayConfigBody({ enabled: false, base_url: ' ', endpoint: '/x', secret_key: '', timeout_seconds: 10, severity_levels: ['high'], source: 'x', max_retry: 3, retry_backoff_seconds: 5, alert_dept_filter: [] })
    expect(body).not.toHaveProperty('base_url')
    expect(body).not.toHaveProperty('secret_key')
  })
})
