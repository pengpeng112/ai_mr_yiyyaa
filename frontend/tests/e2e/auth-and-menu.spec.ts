import { expect, test, type Page, type Route } from '@playwright/test'

const ROLE_MENUS: Record<string, string[]> = {
  admin: [
    'dashboard',
    'patient-qc',
    'audit',
    'relay-alert-logs',
    'feedback',
    'push',
    'push-progress',
    'scheduler',
    'audit-types',
    'config',
    'relay',
    'config-runtime',
    'health',
    'access',
    'debug',
  ],
  dept_manager: ['dashboard', 'patient-qc', 'audit', 'feedback', 'scheduler', 'health'],
  auditor: ['dashboard', 'patient-qc', 'audit', 'feedback', 'health'],
  clinician: ['dashboard', 'audit', 'feedback'],
}

const GROUPS = [
  { id: 'workbench', label: '工作台', order: 10 },
  { id: 'quality', label: '质控中心', order: 20 },
  { id: 'closure', label: '闭环管理', order: 30 },
  { id: 'tasks', label: '任务中心', order: 40 },
  { id: 'governance', label: '规则与配置', order: 50 },
  { id: 'system', label: '系统管理', order: 60 },
]

const CATALOG: Record<string, { id: string; label: string; group: string; order: number; route_name: string }> = {
  dashboard: { id: 'dashboard', label: '工作台', group: 'workbench', order: 10, route_name: 'workbench' },
  'patient-qc': { id: 'patient-qc', label: '患者质控', group: 'quality', order: 10, route_name: 'quality-patients' },
  audit: { id: 'audit', label: '质控记录', group: 'quality', order: 20, route_name: 'quality-records' },
  'relay-alert-logs': { id: 'relay-alert-logs', label: '告警记录', group: 'closure', order: 10, route_name: 'closure-alerts' },
  feedback: { id: 'feedback', label: '整改反馈', group: 'closure', order: 20, route_name: 'closure-feedback' },
  push: { id: 'push', label: '手动推送', group: 'tasks', order: 10, route_name: 'tasks-push' },
  'push-progress': { id: 'push-progress', label: '任务进度', group: 'tasks', order: 20, route_name: 'tasks-progress' },
  scheduler: { id: 'scheduler', label: '定时任务', group: 'tasks', order: 30, route_name: 'tasks-scheduler' },
  'audit-types': { id: 'audit-types', label: '质控类型', group: 'governance', order: 10, route_name: 'governance-audit-types' },
  config: { id: 'config', label: '系统配置', group: 'governance', order: 20, route_name: 'governance-config' },
  relay: { id: 'relay', label: '告警推送配置', group: 'governance', order: 30, route_name: 'governance-relay' },
  'config-runtime': { id: 'config-runtime', label: '运行总览', group: 'system', order: 10, route_name: 'system-runtime' },
  health: { id: 'health', label: '系统健康', group: 'system', order: 20, route_name: 'system-health' },
  access: { id: 'access', label: '用户与权限', group: 'system', order: 30, route_name: 'system-access' },
  debug: { id: 'debug', label: 'Dify 调试', group: 'system', order: 40, route_name: 'system-debug' },
}

function menuPayload(role: string) {
  const ids = ROLE_MENUS[role] || []
  const menu = ids.map((id) => CATALOG[id]).filter(Boolean)
  const used = new Set(menu.map((m) => m.group))
  return {
    schema_version: 2,
    role,
    menu,
    groups: GROUPS.filter((g) => used.has(g.id)),
    default_home: role === 'dept_manager' ? 'patient-qc' : role === 'clinician' ? 'feedback' : 'dashboard',
  }
}

async function mockApis(page: Page, role: string) {
  await page.route('**/api/**', async (route: Route) => {
    const url = route.request().url()
    const method = route.request().method()

    if (url.includes('/api/users/login') && method === 'POST') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          access_token: 'aaa.bbb.ccc',
          user: { id: 1, username: role, full_name: role, role },
        }),
      })
      return
    }
    if (url.includes('/api/users/me')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 1, username: role, full_name: role, role }),
      })
      return
    }
    if (url.includes('/api/menu') && !url.includes('/menu/all')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(menuPayload(role)),
      })
      return
    }
    if (url.includes('/api/health')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          status: 'ok',
          components: { app: { status: 'ok', latency_ms: 1 } },
        }),
      })
      return
    }
    if (url.includes('/api/push/tasks/latest')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ task_id: 't1', status: 'success', total: 1, done: 1, success: 1 }),
      })
      return
    }
    if (url.includes('/api/stats/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ total: 0, success: 0, failed: 0, items: [] }),
      })
      return
    }
    if (url.includes('/api/config/runtime-summary')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_modes: {}, schedulers: {}, warnings: [] }),
      })
      return
    }
    if (url.includes('/api/logs')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items: [], total: 0 }),
      })
      return
    }
    // default empty ok for other GETs
    if (method === 'GET') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: '{}' })
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"success":true}' })
  })
}

async function loginAs(page: Page, role: string) {
  await mockApis(page, role)
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill(role)
  await page.getByPlaceholder('请输入密码').fill('password')
  await page.getByRole('button', { name: '登录' }).click()
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 15_000 })
}

test.describe('auth and role menus', () => {
  for (const role of ['admin', 'dept_manager', 'auditor', 'clinician'] as const) {
    test(`${role} can login and sees only allowed menus`, async ({ page }) => {
      await loginAs(page, role)
      // 不应出现占位菜单
      await expect(page.getByText('Oracle 连接')).toHaveCount(0)
      await expect(page.getByText('运行日志')).toHaveCount(0)
      // clinician 不应看到系统配置
      if (role === 'clinician') {
        await expect(page.getByRole('menuitem', { name: '系统配置' })).toHaveCount(0)
      }
      if (role === 'admin') {
        // 移动端面包屑隐藏，改为校验 shell + 用户区
        await expect(page.locator('.app-header__user')).toBeVisible()
        await expect(page.getByText('Oracle 连接')).toHaveCount(0)
      }
    })
  }

  test('unauthorized direct route shows 403', async ({ page }) => {
    await loginAs(page, 'clinician')
    await page.goto('./#/governance/config')
    await expect(page.getByText('403')).toBeVisible()
  })

  test('refresh keeps session on workbench', async ({ page }) => {
    await loginAs(page, 'auditor')
    await page.goto('./#/workbench')
    await page.reload()
    await expect(page.locator('.app-shell')).toBeVisible()
  })

  test('no red console errors on login flow', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (err) => errors.push(err.message))
    await loginAs(page, 'admin')
    await page.goto('./#/system/health')
    await expect(page.getByRole('heading', { name: '系统健康' })).toBeVisible()
    expect(errors).toEqual([])
  })
})
