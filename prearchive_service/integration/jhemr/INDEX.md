# 联调包 INDEX（prearchive_service/integration/jhemr/）

> 登记义务：本目录新增/改名/删除文件时同步更新本 INDEX（046 §T7 联调包约定）。

| 文件 | 用途 | 机器校验 |
| --- | --- | --- |
| `README.md` | 启动说明、接口清单、客户端约定、能力级别、安全边界 | tests/test_pa_integration_package.py |
| `INDEX.md` | 本文件（包内登记） | 同上 |
| `openapi.json` | 外部五接口 OpenAPI 3.0 契约（含 redeem 载体） | 同上 |
| `schemas/submission-check-summary.schema.json` | GET 检查结果完整 T7.1 schema（计数单位/守恒/分母 null） | 同上 |
| `examples/test-samples.json` | 纯 TEST 请求/响应样例（虚构 TEST000x 患者，零 PHI） | 同上 |
| `mock_client.py` | 纯标准库 Mock 客户端（签名实现+五接口+L1 演示 main） | 同上（签名与主服务逐字节对拍） |
| `SIGNATURE_VECTORS.json` | 确定性签名向量（对拍源=tests/test_jhemr_integration.py） | 同上 |
| `ERROR_CODES.md` | 错误码与展示语义（不伪装已检查/已通过） | — |
| `FIELD_MAPPING.md` | JHEMR ↔ Med-Audit 字段对照表 | — |

外部测试（主服务侧）：`tests/test_jhemr_integration.py`；
内部测试（预检侧）：`prearchive_service/tests/test_pa_jhemr_check.py`；
包契约测试：`prearchive_service/tests/test_pa_integration_package.py`。
