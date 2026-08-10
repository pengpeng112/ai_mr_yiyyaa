import { apiGet } from '../client'
import type { MenuResponse } from '../types'

export function fetchMenuApi() {
  return apiGet<MenuResponse>('/menu')
}
