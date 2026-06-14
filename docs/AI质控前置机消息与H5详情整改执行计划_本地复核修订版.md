# AI质控前置机消息与医生端H5详情整改执行计划（本地复核修订版）

项目仓库：`pengpeng112/ai_mr_yiyyaa`  
当前参考版本：`562f06e`  
计划版本：`v2-local-reviewed`  
适用范围：前置机高危质控消息、医生端 H5 详情页、查看记录、核查对象标题展示、后台前置机告警列表。

---

## 0. 本版修订说明

本计划是在上一版“前置机消息推送与 H5 详情完善计划”的基础上，根据本地实际复核结果修订而来。上一版方向基本正确，但按当前仓库实际代码，需要重点修正以下问题：

1. **不能只改 `models.py`，必须同步改 `app/database.py` 迁移与 schema 自检。**
2. **`mobile_qc._get_token_secret()` 不能继续 fallback 到 `source`，必须与 relay 侧 secret 策略一致。**
3. **前置机是否支持嵌套 JSON 不确定，第一版不要强依赖发送 `evidence_titles` 嵌套结构。**
4. **后台前置机告警列表已有明确接口 `/patient-qc/relay-alert/logs`，需要直接改 `app/routers/patient_qc.py` 和对应前端文件。**
5. **Oracle 字段名不能假设过多，第一版 SQL 必须保守，只使用已确认字段，字段不确定的要明确列出等待人工确认。**
6. **H5 前端不只改 HTML，还必须同步改 JS 和 CSS。**
7. **查看记录需要处理 FastAPI 参数顺序、token 校验失败不记录、事务边界、重复查看计数。**

---

## 1. 当前问题与整改目标

### 1.1 当前问题

当前系统存在：

1. 前置机消息中科室显示“未知科室”或为空。
2. H5 详情页中“科室”“管床医师”为空。
3. 前置机接收人可能能查到管床医生，但 payload/H5 仍拿不到该医生信息。
4. 医生点击打开 H5 详情后，系统没有记录“是否查看、谁查看、查看时间、查看次数”。
5. H5 详情缺少“本次核查对象”，医生不知道具体核查的是哪份病程、护理记录、检验项目或检查报告。
6. 后台前置机告警列表没有展示查看状态和核查对象摘要。
7. `mobile_qc.py` token secret 仍 fallback 到 `source`，与当前 relay 侧“无 secret 不生成 detail_url”的策略不一致。
8. 前置机是否支持嵌套 JSON 未确认，直接发送 `evidence_titles` 有兼容风险。

### 1.2 整改目标

本次整改目标：

1. 前置机消息和 H5 页面能显示正确科室、科室编码、管床医师。
2. H5 详情接口能记录查看状态：
   - 是否已查看
   - 首次查看时间
   - 最近查看时间
   - 查看次数
   - 最近查看人
   - IP 和 User-Agent
3. H5 页面和前置机 payload 中增加“本次核查对象”摘要。
4. 后台 `/patient-qc/relay-alert/logs` 返回并展示查看状态和核查对象摘要。
5. 数据库模型、SQLite 迁移、Oracle 迁移、启动 schema 自检保持一致。
6. token secret 策略统一：无 secret 不生成可访问链接，不允许 fallback 到 `source`。
7. 第一版前置机只依赖 `evidence_summary` 字符串；`evidence_titles` 结构化字段主要给本地 H5 使用，是否发送给前置机由配置控制或后续确认。

---

## 2. 修改范围

### 2.1 后端文件

必须检查和修改：

```text
app/services/relay_alert_service.py
app/services/alert_evidence_service.py         # 新增
app/routers/mobile_qc.py
app/routers/patient_qc.py
app/models.py
app/database.py
```

### 2.2 前端文件

必须检查和修改：

```text
static/templates/mobile/qc_detail.html
static/scripts/mobile/qc_detail.js
static/styles/mobile/qc_detail.css

static/templates/pages/patient_qc.html
static/scripts/modules/patient_qc.js
```

### 2.3 测试文件

建议新增或修改：

```text
tests/test_relay_alert_service.py
tests/test_mobile_qc.py
tests/test_alert_evidence_service.py
```

### 2.4 执行前必须阅读

```text
AGENTS.md
app/services/relay_alert_service.py
app/routers/mobile_qc.py
app/models.py
app/database.py
app/routers/patient_qc.py
```

---

## 3. 阶段一：患者上下文补全

### 3.1 新增 `_query_patient_dept_info()`

文件：`app/services/relay_alert_service.py`

新增函数：

```python
def _query_patient_dept_info(patient_id: str, visit_number: str = "") -> dict:
    """
    从 JHEMR.V_QYBR 查询患者科室信息。
    返回：
    {
        "dept_code": "",
        "dept_name": "",
        "admission_dept_name": "",
        "discharge_dept_name": ""
    }
    """
```

### 3.1.1 SQL 设计原则

不要直接假设所有字段都存在。根据本地复核，当前已知或较确定字段包括：

```text
出院科室编码
所在科室名称
入院科室名称
出院日期
入院日期
```

`出院科室名称` 是否存在不确定，不要第一版硬写到生产 SQL，除非先确认字段存在。

### 3.1.2 推荐第一版 SQL

有 `visit_number` 时：

```sql
SELECT *
FROM (
    SELECT
        "出院科室编码",
        "所在科室名称",
        "入院科室名称",
        "出院日期",
        "入院日期"
    FROM JHEMR.V_QYBR
    WHERE "患者ID" = :pid
      AND "次数" = :vn
    ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST
)
WHERE ROWNUM = 1
```

