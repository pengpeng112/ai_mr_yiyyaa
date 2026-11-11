# 120 仓库目录与文件索引

> 盘点日期：2026-10-12。执行者：Grok。本文件给后续 AI 用，回答「代码和目录在哪」。
> 计划编号、状态和能否执行，以 [docs/INDEX.md](../INDEX.md) 为准。启动顺序以仓库根 `AGENTS.md` 为准。
> 本文件不授权生产写入、Git 提交或临床口径变更。文件数是当天排除 `.git`、`.venv`、`node_modules`、`__pycache__`、`.pytest_cache` 后的近似计数。

## 1. 三十秒接手

1. 读 `AGENTS.md`，再读 [开发起步包/README.md](../../开发起步包/README.md)、`00_AI协作规则.md`、`01_统一修改记录.md` 末 10 行。
2. 改文件前看 [02_协作任务板.md](../../开发起步包/02_协作任务板.md)。工作区长期有别人的未提交改动，禁止 revert 或覆盖来路不明的脏文件。
3. 找计划用 `docs/INDEX.md`。找代码用本文件。找回归约束用 `docs/reference/101_FEATURE_BASELINE.md` 和 `docs/skills/med-audit-codex.md`。
4. 门禁唯一入口是 `scripts/run_gates_20260906.py`。`--full` 含前端 build，会用 robocopy `/MIR` 覆盖 `static/ui-next`。没有明确授权时只用 `--quick`。
5. 应用解释器使用仓库 `.venv`（Python 3.11）。不要用系统自带的 `python`。

## 2. 顶层目录

| 路径 | 大约文件数 | 职责 | 后续 AI 怎么对待 |
| --- | --- | --- | --- |
| `app/` | 132 | 主服务 FastAPI | 可改业务代码；路由只在 `app/main.py` 注册 |
| `tests/` | 166 | 主服务 pytest | 新行为先补测试；生产库不进单测 |
| `frontend/` | 126 | UI Next 源码（Vue 3 + Vite） | 与 `static/` 不是同一棵树 |
| `static/` | 145 | 旧页面和已构建的 `ui-next/` | 不是缓存，不要整目录删除 |
| `prearchive_service/` | 133 | 归档前预检，独立进程 | 禁止 `import app.*`；主服务也不得反向依赖它 |
| `docs/` | 286 | 计划、契约、归档、技能、SQL | 改任何 `docs/**/*.md` 必须同步 `docs/INDEX.md` |
| `scripts/` | 77 | 门禁、演示、历史热修和诊断 | 新脚本用 `*_YYYYMMDD.py`；历史 deploy/hotfix 不要重跑 |
| `config/` | 84 | 运行配置；`demo/` 约占 80 | 不改 `config.json` 密文；模板是 `config.json.template` |
| `data/` | 13 | 本地应用库等运行数据 | 不为整理去迁移库或调用 `init_db()` |
| `logs/` | 39 | 运行日志 | 只读排查；不把患者原文抄进文档 |
| `prompts/` | 2 | 旧病程/护理提示词（INDEX 107、108） | 待 Dify 复核，不是当前代码入口 |
| `design/` | 5 | 设计资产 | 与前端源码分开 |
| `oracle-client/` | 66 | Oracle Instant Client | 离线部署依赖，不按体积清理 |
| `packages/` | 49 | 离线依赖包 | 同上 |
| `review/` | 1397 | 本地过程证据，多数不入库 | 不整包提交；长期结论写进 01 或现役文档 |
| `开发起步包/` | 5 | 启动、规则、修改台账、任务板 | 01 只追加；PROMPT 不是当前授权 |
| `.agents/` | — | 仓库技能（门禁、演示栈、一次性交付等） | 与业务代码一起维护；不是个人缓存 |

隐藏目录 `.claude/`、`.opencode/`、`.qodo/`、`.sisyphus/`、`.v2c/`、`.video_agent/`、`.vscode/` 是工具工作区。不得只凭目录名删除。

## 3. 根目录文件

允许留在根目录的说明和部署文件：`AGENTS.md`、`CLAUDE.md`、`ARCHITECTURE.md`、`DEPLOY.md`、`CODE_STYLE.md`、`README_CN.md`、`Dockerfile`、`docker-compose.yml`、`docker-compose.demo.yml`、`docker_build.bat`、`docker_deploy.sh`、`entrypoint.sh`、`requirements*.txt`、`pytest.ini`、`.env.example`、`.gitignore`、`.gitattributes`、`.dockerignore`。

有意保留、本次不迁移：

- `docs/3一致性核查正式版-质控门禁影子V2.yml` 虽在 `docs/` 顶层，但是 2026-08-19 起的唯一影子工作流。`tests/test_dify_workflow_optimized_export.py` 和 `scripts/build_admission_fact_gate_shadow_yml_20260819.py` 写死了这个路径。
- 根目录 `user.xlsx`、`user_dict.xlsx` 被 `.gitignore` 按文件名忽略。119 指南已裁定继续留在原位：不打开、不迁移、不在文档里展开内容。

