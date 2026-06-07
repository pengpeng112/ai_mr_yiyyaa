# Configuration Reorganization Plan — Phase 1

> 2026-06-04 · Med-Audit Backend · Phase 1 read-only resolver baseline

## 1. Current State

The system configuration consists of a single JSON file (`config/config.json`) with ~800 lines. The same dict services every subsystem: Oracle/PostgreSQL datasource, Dify workflow targets, audit-type definitions, scheduler (daily + discharge), push executor, skip policies, patient census, relay alert, and privacy masking. There is no uniform abstraction layer — each module reads directly from the raw config dict, which leads to the issues described below.

## 2. Configuration Field Inventory

| Field | Config Path | Primary Read Locations | Write Locations | Category | Impact |
|---|---|---|---|---|---|
| `enabled` | `scheduler_daily.enabled` | `app/scheduler.py` | `app/routers/config.py`, `app/routers/scheduler.py` | scheduler | daily dispatch on/off |
| `cron` | `scheduler_daily.cron` | `app/scheduler.py` | `app/routers/config.py` | scheduler | daily trigger time |
| `audit_run_mode` | `scheduler_daily.audit_run_mode` | `app/scheduler.py` | `app/routers/config.py` | scheduler / run-mode | `daily_increment` |
| `audit_type_codes` | `scheduler_daily.audit_type_codes` | `app/scheduler.py` | `app/routers/config.py` | scheduler / audit-type | empty = use `default_for_schedule` |
| `dept_filter` | `scheduler_daily.dept_filter` | `app/scheduler.py`, `app/services/data_source_loader.py` | `app/routers/config.py` | department scope | fed into `{dept_filter}` SQL placeholder |
| `enabled` | `scheduler_discharge.enabled` | `app/scheduler.py` | `app/routers/config.py`, `app/routers/scheduler.py` | scheduler | discharge dispatch on/off |
| `audit_run_mode` | `scheduler_discharge.audit_run_mode` | `app/scheduler.py` | `app/routers/config.py` | scheduler / run-mode | `discharge_final` |
| `audit_type_codes` | `scheduler_discharge.audit_type_codes` | `app/scheduler.py` | `app/routers/config.py` | audit-type | explicit list for discharge |
| `dept_filter` | `scheduler_discharge.dept_filter` | `app/scheduler.py` | `app/routers/config.py` | department scope | discharge-specific |
| `audit_types[].code` | `audit_types[].code` | `app/services/audit_type_registry.py`, `app/scheduler.py`, `app/services/payload_composer.py`, `app/services/data_source_loader.py` | `app/routers/config.py` | audit-type | identifies the audit type across all subsystems |
| `audit_types[].enabled` | `audit_types[].enabled` | `app/services/audit_type_registry.py` | `app/routers/config.py` | audit-type | toggle per type |
| `audit_types[].default_for_schedule` | `audit_types[].default_for_schedule` | `app/services/audit_type_registry.py` | `app/routers/config.py` | audit-type / scheduler | fallback when `audit_type_codes=[]` |
| `audit_types[].sources` | `audit_types[].sources` | `app/services/data_source_loader.py` | `app/routers/config.py` | audit-type | per-source SQL + field mapping |
| `audit_types[].payload.builder` | `audit_types[].payload.builder` | `app/services/payload_composer.py`, `app/services/record_identity.py` | `app/routers/config.py` | audit-type | selects payload builder |
| `audit_types[].dify` | `audit_types[].dify` | `app/services/dify_pusher.py`, `app/scheduler.py` | `app/routers/config.py` | dify | per-audit-type Dify target |
| `audit_types[].response` | `audit_types[].response` | `app/services/audit_result_mapper.py` | `app/routers/config.py` | audit-type | JSONPath parsing config |
| `audit_types[].display` | `audit_types[].display` | frontend | `app/routers/config.py` | audit-type | UI block layout |
| `dify.base_url` | `dify.base_url` | `app/services/dify_pusher.py`, `app/services/config_parser.py` | `app/routers/config.py` | dify | global Dify endpoint |
| `dify.api_key_enc` | `dify.api_key_enc` | `app/services/dify_pusher.py` | `app/routers/config.py` | dify | encrypted API key |
| `dify.workflow_input_variable` | `dify.workflow_input_variable` | `app/services/dify_pusher.py` | `app/routers/config.py` | dify | maps to `mr_txt` |
| `push.interval_ms` | `push.interval_ms` | `app/services/push_executor.py`, `app/scheduler.py` | `app/routers/config.py` | push | rate-limiting |
| `push.max_retry` | `push.max_retry` | `app/services/push_executor.py` | `app/routers/config.py` | push | Dify retry count |
| `relay_alert.enabled` | `relay_alert.enabled` | `app/services/relay_alert_service.py` | `app/routers/config.py` | relay | toggle alert push |
| `emr_vastbase.*` | `emr_vastbase.*` | `app/services/data_source_loader.py`, frontend export | `app/routers/config.py` | datasource | vastbase EMR export |
| `departments.mode` | `departments.mode` | `app/services/config_parser.py` | `app/routers/config.py` | department | include/exclude |

