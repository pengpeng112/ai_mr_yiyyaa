# 山东省第二人民医院 · AI病历质控系统 · 本地设计画板 v2

这是 Figma MCP 额度受限时的本地平替画板 v2：无构建、无 API、无网络资源，仅使用匿名合成数据展示已确认的信息架构与交互状态。侧栏中的 AI/医疗标记是可替换抽象标记，不代表医院官方 Logo。

## 启动

直接在浏览器打开 `index.html`，或在仓库根目录运行任意静态文件服务器后访问该目录。不要把本目录接入生产入口。

## 内容

- Foundations：代码真值 token 摘要。
- Components：App Shell、筛选、表格、Drawer、状态和按钮。
- Patterns：列表详情、分步操作、配置编辑、告警时间线、调度诊断。
- 7 个代表页：Workbench、Quality Records + Detail、Alert Timeline、Manual Push、Audit Type Editor、Scheduler Dual Locks、Config + Access。
- 品牌上下文固定为“山东省第二人民医院 / AI病历质控系统”，界面主要内容中文化。
- 浅色现代医疗骨架、深蓝导航、局部蓝青 AI 渐变；工作台使用 SVG 趋势与风险环图，不使用外部图标或图片。
- Desktop / Tablet / Mobile 视口切换。
- Default、Loading、Empty、Error、403、Readonly、Dirty、Confirm、Saving、Success、Failure 及页面专属状态。

## 与 Figma 的命名回灌

本地画板的 `data-page`、`data-state`、`data-viewport` 值可作为 Figma frame 命名来源：

```text
SCREEN / Desktop / Workbench / Default
SCREEN / Mobile / Scheduler Dual Locks / Stale Lock
COMP / Data / TableShell / State=Loading
```

后续 Figma 文件应按 `00 Cover → 01 Getting Started → 02 Foundations → 03 Components → 04 Patterns → 05 Screens → 06 Prototype Flows → 07 QA & Handoff` 建立页面。`menu_id` 与 Vue route manifest 保持代码真值；本画板不执行 RBAC 或真实写操作。

## 边界

- token 真值来自 `frontend/src/styles/tokens.css`、`global.css`、`element-overrides.css`；本地新增 token 只放在 `--proposed-*` 命名空间并标注 Proposed。
- 不展示真实患者、病历、密钥、API 请求或响应。
- 不复制业务 JS、不发请求、不触发推送、调度、告警、Dify 或数据库操作。
- 管理端与医生 H5、`log_detail.html`、legacy `/` 保持独立边界。
