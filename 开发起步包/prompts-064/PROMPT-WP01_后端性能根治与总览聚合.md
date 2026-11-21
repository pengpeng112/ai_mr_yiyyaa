# 执行任务书 `PROMPT-WP01`：后端性能根治 + `timeliness_scan` 脏写修复 + 质控总览单接口聚合

> **所属总计划**：`docs/ACTIVE/064_FULLSTACK_OPTIMIZATION_MASTER_PLAN_20261119.md`（工作包 1 / 10）  
> **预计耗时**：约 3.0 小时  
> **前置依赖**：无（首个执行包）  
> **先读文件顺序**：`AGENTS.md` → `开发起步包/README.md` → `开发起步包/00_AI协作规则.md` → `开发起步包/01_统一修改记录.md` 末 10 行 → `开发起步包/02_协作任务板.md` → **`开发起步包/prompts-064/PROMPT-00_通用事实基线与勘误_必读.md`（冲突以它和真实代码为准）** → 先跑 `git status --short` 存到 `review/064-wp01/git_status_before.txt` 并完整保留他人既有未提交文件。

---

## 一、任务背景与明确目标

2026-11-19 对生产 `10.10.8.84` 与 Oracle `10.10.8.216` 只读实测发现四大严重后端性能瓶颈：
1. **隐藏 P0 炸弹（`timeliness_scan` 每 5 分钟跑 105～116 秒）**：`app/timeliness/scanner.py` 第 890–919 行对全部 **8,188 条既有事件**（包括已完成终态记录）无条件赋值 `event.last_scan_at = now` / `event.updated_at = now`，导致每 5 分钟向 Oracle 发起 8,200 次逐行 `UPDATE`，严重阻塞单 Worker FastAPI 和数据库连接池。
2. **质控总览首屏慢**：打开总览触发 10～14 个请求且分 3 批串行——`/stats/severity`（841ms）和 `/stats/anomaly-top`（292ms）各做二次全表扫；`/stats/today` 发 4 条 COUNT；`/relay-alert/summary` 发 10 条 COUNT；`/api/logs` 加载 4 个总计 **7.45 GB** 的大 CLOB 列且解析 `request_json` 两次；3 次 `/timeliness/*?limit=1` 只为拿 `total` 却全量查字典与 `V_QYBR`。
3. **列表页 CLOB 扫描灾难**：`patient_qc.py` 按 `discharge_dept_name` 筛选用 `dbms_lob.instr(request_json, ...)` 扫 1.86 GB CLOB；`/api/logs/dept-options` 与 `/filters/options` 无缓存每次直连业务库 + 多次全表计数。
4. **AI 定时调度容错弱**：`progress_vs_nursing` 遇瞬时 `ORA-12609` 接收超时直接 `tot=0` 放弃，缺少单质控类型自动退避重试；且无可选并发开关。

**本包目标**：一次性根治上述 4 大后端性能问题，交付单聚合总览接口 `GET /api/stats/workbench-overview`，并生成纯增量 Oracle 索引/补列审批脚本（**只生成文件，不在本包执行生产 DDL**）。

---

## 二、允许修改与新增的文件白名单（严禁改动白名单外文件）

### 允许新增
1. `app/services/ttl_cache.py`
2. `scripts/oracle_perf_indexes_20261119.sql`（只生成，不执行）
3. `scripts/backfill_pushlog_discharge_dept_20261119.py`（历史行回填脚本，默认 `--dry-run`，只生成不在生产执行）
4. `tests/test_wp01_perf_and_overview.py`
5. `review/064-wp01/`（exec-log.md、git_status_before.txt、DELIVERY.md）

