# 019 旧界面能力迁移矩阵与 UI Next Figma 设计清单

> 日期：2026-08-11（Asia/Shanghai）
> 状态：**迁移方案与本地设计已获批准；Figma 正式画布标记为“用户取消，不再实施”（既有 fileKey 仅保留，不删除 design 资产）；患者汇总导出已改为“当前筛选全部结果”；“山东省第二人民医院 · AI病历质控系统”UI Next 首轮功能迁移已由 Luna 本地实现并通过自动化/mock 验收；尚未生产部署、切换默认入口或执行真实业务写操作**
> 范围：legacy `static/` → Vue 3 `frontend/` 管理端能力迁移；本地 Figma 文件规划
> 依据：`017`、`018`、`frontend/src/router/route-manifest.ts`、`static/templates/pages/`、`static/scripts/modules/`、`frontend/src/features/`、现役 FastAPI 路由
> 执行约定：主 AI 负责规划、契约复核与验收；Luna 负责获批后的实现；涉及 Figma 时必须先获本文件复核批准。

---

## 0. 结论与批准边界

新界面的架构和视觉方向优于 legacy，应继续沿用 Vue 3、Hash Router、App Shell、route manifest、基础组件和新菜单信息架构，不推倒重做。当前主要问题是“15 个路由均有页面，但部分页面只有基础功能”，不能用页面存在证明迁移完成。

迁移原则不是照搬 legacy，而是逐项裁定：

| 裁定 | 含义 |
| --- | --- |
| 保留 | 业务必要且交互已合理，按契约迁移 |
| 重组 | 能力保留，重做信息层次或流程 |
| 合并 | 多个重复入口合为一个权威入口 |
| 独立保留 | 不并入管理端 App Shell，保持独立路由和发布边界 |
| 淘汰/暂缓 | 占位、重复、无调用或尚未满足安全门禁 |

优先级：

- **P0**：业务闭环、写操作契约、权限或安全阻断；正式灰度前必须完成。
- **P1**：核心效率、诊断和信息完整性；首轮设计应覆盖。
- **P2**：一致性、可访问性和维护性优化。
- **P3**：占位或低收益能力，暂缓。

当前仍禁止：未经单独批准启用生产 `/ui-next/`、调用 Dify、触发推送/调度/告警、修改生产配置或数据库、同步覆盖 legacy 静态入口或删除 legacy。Figma 正式画布已被用户取消、不再实施；本地 `design/` 资产与既有 fileKey 仅作历史参考，不得据此重新发起正式画布实施。

---

## 1. 页面级迁移总表

| menu_id / 独立入口 | legacy | UI Next | 当前完成度 | 总裁定 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| `dashboard` | 工作台、统计、健康、告警、调度摘要 | `WorkbenchPage.vue` | 部分完成 | 重组 | P1 |
| `patient-qc` | 患者列表、详情、证据、反馈、导出 | `PatientQcPage.vue` | 部分完成 | 重组 | P0 |
| `audit` | 日志列表、统计、详情、标记、重推、报告、导出 | `AuditRecordsPage.vue` | 部分完成 | 重组 | P0 |
| `relay-alert-logs` | 告警列表、摘要、详情、重试 | `AlertLogsPage.vue` | 部分完成 | 重组为闭环时间线 | P0 |
| `feedback` | 列表、看板、详情、确认/关闭、删除、导出 | `FeedbackPage.vue` | 大部分完成 | 重组 | P0 |
| `push` | 普通推送、匹配诊断、节点池摘要、历史重跑 | `ManualPushPage.vue` | 部分完成 | 重组为步骤流 | P0 |
| `push-progress` | 最新任务、轮询、调度历史 | `PushProgressPage.vue` | 部分完成 | 与任务历史重组 | P1 |
| `scheduler` | 双调度、配置、历史、完整性、运行告警 | `SchedulerPage.vue` | 大部分完成，本地已补双锁诊断 | 重组 | P0 |
| `audit-types` | 完整 CRUD、可视化 source、测试、运行告警 | `AuditTypesPage.vue` | 明显缺失 | 向导式重做 | P0 |
| `config` | 数据源、Oracle/PG/Vastbase、Dify、通知、隐私、科室等 | `ConfigPage.vue` | 部分完成 | 分区重组 | P0 |
| `relay` | Receiver Rules、人员搜索、接收人预览、护士长测试 | `RelayConfigPage.vue` | 明显缺失 | 独立告警推送配置中心 | P0 |
| `config-runtime` | 配置页内运行摘要 | `RuntimeSummaryPage.vue` | 基本完成 | 合并为唯一只读入口 | P1 |
| `health` | 组件健康和单项探测 | `HealthPage.vue` | 基本完成 | 保留 | P1 |
| `access` | 用户/角色/权限/科室完整 CRUD 与分配 | `AccessPage.vue` | 明显缺失 | 重组 | P0 |
| `debug` | Dify 直接调试 | `DebugPage.vue` | 基本完成 | dev_only 独立保留 | P1 |
| `oracle-status` | 占位 | 隐藏 | 符合预期 | 淘汰/暂缓 | P3 |
| `system-logs` | 占位 | 隐藏 | 符合预期 | 淘汰/暂缓 | P3 |
| `/mobile/qc/*` | 医生 H5 详情、查看、反馈、token | 未并入 SPA | 独立链路存在 | **独立保留** | P0 |
| `/log_detail.html` | 深链接日志详情、打印 | SPA 有 Drawer，但独立页仍在 | 部分复用 | **独立保留** | P1 |
| `/report/*` | token 化报告和打印 | SPA 打开独立报告 | 已接线 | **独立保留** | P1 |

---

## 2. 完整旧新功能迁移矩阵

### 2.1 工作台

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 今日 KPI | `/stats/summary`、`today`、`/logs` | 已有 | 保留并简化 | 口径须与列表一致 | P1 |
| 趋势/严重度 | `/stats/daily`、`severity` | 已有 | 保留 | 空数据、错误和窄屏降级 | P1 |
| 科室/患者异常排行 | `/stats/anomaly-top` | 部分已有 | 重组 | 点击后把科室/患者筛选带入目标页 | P1 |
| 维度统计 | `/stats/dimensions` | 未完整呈现 | 合并到质控分析抽屉或钻取页 | 不在首页堆图 | P2 |
| 健康状态 | `/health` | 已有 | 保留 | 与系统健康页联动 | P1 |
| 调度完整性 | `/scheduler/status` | 仅摘要 | 重组 | 显示 incomplete/stale 并钻取调度页 | P0 |
| 高危/待反馈/Relay | 日志、反馈、Relay 摘要 | 已有基础 | 重组 | 所有卡片携带筛选条件；遵守科室权限 | P0 |