## 3. Problem Statement

Top five configuration pain points:

1. **Department filter is scattered.** The same concept (“which departments should be audited?”) lives in `scheduler_daily.dept_filter`, `scheduler_discharge.dept_filter`, `departments.mode/list`, and inside per-audit-type SQL `{dept_filter}` placeholders. Inpatient vs. discharge department semantics differ but are not declared anywhere.

2. **Audit-type config is overloaded.** A single `audit_types[]` entry carries SQL sources, payload builder choice, Dify target, JSONPath response mapping, display layout, and `default_for_schedule`. Changing one aspect (e.g., display) requires reading/writing the full entry.

3. **No formal run-mode abstraction.** `audit_run_mode` is passed as a string through scheduler → push executor → skip policy → record identity. The behavior differences (“does this mode call Dify? does it write PushLog? what skip policy applies?”) are implicit if/else branches across four modules.

4. **Empty-collection semantics are undocumented.** `audit_type_codes=[]` means “use default_for_schedule”. `dept_filter=[]` sometimes means “all departments” and sometimes “not configured”. The resolver intentionally preserves them verbatim, but the ambiguity is a source of bugs.

5. **Secrets leak risk in resolution.** The global `dify.api_key_enc` and per-audit-type `api_key_enc` are encrypted, but any future resolver or config-exposure layer must explicitly avoid returning plain text. The Phase 1 resolver enforces `has_api_key` only.

## 4. Phase 1 Resolver Design

`app/services/runtime_config_resolver.py` provides five pure functions that interpret the existing config dict:

| Function | Purpose |
|---|---|
| `resolve_run_mode_config(config, run_mode)` | Standardized metadata for daily_increment / discharge_final / manual / precheck |
| `resolve_scheduler_config(config, scheduler_key)` | Normalized view of scheduler_daily or scheduler_discharge |
| `resolve_dept_scope(config, scope_name, override)` | Resolved dept codes with scope metadata |
| `resolve_audit_type_config(config, audit_type_code)` | Deep-copied audit type entry |
| `resolve_dify_target(config, audit_type_code)` | Effective Dify target without secrets |

Key design decisions:

- **Read-only.** Every function returns a **new** dict; no config mutation.
- **No business imports.** The resolver only uses `copy.deepcopy` and built-in types.
- **No expansion.** `audit_type_codes=[]` stays empty; `dept_filter=[]` stays empty. The calling code (scheduler, manual push) remains responsible for expansion semantics.
- **No secrets.** `resolve_dify_target` returns `has_api_key: bool`, never plain text.
- **Phase 1 isolation.** This module is imported only by its tests; it is NOT wired into scheduler / push / precheck yet.

## 5. Phase 2 Frontend Reorganization Plan

Planned — not implemented in Phase 1:

