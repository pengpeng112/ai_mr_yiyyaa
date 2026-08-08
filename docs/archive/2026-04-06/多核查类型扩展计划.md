# 多核查类型扩展计划（细化版）

> 本文替代旧版"单 Dify workflow + 扩展 payload"方案，改为**每类核查独立 Dify workflow + 独立响应 schema + 前端按 JSONPath 规则渲染**，完整支持用户提出的"检验检查核查""病案首页核查""医嘱核查"等类别，并保证未来新增类型无需改后端代码。

---

## Context

### 业务背景
系统当前只有一种核查：**病程记录 vs 护理记录**，走单一 Dify workflow。业务方希望新增至少三类核查，每类业务目标不同、Dify 返回结构不同：

| 核查类型 code | 名称 | 数据源 A | 数据源 B | 核查重点 | Dify 返回示例字段 |
|---|---|---|---|---|---|
| `progress_vs_nursing`（现有） | 病程 vs 护理 | 病程记录 | 护理记录 | 记录完整性、一致性、时效 | `dimensions[]` + 总体结论 |
| `order_vs_nursing` | 医嘱 vs 护理 | 医嘱 | 护理执行记录 | 医嘱是否被执行、执行时间差、异常打标 | `order_items[]`(订单+执行+匹配结果) |
| `labexam_vs_progress` | 检验检查 vs 病程 | 检验/检查报告 | 病程记录 | 异常结果是否被记录+结果一致+是否有处置措施 | `abnormal_items[]`(项目+结果+记录命中+处置命中) |
| `frontpage_vs_postop` | 病案首页 vs 术后首次病程 | 病案首页手术诊断 | 术后首次病程 | 手术时间一致、手术部位一致、术式一致 | `surgery_match`(bool 组合) |

### 架构目标
1. **每类核查独立 Dify workflow**：独立 `base_url / api_key / workflow_input_variable / workflow_output_key / extra_inputs / timeout`
2. **独立数据源 SQL**：每类可配置 N 个命名数据源（primary/reference/...），按患者分组后统一输入 payload
3. **独立响应 schema**：raw JSON 完整落库，通用维度（若有）走现有 `audit_dimension_result`；per-type 特色字段通过前端 JSONPath 规则渲染
4. **前端可视化配置**：管理员在"审计类型管理"页可增删改审计类型，配置 SQL、Dify、字段展示规则；无需改代码即可上新类型
5. **不破坏现有流程**：`progress_vs_nursing` 以种子数据形式成为第一个 audit_type，旧的 push_log/维度/结论记录继续兼容

---

## 总体分层

```
┌────────────────────────────────────────────────┐
│  前端 UI                                       │
│  ├── 审计类型管理（CRUD audit_types）          │
│  ├── 手动推送（单选/多选类型）                  │
│  ├── 日志详情（按 audit_type_code 渲染）       │
│  └── 动态渲染引擎（JSONPath + 预设组件）        │
└────────────────────────────────────────────────┘
                   ↕ /api/audit-types, /api/push, /api/logs
┌────────────────────────────────────────────────┐
│  FastAPI 路由层                                │
│  ├── /api/audit-types (CRUD + test)            │
│  ├── /api/push/manual (new: audit_type_codes)  │
│  └── /api/logs (new: audit_type_code filter)   │
└────────────────────────────────────────────────┘
                   ↕
┌────────────────────────────────────────────────┐
│  服务层                                        │
│  ├── AuditTypeRegistry（读配置+校验）          │
│  ├── DataSourceLoader（多命名 SQL 抽取合并）   │
│  ├── PayloadComposer（per-type payload 构建）  │
│  ├── DifyClient（per-type Dify 调用）          │
│  ├── ResponseAdapter（通用维度抽取 + raw 落库）│
│  └── PushExecutor / BulkPushExecutor（引入    │
│       audit_type 维度）                        │
└────────────────────────────────────────────────┘
                   ↕
┌────────────────────────────────────────────────┐
│  数据层                                        │
│  ├── config.json.audit_types[]                 │
│  ├── push_log + audit_type_code 列            │
│  ├── audit_dimension_result（通用维度）         │
│  └── audit_conclusion（通用结论）              │
└────────────────────────────────────────────────┘
```

