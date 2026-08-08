# 电子病历海量库接入 —— 代码复核提示词与改造清单

## 复核提示词

```
请对以下电子病历海量库接入改造进行代码复核。本次改造的目标是：
在不破坏现有 Oracle 分析链路的前提下，新增 jhemr.v_blws 海量库文书数据源，
让患者质控总览"导出汇总"的病程记录和出院记录优先查海量库，异常时回退 Oracle。
新质控支持 per-source backend 路由（oracle/postgresql/emr_vastbase/default）。

请重点检查：
1. 海量库查询异常时是否正确回退 Oracle，空结果是否不误触发回退
2. 字段名配置（patient_id_field/visit_id_field/dept_field 等）拼入 SQL 前是否有白名单校验
3. config.json 中 schema 字段与 Pydantic schema 中 db_schema 的映射是否正确
4. psycopg2 连接是否设置了 readonly + autocommit + statement_timeout
5. Excel 单元格内容是否截断到 32767 字符以内
6. 旧配置（无 backend 字段）是否完全向后兼容
7. 数据库密码是否只保存 password_enc，日志/文档不输出明文密码
8. 测试是否覆盖了：字段名校验、backend 路由、Oracle 回退、海量库优先

请按"改造清单"逐项核对代码，指出任何遗漏、逻辑错误或安全隐患。
```

---

## 改造清单

### 一、新增文件（4 个）

| # | 文件 | 职责 | 行数 |
|---|---|---|---|
| 1 | `app/emr_vastbase_client.py` | 海量库连接、查询（含分批）、连接测试、字段名白名单校验、document_kind 过滤、时间字段四阶回退 | ~350 |
| 2 | `tests/test_emr_vastbase_client.py` | 字段名校验、空 keys、出院过滤 SQL | ~61 |
| 3 | `tests/test_data_source_loader_emr_backend.py` | per-source backend 路由测试（emr_vastbase/default/oracle）、canonical fallback | ~120 |
| 4 | `tests/test_patient_visit_export_vastbase.py` | Oracle 回退、海量库优先、discharge 列保留、Excel 截断 | ~210 |

### 二、修改文件（7 个）

#### 2.1 `config/config.json.template`

| 改动 | 说明 |
|---|---|
| 新增 `emr_vastbase` 配置节 | 位于 `postgresql` 和 `dify` 之间；默认 `enabled: false`；`dept_field` 默认 `dept_name`；含 `use_for_export_progress`/`use_for_export_discharge`/`fallback_to_oracle` 三个开关 |

#### 2.2 `app/services/config_parser.py`

| 改动 | 说明 |
|---|---|
| 新增 `parse_emr_vastbase_config(config)` 静态方法 | 读取 `config["emr_vastbase"]`；解密 `password_enc` → `password`；补齐默认值（schema=jhemr, view=v_blws, dept_field=dept_name 等） |

#### 2.3 `app/schemas.py`

| 改动 | 说明 |
|---|---|
| 新增 `EmrVastbaseConfig` 类 | POST 请求体；字段 `db_schema`（避免 Pydantic `schema` 保留名冲突）；默认值与 config.json.template 一致 |
| 新增 `EmrVastbaseConfigResponse` 类 | GET 响应体；密码字段为 `password_masked`（脱敏）；字段 `db_schema` |
| `AuditTypeSource` 新增 `backend` 字段 | 类型 `Literal["default", "oracle", "postgresql", "emr_vastbase"]`；默认 `"default"`；旧配置无此字段时向后兼容 |

#### 2.4 `app/routers/config.py`

| 改动 | 说明 |
|---|---|
| 新增 `GET /api/config/emr-vastbase` | 返回 `EmrVastbaseConfigResponse`；密码脱敏；`cfg["schema"]` → `db_schema` 映射 |
| 新增 `POST /api/config/emr-vastbase` | 接收 `EmrVastbaseConfig`；`body.db_schema` → `schema` 写入 config；密码加密保存 |
| 新增 `POST /api/config/emr-vastbase/test` | 调用 `emr_vastbase_client.test_emr_vastbase_connection` |
| 新增 `EmrVastbaseConfig`/`EmrVastbaseConfigResponse` 导入 | 从 `app.schemas` 导入 |

#### 2.5 `app/emr_vastbase_client.py`（核心）

| 函数 | 职责 | 安全要点 |
|---|---|---|
| `_validate_field_name(name)` | 白名单正则 `^[a-zA-Z_][a-zA-Z0-9_]{0,63}$` | 拒绝空值、数字开头、特殊字符、超长 |
| `_build_event_time_expr(...)` | 构建四阶时间回退 COALESCE | `finish_time_format -> record_time_format -> first_save_time -> create_date` |
| `_build_kind_filter(...)` | 按 document_kind 构建 SQL 过滤 | 支持 all/progress/first_progress/discharge |
| `_coerce_record(rec)` | 记录值安全化 | None→空串、datetime→格式化、其他→strip |
| `_resolve_document_kind(source_name, explicit)` | 按 source_name 推断 document_kind | progress→progress, first_progress→first_progress, discharge→discharge |
| `get_emr_vastbase_connection(config)` | psycopg2 连接；`connect_timeout`；`SET statement_timeout`；`readonly=True, autocommit=True` | 不记录密码 |
| `test_emr_vastbase_connection(config)` | 连接测试 + 字段诊断 + view 可访问性 | 返回 columns/missing_columns/sample_rows |
| `fetch_emr_documents_by_visits(config, patient_keys, document_kind)` | 按患者住院次批量查询；**分批查询**（默认 batch_size=500）；返回 inp_no/document_id/creator_id/state/message_type | VALUES CTE 分批构造；`_validate_field_name` 校验所有配置字段名；`max_records` 截断+warning |
| `fetch_emr_records(config, dept_list, query_date, document_kind, source_name)` | 按日期+科室查询，支持 source 级文书过滤 | `{dept_filter}` 动态注入 IN 子句；参数绑定 `%s`；返回 inp_no/document_id/creator_id/state/message_type |

