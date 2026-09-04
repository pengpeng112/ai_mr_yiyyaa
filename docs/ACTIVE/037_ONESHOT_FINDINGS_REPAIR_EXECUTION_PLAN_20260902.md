# 037 — 一次性全系统模拟测试问题核查与一次性修复执行计划

> 文档编号：037 ｜ 编制：2026-09-02 ｜ 编制者：Grok 4.6（系统分析师）
> 证据来源：`review/oneshot-20260901/问题记录_主文件.md`（一次性测试 AI / ZCode 2026-09-02，基线 HEAD=`52998cc`）
> 性质：**核查结论 + 一次性修复作业书**。从属 023，不构成生产写入授权。
> 完成定义：按本文一次性修完全部「本轮必修」项，门禁全绿，交付报告写入 `docs/ACTIVE/038`。

把本文全文交给执行 AI 即可开工。配套短提示词：`开发起步包/PROMPT-20260902_oneshot问题一次性修复.md`。

---

## 0. 用户需求与本轮边界

用户原话：「如上是别的 ai 测试后发现的问题，请你进行核查并给出一个详细的执行计划 md 文件，我让别的 ai 一次性执行修复完成」。

本文件做三件事：

1. **核查** oneshot 报告 8 条问题 + K 底账 2 条 + 观察/不确定项，对照当前代码给出属实/升级/不修裁定。
2. **给出可一次性执行的修复包**（文件、函数、语义、测试、禁改项、提交粒度）。
3. **明确不修项**，禁止执行 AI 自行扩大范围或把产品决策当缺陷改掉。

**本轮纪律（违反任一条=执行作废）**

- 零生产访问、零生产写入、不 push、不部署。
- 不改 `config/config.json`、不改 `prearchive_service/rules/*.json`、不改 14 条已授权规则。
- 既有测试禁改凑绿；契约变更必须在对应测试中显式改断言并在 01 记录写明原因。
- HTTPException `detail` 用英文；注释/日志/Swagger 用中文。
- 用户未要求不 `git commit`。本地改完后按包准备提交信息，**等用户批准再提交**。
- 改任何 `docs/**/*.md` 必须同步 `docs/INDEX.md`；结束前追加 `开发起步包/01_统一修改记录.md`。

---

## 1. 核查总表（对照代码后的终裁）

证据：oneshot 主文件 + 本轮实读 `app/database.py`、`app/routers/config.py`、`app/services/isolated_mode.py`、`app/main.py`、`app/security_middleware.py`、`app/routers/patients.py`、`app/services/patient_census_service.py`、`app/routers/patient_qc.py`、`app/services/patient_visit_export_service.py`、`app/services/audit_type_registry.py`、`app/routers/audit_types.py`、`static/scripts/mobile/qc_detail.js`。

