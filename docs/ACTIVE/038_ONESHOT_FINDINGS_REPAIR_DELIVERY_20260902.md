# 038 — oneshot 问题一次性修复执行交付报告

> 文档编号：038 ｜ 编制日期：2026-09-02 ｜ 执行者：ZCode/GLM-5.3
> 上游作业书：`docs/ACTIVE/037_ONESHOT_FINDINGS_REPAIR_EXECUTION_PLAN_20260902.md`
> 执行时 HEAD：`52998cc`（工作区含 037/039 计划等已登记未跟踪文件，全部保留未动）
> 生产写入：**无**（零生产访问、零 git commit、零 push）

## 0. 执行摘要

按 037 作业书一次性完成 RP-C/B/D/E/F/A/H/G/I 全部 9 个修复包，§15 门禁九项一次全绿。
主服务测试 1211（基线）→ **1254 passed**（+43 新增，0 failed）；prearchive 211 passed + 1 skipped 不变；
UI Next E2E 52 passed + 17 skipped（oneshot 扫荡默认跳过，RP-I 生效）0 failed。

## 1. 逐包执行结果（对照 037 §19 验收勾选）

- [x] **RP-C IsolatedModeError → 400**：`app/main.py` 注册专用 handler（`generic_exception_handler` 之前），
  保留原始英文 message；新增 `tests/test_isolated_mode_http.py` 3 用例（400 原文/其他异常仍 500/主应用注册锚）。
- [x] **RP-B 空 `{}` 422 + unset-merge**：`app/routers/config.py` 新增 `_reject_empty_update`/`_merge_section_update`
  公共辅助；改造 11 个写端点：data-source、oracle、postgresql、emr-vastbase、dify、departments、
  `_save_scheduler_section`（scheduler/scheduler-daily/scheduler-discharge 三入口共用）、push、
  privacy-masking、notify、relay-alert（空 body 统一 422，仅提交 secret_key 的密钥轮换仍放行）。
  密钥空串不覆盖既有 `*_enc`；SQL 清洗只对提交字段执行；scheduler 未提交排程字段时 cron 保持现值不重算。
  新增 `tests/test_config_partial_update.py` 16 用例（含 T1-T8 全矩阵 + dify/emr/data-source/departments/notify/postgresql 空 body + relay 红线回归）。
- [x] **RP-D departments/list fixture 分支**：`config.py` fixture → 内置 12 科室（不 import cx_Oracle）；
  Oracle 后端故障 → **503**；未知类型 → **400**。`logs.py` `_list_distinct_depts` 同步 fixture 分支（fail-open 保持）。
  新增 `tests/test_departments_list_datasource.py` 5 用例。
- [x] **RP-E census ×3 → 400**：`patient_census_service._assert_data_source_oracle` 改抛英文 ValueError；
  `patients.py` census/metadata 补 `except ValueError → 400`（census/census-summary 原有分支自动生效）。
  新增 `tests/test_patient_census_datasource_400.py` 4 用例（含 oracle 真故障仍 500 防误改）。
- [x] **RP-F 就诊导出数据源前置 + traceback**：`export_patient_visit_summary` 在空 keys 早退之后、
  连接 Oracle 之前校验数据源（非 oracle → ValueError → 路由 400）；空 keys → 200 表头契约（031 T1-0）不破坏；
  `patient_qc.py` RuntimeError 分支补 `logger.error(..., exc_info=True)`。
  新增 `tests/test_patient_visit_export_datasource.py` 4 用例（含失败审计落档 + mock logger 断言 exc_info=True）。
- [x] **RP-A SQLite busy_timeout/WAL 连接级**：`database.py` sqlite 引擎 `connect_args.timeout=30.0` +
  `event.listens_for("connect")` 每连接 `PRAGMA busy_timeout=30000`（WAL/synchronous 文件库生效、内存库忽略失败）；
  `is_transient_app_db_error` 增加 `database is locked/busy` 标记。
  新增 `tests/test_sqlite_busy_timeout.py` 3 用例（双连接 PRAGMA 读回 ≥30000、两线程×40 行并发写零 locked 且 80 行齐、瞬时标记）。
- [x] **RP-H H5 反馈 CSRF**：`security_middleware._CSRF_EXEMPT_PATHS` 增加 `/api/mobile/qc-feedback`
  （docstring 记录"token 是认证主体、Cookie 属附带"决策；logout 强校验保持）；
  `qc_detail.js` fetch 加 `X-Requested-With` 头；`qc_detail.html` js 版本参数 `20260708-stage4-v1 → 20260902-csrf-header`（缓存击穿）。
  新增 `tests/test_mobile_qc_csrf.py` 5 用例（带 Cookie 无头不再 403/logout 仍 403/带头通过/无 Cookie 放行/静态锚）。
- [x] **RP-G 删除不存在审计类型 404**：`audit_type_registry.delete` 存在性预检抛 `KeyError`；
  路由 `except KeyError → 404 "audit type not found"`；`progress_vs_nursing` 仍 422。
  `tests/test_audit_types_api.py` `_FakeRegistry` 对齐 + 新增 3 用例（404/options 字面路径 404/存在非内置 200 且 deleted_code 记录）。
