# 医疗记录一致性审计系统 —— 生产环境适配与质控报告增强

## Context

前期已完成：启动修复、CDN 离线化、前端全面重写、Vue `#compiler-30` 修复。

**本次需求**：用户提供了真实生产环境的 Dify API、Oracle SQL、数据样例和返回结构，要求：
1. 将 Oracle SQL 和字段映射更新为生产实际版本（当前 SQL 列名与真实视图不匹配），sql可以在前端能够可视化自行输入配置调整。
2. 正确传参给 Dify（输入变量名是 `mr_txt` 不是 `mr_text`，输出 key 是 `aa`），参数也能够进行可视化配置和输入，便于调整。
3. 结构化解析 Dify 返回的 JSON（6 个审计维度 + 总体结论 + 重点关注项）
4. 存储结构化的传入前/传入后内容（而非仅存原始文本和 JSON 字符串）
5. 生成质控报告内嵌页面供临床人员查阅
6. 将请求接口的日志记录到本地log中，比如 请求dify的请求地址、入参 返回参数、数据库查询的日志等记录均需要记录下来，便于排查问题。
---

## 一、Oracle SQL 更新（`oracle_client.py`）

### 1.1 当前问题
当前 SQL（line 82-97）使用的列名在生产视图中不存在：
| 当前代码列名 | 实际视图列名 |
|---|---|
| `a.姓名` | `a.患者姓名` |
| `a.年龄` | ❌ 不存在（需从`出生日期`计算或去掉） |
| `a.科室` | `a.所在科室名称` |
| `a.诊断` | `a.入院诊断` |
| `b.记录内容 AS 病程记录内容` | `b.病历内容` |
| `c.创建时间 AS 护理记录时间` | `c.护理记录时间`（原名） |

### 1.2 替换为生产 SQL
```sql
SELECT
    a.患者ID, a.次数, a.住院号, a.患者姓名, a.性别, a.出生日期, a.入院日期,
    a.BED_NO AS 床号, a.入院诊断, a.入院病情,
    a.护理级别 AS 医嘱护理级别, a.所在科室名称, a.管床医生,
    b.病历标题时间, b.病历名称, b.创建人 AS 病历创建人, b.病历内容,
    c.护理记录时间, c.护理单类型, c.记录人 AS 护理记录人,
    c.体温, c.心率脉搏, c.呼吸, c.血压, c.血氧饱和度, c.血糖, c.意识神志,
    c.氧疗_鼻导管, c.氧疗_面罩,
    c.入量_名称, c.入量_途径, c.入量_量, c.出量_名称, c.出量_量, c.尿量,
    c.皮肤情况, c.刀口情况, c.管道护理, c.高危风险,
    c.病情观察及护理措施, c.护士签名
FROM jhemr.v_zybr a
LEFT JOIN jhemr.v_bcjl b ON a.患者ID = b.患者ID AND a.次数 = b.次数
LEFT JOIN ydhl.v_hljl c ON c.患者ID = b.患者ID || '_' || b.次数
    AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = TO_CHAR(c.护理记录时间, 'yyyy-mm-dd')
WHERE {dept_filter}
  AND TO_CHAR(b.病历标题时间, 'yyyy-mm-dd') = :query_date
ORDER BY a.患者ID, a.次数, b.病历标题时间, c.护理记录时间
```

### 1.3 `fetch_department_list()` 修改
line 58: `科室` → `所在科室名称`

### 1.4 `group_by_patient()` 修改
分组键从 `患者ID` 改为 `f"{患者ID}_{次数}"`，避免同一患者不同住院次数的记录混在一起。

### 1.5 `build_mr_text_combined()` 重写
扩展为包含所有生产字段的结构化文本：
```
【患者信息】
姓名：XX | 性别：X | 出生日期：XX | 住院号：XX | 次数：X
科室：XX | 床号：XX | 管床医生：XX
入院日期：XX | 入院诊断：XX | 入院病情：XX | 医嘱护理级别：XX

--- 第 1 条记录 ---
【病程记录】（时间：XX | 名称：XX | 创建人：XX）
{病历内容}

【护理记录】（时间：XX | 类型：XX | 记录人：XX）
生命体征：体温XX 心率XX 呼吸XX 血压XX 血氧XX 血糖XX 意识XX
氧疗：鼻导管XX 面罩XX
出入量：入量(名称XX 途径XX 量XX) 出量(名称XX 量XX) 尿量XX
专科评估：皮肤XX | 刀口XX | 管道XX | 高危风险XX
护理观察：{病情观察及护理措施}
护士签名：XX
```

