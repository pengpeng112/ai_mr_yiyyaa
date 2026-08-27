# Med-Audit 前端信息架构、菜单布局与可扩展 App Shell 分阶段整改计划

> 状态：WP0–WP5 本地实施完成并完成契约加固；WP6/WP7 未实施；交接见 018（2026-08-10）
> 制定日期：2026-08-09
> 适用仓库：`F:\python\前后端代码\ai_mrzk`
> 主要范围：管理端前端架构、菜单信息架构、页面布局、组件复用、路由与状态管理、测试和发布方式
> 安全边界：本文件是实施作业书，不授权修改生产、部署镜像、调用 Dify、触发推送或调度、修改配置或数据库
>
> ## 实施进度（2026-08-10 本地）
>
> | 工作包 | 状态 | 证据摘要 |
> | --- | --- | --- |
> | WP0 | 完成（基线文档） | `docs/reference/wp0_frontend_baseline_fixtures/`；17 页矩阵、角色菜单、体积与 Node 决策已记录。真实浏览器人工截图基线未宣称完成。 |
> | WP1 | 完成 | `app/routers/menu.py` 新分组/文案/route_name/schema_version；生产过滤 `dev_only`；隐藏 oracle-status/system-logs；`navigation.js` 对齐；`menu_service` deprecated 桩；`tests/test_menu_api.py` 通过。 |
> | WP2 | 完成 | `frontend/` Vue3+Vite+TS+Router Hash+Pinia+Element Plus 按需；`/ui-next/` 产物；AppShell/守卫/API client；`npm run typecheck/test:unit/build` 通过。 |
> | WP3 | 完成 | 健康、运行总览、工作台、任务进度（只读 + 进度轮询离开即停）。 |
> | WP4 | 完成 | 质控记录、患者质控、告警记录、整改反馈（含确认 mutation，二次确认）。 |
> | WP5 | 完成（本地） | 用户权限、告警推送配置、系统配置、质控类型、定时任务、手动推送、Dify 调试；写操作含确认与 secret 留空保留语义。 |
> | WP5 加固 | 完成（2026-08-10） | 修复调度触发契约（`audit_run_mode` query，非 body.mode）；`mutation-contracts` 单测；手动推送 body 对齐 dry_run/replace_current；Playwright 扩至 31 pass；Dockerfile 去掉易失败的 `.npm-cache*` 通配 COPY。 |
> | 本地验收加固 | 完成（2026-08-10） | 全量 `pytest` 通过；`tests/test_frontend_menu_manifest_contract.py` 校验后端 catalog ↔ route-manifest；本地 uvicorn 冒烟：`/ui-next/` 200、legacy `/` 200、菜单 401、admin 登录后 schema_version=2、占位隐藏、分组≤6；`scripts/smoke_ui_next_local.py`。 |
> | WP6 | 未实施 / 阻塞中 | 见 020；阶段 A 后 `/ui-next/` 已刷新，完整四角色与 Relay 实发未通过。 |
> | WP7 | 未实施 | 禁止删除 legacy；禁止改 `UI_DEFAULT_ENTRY=ui-next` 直至单独批准。 |
> | 默认入口开关 | 本地已实现；**阶段 A 生产已部署 legacy**（2026-08-11） | 生产镜像含开关；当前 `UI_DEFAULT_ENTRY=legacy`；阶段 B 须单独批准。 |
>
> **本轮是否触碰生产：否。**

## 1. 总体裁定

建议采用“**Vue 3 模块化单体前端 + 可复用 App Shell + 路由/菜单/权限契约**”进行分阶段迁移，目标技术栈为：

- Vue 3 Single File Components（SFC）+ Composition API；
- Vite 离线可复现构建；
- TypeScript 严格模式；
- Vue Router，首期使用 Hash History，避免 FastAPI 静态挂载缺少 SPA fallback；
- Pinia 只管理会话、导航、全局任务等跨页面状态；
- Element Plus 继续作为基础组件库，采用按需引入；
- ECharts 只在需要图表的路由懒加载；
- Vitest + Vue Test Utils + Playwright 建立单元、组件和真实浏览器回归。

本方案**不建议**直接引入微前端、Nuxt/SSR、React 重写或低代码平台。当前系统是单仓库、同域 FastAPI API、院内离线部署的管理应用，模块化单体足以解决现有菜单混乱、全局状态膨胀、页面一次性加载和扩展困难问题；微前端会额外引入运行时集成、依赖重复、权限同步和发布编排成本。

实施方式必须是“**旧前端保留 + 新前端并行 canary + 逐页迁移 + 最后切换入口**”，禁止一次性推倒重写。

## 2. 目标与非目标

### 2.1 本次目标

1. 把当前 17 个菜单项按业务工作流重新分组，减少重复入口、占位入口和开发入口对普通用户的干扰。
2. 建立统一 App Shell，规范侧边栏、顶部栏、面包屑、页面标题、内容滚动和移动端抽屉。
3. 将页面从“全局 Vue 实例中的状态和方法集合”迁移为独立 feature module。
4. 建立稳定 URL、浏览器前进/后退、页面刷新恢复和路由级懒加载。
5. 统一筛选区、指标条、表格、详情抽屉、状态标签、空状态、错误状态和危险操作交互。
6. 保持现有 FastAPI、RBAC、Oracle/Vastbase、Dify、调度、日志、反馈和告警业务契约不变。
7. 为后续多数据源规则引擎、统计报表和新的质控工作台预留清晰扩展点。
8. 建立可离线构建、可自动测试、可灰度、可回滚的前端发布流程。

### 2.2 明确非目标

- 不在本计划中修改 Dify Workflow、提示词、结果契约或 `mr_text`/`mr_txt` 映射。
- 不修改 daily/discharge/manual/retry 的推送、幂等、调度锁和 supersede 语义。
- 不因界面迁移顺手改变配置保存、密码/Key 加密、部分更新或回滚语义。
- 不把前端菜单隐藏当作后端权限控制；所有敏感 API 仍必须由 FastAPI 鉴权授权。
- 不在首批把医生移动 H5 和独立日志详情页强行并入管理端 SPA。
- 不在未建立离线依赖供应和自动化回归前删除旧 `static/` 前端。

## 3. 已确认的当前事实

### 3.1 入口与部署

1. `app/main.py:212-214` 将整个 `static/` 目录以 `StaticFiles(..., html=True)` 挂载到 `/`，API 路由注册在静态挂载之前。
2. Dockerfile 直接 `COPY static/ ./static/`，当前没有 Node 构建阶段。
3. 仓库内没有 `package.json`、Vite 配置、TypeScript 配置或前端锁文件。
4. Vue、Element Plus、Axios、ECharts 和 dayjs 均以本地 vendor 全量脚本加载，不依赖公网 CDN；vendor JavaScript 原始体积合计约 2.35 MB，Element Plus CSS 原始体积约 353 KB。
5. `static/log_detail.html` 是独立入口，并已用 `body.log-detail-page #app` 的作用域覆盖修复全局 `#app` 滚动约束。首期迁移不得破坏该修复。

