# 前置机开发提示词

> 将以下内容完整发给前置机开发人员，按要求实现即可。

---

## 你的任务

我是病历质控系统的开发者。现在需要你对前置机（`10.20.1.153:3000`）做两处改动：

1. **企业微信消息升级**：把纯文本通知改为图文消息，医生点击可打开 H5 页面
2. **新增反向代理**：把手机端对 H5 页面和 API 的请求转发到内网质控系统

第一版使用 HTTP，不需要 HTTPS 证书。

---

## 背景信息

- 前置机地址：`10.20.1.153:3000`（你的服务）
- 内网质控系统：`10.10.8.84:8000`（你可访问）
- 前置机到内网：网络可达（已验证推送链路连通）
- 手机到前置机：通过医院内网 Wi-Fi 可达
- 第一版 URL 格式：`http://10.20.1.153:3000/qc-detail/{alert_id}?token={token}`

---

## 改动一：企业微信消息升级

### 现有行为

质控系统向前置机 POST 推送消息，前置机收到后转发企业微信纯文本通知。

### 需要改为

前置机收到推送 payload 后：

- 如果 payload 中有 `detail_url` 字段 → 用企业微信**图文消息（news）**格式发送
- 如果没有 `detail_url` 字段 → 按旧方式发纯文本（兼容）

### 判断逻辑

```javascript
// 伪代码
if (payload.detail_url) {
    // 用 news 格式
    msgtype = "news";
    articles[0].url = payload.detail_url;
} else {
    // 用旧的 text 格式
    msgtype = "text";
}
```

### 图文消息格式

```json
{
  "touser": payload.doctor_id,
  "msgtype": "news",
  "agentid": 你的应用ID,
  "news": {
    "articles": [{
      "title": "【病历质控】{dept} {patient_name} - {document_type}",
      "description": "{problem}\n严重度：{severity}\n闭环时限：{closure_hours}小时\n\n点击查看详情并反馈",
      "url": payload.detail_url,
      "picurl": ""
    }]
  }
}
```

字段取值说明：

| 字段 | 从 payload 中取 |
|---|---|
| touser | `payload.doctor_id` |
| title | `【病历质控】${payload.dept} ${payload.patient_name} - ${payload.document_type}` |
| description | `${payload.problem}\n严重度：${payload.severity}\n闭环时限：${payload.closure_hours}小时\n\n点击查看详情并反馈` |
| url | `payload.detail_url`（原样使用，不要自己拼接） |

### 完整 payload 示例（你收到的）

```json
{
  "event": "record_qc_issue",
  "alert_id": 12345,
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
  "detail_url": "http://10.20.1.153:3000/qc-detail/12345?token=12345.1717000000.a1b2c3d4e5f67890a1b2c3d4e5f67890",
  "action_required": true
}
```

你需要关注的字段：`detail_url`、`doctor_id`、`dept`、`patient_name`、`document_type`、`problem`、`severity`、`closure_hours`。

其余字段可以忽略，HMAC 签名校验逻辑不变。

---

## 改动二：新增反向代理

医生在企业微信点击图文消息后，手机浏览器会访问：

```
http://10.20.1.153:3000/qc-detail/{alert_id}?token={token}
```

你需要把以下三组路径代理到内网质控系统：

| 你这边的路径 | 方法 | 转发到 | 说明 |
|---|---|---|---|
| `/qc-detail/:id` | GET | `http://10.10.8.84:8000/mobile/qc/:id` | H5 页面 |
| `/qc-api/qc-detail/:id` | GET | `http://10.10.8.84:8000/api/mobile/qc-detail/:id` | 获取详情 JSON |
| `/qc-api/qc-feedback` | POST | `http://10.10.8.84:8000/api/mobile/qc-feedback` | 提交反馈 |

**关键要求：**

- 必须透传 query 参数（特别是 `token`）
- POST 请求必须透传 `Content-Type: application/json` 和请求 body
- 代理超时 10 秒
- 只代理以上路径，不要暴露内网其他服务

### Node.js 实现参考