### 2.2 患者质控

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 患者聚合列表 | `/patient-qc/patients` | 已有 | 保留 | 对齐全部筛选、聚合字段、NULL | P0 |
| 科室筛选 | `/logs/dept-options` | 已有 | 保留 | 在院/出院科室不可混用 | P0 |
| 患者详情 | `/patient-qc/patient-detail` | 已有 Drawer | 重组 | 统一患者摘要、维度、证据、版本、反馈 | P0 |
| 病程/护理原文 | legacy 详情区 | 未完整显式分区 | 重组为 EvidencePanel | 保留换行、默认折叠、权限与脱敏 | P0 |
| 证据与版本链 | 维度、推送记录、当前结果 | 部分已有 | 重组 | 明确 current/superseded、历史版本 | P0 |
| 快捷整改 | `/patient-qc/feedback/quick-action` | 已有 | 保留 | 二次确认、错误回滚、权限 | P0 |
| 患者汇总导出 | `/patient-qc/export/patient-visit-summary` | 已有 | 保留 | **当前筛选全部结果**（不限当前页；无筛选=全部匹配患者）；与列表同源筛选 + `TEMP_PAT_VISIT_LIST` 交集；`ExportAuditLog.scope=filtered_all_pages` | P0 |

### 2.3 质控记录、统计与报告

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 日志筛选/分页 | `/logs`、`filters/options` | 已有 | 保留 | 对齐日期、推送时间、患者、两类科室、类型等 | P0 |
| 跳过漏斗 | `/logs/skip-reasons/stats` | 已有 | 保留 | 标签中文化、点击筛选 | P1 |
| 统计 Tab | `/stats/*` | 未等价迁移 | 合并到工作台/分析视图 | 不恢复旧页密集多图布局 | P1 |
| 日志详情 | `/logs/{id}` | 已有 Drawer | 重组 | 结论、维度、病程、护理、错误、技术字段分层 | P0 |
| 上一条/下一条 | legacy 详情 | 已有 | 保留 | 翻页边界、关闭清理状态 | P1 |
| 人工标记 | `GET/POST /logs/{id}/marker` | 缺失 | 保留 | `reviewed_flag/manual_override/skip_reason`，管理员授权 | P0 |
| 单/批量重推 | `/logs/{id}/retry`、`/push/retry` | 已有 | 保留 | 幂等、确认、结果反馈 | P0 |
| 单/批量删除 | `/logs/{id}`、`bulk/delete` | 已有 | 保留 | 明确关联清理、二次确认、角色限制 | P0 |
| Relay 手工派发 | `/relay/dispatch` | 缺失 | 移至告警详情或日志更多菜单 | 禁止默认显示；需发送权限 | P1 |
| CSV 导出 | `/logs/export/csv` | 已有 | 保留 | 全字段、历史 NULL、导出审计 | P1 |
| 报告/打印 | `/report/{id}/data`、`print-token` | 部分已有 | 独立报告保留 | 短期 token、深链接、打印样式 | P1 |
| 独立 log_detail | `static/log_detail.html` | 未替代 | 独立保留 | 滚动修复、打印、深链接继续可用 | P1 |

### 2.4 告警与整改闭环

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 告警列表/摘要 | `/patient-qc/relay-alert/logs`、`summary` | 已有 | 保留 | 发送失败、已发未看、已看未反馈快捷筛选 | P0 |
| 告警详情 | `/logs/{id}` | 已有基础 | 重组为时间线 | 生成→发送→查看→反馈→确认 | P0 |
| 过滤/抑制原因 | `dept_filtered`、配置规则 | 部分显示 | 保留 | 与失败区分，不误标为发送失败 | P0 |
| 告警重试 | `/relay-alert/retry/{id}` | 已有 | 保留 | 防重复、重试次数、外发确认 | P0 |
| 整改列表/看板 | `/qc/feedback/cases` | 已有 | 保留 | 状态、科室、用户、类型选项对齐 | P0 |
| 整改详情 | `/qc/feedback/cases/{id}` | 已有基础 | 重组 | 病程/护理换行、反馈历史、医生反馈 | P0 |
| 确认/关闭 | `/confirm` | 已有 | 保留 | action、comment、历史落库对齐 | P0 |
| 删除/批量删除 | case DELETE | 已有 | 保留 | 已修复重复 DELETE；继续保持单请求 | P0 |
| Excel 导出 | `/qc/feedback/export/excel` | 已有 | 保留 | 筛选与审计 | P1 |

### 2.5 手动推送、历史重跑与任务进度

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 范围/候选查询 | `/push/query-preview` | 已有 | 保留 | 日期维度、科室、单/多类型、分页 | P0 |
| 只读预检 | `/push/precheck` | 已有 | 保留 | 漏斗、跳过原因、确认前不写库 | P0 |
| 执行参数 | `/push/manual` | 已有大部分 | 保留 | dry_run、async、parallel、skip、replace 全量 diff | P0 |
| 勾选推送 | selected record keys | 已有 | 保留 | 仅单审计类型、最多条数、选择跨页语义 | P0 |
| 匹配诊断 | `/push/match-diagnostics` | 缺失 | 重组为候选详情 Drawer | 来源匹配、文书候选、跳过说明、脱敏 | P1 |
| Dify 节点池 | `/config/dify/targets` | 推送页缺编辑；配置页已有 | 合并 | 推送页只读显示策略摘要，编辑只在配置页 | P1 |
| 运行进度/取消 | `/push/status/{id}`、`cancel/{id}` | 已有 | 保留 | 离页停止轮询、全局任务指示保持 | P0 |
| 结果节点指标 | target metrics | 已有 | 保留 | 空结果、失败、节点熔断解释 | P1 |
| 历史 preview | `/historical-rerun/preview` | 已有基础 | 保留 | 候选分片、hash、before/after 摘要 | P0 |
| 批次创建/控制 | batches、pause/resume/cancel | 已有基础 | 保留 | 批次 items、恢复历史、错误分片详情 | P0 |
| 历史结果对账 | reconciliation | 缺失 | 新增独立对账区 | current/superseded、成功可用门槛 | P0 |
| 任务中心 | latest task、scheduler history | 当前任务与调度历史已聚合 | 重组完成，本地待 canary | 筛选、分页、详情、钻取和轮询生命周期已补齐 | P1 |