---

## 第一阶段：配置层 `audit_types` 结构定义

### 1.1 新增配置结构

**文件：`app/config.py`**

在 `_DEFAULT_CONFIG` 中新增 `audit_types` 数组，每个元素结构：

```json
{
  "code": "labexam_vs_progress",
  "name": "检验检查 vs 病程记录核查",
  "description": "核查异常检验/检查结果是否在病程记录中被记录且有处置",
  "enabled": true,
  "sort_order": 20,
  "default_for_schedule": true,

  "sources": {
    "primary": {
      "type": "sql",
      "query_sql": "SELECT ... FROM lab_exam_report WHERE ...",
      "field_mapping": { "patient_id": "PAT_ID" },
      "required": true
    },
    "reference": {
      "type": "sql",
      "query_sql": "SELECT ... FROM mr_progress WHERE ...",
      "field_mapping": {},
      "required": true
    }
  },

  "group_key": ["patient_id", "visit_number"],

  "payload": {
    "builder": "generic_multi_source",
    "text_template": "\n[检验检查报告]\n{primary}\n\n[病程记录]\n{reference}\n",
    "extra_fields": { "audit_focus": "abnormal_followup" }
  },

  "dify": {
    "base_url": "https://dify.example.com/v1",
    "api_key_enc": "gAAAAA...",
    "workflow_input_variable": "mr_txt",
    "workflow_output_key": "result",
    "user_identifier": "med-audit-labexam",
    "timeout_seconds": 90,
    "extra_inputs": {},
    "targets": []
  },

  "response": {
    "parse_strategy": "hybrid",
    "dimension_path": "$.dimensions",
    "conclusion_path": "$.overall_conclusion",
    "severity_path": "$.severity",
    "risk_score_path": "$.risk_score",
    "inconsistency_path": "$.inconsistency"
  },

  "display": {
    "summary_blocks": [
      { "label": "核查结论", "path": "$.overall_conclusion", "type": "text_block" },
      { "label": "风险分值", "path": "$.risk_score", "type": "severity_badge" }
    ],
    "detail_blocks": [
      {
        "label": "异常结果处置清单",
        "path": "$.abnormal_items",
        "type": "table",
        "columns": [
          { "label": "项目", "path": "item_name" },
          { "label": "结果", "path": "result" },
          { "label": "参考值", "path": "reference_range" },
          { "label": "病程命中", "path": "recorded_in_progress", "renderer": "bool_tag" },
          { "label": "处置命中", "path": "has_followup", "renderer": "bool_tag" },
          { "label": "说明", "path": "explanation" }
        ]
      },
      { "label": "原始 Dify 返回", "path": "$", "type": "raw_json", "collapsed": true }
    ]
  }
}
```

**要点**：
- `code` 全局唯一，前端与后端以此为标识
- `sources.{name}` 支持任意命名；`required=true` 的数据源缺失时跳过该患者
- `payload.builder="generic_multi_source"` 先落一个通用实现；未来可扩展其他 builder 名称映射到 Python 函数
- `response.parse_strategy`：`dimensions_only`（仅走通用维度）/ `raw_only`（不解析维度）/ `hybrid`（都做）
- `display.summary_blocks` 显示在日志列表/详情顶部；`detail_blocks` 显示在详情展开区
- 敏感字段：`dify.api_key_enc` 继续走 Fernet 加密，`/api/config` 读取时脱敏

### 1.2 默认种子：迁移现有"病程 vs 护理"

首次启动时若 `audit_types` 为空，从现有 `oracle`/`postgresql`/`dify` 配置派生一条 `code="progress_vs_nursing"` 种子，保证旧配置零停机。`_ensure_default_audit_type()` 函数放在 `app/config.py`，启动时由 `load_config()` 调用。