无 `visit_number` 时：

```sql
SELECT *
FROM (
    SELECT
        "出院科室编码",
        "所在科室名称",
        "入院科室名称",
        "出院日期",
        "入院日期"
    FROM JHEMR.V_QYBR
    WHERE "患者ID" = :pid
    ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST
)
WHERE ROWNUM = 1
```

### 3.1.3 注意事项

必须使用：

```python
visit_num = str(visit_number or "").strip()
```

不要使用：

```python
visit_number.strip()
```

因为 `visit_number` 可能是数字。

Oracle 查询异常必须吞掉并记录 warning，不得影响前置机主流程：

```python
except Exception as exc:
    logger.warning("[relay_alert] query patient dept info failed patient_id=%s visit=%s err=%s", patient_id, visit_num, exc)
    return {}
```

返回字段建议：

```python
return {
    "dept_code": _as_text(row[0]),
    "dept_name": _as_text(row[1]),
    "admission_dept_name": _as_text(row[2]),
    "discharge_dept_name": "",
}
```

如果后续确认存在 `出院科室名称`，再把它加入查询并优先作为 `discharge_dept_name`。

---

### 3.2 增强 `_query_attending_doctor()`

文件：`app/services/relay_alert_service.py`

当前已有 `_query_attending_doctor()`，建议做以下增强：

1. `visit_number` 使用 `str(visit_number or "").strip()`。
2. SQL 按 `患者ID + 次数` 精确查。
3. 加 `ORDER BY 出院日期 DESC NULLS LAST, 入院日期 DESC NULLS LAST`。
4. 查询异常记录 warning。
5. 字段名以实际为准，优先使用已确认字段：

```text
管床医生编号
管床医生
```

推荐 SQL：

```sql
SELECT *
FROM (
    SELECT
        "管床医生编号",
        "管床医生",
        "出院日期",
        "入院日期"
    FROM JHEMR.V_QYBR
    WHERE "患者ID" = :pid
      AND "次数" = :vn
    ORDER BY "出院日期" DESC NULLS LAST, "入院日期" DESC NULLS LAST
)
WHERE ROWNUM = 1
```

---

### 3.3 新增 `_hydrate_patient_context()`

文件：`app/services/relay_alert_service.py`

新增函数：

```python
def _hydrate_patient_context(patient_info: dict, push_log: PushLog | None) -> dict:
    """
    统一补全前置机消息、H5详情页和后台列表需要的患者上下文。
    只有关键字段缺失时才查 Oracle，避免重复查询。
    """
```

### 3.3.1 输出字段

必须保证返回结构至少包含：

```python
{
    "patient_id": "",
    "visit_number": "",
    "patient_name": "",
    "admission_no": "",
    "dept": "",
    "dept_name": "",
    "dept_code": "",
    "admission_dept_name": "",
    "discharge_dept_name": "",
    "doctor_id": "",
    "doctor_name": "",
    "nurse_head_userid": "",
    "nurse_head_name": "",
}
```

### 3.3.2 科室补全优先级

```text
1. patient_info.dept
2. patient_info.department
3. patient_info.所在科室名称
4. patient_info.科室
5. patient_info.dept_name
6. push_log.dept
7. patient_info.discharge_dept_name
8. patient_info.admission_dept_name
9. Oracle _query_patient_dept_info().dept_name
10. 仍为空则保留空，由前端展示“未维护科室”
```

### 3.3.3 科室编码补全优先级

```text
1. patient_info.dept_code
2. patient_info.科室编码
3. patient_info.department_code
4. Oracle _query_patient_dept_info().dept_code
```

### 3.3.4 管床医师补全优先级

医生姓名：

```text
1. patient_info.doctor_name
2. patient_info.attending_doctor_name
3. patient_info.attending_doctor
4. patient_info.管床医生
5. patient_info.管床医师
6. Oracle _query_attending_doctor().doctor_name
```

医生编号：

```text
1. patient_info.doctor_id
2. patient_info.attending_doctor_userid
3. patient_info.attending_doctor_id
4. patient_info.管床医生编号
5. patient_info.管床医师编号
6. Oracle _query_attending_doctor().doctor_id
7. 如果有 doctor_name 无 doctor_id，则 _query_userid_by_name()
```

### 3.3.5 避免重复查 Oracle

规则：

- 如果 `dept/dept_name/dept_code` 都已有，不查科室。
- 如果 `doctor_name/doctor_id` 都已有，不查医生。
- `_get_patient_info()` 调一次 hydrate。
- `_build_receivers()` 继续可做兜底，但应优先使用 hydrate 后的 `patient_info`，不要重复查询相同信息。

---

### 3.4 修改 `_get_patient_info()`

文件：`app/services/relay_alert_service.py`

现有 `_get_patient_info(log)` 返回前必须调用：

```python
return _hydrate_patient_context(result, log)
```

要求：

1. Oracle 查到的 `dept_name`、`dept_code`、`doctor_name`、`doctor_id` 必须回写到 `result`。
2. 不能只在 `_build_receivers()` 里使用医生信息。
3. `_build_payload()` 使用的 `patient_info` 必须已补全。
4. H5 detail 也应能从 alert payload 读取到补全后的字段。

---

### 3.5 修改 `_build_payload()`

文件：`app/services/relay_alert_service.py`

在 payload 字段循环后强制追加：