### 3.2 页面装载与状态

1. `static/index.html:151-183` 在应用挂载前声明 17 个 `data-template-src`，`static/scripts/app.js:53-76` 并行获取所有模板，任一模板失败会阻止整个主应用挂载。
2. 页面通过 `v-show="activeMenu==='...'"` 或少量 `v-if` 切换；不是正式路由，浏览器地址、前进后退、刷新恢复和深链接能力不足。
3. `static/scripts/app.js` 当前 1,345 行，单个 `createApp()` 同时持有认证、菜单、仪表盘、日志、反馈、推送、配置、调度、权限等跨域状态。
4. 业务脚本虽然已拆为模块，但通过 `...xxxMethods` 混入同一 Options API 实例；`config.js`、`push.js`、`audit_types.js` 分别已达到约 1,035、1,001、897 行。
5. 页面模板中仍有约 351 处内联 `style`，会增加视觉一致性、响应式修复和主题调整成本。
6. 当前全局 `#app` 使用 `height:100vh/100dvh` 和 `overflow:hidden`，主应用依赖 `.content` 作为滚动容器；独立页面若未加作用域覆盖，容易再次出现无法滚动。

### 3.3 菜单与权限

1. `app/routers/menu.py` 是当前 `/api/menu` 的实际菜单来源，后端目录包含 5 个组、17 个菜单和默认角色映射。
2. `static/scripts/navigation.js` 又维护 `FALLBACK_GROUPS`、`FALLBACK_MENU`、`SAFE_FALLBACK_MENU`，存在第二套名称、顺序和分组定义。
3. `app/services/menu_service.py` 还保留一套旧菜单和权限映射，仓库内没有调用方，内容已经与现役路由不一致。
4. 后端菜单项包含 `path`、`target`、`dev_only` 等字段，但当前客户端仍依赖 `activeMenu + tab` 映射；`path` 没有形成真实路由。
5. `debug` 被标记为 `dev_only=True`，但现役 `/api/menu` 组装过程没有基于环境过滤；管理员默认菜单会包含全部目录项。
6. `oracle-status` 和 `system-logs` 仍为占位页，却在管理员菜单中作为正式入口展示。
7. 当前菜单加载失败后会显示前端安全兜底菜单，而不是明确的“菜单权限加载失败”状态。
8. 角色菜单使用稳定的 `menu_id` 持久化。整改分组和文案时必须保留既有菜单 ID，否则会破坏 `RoleMenu` 分配。

### 3.4 已有基础不能回退

- 已有动态菜单、角色菜单分配、移动端抽屉、全局健康状态和推送任务指示器。
- 已有页面模板拆分、部分脚本模块化、语义色 token、表格横向滚动、响应式断点和 scoped page class。
- 已有日志筛选防抖、分页重置、详情页上一条/下一条、JSON 展开复制和错误展示。
- 已有静态前端回归脚本和多组页面级 pytest，但尚无真实浏览器自动化。
- 已有配置密钥“留空保留”、Relay 部分更新、推送危险操作确认等业务约束，迁移不得改变请求体和提交时机。

## 4. 问题裁定与优先级

### 4.1 P0：迁移前必须关闭

| 编号 | 问题 | 影响 | 整改要求 |
| --- | --- | --- | --- |
| FE-P0-01 | 菜单存在后端路由、前端 fallback、未使用旧 service 三套定义 | 文案、分组、角色和路径会继续漂移 | 确定后端菜单目录为业务授权单一来源；前端只保留编译期 route manifest；删除死代码前做全仓引用和测试 |
| FE-P0-02 | 菜单项与实际路由没有稳定契约 | 刷新、深链接、浏览器导航和新模块接入困难 | 建立 `menu_id -> route name -> component` 白名单映射，未知 ID fail-closed |
| FE-P0-03 | 开发菜单和占位菜单可进入正式导航 | 用户看到不可用/不应开放功能 | 生产服务端过滤 `dev_only`；未实现的 Oracle 状态、运行日志隐藏或完成后再开放 |
| FE-P0-04 | 新构建链尚不存在且生产为离线环境 | 直接引入 npm 会导致镜像无法复现 | 先通过锁文件、固定 Node、离线依赖或院内 registry 门禁，再允许进入新 SPA 实施 |
| FE-P0-05 | 缺少真实浏览器基线 | 迁移后无法证明没有交互回退 | 先完成旧页面 1366/768/390 基线、角色菜单矩阵和关键请求快照 |

### 4.2 P1：App Shell 与首批页面必须解决

| 编号 | 问题 | 整改要求 |
| --- | --- | --- |
| FE-P1-01 | 所有模板在登录前/启动时一次加载 | 按路由动态 import，只下载当前页面 chunk；模板失败只影响当前路由 |
| FE-P1-02 | 单一全局 Vue 状态和方法空间 | 拆为 layout、store、feature composable 和 page component；禁止新的 god store |
| FE-P1-03 | 标题和 tab 跳转依赖多个硬编码 map | 标题、分组、面包屑、权限和布局由 route meta 生成 |
| FE-P1-04 | 全局滚动约束易污染独立页 | 把视口锁定限制在 `.app-shell`，默认 `html/body/#app` 允许正常高度；独立页保留自己的滚动策略 |
| FE-P1-05 | 页面视觉结构不统一 | 建立 PageHeader、SummaryStrip、FilterBar、TableShell、DetailPanel 等基础组件 |
| FE-P1-06 | API 错误处理存在全局/页面重复提示风险 | 建立单一 typed API client 和标准 `ApiError`；401 全局处理，其余由调用页决定展示位置 |
| FE-P1-07 | 17 项菜单对不同角色的优先级相同 | 按角色和任务流分组，普通用户不展示配置/运维噪音 |

### 4.3 P2：迁移期间逐步完善

- 逐步消除内联样式和重复页面 CSS，迁入 token、基础组件和 feature scope。
- ECharts、JSON viewer、复杂编辑器按路由或组件懒加载。
- 增加键盘焦点、跳过导航、aria label、对比度和 `prefers-reduced-motion`。
- 建立前端 bundle 预算、请求数预算和视觉回归。
- 生成或维护 TypeScript API DTO，避免字段名和 nullable 语义靠人工记忆。
- 增加离开未保存表单的路由守卫，但不得改变后端保存和回滚语义。

## 5. 架构选择对比

