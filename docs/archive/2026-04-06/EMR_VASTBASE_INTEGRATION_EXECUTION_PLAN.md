# 电子病历海量库接入执行计划

## 1. 背景

当前系统以 Oracle 业务库作为主要临床数据来源。患者质控总览的“导出汇总”已从 Oracle 临时表 `TEMP_PAT_VISIT_LIST` 出发，关联患者基本信息、病程、护理、检验、检查、手术、质控推送日志，并已增加 Oracle 数据中心抽取表 `jhemr.V_cyJL` 的出院记录。

现需新增电子病历海量库视图 `jhemr.v_blws`，用于更及时地读取病历文书。该视图已重新修订，包含 `patient_id`、`visit_id` 和科室字段，因此可以直接用于患者住院次关联和科室筛选，不再依赖 `serial_number` 拆分。

## 2. 总目标

1. 保持现有 Oracle 分析链路稳定，不破坏已有质控、推送、日志、调度和导出行为。
2. 新增“电子病历海量库文书数据源”，专门用于读取病历文书。
3. 新质控支持混合数据源：检验、检查、护理、首页、基础信息继续走 Oracle；病程、首次病程、出院记录等文书可走海量库。
4. 患者质控总览的“导出汇总”中，病程记录和出院记录优先使用海量库，失败或未启用时回退当前 Oracle 逻辑。
5. 增加配置、连接测试、查询诊断和回归测试，便于上线验证。

## 3. 当前已完成状态

患者质控总览导出汇总已经具备出院记录导出能力：

1. 文件：`app/services/patient_visit_export_service.py`
2. 动态列分类：`_CATEGORY_DEFS["discharge"]`
3. Excel 列前缀：`出院记录`
4. 字段：`记录时间`、`病历名称`、`内容`、`创建科室`、`创建人`
5. 当前出院记录 Oracle 来源：`jhemr.V_cyJL`
6. 当前出院记录过滤：`病历名称 LIKE '%出院记录%'` 且 `RN = 1`
7. 当前病程记录 Oracle 来源：Oracle 表 `bcjl202603`（`JOIN jhemr.v_cybr ON 患者ID/次数`），查询函数为 `_query_progress_notes()`
8. 当前入口：`GET /api/patient-qc/export/patient-visit-summary`

后续开发：
- 出院记录升级为优先海量库 `jhemr.v_blws`，**异常**时回退 Oracle `jhemr.V_cyJL`。
- 病程记录升级为优先海量库 `jhemr.v_blws`，**异常**时回退 Oracle `bcjl202603`。

## 4. 不做事项

1. 不把全局 `data_source.type` 直接切成海量库。
2. 不移除 Oracle 数据源。
3. 不改 Dify 主输入约定，`mr_txt` 仍必须是字符串。
4. 不让旧质控自动切换到海量库。
5. 不在代码、文档、日志、测试脚本中写入明文数据库密码。
6. 不使用生产查询 `SELECT * FROM jhemr.v_blws` 或无条件全表 `COUNT(*)`。

## 5. 推荐架构

采用“Oracle 主数据源 + 海量库文书子数据源”的混合架构。

### 5.1 数据源分工

| 数据类别 | 推荐来源 | 说明 |
|---|---|---|
| 患者清单 | Oracle `TEMP_PAT_VISIT_LIST` | 维持现有导出入口和范围 |
| 患者基本信息 | Oracle `jhemr.v_cybr` | 继续使用当前稳定逻辑 |
| 检验 | Oracle HIS 表 | 当前海量库视图不覆盖 |
| 检查 | Oracle HIS 表 | 当前海量库视图不覆盖 |
| 护理 | Oracle 护理表 | 当前海量库视图不覆盖 |
| 首页/手术 | Oracle `jhemr.v_cybr` | 继续使用当前稳定逻辑 |
| 病程文书 | 海量库 `jhemr.v_blws` 优先 | Oracle 回退 |
| 首次病程 | 海量库 `jhemr.v_blws` 优先 | 用于新质控 |
| 出院记录 | 海量库 `jhemr.v_blws` 优先 | Oracle `jhemr.V_cyJL` 回退 |

### 5.2 代码路由原则

