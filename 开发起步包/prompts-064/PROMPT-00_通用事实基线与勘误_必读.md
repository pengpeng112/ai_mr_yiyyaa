# PROMPT-00：064 全部工作包共用的「代码事实基线 + 勘误 + 通用铁律」（每包开工前必读）

> **版本**：v1.1（2026-11-19 19:30，对照仓库真实代码逐项核验后修订）  
> **用法**：执行任何 `PROMPT-WPxx` 之前，**先完整读本文件**。若 WP 提示词与本文件或真实代码冲突，**一律以真实代码为准，其次以本文件为准**，并在交付报告「偏差说明」中逐条列出。**严禁为了贴合提示词去臆造字段、路由或文件。**

---

## 一、已核验的代码事实（不要再猜）

### 1.1 前端路由（`createWebHashHistory('/ui-next/')`，真实 URL 形如 `/ui-next/#/quality/patients`）

| 菜单 ID（`menuId`） | 路由 `name` | 真实 `path`（`router.push` 时前面加 `/`） | 页面 |
| --- | --- | --- | --- |
| `dashboard` | `workbench` | `workbench` | 质控总览 `features/workbench/WorkbenchPage.vue` |
| `timeliness-approvals` | `timeliness-approvals` | `timeliness/approvals` | 解锁审批与豁免 |
| `timeliness-events` | `quality-timeliness-events` | `quality/timeliness-events` | 在院时效台账 |
| `timeliness-monthly` | `quality-timeliness-monthly` | `quality/timeliness-monthly` | 时效月度考核 |
| `patient-qc` | `quality-patients` | `quality/patients` | 患者质控全景（WP-05 后改名「内涵质控工作台」） |
| `audit` | `quality-records` | `quality/records` | AI 内涵质控记录（WP-05 后隐藏+重定向） |
| （独立页，非菜单） | `quality-patient-detail-standalone` | `quality/patient-detail` | 患者详情独立页（`layout: 'standalone'`） |
| `relay-alert-logs` | `closure-alerts` | `closure/alerts` | 企微告警 |
| `feedback` | `closure-feedback` | `closure/feedback` | 整改反馈 |
| `push` | `tasks-push` | `tasks/push` | 手动补推与重查 |
| `push-progress` | `tasks-progress` | `tasks/progress` | 任务进度（hidden） |
| `scheduler` | `tasks-scheduler` | `tasks/scheduler` | 定时调度 |
| `audit-types` | `governance-audit-types` | `governance/audit-types` | AI 质控规则 |
| `workbench` ⚠️ | `governance-workbench` | `governance/workbench` | **归档前形式核查**（注意：菜单 ID `workbench` 是预检页，不是总览！总览是 `dashboard`） |
| `config` | `governance-config` | `governance/config` | 数据源与系统配置 |
| `relay` | `governance-relay` | `governance/relay` | 企微接收人配置 |
| `timeliness-rules` | `governance-timeliness-rules` | `governance/timeliness-rules` | 时效锁定规则 |
| `access` | `system-access` | `system/access` | 用户与权限 |
| `health` / `config-runtime` / `debug` | … | `system/health` / `system/runtime` / `system/debug` | 运维 |

**本计划新增路由（统一命名，所有包必须一致）**：
- `timeliness-stats` → path `timeliness/stats`，name `timeliness-stats`（时效统计分析，WP-02 建占位，WP-03 填充）；
- `prearchive-rules` → path `governance/prearchive-rules`，name `governance-prearchive-rules`（归档前形式预检规则，WP-02 建占位，WP-06 填充）。

### 1.2 后端路由前缀（`app/main.py`）与关键现有端点

- `/api/stats/*`：`today`、`summary`、`daily`、`dept`、`severity`、`monthly`、`anomaly-top`、`dimensions`（WP-01 新增 `workbench-overview`）。
- `/api/timeliness/*`：`dicts`、`rules*`、`events`、`events/{id}`、`events/{id}/exempt`、**`stats/monthly`**（月度统计 JSON）、**`export/monthly`**（月度 CSV 导出，已调用 `record_export_audit`）、`scan-runs`、`approvals`、`approvals/{id}/exempt`、`approvals/{id}/approve`、`approvals/sync`。
  - ⚠️ **不存在** `/api/timeliness/reports/monthly`，WP-04 必须在 `stats/monthly` 与 `export/monthly` 上扩展。
- `/api/patient-qc/*`：`patients`（聚合列表）、**`patient-detail`**（详情，query 参数）、`relay-alert/logs`、`relay-alert/logs/export`、`relay-alert/summary`、`relay-alert/retry/{id}`、`alert-status-report`、`feedback/quick-action`、`export/*`。
  - 其中 `relay-alert/logs`、`logs/export`、`summary`、`retry`、`alert-status-report` 当前都是 `require_role("admin")`。