| 方案 | 优点 | 缺点 | 裁定 |
| --- | --- | --- | --- |
| 继续当前无构建全局 Vue | 部署简单、无需 Node | 全局状态、模板一次加载、缺少类型/路由/组件边界，扩展成本继续上升 | 仅作为过渡和回滚版本 |
| Vue 3 + Vite + TypeScript 模块化单体 | 与现有 Vue/Element Plus 兼容；支持 SFC、路由懒加载、类型、测试和按需打包 | 需要引入可靠离线构建链 | **推荐目标架构** |
| React/Ant Design 全量重写 | 生态成熟 | 现有 Vue 页面和团队资产全部重写，双栈成本高 | 不采用 |
| Nuxt/SSR | 路由和工程化完整 | 内部系统无 SEO/SSR 收益，增加 Node 运行或预渲染复杂度 | 不采用 |
| 微前端/Module Federation | 可独立发布大型多团队模块 | 当前规模和团队边界不足，权限、依赖、ECharts/Element 重复加载更复杂 | 当前不采用，未来多团队独立发布时再评估 |
| 低代码平台替换 | 表单搭建快 | 医疗质控详情、复杂表格、证据展示和安全契约难以受控 | 不作为主架构 |

官方依据：Vue 官方建议 SFC 场景使用 Composition API 与 `<script setup>`，TypeScript 可为 props/emits/ref 提供类型约束；Vue Router 支持 route meta、导航守卫和动态 import 懒加载；Pinia 是 Vue 生态推荐的类型友好状态方案；Vite 通过 `vite build` 生成可静态部署产物；Element Plus 支持 Vite 下按需引入。实施时应以锁定版本的官方文档和兼容矩阵为准：

- <https://vuejs.org/guide/typescript/composition-api.html>
- <https://router.vuejs.org/guide/advanced/lazy-loading>
- <https://router.vuejs.org/guide/advanced/navigation-guards.html>
- <https://pinia.vuejs.org/introduction.html>
- <https://main.vite.dev/guide/static-deploy>
- <https://element-plus.org/en-US/guide/quickstart.html>

## 6. 目标架构

```text
FastAPI /api/*                     业务与安全唯一权威
      │
      ├── /api/users/me            会话与角色
      ├── /api/menu                可见 menu_id、分组、顺序、schema_version
      └── 现有业务 API              请求/响应语义保持不变
      │
Vue App Shell
      ├── Router                   URL、路由懒加载、meta、守卫
      ├── Pinia                    auth/navigation/task/preferences
      ├── API Client               鉴权、错误归一、取消请求、request-id
      ├── Design System            token + 基础组件 + Element Plus 适配
      └── Feature Modules
          ├── workbench            dashboard
          ├── quality              patient-qc, logs
          ├── closure              relay-alert, feedback
          ├── tasks                push, push-progress, scheduler
          ├── governance           audit-types, config, relay
          └── system               runtime, health, access, debug
```

### 6.1 核心边界

1. **后端菜单是授权目录权威**：返回当前用户允许看到的稳定 `menu_id`。
2. **前端 route manifest 是组件白名单权威**：服务器不能传任意组件路径让浏览器动态执行。
3. **最终菜单是二者交集**：后端允许但前端未知的 ID 不渲染并上报诊断；前端存在但后端未授权的路由不能进入。
4. **后端 API 权限仍是安全权威**：即使用户手工输入 URL，也必须由 API 返回 401/403。
5. **页面模块不得互相直接读取组件内部状态**：跨模块只通过稳定 store、typed API 或明确的 shared composable。
6. **移动 H5、日志独立页是单独 entry**：共享 token/formatters 可以，不能共享管理端全局布局状态。

## 7. 菜单信息架构整改

### 7.1 推荐菜单分组

菜单 ID 全部保留，只调整展示分组、顺序和必要文案。

| 新分组 | 菜单 ID | 推荐显示名 | 说明 |
| --- | --- | --- | --- |
| 工作台 | `dashboard` | 工作台 | 展示本人/本科室待办、异常和系统概览；不同角色显示不同卡片 |
| 质控中心 | `patient-qc` | 患者质控 | 病例维度主入口 |
| 质控中心 | `audit` | 质控记录 | 保留内部 ID；如业务坚持“推送日志”可维持旧文案 |
| 闭环管理 | `relay-alert-logs` | 告警记录 | 展示生成、发送、查看、反馈链路 |
| 闭环管理 | `feedback` | 整改反馈 | 以待处理/处理中/已关闭组织 |
| 任务中心 | `push` | 手动推送 | 只对具备执行权限的角色显示 |
| 任务中心 | `push-progress` | 任务进度 | 运行中和历史执行统一入口 |
| 任务中心 | `scheduler` | 定时任务 | 调度状态、执行历史和配置风险 |
| 规则与配置 | `audit-types` | 质控类型 | 审计类型、来源、Dify 和解析契约 |
| 规则与配置 | `config` | 系统配置 | 数据源、Dify、科室、推送等配置 |
| 规则与配置 | `relay` | 告警推送配置 | 最终文案需项目负责人确认，ID 不变 |
| 系统管理 | `config-runtime` | 运行总览 | 指向 config 的只读运行摘要 tab，后续可独立成 route |
| 系统管理 | `health` | 系统健康 | 只读组件健康和延迟 |
| 系统管理 | `access` | 用户与权限 | 用户、角色、权限、科室 |
| 系统管理 | `debug` | Dify 调试 | 仅非生产或明确受控管理员可见 |
| 暂时隐藏 | `oracle-status` | Oracle 连接 | 仍是占位页，完成真实功能后再开放 |
| 暂时隐藏 | `system-logs` | 运行日志 | 仍是占位页；只能在脱敏、鉴权、审计完成后开放 |

### 7.2 菜单交互规则

- 一级分组不超过 6 个；当前分组只展开一个，保留用户展开状态。
- 桌面侧边栏宽 232–248px，可折叠为 64px；折叠状态只保存 UI 偏好，不保存患者数据。
- 平板默认折叠；小于 900px 使用抽屉，选择菜单后自动关闭。
- 侧边栏顶部保留医院/系统标识；底部可放版本号和帮助入口，不放业务按钮。
- 顶部栏显示面包屑、页面标题、全局推送任务、健康状态和用户菜单。
- 不增加长期驻留的“多页签标签栏”，避免再次形成拥挤和状态滞留；使用浏览器历史、面包屑和页面内 tab。
- 可在二期增加 `Ctrl/Cmd + K` 菜单搜索，但搜索结果必须经过当前用户菜单交集过滤。
- 默认首页按角色设置：管理员/审核员进入工作台，科室负责人进入患者质控或待反馈，临床用户进入与其权限一致的首个菜单。最终角色落点需要业务确认。

