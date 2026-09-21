import { execFile } from 'node:child_process'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { expect, test, type Page, type Response } from '@playwright/test'

const execFileAsync = promisify(execFile)

// 046 T5 → 048 T5 重写：核查工作台 Legacy E2E（真实隔离后端：demo_env serve:18080 + sidecar:18600）。
// 覆盖：
// - 真实 API 全链：AI 匹配(stub)→候选接受→trial 执行→观察数据；
// - 非空工作台链路（seed_workbench_demo_20260915.py 预置正式 run+open issue）：
//   列表→详情→已查看→提交整改→复检通过；人工状态与引擎结论分别保留；
// - 409 乐观锁（仅该请求允许 409）；BFF 科室范围（clinician 仅本科室、跨科室详情 403）；
// - 降级轮（sidecar 停）：核查 tab 错误态 + 主页面不受影响 + 零 pageerror。
//
// 失败断言口径（048 Q2）：不再整体豁免 prearchive-admin——
// 除「显式允许清单」（/api/users/me 未认证探测、用例内刻意触发的 409/403、
// 降级轮 checks 502/503）外，任何 /api 失败都判失败。
test.skip(process.env.LEGACY_E2E !== 'true', 'requires demo stack + LEGACY_E2E=true')

const DEGRADED = process.env.RULE_CENTER_SIDECAR === '0'
const DEMO_ADMIN = 'demo_admin'
const DEMO_PASSWORD = 'Demo-12Dept!2026'
const CLINICIAN = 'clinician_d001'          // 听觉植入科（DEMO-D001）
const SEED_PATIENT_A = 'WB-E2E-P001'        // DEMO-D001（本科室）
const SEED_PATIENT_B = 'WB-E2E-P002'        // DEMO-D002（跨科室，clinician 不可见）

function trackFailures(page: Page): { api: string[]; pageErrors: string[] } {
  const failedApi: string[] = []
  const pageErrors: string[] = []
  page.on('response', (response: Response) => {
    if (response.status() >= 400 && response.url().includes('/api/')) {
      failedApi.push(`${response.status()} ${response.request().method()} ${response.url()}`)
    }
  })
  page.on('pageerror', (error) => pageErrors.push(String(error)))
  return { api: failedApi, pageErrors }
}

async function legacyLogin(page: Page, username = DEMO_ADMIN) {
  await page.goto('/index.html')
  await expect(page.getByText('欢迎登录')).toBeVisible()
  await page.getByPlaceholder('请输入用户名').fill(username)
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page.locator('.main-area')).toBeVisible({ timeout: 20_000 })
}

async function openAuditTypesPage(page: Page) {
  await page.locator('.el-menu').getByText(/规则与配置|治理/, { exact: true }).first().click()
  await page.locator('.el-menu-item', { hasText: '质控类型' }).first().click()
}

async function authedFetch(page: Page, path: string, init: RequestInit = {}) {
  // 023 P1-03：legacy 会话主通道=HttpOnly Cookie；page.request 共享浏览器
  // 上下文 Cookie，同源自动携带。写请求需带 CSRF 头（与页面 api.js 同口径）。
  const method = (init.method || 'GET').toUpperCase()
  const headers = { ...(init.headers || {}) } as Record<string, string>
  if (method !== 'GET' && method !== 'HEAD') {
    headers['X-Requested-With'] = 'XMLHttpRequest'
  }
  return page.request.fetch(path, { ...init, headers })
}

