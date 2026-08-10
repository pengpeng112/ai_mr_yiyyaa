import { describe, expect, it } from 'vitest'
import {
  normalizeSeverity,
  normalizeStatus,
  severityLabel,
  statusLabel,
} from '@/utils/status'

describe('status/severity formatters', () => {
  it('never maps unknown severity to 正常', () => {
    expect(severityLabel(null)).toBe('未知')
    expect(severityLabel('weird')).toBe('未知')
    expect(normalizeSeverity('high')).toBe('high')
    expect(normalizeSeverity('')).toBe('unknown')
  })

  it('handles historical status aliases', () => {
    expect(normalizeStatus('success')).toBe('success')
    expect(normalizeStatus('FAILED')).toBe('failed')
    expect(normalizeStatus('skipped')).toBe('skipped')
    expect(statusLabel(undefined)).toBe('未知')
  })
})
