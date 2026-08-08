# 质控系统开发需求 - 医生端 H5 页面与反馈接口

## 一、目标

医生收到企业微信质控提醒后，可以点击消息进入手机端页面，查看具体质控问题，并提交三类反馈：

- 已知晓
- 已处理
- 其他原因（需要输入说明）

本需求只负责质控系统侧开发。前置机侧负责企业微信图文消息和反向代理。

短期快速方案使用 HTTP，不配置 HTTPS 证书：

```
http://10.20.1.153:3000/qc-detail/{alert_id}?token={token}
```

## 二、总体架构

```
企业微信图文消息
    │ 点击 detail_url
    ▼
前置机 10.20.1.153:3000
    │ 反向代理
    ▼
质控系统 10.10.8.84:8000
    │
    ├─ GET  /mobile/qc/{alert_id}             H5 页面
    ├─ GET  /api/mobile/qc-detail/{alert_id}  详情 JSON
    └─ POST /api/mobile/qc-feedback           提交反馈
```

## 三、关键设计修正

### 3.1 反馈必须按 alert 维度记录

前置机告警是按 `QCRecordAlertLog` 维度级推送的。同一个 `PushLog` 可能有多个高危维度，因此不能只按 `push_log_id` 复用 `QCFeedback` 判断是否处理，否则医生处理一个维度会误影响其他维度。

新增独立表：`QCAlertFeedback`。

### 3.2 不修改 `QCRecordAlertLog.status` 的语义

`QCRecordAlertLog.status` 继续只表示投递状态：

```
pending | success | failed
```

不要把它改成 `feedback_received`。医生反馈状态由 `QCAlertFeedback.action` 表示。

### 3.3 `detail_url` 是系统保留字段

`alert_id`、`detail_url`、`action_required` 是点击查看功能必需字段，必须始终发送，不受“推送内容可视化配置”的字段开关影响。

### 3.4 Token 不落库

Token 是 bearer token，拿到链接的人即可查看和提交反馈。第一版为快速上线采用“链接即授权”。

Token 通过 HMAC 生成，无状态验证，不保存明文 token。若后续要追溯，可保存 token hash 或 expire_ts，不保存完整 token。

## 四、数据模型

### 4.1 新增表 `QCAlertFeedback`

```python
class QCAlertFeedback(Base):
    """医生端 H5 维度级反馈表"""
    __tablename__ = _table_name("qc_alert_feedback")

    id = _id_column("qc_alert_feedback")
    alert_log_id = Column(Integer, ForeignKey(_foreign_key("qc_record_alert_log")), nullable=False, unique=True, index=True)
    push_log_id = Column(Integer, ForeignKey(_foreign_key("push_log")), nullable=False, index=True)
    dimension_code = Column(String(100), default="", index=True)

    action = Column(String(32), nullable=False, index=True)  # acknowledged | rectified | other
    status = Column(String(32), default="submitted", index=True)

    doctor_id = Column(String(64), default="")
    doctor_name = Column(String(64), default="")
    dept = Column(String(128), default="")

    reason = Column(Text, default="")              # action=other 时填写
    rectification_text = Column(Text, default="")  # action=rectified 时填写

    client_ip = Column(String(64), default="")
    user_agent = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_qc_alert_feedback_push", "push_log_id", "dimension_code"),
    )
```

### 4.2 现有表使用方式

| 表 | 使用方式 |
|---|---|
| `QCRecordAlertLog` | 记录前置机投递状态，作为 H5 详情入口主记录 |
| `PushLog` | 患者、住院号、审计类型、原始请求/响应 |
| `AuditDimensionResult` | 维度级问题详情、建议、证据 |
| `AuditConclusion` | 总体结论、风险评分、推理摘要 |
| `QCAlertFeedback` | H5 医生反馈结果 |

## 五、Token 设计

### 5.1 格式

```
{alert_id}.{expire_ts}.{signature}
```

### 5.2 生成与验证

新增 `app/services/alert_token.py`：

```python
def generate_alert_token(alert_id: int, secret: str, ttl_hours: int = 72) -> str:
    expire_ts = int(time.time()) + ttl_hours * 3600
    msg = f"{alert_id}.{expire_ts}"
    sig = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{alert_id}.{expire_ts}.{sig}"


def verify_alert_token(token: str, secret: str) -> int | None:
    parts = token.split(".")
    if len(parts) != 3:
        return None
    alert_id, expire_ts, sig = parts
    if not alert_id.isdigit() or not expire_ts.isdigit():
        return None
    if int(expire_ts) < int(time.time()):
        return None
    msg = f"{alert_id}.{expire_ts}"
    expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return None
    return int(alert_id)
```