- `/api/users`：`GET ""` 已支持 `page`、**`limit`**（不是 `page_size`）、`q`，返回 `UserListResponse{total,page,limit,items}`，items 已含 `timeliness_access`、`directory_pending`。
- `/api/roles`：已有 `PUT /{role_id}/timeliness-access`、`/{role_id}/menus/{menu_id}`（POST/DELETE 逐项）、`/{role_id}/departments/{dept_id}`（POST/DELETE 逐项）、`/{role_id}/permissions/{permission_id}`。
- `/api/departments`：`GET ""` 返回 **`List[DepartmentInfo]`（非分页）**——**不要改它的返回结构**，分页搜索请新增 `GET /api/departments/paged`。
- `/api/config/departments/list`：按数据源动态查科室列表（手动补推页在用）。
- `/api/integrations/jhemr/*`：鉴权统一走 `app/routers/jhemr_integration.py::_verify_request(request, body)`（含 `JHEMR_INTEGRATION_ENABLED` 开关→503）。
- 预检 BFF：`app/services/prearchive_admin_client.py` 只允许白名单目标，例如 `GET /api/admin/checks`、`GET /api/admin/issues`、`POST /api/admin/issues/{issue_id}/actions`（权限 `prearchive_check_view` / `prearchive_issue_feedback`）。**新增调用必须复用白名单，不得绕过**。

### 1.3 数据模型真实字段（写 SQL / ORM 时只能用这些）

- `TLEvent`：`event_uid, rule_code, rule_version_id, patient_id, visit_id, dept_code, responsible_doctor_id, t0, deadline, status, matched_file_unique_id, completed_at, overdue_minutes, warn_sent_at, last_scan_at, created_at, updated_at, source_ref_json`
  - ⚠️ 没有 `t0_time` / `deadline_at` / `lock_status` / `dept_name`。
- `TLApproval`：`patient_id, visit_id, monitor_code, apply_date_time, type, flag, apply_user_id, approve_user_id, approve_date_time, hospital_no, dept_code, approve_channel, penalty_amount, penalty_exempt, synced_at, apply_reason, exempt_reason`
  - ⚠️ 没有 `exempt_by` / `exempt_at`。
  - **业务口径（重要）**：`TLApproval` 每一行 = JHEMR `jhmr_monitor_limit_log` 中一次「超时被锁 → 医生申请解锁」记录。**`flag='1'` = 锁定待审批；`flag='2'` = 已审批解锁**。所以「科室锁定排名 / 医生锁定排名」= 按 `dept_code` / `apply_user_id` 统计 `TLApproval` 行数（与现有 `_monthly_rows` 中 `approval_count` 口径一致）。扣罚 = `flag='2'` 且 `penalty_exempt` 非真的 `COALESCE(penalty_amount, 200)`。
- `TLScanRun`：`started_at, finished_at, status, patients_scanned, events_created, events_updated, error_text`
- 时效状态枚举（`app/timeliness/engine/state.py`）：`PENDING, WARNING, OVERDUE, APPLYING, APPROVED, COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT`；**终态常量已存在：`TERMINAL_STATUSES`**（直接 import，不要自己再定义）。
- `PushLog`：`id, push_time, trigger_type, query_date, patient_id, patient_name, admission_no, visit_number, audit_type_code, source_record_key, dept, …, status, pushed_flag, reviewed_flag, reviewed_at, reviewed_by, manual_override, skip_reason, audit_run_mode, superseded_by, superseded_at, inconsistency, severity, elapsed_ms, retry_count, parse_status, risk_score, ai_version, alert_level, ai_result, error_msg, mr_text, request_json, response_json, parse_error, contract_valid, contract_errors`（CLOB：`ai_result, mr_text, request_json, response_json`）。
- `User`：`id, username, password_hash, full_name, email, dept_id, role_id, timeliness_access_json, directory_pending, password_setup_required, is_active, …`
  - ⚠️ **没有 `emp_no` 字段**。全院同步的 2,382 名员工 `username` 就是 HIS 工号（如 `003966`）；`admin` 等是系统账号。
- `Role`：`id, name, description, timeliness_access_json, created_at`；角色名实际有：`admin, auditor, dept_manager, clinician, timeliness_reader, medical_affairs`。
- `Department`：`id, name, code, manager_id, created_at`；`RoleDepartment(role_id, dept_id)`；`RoleMenu(role_id, menu_id)`。
- `ExportAuditLog` 由 `app/services/export_audit_service.py::record_export_audit(db=, user_id=, username=, export_type=, export_format=, filter_criteria=, record_count=, status=, request=)` 写入（参照 `timeliness.py::export_monthly` 的调用写法）。
- 文件位置更正：`app/services/audit_type_registry.py`（不是 `app/audit_type_registry.py`）；`app/services/push_log_writer.py`（不是 `app/push_log_writer.py`）；`app/services/current_result_filter.py::apply_current_result_filter(query, include_superseded=False)`。

### 1.4 预检服务 `prearchive_service/` 已有能力（**复用，不要重写平行模块**）

