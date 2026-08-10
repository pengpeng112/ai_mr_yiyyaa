import { apiGet } from '../client'
import type { HealthResponse } from '../types'

export function fetchHealthApi(forceRefresh = false) {
  return apiGet<HealthResponse>('/health', {
    params: forceRefresh ? { force_refresh: true } : undefined,
  })
}

export function fetchHealthReadyApi() {
  return apiGet<HealthResponse>('/health/ready')
}

export function fetchHealthComponentApi(name: 'oracle' | 'postgresql' | 'dify') {
  return apiGet(`/health/${name}`)
}
