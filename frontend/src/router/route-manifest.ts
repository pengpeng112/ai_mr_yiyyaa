/**
 * 前端 route manifest — 组件白名单权威。
 * 服务器不得指定任意组件路径；最终菜单 = 服务端授权 menu_id ∩ 本 manifest。
 * 未知 menu ID fail-closed。
 *
 * 2026-11-15 菜单体系重构：group 收敛为 5 大业务分组（与后端 MENU_GROUPS 一致）；
 * title 与后端 MENU_CATALOG 文案一一对应；全部历史 menuId 保留不删
 * （route-manifest.test.ts 契约强校验），路径保持原值避免书签/跳转失效。
 */

import type { Component } from 'vue'
import type { RouteRecordRaw } from 'vue-router'

export type RouteRisk = 'readonly' | 'business-write' | 'system-write'
export type RouteGroup = 'workbench' | 'timeliness' | 'quality' | 'governance' | 'system'

export interface MedAuditRouteMeta {
  menuId: string
  title: string
  group: RouteGroup
  requiresAuth: true
  layout: 'app' | 'standalone'
  risk: RouteRisk
  keepAlive?: boolean
  /** mutation 是否在本轮启用；false 时页面只读展示 */
  mutationsEnabled?: boolean
}

export interface RouteManifestEntry {
  menuId: string
  name: string
  path: string
  title: string
  group: RouteGroup
  risk: RouteRisk
  keepAlive?: boolean
  mutationsEnabled?: boolean
  /** 旧版 static 页签标识（信息性元数据，与后端 MENU_CATALOG.legacy_tab 对应） */
  legacyTab?: string
  component: () => Promise<Component>
}

/** 与后端 MENU_CATALOG.route_name / id 对齐的白名单 */
export const ROUTE_MANIFEST: RouteManifestEntry[] = [
  {
    menuId: 'dashboard',
    name: 'workbench',
    path: 'workbench',
    title: '质控总览',
    group: 'workbench',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/workbench/WorkbenchPage.vue'),
  },
  {
    // WP02（064）：时效统计分析占位（WP-03 填充）
    menuId: 'timeliness-stats',
    name: 'timeliness-stats',
    path: 'timeliness/stats',
    title: '时效统计分析',
    group: 'timeliness',
    risk: 'readonly',
    keepAlive: true,
    legacyTab: 'timeliness-stats',
    component: () => import('@/features/timeliness/TimelinessStatsPage.vue'),
  },
  {
    // 病历时效质控：解锁审批与人工豁免集中处理（2026-11-15 从月报页签独立成页）。
    menuId: 'timeliness-approvals',
    name: 'timeliness-approvals',
    path: 'timeliness/approvals',
    title: '解锁审批与豁免',
    group: 'timeliness',
    risk: 'business-write',
    mutationsEnabled: true,
    legacyTab: 'timeliness-approvals',
    component: () => import('@/features/timeliness/ApprovalCenterPage.vue'),
  },
  {
    menuId: 'patient-qc',
    name: 'quality-patients',
    path: 'quality/patients',
    title: '内涵质控工作台',
    group: 'quality',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/quality/PatientQcPage.vue'),
  },
  {
    menuId: 'audit',
    name: 'quality-records',
    path: 'quality/records',
    title: 'AI 内涵质控记录',
    group: 'quality',
    risk: 'business-write',
    mutationsEnabled: true,
    keepAlive: true,
    component: () => import('@/features/quality/AuditRecordsPage.vue'),
  },
  {
    // T6：病历时效质控（ai_mrzk-timeliness）。事件台账只读。
    menuId: 'timeliness-events',
    name: 'quality-timeliness-events',
    path: 'quality/timeliness-events',
    title: '在院时效台账',
    group: 'timeliness',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/timeliness/EventLedgerPage.vue'),
  },
  {
    menuId: 'timeliness-monthly',
    name: 'quality-timeliness-monthly',
    path: 'quality/timeliness-monthly',
    title: '时效月度考核',
    group: 'timeliness',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/timeliness/MonthlyReportPage.vue'),
  },
  {
    menuId: 'relay-alert-logs',
    name: 'closure-alerts',
    path: 'closure/alerts',
    title: '企微告警记录',
    group: 'quality',
    risk: 'business-write',
    mutationsEnabled: true,
    keepAlive: true,
    component: () => import('@/features/closure/AlertLogsPage.vue'),
  },
  {
    menuId: 'feedback',
    name: 'closure-feedback',
    path: 'closure/feedback',
    title: '临床整改反馈',
    group: 'quality',
    risk: 'business-write',
    mutationsEnabled: true,
    keepAlive: true,
    component: () => import('@/features/closure/FeedbackPage.vue'),
  },
  {
    menuId: 'push',
    name: 'tasks-push',
    path: 'tasks/push',
    title: '手动补推与重查',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/tasks/ManualPushPage.vue'),
  },
  {
    menuId: 'push-progress',
    name: 'tasks-progress',
    path: 'tasks/progress',
    title: '任务执行进度',
    group: 'system',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/tasks/PushProgressPage.vue'),
  },
  {
    menuId: 'scheduler',
    name: 'tasks-scheduler',
    path: 'tasks/scheduler',
    title: '定时调度管理',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/tasks/SchedulerPage.vue'),
  },
  {
    menuId: 'audit-types',
    name: 'governance-audit-types',
    path: 'governance/audit-types',
    title: '内涵与预检规则',
    group: 'governance',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/AuditTypesPage.vue'),
  },
  {
    menuId: 'workbench',
    name: 'governance-workbench',
    path: 'governance/workbench',
    title: '归档前形式核查',
    group: 'quality',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/WorkbenchPage.vue'),
  },
  {
    menuId: 'config',
    name: 'governance-config',
    path: 'governance/config',
    title: '数据源与系统配置',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/ConfigPage.vue'),
  },
  {
    menuId: 'relay',
    name: 'governance-relay',
    path: 'governance/relay',
    title: '企微接收人配置',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/RelayConfigPage.vue'),
  },
  {
    // WP02（064）：归档前形式预检规则占位（WP-06 填充）
    menuId: 'prearchive-rules',
    name: 'governance-prearchive-rules',
    path: 'governance/prearchive-rules',
    title: '归档前形式预检规则',
    group: 'governance',
    risk: 'system-write',
    mutationsEnabled: true,
    legacyTab: 'prearchive-rules',
    component: () => import('@/features/governance/PrearchiveRulesPage.vue'),
  },
  {
    // T6：时效规则可视化配置（保存新版本/启停为写操作）。
    menuId: 'timeliness-rules',
    name: 'governance-timeliness-rules',
    path: 'governance/timeliness-rules',
    title: '时效锁定规则',
    group: 'governance',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/timeliness/RuleListPage.vue'),
  },
  {
    menuId: 'config-runtime',
    name: 'system-runtime',
    path: 'system/runtime',
    title: '运行配置摘要',
    group: 'system',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/system/RuntimeSummaryPage.vue'),
  },
  {
    menuId: 'health',
    name: 'system-health',
    path: 'system/health',
    title: '系统健康状态',
    group: 'system',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/system/HealthPage.vue'),
  },
  {
    menuId: 'access',
    name: 'system-access',
    path: 'system/access',
    title: '用户与角色权限',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/system/AccessPage.vue'),
  },
  {
    menuId: 'debug',
    name: 'system-debug',
    path: 'system/debug',
    title: 'Dify 接口调试',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/system/DebugPage.vue'),
  },
]