| 编号 | 测试 AI 结论 | 核查结果 | 终裁级别 | 本轮 |
|---|---|---|---|---|
| P-001 | SQLite `database is locked` 致调度推送 21/24 失败 | **属实**。WAL 仅在 `init_db()` 的一次性连接上设置（`database.py:148-158`）；引擎 `NullPool` + `connect_args` 只有 `check_same_thread=False`，**每条新连接未设 `timeout`/`busy_timeout`**。生产 Oracle 应用库不受此 SQLITE 锁影响（U-4 维持观察）。 | **B** | **必修 RP-A** |
| P-002 | 空 `{}` POST 配置端点用模型默认值整段覆盖 | **属实且升级**。`update_section` 全量替换（`config.py:571-575`）；`PrivacyMaskingConfig.enabled` 默认 `False`、`SchedulerConfig.enabled` 默认 `True`、`OracleConfig.host` 默认 `10.255.255.20`、`DifyConfig.base_url` 默认 `http://10.255.255.10/v1`（`schemas.py:41-208`）。同文件 relay-alert 已是 `exclude_unset`+merge（`config.py:973-1005`）。**生产空 body 会把 Oracle/Dify 主机写成占位内网地址**，不只是 demo 问题。 | **B**（从 C 升级） | **必修 RP-B** |
| P-003 | IsolatedModeError 冒泡 500 | **属实**。`save_config` → `validate_isolated_config` 抛 `IsolatedModeError(RuntimeError)`（`isolated_mode.py:13,83-88`）；`main.py` 只有 HTTPException 与裸 `Exception` 处理器，后者一律 500（`main.py:177-200`）。落盘前失败，配置未被污染——与测试记录一致。 | **C** | **必修 RP-C** |
| P-004 / K-2 | `GET /api/config/departments/list` fixture 走 Oracle | **属实**。`config.py:701-720` 仅 `postgresql` / else→oracle。`data_source.type=fixture` 落入 else，本机无 cx_Oracle → 500。`GET /api/departments` 是应用库科室管理，不是同源。`logs.py:496-508` 有同样 else→oracle，但是 fail-open 只打 warning，本轮一并修。 | **C** | **必修 RP-D** |
| P-005 | census 三端点用 500 表达「仅支持 Oracle」 | **属实**。`patient_census_service.py:229-232` 抛 `RuntimeError`；`patients.py:49/77/89` 把 RuntimeError 映射为 500。能力不支持不是服务器故障。 | **C** | **必修 RP-E** |
| P-006 | visit-summary 导出 fixture 500 且 RuntimeError 无 traceback | **属实**。`patient_visit_export_service.py:909-921` 无数据源前置检查，直接 `get_oracle_connection`。路由 `patient_qc.py:1202-1212` 的 `RuntimeError` 分支**没有** `exc_info=True`（对比 1224 的裸 Exception 有）。U-5 因此闭合：内部异常类型=连接/驱动 RuntimeError，不是 openpyxl。 | **C** | **必修 RP-F** |
| P-007 | DELETE 不存在 audit type 返回 200 | **属实**。`audit_type_registry.py:276-286` 过滤空列表后照样 `save_config`。`DELETE /options`、`DELETE /prearchive` 被 `DELETE /{code}` 吃掉是 FastAPI 模板路由的正常行为；修存在性 404 即可，不必为 `options`/`prearchive` 单独注册 DELETE 405。 | **D** | **必修 RP-G** |
| P-008 | 若干端点空参 400 | **不是缺陷**。业务规则拒绝（缺 SQL、删内置对象等）。 | — | **不修**（写入回归基线说明即可） |
| K-1 | H5 `POST /api/mobile/qc-feedback` 带 Cookie 无自定义头 → CSRF 403 | **属实且本轮纳入必修**。中间件条件=写方法 + Cookie + 无 Bearer + 无 `X-Requested-With`（`security_middleware.py:46-56`）。H5 认证靠 body 里 HMAC token，`qc_detail.js:78-81` 的 `fetch` 不带头。医生在同浏览器残留管理端 Cookie 时反馈失败。仅测无 Cookie 会得到 200，会漏。 | **B** | **必修 RP-H** |
| O-5 | ui-next oneshot spec 无 skip 守卫，`npm run test:e2e` 会 3 failed | **属实**。`frontend/tests/e2e-legacy/oneshot-sweep.spec.ts` 已有 `LEGACY_E2E` skip；`frontend/tests/e2e/oneshot-uinext-sweep.spec.ts` **没有** skip，会被默认 mock 套收集。 | **D**（测试卫生） | **必修 RP-I** |

### 不修 / 不擅自改（执行 AI 禁止动手）

| 项 | 原因 |
|---|---|
| U-3 `GET /api/departments` admin-only vs 作业书全角色 200 | 产品口径未拍板。代码 `departments.py:77-83` 硬编码 admin。UI 扫荡未被阻断。**留给用户**。 |
| U-4 生产 Oracle 应用库等价锁 | 红线禁止连生产库。RP-A 只修 SQLite 路径；Oracle 只在 `is_transient_app_db_error` 保持现有 ORA 标记。 |
| O-1 `/api/demo/credentials` 匿名出口令 | demo 条件挂载（`main.py` `demo_mode_enabled()`），作业书已降为观察项。 |
| O-2 `POST /api/scheduler/trigger` 空 body 即触发 | 已认证 admin 的既有产品行为；强制 `confirm` 会破现有前端。不改。 |
| O-3 `GET /api/config/data-source` 登录即可读 | 响应只有 `type`，写端点仍要 `manage_config`。设计行为。 |
| O-4 开发机 pip requests 2.33.1 vs pin 2.32.4 | 035/RP5 已锁 2.32.4；开发机漂移不改 pin。 |
| P-008 | 非缺陷。 |
| 生产热更新 / config.json 业务值 / Dify / Relay | 本轮零生产。 |

---

## 2. 修复包一览与依赖

```
RP-C（隔离异常 400，小且独立）
  ↓
RP-B（配置空 body 部分更新；修 P-002 根因，也减少 P-003 触发面）
  ↓
RP-D / RP-E / RP-F（数据源能力分支，可并行）
  ↓
RP-A（SQLite busy_timeout；B 级，改引擎连接参数）
  ↓
RP-H（H5 CSRF 豁免 + 前端带头）
  ↓
RP-G（删除 404）
  ↓
RP-I（oneshot spec 守卫）
  ↓
门禁 + 038 交付报告 + INDEX/01 登记
```

RP-D/E/F 互不依赖，可同一提交或分提交。推荐 **每包一提交信息**（用户批准后再 commit）。

---

## 3. RP-C — IsolatedModeError → 400

### 目标

隔离门禁拒绝必须是 **400**，文案保留原始英文原因（已是英文），不得再进 `generic_exception_handler` 变成 `INTERNAL_ERROR`。

