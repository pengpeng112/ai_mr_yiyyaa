import { describe, expect, it } from 'vitest'
import { parseAlertRouteQuery, parseAuditRouteQuery, parseFeedbackRouteQuery, parsePatientRouteQuery, positiveLogId, validDate } from '@/utils/route-filters'

describe('route filters', () => {
  it('rejects arrays, invalid dates, enums and unsafe ids', () => {
    expect(validDate('2026-02-30')).toBe('')
    const patient = parsePatientRouteQuery({ source: ['workbench', 'evil'], severity: 'drop', patient_id: 'x'.repeat(200) })
    expect(patient.source).toBe('workbench'); expect(patient.filters).toEqual({ patient_id: 'x'.repeat(120) })
    expect(parseAuditRouteQuery({ log_id: ['7', '8'], alert_level: 'red' }).logId).toBe(7)
    expect(positiveLogId('0')).toBeNull()
    expect(positiveLogId('-1')).toBeNull()
  })
  it('adapts page-specific safe filters and only accepts workbench source', () => {
    const alert = parseAlertRouteQuery({ source: 'workbench', quick: 'failed' })
    expect(alert.quick).toBe('failed'); expect(alert.filters).not.toHaveProperty('source'); expect(alert.filters).not.toHaveProperty('quick'); expect(alert.filters).not.toHaveProperty('log_id')
    expect(parseFeedbackRouteQuery({ source: 'other', status: 'pending' }).source).toBe('')
    expect(parseAuditRouteQuery({ source: 'workbench', log_id: '19', patient_id: 'P1' })).toMatchObject({ logId: 19, source: 'workbench' })
    expect(parseAuditRouteQuery({ source: 'task-progress', audit_type_code: 'progress_vs_nursing' })).toMatchObject({ source: 'task-progress', filters: { audit_type_code: 'progress_vs_nursing' } })
  })
})