test('工作台真实链路：AI匹配(stub)→候选接受→trial执行→观察数据入页', async ({ page }) => {
  test.skip(DEGRADED, 'degradation round skips positive case')
  test.setTimeout(180_000)
  // 幂等造数：正式 run + open issue（demo 隔离 sqlite；spec 自带，便于手工复跑）
  const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
  const seeded = await execFileAsync('python',
    [join(repoRoot, 'scripts', 'seed_workbench_demo_20260915.py')],
    { cwd: repoRoot, timeout: 60_000 })
  expect(seeded.stderr || '').toBe('')
  const { api: failedApi, pageErrors } = trackFailures(page)
  const allowed409: string[] = []

  await legacyLogin(page)
  await openAuditTypesPage(page)
  const card = page.locator('.page-card', { hasText: '归档前规则中心' })
  await expect(card).toBeVisible({ timeout: 30_000 })

  // ---- 真实 API 链（经主服务 BFF → sidecar）：匹配 FID38 → 接受 → trial → 执行 ----
  const imported = await authedFetch(page, '/api/prearchive-admin/coverage/import-snapshot', {
    method: 'POST', data: JSON.stringify({ apply: true }),
    headers: { 'Content-Type': 'application/json' },
  })
  expect(imported.ok(), `coverage import: ${imported.status()}`).toBeTruthy()

  const task = await (await authedFetch(page, '/api/prearchive-admin/match/tasks', {
    method: 'POST', data: JSON.stringify({ fids: [38], model: 'stub' }),
    headers: { 'Content-Type': 'application/json' },
  })).json()
  const ran = await (await authedFetch(
    page, `/api/prearchive-admin/match/tasks/${task.task_id}/run`, { method: 'POST' })).json()
  expect(['completed', 'partial']).toContain(ran.status)

  const detail = await (await authedFetch(
    page, `/api/prearchive-admin/match/tasks/${task.task_id}`)).json()
  const candidate = (detail.candidates || []).find(
    (c: { validation_ok: boolean; suggested_dsl: object }) =>
      c.validation_ok && Object.keys(c.suggested_dsl || {}).length > 0)
  expect(candidate, 'stub 应产出合法候选').toBeTruthy()

  const decided = await authedFetch(
    page, `/api/prearchive-admin/match/candidates/${candidate.candidate_id}/decision`, {
      method: 'POST',
      data: JSON.stringify({ decision: 'accepted', note: 'E2E 观察' }),
      headers: { 'Content-Type': 'application/json' },
    })
  expect([200, 409]).toContain(decided.status())   // 任务按输入复用→已决策 409 幂等续跑
  if (decided.status() === 409) allowed409.push('candidate-decision-reuse')

  const trial = await (await authedFetch(page, '/api/prearchive-admin/trial/runs', {
    method: 'POST',
    data: JSON.stringify({ candidate_ids: [candidate.candidate_id],
                           scope: { synthetic_only: true } }),
    headers: { 'Content-Type': 'application/json' },
  })).json()
  expect(trial.status).toBe('requested')
  const executed = await (await authedFetch(
    page, `/api/prearchive-admin/trial/runs/${trial.trial_run_id}/execute`,
    { method: 'POST' })).json()
  expect(executed.status).toBe('completed')
  expect(executed.patients).toBeGreaterThan(0)

  const obs = await (await authedFetch(
    page, `/api/prearchive-admin/trial/runs/${trial.trial_run_id}/observations`)).json()
  expect(obs.totals.executions).toBeGreaterThan(0)

  await card.locator('.el-tabs__item', { hasText: '试运行观察' }).click()
  await card.getByRole('button', { name: '刷新试运行' }).click()
  await expect(card.locator('.el-table__row', { hasText: trial.trial_run_id })
    .first()).toBeVisible({ timeout: 30_000 })

  // ---- 非空核查工作台（seed 预置）：列表 → 详情 → 人工动作全链 ----
  await card.locator('.el-tabs__item', { hasText: '核查工作台' }).click()
  await card.getByRole('button', { name: '刷新核查列表' }).click()
  const rowA = card.locator('.el-table__row', { hasText: SEED_PATIENT_A }).first()
  await expect(rowA).toBeVisible({ timeout: 30_000 })
  // 分页元数据可见（legacy Element 默认英文 locale：Total N；中文环境为 共 N 条）
  await expect(card.locator('.el-pagination')).toBeVisible()
  await expect(card.locator('.el-pagination')
    .getByText(/(Total|共)\s*\d+/)).toBeVisible()

  // 详情：引擎结论=缺陷(fail) 保持，人工状态=待处理
  await rowA.getByRole('button', { name: '详情' }).click()
  const drawer = page.locator('.el-drawer', { hasText: '核查详情' })
  await expect(drawer).toBeVisible()
  const issueRow = drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' }).first()
  await expect(issueRow.getByText('缺陷')).toBeVisible()          // 引擎结论中文
  await expect(issueRow.getByText('待处理')).toBeVisible()        // 人工状态中文
  await expect(issueRow.getByText('缺少必需文书')).toBeVisible()  // reason_code 中文

  // 乐观锁 409：真实 issue + 过期 version（仅此请求允许 409）
  const runAList = await (await authedFetch(page,
    '/api/prearchive-admin/checks?page=1&page_size=50')).json()
  const runA = runAList.items.find((i: { patient_id: string }) => i.patient_id === SEED_PATIENT_A)
  expect(runA, '种子 run A 应在列表').toBeTruthy()
  const runADetail = await (await authedFetch(page,
    `/api/prearchive-admin/checks/${runA.run_id}`)).json()
  const seedClause = runADetail.clauses.find((c: { rule_id: string }) =>
    c.rule_id === 'R-WB-E2E-01')
  expect(seedClause?.issue, '种子缺陷应已物化').toBeTruthy()
  const stale = await authedFetch(page,
    `/api/prearchive-admin/issues/${seedClause.issue.issue_id}/actions`, {
      method: 'POST',
      data: JSON.stringify({ action: 'viewed', expect_issue_version: 99999 }),
      headers: { 'Content-Type': 'application/json' },
    })
  expect(stale.status(), '过期 version 必须精确 409').toBe(409)
  allowed409.push(`stale:${seedClause.issue.issue_id}`)

  // 人工动作链：已查看 → 提交整改 → 复检通过（admin 持双权限）
  await issueRow.getByRole('button', { name: '已查看' }).click()
  await expect(page.locator('.el-message', { hasText: '已记录' }).first()).toBeVisible({ timeout: 10_000 })
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('已查看')).toBeVisible({ timeout: 10_000 })
  const rowAfterView = drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' }).first()
  await rowAfterView.getByRole('button', { name: '提交整改' }).click()
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('整改中')).toBeVisible({ timeout: 10_000 })
  const rowRectifying = drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' }).first()
  await rowRectifying.getByRole('button', { name: '复检通过' }).click()
  const prompt = page.locator('.el-message-box')
  await prompt.getByPlaceholder('请填写原因').fill('E2E 复检通过（合成数据）')
  await prompt.getByRole('button', { name: /^(确定|OK)$/ }).click()   // legacy Element 默认英文 locale
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('复检通过')).toBeVisible({ timeout: 10_000 })
  // 引擎结论在人工动作后仍保留为「缺陷」（人工状态与引擎结论分离）
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('缺陷')).toBeVisible()
  await page.keyboard.press('Escape')

  // ---- BFF 科室范围（API 级，真实 RBAC）：clinician 仅本科室 + 跨科室详情 403 ----
  // admin 对照取数必须在切换身份前（登录 Set-Cookie 覆盖共享上下文会话）
  const runB = await (await authedFetch(page,
    '/api/prearchive-admin/checks?page=1&page_size=50')).json()
  const crossRun = runB.items.find((i: { patient_id: string }) => i.patient_id === SEED_PATIENT_B)
  expect(crossRun, 'admin 应看到跨科室种子（对照）').toBeTruthy()

  const clinicianLogin = await page.request.post('/api/users/login', {
    data: { username: CLINICIAN, password: DEMO_PASSWORD },
  })
  expect(clinicianLogin.ok(), 'clinician 登录').toBeTruthy()
  // Cookie 通道：后续 page.request 即 clinician
  const clinicianChecks = await (await page.request.get(
    '/api/prearchive-admin/checks?page=1&page_size=50')).json()
  expect(clinicianChecks.total).toBeGreaterThanOrEqual(1)
  for (const item of clinicianChecks.items) {
    expect(item.dept_code, 'clinician 只能看到本科室 run').toBe('DEMO-D001')
  }
  expect(clinicianChecks.items.some((i: { patient_id: string }) =>
    i.patient_id === SEED_PATIENT_A)).toBeTruthy()
  expect(clinicianChecks.items.some((i: { patient_id: string }) =>
    i.patient_id === SEED_PATIENT_B), '跨科室种子不可见').toBeFalsy()

  const denied = await page.request.get(
    `/api/prearchive-admin/checks/${crossRun.run_id}`)
  expect(denied.status(), 'clinician 跨科室详情必须 403').toBe(403)

  // ---- 精确失败断言：除允许清单外任何 /api 失败都算阻断 ----
  const blocking = failedApi.filter((entry) => {
    if (entry.includes('/api/users/me')) return false
    if (entry.startsWith('409 ') && allowed409.some((id) => entry.includes(id))) return false
    if (entry.startsWith('403 ') && entry.includes(`/checks/${crossRun.run_id}`)) return false
    return true
  })
  expect(blocking, `未预期的 API 失败: ${blocking.join(',')}`).toEqual([])
  expect(pageErrors, `零未处理 pageerror: ${pageErrors.join(',')}`).toEqual([])
})

