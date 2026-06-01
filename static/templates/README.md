# 前端模板拆分说明

本目录存放从 `static/index.html` 拆出的 Vue 模板片段。应用启动时，`static/scripts/app.js` 会在 Vue `mount` 前读取 `data-template-src` 占位并替换为对应 HTML 内容。

## 目录

- `pages/dashboard.html`：仪表盘。
- `pages/push.html`：手动推送、Dify 节点、SQL 预览。
- `pages/audit.html`：审计中心、推送日志、数据统计。
- `pages/feedback.html`：质控反馈列表、看板、详情弹窗。
- `pages/audit_types.html`：审计类型管理与测试弹窗。
- `pages/access.html`：权限管理、用户、角色、权限、科室弹窗。
- `pages/config.html`：系统配置。
- `pages/scheduler.html`：定时任务。
- `pages/health.html`：系统健康。
- `pages/debug.html`：Dify 调试。
- `common/overlays.html`：跨页面公共抽屉和弹窗。

## 维护规则

- 模板内仍使用主 Vue 实例的状态和方法，不在模板片段中引入脚本。
- 新增页面时，在 `static/index.html` 增加 `data-template-src` 占位，并把模板放入 `pages/`。
- 跨页面弹窗、抽屉优先放入 `common/`。
- 修改后至少运行 `node --check static/scripts/app.js`。