```python
payload["dept"] = patient_info.get("dept") or payload.get("dept") or ""
payload["dept_name"] = patient_info.get("dept_name") or patient_info.get("dept") or payload.get("dept") or ""
payload["dept_code"] = patient_info.get("dept_code") or ""
payload["admission_dept_name"] = patient_info.get("admission_dept_name") or ""
payload["discharge_dept_name"] = patient_info.get("discharge_dept_name") or ""
payload["doctor_id"] = patient_info.get("doctor_id") or payload.get("doctor_id") or ""
payload["doctor_name"] = patient_info.get("doctor_name") or payload.get("doctor_name") or ""
```

要求：

- `_create_alert_log().dept` 使用补全后的 `patient_info["dept"]`。
- `payload_json` 中必须能看到这些字段。
- 前置机至少能使用 `dept`、`dept_name`、`doctor_name`。

---

## 4. 阶段二：统一 token secret 策略

### 4.1 当前风险

当前 relay 侧已经修复为：无 secret 不生成可访问 `detail_url`。但 `mobile_qc._get_token_secret()` 仍 fallback 到：

```python
cfg.get("source") or "病历质控系统"
```

这会导致 token 策略不一致。

### 4.2 修改要求

文件：`app/routers/mobile_qc.py`

修改 `_get_token_secret()`：

```python
def _get_token_secret() -> str:
    cfg = load_config().get("relay_alert") or {}
    secret = (cfg.get("secret_key") or "").strip()
    if secret:
        return secret

    enc = (cfg.get("secret_key_enc") or "").strip()
    if enc:
        try:
            return decrypt_value(enc)
        except Exception:
            logger.warning("[mobile_qc] secret_key_enc decrypt failed")
            return ""

    return ""
```

### 4.3 调用处处理

以下接口如果 secret 为空，应返回错误，不允许 fallback source：

```text
/mobile/qc/{alert_id}
/api/mobile/qc-detail/{alert_id}
/api/mobile/qc-detail/{alert_id}/verify-token
/api/mobile/qc-feedback
```

建议：

- HTML 页面返回 401 错误页：“访问令牌配置异常，请联系管理员”。
- API 返回 401 或 500。推荐 401/500 视项目习惯而定。
- 不要记录 viewed。
- 不要提交 feedback。

---

## 5. 阶段三：查看记录能力

### 5.1 修改 `QCRecordAlertLog` 模型

文件：`app/models.py`

在 `QCRecordAlertLog` 中增加：

```python
viewed_flag = Column(Integer, default=0, index=True)  # 0未查看，1已查看
viewed_at = Column(DateTime, nullable=True)
last_viewed_at = Column(DateTime, nullable=True)
view_count = Column(Integer, default=0)
viewer_userid = Column(String(64), default="")
viewer_name = Column(String(64), default="")
viewer_ip = Column(String(64), default="")
viewer_user_agent = Column(Text, default="")
```

### 5.2 修改 `app/database.py`

当前项目没有 Alembic，必须同步修改 `app/database.py`。

需要完成：

1. SQLite 迁移。
2. Oracle 迁移。
3. schema 自检。

### 5.2.1 SQLite 迁移

新增或扩展函数，例如：

```python
def _migrate_qc_record_alert_log_columns():
    ...
```

需要添加字段：

```text
viewed_flag INTEGER DEFAULT 0
viewed_at DATETIME
last_viewed_at DATETIME
view_count INTEGER DEFAULT 0
viewer_userid VARCHAR(64) DEFAULT ''
viewer_name VARCHAR(64) DEFAULT ''
viewer_ip VARCHAR(64) DEFAULT ''
viewer_user_agent TEXT
```

并在 `init_db()` 的 SQLite 路径调用。

### 5.2.2 Oracle 迁移

新增或扩展函数，例如：

```python
def _migrate_oracle_alert_columns():
    ...
```

表名以实际为准，可能是：

```text
MED_QC_RECORD_ALERT_LOG
```

Oracle SQL 示例：

```sql
ALTER TABLE MED_QC_RECORD_ALERT_LOG ADD (
  VIEWED_FLAG NUMBER(1) DEFAULT 0,
  VIEWED_AT DATE,
  LAST_VIEWED_AT DATE,
  VIEW_COUNT NUMBER DEFAULT 0,
  VIEWER_USERID VARCHAR2(64) DEFAULT '',
  VIEWER_NAME VARCHAR2(64) DEFAULT '',
  VIEWER_IP VARCHAR2(64) DEFAULT '',
  VIEWER_USER_AGENT CLOB
)
```

索引名必须小于 30 字符：

```sql
CREATE INDEX IDX_ALERT_VIEW_FLAG ON MED_QC_RECORD_ALERT_LOG (VIEWED_FLAG)
CREATE INDEX IDX_ALERT_VIEW_AT ON MED_QC_RECORD_ALERT_LOG (VIEWED_AT)
```

### 5.2.3 schema 自检

`_verify_required_schema()` 必须加入：

```text
VIEWED_FLAG
VIEWED_AT
LAST_VIEWED_AT
VIEW_COUNT
VIEWER_USERID
VIEWER_NAME
VIEWER_IP
VIEWER_USER_AGENT
```

否则启动自检可能无法发现迁移缺失。

---

### 5.3 新增 `_mark_alert_viewed()`

文件：`app/routers/mobile_qc.py`

新增：