## 4. 主服务怎么跑

入口是 `app/main.py`。启动时做配置校验、`init_db()`、按 `ENABLE_SCHEDULER` 启动进程内 APScheduler，然后注册路由，最后把 `static/` 挂到 `/`。因此业务路由必须写在静态挂载之前。

数据流：`data_source_loader` 拉患者包 → `payload_composer` 按审计类型组装 → `dify_pusher.push_to_dify` → `audit_result_mapper` / `models.py` 落库。调度和重试走串行 `push_executor.py`；`/api/push/manual` 走并行 `bulk_push_executor.py`。

应用库由 `APP_DB_TYPE` 选择（默认 sqlite）。病历来源在 `config/config.json` 的 `data_source.type`，与应用库不是同一个连接。构建器输出用 `mr_text`；Dify 入参变量默认 `mr_txt`，只在 `dify_pusher.py` 里映射。

`app/` 顶层文件：

| 文件 | 职责 |
| --- | --- |
| `main.py` | 进程入口、路由注册、静态挂载 |
| `config.py` | 环境变量、JSON、Fernet；启动时金丝雀解密 `*_enc` |
| `database.py` | 连接与手工迁移；没有 Alembic |
| `models.py` / `schemas.py` | ORM 与请求模型 |
| `auth.py` / `permissions.py` | JWT 与 RBAC |
| `oracle_client.py` / `postgresql_client.py` / `db_client_base.py` | 业务库查询 |
| `emr_vastbase_client.py` | Vastbase 文书；列名要转小写 |
| `dify_pusher.py` | 调用 Dify、解析、契约校验、正文缺失标记 |
| `scheduler.py` | APScheduler；日增锁 `daily_push`，终末锁 `discharge_push` |
| `notifier.py` / `notify_channels.py` | 通知渠道 |
| `security_middleware.py` / `security_utils.py` | 安全中间件与工具 |
| `metrics.py` | 运行指标 |

`app/utils/`：`json_utils.py`、`patient_dept_query.py`、`text_utils.py`。科室查询以 `patient_dept_query` 为准。`app/demo_support/` 只服务隔离演示。

路由注册在 `app/main.py` 约 236–278 行。下表是文件到前缀的对照；前缀写在 `main.py` 里的按该前缀找，写在装饰器里的进对应文件看路径。

| 路由文件 | 注册前缀 |
| --- | --- |
| `config.py` | `/api/config` |
| `audit_types.py` | `/api/audit-types` |
| `push.py` | `/api/push` |
| `historical_rerun.py` | `/api/push/historical-rerun` |
| `logs.py` | `/api/logs` |
| `metrics.py` | `/api/metrics` |
| `scheduler.py` | `/api/scheduler` |
| `stats.py` | `/api/stats` |
| `notify.py` | `/api/notify` |
| `health.py` | `/api/health` |
| `users.py` | `/api/users` |
| `roles.py` / `permissions.py` / `departments.py` | `/api/roles`、`/api/permissions`、`/api/departments` |
| `qc_feedback.py` | `/api/qc/feedback` |
| `patient_qc.py` / `patients.py` | `/api/patient-qc`、`/api/patients` |
| `audit.py` | `/api/audit` |
| `relay_config.py` | `/api/relay` |
| `menu.py`、`prearchive_admin.py`、`jhemr_integration.py`、`mobile_qc.py`、`report.py`、`demo.py` | 前缀在各文件的路由装饰器上 |

`app/services/` 按名字找，不要新造同义模块：

| 分组 | 文件 |
| --- | --- |
| 组包与送模 | `data_source_loader.py`、`dual_source_loader.py`、`payload_composer.py`、`payload_builder.py`、`builder_registry.py`、`*_payload_builder.py`、`progress_record_adapter.py`、`nursing_record_adapter.py` |
| 推送与当前结果 | `push_executor.py`、`bulk_push_executor.py`、`push_log_writer.py`、`push_log_supersede.py`、`current_result_filter.py`、`push_skip_policy.py`、`push_idempotency.py`、`qc_status_semantics.py` |
| Dify 结果 | `dify_schema_parser.py`、`dify_result_normalizer.py`、`dify_json_parser.py`、`dify_output_resolver.py`、`result_contract_validator.py`、`audit_result_mapper.py`、`audit_result_writer.py` |
| 调度 | `scheduler_audit_runner.py`、`scheduler_lock_service.py`、`scheduler_run_modes.py`、`scheduler_history_service.py`、`scheduler_run_summary.py` |
| 告警与反馈 | `relay_alert_service.py`、`alert_token.py`、`alert_evidence_service.py`、`feedback_stats.py` |
| 配置与审计类型 | `audit_type_registry.py`、`audit_type_contracts.py`、`runtime_config_resolver.py`、`runtime_summary_service.py`、`source_field_contract.py` |
| 导出与留存 | `export_service.py`、`export_audit_service.py`、`qc_summary_export.py`、`retention_service.py` |
| 预检只读衔接 | `prearchive_admin_client.py`、`prearchive_rules_view.py`（主服务侧；不 import 预检包内部模块） |