### 1.6 级联修改（列名引用变更）

| 文件 | 位置 | 旧值 → 新值 |
|---|---|---|
| `services/push_executor.py` | line 189 | `"姓名"` → `"患者姓名"` |
| `services/push_executor.py` | line 190 | `"科室"` → `"所在科室名称"` |
| `services/config_parser.py` | line 124 | `r.get("科室")` → `r.get("所在科室名称")` |
| `services/config_parser.py` | line 128 | `r.get("科室")` → `r.get("所在科室名称")` |
| `routers/push.py` | line 77 | `"姓名"` → `"患者姓名"` |
| `routers/push.py` | line 78 | `"科室"` → `"所在科室名称"` |
| `oracle_client.py` | line 74 | `a.科室 IN (...)` → `a.所在科室名称 IN (...)` |

---

## 二、Dify 集成修复（`dify_pusher.py` + `config.py`）

### 2.1 修复输入变量名默认值
三处修改 `"mr_text"` → `"mr_txt"`：
- `config.py` line 78: `_DEFAULT_CONFIG["dify"]["workflow_input_variable"]`
- `schemas.py` line 29: `DifyConfig.workflow_input_variable` 的 Field 默认值
- `config_parser.py` line 61: `setdefault("workflow_input_variable", "mr_txt")`

### 2.2 新增 `workflow_output_key` 配置
在 `_DEFAULT_CONFIG["dify"]` 中增加 `"workflow_output_key": "aa"`。

需修改的文件：
- `config.py`: 默认配置增加该字段
- `schemas.py`: `DifyConfig` 增加 `workflow_output_key` 字段 + `DifyConfigResponse` 增加该字段
- `config_parser.py`: `parse_dify_config` 增加 `setdefault`
- `routers/config.py`: `save_dify_config` 和 `get_dify_config` 处理该字段

### 2.3 重写 Dify 响应解析

**当前问题**：`_extract_inconsistency()` 仅做关键字匹配（"不一致"/"inconsisten"），输出 key 只查 "result","output","text","analysis"。

**实际 Dify 返回**：
```json
{
  "data": {
    "outputs": {
      "aa": "{ \"患者姓名\": \"XX\", \"核查结果\": [{\"维度\":\"诊断一致性\",\"状态\":\"✅\",\"说明\":\"...\"},...], \"总体结论\":\"...\", \"重点关注项\":[...] }"
    }
  }
}
```

**新函数 `parse_dify_structured_output(outputs, output_key)`**：
1. 取 `outputs[output_key]`，失败则遍历 fallback keys
2. 若是字符串，`json.loads()` 解析
3. 提取 `核查结果` 列表，每项包含 `{维度, 状态, 病程记录内容, 护理记录内容, 说明}`
4. 状态映射：`"❌"` → inconsistency=True, severity="high"；`"⚠️"` → severity="medium"；`"✅"/"❓"` → severity="low"
5. 提取 `总体结论` 和 `重点关注项`
6. 返回完整解析结构 + 兼容旧 `inconsistency`/`severity` 字段
7. **解析失败时回退**：存原始输出，不中断推送流程

---

## 三、数据库新增结构化存储（`models.py`）

### 3.1 新增表 `AuditDimensionResult`
```python
class AuditDimensionResult(Base):
    __tablename__ = "audit_dimension_result"
    id = Column(Integer, primary_key=True, autoincrement=True)
    push_log_id = Column(Integer, nullable=False, index=True)  # 关联 push_log.id
    dimension = Column(String(50), nullable=False)     # 如"诊断一致性"
    status = Column(String(10), nullable=False)        # ✅❌⚠️❓
    medical_content = Column(Text, default="")         # 病程记录内容
    nursing_content = Column(Text, default="")         # 护理记录内容
    explanation = Column(Text, default="")             # 说明
```

### 3.2 新增表 `AuditConclusion`
```python
class AuditConclusion(Base):
    __tablename__ = "audit_conclusion"
    id = Column(Integer, primary_key=True, autoincrement=True)
    push_log_id = Column(Integer, nullable=False, unique=True, index=True)
    overall_conclusion = Column(Text, default="")      # 总体结论
    focus_items = Column(Text, default="")             # JSON array: 重点关注项
    audit_date = Column(String(20), default="")        # 核查日期
```

