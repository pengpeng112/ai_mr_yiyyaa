import { expect, test, type Page } from '@playwright/test'

// 054 §10 U2/H03/H04/H11（uat054 增补）：真后端权限 fail-closed 与会话失效。
// 运行门：UAT054_E2E=true + PLAYWRIGHT_SKIP_WEBSERVER=1 +
//   PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080/ui-next/（demo 主服务直接服务构建产物）；
// 造数=scripts/seed_workbench_demo_20260915.py（编排先跑，WB-E2E-P001/P002 幂等种子）。
// 故障注入位置：仅 H04-fail-closed 用例拦截 /api/users/login 与 /api/users/me
//   剥掉 user.permissions 字段（模拟"权限信息缺失"），其余用例走真实响应。
test.skip(process.env.UAT054_E2E !== 'true',
  'requires demo main service + seed + UAT054_E2E=true')

const DEMO_PASSWORD = 'Demo-12Dept!2026'
const REVIEW_DEPT_INPUT = '科室编码（复核角色）'

async function loginAs(page: Page, username: string, password: string = DEMO_PASSWORD) {
  await page.goto('./#/login')
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(password)
  await page.getByRole('button', { name: '登录系统' }).click()
  // 注意：/ui-next\/(workbench)?/ 会匹配 #/login，必须同时等 app-shell 出现才算登录完成
  await expect(page.locator('.app-shell')).toBeVisible({ timeout: 20_000 })
  await expect(page).not.toHaveURL(/#\/login/)
}

/** 切换用户：清本地会话并重载（已认证会话会被守卫挡在登录页外） */
async function switchUser(page: Page) {
  await page.evaluate(() => localStorage.clear())
  await page.reload()
  await page.goto('./#/login')
}

async function openWorkbenchFiltered(page: Page, patient: string) {
  await page.goto('./#/governance/workbench')
  await expect(page.getByText('核查工作台', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByPlaceholder('患者ID').fill(patient)
  await page.getByRole('button', { name: '刷新核查列表' }).click()
}

test('H04 review-only(auditor)：复核动作可见、反馈动作不可见（真实 permissions 精确判定）', async ({ page }) => {
  await loginAs(page, 'demo_auditor')
  await openWorkbenchFiltered(page, 'WB-E2E-P001')
  await expect(page.getByRole('cell', { name: 'WB-E2E-P001' }).first()).toBeVisible({ timeout: 20_000 })
  // auditor 有 prearchive_issue_review：复核筛选框可见
  await expect(page.getByPlaceholder(REVIEW_DEPT_INPUT)).toBeVisible()
  await page.getByRole('button', { name: '详情' }).first().click()
  await expect(page.getByRole('button', { name: '误报' }).first()).toBeVisible()
  // auditor 无 prearchive_issue_feedback：整改/已查看不可见
  await expect(page.getByRole('button', { name: '提交整改' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '已查看' })).toHaveCount(0)
})

test('H04 feedback-only(dept_manager)：反馈动作可见、复核动作不可见，跨科室患者不可见；clinician 无菜单直达被拒', async ({ page }) => {
  // clinician 无 governance workbench 菜单 → 直达被守卫拦截（H02 语义，正确行为）
  await loginAs(page, 'clinician_d001')
  await page.goto('./#/governance/workbench')
  await expect(page.getByText(/403|无权|禁止/).first()).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('核查工作台', { exact: true }).first()).toHaveCount(0)

  // manager_d001：有 workbench 菜单但仅 prearchive_issue_feedback（真实 feedback-only）
  await switchUser(page)
  await loginAs(page, 'manager_d001')
  await openWorkbenchFiltered(page, 'WB-E2E-P002')
  // P002 属 DEMO-D002，manager_d001 仅本科（服务端科室隔离）
  await expect(page.getByRole('cell', { name: 'WB-E2E-P002' })).toHaveCount(0)
  await expect(page.getByPlaceholder(REVIEW_DEPT_INPUT)).toHaveCount(0)

  await openWorkbenchFiltered(page, 'WB-E2E-P001')
  await expect(page.getByRole('cell', { name: 'WB-E2E-P001' }).first()).toBeVisible({ timeout: 20_000 })
  await page.getByRole('button', { name: '详情' }).first().click()
  await expect(page.getByRole('button', { name: '提交整改' }).first()).toBeVisible()
  await expect(page.getByRole('button', { name: '误报' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '复检通过' })).toHaveCount(0)
})

test('H04 fail-closed：permissions 缺失→写按钮隐藏+可重试；重载权限后恢复（注入仅剥字段）', async ({ page }) => {
  const stripPerms = (body: string) => {
    const data = JSON.parse(body)
    if (data && typeof data === 'object' && 'user' in data && data.user && typeof data.user === 'object') {
      const { permissions: _drop, ...rest } = data.user
      data.user = rest
    }
    if (data && typeof data === 'object' && 'permissions' in data) {
      const { permissions: _drop, ...rest } = data
      Object.keys(data).forEach((k) => delete (data as Record<string, unknown>)[k])
      Object.assign(data, rest)
    }
    return JSON.stringify(data)
  }
  await page.route('**/api/users/login', async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, body: stripPerms(await response.text()) })
  })
  await page.route('**/api/users/me', async (route) => {
    const response = await route.fetch()
    await route.fulfill({ response, body: stripPerms(await response.text()) })
  })

  await loginAs(page, 'demo_admin')
  await openWorkbenchFiltered(page, 'WB-E2E-P001')
  await expect(page.getByRole('cell', { name: 'WB-E2E-P001' }).first()).toBeVisible({ timeout: 20_000 })
  // 缺失=不可用：提示可见、复核筛选框隐藏、行内写按钮全部隐藏
  await expect(page.getByText('用户权限信息未加载，写操作暂不可用')).toBeVisible()
  await expect(page.getByPlaceholder(REVIEW_DEPT_INPUT)).toHaveCount(0)
  await page.getByRole('button', { name: '详情' }).first().click()
  await expect(page.getByRole('button', { name: '已查看' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '提交整改' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '误报' })).toHaveCount(0)
  await expect(page.getByRole('button', { name: '复检通过' })).toHaveCount(0)

  // 解除注入 → 关闭详情抽屉 → 重新加载权限 → 恢复（同一会话不清登录）
  await page.unroute('**/api/users/login')
  await page.unroute('**/api/users/me')
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '重新加载权限' }).click()
  await expect(page.getByText('用户权限信息未加载，写操作暂不可用')).toHaveCount(0)
  await expect(page.getByPlaceholder(REVIEW_DEPT_INPUT)).toBeVisible()
  // 重开详情确认行内写动作恢复
  await page.getByRole('button', { name: '详情' }).first().click()
  await expect(page.getByRole('button', { name: '误报' }).first()).toBeVisible()
})