```python
def _mark_alert_viewed(
    alert: QCRecordAlertLog,
    request: Request,
    viewer_userid: str = "",
    viewer_name: str = "",
) -> None:
    now = datetime.now()

    if not getattr(alert, "viewed_flag", 0):
        alert.viewed_flag = 1
        alert.viewed_at = now

    alert.last_viewed_at = now
    alert.view_count = int(alert.view_count or 0) + 1

    header_userid = request.headers.get("X-WeCom-UserId", "") if request else ""
    header_name = request.headers.get("X-WeCom-UserName", "") if request else ""

    alert.viewer_userid = viewer_userid or header_userid or alert.viewer_userid or ""
    alert.viewer_name = viewer_name or header_name or alert.viewer_name or ""
    alert.viewer_ip = request.client.host if request and request.client else ""
    alert.viewer_user_agent = (request.headers.get("user-agent", "") if request else "")[:500]
```

---

### 5.4 修改 H5 Detail API

当前函数：

```python
def get_qc_detail(alert_id: int, token: str = "", db: Session = Depends(get_db)):
```

应改为注意 FastAPI / Python 参数顺序：

```python
def get_qc_detail(
    alert_id: int,
    request: Request,
    token: str = "",
    viewer_userid: str = "",
    viewer_name: str = "",
    db: Session = Depends(get_db),
):
    ...
```

要求：

1. token 校验失败不记录查看。
2. alert 不存在不记录查看。
3. 成功准备返回详情前调用 `_mark_alert_viewed()`。
4. 调用后 `db.commit()`。
5. 如果 `_mark_alert_viewed()` 写入失败，第一版建议 rollback 并返回 500，以便及时发现迁移问题。

示例：

```python
alert = _verify_token_and_get_alert(token, alert_id, db)

try:
    _mark_alert_viewed(alert, request, viewer_userid, viewer_name)
    db.commit()
except Exception as exc:
    db.rollback()
    logger.error("[mobile_qc] mark viewed failed alert_id=%s err=%s", alert_id, exc, exc_info=True)
    raise HTTPException(status_code=500, detail="查看状态记录失败，请联系管理员")
```

---

### 5.5 修改 H5 JS

文件：`static/scripts/mobile/qc_detail.js`

当前 `loadDetail()` 只传 token，应改为：

```javascript
const params = new URLSearchParams({
  token: TOKEN,
  viewer_userid: VIEWER_USERID || '',
  viewer_name: VIEWER_NAME || ''
});
const resp = await fetch(`${API_BASE}/qc-detail/${ALERT_ID}?${params.toString()}`);
```

---

### 5.6 H5 Detail API 返回查看状态

在返回 JSON 中增加：

```python
"view_status": {
    "viewed_flag": int(alert.viewed_flag or 0),
    "viewed_at": alert.viewed_at.strftime("%Y-%m-%d %H:%M:%S") if alert.viewed_at else "",
    "last_viewed_at": alert.last_viewed_at.strftime("%Y-%m-%d %H:%M:%S") if alert.last_viewed_at else "",
    "view_count": int(alert.view_count or 0),
    "viewer_userid": alert.viewer_userid or "",
    "viewer_name": alert.viewer_name or "",
}
```

---

## 6. 阶段四：核查对象 evidence 标题

### 6.1 新增独立服务文件

不要继续膨胀 `relay_alert_service.py`，新增：

```text
app/services/alert_evidence_service.py
```

包含：

```python
def extract_evidence_titles(push_log, dimension_obj=None, conclusion_obj=None) -> dict:
    ...

def build_evidence_summary(evidence_titles: dict, max_items_per_group: int = 2, max_len: int = 280) -> str:
    ...
```

`relay_alert_service.py` 引用：

```python
from app.services.alert_evidence_service import extract_evidence_titles, build_evidence_summary
```

---

### 6.2 evidence 输出结构

```python
{
    "medical_documents": [
        {"title": "", "time": "", "doctor": ""}
    ],
    "nursing_records": [
        {"title": "", "time": "", "recorder": ""}
    ],
    "lab_reports": [
        {"title": "", "item": "", "time": "", "test_no": "", "result": "", "flag": ""}
    ],
    "exam_reports": [
        {"title": "", "class": "", "time": "", "exam_no": "", "summary": ""}
    ],
    "progress_records": [
        {"title": "", "time": "", "matched_source": ""}
    ],
    "matched_sources": []
}
```

---

### 6.3 提取优先级

优先从 `structured_input` 提取，再回退原始结构。

#### 6.3.1 structured_input

路径：

```text
structured_input["检验检查"]["检验报告信息"]
structured_input["检验检查"]["检查报告"]
structured_input["病程"]["病程记录"]
structured_input["护理"]["护理记录"]
```

字段：

```text
检验项目
报告项目[].报告项目名称
检查名称
病程名称
护理单类型
```

#### 6.3.2 legacy 病程 vs 护理

从 `request_json.medical_documents` 提取：

```text
document_name
document_time
signed_doctor
creator_name
```

从 `request_json.nursing_records` 提取：

```text
record_type
record_time
recorder
```

#### 6.3.3 检验检查

从 `abnormal_labs.items` 提取：

```text
test_no
test_name
report_item_name
item_name
result
units
abnormal_indicator
result_time
```

从 `abnormal_exams.reports` 提取：

```text
exam_no
exam_class
exam_name
description
summary
report_time
exam_time
```

从 `progress_context.records` / `nursing_context.records` 提取：

```text
record_name
event_time
matched_event_source_label
```

---

### 6.4 summary 生成规则

`build_evidence_summary()` 要求：

1. 每类最多展示 2 条。
2. 总长度控制在 280 字左右。
3. 超长截断时不要破坏中文。
4. 输出为空时返回空字符串，不影响推送。

示例：

```text
病历文书《首次病程记录 2026-06-06 09:20》；护理记录《一般护理记录 2026-06-06 10:00》；检验《血常规-白细胞 18.2↑》；检查《胸部CT 2026-06-06 11:00》
```