### 3.3 PushLog 表新增字段
```python
admission_no = Column(String(50), default="", index=True)   # 住院号
visit_number = Column(String(20), default="")               # 次数
```

### 3.4 数据库迁移策略
- 新表由 `Base.metadata.create_all()` 自动创建
- PushLog 新字段：在 `init_db()` 中添加 `ALTER TABLE` 包裹 try/except
- 旧记录的新字段为空，属正常状态

---

## 四、推送执行器存储增强（`push_executor.py`）

### 4.1 `_create_push_log()` 增强
在创建 `PushLog` 之后，额外创建：
1. 多条 `AuditDimensionResult`（来自 `dify_result["parsed_output"]["dimensions"]`）
2. 一条 `AuditConclusion`（来自 `dify_result["parsed_output"]`）
3. 填充 `PushLog.admission_no` 和 `PushLog.visit_number`

### 4.2 `execute_retry()` 增强
重推成功后：
1. 删除旧的 `AuditDimensionResult` 和 `AuditConclusion`
2. 用新结果重建

### 4.3 `routers/logs.py` 的 `retry_single()` 同步修改

---

## 五、质控报告页面（新增 `routers/report.py`）

### 5.1 HTML 报告端点：`GET /report/{log_id}`
返回自包含的 HTML 页面，供临床人员在浏览器中查看和打印。

**数据加载**：
1. 查 PushLog → 患者基础信息
2. 查 AuditDimensionResult → 6 个审计维度详情
3. 查 AuditConclusion → 总体结论 + 重点关注项
4. 兼容旧数据：若无结构化数据，尝试从 `ai_result` JSON 重新解析

**页面设计**：
```
┌──────────────────────────────────────────────┐
│         病历一致性核查报告                      │
│  患者：XX  住院号：XX  科室：XX  日期：XX       │
├──────────────────────────────────────────────┤
│ 核查维度        状态   说明                    │
│ ─────────────  ────  ──────────────────      │
│ 诊断一致性       ✅    诊断信息一致             │
│ 护理级别执行     ❌    护理级别不匹配           │
│   ├─ 病程记录：XX                             │
│   └─ 护理记录：XX                             │
│ 生命体征交叉     ✅    体温/心率等数据一致       │
│ ...                                          │
├──────────────────────────────────────────────┤
│ 总体结论：存在1项不一致，建议核查               │
│ 重点关注项：                                   │
│   1. 核实护理级别是否与医嘱一致                 │
│   2. ...                                     │
├──────────────────────────────────────────────┤
│ [打印] [返回]                                 │
└──────────────────────────────────────────────┘
```

**状态颜色**：✅ 绿 `#52c41a` | ❌ 红 `#ff4d4f` | ⚠️ 橙 `#fa8c16` | ❓ 灰 `#8c8c8c`

所有 CSS 内联于 `<style>` 块，无外部依赖，打印时隐藏操作按钮。

### 5.2 JSON 数据端点：`GET /api/report/{log_id}/data`
返回结构化 JSON，供前端 SPA 在对话框内渲染报告。

### 5.3 路由注册（`main.py`）
在 static mount（line 96）之前注册：
```python
from app.routers import report
app.include_router(report.router, tags=["📄 审计报告"])
```

---

## 六、Schemas 更新（`schemas.py`）

### 6.1 DifyConfig 修改
```python
class DifyConfig(BaseModel):
    ...
    workflow_output_key: constr(min_length=1, max_length=50) = Field("aa", description="Dify Workflow 输出变量名")
```

### 6.2 DifyConfigResponse 修改
增加 `workflow_output_key: str` 字段

### 6.3 新增 Schema
```python
class AuditDimensionItem(BaseModel):
    dimension: str
    status: str        # ✅❌⚠️❓
    medical_content: str = ""
    nursing_content: str = ""
    explanation: str = ""

class AuditReportResponse(BaseModel):
    log_id: int
    patient_id: str
    patient_name: str
    admission_no: str
    dept: str
    query_date: str
    push_time: datetime
    dimensions: List[AuditDimensionItem]
    overall_conclusion: str
    focus_items: List[str]
    status: str

class DimensionStatsItem(BaseModel):
    dimension: str
    total: int
    pass_count: int      # ✅
    fail_count: int      # ❌
    warn_count: int      # ⚠️
    unknown_count: int   # ❓
    pass_rate: float
```

---

## 七、配置路由更新（`routers/config.py`）