### 2.6 定时任务

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| daily/discharge 配置 | config scheduler sections | 已有 | 保留 | audit_type、科室、cron、enabled 完整对照 | P0 |
| 启停 | `/scheduler/start|stop` | 已有 | 保留 | job_id、确认、失败反馈 | P0 |
| 立即触发 | `/scheduler/trigger` query | 已有且契约已修 | 保留 | 显示 task_id/历史跳转；生产需单独批准 | P0 |
| 双锁 | `daily_push`、`discharge_push` | 本地已补 UI/API | 保留并强化 | 两锁不可合并；不提供直接清锁按钮 | P0 |
| 陈旧锁 | heartbeat + 4h timeout | 本地已补诊断 | 保留 | 原子 CAS 接管，避免双恢复者双跑 | P0 |
| 执行历史 | `/scheduler/history` | 已有 | 保留 | 错误码、类型级失败、分页 | P1 |
| 运行完整性 | `/scheduler/run-summary` | 已有 | 保留 | configured 类型缺失必须标红 | P0 |
| 历史对应日志 | legacy 跳日志 | 缺失 | 重组 | 聚合详情，不泄露正文 | P1 |
| Relay 科室快捷设置 | legacy scheduler 页附带 | 不迁移 | 合并到 Relay 配置 | 避免配置双入口 | P1 |

### 2.7 质控类型

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 列表/详情 | GET `/audit-types` | 已有 | 保留 | 显示启用、默认调度、builder、source、Dify 摘要 | P0 |
| 新建 | POST `/audit-types` | 缺失 | 保留 | 分步创建、code 一次确定 | P0 |
| 编辑 | PUT `/{code}` | 仅 JSON | 向导式重组 | 基础、source、builder、Dify、解析、展示 | P0 |
| 克隆 | POST `/{code}/clone` | 缺失 | 保留 | 新 code/name、冲突校验、确认 | P0 |
| 删除 | DELETE `/{code}` | 缺失 | 保留 | 调度引用提示、危险确认 | P0 |
| Source Cards | 可视化 sources/field mapping | 缺失 | 重组 | 卡片、高级 JSON 双模式且双向同步 | P0 |
| SQL/JSONPath 校验 | registry 保存契约 | 缺失直观状态 | 保留 | `{dept_filter}`、`:query_date`、`$` 开头 | P0 |
| Source 测试 | `/{code}/test-source` | 缺失 | 保留 | 只读、脱敏、行数/跳过/缺源诊断 | P1 |
| Dify 测试 | `/{code}/test-dify` | 缺失 | 保留 | 明确会产生外部调用；默认不带真实正文 | P1 |
| 运行警告 | `/config/runtime-summary` | 分散 | 合并显示摘要 | builder/source/目标风险就地展示 | P1 |

向导固定顺序：

```text
基本信息 → 数据源 → 分组/关联 → Payload Builder → Dify → 响应解析 → 展示映射 → 测试与诊断
```

必须展示的契约提示：builder 使用 `mr_text`；Dify 默认输入变量为 `mr_txt`；base URL 不保存 `/workflows/run`；密钥留空保留；SQL 与 JSONPath 继续走后端验证。

### 2.8 系统配置与 Relay

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 数据源类型 | `/config/data-source` | 已有 | 保留 | 切换影响摘要、确认与回滚显示 | P0 |
| Oracle | config/test/query | 保存/测试已有 | 重组 | 补受控 SQL 测试和高级诊断 | P1 |
| PostgreSQL | config/test/query | 保存/测试已有 | 重组 | 补受控 SQL 测试 | P1 |
| EMR Vastbase | `/config/emr-vastbase`、test | 缺失 | 独立配置区 | sslmode 仅显式传入；密码留空保留 | P0 |
| Dify 主配置 | `/config/dify` | 已有 | 保留 | workflow variable、已配置密钥状态 | P0 |
| Dify 节点池 | `/config/dify/targets` | 已有 | 保留 | 策略、权重、熔断、密钥保留完整对照 | P0 |
| 推送参数 | `/config/push` | 基础已有 | 保留 | 全字段说明与风险摘要 | P1 |
| 隐私脱敏 | `/config/privacy-masking` | 已有 | 保留 | 仅合成示例，不用真实患者数据 | P1 |
| 科室配置 | `/config/departments`、list | 已有 | 重组 | 区分全局列表和动态候选；空列表语义 | P1 |
| 通知渠道 | `/config/notify`、`/notify/test` | 缺失 | 保留 | channel cards、JSON 校验、真实发送确认 | P0 |
| Relay 基础配置 | `/config/relay-alert` | 两页重复 | 合并 | `RelayConfigPage` 为唯一编辑入口 | P0 |
| Relay 部分更新 | exclude_unset + merge | UI 基础已有 | 保留 | 空 base_url、空 secret 不覆盖 | P0 |
| Receiver Rules | `/relay/receiver-config|receiver-rules` | 缺失 | 保留 | 管床/创建医师/护士长/固定人员/上限 | P0 |
| 接收人预览 | `/relay/preview-receivers` | 缺失 | 保留 | 只预览，不发送；说明过滤原因 | P0 |
| 护士长/人员查询 | nurse-head、search-user | 缺失 | 保留 | 搜索脱敏、权限、无结果状态 | P1 |
| Relay 测试 | `/config/relay-alert/test` | 缺失/不完整 | 保留 | 明确会真实请求前置机，二次确认 | P0 |
| 运行总览 | `/config/runtime-summary` | 独立页已有 | 合并 | 配置页仅显示摘要/链接，不再复制完整表 | P1 |

### 2.9 用户、角色、权限和科室