### 7.3 菜单 API v2（向后兼容）

建议在现有响应上增量增加字段，不删除旧字段：

```json
{
  "schema_version": 2,
  "role": "auditor",
  "groups": [
    {"id": "quality", "label": "质控中心", "order": 20}
  ],
  "menu": [
    {
      "id": "patient-qc",
      "label": "患者质控",
      "group": "quality",
      "order": 10,
      "route_name": "quality-patients",
      "hidden": false
    }
  ]
}
```

约束：

1. `id` 是 RBAC 持久身份，禁止因改名而变化。
2. `route_name` 只能从后端枚举生成；客户端仍需与本地白名单取交集。
3. `dev_only`、未实现和环境限制必须由服务端先过滤，不能只靠 CSS 隐藏。
4. `/api/menu` 失败时新前端显示错误状态和“重新加载”，不显示未经本次会话确认的业务 fallback 菜单。
5. `/api/menu/all` 应采用与角色菜单目录相同的管理员权限守卫；若当前外部调用依赖匿名访问，必须先报告并迁移，不能直接破坏。
6. 删除 `app/services/menu_service.py` 前必须证明无运行时、测试、脚本和外部导入；若无法证明，先标记 deprecated 并加一致性测试。

## 8. App Shell 与响应式布局规范

### 8.1 页面骨架

```text
┌──────────────┬─────────────────────────────────────────────┐
│ Logo / 系统名 │ 面包屑 + 页面标题       任务/健康/用户       │ 56px
├──────────────┼─────────────────────────────────────────────┤
│              │ PageHeader：说明、刷新、主要动作             │
│  分组菜单     ├─────────────────────────────────────────────┤
│              │ SummaryStrip：3–6 个可解释指标              │
│  232–248px   ├─────────────────────────────────────────────┤
│              │ FilterBar：筛选 + 查询/重置                  │
│              ├─────────────────────────────────────────────┤
│              │ 主内容：表格/卡片 + 详情抽屉                 │
└──────────────┴─────────────────────────────────────────────┘
```

### 8.2 滚动和高度

- `html, body, #app` 只定义 `min-height: 100%`，不再全局锁死 overflow。
- 仅 `.app-shell` 使用 `height: 100dvh; overflow: hidden`。
- `.app-main` 作为唯一桌面主滚动容器；抽屉、弹窗和表格拥有自己的受控滚动。
- 路由切换记录并恢复列表页 scroll position；进入详情默认从顶部开始。
- `log_detail.html` 和移动 H5 使用独立 body class，保持自然文档滚动。
- 所有 sticky 元素必须声明所属滚动容器，禁止依赖偶然的 body 滚动。

### 8.3 断点

| 宽度 | 行为 |
| --- | --- |
| `>= 1440px` | 展开侧栏；内容最大宽度按页面类型控制，数据表可全宽 |
| `1280–1439px` | 展开或用户折叠侧栏；指标卡适当降列 |
| `900–1279px` | 默认折叠侧栏；筛选区允许两列/折行 |
| `< 900px` | 抽屉菜单；顶部栏简化；表格水平滚动；详情面板全屏 |
| `< 640px` | 单列筛选和卡片；主要动作固定底部时需避开安全区 |

### 8.4 页面密度

- 默认采用适合医疗后台的紧凑密度，不以大面积装饰卡片挤压信息。
- 每页只保留一个高强调主按钮；危险操作使用红色且与查询/刷新分离。
- 筛选默认展示 4–6 个高频字段，低频字段放“更多筛选”。
- 表格列按“身份 → 业务结论 → 状态 → 时间 → 操作”排列；次要列允许用户显隐，但不得隐藏合规必需字段。
- 长文本默认摘要，详情中展开；request/response 原文必须遵守脱敏和权限，不因新 JSON viewer 扩大展示。

## 9. 设计系统与共享组件

### 9.1 Token 分层

建议建立：

- primitive：颜色、字号、间距、圆角、阴影；
- semantic：`surface-page`、`text-muted`、`risk-high`、`status-success`；
- component：table header、filter bar、drawer、dialog；
- Element Plus bridge：把 semantic token 映射到 `--el-*`。

必须保留现役业务语义：

- 红：失败/高危/阻断；
- 橙：警告/中危/待处理；
- 绿：成功/低危/已闭环；
- 蓝：运行中/信息；
- 灰：未知/禁用/被覆盖。

不得只靠颜色表达风险和状态，必须同时有文案或图标。

### 9.2 首批基础组件

| 组件 | 职责 | 禁止事项 |
| --- | --- | --- |
| `AppShell` | 侧栏、顶部栏、主滚动区、移动抽屉 | 不读取具体业务列表状态 |
| `AppSidebar` | 菜单树、折叠、权限后菜单 | 不自行维护第二套菜单目录 |
| `PageHeader` | 标题、说明、面包屑、主要动作 | 不塞入页面筛选字段 |
| `SummaryStrip` | 3–6 个核心指标和状态 | 不用不可解释的纯装饰数字 |
| `FilterPanel` | 基础/更多筛选、查询、重置 | 不自动触发写操作 |
| `DataTableShell` | loading、empty、error、横向滚动、分页 | 不改变后端分页口径 |
| `StatusTag`/`RiskTag` | 统一状态与严重度映射 | 不接收未知组合后静默显示“正常” |
| `DetailDrawer` | 详情分区、锚点、关闭、移动端全屏 | 不在打开时重复调用写接口 |
| `AsyncButton` | loading、防重复提交、结果反馈 | 不替代后端幂等 |
| `ErrorState` | 稳定错误文案、request_id、重试 | 不向用户展示 SQL/驱动/密钥 |
| `JsonViewer` | 只读格式化、折叠、复制 | 不绕过脱敏，不默认展开正文 |
| `UnsavedChangesGuard` | 离开未保存页面前确认 | 不自动保存配置 |

### 9.3 组件使用门禁

- 业务组件不得直接修改全局 token。
- 页面 CSS 必须以 feature root 或 CSS Module 作用域化。
- 禁止新增内联 `style`，动态尺寸使用受控 prop/class 或 CSS variable。
- 共享组件只抽取至少两页已经稳定复用的交互；不要为“看起来通用”提前建复杂框架。
- Element Plus 二次封装必须薄，不复制其全部 props/events。

## 10. 路由、权限与会话

### 10.1 路由策略

首期使用 `createWebHashHistory()`：

- `/ui-next/#/workbench`
- `/ui-next/#/quality/patients`
- `/ui-next/#/quality/records`
- `/ui-next/#/closure/alerts`
- `/ui-next/#/tasks/progress`

