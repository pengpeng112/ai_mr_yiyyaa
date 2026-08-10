/** 关键 DTO（手工维护；禁止构建时拉取生产 OpenAPI） */

export interface UserInfo {
  id: number
  username: string
  full_name?: string | null
  email?: string | null
  role?: string | null
  role_id?: number | null
  dept_id?: number | null
  dept_name?: string | null
  is_active?: boolean
}

export interface LoginResponse {
  access_token: string
  token_type?: string
  user?: UserInfo
}

export interface MenuItem {
  id: string
  label: string
  icon?: string
  path?: string
  group?: string
  order?: number
  route_name?: string
  target?: {
    activeMenu?: string
    tab?: string
  }
  hidden?: boolean
  dev_only?: boolean
}

export interface MenuGroup {
  id: string
  label: string
  icon?: string
  order?: number
}

export interface MenuResponse {
  schema_version?: number
  role?: string | null
  menu: MenuItem[]
  groups: MenuGroup[]
  default_home?: string | null
}

export interface HealthComponent {
  name?: string
  status?: string
  latency_ms?: number | null
  message?: string | null
  detail?: string | null
}

export interface HealthResponse {
  status?: string
  components?: Record<string, HealthComponent | string>
  timestamp?: string
  version?: string
}

export interface StatsSummary {
  total?: number
  success?: number
  failed?: number
  skipped?: number
  inconsistency?: number
  high_risk?: number
  [key: string]: unknown
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page?: number
  limit?: number
  pages?: number
}

export interface PushLogListItem {
  id: number
  patient_id?: string | null
  visit_number?: string | number | null
  dept?: string | null
  status?: string | null
  severity?: string | null
  audit_type_code?: string | null
  audit_run_mode?: string | null
  reviewed_flag?: boolean | number | null
  manual_override?: boolean | number | null
  skip_reason?: string | null
  pushed_flag?: boolean | number | null
  created_at?: string | null
  parse_success?: boolean | number | null
  is_current?: boolean | number | null
  superseded_by?: number | null
  source_record_key?: string | null
  [key: string]: unknown
}

export interface MessageResponse {
  message?: string
  success?: boolean
  [key: string]: unknown
}

export interface PushProgress {
  task_id?: string
  status?: string
  total?: number
  done?: number
  success?: number
  failed?: number
  skipped?: number
  message?: string
  percent?: number
  [key: string]: unknown
}

export interface RuntimeSummary {
  run_modes?: unknown
  schedulers?: unknown
  dept_scopes?: unknown
  audit_types?: unknown
  warnings?: unknown[]
  meta?: unknown
  [key: string]: unknown
}