- 规则导入：`prearchive/rule_service.py::RuleService.import_files(paths, *, apply, actor, …)`（`scripts/run_prearchive_demo_sidecar_20260904.py --import-rules` 就在用它）。
- 金标准回测：`prearchive/backtest.py::backtest_v2(manual, results, …)` + `render_markdown_v2`。
- 投递：`prearchive/outbox.py::DeliveryWorker`（已有 HTTP 传输、重试退避、DEAD 状态）+ `prearchive/delivery_wiring.py`（投递治理/事件发射）。
- 无纸化：`prearchive/paperless.py`、`prearchive/paperless_rpa.py`、`prearchive/sync_paperless_rules.py`。
- 配置样例在 `prearchive_service/config.example.json`（`service.anchor_mode`、`sources.*`、`push`、`result_delivery`）；**没有 `prearchive_service/config/` 子目录**。
- DDL 在 `prearchive_service/sql/`。

### 1.5 测试位置与命令（Windows PowerShell）

- 后端测试在 `tests/`、`tests/timeliness/`、`prearchive_service/tests/`；与本计划相关的既有测试：`tests/test_stats_metadata.py`、`tests/test_logs_regression.py`、`tests/test_logs_schema.py`、`tests/test_logs_export_scope_20261004.py`、`tests/test_patient_qc_export_filters.py`、`tests/test_dept_visibility.py`、`tests/test_access_contracts.py`、`tests/test_prearchive_rbac_matrix.py`、`tests/test_menu_api.py`、`tests/test_audit_type_registry.py`、`tests/test_audit_types_api.py`、`tests/test_push_executor.py`、`tests/timeliness/test_scanner.py`、`tests/timeliness/test_api_timeliness.py`、`tests/timeliness/test_access_configuration.py`、`tests/timeliness/test_mobile_*.py`。
- ⚠️ **PowerShell 不会展开 `tests/test_logs*.py` 这类通配符**，pytest 命令里必须写完整文件名。
- 前端单测**统一放 `frontend/tests/unit/*.test.ts`**（vite 配置也收 `src/**/*.test.ts`，但仓库惯例是 `tests/unit/`）。
- 前端命令一律用 package.json 脚本：
  ```powershell
  cd frontend
  npm run typecheck            # = vue-tsc -b
  npm run test:unit -- tests/unit/xxx.test.ts   # 定向
  npm run test:unit            # 全量
  npm run build                # 含 sync-static 到 static/ui-next
  ```

---

## 二、通用铁律（每包都要遵守）

1. **红线**：禁止连接 `10.10.8.84` / `10.10.8.177` / `10.10.8.216` / `10.10.10.93` 做任何写入、DDL、重启、部署；禁止 `git commit/push/reset/clean/checkout --`；保留工作区全部既有未提交改动；日志/报告零明文口令、零患者姓名、患者号脱敏为 `<ID>`。
2. **以代码为准**：动手前先 `Select-String`/阅读目标函数，确认真实签名、字段、返回结构；**已有端点只做向后兼容扩展**（加可选参数、加字段），不改名、不删字段、不改 `response_model` 类型。
3. **Oracle 兼容**：禁 `FETCH FIRST`；布尔用 `== True`；SQL 层禁 `!= ''`；日期截断要写 SQLite/Oracle 方言分支；新 CLOB 列放模型末尾。
4. **视图**：`V_QYBR` 只能经 `oracle_patient_view_compat.py` 访问，单列 `患者ID IN (...)` ≤50，只用 40 列契约内的列（无「床号」）。
5. **前端**：复用 `PageHeader / SummaryStrip / FilterPanel / DataTableShell / DetailDrawer / RiskTag / StatusTag / HolographyButton`；持久中文标签；不裸露英文枚举与 JSON；长选项 `filterable`；禁平铺 >20 个复选框；保持 `X-Requested-With`；配置/规则抽屉 `rawExtras` 无损往返。
6. **断点续跑**：每包在 `review/064-wpNN/exec-log.md` 记录检查点（开工基线 `git status --short` 存为 `review/064-wpNN/git_status_before.txt`、每完成一个子任务追加一行、最终门禁输出）；中断后从最后一个检查点继续，不重做已完成步骤。
7. **交付报告**：每包产出 `review/064-wpNN/DELIVERY.md`（修改文件清单、测试数字、偏差说明、未完成项），并登记 `开发起步包/01_统一修改记录.md`（追加一行）与 `02_协作任务板.md`。
8. **每包结束必须保证**：`npm run build` 通过、既有测试零回归、`python scripts/run_gates_20260906.py --quick` 4/4 PASS。
9. **重构页面前先保护测试契约**：用 `Select-String -Path frontend/tests/unit/*.ts,frontend/tests/e2e/*.ts -Pattern "<页面关键词>|data-testid"` 找出该页面被测试引用的 `data-testid`、文案和选择器，新页面必须保留；确需变更的同步改测试并在交付报告逐条列出。既有 E2E 已知失败 2 条（Relay 中文标签、工作台 `.meta-grid` 定位，见 `review/gate-runs/20261118-183713/frontend_e2e-recheck.log`），不得新增失败。
10. **包的顺序固定**：WP-01 → WP-02 → … → WP-09（本地开发），WP-10（生产发布，逐步审批）。一次只做一个包，不跨包改文件。
