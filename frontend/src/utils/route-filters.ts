type QueryValue = string | string[] | undefined
export type RouteQuery = Record<string, QueryValue | unknown>

const MAX_TEXT = 120
const first = (value: unknown): string => {
  const raw = Array.isArray(value) ? value[0] : value
  return typeof raw === 'string' ? raw.trim().slice(0, MAX_TEXT) : ''
}

export function validDate(value: unknown): string {
  const text = first(value)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return ''
  const date = new Date(`${text}T00:00:00Z`)
  return Number.isNaN(date.getTime()) || date.toISOString().slice(0, 10) !== text ? '' : text
}

export function positiveLogId(value: unknown): number | null {
  const text = first(value)
  if (!/^\d+$/.test(text)) return null
  const id = Number(text)
  return Number.isSafeInteger(id) && id > 0 ? id : null
}

function source(value: unknown): 'workbench' | 'task-progress' | '' {
  const valueText = first(value)
  return valueText === 'workbench' || valueText === 'task-progress' ? valueText : ''
}

function common(query: RouteQuery) {
  const result: Record<string, string> = {}
  const sourceValue = source(query.source)
  const from = validDate(query.date_from); const to = validDate(query.date_to)
  if (from) result.date_from = from
  if (to) result.date_to = to
  return { source: sourceValue, filters: result }
}

export function parsePatientRouteQuery(query: RouteQuery) {
  const commonQuery = common(query); const filters = commonQuery.filters
  for (const key of ['patient_id', 'patient_name', 'admission_no', 'visit_number', 'dept', 'discharge_dept_name']) {
    const value = first(query[key]); if (value) filters[key] = value
  }
  const severity = first(query.severity); if (['high', 'medium', 'low'].includes(severity)) filters.severity = severity
  const status = first(query.status); if (['pending', 'rectified', 'closed'].includes(status)) filters.status = status
  return { source: commonQuery.source, filters }
}

export function parseAuditRouteQuery(query: RouteQuery) {
  const commonQuery = common(query); const filters = commonQuery.filters
  const severity = first(query.severity); if (['high', 'medium', 'low'].includes(severity)) filters.severity = severity
  const status = first(query.status); if (['success', 'failed', 'skipped', 'pending'].includes(status)) filters.status = status
  const alertLevel = first(query.alert_level); if (['red', 'yellow', 'blue', 'gray'].includes(alertLevel)) filters.alert_level = alertLevel
  const patientId = first(query.patient_id); if (patientId) filters.patient_id = patientId
  const auditType = first(query.audit_type_code); if (/^[A-Za-z0-9_-]{1,64}$/.test(auditType)) filters.audit_type_code = auditType
  return { source: commonQuery.source, filters, logId: positiveLogId(query.log_id) }
}

export function parseAlertRouteQuery(query: RouteQuery) {
  const commonQuery = common(query); const filters = commonQuery.filters
  const quickValue = first(query.quick); const quick = ['failed', 'pending', 'unviewed', 'viewed'].includes(quickValue) ? quickValue : ''
  const severity = first(query.severity); if (['high', 'medium'].includes(severity)) filters.severity = severity
  const status = first(query.status); if (['success', 'failed', 'pending'].includes(status)) filters.status = status
  const viewed = first(query.viewed_flag); if (['0', '1'].includes(viewed)) filters.viewed_flag = viewed
  const dept = first(query.dept); if (dept) filters.dept = dept
  return { source: commonQuery.source, filters, quick }
}

export function parseFeedbackRouteQuery(query: RouteQuery) {
  const commonQuery = common(query); const filters = commonQuery.filters
  const status = first(query.status); if (['pending', 'acknowledged', 'rectified', 'closed'].includes(status)) filters.status = status
  const severity = first(query.severity); if (['high', 'medium', 'low'].includes(severity)) filters.severity = severity
  const keyword = first(query.keyword); if (keyword) filters.keyword = keyword
  return { source: commonQuery.source, filters }
}
