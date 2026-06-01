# 电子病历海量库接入后续完善计划

## 1. 复核结论

`docs/EMR_VASTBASE_REVIEW_PROMPT.md` 可以作为复核入口，但对照当前代码后，发现部分内容与实现不完全一致，且当前实现仍有几个上线前应修复的问题。

建议先按本文档完成修复，再重新运行回归测试，并更新 `docs/EMR_VASTBASE_REVIEW_PROMPT.md` 中的改造清单与验证结果。

## 2. 可直接交给其他 AI 的提示词

```text
请按 docs/EMR_VASTBASE_FOLLOWUP_FIX_PLAN.md 对电子病历海量库接入代码做后续完善。重点修复：海量库连接测试仍默认检查 dept 而不是实际字段 dept_name；导出 Excel 动态内容未统一截断到 32767 字符；data_source_loader 在 emr_vastbase 返回英文 canonical 字段时，_record_group_values 对中文 field_mapping 缺少 canonical fallback；emr_vastbase 新质控源缺少 document_kind/source 级过滤，first_progress/discharge 可能无法准确筛选；event_time 只用 finish_time_format/record_time_format，未按计划回退 first_save_time/create_date。修复时不得写入明文密码，不得破坏 Oracle 原链路，不得改变 Dify mr_txt 约定。完成后补测试并运行 python -m compileall app tests scripts -q、python scripts/check_naming_convention.py、python -m pytest tests/test_emr_vastbase_client.py tests/test_data_source_loader_emr_backend.py tests/test_patient_visit_export_vastbase.py -q。
```

## 3. 发现的问题清单

| # | 风险 | 文件/位置 | 问题 | 建议 |
|---|---|---|---|---|
| 1 | 高 | `app/emr_vastbase_client.py:83-88` | 连接测试 required_fields 仍使用 `dept` 默认值，实际字段已确认为 `dept_name` | 改为 `_get_field(config, "dept_field", "dept_name")`，并补测试 |
| 2 | 高 | `app/services/patient_visit_export_service.py:905-908` | Excel 动态列写入时只 `_safe_text`，未统一截断到 32767 字符；长 `progress_message` 可能导致 openpyxl 保存失败 | 新增统一 helper，所有单元格字符串写入前截断到 32767 |
| 3 | 高 | `app/services/data_source_loader.py:285` | `fetch_emr_records()` 返回英文 canonical 字段，但 `_record_group_values()` 对中文 `field_mapping` 只查映射字段，不回退 canonical key，可能导致 bundle_id 为空 | `_record_group_values()` 改为先查映射字段，再查 canonical key |
| 4 | 高 | `app/services/data_source_loader.py:78-83` 与 `app/emr_vastbase_client.py:239-319` | `backend=emr_vastbase` 忽略 source 级文书类型需求，无法区分 `progress`、`first_progress`、`discharge` 等源 | 支持 `source_cfg.document_kind` 或按 `source_name` 推断过滤条件 |
| 5 | 中 | `app/emr_vastbase_client.py:158`、`:266` | `event_time` 只用 `finish_time_format`/`record_time_format`，计划中要求继续回退 `first_save_time`、`create_date` | 新增可配置字段并纳入 COALESCE |
| 6 | 中 | `app/emr_vastbase_client.py:176-193`、`:279-294` | 查询结果未返回 `document_id`、`creator_id`、`state`、`admission_no` 等实际可用字段 | 增加可选字段映射，至少返回 `progress_guid AS document_id`、`doctor_guid AS creator_id`、`state`、`inp_no AS admission_no` |
| 7 | 中 | `app/emr_vastbase_client.py:152-156` | `VALUES` CTE 一次性拼接全部 `patient_keys`，大批量时 SQL 过长或参数过多 | 增加分批查询，默认 batch size 可配置，例如 500 或 1000 |
| 8 | 中 | `app/schemas.py:269` 与 `app/routers/config.py:381-384` | API 请求字段使用 `db_schema`，但底层配置字段叫 `schema`；如果调用方传 `schema` 可能被 Pydantic 忽略 | 增加别名兼容或在接口文档明确只传 `db_schema` |
| 9 | 低 | `docs/EMR_VASTBASE_REVIEW_PROMPT.md:28-35` | 标题写“新增文件（2 个）”，表格实际列出 4 个 | 改为“新增文件（4 个）” |
| 10 | 低 | `docs/EMR_VASTBASE_REVIEW_PROMPT.md:15-16`、`:121-124` | 文档提示检查 Excel 截断，但当前代码未实现完整截断；回归结果未体现该风险 | 在修复 #2 后更新文档，或在文档中标为待修复 |

## 4. 修复步骤

### Step 1 修复连接测试字段默认值

目标文件：`app/emr_vastbase_client.py`

修改点：

```python
_get_field(config, "dept_field", "dept")
```

改为：

```python
_get_field(config, "dept_field", "dept_name")
```

新增测试：

| 测试文件 | 测试点 |
|---|---|
| `tests/test_emr_vastbase_client.py` | mock `information_schema.columns` 返回 `dept_name`，确认 `missing_columns` 不包含 `dept` |

### Step 2 统一 Excel 单元格截断

目标文件：`app/services/patient_visit_export_service.py`

建议新增 helper：

```python
_EXCEL_CELL_MAX_LEN = 32767

def _excel_cell_value(value: Any, *, is_datetime_field: bool = False) -> str:
    text = _format_dt(value) if is_datetime_field else _safe_text(value)
    return text[:_EXCEL_CELL_MAX_LEN]
```

替换位置：

