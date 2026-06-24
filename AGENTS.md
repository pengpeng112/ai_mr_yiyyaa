# AGENTS.md — Med-Audit Backend

## 核心原则
当任务需求存在不确定、上下文不足、目标不明确或可能产生误解时，必须先向用户确认关键细节；在未确认前，不要自行假设、猜测或执行可能影响结果的操作。

## High-Value Context
- Python 3.11 FastAPI service: clinical record data is loaded from Oracle/PostgreSQL business DBs, sent to Dify Workflow, then stored in the application DB with RBAC, scheduler, logs, feedback, and notifications.
- Application DB and business data source are separate: `APP_DB_TYPE` selects the application DB (`sqlite` default, `oracle` supported); clinical source type lives in `config/config.json` / `config/config.json.template` under `data_source.type`.
- Read `docs/FEATURE_BASELINE_2026-04.md` and `docs/skills/med-audit-codex.md` before changing push/logs/scheduler/qc-feedback/Oracle/Dify behavior; they contain regression baselines not obvious from code.
- `CLAUDE.md` is longer than this file and useful for deeper module maps, but prefer executable files when it conflicts with code/config.

## Commands
- Install runtime deps: `pip install -r requirements.txt`; add test deps with `pip install -r requirements.dev.txt`.
- Local dev server: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`.
- Keep production/container uvicorn single-worker; APScheduler is in-process and will duplicate jobs with multiple workers.
- Health/API docs: `curl http://localhost:8000/api/health`, Swagger at `http://localhost:8000/docs`.
- Pytest suite: `python -m pytest`; focused file/function: `python -m pytest tests/test_push_executor.py -q` or `python -m pytest tests/test_push_executor.py::test_name -q`.
- Fast syntax/import smoke check on Windows PowerShell: `python -m compileall app tests scripts`.
- Naming guard for Dify input conventions: `python scripts/check_naming_convention.py`.
- Integration scripts need the service already running: `python scripts/test_api.py`, `python scripts/quick_start.py`, `python scripts/test_phase2.py`, `python scripts/test_phase3.py`, `python scripts/test_parser_v2.py`.
- Docker local compose: `docker-compose up -d --build`; Windows offline package export: `docker_build.bat`; Linux first deploy after `docker load -i med-audit-image.tar`: `bash docker_deploy.sh`.
- Backfill empty `PushLog.dept` from `JHEMR.V_QYBR`: `docker exec -w /app med-audit python scripts/backfill_pushlog_dept.py 3000` (limit arg = max rows).

## Entrypoints And Flow
- App startup is `app/main.py`: config validation, `init_db()`, optional scheduler controlled by `ENABLE_SCHEDULER` (default `true`), router registration, then static Vue assets from `static/` mounted at `/` after API routes.
- DB setup/migrations are in `app/database.py`; there is no Alembic. New ORM fields must be added to the relevant manual migration and `_verify_required_schema()` for SQLite/Oracle compatibility.
- Config is file-backed at `config/config.json`; if missing, `load_config()` initializes from `CONFIG_TEMPLATE_PATH` (default `config/config.json.template`) and `save_config()` writes timestamped backups under `config/backups/`.
- Secrets are encrypted with Fernet derived from `SECRET_KEY`; production rejects the default `SECRET_KEY`. Do not rewrite or rotate encrypted `password_enc` / `api_key_enc` unless intentionally migrating secrets.
- Manual push `/api/push/manual` uses `BulkPushExecutor` with parallel Dify targets/circuit breaker; scheduler and retry paths use serial `PushExecutor`. Keep behavior aligned when changing shared push semantics.
- Multi-source audit flow is `data_source_loader.load_patient_bundles()` -> `payload_composer.compose()` -> `dify_pusher.push_to_dify()` -> `audit_result_mapper`/`models.py` persistence.
- Built-in payload builders are registered in `payload_composer.py`: `legacy_progress_nursing`, `generic_multi_source`, `lab_exam_progress_nursing`, `frontpage_surgery_first_progress`.

## Dify And Audit-Type Constraints
- Builder output and stored payload semantics use `mr_text`; Dify's default workflow input variable is `mr_txt` and is mapped only in `dify_pusher.py` via `workflow_input_variable`. Do not return `mr_txt` from builders or set `payload["mr_txt"]`.
- Dify `base_url` should be a base API URL; `normalize_dify_base_url()` appends `/workflows/run` in `dify_pusher.py`, so avoid storing full run URLs.
- `config/config.json` `audit_types[]` drives sources, grouping, builder choice, Dify target, response JSONPath, and display paths. Use `AuditTypeRegistry` paths for CRUD so SQL validation, JSONPath validation, masking, and encryption are applied.
- JSONPath response fields must start with `$`; SQL source configs pass through `validate_configurable_sql` and should keep `{dept_filter}` / `:query_date` conventions when applicable.
- Multi-source loading currently only explicitly passes `query_date`; other `date_dimension` modes must be handled by the configured SQL.