/**
 * 侧栏隐藏但保留直达入口的路由（后端 MENU_CATALOG hidden=True 兼容项）：
 * 顶栏「任务」按钮、手动补推页内按钮与历史书签仍可直达，路由守卫放行
 * （manifest 已知 + 登录即可；两页均为只读展示）。
 */
export const DIRECT_ACCESS_MENU_IDS: ReadonlySet<string> = new Set([
  'push-progress',
  'config-runtime',
])

export const MANIFEST_BY_MENU_ID = new Map(ROUTE_MANIFEST.map((e) => [e.menuId, e]))
export const MANIFEST_BY_NAME = new Map(ROUTE_MANIFEST.map((e) => [e.name, e]))

export function getManifestByMenuId(menuId: string): RouteManifestEntry | undefined {
  return MANIFEST_BY_MENU_ID.get(menuId)
}

/** 未知 menu ID 不渲染（fail-closed） */
export function intersectMenuWithManifest<T extends { id: string }>(
  serverMenu: T[],
): { allowed: Array<T & { entry: RouteManifestEntry }>; unknownIds: string[] } {
  const allowed: Array<T & { entry: RouteManifestEntry }> = []
  const unknownIds: string[] = []
  for (const item of serverMenu) {
    const entry = MANIFEST_BY_MENU_ID.get(item.id)
    if (!entry) {
      unknownIds.push(item.id)
      continue
    }
    allowed.push({ ...item, entry })
  }
  return { allowed, unknownIds }
}

export function buildAppRoutes(): RouteRecordRaw[] {
  return ROUTE_MANIFEST.map((entry) => ({
    path: entry.path,
    name: entry.name,
    component: entry.component,
    meta: {
      menuId: entry.menuId,
      title: entry.title,
      group: entry.group,
      requiresAuth: true,
      layout: 'app',
      risk: entry.risk,
      keepAlive: entry.keepAlive ?? false,
      mutationsEnabled: entry.mutationsEnabled ?? entry.risk === 'readonly',
    } satisfies MedAuditRouteMeta,
  }))
}