### 允许修改
1. `app/timeliness/scanner.py`
2. `app/routers/stats.py`
3. `app/routers/logs.py`
4. `app/routers/patient_qc.py`
5. `app/services/push_log_writer.py`（仅写日志时同步填充 `discharge_dept`）
6. `app/scheduler.py`
7. `app/models.py` & `app/database.py`（仅新增 `PushLog.discharge_dept` 索引列及幂等迁移，兼容 SQLite 与 Oracle）
8. `开发起步包/01_统一修改记录.md` & `开发起步包/02_协作任务板.md`（收工登记）

> **注意**：不要修改前端任何文件（总览前端切换在 `WP-03` 做），不要修改 `prearchive_service/` 下任何文件！

---

## 三、逐项超详细实施规范

### 任务 1：新建线程安全轻量 TTL 缓存 `app/services/ttl_cache.py`
实现以下最小 API（≤80 行，标准库 `threading` + `time` 零第三方依赖）：
```python
class TTLCache:
    def __init__(self, maxsize: int = 512) -> None: ...
    def get(self, key: str): ...
    def set(self, key: str, value, ttl_seconds: float) -> None: ...
    def get_or_set(self, key: str, ttl_seconds: float, loader: Callable[[], T]) -> T: ...
    def invalidate_prefix(self, prefix: str) -> int: ...
    def clear(self) -> None: ...

# 导出全局共享实例
app_ttl_cache = TTLCache(maxsize=512)
```
要求：
- 使用 `time.monotonic()` 判过期；
- `get_or_set` 锁内不要持锁执行慢 `loader`（先加锁读，未命中则释放锁执行 `loader()`，再加锁写入），防止慢 SQL 阻塞所有其他线程；
- 超过 `maxsize` 时先清理已过期项，仍超限时淘汰最早过期项。

### 任务 2：根治 `app/timeliness/scanner.py` 8,188 行无效 UPDATE（P0）
1. 真实代码位置：`app/timeliness/scanner.py` 方法 `_persist_results`（约第 838–920 行），既有事件分支在第 889–919 行，**第 906–907 行无条件写 `event.last_scan_at = now` / `event.updated_at = now`** 就是根因。
2. 终态集合**直接复用**：`from app.timeliness.engine.state import TERMINAL_STATUSES`（= `COMPLETED_ON_TIME, COMPLETED_LATE, CANCELLED, EXEMPT`），不要自己定义。
3. 改造既有事件分支（只改 `else:` 分支，新建事件分支保持不动）：
   - 先算出新值（注意保持原有「`result.dept_code or event.dept_code`」「`result.responsible_doctor_id or event.responsible_doctor_id`」的兜底语义）；
   - 业务字段快照只用**真实字段**：`rule_version_id, dept_code, responsible_doctor_id, t0, deadline, status, matched_file_unique_id, completed_at, overdue_minutes, warn_sent_at`（不含 `last_scan_at`、`updated_at`）；
   - **`overdue_minutes` 特殊处理**：OVERDUE 事件的超时分钟数每轮都会自然增长，若每轮都写回仍会产生几百行 UPDATE。规则：状态未变时，仅当 `abs(new - old) >= 30` 才写回 `overdue_minutes`；状态变化时必须写回；
   - 原状态 ∈ `TERMINAL_STATUSES` 且新状态相同、其余字段无变化 → **直接跳过，零赋值**；
   - 其余情况：只有快照不同才赋值变更字段 + `last_scan_at = now` + `updated_at = now`，并 `updated += 1`；快照相同 → 零赋值、不计数；
   - 保留第 893–894 行「WARNING/OVERDUE 回退 PENDING 时清空 `warn_sent_at`」与第 908–918 行状态变化写 `TLEventHistory` 的逻辑不变。
