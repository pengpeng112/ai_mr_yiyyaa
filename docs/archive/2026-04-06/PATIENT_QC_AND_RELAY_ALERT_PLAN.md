# 患者质控总览与高危问题前置机推送开发计划

## 目标

新增两个独立能力，要求不破坏现有推送、日志、反馈和导出功能：

1. 新增“患者质控总览”页面：以 `患者ID + 住院次 + 科室` 为中心，合并展示同一患者本次住院的所有质控结果，便于临床查阅。
2. 新增高危问题实时推送前置机：当质控结果 `severity == "high"` 时，将每个高危维度作为一条消息推送到前置机接口，由前置机转发企业微信。

## 已确认需求

### 患者质控总览

- 不改动现有“质控反馈”页面。
- 新建独立页面，可参考质控反馈样式。
- 按 `patient_id + visit_number + dept` 聚合。
- 一个患者的所有审计类型、所有推送日志、所有维度结果合并展示。

### 前置机推送

- 医生字段来源：业务 SQL 已增加 `管床医师编号`、`管床医师`。
- 前置机地址：`http://10.20.1.153:3001`
- 前置机接口：`POST /qc-record-alert`
- 完整 URL：`http://10.20.1.153:3001/qc-record-alert`
- 只推送 `severity == "high"`。
- 同一患者多个高危维度：按维度推多条。
- 推送失败重试：3 次。
- 历史高危问题：暂不补推，只处理实时新增结果。

## 一、患者质控总览开发设计

### 1. 后端接口

新增文件：

```text
app/routers/patient_qc.py
```

在 `app/main.py` 注册：

```python
app.include_router(patient_qc.router, prefix="/api/patient-qc", tags=["patient-qc"])
```

### 1.1 患者聚合列表接口

```http
GET /api/patient-qc/patients
```

查询参数：

```text
patient_id?: string
patient_name?: string
admission_no?: string
visit_number?: string
severity?: high|medium|low
audit_type_code?: string
status?: pending|processing|resolved|ignored
date_from?: yyyy-mm-dd
date_to?: yyyy-mm-dd
page?: int
limit?: int
```

返回结构：

```json
{
  "total": 123,
  "items": [
    {
      "patient_id": "01029768",
      "visit_number": "0497450",
      "patient_name": "候吉森",
      "admission_no": "ZYxxx",
      "dept": "耳鼻喉科",
      "latest_push_time": "2026-05-26 10:30:00",
      "audit_type_count": 3,
      "push_log_count": 6,
      "issue_count": 5,
      "high_count": 1,
      "medium_count": 3,
      "low_count": 1,
      "pending_count": 2,
      "resolved_count": 1,
      "highest_severity": "high",
      "alert_level": "red"
    }
  ]
}
```

### 1.2 患者详情接口

```http
GET /api/patient-qc/patient-detail
```

查询参数：

```text
patient_id: string
visit_number: string
```

返回结构：

```json
{
  "patient": {
    "patient_id": "01029768",
    "visit_number": "0497450",
    "patient_name": "候吉森",
    "admission_no": "ZYxxx",
    "dept": "耳鼻喉科",
    "admission_date": "",
    "discharge_date": "",
    "admission_diagnosis": "",
    "discharge_main_diagnosis": "",
    "admission_dept_name": "",
    "discharge_dept_name": "",
    "surgery": ""
  },
  "summary": {
    "audit_type_count": 3,
    "push_log_count": 6,
    "issue_count": 8,
    "high_count": 1,
    "medium_count": 4,
    "low_count": 3,
    "pending_count": 2,
    "resolved_count": 1,
    "highest_severity": "high"
  },
  "audit_groups": [
    {
      "audit_type_code": "frontpage_surgery_diagnosis_vs_first_progress",
      "audit_type_name": "病案首页手术诊断 vs 首次病程",
      "latest_push_time": "2026-05-26 10:30:00",
      "overall_conclusion": "xxx",
      "overall_qc_summary": "xxx",
      "severity": "low",
      "alert_level": "blue",
      "logs": [
        {
          "push_log_id": 123,
          "push_time": "2026-05-26 10:30:00",
          "status": "success",
          "parse_status": "success",
          "parse_error": "",
          "overall_conclusion": "xxx",
          "dimensions": [
            {
              "dimension_code": "diagnosis_consistency",
              "dimension_name": "诊断一致性",
              "status": "pass",
              "severity": "low",
              "issue_summary": "",
              "medical_evidence": [],
              "nursing_evidence": [],
              "recommendation": ""
            }
          ],
          "feedback": {
            "status": "pending",
            "feedback_text": "",
            "assigned_to_name": ""
          }
        }
      ]
    }
  ]
}
```