这样无需立即修改 FastAPI 为任意前端路径提供 `index.html` fallback，适合与旧 `/` 页面并行 canary。待新前端稳定且确有干净 URL 需求，再单独设计 History 模式和后端 fallback，不能在首批同时切换。

### 10.2 Route Meta

每条路由至少定义：

```ts
interface MedAuditRouteMeta {
  menuId: string
  title: string
  group: 'workbench' | 'quality' | 'closure' | 'tasks' | 'governance' | 'system'
  requiresAuth: true
  permissions?: string[]
  layout: 'app' | 'standalone'
  risk: 'readonly' | 'business-write' | 'system-write'
  keepAlive?: boolean
}
```

- `risk` 用于测试和 UI 提示，不替代权限。
- 列表页可选择性 keep-alive；配置、调度、手动推送等写页面默认不 keep-alive，避免陈旧表单。
- 路由切换到写页面前不自动发起任何 mutation。
- 不把患者姓名、病历正文、request/response、密钥放入 URL、localStorage 或浏览器标题。

### 10.3 导航守卫

1. 未认证：进入登录页。
2. 会话存在：读取 `/api/users/me`，再读取 `/api/menu`。
3. 目标 `menuId` 不在可见菜单：显示 403 页面，不跳到可能暴露功能的 fallback。
4. 菜单 API 失败：显示“权限菜单加载失败 + 重试 + request_id”，不能显示默认管理员菜单。
5. 401：清会话并回登录；403：保留会话并显示无权限；5xx：页面错误状态。
6. 写页面有未保存变化：离开时二次确认。
7. 前端守卫通过后，实际 API 仍需后端授权。

### 10.4 会话存储

首轮迁移保持现役 token 语义，避免前端架构改造与认证协议改造绑在一起。若后续要从 localStorage 迁移到 HttpOnly Cookie，必须另立安全计划、处理 CSRF、登出和反向代理后再实施。

## 11. 状态、API 与数据契约

### 11.1 Pinia 使用边界

只建立以下全局 store：

- `authStore`：token、当前用户、恢复会话、登出；
- `navigationStore`：服务端菜单、菜单加载状态、侧栏偏好；
- `taskStore`：全局推送任务指示器和轮询生命周期；
- `healthStore`：顶部最小健康摘要；
- `preferenceStore`：非敏感 UI 偏好，如侧栏折叠和表格密度。

页面列表、筛选、分页、详情和编辑表单留在 feature composable 或页面组件内。禁止把所有页面状态再次集中到一个 store。

### 11.2 API Client

- 单一 Axios instance，`baseURL='/api'`，统一 timeout、Authorization 和 request-id 读取。
- 取消离开页面后的陈旧请求，避免旧结果覆盖新筛选。
- 定义标准 `ApiError { status, code, message, requestId, fieldErrors }`。
- 401 只由全局处理；页面不重复弹两次消息。
- 403、404、409、422、429、5xx 使用稳定中文用户文案，原始异常只进入服务端日志。
- 导出继续使用 blob 安全校验，并保持 `record_export_audit()` 后端要求。
- mutation 请求体必须与现役接口做 fixture 对比；迁移不得增加未定义字段或把空字符串覆盖已有秘密。

### 11.3 TypeScript 契约

首批手工定义关键 DTO，并标注历史 `NULL`：PushLog、AuditDimensionResult、Feedback、RelayAlert、SchedulerExecution、MenuResponse。后续可从**本地受控 OpenAPI 快照**生成类型，但禁止构建时访问生产 `/openapi.json`。

必须显式覆盖：

- `reviewed_flag`、`manual_override`、`skip_reason`；
- `audit_type_code`、`audit_run_mode`、`source_record_key`；
- `replace_current`、`superseded_by`、current-result 字段；
- severity/status 允许值与 unknown/NULL 兼容；
- Oracle 空字符串等价 NULL 的展示；
- 配置 `has_secret + masked value + empty means preserve` 语义。

## 12. 各页面整改蓝图

| 页面 | 目标布局 | 首批重点 | 不得改变 |
| --- | --- | --- | --- |
| 工作台 | 角色化 KPI + 待办 + 链路状态 + 趋势 | 减少装饰，突出待处理、高危、失败任务；ECharts 懒加载 | 统计口径和科室权限 |
| 患者质控 | 筛选 + 主表 + 右侧选中摘要/详情抽屉 | 当前结果、风险、待反馈清晰；移动端全屏详情 | current/superseded 过滤和患者可见性 |
| 质控记录 | 紧凑指标 + 高级筛选 + 日志表 + 独立详情 | 成功/失败/跳过/解析失败分开；保留上一条下一条 | 导出字段、历史 NULL、详情脱敏 |
| 告警记录 | 链路指标 + 告警表 + 发送/查看/反馈时间线 | 失败原因和重试状态可见 | 不自动重发告警 |
| 整改反馈 | 待办指标 + 状态筛选 + 详情时间线 + 固定操作栏 | AI 问题、医生反馈、整改动作分区 | 科室权限、suppress 语义 |
| 手动推送 | 三步式：范围 → 候选预览 → 执行确认 | dry-run/历史重跑/普通推送明确分流；危险动作隔离 | 请求结构、候选 hash、Dify 调用和幂等 |
| 任务进度 | 运行中优先 + 历史列表 + 失败详情 | 全院任务继续保留；失败可跳日志排查 | 不取消用户要求保留的全院能力 |
| 定时任务 | 模式状态 + 配置风险 + 执行历史 | daily/discharge/legacy 明确，立即触发置于危险区 | 双任务锁、cron 和 audit type 语义 |
| 质控类型 | 左列表 + 中编辑 + 右预览/风险 | 来源、builder、Dify、JSONPath 分层；规则扩展预留 tab | `mr_text`/`mr_txt`、SQL/JSONPath 校验和秘密脱敏 |
| 系统配置 | 配置域导航 + 表单 + sticky 保存区 | dirty 状态、保存影响范围、密钥提示统一 | 部分更新、加密和 base_url 保护 |
| 告警推送配置 | 状态摘要 + 规则表 + 受控测试区 | 文案从“企业微信”与“前置机”混用中收口 | 不实际发送，除非单独批准 |
| 运行总览 | 只读运行模式、配置风险和解析结果 | 从系统配置写表单中视觉分离 | resolver 口径 |
| 系统健康 | 组件卡 + 最近延迟 + 只读诊断 | liveness/readiness 区分 | 不泄露匿名详细诊断 |
| 用户与权限 | 用户/角色/菜单/权限/科室 | 菜单分配展示新分组；危险操作确认 | RoleMenu ID、RBAC 和科室边界 |
| Dify 调试 | 非生产/受控入口，结构化输入与脱敏输出 | `dev_only` 真正生效 | 不读取/回填明文 Key，不默认真实调用 |
| Oracle 状态 | 暂隐藏 | 完成受控只读 API 后再设计 | 不直接在浏览器连接 Oracle |
| 运行日志 | 暂隐藏 | 仅展示脱敏摘要、权限和导出审计后再开放 | 不展示病历正文、密钥、request/response |

