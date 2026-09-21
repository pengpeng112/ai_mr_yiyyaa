import { execFile } from 'node:child_process'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { expect, test, type Page, type Response } from '@playwright/test'

const execFileAsync = promisify(execFile)

// 048 T5：UI Next 核查工作台真后端链路（demo 主服务 18080 直接服务 static/ui-next，
// 同源访问 /api；sidecar:18600 由编排脚本管理；造数=seed_workbench_demo_20260915.py）。
//
// 运行门：WORKBENCH_E2E=true；编排（scripts/run_workbench_e2e_20260915.py）注入
// PLAYWRIGHT_BASE_URL=http://127.0.0.1:18080/ui-next/ + PLAYWRIGHT_SKIP_WEBSERVER=1。
// desktop-1366 跑完整人工动作链（已查看→提交整改→复检通过，引擎结论保留）；
// mobile-390 只做只读响应式检查（工具栏换行/分页可见/详情可开），与动作链无状态竞争。
test.skip(process.env.WORKBENCH_E2E !== 'true',
  'requires demo main service + sidecar + WORKBENCH_E2E=true')

const DEMO_PASSWORD = 'Demo-12Dept!2026'
const SEED_PATIENT_A = 'WB-E2E-P001'

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

async function uiNextLogin(page: Page) {
  await page.goto('./#/login')
  await expect(page.getByPlaceholder('请输入用户名')).toHaveValue('demo_admin')
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登录系统' }).click()
  await expect(page).toHaveURL(/ui-next\/(workbench)?/, { timeout: 20_000 })
}

async function openWorkbench(page: Page) {
  await page.goto('./#/governance/workbench')
  await expect(page.getByText('核查工作台', { exact: true }).first()).toBeVisible(
    { timeout: 20_000 })
}

test('desktop-1366：非空列表→详情→人工动作链→引擎结论保留', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1366', '有状态动作链只跑桌面轮')
  test.setTimeout(150_000)
  const { api: failedApi, pageErrors } = trackFailures(page)

  // 幂等造数（正式 run + open issue，复位置 open）
  const repoRoot = fileURLToPath(new URL('../../../', import.meta.url))
  const seeded = await execFileAsync('python',
    [join(repoRoot, 'scripts', 'seed_workbench_demo_20260915.py')],
    { cwd: repoRoot, timeout: 60_000 })
  expect(seeded.stderr || '').toBe('')

  await uiNextLogin(page)
  await openWorkbench(page)

  // 非空列表（真后端数据，非 mock）：种子患者可见 + 分页元数据
  const rowA = page.locator('.el-table__row', { hasText: SEED_PATIENT_A }).first()
  await expect(rowA).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(/第 \d+-\d+ 条 \/ 共 \d+ 条/)).toBeVisible()
  await expect(rowA.getByText('已完成')).toBeVisible()   // 运行状态中文

  // 详情：引擎结论=缺陷；人工状态=待处理；依据中文
  await rowA.getByRole('button', { name: '详情' }).click()
  const drawer = page.locator('.el-drawer', { hasText: '核查详情' })
  await expect(drawer).toBeVisible()
  const clauseRow = drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' }).first()
  await expect(clauseRow.getByText('缺陷')).toBeVisible()
  await expect(clauseRow.getByText('待处理')).toBeVisible()
  await expect(clauseRow.getByText('缺少必需文书')).toBeVisible()

  // 人工动作链（demo_admin 持 feedback+review 双权限）：已查看→提交整改→复检通过
  await clauseRow.getByRole('button', { name: '已查看', exact: true }).click()
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('已查看')).toBeVisible({ timeout: 15_000 })
  await drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByRole('button', { name: '提交整改' }).click()
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('整改中')).toBeVisible({ timeout: 15_000 })
  await drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByRole('button', { name: '复检通过' }).click()
  const prompt = page.locator('.el-message-box')
  await prompt.getByPlaceholder('请填写原因').fill('UI Next E2E 复检（合成数据）')
  await prompt.getByRole('button', { name: /^(确定|OK)$/ }).click()
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('复检通过')).toBeVisible({ timeout: 15_000 })
  // 引擎结论与人工状态分离：人工终态后引擎结论仍为「缺陷」
  await expect(drawer.locator('.el-table__row', { hasText: 'R-WB-E2E-01' })
    .first().getByText('缺陷')).toBeVisible()
  await page.keyboard.press('Escape')

  // 精确失败断言：本正向链不允许任何 /api 失败（无已知豁免；/users/me 已认证）
  expect(failedApi, `未预期的 API 失败: ${failedApi.join(',')}`).toEqual([])
  expect(pageErrors, `零未处理 pageerror: ${pageErrors.join(',')}`).toEqual([])
})

test('mobile-390：响应式只读检查（工具栏换行/分页/详情可达）', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-390', '响应式检查只跑移动轮')
  test.setTimeout(120_000)
  const { pageErrors } = trackFailures(page)

  await uiNextLogin(page)
  await openWorkbench(page)

  await expect(page.locator('.el-table__row', { hasText: SEED_PATIENT_A })
    .first()).toBeVisible({ timeout: 30_000 })
  // 工具栏换行不横向溢出
  await expect.poll(async () => page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth + 2)).toBe(true)
  // 分页可达
  await expect(page.locator('.el-pagination')).toBeVisible()
  // 详情抽屉在窄屏可打开且内容可滚动
  await page.locator('.el-table__row', { hasText: SEED_PATIENT_A })
    .first().getByRole('button', { name: '详情' }).click()
  const drawer = page.locator('.el-drawer', { hasText: '核查详情' })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('R-WB-E2E-01').first()).toBeVisible()
  await page.keyboard.press('Escape')
  expect(pageErrors, `零未处理 pageerror: ${pageErrors.join(',')}`).toEqual([])
})
