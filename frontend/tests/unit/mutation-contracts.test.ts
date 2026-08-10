import { describe, expect, it } from 'vitest'
import {
  assertNoSecretEchoFields,
  buildDifySaveBody,
  buildManualPushBody,
  buildRelayPartialUpdateBody,
  buildSchedulerTriggerParams,
} from '@/utils/mutation-contracts'

describe('mutation contracts', () => {
  it('relay: omits empty secret and empty base_url', () => {
    const body = buildRelayPartialUpdateBody({
      enabled: true,
      base_url: '',
      secret_key: '   ',
      endpoint: '/qc-record-alert',
      alert_dept_filter: '听觉植入科',
      severity_levels: 'high',
    })
    expect(body).not.toHaveProperty('secret_key')
    expect(body).not.toHaveProperty('base_url')
    expect(body.enabled).toBe(true)
    expect(body.alert_dept_filter).toEqual(['听觉植入科'])
    expect(body.severity_levels).toEqual(['high'])
  })

  it('relay: includes secret and base_url only when non-empty', () => {
    const body = buildRelayPartialUpdateBody({
      enabled: false,
      base_url: 'http://example.invalid',
      secret_key: 'new-secret',
    })
    expect(body.base_url).toBe('http://example.invalid')
    expect(body.secret_key).toBe('new-secret')
  })

  it('dify: preserves empty api_key by omission', () => {
    const body = buildDifySaveBody({
      base_url: 'http://dify.local/v1',
      workflow_input_variable: 'mr_txt',
      api_key: '',
    })
    expect(body.base_url).toBe('http://dify.local/v1')
    expect(body.workflow_input_variable).toBe('mr_txt')
    expect(body).not.toHaveProperty('api_key')
  })

  it('scheduler trigger uses audit_run_mode query, not mode body', () => {
    const params = buildSchedulerTriggerParams({
      audit_run_mode: 'discharge_final',
      audit_type_codes: ['progress_vs_nursing', 'syssvsscbc'],
    })
    expect(params.audit_run_mode).toBe('discharge_final')
    expect(params.audit_type_codes).toBe('progress_vs_nursing,syssvsscbc')
    expect(params).not.toHaveProperty('mode')
  })

  it('manual push maps replace_current and dry_run', () => {
    const dry = buildManualPushBody({
      query_date: '2026-08-01',
      dry_run: true,
      async_mode: true,
      replace_current: false,
      skip_already_succeeded: true,
    })
    expect(dry.dry_run).toBe(true)
    expect(dry.async_mode).toBe(false)
    expect(dry.existing_result_policy).toBe('skip_success')
    expect(dry.skip_already_succeeded).toBe(true)

    const replace = buildManualPushBody({
      query_date: '2026-08-01',
      dry_run: false,
      async_mode: true,
      replace_current: true,
      skip_already_succeeded: true,
    })
    expect(replace.existing_result_policy).toBe('replace_current')
    expect(replace.alert_policy).toBe('suppress')
    expect(replace.skip_already_succeeded).toBe(false)
    expect(replace.async_mode).toBe(true)
  })

  it('rejects accidental secret echo field names', () => {
    expect(assertNoSecretEchoFields({ api_key: 'x' })).toEqual([])
    expect(assertNoSecretEchoFields({ api_key_enc: 'cipher' })).toEqual(['api_key_enc'])
  })
})