test('H03 会话失效：账号被停用后刷新→回登录页带失效提示，旧 token 调 API 返回 401（无静默成功）', async ({ browser, page }) => {
  // 管理员建合成账号（clinician 角色）→ 独立上下文登录 → 管理员停用 → 刷新验证
  await loginAs(page, 'demo_admin')
  const adminToken = await page.evaluate(() => localStorage.getItem('auth_token'))
  expect(adminToken).toBeTruthy()
  const api = async (path: string, init: RequestInit) =>
    page.evaluate(async ({ path, init }) => {
      const res = await fetch(path, init)
      return { status: res.status, body: await res.json().catch(() => null) }
    }, { path, init })
  const authed = (method: string, path: string, body?: unknown): RequestInit => ({
    method,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${adminToken}` },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const roles = await api('/api/roles?page=1&limit=50', authed('GET', '/api/roles?page=1&limit=50'))
  const clinicianRole = (roles.body?.roles || roles.body || []).find?.(
    (r: { name: string }) => r.name === 'clinician')
  expect(clinicianRole?.id).toBeTruthy()
  const suffix = Date.now().toString().slice(-8)
  const username = `uat054_h03_${suffix}`
  const created = await api('/api/users', authed('POST', '/api/users', {
    username, password: 'Uat054!Pass', full_name: 'UAT054会话失效合成账号',
    role_id: clinicianRole.id,
  }))
  expect(created.status).toBeLessThan(300)

  const ctxB = await browser.newContext({ viewport: { width: 1366, height: 768 } })
  const pageB = await ctxB.newPage()
  await loginAs(pageB, username, 'Uat054!Pass')
  // clinician 角色可访问患者质控页（合成账号无 governance workbench 菜单，属预期）
  await pageB.goto('./#/quality/patients')
  await expect(pageB.getByText('患者质控', { exact: true }).first()).toBeVisible({ timeout: 20_000 })
  const staleToken = await pageB.evaluate(() => localStorage.getItem('auth_token'))
  expect(staleToken).toBeTruthy()

  // 管理员停用该账号（=服务端会话失效，H41 撤权路径同链）
  const disabled = await api(`/api/users/${created.body.id}`, authed('PUT', `/api/users/${created.body.id}`, { is_active: false }))
  expect(disabled.status).toBeLessThan(300)
  // 刷新：restoreSession 401 → 回登录页 + 失效提示；不静默留在业务页
  await pageB.reload()
  await expect(pageB).toHaveURL(/#\/login/, { timeout: 20_000 })
  await expect(pageB.getByText(/登录已失效|请重新登录/).first()).toBeVisible({ timeout: 10_000 })
  // 旧 token 再调受保护接口被拒绝（服务端拒绝停用用户，非仅前端清理）
  const reuse = await pageB.evaluate(async (token: string) => {
    const res = await fetch('/api/users/me', { headers: { Authorization: `Bearer ${token}` } })
    return res.status
  }, staleToken as string)
  expect(reuse).toBe(401)
  await ctxB.close()
})

test('H11 未认证访问独立详情页：/api/logs/{id} 被拒（401/403）且不泄漏患者详情', async ({ page }) => {
  const failed: number[] = []
  page.on('response', (r) => { if (r.url().includes('/api/logs')) failed.push(r.status()) })
  await page.goto('/log_detail.html?id=88')
  await page.waitForTimeout(2500)
  // 服务端拒绝无凭据请求（无 token 时走 403，坏 token 走 401——均为拒绝）
  expect(failed.length).toBeGreaterThan(0)
  expect(failed.every((s) => s === 401 || s === 403)).toBe(true)
  // 页面不出现患者维度数据（静态模板有「患者ID：--」占位，断言值不为真实数据）
  await expect(page.getByText(/高风险患者/)).toHaveCount(0)
  const bodyText = await page.locator('body').innerText()
  expect(bodyText).not.toMatch(/患者ID：(?!--)/)
  expect(bodyText).not.toMatch(/住院号|身份证号/)
})