---

### 6.5 写入 relay payload

文件：`app/services/relay_alert_service.py`

在 `_build_payload()` 中加入：

```python
evidence_titles = extract_evidence_titles(push_log, dimension_obj, conclusion_obj)
evidence_summary = build_evidence_summary(evidence_titles)

payload["evidence_summary"] = evidence_summary
payload["evidence_title"] = evidence_summary
payload["evidence_titles"] = evidence_titles
```

### 6.6 前置机兼容策略

第一版建议：

1. 前置机模板只使用 `evidence_summary` 或 `evidence_title` 字符串。
2. `evidence_titles` 保存在 `QCRecordAlertLog.payload_json`，供 H5 使用。
3. 如果前置机对 payload schema 严格校验，可在 `dispatch_pending()` 发送前复制 payload 并移除 `evidence_titles`。
4. 可增加配置：

```json
{
  "relay_alert": {
    "send_structured_evidence": false
  }
}
```

发送前处理：

```python
payload_to_send = dict(payload)
if not self.relay_cfg.get("send_structured_evidence", False):
    payload_to_send.pop("evidence_titles", None)
```

注意：

- 本地 `alert.payload_json` 仍保留 `evidence_titles`。
- 只是不发送给前置机。

---

## 7. 阶段五：H5 页面展示

### 7.1 H5 Detail API 返回 evidence

文件：`app/routers/mobile_qc.py`

解析 alert payload：

```python
payload = json.loads(alert.payload_json or "{}")
```

返回增加：

```python
"evidence": {
    "summary": payload.get("evidence_summary") or payload.get("evidence_title") or "",
    "titles": payload.get("evidence_titles") or {},
}
```

---

### 7.2 修改 H5 JS

文件：`static/scripts/mobile/qc_detail.js`

当前：

```javascript
const { createApp, ref, reactive, onMounted } = Vue;
```

改为：

```javascript
const { createApp, ref, reactive, onMounted, computed } = Vue;
```

新增：

```javascript
const evidence = ref({ summary: '', titles: {} });

const hasEvidenceTitles = computed(() => {
  const titles = evidence.value.titles || {};
  return Object.values(titles).some(arr => Array.isArray(arr) && arr.length > 0);
});
```

`loadDetail()` 中增加：

```javascript
evidence.value = data.evidence || { summary: '', titles: {} };
```

return 中加入：

```javascript
evidence,
hasEvidenceTitles,
```

---

### 7.3 修改 H5 HTML

文件：`static/templates/mobile/qc_detail.html`

在患者信息卡片后、维度卡片前新增“本次核查对象”卡片：

```html
<section class="card evidence-card" v-if="evidence.summary || hasEvidenceTitles">
  <div class="section-title">本次核查对象</div>

  <div class="content-block" v-if="evidence.summary">
    {{ evidence.summary }}
  </div>

  <div class="evidence-detail" v-if="hasEvidenceTitles">
    <div v-if="evidence.titles.medical_documents && evidence.titles.medical_documents.length">
      <div class="sub-title">病历文书</div>
      <div class="evidence-item" v-for="item in evidence.titles.medical_documents">
        《{{ item.title || '未命名文书' }}》 {{ item.time || '' }} {{ item.doctor || '' }}
      </div>
    </div>

    <div v-if="evidence.titles.nursing_records && evidence.titles.nursing_records.length">
      <div class="sub-title">护理记录</div>
      <div class="evidence-item" v-for="item in evidence.titles.nursing_records">
        《{{ item.title || '未命名护理记录' }}》 {{ item.time || '' }} {{ item.recorder || '' }}
      </div>
    </div>

    <div v-if="evidence.titles.lab_reports && evidence.titles.lab_reports.length">
      <div class="sub-title">检验</div>
      <div class="evidence-item" v-for="item in evidence.titles.lab_reports">
        《{{ item.title || '检验' }}{{ item.item ? '-' + item.item : '' }}》 {{ item.result || '' }} {{ item.flag || '' }} {{ item.time || '' }}
      </div>
    </div>

    <div v-if="evidence.titles.exam_reports && evidence.titles.exam_reports.length">
      <div class="sub-title">检查</div>
      <div class="evidence-item" v-for="item in evidence.titles.exam_reports">
        《{{ item.title || item.class || '检查' }}》 {{ item.time || '' }}
      </div>
    </div>
  </div>
</section>
```

### 7.4 科室和管床医师兜底

将：

```html
<div class="row"><span class="label">科室</span><span class="value">{{ alert.dept }}</span></div>
<div class="row"><span class="label">管床医师</span><span class="value">{{ alert.doctor_name }}</span></div>
```

改为：

```html
<div class="row">
  <span class="label">科室</span>
  <span class="value">{{ alert.dept || alert.discharge_dept_name || alert.admission_dept_name || '未维护科室' }}</span>
</div>
<div class="row">
  <span class="label">管床医师</span>
  <span class="value">{{ alert.doctor_name || '未维护' }}</span>
</div>
```

---

### 7.5 修改 CSS

文件：`static/styles/mobile/qc_detail.css`

新增样式：

```css
.evidence-card .content-block {
  line-height: 1.6;
}

.evidence-detail {
  margin-top: 10px;
}

.sub-title {
  margin-top: 8px;
  font-weight: 600;
  color: #334155;
  font-size: 14px;
}

.evidence-item {
  margin-top: 4px;
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
}
```

---

## 8. 阶段六：后台列表展示

### 8.1 修改后端接口