### 改哪里

**`app/main.py`**

在现有 `@app.exception_handler(HTTPException)` 旁新增：

```python
from app.services.isolated_mode import IsolatedModeError

@app.exception_handler(IsolatedModeError)
async def isolated_mode_exception_handler(_request: Request, exc: IsolatedModeError):
    return JSONResponse(
        status_code=400,
        content={"code": "HTTP_400", "message": str(exc)},
    )
```

放在 `generic_exception_handler` **之前**注册（FastAPI 按类型匹配，子类优先，但显式注册更稳）。

**不要**在每个 config POST 里散落 try/except。全局一处即可覆盖 `save_config` / Pydantic validator 里直接 raise 的路径。注意：`DataSourceConfig.fixture_requires_isolated_mode` 若在模型校验阶段 raise IsolatedModeError，可能被 Pydantic 包成 ValidationError→422，这可接受；本包断言的是 **save_config 路径**。

### 测试（新文件 `tests/test_isolated_mode_http.py`）

用 TestClient + monkeypatch `TEST_ISOLATED_MODE=true` 的代价高（要 demo 路径）。更稳的最小测法：

1. 单测：构造 FastAPI 小应用，注册与 `main.py` 相同的 IsolatedModeError handler，路由里 `raise IsolatedModeError("isolated mode requires data_source.type=fixture")` → 400，body `code=HTTP_400`，message 含该字符串，**不是** `INTERNAL_ERROR`。
2. 单测：同一应用 raise `RuntimeError("other")` 若未注册裸 Exception handler则不测；改为对 `app.main.generic_exception_handler` 不重复。再测 IsolatedModeError **不是**被 HTTPException handler 吃掉。

若能低成本挂主应用：admin 保存 `data-source` 为 `oracle` 且 env 已是 isolated——这依赖 demo 环境，**不要**作为必过门禁。以（1）为验收。

### 验收

- IsolatedModeError → 400 + 原文字 message
- 其他未捕获异常仍 500
- 既有 `tests/test_isolated_demo_environment.py` 仍绿

---

## 4. RP-B — 配置写端点改为 unset-merge（禁止空 body 用默认值覆盖）

### 目标

与 relay-alert 对齐：

- 请求体未出现的字段 **保留现有配置**。
- 空 JSON `{}` → **422** `empty config update is not allowed`（英文）。
- 前端完整表单（字段全给）行为与现在一致。
- 密钥空串不覆盖已有 `password_enc` / `api_key_enc`（oracle/pg/emr/dify 已有逻辑必须保留）。

### 公共辅助（放 `app/routers/config.py` 内部即可，不要新模块除非文件过大）

```python
def _reject_empty_update(incoming: dict) -> None:
    if not incoming:
        raise HTTPException(status_code=422, detail="empty config update is not allowed")

def _merge_section(section: str, incoming: dict) -> dict:
    current = load_config().get(section, {}) or {}
    merged = {**current, **incoming}
    update_section(section, merged)
    return merged
```

### 逐端点改法（必须全部改，漏一个就还能被空 body 打穿）

| 函数 | 现状 | 改法 |
|---|---|---|
| `save_data_source` | `body.model_dump()` 全量 | `incoming = body.model_dump(exclude_unset=True)` → 空则 422 → merge `data_source` |
| `save_oracle_config` | 手搓 `data` 全量写 | 先 `exclude_unset`；空则 422；密码：仅当 incoming 含非空 `password` 才 encrypt，否则保留 `current.password_enc`；其余字段 merge；`field_mapping` 若未 set 则不改；SQL 清洗只对 set 的 query_sql/dept_sql |
| `save_postgresql_config` | 同上 | 同 oracle |
| `save_emr_vastbase`（约 L383） | 全量 | 同「unset merge + 空密码保留 enc」 |
| `save_dify`（约 L539） | 全量 | unset merge；空 api_key 保留 enc；`base_url` 走现有 normalize |
| `save_departments` | `model_dump()` | unset merge；空 422 |
| `_save_scheduler_section` | `payload = body.model_dump()` 后改 cron | `incoming = body.model_dump(exclude_unset=True)`；空 422；再按 **已出现的** schedule_mode/daily_time/cron 解析 cron；`enabled` 未出现则不改；`audit_run_mode` 仍由 daily/discharge 两个入口强制写入（这两入口在调用 `_save_scheduler_section` 前赋值，算 set） |
| `save_push_settings` | 全量 | unset merge |
| `save_privacy_masking_config` | 全量 | unset merge（这是脱敏被空 body 关掉的直接原因） |
| `save_notify` | 全量 | unset merge；若 `channels` 未 set 则不改 |
| `save_relay_alert_config` | **已 merge** | **保持**；可加「incoming 去掉 secret 后若完全空且没有 secret_key 则 422」，但 **不要破坏**「只提交 `alert_dept_filter`」的部分保存（AGENTS Relay Alert 红线）。relay 的 `exclude_unset` 已满足；空 `{}` 对 relay 目前会 merge 成原样 200——允许保留 200（无字段变更）或与其它端点统一 422。**本轮统一 422**，前提是 `exclude_unset` 后无任何键（包括未提交 secret_key）。前端 relay 保存一定带字段，不受影响。 |