1. **Split config UI into five tabs/pages:**
   - **Department Scopes** — daily, discharge, census; field semantics; allow-override flag
   - **Run Modes** — daily_increment / discharge_final / manual / precheck flags (Dify, PushLog, SchedulerHistory, Relay)
   - **Audit Types** — enabled, builder, sources summary, Dify target reference (no SQL editing for non-admin users)
   - **Scheduler Plans** — per-scheduler enable/cron + audit_type_codes picker
   - **Dify Targets** — global + per-audit-type, URL validation, key masking

2. **Keep existing API routes compatible.** All current `/api/config/*` and `/api/scheduler/*` routes continue returning the same shape; the frontend reorganization purely changes presentation.

## 6. Phase 3 Config Migration Strategy

Planned — not implemented in Phase 1:

1. Add optional `dept_scopes`, `run_modes` sections alongside existing config.
2. Read path: new section first, legacy fallback second (already prototyped in resolver).
3. Save path: initially write both legacy + new; later switch to new-only.
4. Template update: `config.json.template` adds commented-out new sections.
5. Cleanup: remove legacy fields only after a full release cycle with no regression reports.

## 7. Compatibility Rules

- No `*_discharge` audit types are created or required.
- `scheduler_discharge` continues to reuse `progress_vs_nursing`, `jyjc_vs_bcnursing`, `syssvsscbc`.
- `source_record_key` namespace isolation (mode-prefix in `record_identity.py`) is preserved.
- Precheck remains read-only; patient census remains masked by default.
- Dify builders still output `mr_text`; the `mr_txt` variable mapping is only in `dify_pusher.py`.
- All 292 existing tests must pass when Phase 1 module and tests are added.

## 8. Risk Assessment

| Risk | Mitigation |
|---|---|
| New module accidentally imported by existing code | Phase 1 constraint: no existing file imports it; verified by `git diff --stat` |
| Resolver returns mutable references to config | All functions return `deepcopy` or newly-constructed dicts |
| Empty `dept_filter` / `audit_type_codes` behavior misinterpreted | Resolver preserves verbatim; expansion remains caller's responsibility |
| Secret exposure via `resolve_dify_target` | Only `has_api_key` boolean returned |
| Resolver imports create circular dependency | Only `copy.deepcopy` and `typing.Any` are imported |
| Phase 1 tests use stale assumption about config shape | Tests use hand-crafted dicts matching `config.json.template` structure |

## 9. Regression Checklist

- [ ] `scheduler_daily` job runs with correct `audit_run_mode`
- [ ] `scheduler_discharge` job runs with correct `audit_run_mode`
- [ ] `progress_vs_nursing` discharge SQL override still active in scheduler
- [ ] Nursing same-day range matching preserved
- [ ] `jyjc_vs_bcnursing` / `syssvsscbc` use original config SQL in discharge
- [ ] Precheck does not call Dify, write PushLog, SchedulerHistory, QCFeedback, or RelayAlert
- [ ] Patient census masking enforced
- [ ] Unknown audit type returns error
- [ ] `source_record_key` mode isolation unchanged
- [ ] Manual push still works (test_push_executor + test_push_router_bulk_options)
- [ ] `/api/logs` and export endpoints unchanged
- [ ] Relay Alert behavior unchanged
- [ ] `python -m pytest -q --tb=short` passes

## 10. Phase 1 Safety Fixes (2026-06-04)

Three issues identified in code review have been addressed:

### 10.1 Non-daily skip-policy no longer depends on source_record_key

**Before:** The non-daily bypass (`return "", ""`) was inside the `if source_record_key:` block. If source_record_key was empty, non-daily modes could fall through to the patient-level unreviewed check and be intercepted by daily-mode unreviewed records.

**After:** The mode check `if mode != "daily_increment": return "", ""` now sits **after** the source_record_key block but **before** the patient-level unreviewed query. Non-daily modes never perform patient-level fallback regardless of whether source_record_key is present.

### 10.2 discharge_final no longer falls back to legacy scheduler config