## Scheduler And Dual-Mode (Regression-Sensitive)
- Config keys: `scheduler` (legacy, single job), `scheduler_daily` (daily_increment), `scheduler_discharge` (discharge_final). All three always exist in config.json — `start_scheduler()` decides which to use by checking `*.get("enabled")`, NOT by dict existence.
- When `scheduler_daily.enabled` OR `scheduler_discharge.enabled` is true, the dual scheduler path runs; the legacy `scheduler` section is ignored even if its `enabled` is true.
- Both jobs run through the same `_daily_push_job_v2` entrypoint; `audit_run_mode_override` is bound via `functools.partial` at job registration time.
- `daily_push` and `discharge_push` use **separate DB-level run locks** (`lock_name` = job_id). Do not revert to a single shared lock or the two jobs will silently skip each other.
- `discharge_final` mode: `audit_type_for_run_mode()` in `scheduler_run_modes.py` converts SQL from record-creation-date filtering to discharge-date filtering. **Only 3 of 6 audit types have conversion logic** (`progress_vs_nursing`, `jyjc_vs_bcnursing`, `syssvsscbc`). The other 3 (`admission_vs_first_progress`, `surgery_chain`, `discharge_vs_frontpage`) fall through to original `daily_increment` SQL and will miss patients whose records predate the query date.
- `_resolve_scheduler_cfg()` in `scheduler.py` uses truthiness (`if daily:`) not `enabled` check — this is intentional for manual-trigger/config-read paths but must not be confused with the startup decision logic.
- `scheduler_discharge.audit_type_codes` should list types that have discharge_final SQL support; adding unsupported types there will not error but will produce zero PushLogs for those types.
- Scheduler config supports `every_10m`, `every_30m`, `daily`, and `cron`; cron is validated before save and `/api/scheduler/status` should keep diagnostic fields.

## Department (Dept) Fields — V_QYBR vs EMR vs PushLog
- `JHEMR.V_QYBR` real column names: `"所在科室编码"`, `"所在科室名称"`, `"出院科室编码"`, `"出院科室名称"`, `"入院科室名称"`, `"患者ID"`, `"次数"`. There is NO `"在院科室*"` column — using it silently fails (ORA-00904).
- `push_log_writer.py` falls back to `app.utils.patient_dept_query.query_patient_dept(patient_id, visit_number)` when `PushLog.dept` is empty after payload/record extraction. This queries V_QYBR and also enriches `payload.patient_info` with dept_code, inpatient/admission/discharge names.
- `relay_alert_service._query_patient_dept_code` and `_query_patient_dept_info` are kept as local wrappers (mock-tested in `test_relay_alert_service.py`); the shared `patient_dept_query` module is the canonical implementation for new code.
- Oracle treats empty string `""` the same as `NULL`; `PushLog.dept != ""` in Oracle mode filters out ALL rows. `_list_distinct_depts()` in `logs.py` avoids SQL-level `!= ""` and filters empties in Python instead.
- `alert_dept_filter` in `relay_alert` config (e.g. `["听觉植入科"]`) restricts WeChat push to those departments only; empty list = all departments. Matching checks BOTH `dept_code` and `dept_name` against the filter list.

## Relay Alert Config Save (Partial Update Safety)
- `POST /api/config/relay-alert` uses `model_dump(exclude_unset=True)` + merge with current config (`{**current, **body_data}`). This means partial saves (e.g. only `alert_dept_filter` from the relay page) will NOT clobber `enabled`, `secret_key_enc`, `detail_page`, `receiver_rules`, or `nurse_heads`.
- `base_url` is protected against empty-string overwrite. If the page submits `base_url: ""` while an existing address is configured, the old address must be preserved; if relay alert is enabled and no address exists, saving must fail instead of storing an empty address.
- `secret_key` plaintext is popped from body_data, encrypted to `secret_key_enc`, and only written when non-empty; omitting it preserves the existing encrypted value.
- Do NOT revert this to full-replacement `update_section` or the relay.html "Save" button will silently disable push and lose receiver rules.

## Regression-Sensitive Behavior
- Dify main input must remain a string; bulk push must isolate per-item transaction failures so one failed patient does not poison the whole batch.
- Preserve skip reasons and flags: `pushed_flag`, `reviewed_flag`, `manual_override`, `skip_reason`, especially `unreviewed_pending` and `rectified_suppressed`.
- `/api/logs` and CSV export must remain tolerant of historical `NULL` rows and include `reviewed_flag`, `manual_override`, `skip_reason`, `audit_type_code`, and risk/structured result fields when relevant.
- New export endpoints under logs/feedback/reporting should call `record_export_audit()` so `ExportAuditLog` remains complete.
- Oracle compatibility is easy to break: clean trailing SQL separators, keep SELECT/GROUP BY expressions aligned, and verify boolean/date expressions against Oracle as well as SQLite.

