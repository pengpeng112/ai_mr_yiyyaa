import { describe, expect, it } from 'vitest'
import { applySourceCardsToConfig, deepClone, patchVisibleAuditFields, responsePathError, sourceCardsFromConfig, validateAuditTypeJson } from '@/utils/audit-types'

describe('audit type editor contracts', () => {
  it('round trips source cards without dropping future fields', () => {
    const config = { sources: { progress: { backend: 'postgresql', data_source: 'default', document_kind: 'progress', load_strategy: 'fanout', fanout_params: { patient_key: '{patient_id}' }, future_flag: true } } }
    const cards = sourceCardsFromConfig(config.sources)
    const result = applySourceCardsToConfig(config, cards)
    expect(result.sources).toEqual(config.sources)
  })
  it('validates response paths and rejects payload mr_txt', () => {
    expect(responsePathError({ conclusion_path: 'result' })).toContain('$')
    expect(validateAuditTypeJson({ sources: { a: {} }, payload: { mr_txt: 'bad' } })).toContain('mr_txt')
    expect(validateAuditTypeJson({ sources: { a: {} }, response: { result_path: '$.result' } })).toBe('')
  })
  it('patches visible fields without dropping unknown fields', () => {
    const result = patchVisibleAuditFields({ future: 1, payload: { builder: 'x', future_builder: true } }, { name: '新名称' })
    expect(result.future).toBe(1)
    expect((result.payload as Record<string, unknown>).future_builder).toBe(true)
  })
  it('applies payload, dify and response changes while retaining nested unknowns', () => {
    const result = patchVisibleAuditFields({ payload: { future: 1 }, dify: { future: 2 }, response: { future: 3 } }, { payload: { builder: 'new' }, dify: { base_url: 'x' }, response: { result_path: '$.result' } })
    expect(result.payload).toMatchObject({ builder: 'new', future: 1 })
    expect(result.dify).toMatchObject({ base_url: 'x', future: 2 })
    expect(result.response).toMatchObject({ result_path: '$.result', future: 3 })
  })
  it('rejects malformed fanout JSON without changing source config', () => {
    const original = { sources: { a: { fanout_params: { keep: true } } } }
    expect(() => applySourceCardsToConfig(original, [{ name: 'a', source: { fanout_params_json: '{bad' } }])).toThrow('来源 a')
    expect(original.sources.a.fanout_params).toEqual({ keep: true })
  })
  it('deep clones nested source state', () => {
    const source = { fanout: { workers: 2 }, mapping: [{ key: 'a' }] }
    const clone = deepClone(source)
    clone.fanout.workers = 5
    clone.mapping[0].key = 'b'
    expect(source).toEqual({ fanout: { workers: 2 }, mapping: [{ key: 'a' }] })
  })
})