4. **加阶段耗时日志（用于证明修复有效）**：在 `run_scan`（或主流程）中用 `time.perf_counter()` 分别记录「取数（JHEMR/HIS/V_QYBR）」「规则评估」「落库 flush/commit」三段耗时，以 INFO 日志一行输出（如 `timeliness_scan phase_ms fetch=… eval=… persist=… updated=…`），并写入 `TLScanRun.error_text` 以外的现有日志即可（**不要新增表字段**）。交付报告里写清：若修复后 persist 段已很小但总耗时仍 >30s，说明瓶颈在取数段，列为后续事项，不要在本包擅自改取数逻辑。
5. **`dept_code` 为空（线上 106 条）兜底**：找到 scanner 组装 `result.dept_code` 的位置（`fetch_patient_visit_meta` 回填处），为空时依次兜底 `所在科室编码` → `入院科室编码` → `出院科室编码`（这 3 列都在 V_QYBR 40 列契约内）。

### 任务 3：优化 `app/routers/stats.py` 并新增总览聚合接口 `GET /api/stats/workbench-overview`
1. **旧接口 SQL 合并优化（保持 100% 原响应结构，零破坏既有测试）**：
   - `/api/stats/today`：将多条 `COUNT(*)` 合并为 **1 条 SQL** `SELECT COUNT(id), SUM(CASE WHEN ... THEN 1 ELSE 0 END), ...`（注意 Oracle/SQLite 兼容：结果用 `int(val or 0)`）。
   - `_stats_metadata()`：将全表 `SELECT MIN(query_date), MAX(query_date)` 放进 `app_ttl_cache.get_or_set(f"stats:date_bounds:{scope_key}", 300, ...)`，消除 `/stats/severity` 和 `/stats/anomaly-top` 的二次全表扫描！
   - `app/routers/patient_qc.py` 中 `/relay-alert/summary`：把 10 条独立 `COUNT(*)` 合并为 **1 条 SQL `SUM(CASE WHEN ...)`**。