**Before:** `_resolve_scheduler_cfg("discharge_final")` returned `config.get("scheduler_discharge") or config.get("scheduler") or {}`. If `scheduler_discharge` was absent, the legacy `scheduler` section could supply daily-mode audit types.

**After:** If `scheduler_discharge` is absent, a safe default is returned with `audit_type_codes=["progress_vs_nursing"]`, `audit_run_mode="discharge_final"`, `enabled=False`, and `dept_filter=[]`.

### 10.3 Empty audit_types in discharge_final writes failed SchedulerHistory

**Before:** When all configured audit_type_codes were invalid in discharge_final mode, the scheduler logged an error but produced zero SchedulerHistory rows, leaving no trace in the DB for operators.

**After:** A `SchedulerHistory` row is written with `audit_type_code="__scheduler__"`, `status="failed"`, `total_records=0`. The `_last_run_info` is populated with a descriptive error message visible in `/api/scheduler/status`.

### 10.4 SchedulerHistory Semantics

- Each successful scheduled run now produces **one SchedulerHistory row per audit type** (previously one aggregate row per run).
- If an audit_type fails in-dispatch, the exception is caught and the next audit_type continues (failure-isolation).
- The empty-audit-types edge case writes a single `__scheduler__`-level failure row.

### Test Coverage

New tests added:

- `tests/test_push_skip_policy.py` — 11 tests covering mode isolation and fallback safety.
- `tests/test_scheduler_safety.py` — 10 tests covering `_resolve_scheduler_cfg()` and `_resolve_audit_run_mode()`.

Full suite: 345 tests pass.

---

*Phase 1 scope: `app/services/runtime_config_resolver.py` + `tests/test_runtime_config_resolver.py` + `tests/test_push_skip_policy.py` + `tests/test_scheduler_safety.py` + this document. Core source modified: `app/services/push_skip_policy.py`, `app/scheduler.py`.*

---

## 11. Phase 2 Runtime Summary Endpoint

### 11.1 Purpose

新增只读配置归纳接口，为后续前端配置页重组提供统一的数据入口：

- **Endpoint:** `GET /api/config/runtime-summary`
- **Auth:** 需要 `manage_config` 权限
- **Method:** 只读，不保存、不迁移、不改变现有配置

### 11.2 Files

| File | Description |
|---|---|
| `app/services/runtime_summary_service.py` | 核心聚合逻辑，调用 Phase 1 resolver |
| `app/routers/config.py` | 新增 `/api/config/runtime-summary` 路由 |
| `tests/test_runtime_summary_service.py` | 28 个测试覆盖 |

### 11.3 Response Structure

```json
{
  "run_modes": {
    "daily_increment": { "run_mode": "daily_increment", "calls_dify": true, ... },
    "discharge_final": { ... },
    "manual": { ... },
    "precheck": { "calls_dify": false, "writes_push_log": false, ... }
  },
  "schedulers": {
    "scheduler_daily": { "scheduler_key": "scheduler_daily", "enabled": true, "audit_type_codes": [...], "dept_filter": [...], ... },
    "scheduler_discharge": { ... }
  },
  "dept_scopes": {
    "daily_increment": { "scope_name": "daily_increment", "dept_codes": [...], "field_semantics": "current_dept", ... },
    "discharge_final": { ... },
    "manual_default": { ... },
    "patient_census": { ... }
  },
  "audit_types": [
    {
      "code": "progress_vs_nursing",
      "name": "病程 vs 护理",
      "enabled": true,
      "default_for_schedule": true,
      "sort_order": 10,
      "builder": "generic_multi_source",
      "source_keys": ["primary"],
      "required_source_keys": ["primary"],
      "group_key": ["patient_id", "visit_number"],
      "dify_target": { "target_source": "audit_type", "base_url": "...", "has_api_key": true, ... },
      "response": { "dimension_path": "$.dimensions", ... },
      "display_paths": ["blocks"],
      "flags": { "uses_sql": true, "has_sensitive_secret": true, "has_display_config": true }
    }
  ],
  "warnings": [
    { "level": "info", "code": "scheduler_daily_empty_audit_type_codes", "message": "...", "path": "..." }
  ],
  "meta": {
    "readonly": true,
    "secrets_masked": true,
    "sql_included": false,
    "config_shape": "legacy-compatible"
  }
}
```