### 5.3 安全约定

- 默认有效期：72 小时。
- 使用应用 `SECRET_KEY` 派生签名密钥或新增 `relay_alert.detail_page.token_secret`。
- 第一版不做企业微信 OAuth，明确采用“链接即授权”。
- 后续若要求确认医生身份，再接入企业微信 OAuth。

## 六、推送 payload 生成流程

当前实现是先构建 payload，再创建 `QCRecordAlertLog`。为了生成 `alert_id/detail_url`，需要调整为两阶段：

```python
# 1. 先构建基础 payload，不含 detail_url
payload = self._build_payload(...)

# 2. 创建 alert log 并 flush，拿到 alert.id
alert = self._create_alert_log(push_log_id, code, patient_info, visit_number, severity, alert_level, payload)
self.db.flush()

# 3. 生成 token 和 detail_url
token = generate_alert_token(alert.id, token_secret, ttl_hours)
detail_url = f"{external_base_url}/qc-detail/{alert.id}?token={token}"

# 4. 追加系统保留字段，并回写 payload_json
payload.update({
    "alert_id": alert.id,
    "detail_url": detail_url,
    "action_required": True,
})
alert.payload_json = _safe_json_dumps(payload)
```

### 6.1 系统保留字段

以下字段必须始终发送，不允许被可视化配置关闭：

| 字段 | 说明 |
|---|---|
| `alert_id` | `QCRecordAlertLog.id` |
| `detail_url` | 医生点击查看的完整 URL |
| `action_required` | 是否需要医生操作，默认 `true` |

`closure_hours` 建议始终发送。如果维度没有闭环时限，则回退到结论闭环时限或空值。

### 6.2 默认 payload 示例

```json
{
  "event": "record_qc_issue",
  "doctor_id": "D00123",
  "doctor_name": "张医生",
  "dept": "心内科",
  "patient_name": "李某某",
  "admission_no": "ZY202405260001",
  "document_type": "诊断一致性",
  "problem": "入院诊断与出院诊断不一致",
  "recommendation": "请核实诊断依据，补充鉴别诊断记录",
  "alert_level": "red",
  "severity": "high",
  "closure_hours": 24,
  "occurred_at": "2026-05-27 12:00:00",
  "source": "病历质控系统",
  "alert_id": 12345,
  "detail_url": "http://10.20.1.153:3000/qc-detail/12345?token=12345.1717000000.a1b2c3d4e5f67890a1b2c3d4e5f67890",
  "action_required": true
}
```

## 七、接口设计

### 7.1 H5 页面

`GET /mobile/qc/{alert_id}`

返回手机端 HTML 页面。页面内 JS 调用前置机代理路径：

```
GET  /qc-api/qc-detail/{alert_id}?token=...
POST /qc-api/qc-feedback
```

如果直接内网调试，可兼容调用：

```
GET  /api/mobile/qc-detail/{alert_id}?token=...
POST /api/mobile/qc-feedback
```

### 7.2 获取详情

`GET /api/mobile/qc-detail/{alert_id}?token={token}`

处理逻辑：

1. 验证 token，得到 alert_id，并确认 token 中 alert_id 与路径 alert_id 一致。
2. 查询 `QCRecordAlertLog`。
3. 查询关联 `PushLog`。
4. 查询对应 `AuditDimensionResult`。
5. 查询 `AuditConclusion`。
6. 查询 `QCAlertFeedback`，判断是否已反馈。

响应示例：

```json
{
  "alert": {
    "id": 12345,
    "patient_name": "李某某",
    "admission_no": "ZY202405260001",
    "dept": "心内科",
    "doctor_name": "张医生",
    "dimension": "诊断一致性",
    "alert_level": "red",
    "severity": "high",
    "closure_hours": 24,
    "created_at": "2026-05-27 12:00:00"
  },
  "dimension_detail": {
    "issue_summary": "入院诊断与出院诊断不一致",
    "recommendation": "请核实诊断依据，补充鉴别诊断记录",
    "explanation": "...",
    "confidence": 0.95,
    "medical_content": "相关病程记录内容...",
    "nursing_content": "相关护理记录内容..."
  },
  "conclusion": {
    "overall_conclusion": "...",
    "risk_score": 85,
    "reasoning_brief": "AI 推理摘要..."
  },
  "feedback": {
    "action": null,
    "reason": "",
    "rectification_text": "",
    "created_at": null
  }
}
```