test('工作台降级：sidecar 停 → 核查错误态可重试，主页面可用，零 pageerror', async ({ page }) => {
  test.setTimeout(120_000)
  const { api: failedApi, pageErrors } = trackFailures(page)
  await legacyLogin(page)
  await openAuditTypesPage(page)
  const card = page.locator('.page-card', { hasText: '归档前规则中心' })
  await expect(card).toBeVisible({ timeout: 30_000 })
  if (DEGRADED) {
    await expect(card.getByText(/规则中心不可用/).first()).toBeVisible()
    // 降级轮允许的失败仅 502/503 且仅 prearchive-admin 路径
    const illegal = failedApi.filter((entry) =>
      !(entry.includes('prearchive-admin')
        && (entry.startsWith('502 ') || entry.startsWith('503 ')))
      && !entry.includes('/api/users/me'))
    expect(illegal, `降级轮不允许的 API 失败: ${illegal.join(',')}`).toEqual([])
  } else {
    await card.locator('.el-tabs__item', { hasText: '核查工作台' }).click()
    await expect(card.locator('.el-tabs__item', { hasText: '核查工作台' })).toBeVisible()
  }
  await expect(page.locator('.el-menu-item', { hasText: '质控类型' })).toBeVisible()
  expect(pageErrors, `零未处理 pageerror: ${pageErrors.join(',')}`).toEqual([])
})