## 5. 两套前端

`frontend/` 是源码。页面在 `frontend/src/features/`：

| 目录 | 页面 |
| --- | --- |
| `auth` | `LoginPage.vue` |
| `tasks` | `ManualPushPage.vue`、`PushProgressPage.vue`、`SchedulerPage.vue` |
| `quality` | `PatientQcPage.vue`、`AuditRecordsPage.vue`、`PatientDetailStandalonePage.vue` |
| `closure` | `AlertLogsPage.vue`、`FeedbackPage.vue` |
| `governance` | `AuditTypesPage.vue`、`ConfigPage.vue`、`RelayConfigPage.vue`、`WorkbenchPage.vue`、`PrcRuleEditDrawer.vue`、`workbenchPerms.ts` |
| `workbench` | 另一个 `WorkbenchPage.vue`（质控工作台，不是 governance 那份） |
| `system` | 健康、权限、调试、错误页、`RuntimeSummaryPage.vue` |

接口封装在 `frontend/src/api/`，路由在 `frontend/src/router/`，状态在 `frontend/src/stores/`。单元测试 `frontend/tests/unit/`，浏览器测试 `frontend/tests/e2e/` 与 `frontend/tests/e2e-legacy/`。

`static/` 是旧版单页和构建产物：`index.html`、`scripts/`、`styles/`、`templates/`、`vendor/`、`ui-next/`。改 UI Next 行为时改 `frontend/src`，再按已有构建流程更新 `static/ui-next`。不要手改构建产物后又被 `/MIR` 覆盖。

## 6. 预检服务

`prearchive_service/` 独立运行，入口 `run_service.py`，隔离检查 `check_isolation.py`。

| 目录 | 职责 |
| --- | --- |
| `prearchive/` | 规则引擎、采集、闭环、触发、Outbox |
| `prearchive/insurance/` | 医保插件：`deterministic.py`、`noop.py`、`opendrg_adapter.py` |
| `reminder_agent/` | 提醒代理，保持与主服务隔离 |
| `rules/` | 规则 JSON |
| `sql/` | 预检自己的 SQL |
| `tests/` | 预检 pytest，不并进主服务 `tests/` |
| `integration/`、`schemas/` | 联调与契约 |

`config.example.json` 是样例。`config.demo.json` 只给隔离演示。`data/` 是预检本地数据，不是主服务 `data/`。

## 7. 文档怎么分

| 目录 | 内容 |
| --- | --- |
| `docs/INDEX.md` | 编号台账。改文档先改这里 |
| `docs/ACTIVE/` | 约 60 份。目录名不等于待办，先看状态列 |
| `docs/reference/` | 101–120 契约、提示词、本索引、门禁锚 `gate_anchors.json` |
| `docs/archive/` | 只追溯 |
| `docs/remediation/` | 整改证据与回退说明 |
| `docs/attachments/` | 可能含隐私，禁止提交和外发 |
| `docs/skills/` | `med-audit-codex.md`、`med-audit-refactor-workflow.md` |
| `docs/sql/` | 三份只读查询样例（护理/病程） |

当前业务主线编号是 023。061 记录 2026-10-08 仍未关闭的人工项。059/060 是本地核查和测试计划，执行事实以各自文首为准。

## 8. 测试与脚本

主测试：`.venv\Scripts\python.exe -m pytest tests`。2026-10-12 修复两处 Dify 缺陷后为 1538 passed。预检测试目录是 `prearchive_service/tests`。前端单元是 `npm --prefix frontend run test:unit`（当时 72 passed）。

脚本只记入口，不把历史热修当操作手册：

| 类别 | 代表文件 |
| --- | --- |
| 现在就用 | `run_gates_20260906.py`、`check_naming_convention.py`、`check_documentation_20261002.py`、`demo_env.py`、`run_prearchive_demo_sidecar_20260904.py`、`init_rbac.py` |
| 历史部署或生产热修 | `deploy_*.py`、`hotfix_*.py`、`remediate_*.py`、`qc_production_readonly_audit.py` |
| 诊断草稿，无日期 | `debug_*.py`、`deep_diag.py`、`quick_diag.py`、`test_conn.py`、`todo.txt`、`TestVastbaseJdbc.java` |

这些诊断草稿本次留在原位。它们没有日期后缀，也不在 AGENTS 的常用命令里。移动会碰到引用和别人的工作区，所以只在这里分类。

## 9. 本次整理实际做了什么

核对了根目录、`app/`、`frontend/src/features/`、`prearchive_service/`、`docs/`、`scripts/`、`static/`、`tests/`。没有移动运行代码，没有移动影子 YML，没有移动根目录 xlsx，没有改 `config/`，没有连生产，没有 Git 写。

新增本文件，并在 `docs/INDEX.md`、`docs/README.md`、`开发起步包/README.md` 挂上入口。