文件：`app/routers/patient_qc.py`

明确接口：

```text
GET /patient-qc/relay-alert/logs
```

在返回中增加：

```python
viewed_flag
viewed_at
last_viewed_at
view_count
viewer_name
viewer_userid
evidence_summary
```

`evidence_summary` 从 `payload_json` 读取：

```python
def _extract_evidence_summary(payload_json: str) -> str:
    try:
        payload = json.loads(payload_json or "{}")
        return payload.get("evidence_summary") or payload.get("evidence_title") or ""
    except Exception:
        return ""
```

时间格式统一：

```python
viewed_at.strftime("%Y-%m-%d %H:%M:%S") if viewed_at else ""
```

---

### 8.2 修改前端列表

文件：

```text
static/scripts/modules/patient_qc.js
static/templates/pages/patient_qc.html
```

新增展示字段：

```text
查看状态：未查看 / 已查看
首次查看时间
最近查看时间
查看次数
最近查看人
核查对象摘要
```

### 8.3 暂不重构主状态枚举

不要第一版重构主 status 枚举。

原因：

- `QCRecordAlertLog.status` 表示前置机发送状态。
- `QCAlertFeedback` 表示 H5 反馈状态。
- `QCFeedback` 表示业务整改反馈。
- 这三类状态不要混成一个枚举，避免统计口径混乱。

第一版只展示查看状态字段，不改主状态逻辑。

---

## 9. 测试计划

### 9.1 患者上下文测试

文件：`tests/test_relay_alert_service.py`

必须覆盖：

1. `request_json.patient_info.department` 存在时，payload.dept 正确。
2. `request_json` 无科室时，mock `_query_patient_dept_info()` 返回科室，payload.dept 正确。
3. `request_json` 无管床医生时，mock `_query_attending_doctor()` 返回医生，payload.doctor_name 正确。
4. 只有 doctor_name 没有 doctor_id 时，mock `_query_userid_by_name()` 可补 doctor_id。
5. `_build_payload()` 包含：
   - dept
   - dept_name
   - dept_code
   - admission_dept_name
   - discharge_dept_name
   - doctor_id
   - doctor_name

---

### 9.2 查看记录测试

文件：`tests/test_mobile_qc.py`

必须覆盖：

1. token 无效时不记录 viewed。
2. 第一次详情：
   - `viewed_flag=1`
   - `view_count=1`
   - `viewed_at` 非空
   - `last_viewed_at` 非空
3. 第二次详情：
   - `view_count=2`
   - `viewed_at` 不变
   - `last_viewed_at` 更新
4. query 参数 `viewer_userid/viewer_name` 写入 alert。
5. header `X-WeCom-UserId/X-WeCom-UserName` 兜底写入。
6. secret 为空时 token 校验失败，不 fallback source。

---

### 9.3 evidence 测试

文件：`tests/test_alert_evidence_service.py`

必须覆盖：

1. legacy `medical_documents` / `nursing_records`：
   - 能提取 `document_name`
   - 能提取 `record_type`
   - summary 包含文书和护理记录名称
2. 检验检查：
   - 能提取 `test_name`
   - 能提取 `item_name` / `report_item_name`
   - 能提取 `exam_name`
   - 能提取 `progress_context.records[].record_name`
   - 能提取 `nursing_context.records[].record_name`
3. `structured_input` 优先：
   - 从中文结构中提取 `检验项目`
   - `报告项目名称`
   - `检查名称`
   - `病程名称`
   - `护理单类型`
4. summary 限长：
   - 超长时截断
   - 空输入返回空字符串

---

### 9.4 前置机 payload 集成测试

文件：`tests/test_relay_alert_service.py`

`enqueue_high_severity_alerts()` 生成 alert 后，断言：

```text
alert.payload_json 包含：
- dept
- dept_name
- doctor_name
- evidence_summary
- evidence_title
- evidence_titles
- detail_url
```

如启用 `send_structured_evidence=false`，测试 `dispatch_pending()` 发送给前置机的 payload 不包含 `evidence_titles`，但本地 `alert.payload_json` 仍保留。

---

### 9.5 后台接口测试

文件可新增：`tests/test_patient_qc_relay_alert_logs.py`

覆盖：

1. `/patient-qc/relay-alert/logs` 返回 `viewed_flag`。
2. 返回 `view_count`。
3. 返回 `viewer_name`。
4. 从 `payload_json` 解析出 `evidence_summary`。
5. `payload_json` 非法时不报错，返回空 evidence_summary。

---

## 10. 运行命令

执行：

```bash
python -m compileall app tests scripts
python scripts/check_naming_convention.py
python -m pytest tests/test_relay_alert_service.py tests/test_mobile_qc.py tests/test_alert_evidence_service.py -q --tb=short
python -m pytest -q --tb=short
```

如新增后台接口测试：

```bash
python -m pytest tests/test_patient_qc_relay_alert_logs.py -q --tb=short
```

---

## 11. 前置机配合确认项

请最终明确列出以下问题：

1. 前置机模板显示科室用的是：
   - `dept`
   - `dept_name`
   - 其他字段

2. 前置机模板是否显示：
   - `doctor_name`
   - `evidence_summary`

3. 前置机是否能保留 detail_url query string。

4. 前置机是否能追加：

```text
viewer_userid
viewer_name
```

例如：

```text
/qc-detail/{alert_id}?token=xxx&viewer_userid=xxx&viewer_name=xxx
```

5. 如果不能追加 query 参数，是否能通过 header 透传：

```text
X-WeCom-UserId
X-WeCom-UserName
```