## 13. 推荐目录与文件变更

### 13.1 新前端源码

```text
frontend/
├── package.json
├── package-lock.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.ts
│   ├── App.vue
│   ├── api/
│   │   ├── client.ts
│   │   ├── errors.ts
│   │   ├── types.ts
│   │   └── endpoints/
│   ├── router/
│   │   ├── index.ts
│   │   ├── route-manifest.ts
│   │   └── guards.ts
│   ├── stores/
│   ├── layouts/
│   │   └── AppShell.vue
│   ├── components/
│   │   ├── base/
│   │   ├── data/
│   │   └── feedback/
│   ├── features/
│   │   ├── workbench/
│   │   ├── quality/
│   │   ├── closure/
│   │   ├── tasks/
│   │   ├── governance/
│   │   └── system/
│   ├── styles/
│   │   ├── tokens.css
│   │   ├── global.css
│   │   └── element-overrides.css
│   └── utils/
├── tests/
│   ├── unit/
│   ├── component/
│   └── e2e/
└── playwright.config.ts
```

### 13.2 既有文件处理

| 文件 | 处理 |
| --- | --- |
| `app/routers/menu.py` | 作为菜单单一业务目录，增加 schema_version/route_name 和环境过滤；保持旧字段兼容 |
| `app/services/menu_service.py` | 经引用/外部依赖门禁后删除或 deprecated；不得继续维护第二份目录 |
| `static/scripts/navigation.js` | 旧前端过渡期保留；新前端不复制整份 fallback 目录 |
| `static/scripts/app.js` | 只修过渡期缺陷，不在其中继续新增新业务模块 |
| `static/index.html` | 作为 legacy 入口保留到新前端完成灰度 |
| `static/log_detail.html` | 首批保持独立；共享 token 的迁移另做兼容验证 |
| `static/templates/mobile/qc_detail.html` | 保持 H5 契约和现役路由，首批不迁移 |
| `Dockerfile` | 通过单独工作包增加固定 Node 的 multi-stage build；离线构建通过后才合并 |
| `scripts/frontend_regression_check.py` | 过渡期继续验证 legacy；新增 build/route/manifest 检查，最终不再依赖手工 cache version 字符串 |

### 13.3 构建输出

- canary 阶段 Vite `base` 使用 `/ui-next/`，输出到构建镜像内的 `/app/static/ui-next/`。
- 使用 Hash History，因此 `/ui-next/#/...` 由同一静态 index 处理。
- 旧 `/` 入口和 vendor 文件继续存在，形成可立即切回的 legacy 版本。
- 生成产物不手工改、不以 `docker commit` 作为常规发布；必须由锁文件和 Dockerfile 重建。

## 14. 分阶段实施工作包

### WP0：冻结基线与决策门禁（只读）

交付：

1. 旧系统 17 页面、4 角色的菜单矩阵；
2. 1366x768、768x1024、390x844 截图和 Console/Network 基线；
3. 页面 → API → permission → mutation 风险矩阵；
4. `/api/menu`、关键列表、关键保存请求的脱敏 fixture；
5. Node/包管理器/registry/离线缓存/浏览器最低版本决策；
6. 当前 vendor 体积、模板请求数、首屏时间基线。

停止点：无法完成旧系统登录、菜单角色核验或离线构建决策时，不得开始新 SPA。

### WP1：旧菜单最小收口（低风险，可独立发布）

1. 统一后端 `MENU_GROUPS/MENU_CATALOG` 的新分组和顺序，保留 menu ID。
2. `debug` 在生产环境服务端过滤。
3. `oracle-status`、`system-logs` 未实现前隐藏。
4. 更新 legacy fallback 与后端一致性测试，避免过渡期漂移。
5. 标记或删除无引用 `app/services/menu_service.py`。
6. 为 `/api/menu` 和角色菜单分配增加聚焦测试。

验收：现役 UI 不改业务页面即可先获得清晰菜单；所有角色仍只能看到获授权菜单。

### WP2：新工程和 App Shell 空壳

1. 建立 `frontend/`、锁文件、严格 TypeScript、ESLint（若采用）和 Vitest。
2. 配置 Vite `base=/ui-next/`、Hash Router、按需 Element Plus。
3. 实现登录、恢复会话、菜单加载、403/404/500、AppShell、移动抽屉。
4. 建立 route manifest 与 `/api/menu` 交集；未知 ID fail-closed。
5. 实现 token、PageHeader、ErrorState、Skeleton、EmptyState。
6. Docker 本地/离线 multi-stage build，输出 `/ui-next/`。

验收：只包含空白 route 页面，不接写操作；旧 `/` 完全不变。

### WP3：只读 canary 页面

顺序：

1. 系统健康；
2. 运行总览；
3. 工作台；
4. 任务进度。

理由：这些页面以只读查询为主，适合先验证认证、菜单、API client、图表、表格和布局。

每页必须完成 API fixture、组件测试、三分辨率 Playwright 和旧/新字段对照，再进入下一页。

### WP4：质控查询与闭环页面

顺序：

1. 质控记录和独立日志详情跳转；
2. 患者质控；
3. 告警记录；
4. 整改反馈只读能力；
5. 反馈 mutation 在单独子批次启用。

停止点：current-result、superseded、severity/status、科室权限或导出字段任何一项对照不一致，停止切换该页。

### WP5：高风险写页面

顺序：

1. 用户与权限；
2. 告警推送配置；
3. 系统配置；
4. 质控类型；
5. 定时任务；
6. 手动推送；
7. Dify 调试（仅受控环境）。

每一页拆成“只读展示迁移”和“写操作启用”两个提交/发布。写操作启用前必须对比旧/新 request body、空值、秘密保留、确认弹窗、重复点击和 409/422 处理。

### WP6：新入口灰度

1. 管理员和测试账号通过 `/ui-next/` 并行使用；旧 `/` 仍为默认。
2. 至少连续 7 个业务日比较 API 错误率、前端异常、页面加载和用户反馈。
3. 按角色扩大；高风险写页面需单独开关，不因只读页面通过而自动开放。
4. 业务负责人签字后，新前端才可成为默认入口。

### WP7：默认切换与 legacy 退役