#### 2.6 `app/services/patient_visit_export_service.py`

| 改动 | 说明 |
|---|---|
| 新增 `_query_discharge_records_from_emr(emr_cfg, patient_keys)` | 调用 `fetch_emr_documents_by_visits(..., document_kind="discharge")`；映射返回字段为 `event_time/record_name/content/dept/creator` |
| 新增 `_query_progress_notes_from_emr(emr_cfg, patient_keys)` | 调用 `fetch_emr_documents_by_visits(..., document_kind="progress")`；按时间+创建人+内容前100字合并 |
| 修改 `export_patient_visit_summary()` | 加载 `emr_vastbase` 配置；病程：先 `_from_emr`，异常时回退 Oracle `_query_progress_notes`；出院：先 `_from_emr`，异常时回退 Oracle `_query_discharge_records`；**空结果不回退** |

**回退逻辑关键代码路径**：
```
emr_enabled AND use_for_export_progress?
  ├── YES → try _query_progress_notes_from_emr()
  │         ├── 成功（含空结果）→ 使用海量库数据
  │         └── 异常 AND fallback_to_oracle → warning + _query_progress_notes(Oracle)
  └── NO  → _query_progress_notes(Oracle)
```

#### 2.7 `app/services/data_source_loader.py`

| 改动 | 说明 |
|---|---|
| 新增 `from app.emr_vastbase_client import fetch_emr_records` | 顶部导入 |
| 修改 `_fetch_source_records()` | 读取 `source_cfg.get("backend", "default")`；`emr_vastbase` → `parse_emr_vastbase_config` + `fetch_emr_records`；`oracle`/`postgresql` 强制指定；`default` 走原逻辑 |

### 三、未改动文件（确认无副作用）

| 文件 | 确认点 |
|---|---|
| `app/oracle_client.py` | 未修改 |
| `app/postgresql_client.py` | 未修改 |
| `app/dify_pusher.py` | 未修改 |
| `app/scheduler.py` | 未修改 |
| `app/routers/push.py` | 未修改 |
| `app/routers/patient_qc.py` | 未修改 |
| `app/routers/logs.py` | 未修改 |
| `app/models.py` | 未修改 |
| `app/main.py` | 未修改（路由注册不变） |
| `app/config.py` | 未修改 |

### 四、回归验证结果

| 检查项 | 结果 |
|---|---|
| `python -m compileall app tests scripts -q` | 通过 |
| `python scripts/check_naming_convention.py` | 通过（未引入 mr_txt 变量） |
| `pytest tests/test_emr_vastbase_client.py tests/test_data_source_loader_emr_backend.py tests/test_patient_visit_export_vastbase.py -q` | **21 passed** |
| Pydantic `schema` 字段名警告 | 已修复（改用 `db_schema`） |
| 海量库连接测试 dept 默认值 | 已修复（改用 `dept_name`） |
| Excel 单元格截断 | 已修复（`_excel_cell_value` 统一截断到 32767） |
| canonical fallback | 已修复（`_record_group_values` 先查映射字段，再回退 canonical key） |
| source 级文书过滤 | 已修复（`document_kind` 支持 all/progress/first_progress/discharge） |
| 时间字段四阶回退 | 已修复（`finish_time_format -> record_time_format -> first_save_time -> create_date`） |
| 返回字段扩展 | 已修复（新增 inp_no/document_id/creator_id/state/message_type） |
| 分批查询 | 已修复（`batch_size` 默认 500，可配置） |

### 五、复核重点建议

| # | 复核点 | 风险等级 |
|---|---|---|
| 1 | `emr_vastbase_client.py` 中分批查询是否正确合并结果且不超 max_records | 高 |
| 2 | `first_save_time/create_date` 的 COALESCE 是否对 timestamp 类型字段安全（未使用 NULLIF） | 中 |
| 3 | `document_kind=first_progress` 的关键词过滤是否覆盖所有首次病程命名变体 | 中 |
| 4 | `data_source_loader.py` 中 canonical fallback 是否在所有 source 类型下都正确工作 | 中 |
| 5 | `export_patient_visit_summary` 中 Oracle 回退路径是否与海量库路径返回相同结构的 dict | 低 |
| 6 | `batch_size` 配置是否在 config.json.template 中有默认值 | 低 |

### 六、已知限制（不在本次范围）

1. §12 数据库字段只读复核 SQL 需手动执行确认实际字段名
2. §13.3 人工验收（导出 Excel 抽查）需在服务器完成
3. 前端配置页面（`config.html`/`config.js`）未新增海量库配置 tab（§8.2 标记为可选）