2. **新增 `GET /api/stats/workbench-overview`**：
   - 权限：同 `/api/stats/today`（登录且有工作台/统计权限），自动套用当前用户可见科室范围（先复用现有 `dept_visibility`；WP-02 会无缝替换为统一 `data_scope`）。
   - 参数：`days: int = Query(30, ge=1, le=90)`、`force_refresh: bool = Query(False)`。
   - 缓存键：`f"wb_overview:{scope_key}:{days}"`，TTL = **30 秒**（`force_refresh=True` 时跳过读缓存并刷新写缓存）。
   - **返回 JSON 精确契约**（前端 `WP-03` 将严格按此字段读取，**一个键名都不要拼错**）：
     ```json
     {
       "cached_at": "2026-11-19T18:00:00+08:00",
       "days": 30,
       "scope_label": "全院",
       "ai_qc": {
         "today_pushed": 0,
         "today_success": 0,
         "today_failed": 0,
         "today_high_risk": 0,
         "severity_counts": { "high": 0, "medium": 0, "low": 0, "none": 0 },
         "daily_trend": [{ "date": "2026-11-18", "total": 0, "high": 0, "medium": 0, "low": 0 }],
         "top_depts": [{ "name": "科室名", "anomaly_count": 0, "high_count": 0 }],
         "high_risk_recent": [
           {
             "id": 1,
             "patient_id": "00985003",
             "patient_name": "脱敏或真实名",
             "visit_number": 1,
             "dept": "骨科",
             "audit_type_code": "progress_vs_nursing",
             "audit_type_name": "病程与护理一致性",
             "severity": "high",
             "push_time": "2026-11-19T09:15:00",
             "summary": "核心结论摘要",
             "reviewed_flag": false
           }
         ]
       },
       "timeliness": {
         "inpatient_warning": 0,
         "inpatient_overdue": 0,
         "locked_pending": 0,
         "month_locked_total": 0,
         "month_unlocked": 0,
         "month_on_time_rate": 0.0,
         "month_total_events": 0,
         "last_scan_at": null,
         "last_scan_duration_ms": null
       },
       "prearchive": {
         "available": false,
         "mode": "unconfigured",
         "total_checked": 0,
         "issue_records": 0,
         "pending_review": 0,
         "rules_active": 0,
         "status_message": "归档前形式预检暂未接入数据"
       },
       "relay": {
         "total": 0,
         "success": 0,
         "failed": 0,
         "pending": 0,
         "viewed": 0,
         "unviewed": 0
       },
       "system": {
         "status": "ok",
         "scheduler_running": false,
         "daily_next_run": null,
         "discharge_next_run": null
       }
     }
     ```
   - **关键性能硬约束**：
     - `ai_qc.high_risk_recent`：单条 SQL 查近 14 天 `severity == 'high'` 最新 15 条，**必须使用 `sqlalchemy.orm.defer(PushLog.mr_text, PushLog.ai_result, PushLog.request_json, PushLog.response_json)`**，摘要通过 `OUTER JOIN AuditConclusion` 读取 `overall_conclusion`（绝不加载 4 个 CLOB！）；
     - `timeliness`：只用轻量聚合 SQL，口径**必须**如下（字段名见 PROMPT-00 §1.3）：
       - `inpatient_warning` / `inpatient_overdue`：`TLEvent` 中 `status == 'WARNING'` / `'OVERDUE'` 的条数（受科室可见性约束）；
       - `locked_pending`：`TLApproval.flag == '1'`（锁定待审批）条数；
       - `month_locked_total`：本月 `TLApproval.apply_date_time` 落在本月的行数（= 本月触发锁定次数，与 `_monthly_rows.approval_count` 同口径）；
       - `month_unlocked`：其中 `flag == '2'` 的行数；
       - `month_on_time_rate`：本月 `TLEvent.t0` 落在本月且已完成（`COMPLETED_ON_TIME` + `COMPLETED_LATE`）中按时完成占比，保留 1 位小数，分母为 0 时返回 0.0；
       - `last_scan_at` / `last_scan_duration_ms`：`TLScanRun` 按 `id` 倒序取 1 条，`finished_at - started_at` 换算毫秒；
       - **严禁调用 `_display_maps()`、`_patient_name_map()` 或查询 `V_QYBR`！**
     - `prearchive`：通过现有 `PrearchiveAdminClient.call("GET", "/api/admin/checks", actor, query={"page": 1, "page_size": 1, ...})` 这类**已在白名单内**的目标取 `total`（先读 `app/services/prearchive_admin_client.py` 与 `app/routers/prearchive_admin.py` 确认真实调用签名与分页参数名）；`PREARCHIVE_ADMIN_ENABLED` 未开启、超时（2 秒）、异常时静默返回 `available: false` + 中文说明；独立 60 秒缓存；`rules_active` 从 `app/services/prearchive_rules_view.py` 读取本地生效规则条数（文件缺失 fail-open 为 0）。**不得新增 BFF 白名单目标。**

### 任务 4：消除 `logs.py` 和 `patient_qc.py` 的 CLOB 加载与全表扫描
1. **`app/models.py` & `app/database.py` & `app/services/push_log_writer.py`**：
   - 在 `PushLog` 的非 CLOB 字段区域（放在 `contract_valid` 附近、`ai_result/mr_text/request_json/response_json` 这些 CLOB 列之前）新增：
     ```python
     discharge_dept = Column(String(120), nullable=True)  # 不在 ORM 写 index=True，索引由人工 DDL 脚本创建
     ```
   - 在 `app/database.py` 的现有手工迁移函数中按既有写法补「列不存在则 `ALTER TABLE ... ADD`」（SQLite 与 Oracle 都要；Oracle 上新增**可空、无默认值**的列是秒级元数据操作，可以随启动自动执行），并把列加入 `_verify_required_schema()`。**不要在 `init_db` 里建索引或回填历史数据**（24.5 万行，留给人工脚本）。
   - 在 `app/services/push_log_writer.py` 写 `PushLog` 时，从 payload/`patient_info` 提取出院科室名称写入 `discharge_dept`（截断 120 字符；取不到就留空）。
   - 新建 `scripts/backfill_pushlog_discharge_dept_20261119.py`：默认 `--dry-run` 只统计；`--apply --batch 2000 --limit N` 才分批写；每批只读 `id, request_json`（Python 侧 `json.loads` 解析出院科室），每批独立提交、失败回滚并继续；只处理 `discharge_dept IS NULL` 的行；输出脱敏统计。**本包只写脚本+单测，不在任何生产环境运行。**
