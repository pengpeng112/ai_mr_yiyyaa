import { describe, expect, it } from 'vitest'
import {
  buildPatientQcExportParams,
  canQuickAction,
  diagnosisValue,
  feedbackInfo,
  formatEvidence,
  hasEvidence,
  normalizePushLogId,
} from '@/utils/patient-qc-contracts'

describe('patient qc contracts', () => {
  it('normalizes valid log ids with fallback', () => {
    expect(normalizePushLogId({ push_log_id: 4, id: 9 })).toBe(4)
    expect(normalizePushLogId({ id: '3' })).toBe(3)
    expect(normalizePushLogId({ id: 0 })).toBeNull()
  })
  it('reads feedback and gates closed actions', () => {
    expect(feedbackInfo({ feedback: { status: 'closed', feedback_text: 'x' } }).status).toBe('closed')
    expect(canQuickAction(' CLOSED ')).toBe(false)
    expect(canQuickAction('pending')).toBe(true)
  })
  it('uses diagnosis fallback and safely formats evidence', () => {
    expect(diagnosisValue({ discharge_main_diagnosis: '主诊断' })).toBe('主诊断')
    expect(diagnosisValue({ discharge_diagnosis: '旧字段' })).toBe('旧字段')
    expect(formatEvidence([{ text: 'e' }])).toContain('text')
  })
  it('detects only non-empty evidence', () => {
    expect(hasEvidence('')).toBe(false)
    expect(hasEvidence([])).toBe(false)
    expect(hasEvidence({})).toBe(false)
    expect(hasEvidence('e')).toBe(true)
    expect(hasEvidence([{ text: 'e' }])).toBe(true)
  })
  it('builds export params from filters without page/limit/source/empty', () => {
    const params = buildPatientQcExportParams({
      patient_id: ' P1 ',
      patient_name: '',
      admission_no: 'A1',
      visit_number: '1',
      dept: '内科',
      discharge_dept_name: '  ',
      severity: 'high',
      status: 'pending',
      date_from: '2026-08-01',
      date_to: '2026-08-10',
      audit_type_code: 'progress_vs_nursing',
      page: 2,
      limit: 20,
      source: 'workbench',
      log_id: 88,
    })
    expect(params).toEqual({
      patient_id: 'P1',
      admission_no: 'A1',
      visit_number: '1',
      dept: '内科',
      severity: 'high',
      status: 'pending',
      date_from: '2026-08-01',
      date_to: '2026-08-10',
      audit_type_code: 'progress_vs_nursing',
    })
    expect(params).not.toHaveProperty('page')
    expect(params).not.toHaveProperty('limit')
    expect(params).not.toHaveProperty('source')
    expect(params).not.toHaveProperty('log_id')
    expect(params).not.toHaveProperty('patient_name')
  })
})