6. 前置机是否接受 `evidence_titles` 嵌套 JSON。

第一版建议即使不确认第 6 点，也不要阻塞上线，因为前置机只需使用 `evidence_summary` 字符串。

---

## 12. 上线验证清单

### 12.1 数据库验证

#### SQLite

```sql
SELECT
  id,
  patient_id,
  visit_number,
  dept,
  status,
  viewed_flag,
  viewed_at,
  last_viewed_at,
  view_count,
  viewer_name
FROM qc_record_alert_log
ORDER BY id DESC
LIMIT 20;
```

#### Oracle

```sql
SELECT
  ID,
  PATIENT_ID,
  VISIT_NUMBER,
  DEPT,
  STATUS,
  VIEWED_FLAG,
  VIEWED_AT,
  LAST_VIEWED_AT,
  VIEW_COUNT,
  VIEWER_NAME
FROM MED_QC_RECORD_ALERT_LOG
ORDER BY ID DESC
FETCH FIRST 20 ROWS ONLY;
```

### 12.2 病程 vs 护理场景

1. 找一条 `progress_vs_nursing` 高危记录。
2. 生成前置机 alert。
3. 检查 `payload_json`：
   - dept 不为空
   - doctor_name 不为空
   - evidence_summary 包含病历文书名称和护理记录类型
4. 打开 H5：
   - 科室正常
   - 管床医师正常
   - 显示“本次核查对象”
5. 后台列表：
   - 由未查看变为已查看
   - view_count +1

### 12.3 检验检查场景

1. 找一条检验/检查异常核查记录。
2. 生成前置机 alert。
3. 检查 `payload_json`：
   - evidence_summary 包含检验项目、检查名称、病程/护理记录名称。
4. 打开 H5：
   - 本次核查对象展示检验、检查、病程、护理标题。
5. 后台列表显示查看状态。

---

## 13. 回滚方案

### 13.1 H5 展示异常

回滚：

```text
static/templates/mobile/qc_detail.html
static/scripts/mobile/qc_detail.js
static/styles/mobile/qc_detail.css
```

后端字段保留，不影响推送。

### 13.2 查看记录异常

临时注释：

```python
_mark_alert_viewed(...)
```

保留数据库字段。

### 13.3 前置机发送异常

如果怀疑前置机不兼容新字段：

1. 保留 `evidence_summary`。
2. 在发送前移除 `evidence_titles`。
3. 或设置：

```json
"send_structured_evidence": false
```

### 13.4 Oracle 查询异常

`_query_patient_dept_info()` 和 `_query_attending_doctor()` 必须捕获异常并返回空，不影响主流程。

如字段不确定：

- 暂停 Oracle 查询增强。
- 保留 request_json/push_log 兜底。
- 等字段确认后再启用。

---

## 14. 建议提交拆分

### Commit 1：患者上下文补全

```text
fix: hydrate relay alert patient context
```

范围：

```text
app/services/relay_alert_service.py
tests/test_relay_alert_service.py
```

内容：

- 新增 `_query_patient_dept_info()`
- 新增 `_hydrate_patient_context()`
- `_get_patient_info()` 返回前 hydrate
- `_build_payload()` 强制追加 patient context 字段
- `_create_alert_log().dept` 使用补全后的科室

---

### Commit 2：token secret 统一与查看记录

```text
feat: track mobile qc alert views
```

范围：

```text
app/models.py
app/database.py
app/routers/mobile_qc.py
static/scripts/mobile/qc_detail.js
tests/test_mobile_qc.py
```

内容：

- `QCRecordAlertLog` 新增 viewed 字段
- SQLite / Oracle 迁移
- schema 自检补字段
- `mobile_qc._get_token_secret()` 不再 fallback source
- `get_qc_detail()` 记录查看
- JS 传 viewer 参数

---

### Commit 3：核查对象 evidence

```text
feat: include evidence summary in relay alerts
```

范围：

```text
app/services/alert_evidence_service.py
app/services/relay_alert_service.py
app/routers/mobile_qc.py
tests/test_alert_evidence_service.py
tests/test_relay_alert_service.py
```

内容：

- 新增 evidence 提取服务
- `_build_payload()` 写入 `evidence_summary/evidence_title/evidence_titles`
- H5 detail API 返回 `evidence`
- 第一版前置机只依赖 `evidence_summary`

---

### Commit 4：H5 和后台展示

```text
feat: show alert evidence and view status
```

范围：

```text
static/templates/mobile/qc_detail.html
static/scripts/mobile/qc_detail.js
static/styles/mobile/qc_detail.css
app/routers/patient_qc.py
static/templates/pages/patient_qc.html
static/scripts/modules/patient_qc.js
tests/test_patient_qc_relay_alert_logs.py
```

内容：

- H5 展示“本次核查对象”
- H5 科室/管床医师兜底
- 后台列表返回并展示查看状态、查看次数、查看人、evidence_summary
- 不改主 status 枚举

---

# 附：给开发 AI 的完整执行提示词

