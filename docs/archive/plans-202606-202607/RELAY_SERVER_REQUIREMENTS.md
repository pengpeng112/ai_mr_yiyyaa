# 前置机开发需求 - 医生端查看与反馈

## 一、目标

病历质控系统发现高危问题后，继续向前置机 `10.20.1.153:3000` 推送告警。前置机需要把企业微信消息升级为可点击的图文消息，并把医生点击后的 H5 页面请求反向代理到内网质控系统。

短期快速方案不做 HTTPS 证书，使用 HTTP：

```
http://10.20.1.153:3000/qc-detail/{alert_id}?token={token}
```

注意：手机必须能访问 `10.20.1.153`。如果医生在院外 4G/5G 无法访问该内网 IP，后续仍需要域名、专线/VPN 或 HTTPS 网关。

## 二、前置机边界

前置机只负责三件事：

1. 接收质控系统推送的 payload，并按现有 HMAC 签名校验。
2. 如果 payload 包含 `detail_url`，转发企业微信图文消息；否则回退旧的纯文本消息。
3. 代理医生手机访问 H5 页面和反馈 API。

前置机不负责生成 token，不负责判断 token 是否有效，不负责保存反馈数据。

## 三、企业微信消息升级

### 3.1 输入 payload 示例

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

### 3.2 转发逻辑

```
if payload.detail_url 存在:
    使用企业微信 news 图文消息
    article.url = payload.detail_url
else:
    使用旧版 text 纯文本消息
```

### 3.3 企业微信 news 示例

```json
{
  "touser": "003966",
  "msgtype": "news",
  "agentid": 1000001,
  "news": {
    "articles": [
      {
        "title": "【病历质控】心内科 李某某 - 诊断一致性",
        "description": "入院诊断与出院诊断不一致\n严重度：高危\n闭环时限：24小时\n\n点击查看详情并反馈",
        "url": "http://10.20.1.153:3000/qc-detail/12345?token=12345.1717000000.a1b2c3d4e5f67890a1b2c3d4e5f67890",
        "picurl": ""
      }
    ]
  }
}
```

### 3.4 建议标题与描述

标题：

```
【病历质控】{dept} {patient_name} - {document_type}
```

描述：

```
{problem}
严重度：{severity}
闭环时限：{closure_hours}小时

点击查看详情并反馈
```

## 四、H5 页面与 API 代理

### 4.1 路由规则

| 前置机路径 | 方法 | 转发目标 | 说明 |
|---|---|---|---|
| `/qc-detail/:id` | GET | `http://10.10.8.84:8000/mobile/qc/:id` | H5 页面，必须透传 query token |
| `/qc-api/qc-detail/:id` | GET | `http://10.10.8.84:8000/api/mobile/qc-detail/:id` | 获取质控详情 JSON |
| `/qc-api/qc-feedback` | POST | `http://10.10.8.84:8000/api/mobile/qc-feedback` | 提交反馈 |

### 4.2 Node.js 推荐实现

使用 `http-proxy-middleware`，不要直接把完整 target 拼进去后再保留原 path，否则容易转发成重复路径。

```javascript
const { createProxyMiddleware } = require('http-proxy-middleware');

const INTERNAL_BASE_URL = 'http://10.10.8.84:8000';

app.use('/qc-detail', createProxyMiddleware({
  target: INTERNAL_BASE_URL,
  changeOrigin: true,
  pathRewrite: {
    '^/qc-detail': '/mobile/qc'
  },
  proxyTimeout: 10000,
  timeout: 10000
}));

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

### 4.3 nginx 示例

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

## 五、前置机配置

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

## 六、安全要求

| 项目 | 要求 |
|---|---|
| 路径白名单 | 只代理 `/qc-detail/*` 和 `/qc-api/*` |
| Token | 前置机只透传，质控系统验证 |
| Rate limit | 建议每 IP 每分钟最多 10 次；第一版可先记录日志，后续开启限制 |
| 超时 | 代理超时 10 秒 |
| HTTPS | 第一版使用 HTTP 快速上线；正式外网访问再切换 HTTPS + 域名 |

## 七、验收标准

- [ ] 旧 payload 无 `detail_url` 时仍能发送纯文本消息。
- [ ] 新 payload 有 `detail_url` 时发送企业微信 news 图文消息。
- [ ] 医生点击图文消息能打开 `http://10.20.1.153:3000/qc-detail/{id}?token=...`。
- [ ] `/qc-detail/*` 能正确代理到质控系统 H5 页面。
- [ ] `/qc-api/qc-detail/*` 能正确获取质控详情数据。
- [ ] `/qc-api/qc-feedback` 能正确提交反馈。
- [ ] 质控系统返回 401/404/409 时，前置机原样返回给 H5 页面。
- [ ] 质控系统不可用时，前置机 10 秒内返回错误，不长时间挂起。
