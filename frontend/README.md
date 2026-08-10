# Med-Audit Frontend (ui-next)

Vue 3 + Vite + TypeScript + Vue Router (Hash) + Pinia + Element Plus。

- 开发：`npm run dev`（代理 `/api` → `http://127.0.0.1:8000`）
- 类型检查：`npm run typecheck`
- 单元测试：`npm run test:unit`
- 构建产物：`../static/ui-next/`（base=`/ui-next/`）
- E2E：先 `npm run build`，再 `npx playwright install chromium`，然后 `npm run test:e2e`

## 离线构建

1. 在可联网环境执行一次 `npm ci` 生成/更新 `package-lock.json`。
2. 准备 cache：`npm ci --cache .npm-cache --prefer-offline`（可将 `.npm-cache` 随交付包分发）。
3. 目标机：`npm ci --offline --cache .npm-cache` 后 `npm run build`。
4. Docker multi-stage 会在有 `.npm-cache` 时走 offline；**不得把公网临时下载当作生产可复现证明**。

## 与 legacy 并行

- 旧入口：`/`（`static/index.html`）
- 新入口：`/ui-next/`（Hash：`/ui-next/#/workbench`）
- 本轮不切换默认入口（WP6/WP7 另批）
