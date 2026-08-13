/** 患者质控导出可下发的筛选字段（不含 page/limit/source/log_id 等页面元信息） */
export const PATIENT_QC_EXPORT_FILTER_KEYS = [
  'patient_id',
  'patient_name',
  'admission_no',
  'visit_number',
  'dept',
  'discharge_dept_name',
  'severity',
  'status',
  'date_from',
  'date_to',
  'audit_type_code',
] as const

export type PatientQcExportFilterKey = (typeof PATIENT_QC_EXPORT_FILTER_KEYS)[number]

/**
 * 将当前筛选整理为导出 query 参数：
 * - 不发送空字符串
 * - 不携带 page / limit / source / log_id
 */
export function buildPatientQcExportParams(
  filters: Record<string, unknown>,
): Record<string, string> {
  const params: Record<string, string> = {}
  for (const key of PATIENT_QC_EXPORT_FILTER_KEYS) {
    const raw = filters[key]
    if (raw == null) continue
    const value = String(raw).trim()
    if (!value) continue
    params[key] = value
  }
  return params
}

export function normalizePushLogId(log: Record<string, unknown>): number | null { const value = log.push_log_id ?? log.id; const n = Number(value); return Number.isSafeInteger(n) && n > 0 ? n : null }
export function feedbackInfo(log: Record<string, any>) { const fb = (log.feedback && typeof log.feedback === 'object' ? log.feedback : {}) as Record<string, any>; return { status: String(fb.status || log.feedback_status || 'pending'), feedback_text: String(fb.feedback_text || ''), assigned_to_name: String(fb.assigned_to_name || '') } }
export function canQuickAction(status: string) { return !['rectified', 'closed'].includes(String(status || '').trim().toLowerCase()) }
export function diagnosisValue(patient: Record<string, unknown>) { return String(patient.discharge_main_diagnosis ?? patient.discharge_diagnosis ?? '') }
export function formatEvidence(value: unknown): string { if (value == null || value === '') return ''; if (typeof value === 'string') return value; try { return JSON.stringify(value, null, 2) } catch { return String(value) } }
export function hasEvidence(value: unknown): boolean { if (value == null || value === '') return false; if (Array.isArray(value)) return value.length > 0; if (typeof value === 'object') return Object.keys(value as object).length > 0; return String(value).trim().length > 0 }