### 1.3 配置读写 API

**文件：`app/routers/audit_types.py`（新建）**

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/audit-types` | 列出全部（脱敏 api_key） |
| GET | `/api/audit-types/{code}` | 详情 |
| POST | `/api/audit-types` | 新增 |
| PUT | `/api/audit-types/{code}` | 更新（支持局部 PATCH 风格） |
| DELETE | `/api/audit-types/{code}` | 删除（内置 `progress_vs_nursing` 不可删，仅可禁用） |
| POST | `/api/audit-types/{code}/test-source` | 用 `query_date` 测试 SQL 能否执行 |
| POST | `/api/audit-types/{code}/test-dify` | 用 `mr_txt_sample` 测试 Dify endpoint |
| POST | `/api/audit-types/{code}/clone` | 克隆已有类型作为新类型模板 |

所有写操作校验：
- `code` 合法性（`^[a-z][a-z0-9_]{2,63}$`）、唯一性
- `sources` 中每个 SQL 过 `DBClientBase._validate_sql`（复用现有注入防护）
- `display` 中 JSONPath 语法校验（使用 `jsonpath-ng` 第三方库）

### 1.4 Schema 定义

**文件：`app/schemas.py`**

新增：
```python
class AuditTypeSource(BaseModel):
    type: Literal["sql"] = "sql"
    query_sql: str
    field_mapping: Dict[str, str] = {}
    required: bool = True

class AuditTypeDify(BaseModel):
    base_url: str
    api_key_enc: Optional[str] = None
    api_key: Optional[str] = None  # 写入时明文，响应时脱敏
    workflow_input_variable: str = "mr_txt"
    workflow_output_key: str = "result"
    user_identifier: str = "med-audit-system"
    timeout_seconds: int = 90
    extra_inputs: Dict[str, Any] = {}
    targets: List[Dict[str, Any]] = []

class AuditTypeDisplayBlock(BaseModel):
    label: str
    path: str
    type: Literal["text_block", "kv_list", "table", "bool_tag", "severity_badge",
                  "dimension_grid", "raw_json", "tag_list"]
    columns: Optional[List[Dict[str, str]]] = None
    collapsed: bool = False

class AuditTypeDisplay(BaseModel):
    summary_blocks: List[AuditTypeDisplayBlock] = []
    detail_blocks: List[AuditTypeDisplayBlock] = []

class AuditTypeConfig(BaseModel):
    code: str
    name: str
    description: str = ""
    enabled: bool = True
    sort_order: int = 100
    default_for_schedule: bool = False
    sources: Dict[str, AuditTypeSource]
    group_key: List[str] = ["patient_id", "visit_number"]
    payload: Dict[str, Any] = {}
    dify: AuditTypeDify
    response: Dict[str, Any] = {}
    display: AuditTypeDisplay = AuditTypeDisplay()
```

`ManualPushRequest` 新增：
```python
audit_type_codes: Optional[List[str]] = None  # None/空 = 使用调度器默认集合
parallel_audit_types: bool = False            # False=串行, True=并行（线程池）
```

`PushLogItem` / `PushLogDetail` 新增：
```python
audit_type_code: Optional[str] = None
audit_type_name: Optional[str] = None
audit_type_display: Optional[AuditTypeDisplay] = None  # 详情响应时嵌入，前端无需二次请求
```

---

## 第二阶段：数据模型变更

**文件：`app/models.py`**

### 2.1 `PushLog` 新增列

```python
audit_type_code = Column(String(64), default="", index=True)  # 空串兼容老数据
```

**文件：`app/database.py`**

在 `_migrate_push_log_columns()` 中追加：
```python
if "audit_type_code" not in existing_columns:
    conn.execute(text("ALTER TABLE push_log ADD COLUMN audit_type_code VARCHAR(64) DEFAULT ''"))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_push_log_audit_type ON push_log(audit_type_code)"))