| 能力 | legacy 证据/API | UI Next 现状 | 裁定与目标 | 缺口/验收 | 优先级 |
| --- | --- | --- | --- | --- | --- |
| 用户列表 | GET `/users` | 已有 | 保留 | 分页、角色、状态、科室范围 | P0 |
| 用户新增/编辑/删除 | POST/PUT/DELETE `/users` | 缺失 | 保留 | 表单校验、禁用优先、删除确认 | P0 |
| 修改密码 | `/users/{id}/change-password` | 缺失 | 保留 | 不回显、强度与确认 | P0 |
| 角色详情 | `/roles/{id}` | 基础列表 | 重组 | 权限、菜单、科室三块明确分离 | P0 |
| 角色菜单 | `/roles/{id}/menus/*` | 已有 | 保留 | menu_id 只读且稳定 | P0 |
| 角色权限 | `/roles/{id}/permissions/*` | 缺失 | 保留 | 后端 API 权限是最终权威 | P0 |
| 角色科室 | `/roles/{id}/departments/*` | 缺失 | 保留 | 科室范围清晰、批量保存防误删 | P0 |
| 权限 CRUD | `/permissions` | 仅列表 | 保留 | 新建/编辑/删除/模块筛选 | P0 |
| 科室 CRUD | `/departments` | 仅列表 | 与 RBAC 科室管理合并 | 与 config 的业务科室名单区分 | P1 |

### 2.10 健康、运行总览、调试与独立入口

| 能力 | 当前裁定 | 设计要求 | 优先级 |
| --- | --- | --- | --- |
| 系统健康 | 保留 | ready/live/深检含义清晰，不展示原始异常、SQL 或密钥 | P1 |
| 运行总览 | 唯一只读摘要入口 | warnings 可钻取配置；不复制编辑功能 | P1 |
| Dify 调试 | dev_only 独立保留 | 生产服务端过滤；原始 JSON 默认折叠；禁止患者正文进入日志/trace | P1 |
| 医生移动 H5 | 独立保留 | token、反向代理、查看计数、反馈协议不变；不使用 App Shell | P0 |
| log_detail | 独立保留 | 深链接、上一/下一、打印和独立滚动策略不变 | P1 |
| 报告页 | 独立保留 | 短期 token、打印、脱敏和鉴权不变 | P1 |
| Oracle/运行日志占位 | 淘汰/暂缓 | 未完成真实功能、安全脱敏和审计前不开放 | P3 |

---

## 3. 明确不照搬 legacy 的内容

1. 不恢复启动时加载所有模板和全局 Vue god object。
2. 不把全部配置塞进一个长页面；按业务分区并逐区保存。
3. 不把质控类型的 JSON、SQL、Dify、解析映射塞进一个密集 Dialog。
4. 不把普通推送、历史重跑、节点池编辑和进度全部混在同一区域。
5. 不让告警列表只显示最终状态，必须表达闭环时间线。
6. 不默认展示完整原始 JSON、Dify request/response 或病历正文。
7. 不把用户、角色、权限、科室塞进一个密集复选矩阵。
8. 不复制 Relay 和系统配置两套相同保存入口。
9. 不把移动 H5、独立日志页强行并入 App Shell。
10. 不恢复占位菜单；不把菜单隐藏当作后端授权。

---

## 4. 本地 Figma 文件页面清单

文件名：`Med-Audit UI Next`。2026-08-11 已创建目标文件，fileKey 为 `JaBlZJN8uo20IfFzTeMIR8`；创建后首次画布只读检查即触发 Figma Starter MCP 调用额度限制，因此尚未向该文件写入页面、变量、组件或 Frame。**正式画布后续已被用户取消、不再实施**；既有 fileKey 与 `design/med-audit-ui-next/` 本地可交互画板仅作历史/参考资产保留，不删除。

```text
00 Cover
01 Getting Started
02 Foundations
03 Components
04 Patterns
05 Screens
   ├── Desktop
   ├── Tablet
   └── Mobile
06 Prototype Flows
07 QA & Handoff
```

### 4.1 页面内容

| Figma Page | 内容 |
| --- | --- |
| `00 Cover` | 文件状态、负责人、版本、最后更新时间 |
| `01 Getting Started` | 管理端/H5/log_detail 边界、RBAC、menu_id、迁移裁定 |
| `02 Foundations` | 色彩、字体、间距、圆角、阴影、语义状态、响应式网格 |
| `03 Components` | 基础组件、变体、属性和代码映射 |
| `04 Patterns` | 列表、详情、步骤任务、配置编辑、闭环时间线、调度诊断 |
| `05 Screens` | 15 个现役路由的桌面/平板/手机画板；七个代表页先做完整状态 |
| `06 Prototype Flows` | 登录授权、质控闭环、手动推送、配置保存、陈旧锁恢复 |
| `07 QA & Handoff` | RBAC、状态矩阵、响应式、可访问性、route/API 契约 |

不在正式 Screens 内设计 `oracle-status`、`system-logs`；医生 H5 和 log_detail 只放 Reference Frame，避免误并入 App Shell。

### 4.2 Foundations

颜色以 `frontend/src/styles/tokens.css` 为权威，不在 Figma 另造一套主题。代码现有且可直接同步的 v1 token 为：

- Primitive：blue 50/500/600、cyan 500、green/orange/red 500、slate 50/100/200/300/500/700/900。
- Surface：page/card/sidebar。
- Text：primary/secondary/muted/on-dark。
- Border：default。
- Brand：blue/cyan。
- Risk：high/medium/low。
- Status：success/warning/danger/info/muted。
- Layout：240px 默认侧栏、64px 折叠侧栏、56px Header、10px 默认圆角。
- Effect：代码中的双层 `card shadow`。
- Element Plus 适配：primary `#2563eb`、8px 基础圆角、13px 基础字号、表头/hover 色。
- Viewports：1366×768、768×1024、390×844。

`spacing 4/8/12/16/20/24/32`、扩展 radius、overlay、border strong/focus、focus ring 等是根据现有 CSS 使用方式归纳的**候选补充 token**，当前并非代码权威 token。只有在 Figma 中明确标记为 Proposed，并在后续代码同步获批后，才能升级为共享 token。

字体权威栈为 `Segoe UI` → `PingFang SC` → `Microsoft YaHei` → system UI。创建文件后必须先读取 Figma 实际可用字体；不得默认使用 Inter。工作台已有页面级深色科技风，首轮只建 `Page Theme / Workbench` 局部主题，不覆盖管理端通用 Semantic collection。

---

## 5. Figma 组件、Variants 与代码映射

