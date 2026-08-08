# 中继与医生端 H5 契约

> 来源合并：`QC_SYSTEM_MOBILE_FEATURE.md`、`PATIENT_QC_AND_RELAY_ALERT_PLAN.md` 和已核验实现。

## 告警投递

- 高危维度由 `RelayAlertService` 生成 `QCRecordAlertLog` 并使用 HMAC 请求前置机。
- 签名：`HMAC_SHA256(secret, "{timestamp}.{raw_body}")`，请求头为 `X-Relay-Timestamp`、`X-Relay-Signature`。
- 同一 `(push_log_id, dimension_code)` 必须幂等；前置机失败不能改变 Dify 主推送成功状态。
- `QCRecordAlertLog.status` 只表达投递状态，不表达医生反馈状态。

## H5 链路

- H5：`GET /mobile/qc/{alert_id}`。
- 详情：`GET /api/mobile/qc-detail/{alert_id}?token=...`。
- 反馈：`POST /api/mobile/qc-feedback`。
- token 格式：`{alert_id}.{expire_ts}.{signature}`；当前使用链接授权，token 不落库。
- 单个 `alert_id` 最多提交一次反馈；重复提交返回 409。

## 身份与查看记录

- token 校验成功后才可更新查看状态、次数、查看人、IP 和 User-Agent。
- 可从 query `viewer_userid/viewer_name` 或前置机透传头 `X-WeCom-UserId/X-WeCom-UserName` 获取身份。
- 企业微信 OAuth 未完成真实端到端验收前，外链必须保留 token 直通能力，不能以 OAuth 失败阻断详情页。

## 运行地址

公网与 APISIX/relay 的准确当前状态以 `104_PORT_AND_ROUTE_MAPPING.md`、项目 `AGENTS.md` 和部署配置为准；端口变化后必须同步三处文档。