```javascript
const { createProxyMiddleware } = require('http-proxy-middleware');

const INTERNAL_BASE_URL = 'http://10.10.8.84:8000';

// H5 页面代理
app.use('/qc-detail', createProxyMiddleware({
  target: INTERNAL_BASE_URL,
  changeOrigin: true,
  pathRewrite: {
    '^/qc-detail': '/mobile/qc'
  },
  proxyTimeout: 10000,
  timeout: 10000
}));

// API 接口代理
app.use('/qc-api', createProxyMiddleware({
  target: INTERNAL_BASE_URL,
  changeOrigin: true,
  pathRewrite: {
    '^/qc-api': '/api/mobile'
  },
  proxyTimeout: 10000,
  timeout: 10000
}));
```

### nginx 实现参考

```nginx
location /qc-detail/ {
    proxy_pass http://10.10.8.84:8000/mobile/qc/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 10s;
    proxy_read_timeout 10s;
}

location /qc-api/ {
    proxy_pass http://10.10.8.84:8000/api/mobile/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 10s;
    proxy_read_timeout 10s;
}
```

### 代理路径映射示例

```
你收到:  GET /qc-detail/12345?token=abc
转发到:  GET http://10.10.8.84:8000/mobile/qc/12345?token=abc

你收到:  GET /qc-api/qc-detail/12345?token=abc
转发到:  GET http://10.10.8.84:8000/api/mobile/qc-detail/12345?token=abc

你收到:  POST /qc-api/qc-feedback  (body: {...})
转发到:  POST http://10.10.8.84:8000/api/mobile/qc-feedback  (body: {...})
```

---

## 你不需要做的事

以下全部由质控系统侧负责，你不需要处理：

- 生成 token
- 验证 token 是否有效/过期
- 保存反馈数据到数据库
- 拼接 `detail_url`（质控系统已拼好）
- 处理业务逻辑

前置机只做消息转发和路径代理，token 验证和业务逻辑全部在内网质控系统 `10.10.8.84:8000` 处理。

---

## 安全要求

| 要求 | 说明 |
|---|---|
| 路径白名单 | 只代理 `/qc-detail/*` 和 `/qc-api/*`，不要转发其他路径到内网 |
| Rate limit | 建议每 IP 每分钟最多 10 次请求（第一版可先记录日志，后续开启限制） |
| 超时 | 代理超时 10 秒，防止内网服务异常拖慢前置机 |
| HMAC 签名 | 现有签名校验逻辑不变，新接口只是代理透传 |

---

## 验收测试

请按以下步骤验证：

### 测试 1：旧消息兼容

发送一个**没有** `detail_url` 字段的 payload 到 `/qc-record-alert`，确认企业微信收到**纯文本**消息。

### 测试 2：图文消息

发送一个**有** `detail_url` 字段的 payload 到 `/qc-record-alert`，确认企业微信收到**图文消息**，标题和描述正确，点击可跳转。

### 测试 3：H5 页面代理

在手机浏览器直接访问：

```
http://10.20.1.153:3000/qc-detail/12345?token=xxx
```

确认能正常显示质控详情页面（页面由内网 `10.10.8.84:8000` 返回）。

### 测试 4：API 代理

```bash
# 获取详情
curl "http://10.20.1.153:3000/qc-api/qc-detail/12345?token=xxx"

# 提交反馈
curl -X POST "http://10.20.1.153:3000/qc-api/qc-feedback" \
  -H "Content-Type: application/json" \
  -d '{"alert_id":12345,"token":"xxx","action":"acknowledged"}'
```

确认请求能正确到达内网质控系统并返回响应。

### 测试 5：错误透传

内网质控系统返回 401（token 无效）或 404（记录不存在）时，确认前置机把错误原样返回给手机端，而不是返回前置机自己的错误页面。

### 测试 6：超时处理

内网质控系统不可用时，确认前置机在 10 秒内返回错误，不会长时间挂起。

---

## 配置建议

```json
{
  "qc_detail_proxy": {
    "enabled": true,
    "internal_base_url": "http://10.10.8.84:8000",
    "external_base_url": "http://10.20.1.153:3000",
    "timeout_seconds": 10,
    "rate_limit_per_ip_per_minute": 10
  }
}
```

---

## 时间线

- 第一版：HTTP 快速上线，不做 HTTPS
- 后续：如需院外访问，再加域名 + HTTPS 证书 + 企业微信 OAuth 医生身份验证

---

有任何问题随时沟通。