### 11.4 Compatibility

- 不改变现有 `/api/config/*` 和 `/api/scheduler/*` 返回结构
- 不修改 scheduler/manual push/precheck/Dify/Relay Alert 行为
- 不返回 SQL 全文（`query_sql`）
- 不返回任何 secret 或 encrypted secret 字段
- Phase 1 resolver 保持不变

### 11.5 Warnings Coverage

| Code | Level | Condition |
|---|---|---|
| `scheduler_daily_empty_audit_type_codes` | info | `audit_type_codes=[]` |
| `scheduler_daily_enabled_without_cron` | warning | `enabled=true, cron=""` |
| `scheduler_daily_invalid_audit_type` | error | 引用不存在的 audit type |
| `scheduler_daily_disabled_audit_type` | warning | 引用 disabled audit type |
| `scheduler_discharge_empty_audit_type_codes` | warning | `audit_type_codes=[]` |
| `scheduler_discharge_enabled_without_cron` | warning | `enabled=true, cron=""` |
| `scheduler_discharge_invalid_audit_type` | error | 引用不存在的 audit type |
| `scheduler_discharge_disabled_audit_type` | warning | 引用 disabled audit type |
| `dept_filter_empty_daily` | info | `dept_filter=[]` |
| `dept_filter_empty_discharge` | info | `dept_filter=[]` |
| `dept_filter_mismatch` | info | daily 与 discharge 科室不同 |
| `audit_type_missing_builder` | warning | enabled audit type 无 payload.builder |
| `audit_type_missing_sources` | error | enabled audit type 无 sources |
| `audit_type_source_missing_sql` | warning | source 无 query_sql |
| `dify_base_url_empty` | warning | 审计类型无 Dify base_url |
| `workflow_input_variable_not_default` | info | workflow_input_variable != mr_txt |

### 11.6 Test Coverage

`tests/test_runtime_summary_service.py` — 28 tests in 9 classes:

- `TestTopLevelStructure` (2): top-level keys, meta fields
- `TestRunModes` (3): four modes exist, precheck readonly, daily flags
- `TestSchedulers` (3): empty codes preserved, run_mode
- `TestDeptScopes` (2): empty dept_filter, four scopes
- `TestAuditTypes` (7): includes disabled, omits SQL, omits secrets, builder/source_keys, multi-source, flags
- `TestDifyTarget` (2): has dify target, no secrets in target
- `TestWarnings` (10): all warning codes verified
- `TestImmutability` (1): no config mutation
- `TestNoSecrets` (2): recursive secret scan, utility test
- `TestEdgeCases` (3): empty config, missing scheduler_discharge, no audit types

---

## 12. Phase 2.5 Runtime Summary Hardening

### 12.1 Purpose

增强 Phase 2 runtime-summary 接口的稳定性、前端可消费性和测试覆盖。保持只读，不改变业务行为。

### 12.2 Changes

| Change | File | Detail |
|---|---|---|
| Resolver alignment | `runtime_summary_service.py` | `_build_audit_types()` now calls `resolve_audit_type_config()` per code |
| Precise `uses_sql` | `runtime_summary_service.py` | Checks `source.type == "sql"` or `source.query_sql` exists, not just source key count |
| Safe `sources` array | `runtime_summary_service.py` | Each audit type gets `sources: [{key, type, backend, required, has_query_sql}]` — no query_sql or field_mapping |
| Warning path normalization | `runtime_summary_service.py` | All paths use dot notation (e.g. `audit_types.progress_vs_nursing.payload.builder`), no brackets or slashes |
| Dual-path `related_path` | `runtime_summary_service.py` | `dept_filter_mismatch` and `dify_base_url_empty` use `path` + `related_path` instead of concatenated string |
| WIV source distinction | `runtime_summary_service.py` | `workflow_input_variable_not_default` path points to `dify.workflow_input_variable` (global) or `audit_types.{code}.dify.workflow_input_variable` (per-type) |
| Router tests | `test_runtime_summary_router.py` | 10 HTTP-level tests using FastAPI TestClient with mocked config and auth overrides |
| Service tests | `test_runtime_summary_service.py` | +7 tests for sources summary, uses_sql precision, warning path format, related_path, WIV source |