2. **`app/routers/logs.py`**：
   - 分页列表查询 `GET /api/logs` 对 ORM 查询应用 `defer(PushLog.mr_text, PushLog.response_json, PushLog.ai_result)`（若列表字段不需要 `request_json`，连 `request_json` 一并 `defer`；若需读 `patient_info` 内非独立字段，保留最小读取且把 `_to_push_log_item` 里重复 `json.loads(log.request_json)` 合并为仅解析 1 次！）；
   - 单条详情端点保持完整读取全部字段；
   - 给 `/api/logs/dept-options` 和 `/api/logs/filters/options` 加 **300 秒 TTL 缓存**（按用户科室可见范围区分 key）。
3. **`app/routers/patient_qc.py`**：
   - 列表分页接口 `list_patient_qc_patients`：Step 2 加载样本行时强制 `defer(PushLog.mr_text, PushLog.ai_result, PushLog.request_json, PushLog.response_json)`；
   - `discharge_dept_name` 筛选改为**混合条件**（保证历史行不漏、回填后自动变快）：
     `PushLog.discharge_dept == X  OR  (PushLog.discharge_dept IS NULL AND <原有 dbms_lob.instr / like 旧逻辑>)`。
     这样新数据走索引列；历史行在回填脚本跑完前仍按旧逻辑匹配（不丢结果），回填后 NULL 行趋近 0，CLOB 扫描自然消失。**不要直接删掉旧逻辑**（否则历史患者按出院科室筛选会查不到，属于功能回归）。

### 任务 5：`app/scheduler.py` 瞬时 `ORA-12609` 重试 + 可选并发开关
1. 在调度循环执行单个 `audit_type` 时，若捕获异常文本含 `ORA-12609` / `DPY-4011` / `TNS` / `接收超时` / `Read timed out`：
   - 记录清晰 WARNING 日志，等待 `retry_backoff_seconds`（默认 15 秒，可由配置/参数注入以便测试传 0 秒），**最多自动重试 1 次**；若重试仍失败则继续下一质控类型，不中断整批任务。
2. 支持从 `scheduler_daily` / `scheduler_discharge` 配置读取可选 `max_workers`（默认 `1`，安全夹紧到 `[1, 4]`）；当 `max_workers == 1` 时保持完全原有串行行为不变。

### 任务 6：产出 Oracle 人工审批 DDL 脚本 `scripts/oracle_perf_indexes_20261119.sql`
生成纯 SQL 文件（**绝对不要自动执行**），必须包含：
1. 注释头：用途、影响表、锁表评估（Oracle `ONLINE` 建索引）、执行前预检 SQL；
2. 3 条复合索引 DDL：
   - `IDX_PUSH_LOG_CURR_TIME` on `MED_PUSH_LOG (SUPERSEDED_BY, STATUS, CONTRACT_VALID, PUSH_TIME DESC)`
   - `IDX_PUSH_LOG_CURR_SEV_DEPT` on `MED_PUSH_LOG (SUPERSEDED_BY, STATUS, CONTRACT_VALID, SEVERITY, DEPT)`
   - `IDX_PUSH_LOG_DISCHARGE_DEPT` on `MED_PUSH_LOG (DISCHARGE_DEPT)`