1. 旧配置没有 `backend` 字段时，完全保持当前行为。
2. 新质控可为每个 source 单独配置 `backend`。
3. `backend=oracle` 强制使用全局 `oracle` 配置节，调用 `fetch_records()`。
4. `backend=postgresql` 强制使用全局 `postgresql` 配置节，调用 `fetch_pg_records()`；两者虽然都走 psycopg2 协议，但连接参数来自不同配置节。
5. `backend=emr_vastbase` 使用**新增独立**的 `emr_vastbase` 配置节，调用 `fetch_emr_records()`；与 `backend=postgresql` 不同，它有独立的 host/database/schema/view 和字段名映射配置。
6. 汇总导出不依赖 `audit_type.sources`，需要单独在导出服务中接入海量库优先查询。

## 6. 配置设计

新增配置节 `emr_vastbase`。

```json
{
  "emr_vastbase": {
    "enabled": false,
    "host": "",
    "port": 5432,
    "database": "",
    "username": "",
    "password_enc": "",
    "schema": "jhemr",
    "view": "v_blws",
    "patient_id_field": "patient_id",
    "visit_id_field": "visit_id",
    "dept_field": "dept_name",
    "content_field": "progress_message",
    "title_field": "progress_title_name",
    "type_field": "progress_type_name",
    "template_field": "progress_template_name",
    "record_time_field": "record_time_format",
    "finish_time_field": "finish_time_format",
    "doctor_field": "doctor_name",
    "status_field": "progress_status",
    "connect_timeout_seconds": 10,
    "statement_timeout_ms": 60000,
    "max_records": 50000,
    "use_for_export_progress": true,
    "use_for_export_discharge": true,
    "fallback_to_oracle": true
  }
}
```

注意：
- `dept_field` 默认值为 `dept_name`（实际视图字段）。如实际字段名不同，只改配置，不改 SQL 业务逻辑。
- `patient_id_field`、`visit_id_field`、`dept_field`、`content_field` 等字段名会被拼入 SQL（列名无法使用参数绑定），在 `emr_vastbase_client.py` 中**必须经白名单正则校验**（仅允许 `^[a-zA-Z_][a-zA-Z0-9_]{0,63}$`）后才能拼接，严禁直接信任配置值。

## 7. 字段映射

| 系统字段 | 海量库字段 | 用途 |
|---|---|---|
| `patient_id` | `patient_id` | 患者 ID |
| `visit_number` | `visit_id` | 住院次数/住院次 |
| `admission_no` | `inp_no` | 住院号 |
| `dept` | 配置项 `dept_field`（实际字段 `dept_name`） | 科室筛选和展示 |
| `event_time` | 优先 `finish_time_format`，其次 `record_time_format`、`first_save_time`、`create_date` | 文书时间 |
| `record_name` | 优先 `progress_title_name`，其次 `progress_template_name`、`progress_type_name` | 文书标题 |
| `record_type` | `progress_type_name` | 文书类型 |
| `content` | `progress_message` | 文书正文 |
| `creator` | `doctor_name` | 创建/签名医生 |
| `creator_id` | `doctor_guid` | 医生编号 |
| `document_id` | `progress_guid` | 文书唯一标识 |
| `status` | `progress_status` 或 `state` | 文书状态 |
| `url` | `progress_url` / `cda_url` / `pdf_url` | 文书链接 |

## 8. 需要修改的文件

### 8.1 后端

1. 新增：`app/emr_vastbase_client.py`
2. 修改：`app/services/config_parser.py`
3. 修改：`app/schemas.py`
4. 修改：`app/routers/config.py`
5. 修改：`config/config.json.template`
6. 修改：`app/services/data_source_loader.py`
7. 修改：`app/services/patient_visit_export_service.py`

### 8.2 前端，可选但推荐

1. 修改：`static/templates/pages/config.html`
2. 修改：`static/scripts/modules/config.js`
3. 修改：`static/scripts/app.js`

### 8.3 测试

1. 新增：`tests/test_emr_vastbase_client.py`
2. 新增：`tests/test_data_source_loader_emr_backend.py`
3. 新增：`tests/test_patient_visit_export_vastbase.py`

## 9. 后端实现步骤

### 9.1 新增海量库客户端

新增 `app/emr_vastbase_client.py`，提供以下函数：

```python
def get_emr_vastbase_connection(config: dict):
    ...

def test_emr_vastbase_connection(config: dict) -> dict:
    ...

def fetch_emr_records(config: dict, dept_list: list[str], query_date: str) -> list[dict]:
    ...

def fetch_emr_documents_by_visits(
    config: dict,
    patient_keys: list[tuple[str, str]],
    document_kind: str = "all",
) -> dict[tuple[str, str], list[dict]]:
    ...
```

实现要求：