```

迁移策略：旧数据 `audit_type_code=""`，路由查询时兼容空串等价于 `progress_vs_nursing`（或留空作为"未分类"）。

### 2.2 `AuditDimensionResult` / `AuditConclusion` 无需变更

通用维度和结论表保留原样；per-type 特色字段全部从 `push_log.response_json` 动态提取。

---

## 第三阶段：核心服务层

### 3.1 `AuditTypeRegistry`（新建）

**文件：`app/services/audit_type_registry.py`**

```python
class AuditTypeRegistry:
    """读取/校验/查询 audit_types 配置的单例封装。"""
    def __init__(self, config: dict): ...
    def list_enabled(self) -> List[AuditTypeConfig]: ...
    def list_default_schedule(self) -> List[AuditTypeConfig]: ...
    def get(self, code: str) -> AuditTypeConfig: ...
    def validate_for_save(self, cfg: AuditTypeConfig) -> None: ...
    def refresh(self) -> None:  # 配置热更新后调用
        ...
```

调用方：路由、执行器、调度器。

### 3.2 `DataSourceLoader`（新建）

**文件：`app/services/data_source_loader.py`**

职责：根据 `AuditTypeConfig.sources` 中的多命名 SQL 并行抽取数据，按 `group_key` 分组合并：

```python
def load_patient_bundles(
    audit_type: AuditTypeConfig,
    query_date: str,
    date_dimension: str,
    dept_filter: str | None,
) -> List[PatientBundle]:
    """
    返回 [{group_key:..., sources:{primary:[...], reference:[...]}}, ...]
    复用 oracle_client / postgresql_client 的连接池、SQL 校验、占位符机制。
    """
```

要点：
- 复用 `app/db_client_base.py` 的 `validate_sql`、`build_dept_filter_params`、占位符
- 为每个 source 执行一次 `fetch_records`，得到 list
- 按 `group_key` 做字典合并（缺源时根据 `required` 决定是否跳过）
- `date_dimension` 透传给每个 source 的 SQL（SQL 必须使用 `:query_date` 占位符，具体字段由用户写入 WHERE 子句）

### 3.3 `PayloadComposer`（新建）

**文件：`app/services/payload_composer.py`**

```python
def compose(
    audit_type: AuditTypeConfig,
    bundle: PatientBundle,
    query_date: str,
) -> Tuple[Dict[str, Any], str]:
    """
    根据 audit_type.payload.builder 分派:
      - "generic_multi_source": 通用构造, 所有 sources 以文本块拼接,
        填入 text_template, 返回 (payload_dict, mr_text)
      - "legacy_progress_nursing": 保底走现有 build_dify_payload/build_dify_mr_text
    """
```

`generic_multi_source` 实现：
1. 取 `sources.primary` 的第一条记录提取 patient_info（沿用现有 `_pick` + 字段别名）
2. 为每个 source 调用 `_flatten_records_to_text(source_name, records, field_mapping)` 生成文本块
3. 用 `text_template` 拼接，或默认模板 `\n[primary]\n{primary}\n\n[reference]\n{reference}\n...`
4. 把拼接后的 `mr_text` 作为 Dify `workflow_input_variable` 的值

**保留既有 `build_dify_payload` / `build_dify_mr_text`**：`legacy_progress_nursing` builder 直接调用，保证 `progress_vs_nursing` 行为零变化。

### 3.4 `DifyClient` 重构

**文件：`app/dify_pusher.py`**

- 现有 `push_to_dify(...)` 增加参数 `dify_config_override: Optional[dict]`：若传入则用 override 的 `base_url/api_key/input_var/output_key/timeout/extra_inputs`，否则沿用全局 `dify` 配置（向后兼容）
- 现有 `parse_dify_structured_output(outputs, output_key)` 不改核心逻辑（仍然识别通用 `dimensions`/`overall_conclusion` 结构）。当 audit_type 的 `response.parse_strategy="raw_only"` 时，跳过维度解析，仅记录 raw JSON
- 新增 `apply_response_paths(raw: dict, paths: dict) -> dict`：根据 `response.{dimension,conclusion,severity,...}_path` 用 JSONPath 抽取字段，合并入 `result`

### 3.5 `PushExecutor` / `BulkPushExecutor` 改造

**文件：`app/services/push_executor.py`、`app/services/bulk_push_executor.py`**

签名变更：
```python
class PushConfig:
    audit_type_code: str          # 新增: 必填
    audit_type: AuditTypeConfig   # 新增: 从 registry 解析
    ...（其余字段保留）