| Figma 组件 | 关键 Variants/Properties | 代码映射 |
| --- | --- | --- |
| `COMP/AppShell` | viewport、sidebar、health、task、userMenu | `AppShell.vue` |
| `COMP/Navigation/Sidebar` | expanded/collapsed/mobile、group open、item state | `AppSidebar.vue` |
| `COMP/PageHeader` | description、breadcrumb、actions、mobile wrap | `PageHeader.vue` |
| `COMP/FilterPanel` | expanded、query state、validation | `FilterPanel.vue` |
| `COMP/SummaryStrip` | loading、tone、value type、drilldown | `SummaryStrip.vue` |
| `COMP/Data/TableShell` | loading/data/empty/error/403、selection、pagination、responsive | `DataTableShell.vue` |
| `COMP/DetailDrawer` | closed/loading/loaded/error、size、footer、prev-next | `DetailDrawer.vue` |
| `COMP/StatusTag` | success/warning/danger/info/muted | `StatusTag.vue` |
| `COMP/RiskTag` | high/medium/low/unknown | `RiskTag.vue` |
| `COMP/AsyncButton` | idle/loading/disabled/success/failure | `AsyncButton.vue`/Element Plus |
| `COMP/Feedback/*` | skeleton/empty/error/menu error/403/404/500 | `components/feedback/*` 与 system pages |
| `COMP/PatientSummary` | compact/full、inpatient/discharged | 新建 shared component |
| `COMP/AuditDimensionCard` | pass/warn/fail/unknown、expanded | 新建 shared component |
| `COMP/EvidencePanel` | medical/nursing/raw、collapsed/expanded | 新建 shared component |
| `COMP/AlertTimeline` | generated/sent/viewed/feedback/closed/failed/filtered | 新建 closure component |
| `COMP/PushStepper` | configure/candidate/precheck/run/result | `ManualPushPage.vue` 重组 |
| `COMP/Scheduler/LockCard` | idle/running/stale/waiting takeover | `SchedulerPage.vue` 本地已有基础 |
| `COMP/SourceCard` | required/type/valid/error/disabled | 新建 audit-type component |
| `COMP/FieldMappingTable` | view/edit/error/empty | 新建 audit-type component |
| `COMP/SecretInput` | unset/configured/editing/invalid | Element Plus adapter |
| `COMP/ReceiverRuleTable` | enabled/disabled/invalid/preview | 新建 Relay component |
| `COMP/JsonDebugPanel` | collapsed/expanded/copied/invalid | 受控 debug component |

表单控件继续使用 Element Plus 的 Input、Password、Select、DatePicker、Switch、Checkbox、Radio、InputNumber、Textarea、Tabs、Steps、Alert、Dialog、Drawer、Pagination；Figma 不建立冲突的平行控件库。

---

## 6. 七个代表页面的完整 Frame 清单

### 6.1 工作台

- Desktop/Tablet/Mobile：Default。
- Loading/Skeleton。
- Empty trend / Empty high-risk。
- Health degraded。
- Partial API error + retry。
- Drilldown with filter handoff。

### 6.2 质控记录 + 详情

- List：Default/Loading/Empty/Error/403/Multi-select。
- Detail：Loading/Loaded/Error/Previous/Next。
- Sections：患者摘要、结论、维度、医疗证据、护理证据、版本、技术字段。
- Mutations：retry confirm/delete confirm/marker edit/export success/failure。
- Mobile：列表卡片 + 全屏详情；批量操作进入底部操作栏。

### 6.3 告警闭环时间线

- Pending/Sent/Viewed/Feedback pending/Closed/Failed/Dept filtered。
- Retry confirm/Retrying/Retry success/Retry failure。
- Desktop 横向摘要 + 纵向时间线；Tablet/Mobile 单列时间线。
- 明确区分 Relay alert、QCFeedback 和 H5 feedback。

### 6.4 手动推送与历史重跑

- Configure/Querying/Candidates/Precheck warning/Dry run。
- Replace current danger confirm。
- Running/Paused/Cancelled/Completed/Completed with errors/Failed。
- Historical preview/Hash mismatch/Batch items/Reconciliation。
- Advanced 默认折叠；Mobile 每步单卡片。

### 6.5 质控类型编辑器

- List/Readonly/Create/Edit/Clone/Delete confirm。
- Dirty/Unsaved/Validation error/SQL invalid/JSONPath invalid。
- Source cards/Field mapping/Advanced JSON。
- Source test loading/success/failure。
- Dify test confirmation/loading/parse success/failure。
- Secret retained/Save summary/Save success/failure。

### 6.6 定时任务与双锁

- Daily/discharge 两张配置卡。
- Lock：Idle/Running/Heartbeat healthy/Stale/Waiting safe takeover。
- Run summary：Complete/Incomplete/Missing type/Type failure/Parse failure。
- Trigger confirm/Triggering/Success/Failure。
- 不设计“直接清锁”按钮。

### 6.7 系统配置 + 用户权限

- Config：section navigation、readonly/edit/dirty/validate/change summary/save/test。
- Secret：unset/configured/leave blank/edit/invalid。
- Relay receiver preview/filtered/no recipient/test warning。
- Access：用户 CRUD、改密、角色菜单/权限/科室、权限 CRUD、科室 CRUD。
- 403/关联删除阻断/保存冲突/重复提交。

其余 8 个路由在 `05 Screens` 建基础 Default + Loading + Empty + Error + 403 + Mobile Frame，复用上述模式，不重新发明组件。

---

## 7. Prototype Flows

```text
Flow A 登录授权
Login → /users/me → /api/menu → menu_id ∩ route manifest → AppShell
失败：login error / menu error / unknown menu fail-closed / direct URL 403

Flow B 质控闭环
Patient or Record list → Detail → Dimension/Evidence → Alert timeline
→ Feedback action → Confirm → Success/Failure

Flow C 手动推送
Scope → Candidates → Match diagnostics → Precheck → Danger confirm
→ Run → Progress → Result → Retry/Reconciliation

Flow D 配置保存
Edit → Dirty → Validate → Change summary → Confirm → Saving
→ Success/Failure → Reload effective config

Flow E 陈旧锁
Status → Stale warning → No direct clear → Next same-name run CAS takeover
→ Heartbeat healthy → Six-type run summary
```

---

## 8. 每页强制交互状态矩阵

所有页面至少设计并验收：

- Default、Loading/Skeleton、Empty、Filtered Empty。
- API Error + Retry、Network Offline、401、403、404、500。
- Readonly、Edit、Dirty/Unsaved、Validation Warning/Error。
- Confirm、Submitting/Saving、Success、Failure、Conflict 409、Validation 422、Rate limit 429。
- Duplicate-submit prevention。
- Long text collapse/expand、table horizontal scroll、mobile drawer/full-screen detail。
- Polling active / route leave stopped。
- Permission hidden 与 readonly degradation。