**禁止**把 `update_section` 改回整份 config 替换语义以外的东西；`update_section` 仍是「整节替换」，merge 发生在调用它之前。

### 前端

无需改。legacy `config.js` 与 ui-next `ConfigPage.vue` 保存时都发完整表单。

### 测试（新文件 `tests/test_config_partial_update.py`）

用 TestClient 打真实 `config` 路由，fixture 隔离临时 `CONFIG_DIR`（参考 `tests/test_relay_alert_service.py` / 现有 config 测试怎么指到临时 json）。至少：

| ID | 步骤 | 期望 |
|---|---|---|
| T1 | 预置 `privacy_masking.enabled=true`，`POST /api/config/privacy-masking` body `{}` | 422；GET 仍 enabled=true |
| T2 | `POST` `{"mask_phone": false}` | 200；enabled 仍 true，mask_phone=false |
| T3 | 预置 `scheduler.enabled=false`，空 `{}` POST `/api/config/scheduler` | 422；enabled 仍 false |
| T4 | 预置 oracle.host=`127.0.0.1`，空 `{}` POST `/api/config/oracle` | 422；host 不变 |
| T5 | POST oracle `{"port": 1522}`（其它 unset） | 200；host 仍 127.0.0.1，port=1522，password_enc 不变 |
| T6 | 预置 push.interval_ms=800，空 `{}` POST `/api/config/push` | 422 |
| T7 | 对照：完整合法 privacy body（五字段全给） | 200，值与 body 一致（回归前端全量保存） |
| T8 | relay-alert 只提交 `alert_dept_filter` | 200，enabled/base_url/receiver_rules **不被清空**（AGENTS 红线回归） |

权限：这些端点要 `manage_config`。测试里用 admin 用户或 override `Depends`，与现有 config 测试同一套路。

### 验收

- 空 body 不再改磁盘配置（可用备份目录无新文件或节内容哈希不变辅助断言）。
- 既有 `tests/test_relay_alert_service.py` 部分更新仍绿。

---

## 5. RP-D — `departments/list` 与 logs 科室候选的 fixture 分支

### 目标

`data_source.type=fixture` 时 **禁止**走 Oracle/cx_Oracle。返回 demo 12 科室名称。postgresql 分支保持。未知类型 → **400**（英文 detail），不要 500。

### `app/routers/config.py` `list_departments_by_data_source`

伪代码：

```python
data_source = (cfg_all.get("data_source", {}) or {}).get("type", "oracle")
if data_source == "fixture":
    from app.demo_support.dataset import DEPARTMENTS
    return {"departments": [name for _code, name in DEPARTMENTS]}
if data_source == "postgresql":
    ...
if data_source == "oracle":
    ...
raise HTTPException(status_code=400, detail=f"department list is not available for data_source.type={data_source}")
```

cx_Oracle / 连接失败：保留 500 泛化文案 **或** 改为 503 `department list backend unavailable`。本轮：**Oracle 驱动缺失 → 503**，detail 英文 `Oracle client is not available`，日志仍记录原始异常。不要把 SQL/主机写进 HTTP body（已有 `public_error_message` 则用它）。

### `app/routers/logs.py` 约 L490-508

同样加 `fixture` 分支：`biz_depts = {name for _, name in DEPARTMENTS}`。失败仍 fail-open。不要让 fixture demo 去 import cx_Oracle。

### 测试（`tests/test_departments_list_datasource.py`）

| ID | 条件 | 期望 |
|---|---|---|
| T1 | monkeypatch load_config `data_source.type=fixture` | GET `/api/config/departments/list` 200，`departments` 含「听觉植入科」，长度=12，**不**调用 `fetch_department_list` |
| T2 | type=oracle 且 `fetch_department_list` side_effect=Exception("cx_Oracle 未安装") | 503（或若你实现为 500 则测 500，但计划指定 503） |
| T3 | type=`sqlite`（非法） | 400 |
| T4 | type=postgresql 时调用 `fetch_pg_department_list` 一次 | 200 |

GET 只需登录用户（现接口 `get_current_user`，不是 manage_config）。

### 前端

`ConfigPage.vue` / `scheduler.js` 已 `.catch` 空列表，修后端后警告消失即可。**不要**改前端去吞 500。

---

## 6. RP-E — census 能力不支持改为 400

### 目标