1. 使用 `psycopg2`，不使用 JDBC JAR。
2. 每次连接设置 `connect_timeout`。
3. 连接成功后执行 `SET statement_timeout = <配置值>`。
4. 查询全部使用参数绑定。
5. 严禁拼接患者 ID、住院次、科室值。
6. 可拼接的只有通过白名单校验后的 schema、view、字段名。
7. 日志只记录 host、database、耗时、行数，不记录密码和文书正文。
8. 返回统一字段：`patient_id`、`visit_number`、`dept`（来自 `dept_name`）、`event_time`、`record_name`、`content`、`creator`、`document_id`、`status`。
9. 超过 `max_records` 时截断并记录 warning。
10. 查询失败时抛异常，由调用方决定是否回退 Oracle。

### 9.2 配置解析

修改 `app/services/config_parser.py`：

1. 新增 `parse_emr_vastbase_config(config)`。
2. 解密 `password_enc` 到运行时字段 `password`。
3. 默认补齐 `schema=jhemr`、`view=v_blws`。
4. 不在返回值中暴露明文密码给前端。

### 9.3 Schema 扩展

修改 `app/schemas.py`：

1. 新增 `EmrVastbaseConfig`。
2. 新增 `EmrVastbaseConfigResponse`。
3. 给 `AuditTypeSource` 增加字段：

```python
backend: Literal["default", "oracle", "postgresql", "emr_vastbase"] = "default"
```

兼容要求：旧配置没有 `backend` 时必须通过校验。

### 9.4 配置 API

修改 `app/routers/config.py`：

新增接口：

1. `GET /api/config/emr-vastbase`
2. `POST /api/config/emr-vastbase`
3. `POST /api/config/emr-vastbase/test`

连接测试返回建议结构：

```json
{
  "status": "up",
  "latency_ms": 25,
  "view_accessible": true,
  "columns_ok": true,
  "missing_columns": [],
  "sample_rows": 3,
  "message_readable": true
}
```

### 9.5 多源加载支持 per-source backend

修改 `app/services/data_source_loader.py` 的 `_fetch_source_records()`：

1. 读取 `source_cfg.get("backend", "default")`。
2. `default` 走当前全局 `data_source.type` 逻辑。
3. `oracle` 强制调用 `fetch_records()`。
4. `postgresql` 强制调用 `fetch_pg_records()`。
5. `emr_vastbase` 调用 `fetch_emr_records()`。
6. 保持 `return_diagnostics=False` 时仍返回 `list[PatientBundle]`。

### 9.6 汇总导出接入海量库

修改 `app/services/patient_visit_export_service.py`：

1. 保留当前 Oracle 连接，用于患者清单、基本信息、检验、检查、护理、手术。
2. 新增 `_query_progress_notes_from_emr(emr_cfg, patient_keys)` — 通过海量库按患者住院次批量查询病程文书。
3. 新增 `_query_discharge_records_from_emr(emr_cfg, patient_keys)` — 通过海量库按患者住院次批量查询出院记录（过滤条件见下）。
4. **修改主函数 `export_patient_visit_summary()`**：在加载 `oracle_cfg` 的同时读取 `emr_vastbase` 配置节，根据 `enabled`/`use_for_export_progress`/`use_for_export_discharge` 标志决定调用路径。
5. `progress` 查询顺序：海量库启用且 `use_for_export_progress=true` 时**先调用** `_query_progress_notes_from_emr()`；若该函数**抛出异常**且 `fallback_to_oracle=true`，记录 warning 并回退调用 `_query_progress_notes()`（Oracle `bcjl202603`）。
6. `discharge` 查询顺序：海量库启用且 `use_for_export_discharge=true` 时**先调用** `_query_discharge_records_from_emr()`；若该函数**抛出异常**且 `fallback_to_oracle=true`，记录 warning 并回退调用 `_query_discharge_records()`（Oracle `jhemr.V_cyJL`）。
7. **注意**：海量库查询返回空列表是合法的业务状态（该患者确实无该类文书），**不触发回退**。只有查询过程中抛出异常（连接失败、超时、SQL 错误等）才回退 Oracle，否则会掩盖真实数据空缺。
8. Excel 列结构保持不变。
9. 单元格内容超过 Excel 限制时截断到 32767 字符以内。

出院记录海量库过滤逻辑：

```sql
AND (
    COALESCE(progress_type_name, '') LIKE '%出院%'
    OR COALESCE(progress_title_name, '') LIKE '%出院%'
    OR COALESCE(progress_template_name, '') LIKE '%出院%'
)
```

