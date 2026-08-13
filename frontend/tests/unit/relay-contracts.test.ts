import { describe, expect, it } from 'vitest'
import { buildReceiverRulesPayload, dedupeFixedUsers, normalizeReceiverRules, parsePositiveInteger, receiverReasonLabels } from '@/utils/relay-contracts'
describe('relay receiver contracts', () => {
  it('fills exact severity defaults', () => { const rules = normalizeReceiverRules({}); expect(rules.high.max_receivers).toBe(5); expect(rules.medium.nurse_head).toBe(false); expect(rules.low.attending_doctor).toBe(false) })
  it('dedupes fixed users by userid and builds schema', () => { expect(dedupeFixedUsers([{ userid: '1', user_name: 'A' }, { userid: '1', user_name: 'A2' }, { userid: '' }])).toHaveLength(1); const body = buildReceiverRulesPayload({ high: { fixed_users: [{ userid: '1', user_name: 'A' }] } }); expect(body.rules.high.fixed_users[0].userid).toBe('1'); expect(body.rules.low).toHaveProperty('max_receivers', 0) })
  it('validates positive push log ids and maps debug reasons', () => { expect(parsePositiveInteger('12')).toBe(12); expect(parsePositiveInteger('0')).toBeNull(); expect(parsePositiveInteger('abc')).toBeNull(); expect(receiverReasonLabels.max_receivers_exceeded).toContain('最大') })
})