高风险补充：

- 推送：dry-run、replace current、部分成功、取消、重试、历史对账。
- 调度：双锁、陈旧锁、缺失类型、类型级失败。
- 质控类型：SQL/JSONPath/source/Dify 测试。
- Relay：secret 留空保留、接收人预览、科室过滤、真实测试确认。
- 权限：账号禁用、改密、关联删除阻断、直接 URL 403。

---

## 9. Figma 命名、Handoff 与验收

命名：

```text
SCREEN/Desktop/Workbench/Default
SCREEN/Tablet/QualityRecords/Loading
SCREEN/Mobile/AlertTimeline/Failed
COMP/Scheduler/LockCard
COMP/Feedback/ErrorState
State=Default|Loading|Error|Readonly|Disabled|Success|Failure
Viewport=Desktop|Tablet|Mobile
```

Handoff 必须标注：route name、menu_id、风险等级、所用 API、所需 permission、mutation 是否启用、空值语义、独立入口边界。禁止虚构 route/menu_id/API。

验收清单：

- [ ] 15 个 route manifest 页面均有 Screen 或明确复用 Pattern。
- [ ] H5、log_detail、report 边界独立。
- [ ] menu_id 不变；未知 ID fail-closed。
- [ ] admin/dept_manager/auditor/clinician 四角色状态存在。
- [ ] 1366×768、768×1024、390×844 三尺寸齐全。
- [ ] 表格滚动/卡片降级、移动全屏 Drawer 明确。
- [ ] 所有业务和错误状态齐全。
- [ ] 危险操作二次确认、密钥留空保留、部分更新语义明确。
- [ ] 状态不只靠颜色；键盘焦点、触控尺寸和 reduced motion 可验收。
- [ ] Figma token 与代码 token 对应；Element Plus 不建立平行体系。
- [ ] 不在设计稿、注释、截图或原型数据中放患者正文、真实标识或密钥。

---

## 10. 实施顺序（已获批并由 Luna 本地执行）

顺序以依赖和业务风险为准，不代表允许半成品进入生产：

1. 共用详情组件与质控记录/患者质控完整对照。
2. 告警时间线与整改反馈闭环。
3. 调度双锁/完整性与任务进度。
4. 手动推送匹配诊断、历史 items 和对账。
5. 质控类型向导与测试。
6. Vastbase、通知渠道、Relay Receiver Rules。
7. 用户/角色/权限/科室完整管理。
8. 工作台钻取、跨页筛选和整体视觉收口。

每个能力在合入前必须完成：legacy 请求与新请求 Network diff、权限、NULL、二次确认、重复提交、导出审计、响应式和错误状态。所有能力本地完成并通过统一验收后，才可整体申请 WP6 canary；不得把某个页面完成解释为允许提前切默认入口。

---

## 11. 本轮确认结果与后续审批项

已确认：迁移裁定、P0/P1、本地设计平替、医院与产品名称，以及“主 AI 规划/复核、Luna 实现”的分工。字体继续使用代码现有系统字体栈；菜单沿用“质控记录”“告警推送配置”。

仍需单独审批：阶段 A 新镜像 canary 部署（`UI_DEFAULT_ENTRY=legacy`）、阶段 B 默认入口切换（`UI_DEFAULT_ENTRY=ui-next`）、真实 WP6 四角色/Relay 实发、任何 Dify/调度写操作，以及 legacy 下线。Figma 正式画布已用户取消。本地已实现 `UI_DEFAULT_ENTRY` 开关（默认 legacy，`/index.html` 可回旧界面）。

---

## 12. Figma Phase 0 只读发现结果（2026-08-11）

### 12.1 Phase 0 状态

| Task | 结果 | 证据/裁定 |
| --- | --- | --- |
| `P0.a` 代码真值 | 完成 | `tokens.css`、`global.css`、Element Plus override、基础组件、App Shell 和七个代表页已盘点 |
| `P0.b` Figma 目标文件 | 已创建；正式画布用户取消 | `Med-Audit UI Next`：`JaBlZJN8uo20IfFzTeMIR8`；创建动作成功，画布仍为空；**不再实施正式画布** |
| `P0.c` 设计库 | 用户取消，不再实施 | 历史：Starter 额度曾阻断只读检查；现裁定为正式画布取消，保留 fileKey/本地资产，不续接 Figma 写入 |
| `P0.d` v1 scope | 已拟定 | Foundations、核心组件、Patterns、七个完整代表页、其余八页基础状态、Prototype、QA |
| `P0.e` Code → Figma | 完成初判 | 当前没有 Figma 侧对象；正式画布取消后以本地 design 与代码 token 为准 |
| `P0.f` 差距分析 | 完成 | 见下表；Phase 1 Figma 写入**用户取消，不再实施**；本地平替已供负责人复核 |

已通过 Figma 连接读取账号能力：账号属于 Starter 团队。目标文件创建成功，但后续 MCP 读写被 Starter 调用额度限制阻断；在额度恢复前不重复消耗调用，也不换账号或猜测未核验的文件内容。

### 12.2 代码侧精确盘点

| 类别 | 数量/结论 |
| --- | --- |
| Primitive colors | 14 |
| Semantic colors | 16；含 3 risk、5 status alias |
| Layout/dimension | sidebar 240/64、header 56、radius 10 |
| Effect | 1 个双层 card shadow |
| Product font | Segoe UI / PingFang SC / Microsoft YaHei / system fallback |
| Element Plus base | primary、radius、13px base、table header/hover、drawer/dialog padding |
| 响应式 | 640px mobile；900px drawer 全屏；mobile sidebar `min(86vw, 280px)` |
| Code Connect | 无 `*.figma.ts/js/tsx` |
| 页面图片 | 七个代表页无 `<img>`、远程图片或 background-image；不需要图片捕获流程 |

### 12.3 Gap / Conflict