## 10. SQL 模板建议

### 10.1 按患者住院次批量查询文书

适用于汇总导出。

**重要**：`VALUES (%s, %s), ...` 中的占位符数量在运行时是动态的，psycopg2 的 `cursor.execute()` 无法处理可变长度的 VALUES 行列表。应使用 `psycopg2.extras.execute_values` 或在代码中动态构造占位符字符串（如 `",".join(["(%s,%s)"] * len(patient_keys))`）并将列表展平后传参。

```sql
WITH target(patient_id, visit_id) AS (
    VALUES (%s, %s), (%s, %s)
)
SELECT
    b.patient_id,
    b.visit_id AS visit_number,
    b.dept_name,
    COALESCE(b.finish_time_format, b.record_time_format, b.first_save_time, b.create_date) AS event_time,
    COALESCE(b.progress_title_name, b.progress_template_name, b.progress_type_name) AS record_name,
    b.progress_type_name AS record_type,
    b.progress_message AS content,
    b.doctor_name AS creator,
    b.progress_guid AS document_id,
    b.progress_status AS status
FROM jhemr.v_blws b
JOIN target t
  ON b.patient_id = t.patient_id
 AND b.visit_id = t.visit_id
WHERE b.progress_message IS NOT NULL
ORDER BY b.patient_id, b.visit_id, event_time
```

### 10.2 按日期和科室查询文书

适用于新质控。

```sql
SELECT
    patient_id AS "患者ID",
    visit_id AS "次数",
    dept_name AS "所在科室名称",
    COALESCE(finish_time_format, record_time_format, first_save_time, create_date) AS "记录时间",
    COALESCE(progress_title_name, progress_template_name, progress_type_name) AS "病历名称",
    progress_message AS "病历内容",
    doctor_name AS "创建人"
FROM jhemr.v_blws
WHERE {dept_filter}
  AND LEFT(COALESCE(finish_time_format, record_time_format, first_save_time, create_date), 10) = %s
  AND progress_message IS NOT NULL
ORDER BY patient_id, visit_id, "记录时间"
```

## 11. 新质控配置示例

```json
{
  "sources": {
    "lab": {
      "type": "sql",
      "backend": "oracle",
      "query_sql": "...",
      "field_mapping": {}
    },
    "exam": {
      "type": "sql",
      "backend": "oracle",
      "query_sql": "...",
      "field_mapping": {}
    },
    "progress": {
      "type": "sql",
      "backend": "emr_vastbase",
      "query_sql": "SELECT patient_id AS \"患者ID\", visit_id AS \"次数\", dept_name AS \"所在科室名称\", COALESCE(finish_time_format, record_time_format, first_save_time, create_date) AS \"病程时间\", COALESCE(progress_title_name, progress_template_name, progress_type_name) AS \"病历名称\", progress_message AS \"病历内容\" FROM jhemr.v_blws WHERE {dept_filter} AND LEFT(COALESCE(finish_time_format, record_time_format, first_save_time, create_date), 10) = %s",
      "field_mapping": {
        "patient_id": "患者ID",
        "visit_number": "次数",
        "dept": "所在科室名称",
        "event_time": "病程时间",
        "record_name": "病历名称",
        "content": "病历内容"
      },
      "required": true
    }
  }
}
```

## 12. 上线前数据库复核 SQL

只允许只读查询。

### 12.1 字段核对

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'jhemr'
  AND table_name = 'v_blws'
ORDER BY ordinal_position;
```

### 12.2 小样本核对

```sql
SELECT patient_id,
       visit_id,
       dept_name,
       progress_type_name,
       progress_title_name,
       finish_time_format,
       record_time_format,
       LENGTH(progress_message) AS content_len
FROM jhemr.v_blws
WHERE patient_id IS NOT NULL
  AND visit_id IS NOT NULL
LIMIT 5;
```

### 12.3 精确患者住院次核对

```sql
SELECT COUNT(*)
FROM jhemr.v_blws
WHERE patient_id = %s
  AND visit_id = %s;
```

### 12.4 出院记录命中核对

```sql
SELECT COUNT(*)
FROM jhemr.v_blws
WHERE patient_id = %s
  AND visit_id = %s
  AND (
      COALESCE(progress_type_name, '') LIKE '%出院%'
      OR COALESCE(progress_title_name, '') LIKE '%出院%'
      OR COALESCE(progress_template_name, '') LIKE '%出院%'
  );
