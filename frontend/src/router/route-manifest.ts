/**
 * 前端 route manifest — 组件白名单权威。
 * 服务器不得指定任意组件路径；最终菜单 = 服务端授权 menu_id ∩ 本 manifest。
 * 未知 menu ID fail-closed。
 */

import type { Component } from 'vue'
import type { RouteRecordRaw } from 'vue-router'

export type RouteRisk = 'readonly' | 'business-write' | 'system-write'
export type RouteGroup =
  | 'workbench'
  | 'quality'
  | 'closure'
  | 'tasks'
  | 'governance'
  | 'system'

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
  component: () => Promise<Component>
}

/** 与后端 MENU_CATALOG.route_name / id 对齐的白名单 */
export const ROUTE_MANIFEST: RouteManifestEntry[] = [
  {
    menuId: 'dashboard',
    name: 'workbench',
    path: 'workbench',
    title: '工作台',
    group: 'workbench',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/workbench/WorkbenchPage.vue'),
  },
  {
    menuId: 'patient-qc',
    name: 'quality-patients',
    path: 'quality/patients',
    title: '患者质控',
    group: 'quality',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/quality/PatientQcPage.vue'),
  },
  {
    menuId: 'audit',
    name: 'quality-records',
    path: 'quality/records',
    title: '质控记录',
    group: 'quality',
    risk: 'business-write',
    mutationsEnabled: true,
    keepAlive: true,
    component: () => import('@/features/quality/AuditRecordsPage.vue'),
  },
  {
    menuId: 'relay-alert-logs',
    name: 'closure-alerts',
    path: 'closure/alerts',
    title: '告警记录',
    group: 'closure',
    risk: 'business-write',
    mutationsEnabled: true,
    keepAlive: true,
    component: () => import('@/features/closure/AlertLogsPage.vue'),
  },
  {
    menuId: 'feedback',
    name: 'closure-feedback',
    path: 'closure/feedback',
    title: '整改反馈',
    group: 'closure',
    risk: 'business-write',
    mutationsEnabled: true,
    keepAlive: true,
    component: () => import('@/features/closure/FeedbackPage.vue'),
  },
  {
    menuId: 'push',
    name: 'tasks-push',
    path: 'tasks/push',
    title: '手动推送',
    group: 'tasks',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/tasks/ManualPushPage.vue'),
  },
  {
    menuId: 'push-progress',
    name: 'tasks-progress',
    path: 'tasks/progress',
    title: '任务进度',
    group: 'tasks',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/tasks/PushProgressPage.vue'),
  },
  {
    menuId: 'scheduler',
    name: 'tasks-scheduler',
    path: 'tasks/scheduler',
    title: '定时任务',
    group: 'tasks',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/tasks/SchedulerPage.vue'),
  },
  {
    menuId: 'audit-types',
    name: 'governance-audit-types',
    path: 'governance/audit-types',
    title: '质控类型',
    group: 'governance',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/AuditTypesPage.vue'),
  },
  {
    menuId: 'config',
    name: 'governance-config',
    path: 'governance/config',
    title: '系统配置',
    group: 'governance',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/ConfigPage.vue'),
  },
  {
    menuId: 'relay',
    name: 'governance-relay',
    path: 'governance/relay',
    title: '告警推送配置',
    group: 'governance',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/governance/RelayConfigPage.vue'),
  },
  {
    menuId: 'config-runtime',
    name: 'system-runtime',
    path: 'system/runtime',
    title: '运行总览',
    group: 'system',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/system/RuntimeSummaryPage.vue'),
  },
  {
    menuId: 'health',
    name: 'system-health',
    path: 'system/health',
    title: '系统健康',
    group: 'system',
    risk: 'readonly',
    keepAlive: true,
    component: () => import('@/features/system/HealthPage.vue'),
  },
  {
    menuId: 'access',
    name: 'system-access',
    path: 'system/access',
    title: '用户与权限',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/system/AccessPage.vue'),
  },
  {
    menuId: 'debug',
    name: 'system-debug',
    path: 'system/debug',
    title: 'Dify 调试',
    group: 'system',
    risk: 'system-write',
    mutationsEnabled: true,
    component: () => import('@/features/system/DebugPage.vue'),
  },
]

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
