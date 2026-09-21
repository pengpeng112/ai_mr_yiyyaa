# JHEMR ↔ Med-Audit 集成联调包（046 T7）

> 版本：v1（2026-09-11）；能力级别：**L1 本地 Mock 已验收；L2 真实测试 JHEMR /
> L3 生产试点未开始**。本包可直接交给 JHEMR 开发方对接使用。

## 1. 这个包是什么

Med-Audit 服务端为 JHEMR「提交病历」流程提供的**五个受控 HTTP 接口**的契约、
样例、签名向量、错误码与 Mock 客户端。JHEMR 客户端改造由院方另行安排
（046 §2 Q3），本包只约定服务端契约。

## 2. 接口清单（外部形态，主服务承载）

| # | 接口 | 用途 |
| --- | --- | --- |
| 1 | `POST {BASE}/api/integrations/jhemr/submission-checks` | 提交病历时创建检查任务（幂等，202+check_id） |
| 2 | `GET {BASE}/api/integrations/jhemr/submission-checks/{check_id}` | 查询检查结果（T7.1 完整汇总） |
| 3 | `POST {BASE}/api/integrations/jhemr/view-tickets` | 换取短期一次性详情票据（nonce） |
| 4 | `POST {BASE}/api/integrations/jhemr/issues/{issue_id}/feedback` | 医生反馈（看过/已整改/误报/说明） |
| 5 | `POST {BASE}/api/integrations/jhemr/rechecks` | 整改后复检（同锚点也生成新 revision） |

票据核销 `POST {BASE}/api/integrations/jhemr/view-tickets/{nonce}/redeem`
是第 3 个接口的一次性语义载体（内部目标，JHEMR 打开详情页时由 Med-Audit 侧调用）。

完整请求/响应字段见 `openapi.json` 与 `schemas/`；纯 TEST 样例在 `examples/`。

## 3. 认证（共用签名）

每次请求带四件套头：

```
X-Jhemr-Client-Id:   <约定的服务账号 ID>
X-Jhemr-Timestamp:   <unix 秒>
X-Jhemr-Nonce:       <每请求唯一随机串>
X-Jhemr-Signature:   HMAC-SHA256(secret, client_id\nMETHOD\npath\nsha256(body)\ntimestamp\nnonce)
```

- 签名绑定六要素：client_id、method、path、**请求体 sha256**、timestamp、nonce；
- 时钟偏差上限 ±300 秒；nonce 重放直接 401；
- secret 只在 Med-Audit 主服务环境变量配置，不经 URL/正文传递；
- 服务账号身份 ≠ 医生就诊权限：医生身份由请求体 `operator` 携带并全程审计。

确定性向量（对拍用）见 `SIGNATURE_VECTORS.md`；Python 实现见 `mock_client.py`
（`build_signature`，与主服务 `app/routers/jhemr_integration.py` 逐字节一致）。

## 4. 客户端约定（提交动作的展示逻辑，046 §T7）

1. 提交动作前/过程中调用 1 → 202 → 轮询 2（建议退避 2s/5s/10s，超时 60s）；
2. 已完成：展示缺陷列表与文书引用（`issues[].document_refs`）；零问题=可展示
   "本次检查未发现缺陷"；
3. queued/running：显示"检查中，可继续提交"并后续刷新——**不强制阻断提交**；
4. 源故障（summary.status=unknown / partial）：显示"部分未检查"，不用全 0
   伪装已检查完毕；
5. 医生点"已整改"调 4（action=rectified，进入待复检）→ 质控/系统复检调 5 →
   轮询 2 看新 revision 结果；`rectified` 不会直接把机器判定改成通过；
6. 打开缺陷详情页：调 3 换 nonce → 用 nonce 换登录上下文（redeem，一次性）。

## 5. 启动与本地验收（L1）

```bash
# ① 预检服务（fixtures 合成通道，零真实库）
cd prearchive_service && python run_service.py --fixtures          # :8600

# ② 主服务（BFF 打开）
export PREARCHIVE_ADMIN_ENABLED=true
export PREARCHIVE_ADMIN_BASE_URL=http://127.0.0.1:8600
export PREARCHIVE_ADMIN_TOKEN=<与预检 config admin_api.admin_token 一致>
export PREARCHIVE_ADMIN_SECRET=<与预检 config admin_api.signing_secret 一致>

# ③ JHEMR 集成开关
export JHEMR_INTEGRATION_ENABLED=true
export JHEMR_INTEGRATION_CLIENT_ID=jhemr-demo
export JHEMR_INTEGRATION_HMAC_SECRET=<强随机>
cd .. && uvicorn app.main:app --port 8000

# ④ Mock 客户端跑 L1 全链（提交→轮询→票据→反馈→复检）
python prearchive_service/integration/jhemr/mock_client.py \
    --base http://127.0.0.1:8000 --client-id jhemr-demo --secret <同上> \
    --patient TEST0002 --visit 1
```

L1 自动化验收=本仓库测试：
`prearchive_service/tests/test_pa_jhemr_check.py`（12 用例，预检侧）+
`tests/test_jhemr_integration.py`（13 用例，主服务侧签名/转发/降级）+
`prearchive_service/tests/test_pa_integration_package.py`（本包契约）。

## 6. 能力级别与未完成项

| 级别 | 状态 | 说明 |
| --- | --- | --- |
| L1 本地 Mock | **已验收（2026-09-11）** | 全链路测试绿；fixtured 合成患者 |
| L2 真实测试 JHEMR | 未开始 | 需 JHEMR 开发方接入测试环境后联合验收 |
| L3 生产试点 | 未开始 | 按 046 §8.2 部署阶段与批准单执行 |

## 7. 安全边界

- 主服务默认 `JHEMR_INTEGRATION_ENABLED=false` → 全部 503，零网络；
- 预检侧内部目标受 BFF 白名单精确集合保护
  （`/api/integration/jhemr/*`，见 `app/services/prearchive_admin_client.py`）；
- 集成服务账号仅持有 `prearchive_check_view` + `prearchive_issue_feedback`
  两枚最小权限，无规则/发布/投递管理权限；
- 日志与审计不含病历正文/密钥；患者级资料不出批准环境。