```

`_push_single_record` 改造步骤：
1. 从 `audit_type` 得到 per-type Dify override
2. 调用 `PayloadComposer.compose(audit_type, bundle, query_date)` 生成 payload + mr_text
3. 调用 `DifyClient.push_to_dify(..., dify_config_override=audit_type.dify)` 拿到 raw + parsed
4. 调用 `apply_response_paths(raw, audit_type.response)` 融合
5. 写 `push_log`，`audit_type_code` 填入；`response_json` 保留完整 raw JSON
6. 若 `parse_strategy in ("hybrid","dimensions_only")`，走现有 `_save_audit_results` 写维度/结论

### 3.6 多类型调度（手动推送）

`BulkPushExecutor.execute_manual(request: ManualPushRequest)`：
1. `codes = request.audit_type_codes or registry.list_default_schedule()`
2. 若 `parallel_audit_types=False`：对每个 code 串行调用 `_run_for_audit_type(code)`
3. 若 `parallel_audit_types=True`：用 `concurrent.futures.ThreadPoolExecutor`（最大 3 个类型并发）并行调用
4. 每个 audit_type 仍然复用内部的患者级并发池（维持现有线程池行为）
5. 单一 `TaskProgressManager` 汇总进度：`total = sum(patient_count × audit_type_count)`

### 3.7 调度器适配

**文件：`app/scheduler.py`**

`run_scheduled_push()` 改为：
```python
for audit_type in registry.list_default_schedule():
    executor = PushExecutor(audit_type=audit_type, ...)
    executor.execute()
```
串行遍历所有 `default_for_schedule=True` 的类型，每个类型独立记录 `SchedulerHistory`（新增一列 `audit_type_code`）。

---

## 第四阶段：前端动态渲染引擎

### 4.1 渲染引擎设计

**文件：`static/scripts/modules/render_engine.js`（新建）**

核心函数：
```javascript
// 从对象中按 JSONPath 抽取值（轻量版，支持 $、. 、[index]、[?filter] 基础语法）
function extractByPath(obj, path)

// 根据 block 定义渲染 DOM/Vue 虚拟节点
function renderBlock(block, rawJson)