| 类型 | 发现 | 裁定 |
| --- | --- | --- |
| Code-only | 全部现有 token、基础组件、App Shell、页面 Pattern | 新文件中按代码真值建立 |
| Figma-only | 已有 fileKey，正式画布用户取消 | 保留 fileKey，不假设任何 Figma-only 资产，不再续接正式画布 |
| Proposed-only | spacing/radius 扩展、overlay、strong/focus border、focus effect | 仅本地 design 标记 Proposed；不得冒充已实现代码 token |
| 页面主题 | Workbench 使用页面专属深色/科技风硬编码色 | 建局部 `Page Theme / Workbench`，不污染全局语义色 |
| 控件体系 | 代码使用 Element Plus，仓库无配套 Figma Library/Code Connect | 先搜索可用库；API 不匹配时本地包装，不建立第二套业务控件语义 |
| 字体 | 代码是系统字体栈，Figma 可用字体尚未知 | 建文件后读取字体列表，再锁定中英文组合 |
| 账户限制 / 用户决定 | 正式画布用户取消 | **不再实施** Figma 正式画布；本地 design 与代码为准；fileKey 保留不删除 |

### 12.4 Figma 正式画布状态（用户取消）

1. **裁定：用户取消，不再实施正式画布**（不是“待配额恢复”）。
2. 既有 fileKey `JaBlZJN8uo20IfFzTeMIR8` 与 `design/med-audit-ui-next/` 保留作历史参考，禁止删除。
3. 不得创建第二个平行 Figma 文件，也不得因额度恢复自动重启正式画布建设。
4. 视觉与交互以 Vue 代码 + 本地 design 画板为准。

当前仅完成过 Figma 文件创建；没有向画布创建页面、变量、组件或 Frame，且正式续接已取消。

---

## 13. Figma 创建与本地平替 v2 交付（2026-08-11）

### 13.1 交付物

| 交付物 | 路径/地址 | 状态 |
| --- | --- | --- |
| Figma 目标文件 | <https://www.figma.com/design/JaBlZJN8uo20IfFzTeMIR8> | 已创建；**用户取消正式画布，不再实施**；fileKey 保留 |
| 本地交互画板 | `design/med-audit-ui-next/index.html` | 医院品牌增强版 v2 完成，等待负责人复核 |
| 使用与边界说明 | `design/med-audit-ui-next/README.md` | 完成 |
| Figma 续接状态 | `design/med-audit-ui-next/figma-state.json` | 已记录 fileKey、阻断原因和本地平替状态 |

### 13.2 v2 品牌与设计方法

- 品牌抬头统一为“山东省第二人民医院”，产品名统一为“AI病历质控系统”；侧栏、顶栏、页面标题、浏览器标题和说明文档均已纳入品牌层级。
- 视觉采用浅色医疗工作台、深蓝导航与蓝/青 AI 强调色，不照搬 legacy 全屏深色大屏，也不牺牲信息密度和任务可达性。
- 未在仓库发现经确认的医院官方标志资产，因此使用可替换的抽象医疗/AI 图形占位，避免虚构官方 Logo；进入生产实现前必须由院方提供或确认正式品牌资产。
- 本轮以 `figma-generate-design` 和 `figma-generate-library` 的本地技能规范指导设计：先复用代码 token 建 Foundations，再组织组件、Pattern 和页面区块，并区分代码真值与 Proposed 设计项。
- 产品字体继续遵循代码中的 Segoe UI / PingFang SC / Microsoft YaHei / system 字体栈；未因 Figma 不可用另建平行字体规范。

### 13.3 本地平替覆盖范围

- Foundations：14 个 primitive、16 个 semantic alias、布局、字体、效果和 Element Plus override 摘要。
- Components / Patterns：PageHeader、筛选、表格、Drawer、Dialog、状态反馈、分步操作、高级选项和危险操作确认。
- 七个增强代表页：AI 质控工作台、质控记录与详情、告警闭环、手动推送、质控类型、双任务调度、系统配置与访问控制。
- 工作台补充 AI 质控链路、四项指标、风险趋势、风险构成、科室排行、服务健康和今日闭环；其余页面补齐筛选、数据密度、业务状态、风险提示与操作上下文。
- 三档画布：Desktop、Tablet、Mobile，对应 1366px、768px、390px。
- 通用状态：默认、加载、空、错误、403、只读、未保存、确认、保存中、成功、失败；并保留页面专属状态，状态标签和提示均已中文化。
- 全部为匿名合成数据；不连接 API，不执行推送、调度、告警、Dify、数据库或生产写操作。

### 13.4 主审验收结果

- Chrome 自动遍历七个代表页共 84 个页面/状态组合，均有有效渲染，非默认状态均有中文状态横幅。
- 画布实测宽度为 Desktop 1366px、Tablet 768px、Mobile 390px；七页均无根级横向溢出。
- Pattern Stepper、高级选项展开、质控详情 Drawer、通用 Drawer 和 Confirm Dialog 均通过交互检查。
- 浏览器 `pageerror` 和 console error 均为 0；本地脚本语法检查通过。
- 七页桌面截图已逐页目检；双调度陈旧锁归属、锁卡排版和移动端 RBAC 表格内部滚动问题已经纠正。

本地画板仍是设计复核资产，不是运行时依赖；Vue 页面已按获批方案独立实现，未通过自动生成覆盖业务代码，也未启用生产入口。

---

## 14. UI Next 首轮功能迁移与复核结果（2026-08-11）

### 14.1 本地实现范围