### 2. 数据来源与聚合规则

主要表：

- `PushLog`
- `AuditConclusion`
- `AuditDimensionResult`
- `QCFeedback`
- `QCFeedbackHistory`
- `User`
- `Department`

患者快照复用：

```python
from app.services.patient_snapshot import extract_patient_snapshot
```

分组 key：

```text
patient_id + visit_number + dept
```

`dept` 取值优先级：

1. `PushLog.dept`
2. `extract_patient_snapshot(log)["dept_name"]`
3. `request_json.patient_info.dept`
4. 空字符串

严重度排序：

```python
severity_rank = {"high": 3, "medium": 2, "low": 1, "": 0, None: 0}
```

问题维度判断建议：

```python
is_issue = (
    dimension.status in {"fail", "warning", "risk"}
    or dimension.severity in {"high", "medium"}
    or bool(dimension.issue_summary)
)
```

### 3. 前端页面

新增文件：

```text
static/templates/pages/patient_qc.html
static/scripts/modules/patient_qc.js
static/styles/pages/patient_qc.css
```

可复用质控反馈页面样式，但不要改 `feedback` 页面行为。

页面结构：

- 筛选区：患者ID、姓名、住院号、住院次、科室、严重度、审计类型、推送时间范围、状态。
- 患者聚合表格：展示每个患者本次住院总体风险。
- 详情抽屉：`el-drawer` 展示患者完整质控结果。
- 详情内按审计类型分组，审计类型下按 push log 展示结论、维度、证据、建议和反馈状态。

菜单建议：

```text
患者质控总览
```

路由 key 建议：

```text
patient-qc
```

## 二、高危问题前置机推送开发设计

### 1. 配置

在 `config/config.json.template` 增加：

```json
"relay_alert": {
  "enabled": false,
  "base_url": "http://10.20.1.153:3001",
  "endpoint": "/qc-record-alert",
  "secret_key_enc": "",
  "timeout_seconds": 10,
  "severity_levels": ["high"],
  "source": "病历质控系统",
  "max_retry": 3,
  "retry_backoff_seconds": 5
}
```

注意：

- `secret_key_enc` 必须加密保存，不要明文落配置。
- 复用现有配置加密能力：`encrypt_value` / `decrypt_value`。
- 第一版可只支持配置文件，不强制做 UI 配置。

### 2. 数据库模型

新增模型：

```python
class QCRecordAlertLog(Base):
    __tablename__ = "qc_record_alert_log"

    id = Column(Integer, primary_key=True)
    push_log_id = Column(Integer, index=True, nullable=False)
    dimension_code = Column(String(100), default="", index=True)
    patient_id = Column(String(64), default="", index=True)
    visit_number = Column(String(64), default="")
    dept = Column(String(128), default="")
    severity = Column(String(32), default="")
    alert_level = Column(String(32), default="")
    payload_json = Column(Text, default="")
    status = Column(String(32), default="pending")
    retry_count = Column(Integer, default=0)
    last_error = Column(Text, default="")
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now)
```

唯一约束建议：

```text
push_log_id + dimension_code
```

如果是结论级兜底推送，使用：

```text
dimension_code = "__conclusion__"
```

项目没有 Alembic，必须同步修改：

- `app/models.py`
- `app/database.py` 手动建表/迁移
- `_verify_required_schema()` 增加校验
- SQLite / Oracle 都要兼容

### 3. 推送触发时机

推荐触发点：结构化审计结果保存后。

相关链路：

- 串行：`app/services/push_executor.py`
- 并发：`app/services/bulk_push_executor.py`
- 两者最终都会写 `PushLog` 并调用 `_save_audit_results()`。

建议实现方式：

1. Dify 推送成功并保存 `PushLog`。
2. `_save_audit_results()` 保存 `AuditDimensionResult` / `AuditConclusion`。
3. 调用 `RelayAlertService.enqueue_high_severity_alerts(push_log_id)` 生成待发送记录。
4. 调用 `RelayAlertService.dispatch_pending(limit=N)` 发送 pending 记录。

隔离要求：

- 前置机推送失败不能影响 Dify 主推送成功状态。
- 前置机推送异常必须捕获，只写日志和 `QCRecordAlertLog.last_error`。
- bulk 大量推送时避免每条阻塞太久，`timeout_seconds` 使用配置，默认 10 秒。

