# 前端模板拆分说明

本目录存放从 `static/index.html` 拆出的 Vue 模板片段。应用启动时，`static/scripts/app.js` 会在 Vue `mount` 前读取 `data-template-src` 占位并替换为对应 HTML 内容。

> **并行入口（017）**：新模块化前端源码在仓库 `frontend/`，构建产物为 `static/ui-next/`，访问路径 `/ui-next/`（Hash Router）。本目录与 `static/index.html` 仍为 **legacy 默认入口**，在 WP7 退役前禁止删除。

## 目录

- `pages/dashboard.html`：仪表盘 / 工作台。
- `pages/push.html`：手动推送、Dify 节点、SQL 预览。
- `pages/audit.html`：质控记录（推送日志）、数据统计。
- `pages/feedback.html`：整改反馈列表、看板、详情弹窗。
- `pages/patient_qc.html`：患者质控。
- `pages/relay_alert.html`：告警记录。
- `pages/relay.html`：告警推送配置。
- `pages/push_progress.html`：任务进度。
- `pages/audit_types.html`：质控类型管理与测试弹窗。
- `pages/access.html`：用户与权限。
- `pages/config.html`：系统配置（含运行总览 tab）。
- `pages/scheduler.html`：定时任务。
- `pages/health.html`：系统健康。
- `pages/debug.html`：Dify 调试（dev_only）。
- `pages/placeholder.html`：Oracle 连接 / 运行日志占位（导航已隐藏）。
- `common/overlays.html`：跨页面公共抽屉和弹窗。
- `mobile/qc_detail.html`：医生 H5（不并入管理端 SPA）。

## 维护规则

- 模板内仍使用主 Vue 实例的状态和方法，不在模板片段中引入脚本。
- 新增页面时，在 `static/index.html` 增加 `data-template-src` 占位，并把模板放入 `pages/`。
- 跨页面弹窗、抽屉优先放入 `common/`。
- 过渡期 `static/scripts/navigation.js` 须与 `app/routers/menu.py` 分组/文案对齐；menu ID 禁止改名。
- 修改后至少运行 `node --check static/scripts/app.js`。
- 新功能优先在 `frontend/` feature 模块实现，避免继续膨胀 `static/scripts/app.js`。
