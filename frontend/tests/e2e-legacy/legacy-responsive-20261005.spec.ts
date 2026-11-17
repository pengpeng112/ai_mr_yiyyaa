import { expect, test, type Locator, type Page } from '@playwright/test'

// 060 T5 F19 补充（2026-10-05）：legacy 平板(768×1024)/手机(390×844) 视口专项。
// 背景：playwright.legacy.config.ts 默认仅桌面 1366 项目，F19 三视口在 legacy 侧此前为登记缺口。
// 本 spec 用显式 viewport 的独立 context 补齐两视口（不改既有配置，避免影响其他 spec 的 projects 语义）。
// legacy 壳为响应式双菜单：窄视口隐藏 desktop-menu、由 `.mobile-menu-btn` 打开 `el-drawer` 抽屉菜单——
// 该行为本身即为 F19 的被测对象。
// 判据（独立期望，不镜像实现）：
//   1) 登录后关键页面在两视口均可加载：零 pageerror、主内容可见（不白屏）；
//   2) 横滚允许（legacy 内容区为桌面设计）但有界：documentElement.scrollWidth ≤ 2×viewport.width；
//   3) 记录实际 scrollWidth 与所用菜单路径（desktop/drawer）作为现状基线证据。
// 运行前置：demo serve + LEGACY_E2E=true（与其他 legacy spec 同门）。
test.skip(process.env.LEGACY_E2E !== 'true', 'requires scripts/demo_env.py serve + LEGACY_E2E=true')

const DEMO_ADMIN = 'demo_admin'
const DEMO_PASSWORD = 'Demo-12Dept!2026'
const VIEWPORTS = [
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'mobile-390', width: 390, height: 844 },
]
const PAGES: Array<{ group: RegExp; item: string; expectText: RegExp }> = [
  { group: /质控中心|质控/, item: '质控记录', expectText: /质控记录|推送日志/ },
  { group: /任务中心|任务/, item: '手动推送', expectText: /手动推送|开始推送|查询预览/ },
  { group: /规则与配置|治理/, item: '质控类型', expectText: /质控类型|归档前预检/ },
]

async function legacyLogin(page: Page) {
  await page.goto('/index.html')
  await expect(page.getByText('欢迎登录')).toBeVisible()
  await page.getByPlaceholder('请输入用户名').fill(DEMO_ADMIN)
  await page.getByPlaceholder('请输入密码').fill(DEMO_PASSWORD)
  await page.getByRole('button', { name: '登 录' }).click()
  await expect(page.locator('.main-area')).toBeVisible({ timeout: 20_000 })
}

async function menuScope(page: Page): Promise<{ menu: Locator; mode: 'drawer' | 'desktop' }> {
  const btn = page.locator('.mobile-menu-btn')
  if (await btn.isVisible().catch(() => false)) {
    await btn.click()
    const menu = page.locator('.el-drawer .el-menu[role="menubar"]')
    await expect(menu).toBeVisible({ timeout: 10_000 })
    return { menu, mode: 'drawer' }
  }
  return { menu: page.locator('.el-menu:visible').first(), mode: 'desktop' }
}

async function openMenuItem(page: Page, group: RegExp, item: string) {
  const { menu } = await menuScope(page)
  const itemLoc = menu.locator('.el-menu-item', { hasText: item }).first()
  if (!(await itemLoc.isVisible().catch(() => false))) {
    await menu.getByText(group, { exact: false }).first().click()
  }
  await itemLoc.click()
}

test('F19 legacy 平板/手机视口：登录+三关键页加载/零pageerror/横滚有界', async ({ browser }) => {
  test.setTimeout(180_000)
  const baseline: Record<string, unknown> = {}
  for (const vp of VIEWPORTS) {
    const context = await browser.newContext({ viewport: { width: vp.width, height: vp.height } })
    const page = await context.newPage()
    const pageErrors: string[] = []
    page.on('pageerror', (err) => pageErrors.push(String(err)))

    await legacyLogin(page)
    baseline[`${vp.name}:after-login`] = await page.evaluate(() => document.documentElement.scrollWidth)
    expect(baseline[`${vp.name}:after-login`] as number, `${vp.name} 登录页横滚`).toBeLessThanOrEqual(vp.width * 2)

    for (const target of PAGES) {
      await openMenuItem(page, target.group, target.item)
      await expect(page.locator('.main-area').getByText(target.expectText).first()).toBeVisible({ timeout: 20_000 })
      const sw = await page.evaluate(() => document.documentElement.scrollWidth)
      baseline[`${vp.name}:${target.item}`] = sw
      expect(sw, `${target.item}@${vp.name} scrollWidth=${sw}`).toBeLessThanOrEqual(vp.width * 2)
    }
    expect(pageErrors, `${vp.name} pageerrors: ${pageErrors.join('; ')}`).toHaveLength(0)
    await context.close()
  }
  console.log(`[F19-baseline] ${JSON.stringify(baseline)}`)
})