### 12.3 Test Coverage

| File | Tests |
|---|---|
| `tests/test_runtime_summary_service.py` | 46 tests (was 39) |
| `tests/test_runtime_summary_router.py` | 10 tests (new) |
| Full suite | 405 passed (was 383) |

New test classes:
- `TestSourcesSummary` (4): exists, omits query_sql, omits field_mapping, fields
- `TestUsesSql` (3): true for SQL source, false for non-SQL, helper function
- `TestWarningPaths` (5): dot notation, dept mismatch related_path, dify related_path, per-type WIV path, global WIV path

### 12.4 Compatibility

- No config.json / config.json.template changes
- No `*_discharge` audit types
- No changes to existing API routes
- No scheduler/push/precheck/Dify/Relay Alert changes
- No SQL body, no secrets
- 405 passed, 0 failed

---

## 13. Phase 3 Frontend Runtime Summary Integration

### 13.1 Purpose

在系统配置页、调度页、审计类型页接入 `GET /api/config/runtime-summary` 的只读展示，向管理员提供统一的配置风险提示和审计类型安全摘要，不修改任何保存接口。

### 13.2 Security Boundaries

| 规则 | 说明 |
|---|---|
| 只读 | Runtime Summary 仅通过 `apiGet` 加载，不做 `apiPost/apiPut/apiDelete` |
| 不保存 | 所有 summary 区域无"保存"按钮，不接入 POST 接口 |
| 不展示 SQL 全文 | `query_sql`、`field_mapping` 不出现在任何 runtime-summary 前端页面 |
| 不展示 secret | `api_key`、`api_key_enc`、`password`、`password_enc`、`secret_key`、`secret_key_enc` 不出现在任何 runtime-summary 前端页面 |
| 布尔化 secret | `has_api_key`、`has_query_sql`、`has_sensitive_secret`、`has_base_url` 仅作为布尔字段展示 |
| 失败隔离 | runtime-summary 加载失败仅显示 warning，不阻塞页面其余功能 |

### 13.3 Completed Pages

| 阶段 | 页面 | 功能 |
|---|---|---|
| Phase 3.1 | 系统配置页 → "运行总览" Tab | `meta`、`warnings`、`run_modes`、`schedulers`、`dept_scopes`、`audit_types` 只读展示 |
| Phase 3.2 | 调度页 → "配置风险提示" | scheduler_daily / scheduler_discharge 相关 warnings + 审计类型统计提示 |
| Phase 3.3 | 审计类型页 → "审计类型风险提示" | `audit_types.*` warnings 折叠展示 |
| Phase 3.3 Fix | 审计类型页 → "运行解析摘要" | 安全字段表格: code/name/enabled/default_for_schedule/builder/flags/sources |
| Phase 3.3.1 | 审计类型页 → 数据源 tag | 显式展示: key/type/backend/必需\|可选/SQL:有\|无 |
| Phase 3.4 | 审计类型页 → Dify 安全摘要 | target_source/workflow_input_variable/has_api_key(布尔)/base_url(布尔) |

### 13.4 Modified Files