「当前数据源不是 Oracle」是 **400**，detail 保持可读原因。500 只留给真正的查询失败。

### 改法（最小）

`app/services/patient_census_service.py` `_assert_data_source_oracle`：

```python
if ds_type != "oracle":
    raise ValueError(f"患者清单仅支持 Oracle 数据源，当前数据源类型: {ds_type}")
```

`patients.py` 已有 `except ValueError → 400`。`census` / `census/summary` / `census/precheck` 自动变 400。

`census/metadata` 目前只捕 RuntimeError→500，**补** `except ValueError → 400`。

HTTP detail 经 `public_error_message`。中文 RuntimeError 原文会被脱敏成泛化英文——**测一下实际 400 body**。若 `public_error_message` 把中文原因吃掉，改为抛英文 ValueError：

`Patient census requires Oracle data source, current type: {ds_type}`

以「客户端能区分不是 500」为第一目标；detail 英文优先。

### 测试

扩 `tests/test_patient_census_service.py` + 路由级：

| ID | 期望 |
|---|---|
| T1 | config `data_source.type=fixture` 调 `load_patient_census` → ValueError |
| T2 | TestClient GET `/api/patients/census` fixture → **400**（不是 500） |
| T3 | 同 `/census/summary`、`/census/metadata` → 400 |
| T4 | type=oracle 且下游 RuntimeError（mock）仍 500（防误把真故障改成 400） |

路由测试需要 `view_scheduler` 权限用户。

---

## 7. RP-F — 患者就诊导出：数据源前置 + RuntimeError 打 traceback

### 目标

1. 非 oracle（含 fixture）→ **400**，不连 Oracle。
2. `RuntimeError` 分支补 `logger.error(..., exc_info=True)`。
3. 空筛选命中仍返回表头 Excel（既有契约，`patient_qc.py` 注释与 031 T1-0，**禁止破坏**）。

### `export_patient_visit_summary`（service L898+）

在 `get_oracle_connection` 之前：

```python
from app.services.config_parser import ConfigParser
ds_type = ConfigParser.get_data_source_type(config)
if ds_type != "oracle":
    raise ValueError(
        f"patient visit summary export requires Oracle data source, current type: {ds_type}"
    )
```

空 `patient_keys` 早退（L914-915）保持在数据源检查 **之前**（无命中不连库，fixture 下空筛选仍应 200 表头）。**无筛选参数且 fixture**：`query_patient_qc_visit_keys` 可能返回非空 SYNTH 键，然后 `_export` 会连 Oracle——这才是 500 根因。因此数据源检查必须在「有 keys 要查业务库」时发生；建议：

- keys 为空 → 仍空表头（不检查数据源也可以）。
- keys 非空或 keys is None（全量）→ 必须 oracle，否则 ValueError。

路由已把 ValueError → 400。

### `patient_qc.py` L1202-1212

在 raise 前加：

```python
logger.error("患者就诊导出 RuntimeError: %s", exc, exc_info=True)
```

### 测试

扩 `tests/test_patient_qc_export_filters.py` 或新 `tests/test_patient_visit_export_datasource.py`：

| ID | 期望 |
|---|---|
| T1 | monkeypatch load_config fixture + visit_keys 非空 → `_export` ValueError |
| T2 | 路由 GET `/api/patient-qc/export/patient-visit-summary` fixture + 能命中 keys 的用户 → **400**，审计 `status=failed` 仍写入（现有 failed 审计路径） |
| T3 | visit_keys 空集合 → 200 Excel 表头（回归 031 T1-0） |
| T4 | RuntimeError 路径日志带 traceback：mock `_export` raise RuntimeError，断言 `logger.error` 被以 `exc_info=True` 调用（mock logger） |

---

## 8. RP-A — SQLite 应用库 busy_timeout + 连接级 WAL

### 目标

默认 `APP_DB_TYPE=sqlite` 下，调度推送线程与请求线程并发写时，等待而不是立刻 `database is locked` 失败。不改变 Oracle 引擎参数。

### `app/database.py` `create_engine_for_config` sqlite 分支

```python
from sqlalchemy import event

sqlite_engine = create_engine(
    _build_sqlite_url(),
    connect_args={
        "check_same_thread": False,
        "timeout": 30.0,  # sqlite3.connect 等待秒数
    },
    echo=False,
    poolclass=NullPool,
    pool_pre_ping=True,
    echo_pool=False,
)

@event.listens_for(sqlite_engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, _connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA busy_timeout=30000")
    # 文件库才切 WAL；:memory: 忽略失败
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    cursor.close()

return sqlite_engine
```

`init_db()` 里现有 PRAGMA 块可保留作双保险，但 **busy_timeout 必须在 connect 监听器**，因为 NullPool 每连接新建，init_db 的 PRAGMA 不会遗传 timeout。