| 领域 | 本轮结果 | 关键边界 |
| --- | --- | --- |
| 品牌与 App Shell | 统一“山东省第二人民医院 / AI病历质控系统”，补齐浅色医疗管理端 token、响应式侧栏与基础组件状态 | 使用可替换抽象图标，未虚构医院官方 Logo |
| 工作台 | KPI、风险趋势、风险分布、重点事件、服务健康与任务摘要完成视觉和状态重组；指标、科室 TOP 与高风险事件可携带白名单筛选钻取患者、日志、告警和反馈页 | 未改变统计 API 口径；`source/log_id/quick` 等路由元信息不会进入列表 API |
| 患者质控 | 对齐 `push_log_id`、`feedback.status`、`discharge_main_diagnosis`；补齐病历/护理证据、错误重试和快捷整改互斥 | 不展示 `request_json`；导出按当前筛选全部结果 |
| 患者汇总导出 | 列表与导出共用筛选构造器；导出全部匹配患者住院次（跨科室去重）并与 `TEMP_PAT_VISIT_LIST` 取交集；筛选无结果返回表头-only Excel；`ExportAuditLog.scope=filtered_all_pages`，患者标识仅记“已提供” | 不携带 page/limit/source；不改变 `mr_text/mr_txt`、推送、Relay、调度 |
| 质控记录 | 筛选、详情、上一/下一、marker、报告、单/批量重推和删除、导出状态完成迁移 | 危险操作均保留确认；未真实调用重推 |
| 告警与反馈 | 告警快捷筛选、闭环时间线、失败重试；反馈证据、历史、确认/关闭、删除与导出完成迁移 | 未执行真实 Relay 发送 |
| 手动推送与历史重跑 | 候选/匹配诊断、预检、执行参数、进度、批次 items 与 reconciliation 完成迁移 | 未调用 Dify、未创建真实批次、未触发调度 |
| 任务进度 | 聚合当前手动任务与调度历史，补齐状态/触发类型/执行日期/运行模式筛选、分页、详情和质控记录钻取；按后端真实 `processed` 计算当前进度 | 当前任务只在第一页且筛选可判定时出现；页面停用、隐藏或任务结束后停止本页轮询 |
| 双调度 | daily/discharge 独立状态、独立锁、运行摘要、配置与确认状态完成迁移 | 两个 DB 锁未合并；未提供直接清锁 |
| 质控类型 | 列表、创建、编辑、克隆、删除、source 卡片、JSON 高级模式、source/Dify 测试入口完成迁移 | `mr_text`/`mr_txt`、SQL、JSONPath 与密钥保留契约不变；测试入口未真实调用 |
| 系统配置 | Oracle、PostgreSQL、EMR Vastbase、Dify 主节点/节点池、推送、隐私、科室、通知、Relay 与运行摘要按分区迁移 | 密钥成功保存后清空，失败保留；测试按钮均显式确认 |
| Relay 接收规则 | high/medium/low 规则、固定人员搜索、接收人预览、护士长查询和结构化诊断完成迁移 | 基础配置继续部分更新，不覆盖 `receiver_rules/nurse_heads/detail_page`；没有真实发送按钮 |
| 用户与权限 | 用户分页/新增/编辑/禁用启用/改密、角色权限/菜单/科室授权、权限和科室 CRUD 完成迁移 | 自助改密始终校验旧密码；管理员重置他人可留空；后端 RBAC 仍为权威 |
| 独立详情与无障碍 | 质控记录恢复 `/log_detail.html?id=` 独立入口；工作台所有非原生点击卡支持 Enter/Space、语义标签和焦点环；全局支持 reduced motion | 未修改独立详情页、报告页或手机 H5 本体；完整 WCAG 人工审计仍属于 canary 验收 |

为支持真实页面状态，后端只做了最小契约补齐：`UserInfo.is_active` 全链路返回真实值；用户科室/角色和科室负责人可显式清空；管理员重置他人密码可省略旧密码，但修改自己仍必须验证旧密码；患者汇总导出补导出审计与准确记录数；`/scheduler/history` 补只读筛选、分页约束和闭区间执行日期查询。调度注册、双锁、推送执行和外部发送语义未改变。

### 14.2 自动化验收

| 检查 | 结果 |
| --- | --- |
| `npm run typecheck` | 通过 |
| `npm run test:unit` | 14 个文件、50 项通过（含导出 params 契约） |
| `npm run build:docker` | 通过；仅生成 `frontend/dist/`，未同步 `static/` |
| Playwright 完整三视口 | 46 项通过、8 项按移动专属或桌面深交互规则预期跳过；共运行 54 项（含患者筛选导出与 390px） |
| 新增迁移 mock E2E | 覆盖 Patient/Relay/Access 三视口、患者筛选导出 query、以及桌面工作台键盘钻取、任务聚合联动和独立详情打开参数 |
| `python -m pytest -q` | 全量 100% 通过；仅有既有 Pydantic/SQLite 弃用警告 |
| `python -m compileall app tests scripts` | 通过 |

浏览器验收使用 1366×768、768×1024、390×844；新增功能 E2E 的所有 `/api/**` 均由 Playwright mock 拦截，没有连接真实服务、业务库、Dify 或前置机。

### 14.3 手机端与生产边界

- 本轮未修改 `static/templates/mobile/`、`static/scripts/mobile/`、移动 H5 路由、`relay_alert_service.py`、`dify_pusher.py` 或推送执行器，因此从代码变更边界看，现有手机 H5 与手机端告警发送链路不受 UI Next 管理端迁移影响。
- 上述结论是静态差异与自动化回归结论，不等同于生产前置机/企业微信实发验收；真实手机端仍需在 canary 阶段以测试患者和批准的接收人独立验证。
- 未执行 `npm run build`、未同步 `static/`、未登录生产服务器、未修改生产配置/数据库、未触发 Dify、推送、调度、Relay 或历史重跑。

### 14.4 尚未关闭的门禁

1. **Figma 正式画布：用户取消，不再实施。** 既有 fileKey 与本地 `design/` 资产保留、不删除；不得因额度恢复自动恢复正式画布实施。
2. 真实后端逐页联调、四角色 RBAC、真实 401/403/409/422/429、长数据和 Oracle NULL 仍需 WP6 canary 验收。
3. **患者就诊汇总导出：已改为当前筛选全部结果**（列表同源筛选 + TEMP 交集 + 审计脱敏）；生产真实 TEMP/Oracle/Vastbase 联调与大结果集耗时仍需 canary 验证。
4. 工作台跨页筛选、任务中心聚合、独立 `log_detail` 入口和核心键盘无障碍已本地完成；独立页真实认证/打印、全量 WCAG 人工检查与长数据体验仍需 WP6 canary 验收。
5. legacy 默认入口和移动 H5 必须继续保留，直到 canary、回滚演练和至少两个发布周期观察完成。

### 14.5 患者导出筛选口径（2026-08-11 修订）

| 项 | 约定 |
| --- | --- |
| 范围 | 当前筛选条件下全部匹配患者住院次，**不限当前页**；无筛选等价于导出全部匹配患者 |
| 同源筛选 | `patient_id/name/admission_no/visit_number/dept/discharge_dept_name/severity/status/date_from/date_to/audit_type_code` |
| 当前结果 | 仅 `success` + `superseded_by IS NULL` + `contract_valid IS NULL OR =1` |
| 日期 | 与列表一致，按 `PushLog.push_time` 闭区间 |
| 分组 | 列表：`patient_id+visit_number+dept`；导出业务行：`patient_id+visit_number`（跨科室去重） |
| TEMP 交集 | 先筛 PushLog 再与 `TEMP_PAT_VISIT_LIST` 取交集；筛不到不回退全量 |
| 空结果 | 合法表头-only Excel，`record_count=0` |
| 审计 | `scope=filtered_all_pages`；患者标识字段记“已提供” |