### 7.1 `save_dify_config()` 修改
增加 `workflow_output_key` 和 `extra_inputs` 写入：
```python
data = {
    ...
    "workflow_output_key": body.workflow_output_key,
    "extra_inputs": body.extra_inputs,
}
```

### 7.2 `get_dify_config()` 修改
返回中增加 `workflow_output_key` 和 `extra_inputs`

---

## 八、统计增强（`routers/stats.py`）

新增端点：`GET /api/stats/dimensions`
- 联查 `audit_dimension_result` + `push_log`
- 按 `dimension` 和 `status` 分组统计
- 支持 `date_from`/`date_to`/`dept` 过滤
- 返回每个维度的通过/不通过/警告/未知计数及通过率

---

## 九、前端增强（`static/index.html`）

### 9.1 推送日志页
- 增加"查看报告"按钮列（仅 status=success 时显示）
- 点击后 `window.open('/report/' + log.id, '_blank')`

### 9.2 日志详情对话框
- 新增 `el-tabs` 切换"审计报告"和"原始数据"
- "审计报告" Tab 调用 `/api/report/{log_id}/data` 渲染维度表格

### 9.3 Dify 配置表单
- 增加 `workflow_output_key` 输入框
- `dForm` 增加 `workflow_output_key` 字段
- `loadDifyCfg`/`saveDify` 方法处理新字段

### 9.4 统计页
- 增加维度统计分组柱状图（调用 `/api/stats/dimensions`）

---

## 十、关键文件变更清单

| 文件 | 操作 | 改动量 |
|---|---|---|
| `app/oracle_client.py` | **大改** SQL + 文本组装 + 分组逻辑 + 列名 | ~100 行 |
| `app/dify_pusher.py` | **大改** 新增结构化解析函数 + 传参 output_key | ~80 行 |
| `app/models.py` | **新增** 2 个表 + PushLog 2 个字段 | ~30 行 |
| `app/schemas.py` | **新增** 3 个 Schema + 修改 DifyConfig | ~40 行 |
| `app/config.py` | 修改默认值 mr_txt + 新增 output_key | ~5 行 |
| `app/database.py` | 新增 ALTER TABLE 迁移 | ~10 行 |
| `app/services/push_executor.py` | 增强 _create_push_log + retry | ~40 行 |
| `app/services/config_parser.py` | 列名变更 + 新增 setdefault | ~5 行 |
| `app/routers/config.py` | 保存/读取新字段 | ~10 行 |
| `app/routers/report.py` | **新建** HTML 报告 + JSON 端点 | ~200 行 |
| `app/routers/logs.py` | retry 增强 | ~15 行 |
| `app/routers/stats.py` | 新增维度统计端点 | ~40 行 |
| `app/main.py` | 注册 report 路由 | ~3 行 |
| `static/index.html` | 增加报告入口 + Dify 配置字段 + 维度图表 | ~60 行 |

---

## 十一、执行顺序（按依赖关系）

1. `models.py` → 新表 + 新字段（一切存储的基础）
2. `database.py` → ALTER TABLE 迁移逻辑
3. `schemas.py` → 新 Schema + 修改 DifyConfig
4. `config.py` + `config_parser.py` → 默认值 + 新字段
5. `oracle_client.py` → 生产 SQL + 文本组装 + 分组
6. `dify_pusher.py` → 结构化响应解析
7. `push_executor.py` → 结构化存储
8. `routers/config.py` → Dify 配置保存/读取
9. `routers/logs.py` → retry 增强
10. `routers/report.py` → **新建**报告路由
11. `routers/stats.py` → 维度统计端点
12. `main.py` → 注册 report 路由
13. `static/index.html` → 前端增强

---

## 十二、验证方式

1. **启动**：`cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
2. **配置 Dify**：在配置页填入实际 Dify base_url + API key + output_key="aa" + input_variable="mr_txt"
3. **配置 Oracle**：填入实际 Oracle 连接信息，测试连通
4. **手动推送**：选择日期执行推送，检查日志
5. **查看报告**：在推送日志列表点击"查看报告"，验证报告页面渲染
6. **打印报告**：在报告页面点击打印，验证打印布局
7. **统计图表**：访问统计页，检查维度统计图表
8. **Dry-run 预览**：验证新文本格式包含所有生产字段
9. **向后兼容**：旧的推送日志打开报告页应显示"无结构化数据"或尝试重新解析