### `is_transient_app_db_error`

增加标记：`"database is locked"`、`"database is busy"`。供后续重试判断。**本轮不要**在 `push_executor` 上新增大范围重试逻辑（易改变幂等/claim 语义）。先靠 timeout。

### 测试（`tests/test_sqlite_busy_timeout.py`）

| ID | 做法 | 期望 |
|---|---|---|
| T1 | 对 sqlite 引擎连一次，`PRAGMA busy_timeout` 读回 ≥ 30000 | 通过 |
| T2 | 临时文件 DB，NullPool，两线程各插入 40 行同一表，join | 0 个 `database is locked`，行数=80 |
| T3 | `get_app_db_type()==oracle` 时不注册 sqlite timeout（mock 分支或跳过） | 不破坏 oracle 引擎构造（可用 unit 断言 create_engine_for_config 在 monkeypatch APP_DB_TYPE=sqlite 时 connect_args 含 timeout） |

T2 是本包核心。超时 30s 内应完成；pytest 给 60s timeout。

内存库 StaticPool 的既有测试（大量 conftest）不应受 busy_timeout 影响。跑全量 pytest 确认。

### 不要做

- 不要改回 `StaticPool`（101 基线明确 NullPool+WAL）。
- 不要把应用库改成 WAL 以外的 journal。
- 不要为 Oracle 加 sqlite pragma。

---

## 9. RP-H — 移动端反馈 CSRF（K-1）

### 目标

医生 H5 用 HMAC token 提交反馈时，**即使浏览器带有管理端 Cookie**，只要 token 合法，也不应被 CSRF 中间件 403。同时给 H5 `fetch` 加上 `X-Requested-With`，双保险。

### 后端 `app/security_middleware.py`

```python
_CSRF_EXEMPT_PATHS = (
    "/api/users/login",
    "/api/mobile/qc-feedback",
)
```

模块 docstring 加一句：mobile 写端点认证主体是 alert token，Cookie 属附带；豁免避免同浏览器管理端会话误伤。logout **保持**强校验。

### 前端 `static/scripts/mobile/qc_detail.js`

```javascript
headers: {
  'Content-Type': 'application/json',
  'X-Requested-With': 'XMLHttpRequest',
},
```

### 测试（扩 `tests/test_cookie_csrf_security.py`）

现有 fixture 的 app **没有**挂 `mobile_qc` 路由。两种做法，选 B：

- **A**：在该文件加 mobile 路由（重）。
- **B**：新 `tests/test_mobile_qc_csrf.py`：最小 FastAPI = `register_security_middleware` + 一个 `POST /api/mobile/qc-feedback` stub 返回 200。

用例：

| ID | 请求 | 期望 |
|---|---|---|
| T1 | 先 login 拿 Cookie，POST `/api/mobile/qc-feedback` **无** X-Requested-With、**无** Bearer | **不是 403 CSRF**（stub 200 或真实 400/422/401 均可，断言 `message` 不含 `Missing CSRF header`） |
| T2 | 同 Cookie POST `/api/users/logout` 无自定义头 | 仍 403 CSRF（回归） |
| T3 | Cookie + `X-Requested-With` POST mobile | 通过中间件 |
| T4 | 无 Cookie POST mobile | 中间件放行（token 校验是路由的事） |

前端无法用 pytest 跑 js。RP-H 后端测试足够；静态上可加可选断言：`qc_detail.js` 含 `X-Requested-With` 字符串（参考 `scripts/frontend_regression_check.py` 风格，**不要**为此大改检查脚本；在 python 测试里读文件断言即可）。

### 不要做

- 不要豁免全部 `/api/mobile/*`（目前只有这一处写；豁免过宽无必要，但若你发现还有 POST，一并列入并补测）。
- 不要改 HMAC token 校验。

---

## 10. RP-G — 审计类型删除不存在 → 404

### `app/services/audit_type_registry.py` `delete`

在过滤前：

```python
exists = any(
    str(item.get("code") or "").strip() == target
    for item in (self.config.get("audit_types") or [])
)
if not exists:
    raise KeyError(target)
```

`progress_vs_nursing` 仍先 422（现有 ValueError）。

### `app/routers/audit_types.py` `delete_audit_type`

```python
try:
    registry.delete(code)
except KeyError:
    raise HTTPException(status_code=404, detail="audit type not found")
except ValueError as exc:
    raise HTTPException(status_code=422, detail=public_error_message(exc, "审计类型删除失败"))
```

GET 更新已有 404 文案，保持一致。

### 测试（扩 `tests/test_audit_types_api.py`）

`_FakeRegistry.delete` 改为：不存在则 `raise KeyError`；存在则 pop。