错误响应：

| 状态码 | 说明 |
|---|---|
| 400 | token 缺失 |
| 401 | token 无效或过期 |
| 404 | alert 不存在 |

### 7.3 提交反馈

`POST /api/mobile/qc-feedback`

请求体：

```json
{
  "alert_id": 12345,
  "token": "12345.1717000000.a1b2c3d4e5f67890a1b2c3d4e5f67890",
  "action": "acknowledged",
  "reason": "",
  "rectification_text": ""
}
```

字段规则：

| action | 说明 | 必填字段 |
|---|---|---|
| `acknowledged` | 已知晓 | 无 |
| `rectified` | 已处理 | `rectification_text` |
| `other` | 其他原因 | `reason` |

处理逻辑：

1. 验证 token，并确认 token 内 alert_id 与请求 alert_id 一致。
2. 查询 `QCRecordAlertLog`。
3. 如果该 `alert_log_id` 已有 `QCAlertFeedback`，返回 409。
4. 写入 `QCAlertFeedback`。
5. 不修改 `QCRecordAlertLog.status`。
6. 返回成功。

响应：

```json
{ "ok": true, "message": "反馈已提交" }
```

错误响应：

| 状态码 | 说明 |
|---|---|
| 400 | 参数缺失或 action 非法 |
| 401 | token 无效或过期 |
| 404 | alert 不存在 |
| 409 | 已反馈过，不可重复提交 |

## 八、H5 页面要求

### 8.1 页面展示

必须展示：

- 患者姓名、住院号、科室、管床医师
- 质控维度、严重度、警示级别、闭环时限
- 问题描述
- 整改建议
- AI 推理摘要（可折叠）
- 相关病程/护理内容（可折叠，内容过长时限制高度）
- 已反馈状态（如果已有反馈）

### 8.2 三个操作

| 按钮 | 行为 |
|---|---|
| 已知晓 | 直接提交 `action=acknowledged` |
| 已处理 | 弹窗输入整改说明，提交 `action=rectified` |
| 其他原因 | 弹窗输入原因说明，提交 `action=other` |

提交成功后页面进入只读状态，显示操作类型、内容和提交时间。

### 8.3 移动端要求

- 原生 HTML/CSS/JS 即可，不强制框架。
- 320px 宽度可用。
- 主操作按钮高度不小于 48px。
- token 过期时显示“链接已过期”。
- 不展示系统内部错误堆栈。

## 九、配置项

`config/config.json.template` 新增：

```json
{
  "relay_alert": {
    "detail_page": {
      "enabled": true,
      "token_ttl_hours": 72,
      "external_base_url": "http://10.20.1.153:3000"
    }
  }
}
```

## 十、实施步骤

1. 新增 `QCAlertFeedback` ORM 模型。
2. 更新 `app/database.py` 手工迁移和 `_verify_required_schema()`。
3. 新增 `app/services/alert_token.py`。
4. 修改 `app/services/relay_alert_service.py`，按两阶段流程生成 `alert_id/detail_url`。
5. 新增 `app/routers/mobile_qc.py`。
6. 在 `app/main.py` 注册 mobile router。
7. 新增 H5 页面、JS、CSS。
8. 更新 `config/config.json.template`。
9. 编译、接口、端到端联调测试。

## 十一、验收标准

- [ ] 推送 payload 始终包含 `alert_id`、`detail_url`、`action_required`。
- [ ] `QCRecordAlertLog.status` 仍只表示投递状态，不被反馈逻辑覆盖。
- [ ] 同一个 alert 只能反馈一次，重复提交返回 409。
- [ ] 同一个 `PushLog` 下多个维度可分别反馈，互不影响。
- [ ] token 72 小时内有效，过期后详情和提交接口均返回 401。
- [ ] H5 页面在企业微信内置浏览器能正常打开。
- [ ] 已知晓、已处理、其他原因三种反馈均能正确写入 `QCAlertFeedback`。
- [ ] 前置机 HTTP 代理路径下可完整完成：企微消息 -> H5 页面 -> 提交反馈。