| File | Detail |
|---|---|
| `static/templates/pages/config.html` | "运行总览" Tab，含 meta/warnings/run_modes/schedulers/dept_scopes/audit_types |
| `static/scripts/modules/config.js` | `loadRuntimeSummary()` 方法 |
| `static/templates/pages/scheduler.html` | "配置风险提示"折叠区域 + 审计类型统计提示 |
| `static/scripts/modules/scheduler.js` | `loadSchedulerRuntimeSummary()` + 4 个 helper |
| `static/templates/pages/audit_types.html` | "审计类型风险提示" + "运行解析摘要"table + Dify 安全布尔列 |
| `static/scripts/modules/audit_types.js` | `loadAuditTypeRuntimeSummary()` + 13 个安全 helper |
| `static/scripts/app.js` | 三方 data 字段 (config/scheduler/audit_type runtime summary) |
| `static/index.html` | 缓存版本增量更新 |
| `static/styles/pages/config.css` | `.rt-loading-spinner` 等只读样式 |

### 13.5 Unchanged Logic

以下接口/模块未做任何修改：
- `GET/POST /api/audit-types` — 新建
- `GET/PUT/DELETE /api/audit-types/{code}` — 编辑/删除
- `POST /api/audit-types/{code}/clone` — 克隆
- `POST /api/audit-types/{code}/test-source` — 数据源测试
- `POST /api/audit-types/{code}/test-dify` — Dify 测试
- `GET/POST /api/config/scheduler-daily` — 每日调度
- `GET/POST /api/config/scheduler-discharge` — 出院调度
- `POST /api/scheduler/start` / `/stop` / `/trigger` — 调度控制
- `GET /api/config/runtime-summary` — 仅读，后端无变更
- `app/services/runtime_summary_service.py` — Phase 2 基础，Phase 3 未修改

### 13.6 Test Coverage

| File | Tests | Focus |
|---|---|---|
| `tests/test_runtime_summary_frontend_static.py` | 12 | 系统配置页静态: 标题/字段/secret禁用/spinner |
| `tests/test_scheduler_runtime_summary_frontend_static.py` | 15 | 调度页静态: warning区域/字段/secret禁用/保存隔离 |
| `tests/test_audit_types_runtime_summary_frontend_static.py` | 50 | 审计类型页静态: warning区域/summary table/5字段source/4字段Dify/secret禁用/base_url排除/保存隔离 |
| `tests/test_runtime_summary_service.py` | 51 | 后端: sources/uses_sql/warnings/paths |
| `tests/test_runtime_summary_router.py` | 10 | 后端: HTTP 200/字段结构/auth |
| **Total** | **138** | 全量测试无失败，仅既有 Pydantic deprecation warnings |

### 13.7 Compatibility

- 不创建 `*_discharge` 审计类型
- 不修改 `config/config.json` 和 `config/config.json.template`（config.json.template 仅有 Phase 2 双调度既有变更）
- 不修改 scheduler/push/Dify/Relay Alert 主流程
- 不提交未跟踪临时文件：`analyze_10am*.py`、`user.xlsx`、`user_dict.xlsx`、`backups/`
- 缓存版本号：`?v=20260607-audit-runtime-summary-dify-safe`（最新 index.html）

---

## 14. Scheduler Key Semantics (config.json.template)

`config/config.json.template` 同时保留三个 scheduler 配置键：

| Key | 状态 | 说明 |
|---|---|---|
| `scheduler` | 旧版兼容 | 单调度器字段，仅保留用于向后兼容。新代码应使用 `scheduler_daily`。 |
| `scheduler_daily` | 当前 | 每日增量质控调度器。`scheduler.py` 启动时优先检测此键是否存在，存在则启用双调度器路径。 |
| `scheduler_discharge` | 当前 | 出院终末质控调度器（复用原有审计类型）。`scheduler.py` 启动时优先检测此键是否存在。 |

调度器路径判断逻辑 (`app/scheduler.py` -> `start_scheduler()`)：
- 若 `scheduler_daily` 或 `scheduler_discharge` 存在 → 使用双调度器路径 (`_add_cron_job_with_mode`)
- 否则 → 回退到旧版单调度器路径 (`_add_cron_job`，deprecated）