| ID | 期望 |
|---|---|
| T1 | DELETE `/api/audit-types/does_not_exist` → 404 |
| T2 | DELETE `/api/audit-types/options`（无此 code）→ 404（不再 200） |
| T3 | DELETE `/api/audit-types/prearchive` → 404 |
| T4 | DELETE `progress_vs_nursing` 仍 422 |
| T5 | DELETE 一个 FakeRegistry 里存在的非内置 code → 200，且 `deleted_code` 被记录 |

---

## 11. RP-I — oneshot ui-next spec 守卫

### `frontend/tests/e2e/oneshot-uinext-sweep.spec.ts`

文件顶部（import 后、test 前）加：

```typescript
test.skip(
  process.env.ONESHOT_E2E !== 'true' && process.env.PLAYWRIGHT_SKIP_WEBSERVER !== '1',
  'oneshot sweep requires demo_env serve; set ONESHOT_E2E=true (and PLAYWRIGHT_SKIP_WEBSERVER=1)',
)
```

更稳且与 legacy 对称的写法（**采用这个**）：

```typescript
test.skip(process.env.ONESHOT_E2E !== 'true', 'requires demo_env serve + ONESHOT_E2E=true')
```

默认 `npm --prefix frontend run test:e2e` **跳过**该文件。oneshot 复跑时显式 `ONESHOT_E2E=true PLAYWRIGHT_SKIP_WEBSERVER=1 ...`。

legacy 文件已有 `LEGACY_E2E` 守卫，**不要改断言语义**，只允许补注释。

把这两个 spec 纳入本轮交付（它们目前是 untracked）。不要改 PAGES/ROUTES 列表。

---

## 12. 文档与登记（与代码同一轮）

1. 实现过程中不要改 037 正文历史结论。
2. 完成后写 **`docs/ACTIVE/038_ONESHOT_FINDINGS_REPAIR_DELIVERY_20260902.md`**：每包勾选、测试数字、未决项、与 037 的偏差。
3. `docs/INDEX.md`：037 状态改为「已执行完毕，交付=038」；新增 038 行；更新文头盘点日期。
4. `开发起步包/01_统一修改记录.md` **追加一行**（append-only）。
5. 若改了 101/102 契约（配置部分更新、census 400、departments/list fixture），在 `docs/reference/101_FEATURE_BASELINE.md` 追加短条目，不要重写全文。

---

## 13. 逐包测试命令（执行时按此跑，红则停）

仓库根：

```
python -m compileall app tests scripts
```

每包后跑该包新测试，再跑相关旧文件：

```
python -m pytest tests/test_isolated_mode_http.py -q
python -m pytest tests/test_config_partial_update.py tests/test_relay_alert_service.py -q
python -m pytest tests/test_departments_list_datasource.py -q
python -m pytest tests/test_patient_census_service.py tests/test_patient_visit_export_datasource.py tests/test_patient_qc_export_filters.py tests/test_patient_visit_export_audit.py -q
python -m pytest tests/test_sqlite_busy_timeout.py -q
python -m pytest tests/test_cookie_csrf_security.py tests/test_mobile_qc_csrf.py tests/test_csp_policy_baseline.py -q
python -m pytest tests/test_audit_types_api.py tests/test_prearchive_rules_display.py -q
```

全部包完成后 §15 门禁。

---

## 14. 回归红线（改到相关面时必须保持）

- relay-alert **部分保存**不覆盖 `enabled` / `secret_key_enc` / `base_url` / `receiver_rules` / `nurse_heads`。
- 导出空命中 = 成功表头文件 + 审计 success（031 T1-0）；超 2000 → 400 英文。
- 新导出失败/成功都走 `record_export_audit`。
- Dify `mr_text` → `mr_txt` 仅 pusher 映射。
- Cookie CSRF：logout 仍要头；login 仍豁免。
- CSP 含 `'unsafe-eval'`，禁止删。
- SQLite 保持 NullPool，禁止改回 StaticPool。
- prearchive **零** `import app.*`；本轮不要改 `prearchive_service/` 业务。
- Oracle 空串=NULL 语义、PushLog.dept 过滤不要用 SQL `!= ""`。
- 不改 demo 口令、不把密钥写入测试。

---

## 15. 全绿门禁（一次通过才算完）

仓库根：

```
python -m compileall app tests scripts
python -m pytest
python scripts/check_naming_convention.py
python -m pytest prearchive_service/tests -q
python prearchive_service/check_isolation.py
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
npm --prefix frontend run test:e2e
```

判据：