## Deployment Gotchas
- Docker image copies `oracle-client/linux/` to `/opt/oracle`; missing Instant Client means Oracle business queries will not work even if the app starts.
- Container/runtime writable mounts are `./data:/app/data`, `./config:/app/config`, and `./logs:/app/logs`; logs are `logs/app.log` and `logs/audit_detail.log` with audit loggers `audit.dify` and `audit.oracle`.
- `docker_deploy.sh` creates `.env` with random `JWT_SECRET_KEY` and `SECRET_KEY`; back it up because existing encrypted config cannot be decrypted after changing `SECRET_KEY`.

## Vastbase (EMR) Gotchas
- Vastbase/OpenGauss returns **uppercase** column names from `cursor.description`; always call `.lower()` before zipping with rows: `columns = [desc[0].lower() for desc in cur.description]`. Without this, `rec.get("patient_id","")` returns empty strings and all rows are silently skipped.
- `fetch_emr_documents_by_visits` filters by `progress_template_name`, NOT by `progress_type_name` or `progress_title_name`. Discharge uses exact match `= '出院记录'`; progress uses `LIKE '%病程%'` to catch 日常病程/首次病程/术后首次病程; first_progress uses `LIKE '%首次病程%'`.
- The view `jhemr.v_blws` contains non-clinical documents (知情同意书, 查房记录, 手术记录). These must NOT appear in progress/discharge exports; the template-based filter handles this.
- `sslmode` is optional: only pass it to `psycopg2.connect()` if the config explicitly sets it. Do not default to `"disable"`.
- Container hot-updates to `/app/app/emr_vastbase_client.py` must clear `__pycache__/` and be committed to a new image to survive restarts.

## QC Relay Alert Push
- Config lives in `config/config.json` under `relay_alert`: `enabled`, `base_url`, `endpoint`, `secret_key`/`secret_key_enc`, `severity_levels` (default `["high"]`), `source`.
- The relay target is `http://10.20.1.153:3000/qc-record-alert`; auth uses HMAC-SHA256 with headers `X-Relay-Timestamp` and `X-Relay-Signature`.
- `detail_url` format: `http://10.20.1.153:3000/qc-detail/{alert_id}?token={token}` — the relay reverse-proxies to the internal `http://10.10.8.84:8000/mobile/qc/{alert_id}?token={token}`.
- Models: `QCRecordAlertLog` (tracks send status: pending/success/failed) and `QCAlertFeedback` (doctor H5 feedback). The `relay_alert_service.RelayAlertService` class handles enqueue + dispatch.
- Manual push test in container:
  ```python
  from app.services.relay_alert_service import RelayAlertService
  svc = RelayAlertService(db, config)
  svc.enqueue_high_severity_alerts(push_log_id)  # creates pending records
  svc.dispatch_pending(push_log_ids=[push_log_id])  # sends to relay
  ```
- Only dimensions with `severity in severity_levels` generate alerts. If no dimensions qualify but the conclusion is severe, a `__conclusion__` fallback is created.
- The relay alert system is separate from `QCFeedback` (business feedback CRUD in `qc_feedback.py`). The `suppress_ai_push` flag on QCFeedback can block alert creation.

## Remote Production Server
- SSH: `10.10.8.84:40022`, user `root`, password `P@ssw0rd@123`
- Service URL: `http://10.10.8.84:8000`, Swagger at `/docs`
- Container: `med-audit`, docker-compose at `/opt/med-audit-docker/docker-compose.yml`
- Volumes mounted: `./data:/app/data`, `./config:/app/config`, `./logs:/app/logs` (app code is in image, not mounted)
- To persist hot-updates: `docker commit -m "reason" med-audit med-audit:latest`
- Vastbase business DB: `10.10.8.177:5432`, database `jhemr`, user `aizk_user`, password `aizk_user@123`
- Local SFTP uploads from Windows must avoid Chinese paths: write to `C:\Users\ADMINI~1\AppData\Local\Temp\opencode\` first, then upload.

## Local Conventions Worth Keeping
- Code comments, logs, and Swagger summaries are Chinese; HTTP exception `detail` strings are English.
- Route prefixes are registered only in `app/main.py`; put per-feature routers under `app/routers/` with dependencies for auth/permissions as needed.
- Route DB sessions use `Depends(get_db)`; background threads/executors create `SessionLocal()` and must close sessions with rollback on failure.
- No configured formatter/linter (`ruff`, `black`, `mypy`, etc. absent); match nearby style and use the focused tests/scripts above for verification.