### 4. 发送条件

第一版只处理实时新增结果，不处理历史补推。

维度级推送：

```python
dimension.severity == "high"
```

且建议同时要求：

```python
dimension.status in {"fail", "warning", "risk"} or dimension.issue_summary
```

如果没有维度明细，但结论为高危，可兜底推送一条结论级 alert：

```python
conclusion.severity == "high"
```

### 5. 前置机 payload 映射

接口：

```http
POST /qc-record-alert
Content-Type: application/json
X-Relay-Timestamp: 1710000000
X-Relay-Signature: HMAC_SHA256(RELAY_SECRET_KEY, "{timestamp}.{raw_body}")
```

请求体：

```json
{
  "event": "record_qc_issue",
  "doctor_id": "D00123",
  "doctor_name": "张医生",
  "dept": "心内科",
  "patient_name": "李某某",
  "admission_no": "ZY202405260001",
  "document_type": "首次病程记录",
  "problem": "入院后8小时内未完成首次病程记录",
  "problem_code": "FIRST_COURSE_TIMEOUT",
  "alert_level": "yellow",
  "severity": "medium",
  "occurred_at": "2026-05-26 10:30:00",
  "source": "病历质控系统"
}
```

字段映射：

| 前置机字段 | 系统字段来源 |
|---|---|
| `event` | 固定 `record_qc_issue` |
| `doctor_id` | `request_json.patient_info.管床医师编号` / `request_json.patient_info.doctor_id` / 源记录 `管床医师编号` |
| `doctor_name` | `request_json.patient_info.管床医师` / `request_json.patient_info.doctor_name` / 源记录 `管床医师` |
| `dept` | `PushLog.dept` 或 `patient_snapshot.dept_name` |
| `patient_name` | `PushLog.patient_name` 或 patient snapshot |
| `admission_no` | `PushLog.admission_no` 或 patient snapshot |
| `document_type` | `dimension.dimension_name`，或从 `medical_evidence` / `raw_sections` 尝试提取文书类型 |
| `problem` | `dimension.issue_summary`，为空则 `dimension.explanation`，再为空用 `conclusion.overall_conclusion` |
| `problem_code` | `dimension.dimension_code` |
| `alert_level` | `dimension.alert_level` 或 `conclusion.alert_level` |
| `severity` | `dimension.severity` |
| `occurred_at` | `PushLog.push_time`，格式 `%Y-%m-%d %H:%M:%S` |
| `source` | 配置项 `relay_alert.source` |

### 6. HMAC 签名

新增工具函数：

```python
import hmac
import hashlib
import json
import time


def build_signed_request(payload: dict, secret: str):
    raw_body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    timestamp = str(int(time.time()))
    message = timestamp.encode("utf-8") + b"." + raw_body
    signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Relay-Timestamp": timestamp,
        "X-Relay-Signature": signature,
    }
    return raw_body, headers
```

注意：签名使用的 `raw_body` 必须和实际发送的 HTTP body 完全一致。

### 7. 服务类

新增文件：

```text
app/services/relay_alert_service.py
```

建议接口：

```python
class RelayAlertService:
    def __init__(self, db: Session, config: dict):
        ...

    def enqueue_high_severity_alerts(self, push_log_id: int) -> int:
        """根据 push_log_id 读取结论和维度，生成待发送 alert log。返回新增数量。"""

    def dispatch_pending(self, limit: int = 100) -> dict:
        """发送 pending/failed 且 retry_count < max_retry 的 alert。"""

    def send_one(self, alert_log: QCRecordAlertLog) -> bool:
        """签名并 POST 到前置机。"""
```

### 8. 幂等与重试

幂等：

- 按 `push_log_id + dimension_code` 防重复生成。
- 已 `success` 的不再重复发。

重试：

- 失败更新：`status="failed"`、`retry_count += 1`、`last_error`。
- 成功更新：`status="success"`、`sent_at=datetime.now()`。
- 最大重试：配置 `max_retry=3`。

### 9. 日志

新增 logger：

```python
logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("audit.relay_alert")
```

关键日志：

- 生成 alert log 数量
- 发送成功
- 发送失败及 HTTP status/body 摘要
- 配置未启用时跳过
- secret 未配置时跳过并 warning

## 三、回归保护点

必须保证：