```

## 13. 测试计划

### 13.1 单元测试

1. `test_parse_emr_vastbase_config_decrypts_password`
2. `test_emr_vastbase_connection_success`
3. `test_fetch_emr_records_uses_dept_filter`
4. `test_fetch_emr_records_uses_parameter_binding`
5. `test_fetch_emr_documents_by_visits_batches_values`
6. `test_discharge_filter_matches_type_title_template`
7. `test_data_source_loader_routes_emr_backend`
8. `test_data_source_loader_default_backend_unchanged`
9. `test_export_uses_vastbase_progress_when_enabled`
10. `test_export_uses_vastbase_discharge_when_enabled`
11. `test_export_fallback_to_oracle_when_vastbase_failed`
12. `test_export_keeps_discharge_columns`

### 13.2 回归测试命令

```bash
python -m compileall app tests scripts
python -m pytest tests/test_emr_vastbase_client.py tests/test_data_source_loader_emr_backend.py tests/test_patient_visit_export_vastbase.py -q
python scripts/check_naming_convention.py
```

### 13.3 人工验收

1. 打开患者质控总览页面。
2. 点击“导出汇总”。
3. Excel 中应出现 `出院记录1_记录时间`、`出院记录1_病历名称`、`出院记录1_内容` 等列。
4. 抽查 5 个患者，确认出院记录内容来自海量库优先。
5. 临时关闭海量库配置，重新导出，确认可回退 Oracle。
6. 新质控测试源接口返回行数正常，且病程文书来自海量库。

## 14. 风险与控制

| 风险 | 控制措施 |
|---|---|
| 海量库视图字段名变更 | 字段名配置化，启动/测试接口做字段诊断 |
| 海量库查询慢 | 必须按患者住院次、日期、科室过滤，设置 statement_timeout |
| 出院记录识别不全 | 同时匹配类型、标题、模板名包含"出院" |
| 文书正文过长 | Excel 单元格截断到 32767 字符 |
| 海量库不可用影响导出 | `fallback_to_oracle=true` 且异常时回退 Oracle |
| 空结果误触发回退掩盖数据空缺 | 只有抛出异常才回退，返回空列表视为正常业务状态，不触发回退 |
| 旧质控被误切换 | `backend` 默认 `default`，旧配置不变 |
| 密码泄露 | 只保存 `password_enc`，日志和文档不写明文密码 |
| 字段名注入 SQL | `patient_id_field`/`visit_id_field`/`dept_field` 等配置项拼入 SQL 前必须通过白名单正则校验 |

## 15. 开发交付顺序

1. 数据库字段只读复核。
2. 新增 `emr_vastbase` 配置和连接测试。
3. 新增 `app/emr_vastbase_client.py`。
4. 汇总导出接入海量库出院记录，保留 Oracle 回退。
5. 汇总导出接入海量库病程记录，保留 Oracle 回退。
6. 扩展 `AuditTypeSource.backend`。
7. 修改 `data_source_loader.py` 支持混合数据源。
8. 配置新质控使用海量库文书源。
9. 补测试并执行回归。
10. 服务器灰度验证导出 Excel 和新质控样本。

## 16. 可直接交给其他 AI 的执行提示词

```text
请按 docs/EMR_VASTBASE_INTEGRATION_EXECUTION_PLAN.md 实现电子病历海量库接入。要求保持现有 Oracle 分析链路不变，新增 emr_vastbase 文书数据源，使用 psycopg2 连接 jhemr.v_blws。该视图已包含 patient_id、visit_id 和科室字段。SQL 中请将 visit_id 别名为 visit_number，与系统其他部分的命名约定保持一致。患者质控总览导出汇总当前已包含 Oracle 出院记录列（来自 V_cyJL）和病程记录列（来自 bcjl202603），需升级为出院记录和病程记录优先查海量库，仅在抛出异常时才回退 Oracle，返回空列表不触发回退。新质控支持 sources[].backend，让 lab/exam/nursing/frontpage 继续走 Oracle，progress/first_progress/discharge 可走 emr_vastbase。动态拼入 SQL 的字段名（patient_id_field/visit_id_field/dept_field 等配置项）必须经白名单正则校验，不得硬编码密码，不得在日志输出文书全文，不得执行无条件全表 SELECT * 或 COUNT(*)。批量 VALUES 查询使用 psycopg2.extras.execute_values 或动态构造占位符。完成后补充单元测试并运行 compileall、聚焦 pytest（含 test_emr_vastbase_client.py）和命名检查。
```