| 位置 | 当前逻辑 | 修改 |
|---|---|---|
| `_build_excel()` 动态列 | `_safe_text(val)` | `_excel_cell_value(val, is_datetime_field=...)` |
| `_build_excel_with_pushlog()` 基础列 | `p.get(name, "")` | `_excel_cell_value(...)` |
| `_build_excel_with_pushlog()` 动态列 | `_safe_text(val)` | `_excel_cell_value(...)` |
| `_build_excel_with_pushlog()` PushLog 列 | 直接写 `val` | `_excel_cell_value(val)` |

新增测试：

| 测试文件 | 测试点 |
|---|---|
| `tests/test_patient_visit_export_vastbase.py` | 构造 40000 字符 `content`，调用 `_build_excel_with_pushlog()` 不报错，并读取单元格长度 `<=32767` |

### Step 3 修复 canonical fallback

目标文件：`app/services/data_source_loader.py`

当前风险：

```python
mapped_key = str((field_mapping or {}).get(key) or key)
values[key] = str(record.get(mapped_key, "") or "").strip()
```

建议改为：

```python
mapped_key = str((field_mapping or {}).get(key) or key)
value = record.get(mapped_key)
if value in (None, "") and mapped_key != key:
    value = record.get(key)
values[key] = str(value or "").strip()
```

新增测试：

| 测试文件 | 测试点 |
|---|---|
| `tests/test_data_source_loader_emr_backend.py` | field_mapping 配中文键，但 record 已含 canonical `patient_id/visit_number/audit_date`，确认 bundle_id 不为空 |

### Step 4 增加 source 级文书类型过滤

目标文件：`app/services/data_source_loader.py`、`app/emr_vastbase_client.py`、`app/schemas.py`

建议设计：

| 配置项 | 用途 |
|---|---|
| `document_kind` | 可选，枚举 `all/progress/first_progress/discharge` |
| `title_keywords` | 可选，自定义标题/类型/模板关键词列表 |

路由建议：

| source_name | 默认 document_kind |
|---|---|
| `progress` | `progress` |
| `first_progress` | `first_progress` |
| `discharge` | `discharge` |
| 其他 | `all` |

客户端过滤建议：

| kind | 过滤规则 |
|---|---|
| `discharge` | `progress_type_name/title/template LIKE '%出院%'` |
| `progress` | 排除 `LIKE '%出院%'` |
| `first_progress` | `progress_type_name/title/template LIKE '%首次%' OR LIKE '%首次病程%'` |
| `all` | 不增加类型过滤 |

注意：所有关键词必须作为 SQL 参数绑定，不拼接用户输入。

### Step 5 补齐时间字段回退

目标文件：`config/config.json.template`、`app/schemas.py`、`app/services/config_parser.py`、`app/emr_vastbase_client.py`

新增配置默认值：

```json
"first_save_time_field": "first_save_time",
"create_date_field": "create_date"
```

事件时间表达式建议：

```sql
COALESCE(
  NULLIF(finish_time_format,''),
  NULLIF(record_time_format,''),
  first_save_time,
  create_date
)
```

注意：如果 `first_save_time/create_date` 是 timestamp 类型，避免直接 `NULLIF(timestamp, '')`。只对字符串字段使用 `NULLIF`。

### Step 6 补齐返回字段

目标文件：`app/emr_vastbase_client.py`

建议增加字段：

| 系统字段 | 实际字段 |
|---|---|
| `admission_no` | `inp_no` |
| `document_id` | `progress_guid` |
| `creator_id` | `doctor_guid` |
| `state` | `state` |
| `message_type` | `msg_type` |

这些字段不一定写入 Excel，但建议返回到 canonical record，方便新质控 builder 或诊断接口使用。

### Step 7 批量查询分批

目标文件：`app/emr_vastbase_client.py`

建议新增：

```python
batch_size = int(config.get("batch_size", 500) or 500)
```

实现方式：

| 步骤 | 说明 |
|---|---|
| 1 | 将 `patient_keys` 按 batch_size 切片 |
| 2 | 每批构造 VALUES CTE |
| 3 | 每批结果合并到总 result |
| 4 | 仍受 `max_records` 全局上限约束 |

### Step 8 更新复核提示词文档

目标文件：`docs/EMR_VASTBASE_REVIEW_PROMPT.md`

修改点：

| 位置 | 修改 |
|---|---|
| 标题“新增文件（2 个）” | 改为“新增文件（4 个）” |
| 回归验证结果 | 补充新增测试用例数量 |
| 已知限制 | 移除已修复项，保留需要人工验收项 |
| 复核重点建议 | 移除已完成修复的问题，新增真实残余风险 |

## 5. 验证命令

```bash
python -m compileall app tests scripts -q
python scripts/check_naming_convention.py
python -m pytest tests/test_emr_vastbase_client.py tests/test_data_source_loader_emr_backend.py tests/test_patient_visit_export_vastbase.py -q
```

## 6. 验收标准

| # | 标准 |
|---|---|
| 1 | 连接测试对实际字段 `dept_name` 不再误报缺失 |
| 2 | 导出 Excel 任意动态内容超过 32767 字符时自动截断，不报错 |
| 3 | `backend=emr_vastbase` 在中文 `field_mapping` 下仍能生成正确 bundle_id |
| 4 | `progress/first_progress/discharge` 三类文书能按规则区分 |
| 5 | `event_time` 能按 `finish_time_format -> record_time_format -> first_save_time -> create_date` 回退 |
| 6 | 单次导出大批量 patient_keys 不因 SQL 过长失败 |
| 7 | 所有新增测试通过，命名检查不出现 `mr_txt` 违规 |
