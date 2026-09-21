# 错误码与降级行为（046 T7）

HTTP 状态码即错误码（无独立业务码段）；`detail` 为英文短语。

| 状态 | 触发条件 | JHEMR 客户端建议 |
| --- | --- | --- |
| 202 | 检查任务受理（新创建） | 保存 check_id，进入轮询 |
| 200 | 幂等复用既有检查（reused=true） | 直接轮询该 check_id |
| 401 | 签名四件套缺失/错误；client 未知名；timestamp 超出 ±300s；nonce 重放 | 检查签名实现（对拍 SIGNATURE_VECTORS.json）；不要重放 nonce |
| 403 | 票据过期；票据绑定操作者不匹配；终态反馈动作无质控复核权限 | 换新票据；操作者用绑定值；终态动作走质控侧 |
| 404 | 患者/就诊在锚点源不存在；check/issue/ticket 不存在 | 核对 patient_id/visit_number（V_QYBR 口径） |
| 409 | 票据已核销（一次性）；缺陷动作非法/乐观版本冲突/状态机不允许 | 刷新 issue_version 后重试；rectified 后等复检 |
| 422 | 缺必填字段（patient_id/visit_number/submission_id/operator_id） | 补字段 |
| 502 | 预检服务不可达/超时/坏响应（主服务与其他功能不受影响） | 显示"检查暂不可用"，**允许继续提交**（不阻断） |
| 503 | 集成开关关闭（默认）或凭据未配置；BFF 关闭 | 联系 Med-Audit 侧确认开关 |

## 展示语义（不能伪装）

- queued/running：`summary` 全部计数=null 且 `provisional=true` → 显示"检查中，可继续提交"；
- completed 且 `fail_count=0`、`unknown_count=0`：可显示"本次检查未发现缺陷"；
- `unknown_count>0` 或 status=partial：必须显示"部分未检查"，不能用全 0 伪装；
- `rectified` 反馈后 issue.status=**rectifying**（待复检），不是 resolved——机器判定不因医生声明而翻转；
- 复检结果 = 新 `run_revision` 的 GET 视图；旧 revision 数据不回写。
