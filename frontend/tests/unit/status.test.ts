import { describe, expect, it } from 'vitest'
import {
  normalizeSeverity,
  normalizeStatus,
  severityLabel,
  statusLabel,
} from '@/utils/status'
import { canEditPushMarker } from '@/utils/rbac'

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

  it('localizes feedback closure statuses and keeps marker editing admin-only', () => {
    expect(statusLabel('acknowledged')).toBe('已确认')
    expect(statusLabel('rectified')).toBe('已整改')
    expect(statusLabel('closed')).toBe('已关闭')
    expect(canEditPushMarker('admin')).toBe(true)
    expect(canEditPushMarker('auditor')).toBe(false)
    expect(canEditPushMarker('ADMIN')).toBe(true)
  })
})