```markdown
请基于仓库 pengpeng112/ai_mr_yiyyaa 当前 HEAD，完善“前置机质控消息 + 医生端 H5 详情”。

执行前先阅读：
- AGENTS.md
- app/services/relay_alert_service.py
- app/routers/mobile_qc.py
- app/models.py
- app/database.py
- app/routers/patient_qc.py
- static/templates/mobile/qc_detail.html
- static/scripts/mobile/qc_detail.js
- static/styles/mobile/qc_detail.css
- static/templates/pages/patient_qc.html
- static/scripts/modules/patient_qc.js

请按以下修订计划执行，不要原样套用旧计划。

一、患者上下文补全
1. 在 app/services/relay_alert_service.py 新增 `_query_patient_dept_info(patient_id, visit_number)`。
2. SQL 只使用已确认字段，至少查询：出院科室编码、所在科室名称、入院科室名称、出院日期、入院日期。不要直接假设 `出院科室名称` 存在；如需使用，先做字段存在确认。
3. visit_number 必须写成 `visit_num = str(visit_number or "").strip()`。
4. 新增 `_hydrate_patient_context(patient_info, push_log)`。
5. `_get_patient_info()` 返回前调用 hydrate。
6. `_build_payload()` 强制追加：
   - dept
   - dept_name
   - dept_code
   - admission_dept_name
   - discharge_dept_name
   - doctor_id
   - doctor_name
7. `_create_alert_log().dept` 使用补全后的科室。
8. `_build_receivers()` 不要只把 Oracle 查询到的医生用于接收人，payload/H5 也必须能拿到。

二、token 和查看记录
1. 修改 mobile_qc._get_token_secret()：无 relay_alert.secret 时不要 fallback source，返回空并让 token 校验失败。
2. 在 QCRecordAlertLog 增加：
   - viewed_flag
   - viewed_at
   - last_viewed_at
   - view_count
   - viewer_userid
   - viewer_name
   - viewer_ip
   - viewer_user_agent
3. 因项目无 Alembic，必须同步修改 app/database.py：
   - SQLite 迁移
   - Oracle 迁移 MED_QC_RECORD_ALERT_LOG
   - _verify_required_schema()
4. 在 app/routers/mobile_qc.py 新增 `_mark_alert_viewed()`。
5. 修改 `/api/mobile/qc-detail/{alert_id}`：
   - 增加 Request、viewer_userid、viewer_name 参数。
   - 注意 Request 参数顺序。
   - token 校验失败不记录。
   - 成功返回详情前记录查看。
   - 返回 `view_status`。
6. 修改 static/scripts/mobile/qc_detail.js：
   - loadDetail 请求带 viewer_userid/viewer_name。

三、核查对象 evidence
1. 新增 app/services/alert_evidence_service.py，不要继续膨胀 relay_alert_service.py。
2. 实现：
   - extract_evidence_titles(push_log, dimension_obj=None, conclusion_obj=None)
   - build_evidence_summary(evidence_titles, max_items_per_group=2, max_len=280)
3. 优先从 structured_input 提取，再回退：
   - medical_documents
   - nursing_records
   - abnormal_labs.items
   - abnormal_exams.reports
   - progress_context.records
   - nursing_context.records
4. relay_alert_service._build_payload() 写入：
   - evidence_summary
   - evidence_title
   - evidence_titles
5. 前置机第一版只依赖 evidence_summary 字符串。不要假设前置机支持 evidence_titles 嵌套 JSON。
6. mobile_qc detail API 返回：
   - evidence.summary
   - evidence.titles

四、H5 展示
1. static/templates/mobile/qc_detail.html 在患者信息后增加“本次核查对象”卡片。
2. 科室显示兜底：
   - alert.dept || alert.discharge_dept_name || alert.admission_dept_name || '未维护科室'
3. 管床医师兜底：
   - alert.doctor_name || '未维护'
4. static/scripts/mobile/qc_detail.js 增加 computed、evidence、hasEvidenceTitles。
5. static/styles/mobile/qc_detail.css 补样式。

五、后台列表
1. 修改 app/routers/patient_qc.py 的 `/relay-alert/logs` 返回：
   - viewed_flag
   - viewed_at
   - last_viewed_at
   - view_count
   - viewer_name
   - viewer_userid
   - evidence_summary
2. 修改 static/scripts/modules/patient_qc.js 和 static/templates/pages/patient_qc.html 展示这些字段。
3. 暂时不要重构主 status 枚举，只展示查看状态字段。

六、测试
必须补：
1. tests/test_relay_alert_service.py：
   - request_json 有 department 时 payload.dept 正确。
   - Oracle dept info fallback 正确。
   - Oracle attending doctor fallback 正确。
   - _build_payload 包含 dept/doctor/evidence_summary。
2. tests/test_mobile_qc.py：
   - token 无效不记录 viewed。
   - 第一次详情 viewed_flag=1、view_count=1。
   - 第二次详情 view_count=2、viewed_at 不变、last_viewed_at 更新。
   - viewer_userid/viewer_name query 参数写入。
   - secret 为空时不 fallback source。
3. tests/test_alert_evidence_service.py：
   - legacy medical_documents/nursing_records。
   - lab/exam/progress/nursing context。
   - structured_input 优先。
4. tests/test_patient_qc_relay_alert_logs.py：
   - 后台列表返回查看状态和 evidence_summary。
5. 运行：
   - python -m compileall app tests scripts
   - python scripts/check_naming_convention.py
   - python -m pytest tests/test_relay_alert_service.py tests/test_mobile_qc.py tests/test_alert_evidence_service.py -q --tb=short
   - python -m pytest -q --tb=short

七、需要前置机确认
请最终列出：
1. 前置机模板用 dept 还是 dept_name。
2. 是否显示 doctor_name。
3. 是否显示 evidence_summary。
4. 是否能保留 detail_url query string。
5. 是否能追加 viewer_userid/viewer_name，或通过 X-WeCom-UserId/X-WeCom-UserName header 透传。
6. 是否接受 payload 中的 evidence_titles 嵌套 JSON；若不能，后端应只发送 evidence_summary。
```