// 渲染类型映射表
const RENDERERS = {
  text_block:      (val) => <p class="render-text-block">{val}</p>,
  kv_list:         (val) => ...,   // val 为对象, 渲染 key-value 两列表格
  table:           (val, block) => // val 为数组, block.columns 控制列
                       ...,
  bool_tag:        (val) => val ? '<span class="tag-ok">✓</span>' : '<span class="tag-fail">✗</span>',
  severity_badge:  (val) => ...,   // low/medium/high 对应不同颜色
  dimension_grid:  (val) => ...,   // val 为 dimensions[]; 复用现有 ai-dimension-card
  tag_list:        (val) => ...,   // val 为字符串数组
  raw_json:        (val, block) => <ElCollapse ...>{prettyJson(val)}</ElCollapse>,
}
```

### 4.2 日志详情页改造

**文件：`static/scripts/modules/logs.js`、`static/index.html`**

- `viewLogDetail(row)` 响应新增 `audit_type_code / audit_type_name / audit_type_display`
- 详情面板逻辑：
  - 顶部固定区 → 遍历 `display.summary_blocks` 渲染
  - 中部维度卡片 → 若 `parse_strategy` 含 dimensions 则渲染（复用现有组件）
  - 折叠区 → 遍历 `display.detail_blocks` 渲染
- 无 `audit_type_code` 的老数据：走默认渲染（当前行为）

### 4.3 日志列表过滤

- `static/scripts/modules/logs.js` 的 `lf` 新增 `audit_type_code` 字段
- 列表新增"核查类型"列，展示类型中文名 + 颜色 badge
- 过滤下拉从 `GET /api/audit-types?enabled=true` 获取选项

### 4.4 手动推送表单

**文件：`static/scripts/modules/push.js`**

- 新增"审计类型"多选框（`el-select multiple`）
  - 默认选中 `default_for_schedule=true` 的类型
  - 单选/多选切换开关："并行执行多个类型"（对应 `parallel_audit_types`）
- `buildPushRequestBody()` 附加 `audit_type_codes`、`parallel_audit_types`

### 4.5 审计类型管理页（新增）

**文件：`static/scripts/modules/audit_types.js`（新建）、`static/index.html`**

UI 结构：
```
审计类型管理
├── [列表] 表格（code, 名称, 启用, 排序, 操作）
├── [表单] 右侧抽屉
│   ├── 基础 Tab: code/name/description/enabled/sort_order/default_for_schedule
│   ├── 数据源 Tab: 多命名 SQL 配置（SQL 编辑框 + 字段映射 + 测试执行按钮）
│   ├── Dify Tab: base_url/api_key/input_var/output_key/timeout/extra_inputs + 测试连接
│   ├── 响应解析 Tab: parse_strategy + 各 path 配置
│   └── 展示规则 Tab: 可视化增删改 blocks（拖拽排序 + 字段面板）
```

展示规则编辑器（Tab 5）交互：
- 列出现有 summary/detail blocks，每条可编辑/删除/上下移
- "新增字段"弹窗：选择 `type` → 显示对应参数表单（table 类型显示 columns 编辑）
- "预览"按钮：挑选一条已完成的 push_log 数据灌入渲染引擎即时预览

### 4.6 共享常量

**文件：`static/scripts/modules/constants.js`（可沿用现有或新增）**

```javascript
export const RENDERER_TYPES = [
  { value: 'text_block',     label: '文本段落' },
  { value: 'kv_list',        label: '键值列表' },
  { value: 'table',          label: '表格' },
  { value: 'bool_tag',       label: '布尔标签' },
  { value: 'severity_badge', label: '严重度徽章' },
  { value: 'dimension_grid', label: '维度卡片网格' },
  { value: 'tag_list',       label: '标签列表' },
  { value: 'raw_json',       label: '原始 JSON' },
];
```

---

## 第五阶段：导出服务

**文件：`app/services/export_service.py`**

- `export_push_logs` 新增 `audit_type_codes` 过滤参数
- CSV/Excel 第一列后新增"核查类型"列
- 维度列改为"动态列"：基于查询结果中出现的所有 `dimension` 去重生成；per-type 特色字段**不进入通用导出**，仅提供"按类型导出"入口（新接口 `/api/logs/export/by-audit-type/{code}`，根据 `display.detail_blocks` 自动展开列）

---

## 第六阶段：单元测试

新增/更新的测试文件：

| 测试文件 | 覆盖点 |
|---|---|
| `tests/test_audit_type_registry.py` | 配置加载、校验、热更新、code 唯一性 |
| `tests/test_data_source_loader.py` | 多 SQL 并行抽取、按 group_key 合并、required 缺失跳过 |
| `tests/test_payload_composer.py` | generic_multi_source 文本拼接、legacy 保底不变 |
| `tests/test_dify_response_paths.py` | JSONPath 抽取、parse_strategy 三种分支 |
| `tests/test_push_executor.py`（更新） | audit_type_code 写入、多类型并行 |
| `tests/test_manual_push_multi_types.py` | /api/push/manual 多类型流程（Mock Dify） |
| `tests/test_audit_types_api.py` | /api/audit-types CRUD + 内置类型不可删 |

全部使用 SQLite 内存库 + Mock Dify HTTP 响应（`responses` 或 `respx` 库；若当前 requirements 未加入，此计划里**新增 `responses>=0.25` 到 `requirements.dev.txt`**）。

---

## 第七阶段：迁移与兼容

1. **启动时种子**：`_ensure_default_audit_type()` 把现有 `oracle/postgresql/dify` 配置派生为 `progress_vs_nursing`
2. **旧数据**：`audit_type_code=""` 的 push_log 在前端按"病程 vs 护理"默认渲染
3. **旧 API**：`/api/push/manual` 不传 `audit_type_codes` 时走"调度默认集合"（兼容行为）；不传 `parallel_audit_types` 默认 false
4. **配置备份**：新增字段前，`config.py.save_config()` 自动在 `config/backups/` 保存时间戳副本
5. **回滚策略**：`audit_types` 配置损坏时，`AuditTypeRegistry` 记录日志并降级为仅保留 `progress_vs_nursing` 内置种子

---

## 关键文件变更清单

| 文件 | 变更 |
|---|---|
| `app/config.py` | 新增 `audit_types` 默认结构 + `_ensure_default_audit_type` |
| `app/schemas.py` | 新增 `AuditTypeConfig` 系列；`ManualPushRequest`/`PushLogItem` 扩展 |
| `app/models.py` | `PushLog.audit_type_code` 列 |
| `app/database.py` | `_migrate_push_log_columns` 追加 ALTER TABLE |
| `app/services/audit_type_registry.py` | **新建** |
| `app/services/data_source_loader.py` | **新建** |
| `app/services/payload_composer.py` | **新建**（generic/legacy 两种 builder） |
| `app/services/payload_builder.py` | 保留不变，被 legacy builder 调用 |
| `app/dify_pusher.py` | `push_to_dify` 支持 override；新增 `apply_response_paths` |
| `app/services/push_executor.py` | 引入 `audit_type` 字段；改 `_push_single_record` 流程 |
| `app/services/bulk_push_executor.py` | 同上；新增 `execute_manual_multi_types` |
| `app/scheduler.py` | 遍历 `default_for_schedule` 类型 |
| `app/routers/audit_types.py` | **新建**（CRUD + test） |
| `app/routers/push.py` | 接受 `audit_type_codes` + `parallel_audit_types` |
| `app/routers/logs.py` | 过滤 & 详情返回 `audit_type_*` 字段 |
| `app/services/export_service.py` | 新增 audit_type 列 + 按类型导出 |
| `app/main.py` | 注册 `audit_types` 路由 |
| `static/index.html` | 新增"审计类型管理"菜单与入口；日志列表新增类型列 |
| `static/scripts/modules/audit_types.js` | **新建**（CRUD + 展示规则编辑器） |
| `static/scripts/modules/render_engine.js` | **新建** |
| `static/scripts/modules/logs.js` | 详情渲染改造；过滤加 audit_type |
| `static/scripts/modules/push.js` | 手动推送表单加选项 |
| `static/scripts/modules/constants.js` | RENDERER_TYPES 等常量 |
| `static/scripts/modules/stats.js` | 维度图表按 audit_type 聚合（次要） |
| `tests/test_audit_type_*.py` | **新建** |
| `requirements.dev.txt` | 加入 `responses`、`jsonpath-ng` |
| `requirements.txt` | 加入 `jsonpath-ng`（运行时依赖） |

---

## 实施阶段顺序（供 codex 执行）

```
Step 1. 配置层          → app/config.py + app/schemas.py
Step 2. 数据库迁移      → app/models.py + app/database.py (ALTER TABLE)
Step 3. Registry 服务   → app/services/audit_type_registry.py + 单测
Step 4. DataSourceLoader → app/services/data_source_loader.py + 单测
Step 5. PayloadComposer → app/services/payload_composer.py + 单测
Step 6. Dify 改造       → app/dify_pusher.py (override + apply_response_paths)
Step 7. 执行器改造      → app/services/push_executor.py / bulk_push_executor.py
Step 8. 调度器适配      → app/scheduler.py
Step 9. 路由新增/修改   → app/routers/audit_types.py + 修改 push.py / logs.py
Step 10. 导出服务       → app/services/export_service.py
Step 11. 前端渲染引擎   → static/scripts/modules/render_engine.js
Step 12. 前端日志/推送  → static/scripts/modules/logs.js / push.js
Step 13. 前端管理页     → static/scripts/modules/audit_types.js + index.html
Step 14. 集成测试脚本   → scripts/test_audit_types.py（新建）
Step 15. 文档 & 示例配置 → docs/audit-types.md + 三个 example JSON
```

---

## 验证方案

### 功能验证（按阶段）
1. **配置 API**：
   - `curl -X POST /api/audit-types -d @examples/labexam_vs_progress.json` → 创建成功
   - `GET /api/audit-types` → 返回已脱敏的列表
   - `POST /api/audit-types/labexam_vs_progress/test-source` → 返回样例记录数
   - `POST /api/audit-types/labexam_vs_progress/test-dify` → 返回 Dify 响应

2. **推送验证**：
   - 手动推送单类型 `progress_vs_nursing`：行为与当前完全一致（回归测试）
   - 手动推送单类型 `labexam_vs_progress`：push_log.audit_type_code 正确写入；response_json 包含完整 raw
   - 手动推送多类型并行：TaskProgressManager 进度总量 = 患者数 × 类型数；失败类型不影响其他

3. **前端渲染**：
   - 日志详情页：切换不同 audit_type_code 的日志，验证 summary_blocks / detail_blocks 渲染正确
   - 审计类型管理页：新增/克隆/编辑/删除（含内置保护）、展示规则编辑器实时预览

4. **调度器**：
   - 启动服务，等待 cron 触发 → 日志中可见"[audit_type=progress_vs_nursing] 开始推送"依次切换
   - `SchedulerHistory` 每个类型一条记录

### 回归测试
- `pytest tests/ -v` 全绿
- `scripts/test_api.py` 通过
- `scripts/quick_start.py` 通过

### 性能验证
- 单类型推送耗时与当前持平（±5%）
- 三类型串行推送：总耗时 ≈ 3× 单类型；并行模式（3 类型）：总耗时 ≈ 1.2× 单类型（受 Dify 端性能限制）

### 部署验证
- `docker-compose up -d --build` → 容器启动成功
- `/api/health` 返回 healthy
- 旧数据（无 audit_type_code）在前端日志页可正常打开详情

---

## 风险与权衡

| 风险点 | 缓解方案 |
|---|---|
| 配置复杂度高，新手上手困难 | 预置 3 个模板（三类核查 JSON 示例）+ "克隆"功能；管理页提供字段说明 tooltip |
| JSONPath 解析性能 | 仅在展示时计算，不落库；raw_json 最大 200KB 截断 |
| 多 Dify endpoint 凭据泄露 | 所有 api_key 走 Fernet；前端响应脱敏；`extra_inputs` 禁止包含 `password/secret` key |
| 旧日志详情渲染异常 | 详情页 `try/catch` + 降级到"原始 JSON 折叠显示" |
| 调度器耗时变长 | 未来版本提供"每类型独立 cron"选项（本版先不做）|
| 前端包体膨胀 | 渲染引擎约 5KB，可接受；审计类型管理页按需加载 |

---

## 交付物

1. 所有 ✅ 完成的代码变更（见"关键文件变更清单"）
2. 三个示例配置文件：
   - `examples/audit-types/progress_vs_nursing.json`
   - `examples/audit-types/labexam_vs_progress.json`
   - `examples/audit-types/frontpage_vs_postop.json`
3. 更新 `CLAUDE.md` 第"架构与核心模块"章节，加入 AuditType 分层说明
4. `docs/audit-types.md`：
   - 概念说明
   - 配置字段参考
   - JSONPath 速查
   - 展示组件目录
   - 常见问题