1. 现有“质控反馈”页面不改数据结构、不改接口行为。
2. Dify 推送成功不因前置机失败变失败。
3. Bulk 推送不因前置机慢或异常大面积阻塞。
4. 不改变 `PushLog.status` 的既有语义。
5. 不改变 `parse_status` / `parse_error` 的既有语义。
6. 不重复推送同一个 `push_log_id + dimension_code`。
7. `secret_key` 不明文写入日志或配置。
8. SQLite 和 Oracle 初始化/迁移都能通过。

## 四、测试计划

### 后端单元测试

新增测试文件建议：

```text
tests/test_patient_qc_api.py
tests/test_relay_alert_service.py
```

覆盖：

- 患者聚合列表按 `patient_id + visit_number + dept` 合并。
- 患者详情按审计类型分组。
- 高危维度生成多条 alert log。
- 非 high 不生成 alert。
- 已生成/已成功的不重复生成。
- HMAC 签名使用 `{timestamp}.{raw_body}`。
- 前置机 200 成功更新 status。
- 前置机非 2xx 或异常时记录失败且不抛出到主推送链路。

### 命令

```bash
python -m compileall app tests scripts
python -m pytest tests/test_relay_alert_service.py -q
python -m pytest tests/test_patient_qc_api.py -q
python -m pytest tests/test_push_executor.py -q
```

受当前环境影响，如果缺少 `passlib`，涉及 auth/router 的测试可能无法收集，需要先安装：

```bash
pip install -r requirements.dev.txt
```

## 五、实施顺序

### 第一阶段：患者质控总览

1. 新增 `patient_qc.py` router。
2. 实现 `/api/patient-qc/patients`。
3. 实现 `/api/patient-qc/patient-detail`。
4. 新增前端页面、模块、样式和菜单。
5. 做详情 drawer，按审计类型聚合展示。
6. 增加基础测试。

### 第二阶段：高危前置机推送

1. 新增 `relay_alert` 配置模板。
2. 新增 `QCRecordAlertLog` 模型和 DB 初始化/迁移。
3. 实现 `relay_alert_service.py`。
4. 接入 `_save_audit_results()` 后的 enqueue/dispatch。
5. 加 HMAC 签名。
6. 加失败重试和幂等控制。
7. 增加测试。

### 第三阶段：可选增强

1. 配置页面支持前置机 base_url/secret 测试。
2. 新增前置机推送日志页面。
3. 支持历史高危补推。
4. 支持医生字段映射可配置化。

## 六、给其他 AI 的执行提示词

请在当前项目中实现“患者质控总览”和“高危问题前置机推送”两个功能，严格遵守以下要求：

1. 不改动现有“质控反馈”页面行为，新建独立“患者质控总览”页面。
2. 患者质控总览按 `patient_id + visit_number + dept` 聚合，合并展示同一患者所有审计类型、所有推送日志、所有维度结果和反馈状态。
3. 后端新增 `/api/patient-qc/patients` 和 `/api/patient-qc/patient-detail`，复用 `extract_patient_snapshot(push_log)` 补全患者信息。
4. 前端新增 `patient_qc` 模块、模板和样式，使用列表 + drawer 详情方式展示。
5. 新增 `relay_alert` 配置，前置机地址为 `http://10.20.1.153:3001`，接口为 `/qc-record-alert`。
6. 只推送 `severity == "high"` 的实时新增质控问题。
7. 同一患者多个高危维度按维度推多条，不合并。
8. 医生字段使用 `管床医师编号` 映射到 `doctor_id`，`管床医师` 映射到 `doctor_name`。
9. 前置机请求使用 HMAC_SHA256 签名，签名串为 `{timestamp}.{raw_body}`，请求头为 `X-Relay-Timestamp` 和 `X-Relay-Signature`。
10. 新增 `QCRecordAlertLog` 表记录每条前置机推送，按 `push_log_id + dimension_code` 幂等，失败最多重试 3 次。
11. 前置机推送失败不能影响 Dify 主推送结果，必须捕获异常并写日志。
12. 项目没有 Alembic，新增模型后必须同步修改 `app/database.py` 的 SQLite/Oracle 初始化、迁移和 schema 校验。
13. 不要明文保存或打印 relay secret。
14. 增加必要测试，至少覆盖患者聚合、alert 生成、HMAC 签名、重试和不重复推送。

开发完成后运行：

```bash
python -m compileall app tests scripts
python -m pytest tests/test_relay_alert_service.py -q
python -m pytest tests/test_patient_qc_api.py -q
python -m pytest tests/test_push_executor.py -q
```

如果测试环境缺少 `passlib`，先按项目说明安装 `requirements.dev.txt`。