1. 首次默认切换的镜像同时保留 `/legacy/` 回退入口。
2. 连续两个发布周期无阻断回退后，才提出删除 legacy 源码的独立计划。
3. 删除前将仍需保留的 `log_detail`、H5、formatters、样式和测试迁入明确位置。
4. 同步更新 `AGENTS.md`、`CLAUDE.md`、`ARCHITECTURE.md`、Docker/部署文档和 `docs/INDEX.md`。

## 15. 必须补充的测试

### 15.1 单元测试

- 后端菜单目录 ID 唯一、group 存在、order 稳定、role 引用有效。
- 生产环境不返回 `dev_only`；占位功能不返回。
- 前端 route manifest 的 menuId 唯一、每项都有 lazy component 和 meta。
- 服务端菜单与本地 route manifest 取交集；未知项、重复项和非法 route fail-closed。
- status/severity/NULL/unknown 格式化覆盖现役历史数据。
- API error 的 401/403/409/422/429/5xx 分支。
- 配置 secret placeholder、空值保留和 base_url 保护。
- 路由离开未保存表单的守卫。

### 15.2 组件测试

- AppSidebar 展开、折叠、单组展开、移动抽屉关闭。
- PageHeader/面包屑来自 route meta。
- FilterPanel 查询、重置后分页回 1、防抖取消旧请求。
- DataTableShell loading/empty/error/null/长文本/横向滚动。
- AsyncButton 防重复提交，但不吞后端错误。
- DetailDrawer 桌面/移动布局、焦点陷阱和 Esc 关闭。
- 风险标签不只靠颜色，非法 severity/status 不显示为正常。

### 15.3 Playwright 浏览器回归

角色至少覆盖 admin、dept_manager、auditor、clinician：

1. 登录、会话恢复、登出和 401；
2. 各角色菜单、直接输入未授权 URL 的 403；
3. 浏览器前进/后退、刷新当前路由、书签打开；
4. 1366x768、768x1024、390x844；
5. 菜单抽屉、筛选、分页、详情、复制、导出按钮；
6. Element Plus dialog/drawer/popper 层级；
7. 只读页面真实本地 API；写页面默认用 mock/测试库，不连接生产；
8. 动态内容截图必须遮罩患者标识和时间，不把病历正文写入测试产物。

### 15.4 旧新契约对照

对每个迁移页面记录：

- 请求 URL、method、query/body；
- 认证和权限；
- response 字段与 NULL；
- 页面统计口径；
- mutation 二次确认；
- 成功/失败提示；
- 导出字段和审计；
- 是否产生轮询、是否会重复调用。

任何写请求不一致都视为阻断，而不是“前端优化差异”。

### 15.5 统一验证命令（目标态）

```powershell
python -m pytest
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python scripts/frontend_regression_check.py
Get-ChildItem static/scripts -Recurse -Filter *.js | ForEach-Object { node --check $_.FullName }

Set-Location frontend
npm ci --offline
npm run typecheck
npm run test:unit
npm run build
npm run test:e2e
```

若院内环境暂时无法 `npm ci --offline`，WP2 必须停止，不得临时从公网下载后宣称可生产复现。

## 16. 性能、可访问性与安全门禁

### 16.1 性能

- 首屏不再获取全部 17 个页面模板。
- 各 route 使用动态 import；ECharts 只进入图表页面时加载。
- 建立构建报告：initial chunk、route chunk、CSS、资源请求数。
- 目标初始 JS gzip 不超过 450 KB；若因 Element Plus/兼容插件超出，至少比现役 gzip 基线降低 30%，并记录原因。
- 单 route chunk gzip 建议不超过 250 KB；大型 JSON viewer/ECharts 单独 chunk。
- 同一筛选的陈旧请求可取消；轮询在路由离开和组件卸载后停止。
- 不用无限 keep-alive 缓存患者详情或大型列表。

### 16.2 可访问性

- 提供“跳到主内容”；键盘可访问菜单、弹窗、抽屉和操作菜单。
- 焦点在路由切换后移动到页面标题；弹窗关闭后回到触发按钮。
- 图标按钮有 `aria-label`，状态同时有文字。
- 尊重 `prefers-reduced-motion`；运行中脉冲可减弱/关闭。
- 关键文本和状态对比度达到 WCAG AA 的实际检查门槛。

### 16.3 医疗数据与前端安全

- localStorage/sessionStorage 只允许 token 现役兼容和非敏感 UI 偏好；不得保存患者姓名、ID、病历、Dify request/response、配置秘密。
- Console、前端错误上报和 Playwright trace 不得包含病历正文、密钥、request_json 或 response_json。
- JSON viewer、复制、导出和详情都遵守后端脱敏与权限。
- 前端不能拼接可配置 SQL；SQL 只作为受控配置文本传给现役后端校验。
- 依赖版本和 lockfile 固定，构建生成 SBOM/依赖审计报告；依赖升级另设窗口。
- CSP/HttpOnly Cookie 等安全增强需单独设计，不能在 UI 迁移中静默改变认证协议。

## 17. 生产发布、监控与回滚

### 17.1 发布前置条件

1. `npm ci --offline` 和 Docker multi-stage build 在隔离环境可重复成功。
2. 旧前端完整基线、角色矩阵和新前端测试全部完成。
3. 后端菜单 schema 兼容旧客户端。
4. 新前端未修改业务数据库 schema；如其他并行工作涉及 DB，必须拆分镜像和变更窗口。
5. 生产镜像可由 Git commit/tag 重建，禁止把热复制或 `docker commit` 作为正式发布唯一来源。
6. 项目负责人对菜单文案、角色默认首页和高风险页面灰度范围签字。

### 17.2 Canary

- 默认入口仍是 `/`，新入口为 `/ui-next/`。
- 首轮只允许管理员和指定测试账号访问新入口；不触发真实 Dify、推送、调度或配置保存。
- 只读页面通过后，逐个批准 mutation 页面。
- 连续观察：前端 JS 错误、API 401/403/409/422/5xx、页面加载失败、重复请求、用户操作路径、Console 泄露。

### 17.3 回滚

- 页面级：route feature flag 关闭新页面，回旧页面。
- 入口级：恢复默认 `/` legacy，不变更数据库和配置。
- 镜像级：切回上一可重建镜像 tag；挂载的 `data/config/logs` 不回滚、不覆盖。
- 菜单级：恢复变更前 `MENU_GROUPS/MENU_CATALOG` 快照，但保持 RoleMenu ID 不变。
- 回滚后核查登录、菜单、健康、日志查询和旧前端静态资源，不触发业务任务。

## 18. 强制停止点

出现以下任一项必须停止并报告：

