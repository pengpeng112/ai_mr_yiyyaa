import { defineConfig, devices } from '@playwright/test'

// 035/RP6：legacy 前端（static/ 由 FastAPI 挂载于 /）独立 E2E 配置。
// 与 ui-next 配置（playwright.config.ts，base /ui-next/）分轨：
// - base URL 指向 demo 隔离真后端（scripts/demo_env.py serve，默认 18080），
//   覆盖登录/菜单/质控类型页（含 prearchive 卡片）/推送/日志/统计/错误态/CSP 头；
// - 运行门：LEGACY_E2E=true（用例内 skip），与 SYNTHETIC_DEMO_E2E 同模式。
const baseURL = process.env.PLAYWRIGHT_LEGACY_BASE_URL || 'http://127.0.0.1:18080/'

export default defineConfig({
  testDir: 'tests/e2e-legacy',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'off',
  },
  projects: [
    {
      name: 'legacy-desktop-1366',
      use: { ...devices['Desktop Chrome'], viewport: { width: 1366, height: 768 } },
    },
  ],
  // 服务器由 scripts/demo_env.py serve 外部管理（legacy 用真后端发 CSP 头）
  webServer: undefined,
})