- [x] **RP-I oneshot ui-next spec 守卫**：`frontend/tests/e2e/oneshot-uinext-sweep.spec.ts` 头部加
  `test.skip(process.env.ONESHOT_E2E !== 'true', ...)`；复跑说明注释更新。默认 `test:e2e` 0 failed，该文件三端 skipped。
  legacy spec 既有 `LEGACY_E2E` 守卫未动。

## 2. 门禁数字（037 §15 全项）

| 门禁 | 结果 |
|---|---|
| `python -m compileall app tests scripts` | exit 0 |
| `python -m pytest` | **1254 passed**，0 failed（基线 1211+RP-C 3 条=1214 起点，新增 43 条） |
| `python scripts/check_naming_convention.py` | PASS |
| `python -m pytest prearchive_service/tests -q` | 211 passed + 1 skipped（本轮零 prearchive 业务改动） |
| `python prearchive_service/check_isolation.py` | PASSED（46 文件零 `import app.*`） |
| `npm --prefix frontend run typecheck` | exit 0 |
| `npm --prefix frontend run test:unit` | 50 passed（14 文件） |
| `npm --prefix frontend run build` | 成功，dist 已镜像到 `static/ui-next` |
| `npm --prefix frontend run test:e2e` | **52 passed + 17 skipped（含 oneshot 三端），0 failed** |

三个正式规则文件 SHA-256 与执行前一致（example `ecb3e20c…` / system_push `1897bdbd…` / paperless 快照 `b735bdfc…`），未被触碰。

## 3. 与 037 的偏差说明

1. **RP-E 测试需 `TEST_ISOLATED_MODE=true`**：`ConfigParser.get_data_source_type` 对 fixture 类型先过
   `assert_fixture_source_allowed`（非隔离环境抛 IsolatedModeError）。隔离环境下才是 037 描述的
   "fixture 落入 else 走 Oracle"路径。附带收益：非隔离环境误配 fixture 时 IsolatedModeError 经 RP-C 新
   handler 也返回 400（此前 500）。
2. **RP-D Oracle 故障码取 503**（作业书指定），文案 `department list backend unavailable`，未知类型 400 英文 detail。
3. **RP-B relay-alert 空 body 统一 422**：仅提交 `secret_key`（即使为空串）仍按密钥轮换语义放行 200/原样 merge；
   只提交 `alert_dept_filter` 的部分保存红线有专测保护。
4. **RP-H 静态缓存**：`qc_detail.html` 以 query 引 js，版本参数已提升（`20260902-csrf-header`），无需改 app.js 锚
  （该文件不在 6 个版本锚契约测试清单内，全量 pytest 已证）。

## 4. 改动文件清单

代码：`app/main.py`、`app/routers/config.py`、`app/routers/logs.py`、`app/routers/patients.py`、
`app/routers/patient_qc.py`、`app/routers/audit_types.py`、`app/services/isolated_mode.py`（未改，仅引用）、
`app/services/patient_census_service.py`、`app/services/patient_visit_export_service.py`、
`app/services/audit_type_registry.py`、`app/security_middleware.py`、`app/database.py`；
前端静态：`static/scripts/mobile/qc_detail.js`、`static/templates/mobile/qc_detail.html`；
前端 E2E：`frontend/tests/e2e/oneshot-uinext-sweep.spec.ts`；
测试新增：`tests/test_isolated_mode_http.py`、`tests/test_config_partial_update.py`、
`tests/test_departments_list_datasource.py`、`tests/test_patient_census_datasource_400.py`、
`tests/test_patient_visit_export_datasource.py`、`tests/test_sqlite_busy_timeout.py`、`tests/test_mobile_qc_csrf.py`；
测试修改：`tests/test_audit_types_api.py`（FakeRegistry KeyError 对齐 + 3 新用例）。

## 5. 契约基线追加（101）

`docs/reference/101_FEATURE_BASELINE.md` 追加三条短条目：配置写端点 unset-merge/空 body 422、
census 非 Oracle 400、departments/list fixture 12 科室（见该文件末尾 2026-09-02 段）。

## 6. 不修项确认（037 §1 维持）

U-3（/api/departments admin-only 口径）、U-4（生产 Oracle 等价锁）、O-1/O-2/O-3/O-4、P-008 均未动。
未触碰 `app/dify_pusher.py`、`app/services/push_executor.py`、`app/scheduler.py`、
`app/services/relay_alert_service.py`、`config/config.json`、`prearchive_service/rules/*.json`。

## 7. 建议提交粒度（等用户批准，本轮未提交）

按 037 §16 的 10 笔建议信息提交；执行 AI 已按包保持文件边界，可直接对应。

## 8. 给下一任的核查清单

1. `python -m pytest tests/test_config_partial_update.py -q` 应 16 passed（relay 红线 T8 在内）；
2. `TEST_ISOLATED_MODE` 无关的默认全量跑应 0 failed；
3. 生产部署本包时的注意点：`security_middleware.py`（CSRF 豁免）、`qc_detail.js/html`（版本参数）需随镜像发布；
   `database.py` 仅影响 SQLite 应用库模式，Oracle 模式引擎参数不变；
4. 039 执行 AI 接续：工作区已含全部 037 修复（未提交），038 即本文件。