1. 无法证明 menu ID 与生产 RoleMenu 分配兼容；
2. 新旧请求体、保存语义、secret placeholder 或调度参数不一致；
3. 菜单隐藏被当作唯一权限控制；
4. 需要联网下载依赖才能构建生产镜像；
5. 新前端 Console/trace/错误上报出现患者标识、病历正文、密钥或原始 Dify 请求响应；
6. Hash Router 与既有代理、H5、日志详情路由发生冲突；
7. 任一路由切换产生额外 Dify、推送、调度、告警或配置写请求；
8. current/superseded、skip、reviewed、manual_override 等结果口径回退；
9. 三分辨率真实浏览器回归未完成；
10. 未取得生产发布或 mutation 灰度的人工批准。

## 19. 最终验收指标

- [ ] 管理端一级分组不超过 6 个，占位页和开发页不在生产菜单出现。
- [ ] 后端业务菜单目录只有一份；前端只有 route manifest，不再复制业务授权目录。
- [ ] 所有现役 menu ID 与 RoleMenu 分配兼容。
- [ ] 页面拥有稳定 URL，刷新和浏览器前进/后退正常。
- [ ] 首屏不请求未访问页面模板，单页加载失败不导致整个系统白屏。
- [ ] 全局 store 只包含跨页面状态，页面状态不再集中到单一 app 实例。
- [ ] 统一 AppShell、PageHeader、FilterPanel、TableShell、DetailDrawer 和状态标签。
- [ ] 1366x768、768x1024、390x844 浏览器回归通过。
- [ ] admin/dept_manager/auditor/clinician 菜单和直接 URL 权限通过。
- [ ] 旧新 API 请求、响应、统计、导出和 mutation 契约一致。
- [ ] 配置空秘密保留、Relay 部分更新、手动推送和调度危险确认无回退。
- [ ] 轮询在离开页面后停止，无重复请求和内存泄漏。
- [ ] 日志、错误、trace、截图不含敏感正文或秘密。
- [ ] 离线构建、锁文件、镜像 tag、canary 和回滚演练完成。
- [ ] 新前端成为默认入口后连续两个发布周期无阻断问题，才允许提出 legacy 删除。

## 20. 建议给实施 AI 的执行提示词

```text
你是一名资深 Vue 3 / TypeScript / FastAPI 医疗系统工程师。请在仓库
F:\python\前后端代码\ai_mrzk 中，严格依据
docs/ACTIVE/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md
分阶段实施前端整改。

开始前完整阅读：
- AGENTS.md
- docs/INDEX.md
- docs/reference/101_FEATURE_BASELINE.md
- docs/skills/med-audit-codex.md
- docs/ACTIVE/001_PENDING_WORK_EXECUTION_PLAN.md 的前端和统一验证章节
- docs/reference/116_SYSTEM_FUNCTION_UI_PUSH_REVIEW_20260714.md 的前端结论
- docs/archive/2026-06-ui/20260624/浏览器回归复核执行计划.md（已归档）
- 017 本计划

执行规则：
1. 先执行 WP0，只读建立旧系统菜单、页面、API、权限、浏览器和性能基线；未完成门禁不得开始 WP1/WP2。
2. 每次只实施一个工作包；完成聚焦测试和交付报告后停止，等待人工批准下一包。
3. 保留 menu ID、RoleMenu、API、配置保存、秘密留空保留、Dify、调度、幂等、current/superseded、日志导出和科室权限语义。
4. 新前端使用 /ui-next/ 与旧 / 并行；禁止一次性替换或删除 static legacy。
5. 菜单以 app/routers/menu.py 为业务权威，前端 route manifest 为组件白名单；两者取交集，未知项 fail-closed。
6. 生产离线构建必须 npm ci --offline 可复现；失败就停止，不得临时联网绕过。
7. 只读页面先迁移，配置、权限、审计类型、调度、手动推送和 Dify 调试最后迁移，展示与写操作分批启用。
8. 不连接或写入生产，不调用 Dify，不触发推送/调度/告警，不保存配置，除非用户对具体动作另行明确批准。
9. 不输出患者标识、病历正文、密钥、request_json 或 response_json；测试截图和 trace 也必须脱敏。
10. 修改任意 docs/**/*.md 时同步更新 docs/INDEX.md。

每个工作包最终报告：
- 工作包与目标
- 修改文件
- 行为变化与保持不变的契约
- 菜单/权限/API 对照
- 单元、组件、Playwright、Python 回归结果
- 离线构建结果和 bundle 报告
- 未完成项、停止点、生产前置条件
- 回滚方式
- 是否触碰生产（未明确批准必须回答“否”）
```

## 21. 需要项目负责人确认的三项产品决策

这些决策不阻塞 WP0，只阻塞对应 UI 正式定稿：

1. `audit` 对用户显示为“推送日志”还是“质控记录”；建议“质控记录”，详情保留推送技术字段。
2. `relay` 显示为“企业微信推送配置”“前置机配置”还是“告警推送配置”；建议“告警推送配置”。
3. dept_manager、auditor、clinician 登录后的默认首页；建议分别为患者质控、工作台、整改反馈/其首个授权菜单。

除以上文案和默认落点外，技术路线、menu ID 保持、占位页隐藏、生产 `dev_only` 过滤、旧新并行 canary 和高风险页面最后迁移应作为硬性方案执行。

## 22. WP6 生产 canary 前置清单（本轮仅输出，不实施）

1. 项目负责人确认菜单文案（质控记录 / 告警推送配置）与角色默认首页。
2. 隔离环境 `npm ci --offline`（或交付 `.npm-cache`）+ Docker multi-stage 重建成功，镜像可 tag。
3. 本地/预发：`/ui-next/` 与 `/` 并行；管理员测试账号登录、四角色菜单、403 深链、三分辨率回归签字。
4. 高风险写页单独开关或人工限定测试账号；禁止 canary 期间默认真实 Dify/推送/调度。
5. 监控：前端 JS 错误、API 4xx/5xx、重复请求、Console 敏感信息抽检。
6. 回滚演练：切回 `/` legacy 且不改 DB/配置。
7. 连续 ≥7 业务日观察后再扩大角色范围。

## 23. 部署与回滚清单（WP6 前准备）

| 动作 | 说明 |
| --- | --- |
| 构建 | `frontend`: `npm ci` → `npm run build:docker`；镜像 multi-stage 复制 `dist` → `/app/static/ui-next/` |
| 发布 | 新镜像同时含 legacy `/` 与 canary `/ui-next/`；不改默认入口 |
| 验证 | 健康检查、登录、菜单、打开 `/ui-next/#/system/health`；旧首页仍可用 |
| 回滚入口 | 用户改用 `/`；或镜像回退上一 tag |
| 回滚菜单 | 恢复 `MENU_GROUPS/MENU_CATALOG` 快照，**保持 menu ID** |
| 禁止 | `docker commit` 作为正式发布；删除 `static/` legacy；未批准生产 mutation |