3. 列说明：`DISCHARGE_DEPT` 列由应用启动时的手工迁移自动添加（可空无默认值，元数据级）；脚本中只放「若启动迁移未生效时的手工补列」备用语句 `ALTER TABLE MED_PUSH_LOG ADD (DISCHARGE_DEPT VARCHAR2(120));`（注释说明二选一，避免重复执行报 ORA-01430），回填请使用 `scripts/backfill_pushlog_discharge_dept_20261119.py`（不要在 SQL 里用 `dbms_lob` 批量解析 JSON）；
4. 部署顺序注释：①发布新代码（自动补列）→②低峰执行 3 条 `CREATE INDEX ... ONLINE`→③分批跑回填脚本→④核对 `SELECT COUNT(*) FROM MED_PUSH_LOG WHERE DISCHARGE_DEPT IS NULL`；
5. 完整回滚 SQL（`DROP INDEX ...`；列保留不删，空列无害）。

---

## 四、绝对红线与禁令

1. **Oracle 兼容**：禁 `FETCH FIRST`；布尔用 `== True` / `== False`（禁 `.is_(True)`）；SQL 禁 `!= ""`；`discharge_dept` 放非 CLOB 列区。
2. **Dify 契约**：严禁修改 `mr_text` 键名或 Dify 输出解析逻辑。
3. **只改白名单文件**：不得碰前端、不得碰 `prearchive_service/`、不得动既有未提交的 43 个无关文件。
4. **严禁连接生产执行写入、严禁执行 `git commit/push/reset`**。

---

## 五、验收测试与交付标准

新建 `tests/test_wp01_perf_and_overview.py` 至少覆盖以下 10 个测试用例：
1. `TTLCache` 命中、过期、`invalidate_prefix` 与并发 `get_or_set`；
2. `scanner.py` 幂等脏写测试：连续两次相同数据扫描，第二次 `events_updated == 0`，终态事件 `updated_at` 零变化；
3. `scanner.py` 业务字段变化测试：状态由 `WARNING` 变 `OVERDUE` 时正常更新且 `events_updated == 1`；
4. `GET /api/stats/workbench-overview` 返回完整结构且包含 `ai_qc`/`timeliness`/`prearchive`/`relay`/`system` 全部契约键；
5. `workbench-overview` 在 `prearchive` sidecar 不可达/超时时 fail-open 返回 200 且 `prearchive.available == False`；
6. `workbench-overview` 30s TTL 缓存命中测试（含 `force_refresh=true` 绕过缓存）；
7. `GET /api/logs` 与 `GET /api/patient-qc/patients` 列表查询验证 CLOB 列已 `defer`；`discharge_dept_name` 筛选对「已填 `discharge_dept` 的新行」和「`discharge_dept` 为空的历史行」都能命中（混合条件不丢结果）；
8. `scheduler.py` 遇 `ORA-12609` 时自动退避重试 1 次成功并恢复正常返回；
9. `backfill_pushlog_discharge_dept_20261119.py` 在 SQLite 测试库：`--dry-run` 零写入、`--apply` 只更新 `discharge_dept IS NULL` 的行且重复执行幂等；
10. scanner OVERDUE 事件 `overdue_minutes` 增长 <30 分钟时不写回、≥30 分钟时写回。

**收工必跑验收命令（把真实输出贴到交付汇报中；PowerShell 不展开通配符，文件名必须写全）**：
```powershell
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python -m pytest tests/test_wp01_perf_and_overview.py tests/timeliness/test_scanner.py tests/test_push_executor.py tests/test_stats_metadata.py -q
python -m pytest tests/test_logs_regression.py tests/test_logs_schema.py tests/test_logs_export_scope_20261004.py tests/test_patient_qc_export_filters.py -q
python -m pytest tests/timeliness -q
python scripts/run_gates_20260906.py --quick
```
收工前写 `review/064-wp01/DELIVERY.md`（含 scanner 修复前后 `updated` 计数与阶段耗时日志样例），在 `开发起步包/01_统一修改记录.md` 追加一行并更新 `开发起步包/02_协作任务板.md`（状态标 `DONE`，写明“本地交付完成，未提交”）。