- pytest **0 failed**，无意外 skip。基线参考：主服务 oneshot 时 1211 passed；本轮会 **增加** 用例，只报新计数，禁止为凑 1211 删测试。
- prearchive 仍约 211 passed + 1 skipped（本轮不应改 prearchive）。
- ui-next e2e：**0 failed**。oneshot-uinext-sweep 必须是 skipped（RP-I），既有用例不少于 52 passed。
- legacy e2e 不在默认 `test:e2e` 里（独立 `playwright.legacy.config.ts` + `LEGACY_E2E`）。不要为跑 legacy 起 demo，除非你自愿且不阻塞门禁。
- `frontend_regression_check.py` 若仍作为习惯检查：0 high。不是强制门禁，但若你改了 `static/scripts/app.js` 版本锚，需同步契约测试（本计划 **不要求** 改 app.js 版本，除非动了 static 且生产缓存相关——本轮 qc_detail.js 有改动，**把 `static` 移动端脚本的缓存击穿交给执行者判断**：若 `qc_detail.html` 以 query 引 js，给 `qc_detail.js` 加版本参数；没有则只改 js 文件，文档注明需刷新缓存）。

---

## 16. 建议提交粒度（用户批准后再 git commit）

1. `fix(config): IsolatedModeError 映射 400`
2. `fix(config): 配置写端点空 body 不再用模型默认值覆盖`
3. `fix(config): fixture 数据源科室列表不再走 Oracle`
4. `fix(patients): census 非 Oracle 返回 400`
5. `fix(export): 就诊汇总导出校验数据源并补 traceback`
6. `fix(db): SQLite busy_timeout/WAL 按连接设置`
7. `fix(mobile): H5 反馈豁免附带 Cookie CSRF 并补请求头`
8. `fix(audit-types): 删除不存在的类型返回 404`
9. `test(e2e): oneshot ui-next 扫荡默认跳过`
10. `docs: 038 交付 + INDEX/01 登记`

允许合并 3/4/5 为一笔 `fix(datasource): fixture/非Oracle 能力分支与错误码`。

---

## 17. 执行 AI 禁止事项清单（再读一遍）

- 禁止「顺手」修 U-3 科室权限、O-2 trigger 确认框、O-1 口令、CSP、scheduler 双发、requests 版本。
- 禁止把 census/export 在 fixture 下假装返回生产 Oracle 数据。
- 禁止为让 oneshot 扫荡变绿去改业务 500 为前端吞掉。
- 禁止修改 `review/oneshot-20260901/**` 历史证据。
- 禁止生产 SSH / 改容器。
- 发现 037 与代码冲突：以代码+测试为准，在 038 写「偏差」，不要悄悄改 037 历史裁定。

---

## 18. 给执行者的最小阅读顺序

1. `AGENTS.md`
2. `开发起步包/README.md` + `00_AI协作规则.md` + `01_统一修改记录.md` 末 10 行
3. **本文 037 全文**
4. 按需打开 oneshot 主文件核对现象（`review/oneshot-20260901/问题记录_主文件.md`）
5. 按 §2 顺序改代码 + §13/§15 测试

开始前记录 `git log --oneline -1` 与 `git status --short`。结束时两者再记入 038。

---

## 19. 验收勾选（038 必须逐条回答）

- [ ] RP-C IsolatedModeError → 400
- [ ] RP-B 空 `{}` 对 privacy/scheduler/oracle/push 均 422 且配置不变；部分字段 merge 正确；relay 部分保存红线仍在
- [ ] RP-D fixture `departments/list` 200 十二科室；不 import cx_Oracle
- [ ] RP-E census×3 fixture → 400
- [ ] RP-F 非空 keys + fixture → 400；空 keys → 200 表头；RuntimeError 有 traceback
- [ ] RP-A sqlite pragma/timeout 测试过；并发插入无 locked
- [ ] RP-H Cookie 无头 POST qc-feedback 不再 CSRF 403；logout 仍 403
- [ ] RP-G DELETE 不存在 404；内置 422
- [ ] RP-I 默认 e2e 0 fail，oneshot uinext skipped
- [ ] §15 门禁一次通过
- [ ] 038 + INDEX + 01 已写
- [ ] 零生产写入

---

## 20. 核查方法（分析师本轮已做，执行者不必重复发现）

| 声明 | 证据 |
|---|---|
| WAL 只在 init_db | `app/database.py:148-158`，create_engine 无 timeout |
| 配置全量替换 | `update_section` L571-575；privacy POST L876-888 直接 `model_dump()` |
| relay 已 merge | L976 `exclude_unset=True` |
| IsolatedModeError 是 RuntimeError | `isolated_mode.py:13` |
| departments/list else→oracle | `config.py:707-714` |
| census RuntimeError | `patient_census_service.py:232` + `patients.py:49` |
| visit export 无数据源门 | `patient_visit_export_service.py:917-921`；RuntimeError 无日志 L1202-1212 |
| delete 无存在性 | `audit_type_registry.py:276-286` |
| H5 fetch 无 CSRF 头 | `qc_detail.js:78-81`；豁免表只有 login L39 |

以上行号以 HEAD `52998cc` 附近工作区为准；执行时若漂移，按符号搜索，勿死守行号。
