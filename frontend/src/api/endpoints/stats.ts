import { apiGet } from '../client'
import type { StatsSummary } from '../types'

export function fetchStatsSummary() {
  return apiGet<StatsSummary>('/stats/summary')
}

export function fetchStatsToday() {
  return apiGet('/stats/today')
}

export function fetchStatsDaily(days = 30) {
  return apiGet('/stats/daily', { params: { days } })
}

export function fetchStatsSeverity() {
  return apiGet('/stats/severity')
}

export function fetchStatsDept() {
  return apiGet('/stats/dept')
}

export function fetchStatsDimensions() {
  return apiGet('/stats/dimensions')
}

export function fetchAnomalyTop(groupBy: 'dept' | 'patient' = 'dept') {
  return apiGet('/stats/anomaly-top', { params: { group_by: groupBy } })
}
