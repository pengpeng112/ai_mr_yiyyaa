import { describe, expect, it } from 'vitest'
import { normalizeApiPath } from '@/api/client'

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
