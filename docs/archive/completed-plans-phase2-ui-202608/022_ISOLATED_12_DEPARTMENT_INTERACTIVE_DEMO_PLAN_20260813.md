# 12 科室隔离交互测试与演示环境实施计划

> 编号：022  
> 编制日期：2026-08-13（Asia/Shanghai）  
> 状态：**本地一次性交付已完成并通过 smoke/showcase 验收；未部署服务器、未修改生产数据库、未触发真实外联**  
> 实施负责人：Codex 主代理负责总体设计、代码修改、复核、集成和交付；Luna 仅承担边界明确的简单盘点、fixture 整理、机械性测试补充和文档一致性检查  
> 目标环境：独立 SQLite、独立配置/日志目录、独立端口、合成患者数据、Mock Dify、Mock Relay  
> 相关基线：`AGENTS.md`、`docs/INDEX.md`、`docs/reference/101_FEATURE_BASELINE.md`、`docs/reference/102_DATA_AND_DIFY_CONTRACTS.md`、`docs/reference/103_RELAY_AND_MOBILE_CONTRACT.md`、`docs/skills/med-audit-codex.md`、`docs/ACTIVE/017_FRONTEND_ARCHITECTURE_MENU_LAYOUT_REMEDIATION_PLAN_20260809.md`、`docs/ACTIVE/020_WP6_CANARY_ACCEPTANCE_BLOCKED_REPORT_20260811.md`

> **023 收口说明（2026-08-13）**：本文件是从属的隔离演示专项，不与 023 并行执行，也不改变生产配置、数据、入口或外部服务。若需再次运行，必须由 023 阶段表登记并满足本文件 Gate；演示通过不得被解释为生产 canary、临床、Dify 或 Relay 验收通过。

---

## 0. 总裁定

本项目不重新开发 Med-Audit 主系统，而是在现有真实前后端、数据库模型、权限体系和闭环接口之上，补充一套可创建、可点击、可验证、可销毁的 12 科室隔离测试环境。

最终演示必须满足：

1. 浏览器访问的是真实 Vue UI Next，不是静态截图集合。
2. 页面调用的是真实 FastAPI API，数据写入独立 SQLite，而不是只用 Playwright 路由拦截。
3. 登录、筛选、分页、详情、反馈、整改、复核、导出和权限隔离均可点击操作并持久化。
4. Dify 和 Relay 通过本地 Mock 服务完成真实 HTTP 契约交互，但不连接任何生产外部服务。
5. 所有患者、病历、告警和反馈内容均为确定性合成数据；所有页面、导出、截图和视频持续显示测试标识。
6. 12 科室是本测试环境的覆盖范围，不自动代表 12 科室已生产上线。
7. 测试结束通过停止独立服务并删除该 `run_id` 的完整环境目录进行恢复；生产数据不需要也不允许回滚。

允许在确有展示缺口时增加演示专用界面，但该界面必须：

- 仅在 `TEST_ISOLATED_MODE=true` 时注册或显示；
- 使用真实 API 和隔离数据库状态；
- 明确标注“Mock/合成测试”，不得仿冒真实企业微信送达页面；
- 不复制、导入或查询任何生产病历；
- 不进入生产默认菜单或生产构建的常规导航。

---

## 1. 背景与当前证据

### 1.1 需求背景

需要按照申报材料描述的功能范围，对系统完成 12 科室、多源质控、推送、查看、反馈、整改、复核及统计的完整测试，并为后续截图和视频录制提供稳定、可重复的可点击环境。

本计划解决的是“系统测试与交互演示数据不足”，不是通过修改生产历史制造应用证明。

### 1.2 2026-08-12/13 只读盘点结论

生产环境只读预检确认：

- 生产容器健康，应用数据库为 Oracle，Uvicorn 单 worker；
- 六类质控已配置，日常增量和出院终末调度启用；
- Relay 告警白名单当前只有“听觉植入科”；
- 生产库存在大规模任务和结构化质控数据，但真实告警与反馈闭环仍为小范围；
- 生产数据不可作为 12 科室交互测试的可重置测试夹具。

本计划不得从生产导出患者级数据作为 seed。生产聚合数据只能用于确定性能包络，不进入演示数据库。

### 1.3 现有代码可复用能力

| 能力 | 可复用位置 | 判定 |
| --- | --- | --- |
| 独立目录 | `app/config.py` 的 `DATA_DIR`、`CONFIG_DIR`、`LOG_DIR`、`CONFIG_TEMPLATE_PATH` | 可复用；环境变量须在首次导入 `app.*` 之前设置 |
| SQLite 建表 | `app/database.py::init_db()` | 可复用 |
| 真实质控链路测试 | `tests/test_e2e_audit_flow_mock.py` | 可复用其 Fake Dify 与落库思路 |
| 标准结果 fixture | `tests/fixtures/v2_full_output.json` 等 | 可复用结构，不复制患者信息 |
| Relay 行为 | `tests/test_relay_alert_service.py` | 可复用契约和状态断言 |
| H5 查看与反馈 | `tests/test_mobile_qc_api.py` | 可复用 token、查看、反馈和重复提交规则 |
| 业务反馈 | `tests/test_qc_feedback_api.py` | 可复用状态流和权限断言 |
| 科室可见性 | `tests/test_patient_qc_export_filters.py`、`tests/test_dept_visibility.py` | 可复用 seed 模式和范围断言 |
| 前端交互 | `frontend/tests/e2e/functional-migration.spec.ts` | 可复用交互路径；API mock 只作为补充测试 |

### 1.4 不能直接使用的现有机制

1. `scripts/quick_start.py`
   - 只有 5 科室和少量反馈；
   - 没有完整维度、结论、告警、H5、执行/尝试和复核数据；
   - 当前向 `PushLog` 传入不存在的 `dept_id`，存在运行失败风险；
   - 不能作为 12 科室测试环境入口，后续应修复或明确废弃其旧造数职责。
2. `app/routers/demo.py`
   - 主要读取现有数据库，不负责建立完整测试数据；
   - 演示登录使用 `user_id=0`，而正常受保护页面需要数据库中真实存在的用户；
   - 不能替代真实 RBAC 登录流程。
3. 仅使用前端 Playwright mock
   - 可以验证布局和局部交互；
   - 不能证明真实 API、权限、数据库状态变化、导出审计和闭环持久化；
   - 不允许作为最终截图/视频环境的唯一后端。

---

## 2. 范围、边界与名词口径

### 2.1 本次实施范围

- 建立独立测试环境生命周期工具：创建、启动、验证、重置、销毁。
- 建立 12 科室、四类角色及科室权限隔离。
- 生成确定性的 PushLog、维度、结论、执行/尝试、调度、告警和双反馈链路数据。
- 建立 Mock Dify 和 Mock Relay，支持正常及故障场景。
- 让现有 UI Next 页面可真实点击、查询、修改并刷新后保持状态。
- 必要时增加仅测试环境可见的“闭环演示中心/Mock 消息中心”。
- 建立自动验收、统计对账、截图清单和 1 分钟视频脚本。
- 建立零外联证明和安全销毁机制。

### 2.2 明确不做

- 不修改生产 Oracle 应用库或业务源 Oracle/Vastbase。
- 不将生产患者正文、患者标识、住院号、姓名或真实告警 payload 复制到测试环境。
- 不扩大生产 `alert_dept_filter`。
- 不向真实 Dify、Relay、企业微信、钉钉、邮件或 webhook 发送测试内容。
- 不触发生产调度、手工推送、历史重跑或高危整改。
- 不把测试统计写成生产应用统计。
- 不为截图制作无法点击、无法追溯状态的纯静态假页面。
- 不使用真实医院工作人员姓名作为合成账号或反馈人。

### 2.3 统一名词

| 名词 | 定义 |
| --- | --- |
| 真实系统能力 | 现有 Vue、FastAPI、SQLAlchemy、RBAC、筛选、导出、反馈、审计等实际代码执行结果 |
| 合成数据 | 由固定规则生成的虚构患者、虚构病历、任务、风险、反馈和操作历史 |
| Mock Dify | 实现 Dify HTTP 输入输出契约的隔离服务，不调用大模型 |
| Mock Relay | 实现 Relay HMAC 和返回契约的隔离服务，不发送企业微信 |
| 测试覆盖科室 | 隔离环境中建立账号、数据、权限并通过验收的科室 |
| 生产上线科室 | 经真实生产配置、人员使用和验收确认的科室；不由本计划产生 |
| 可点击演示 | UI → 真实 API → 隔离数据库/Mock 服务的完整交互，不是预渲染画面 |

---

## 3. 12 科室范围

依据生产中的数据量、专业代表性以及医技/内科/外科覆盖，测试环境固定使用以下 12 个科室名称。名称可与院内真实科室一致，但其中患者、人员和业务记录全部为合成数据。

| 序号 | 科室 | 测试代码 | 侧重场景 |
| ---: | --- | --- | --- |
| 1 | 听觉植入科 | DEMO-D001 | 真实试点同名场景、完整闭环基准 |
| 2 | 帕金森病与头痛头晕专业 | DEMO-D002 | 内科长病程与诊疗演变 |
| 3 | 头颈放疗科 | DEMO-D003 | 放疗阶段记录与风险分级 |
| 4 | 眩晕疾病科 | DEMO-D004 | 专科病程与护理一致性 |
| 5 | 耳内科 | DEMO-D005 | 耳科多文书质控 |
| 6 | 炎症性鼻病科 | DEMO-D006 | 入院与首次病程一致性 |
| 7 | 结构性心脏病科 | DEMO-D007 | 围手术期和高风险证据链 |
| 8 | 耳鸣疾病科 | DEMO-D008 | 诊疗过程和护理核查 |
| 9 | 肾脏病血液净化中心 | DEMO-D009 | 检验检查、病程和护理时间轴 |
| 10 | 头颈外科 | DEMO-D010 | 手术链与出院终末质控 |
| 11 | 消化内一科 | DEMO-D011 | 检验异常跟踪与病程响应 |
| 12 | 创伤骨科（手足一组） | DEMO-D012 | 手术部位/侧别和植入物场景 |

科室代码统一使用 `DEMO-*`，防止与生产科室编码混淆。页面展示名称保留科室名称，同时显示“测试科室”标识。

---

## 4. 目标架构

```text
浏览器
  │  http://<host>:18080/ui-next/
  ▼
Demo Med-Audit（真实 Vue + 真实 FastAPI）
  ├─ 独立 SQLite：data/demo/<run_id>/med_audit.db
  ├─ 独立配置：config/demo/<run_id>/config.json
  ├─ 独立日志：logs/demo/<run_id>/
  ├─ Mock Dify ──► 隔离网络内的 mock-dify
  └─ Mock Relay ─► 隔离网络内的 mock-relay

生产 Med-Audit / Oracle / Vastbase / Dify / Relay
  └─ 无网络路径、无挂载、无凭据、无数据复制
```

### 4.1 本地模式

- Demo App：`127.0.0.1:18080`
- Mock Dify：`127.0.0.1:18081`
- Mock Relay：`127.0.0.1:18082`
- 所有 Mock 仅绑定回环地址。
- Demo 配置中的 `relay_alert.detail_page.external_base_url` 固定为 Mock Relay 地址，不允许继承现役配置或代码默认外部域名。

### 4.2 服务器容器模式

- 新增独立 `docker-compose.demo.yml`；
- 使用独立 Compose project，如 `med-audit-demo-<run_id>`；
- 不使用生产的 `network_mode: host`；
- 建立 `internal: true` 的 Demo 网络；
- 只发布 Demo App 的 18080 端口，Mock 服务不发布到宿主机；
- 不挂载 `/opt/med-audit-docker/data|config|logs` 生产目录；
- 不挂载 Oracle Client 网络配置、生产 `.env` 或 Docker socket；
- 资源限制独立设置，避免影响生产容器。

---

## 5. 强制隔离和防误连门禁

### 5.1 启动硬门禁

新增 `TEST_ISOLATED_MODE=true`，启动时必须同时满足：

1. `APP_DB_TYPE=sqlite`；
2. `ENABLE_SCHEDULER=false`；
3. `DATA_DIR`、`CONFIG_DIR`、`LOG_DIR` 均位于允许的 demo 根目录且包含当前 `run_id`；
4. 数据库 URL 不得包含 Oracle、PostgreSQL、Vastbase 或网络主机；
5. Dify/Relay 目标只能是回环地址或显式允许的 Demo 内部服务名；
6. notify 全部禁用；
7. 配置文件中不得出现生产地址：`10.10.8.84`、`10.10.8.177`、`10.20.1.153` 或生产服务名；
8. 不存在生产口令、密文、API Key 或 Secret 的复制值；
9. 页面环境标识必须为 `synthetic_test`；
10. 任一条件不满足，应用启动失败，不允许仅记录 warning 后继续。

另需校验 `relay_alert.detail_page.external_base_url`：本地模式必须指向 `http://127.0.0.1:18082`，容器模式必须指向 Demo 内部 Mock Relay 服务；不得为空、不得使用 `RelayAlertService` 的外部默认值。

环境变量必须在任何 `app.*` import 前设置，因为数据库 engine 和路径常量会在模块导入阶段绑定。

### 5.2 运行期网络门禁

- Oracle/Vastbase 客户端在隔离模式下被 fail-closed；
- Dify、Relay、notify 的目标每次调用前重新校验；
- 禁止 HTTP 重定向到非允许地址；
- Mock 服务记录请求方法、时间、场景、请求哈希和状态，不记录完整病历；
- 自动测试通过 socket/HTTP 拦截证明没有访问允许列表以外的主机；
- 服务器 Demo 网络设置为 internal，形成基础设施层第二道门禁。

### 5.3 数据标识门禁

以下位置必须持续显示“脱敏合成测试数据”：

- 登录页和应用页眉；
- 工作台和详情页；
- H5 告警详情；
- CSV/Excel 导出首列或说明页；
- 打印/报告页；
- Mock 消息中心；
- 截图水印与视频字幕；
- API `/api/demo-test/manifest` 返回值。

患者字段规则：

- `patient_id`：`SYNTH-P-<run_id>-NNNNNN`；
- `patient_name`：`测试患者NNNN`；
- `admission_no`：`SYNTH-A-NNNNNN`；
- 医生/护士/质控员：`测试医生01`、`测试护士01`、`测试质控员01`；
- 所有病历句子由模板生成，不得从生产语料抽取或变形。

---

## 6. 数据规模和确定性规则

### 6.1 三档数据集

| 档位 | 用途 | PushLog | 维度 | 业务反馈 | 告警 | H5反馈 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| smoke | 快速开发/CI | 96（每科8） | 约576 | 24 | 24 | 18 |
| showcase | 截图/视频/功能验收 | 1,200（每科100） | 约6,000–7,200 | 240 | 144 | 96 |
| load | 性能测试 | 50,000，后续可升至200,000 | 300,000起 | 10,000起 | 10,000起 | 5,000起 |

性能档只在功能档通过后执行，默认不自动生成。

### 6.2 Showcase 固定比例

生成器使用固定随机种子和固定基准日期。确定性分为两层：

- 相同 seed 版本、随机种子、基准日期和 `run_id` 必须得到相同业务行及数据库内容；
- 不同 `run_id` 的运行元数据、患者 ID、创建时间和数据库 SHA 可以不同，但去除 `run_id`/时间等运行字段后的状态分布、科室分布和 `dataset_contract_digest` 必须一致。

- 12 科室各 100 条 PushLog；
- 六类质控尽量均衡分布；
- 同时覆盖 `daily_increment` 和 `discharge_final`；
- 状态覆盖 `success`、`failed`、`skipped`；
- 解析覆盖 `success`、`failed`、`fallback`；
- 风险覆盖 high、medium、low、unknown；
- 当前结果和被终末结果 superseded 的历史结果同时存在；
- 复核覆盖 reviewed/unreviewed，少量管理员 `manual_override`；
- skip_reason 至少覆盖 `unreviewed_pending`、`rectified_suppressed`、`empty_lab_exam`、`empty_progress_nursing`、`already_succeeded`；
- 业务反馈 240 条，覆盖 pending、acknowledged、rectified、closed；
- 告警 144 条，覆盖 success、pending、failed、suppressed、dept_filtered；
- H5 反馈 96 条，12 科室各 8 条，覆盖 acknowledged、rectified、other；
- 查看记录覆盖未查看、首次查看、多次查看；
- SchedulerHistory 覆盖六类、双模式、completed/failed/cancelled；
- PushExecution/PushAttempt 覆盖成功、失败重试、跳过和幂等冲突场景。

`dept_filtered` 负例使用空科室或 `DEMO-OUT-OF-SCOPE`，不额外宣称第 13 个测试科室。

### 6.3 数据依赖顺序

生成顺序必须固定：

1. schema / `init_db()`；
2. Role、Permission、RolePermission、RoleMenu；
3. Department、RoleDepartment；
4. User；
5. PushLog；
6. AuditDimensionResult、AuditConclusion；
7. QCFeedback、QCFeedbackHistory；
8. QCRecordAlertLog、QCAlertFeedback；
9. PushExecution、PushAttempt；
10. SchedulerHistory、NotifyLog、ExportAuditLog；
11. manifest 和计数校验。

成功当前结果必须符合现有 `source_record_key + audit_type_code + audit_run_mode` 当前唯一性语义。需要历史版本时，使用正确 supersede 关系，不通过重复键绕过唯一约束。

### 6.4 Manifest

每次创建输出 `manifest.json`，至少包含：

- `run_id`、seed 版本、随机种子、创建时间；
- Git commit 和工作区是否 dirty；
- 12 科室代码和名称；
- 各表预期/实际数量；
- 各状态、严重度、类型和运行模式分布；
- 四角色账号清单（不含明文密码）；
- Mock 服务版本和故障档配置；
- 配置文件 SHA-256、数据库 SHA-256（停服快照时计算）；
- `dataset_contract_digest`：对规范化后的科室、业务序号、类型、状态、严重度和关系结构计算，不包含 `run_id`、创建时间、凭证或文件路径；
- 测试标识文本；
- 截图和视频使用的固定筛选条件。

---

## 7. RBAC 与账号设计

### 7.1 角色

- admin：全院管理、配置查看、测试环境控制台；
- auditor：全院质控查看、抽检和允许的反馈操作；
- dept_manager：仅本科室的患者质控、反馈、统计和允许操作；
- clinician：仅本科室的质控记录、H5/业务反馈处理。

### 7.2 用户数量

- 1 个 admin；
- 1 个 auditor；
- 每科室 1 个 dept_manager；
- 每科室 1 个 clinician；
- 合计至少 26 个真实数据库用户。

密码由创建命令随机生成并写入权限受限的本地 `credentials.txt`，不得进入 Git、manifest、截图或日志。允许额外生成便于录屏的短期凭证，但必须满足现有密码规则，并在销毁环境时一并删除。

### 7.3 必验权限

- admin 可见 12 科室；
- dept_manager/clinician 只能看本科室；
- auditor 的写权限以现有产品契约为准，不擅自扩大；
- 无权限深链返回 403；
- 科室筛选、统计、详情、导出使用相同可见性规则；
- 修改 URL 参数不得越权访问他科记录；
- H5 token 只能访问对应告警，重复反馈返回 409；
- 导出操作写 ExportAuditLog。

---

## 8. Mock Dify 与 Mock Relay

### 8.1 Mock Dify

实现与现有客户端兼容的 `/v1/workflows/run`，要求：

- 接收 `mr_txt` 字符串和 `mr_type`；
- 返回 `data.outputs.aa` 字符串；
- 优先按现有 HTTP `inputs.mr_type` 路由；六类 code 中可能共享 `mr_type`，因此隔离模式可由 `push_to_dify(..., audit_type_code=...)` 额外发送不含患者信息的 `X-Demo-Audit-Type` 请求头完成精确路由；
- `X-Demo-Audit-Type` 只能在 `TEST_ISOLATED_MODE=true` 且目标已通过 Demo allowlist 时添加，非隔离模式不得发送，并需通过契约测试证明生产请求头不变；
- Mock 对 `X-Demo-Audit-Type` 使用六类规范 code 白名单校验，然后返回相应合法固定维度；请求头缺失时才按 `mr_type` 的通用场景返回；
- 生成的证据只能引用合成病历；
- 支持通过请求头或合成记录 scenario 控制故障。

故障档至少包括：

- success；
- timeout；
- HTTP 500；
- 空 outputs；
- 非法 JSON；
- 缺 dimensions/conclusion；
- 重复请求/相同 workflow run；
- 高危门槛合格与不合格。

### 8.2 Mock Relay

实现 `/qc-record-alert`，要求：

- 校验 `X-Relay-Timestamp` 和 `X-Relay-Signature`；
- 正常响应与生产 Relay 契约一致；
- 保存最小请求元数据和不可逆哈希；
- 提供测试环境内部的 Mock 消息列表；
- 实现 `GET /qc-detail/{alert_id}?token=...`，将请求反向代理或 302 到 Demo App 的真实 `/mobile/qc/{alert_id}?token=...`；跳转目标必须仍在 Demo 内部网络；
- 能模拟 success、timeout、HTTP 500、签名错误和重复投递；
- 不发送企业微信、不模仿真实企业微信品牌页面。

只有真实请求成功到达 Mock Relay 后，测试告警才能显示 success。直接 seed 的 success 告警必须在 manifest 中标记为 `seeded_state`；用于端到端验收的告警必须标记为 `mock_http_verified`，两者不得混淆。

端到端验收必须从 Mock 消息列表点击 `detail_url`，确认经过 `/qc-detail` 到达真实 H5 页面且 token 有效；不得直接复制内部 `/mobile/qc` 地址绕过 Relay 路由测试。

### 8.3 合成数据源

手动推送页要能够真实点击，需增加仅隔离模式可用的 fixture data-source adapter：

- 根据日期、科室、质控类型返回合成 bundle；
- 复用现有 `payload_composer → dify_pusher → parser/writer` 链路；
- 不经过 Oracle/PostgreSQL/Vastbase 客户端；
- 非隔离模式注册该 adapter 时必须启动失败；
- 支持正常、缺文书、空检验、重复和时间窗错误场景。

完整接线点必须包含：

1. Demo 配置把 `data_source.type` 明确设为 `fixture`，并完整定义现役六类规范 code：`progress_vs_nursing`、`jyjc_vs_bcnursing`、`syssvsscbc`、`discharge_vs_frontpage`、`admission_vs_first_progress`、`surgery_chain`；
2. `ConfigParser.get_data_source_type()` 仅在隔离模式接受 `fixture`，非隔离模式发现该值立即失败，不能回退成 Oracle；
3. 数据源 schema/枚举和 `AuditTypeRegistry` 校验允许隔离模式 fixture，并继续校验六类 builder、sources、维度及 Dify input/output 契约；
4. `load_patient_bundles()` 在任何 Oracle/PostgreSQL/Vastbase 客户端创建前分发到 fixture adapter；
5. `/api/push/query-preview`、`/api/push/precheck`、`/api/push/manual` 和审计类型数据源测试共用同一分发，不允许某个入口绕回真实数据源；
6. 非隔离模式注册 fixture adapter、出现 fixture 配置或访问 fixture 路由均 fail-closed；
7. 自动测试逐入口断言 Oracle/PostgreSQL/Vastbase 连接函数调用次数为 0。

不能以“先把结果写入 SQLite”代替手动推送页的真实链路测试；直接 seed 用于页面展示，fixture adapter + Mock Dify 用于点击联调，两者均需验收。

---

## 9. 界面策略

### 9.1 优先使用现有真实页面

以下页面必须接真实隔离 API：

1. 登录页；
2. 工作台；
3. 患者质控；
4. 质控记录与详情；
5. 手动推送与推送进度；
6. 告警日志；
7. 反馈工作台；
8. 调度状态（调度禁用但历史可展示）；
9. 权限/账号页面；
10. H5 告警详情与反馈；
11. 导出和打印/报告。

### 9.2 必要时新增的测试专用页面

允许新增“闭环演示中心”，仅在隔离模式出现，包含：

- 当前 `run_id` 和“脱敏合成测试数据”标识；
- 12 科室覆盖矩阵；
- 一条合成问题从生成、Mock 推送、查看、反馈、整改到复核的时间轴；
- Mock 消息收件箱；
- 选择故障档并发起一条合成任务；
- manifest 计数与数据库实际计数对账状态。

该页面不能伪造生产在线人数、企业微信送达回执或临床成效；所有状态必须来自隔离 API/SQLite/Mock 服务。

### 9.3 视觉标识

- 顶部固定橙色环境条；
- 左下角半透明水印；
- 页面标题追加“测试”；
- 合成患者姓名使用统一徽标；
- 导出文件名带 `synthetic_<run_id>`；
- H5 页面顶部提示“消息由 Mock Relay 生成，未发送企业微信”。

---

## 10. 实施工作包

### WP0：冻结基线与实施入口

目标：在不修改业务功能的情况下，确认当前工作区、测试基线和演示入口。

步骤：

1. 记录 `git status`、HEAD、现有未提交修改；不得清理或覆盖。
2. 建立 smoke 测试基线：compileall、聚焦 pytest、前端 typecheck/unit/build。
3. 冻结 12 科室、三档数据量、固定随机种子和环境标识。
4. 检查 18080–18082 或容器端口是否可用。
5. 输出本轮允许修改文件清单。

停止点：基线失败须区分既有失败与本次阻断，不能通过删除测试或放宽断言继续。

### WP1：生命周期 CLI 和隔离门禁

建议新增：

- `scripts/demo_env.py`：`create|serve|stop|verify|verify-absent|reset|destroy|status`；
- `app/demo_support/environment.py`：路径、run_id、出口校验；
- `config/demo/config.json.template`：无生产地址、无生产密文；
- `tests/test_demo_environment_guard.py`；
- 可选 `docker-compose.demo.yml`。

CLI 示例设计：

```powershell
python scripts/demo_env.py create --profile showcase --run-id demo-20260813-01
python scripts/demo_env.py verify --run-id demo-20260813-01
python scripts/demo_env.py serve --run-id demo-20260813-01
python scripts/demo_env.py reset --profile showcase --run-id demo-20260813-01
python scripts/demo_env.py stop --run-id demo-20260813-01
python scripts/demo_env.py destroy --run-id demo-20260813-01 --force
python scripts/demo_env.py verify-absent --run-id demo-20260813-01
```

验收：错误路径、生产地址、Oracle 模式、调度启用或缺少 run_id 时全部 fail-closed。

### WP2：确定性数据生成器

建议新增：

- `app/demo_support/seed.py`；
- `app/demo_support/scenarios.py`；
- `app/demo_support/manifest.py`；
- `tests/test_demo_seed.py`。

实现 smoke/showcase/load 三档，按第 6 节依赖顺序写入。创建必须事务化；失败时删除未完成环境，不留下“部分成功”可被启动。

验收：相同 seed 版本、随机种子和基准日期产生相同规范化计数/分布及 `dataset_contract_digest`；相同 `run_id` 的重置得到相同业务内容；12 科室均有完整数据；所有标识符合 `SYNTH-*`；全库敏感内容扫描不命中已知生产格式或地址。

### WP3：RBAC 与真实登录

1. 使用真实 User/Role/Permission/Department 表；
2. 修复或绕开 `demo.py` 的 user_id=0 旧登录，不为受保护 UI 使用虚假用户；
3. 为 12 科室创建主任和临床账号；
4. 验证四角色菜单、API、深链和跨科隔离；
5. 凭证只保存在 demo run 目录。

停止点：任一普通角色能通过 API/深链读取他科数据，立即停止后续截图和部署。

### WP4：Mock Dify、Mock Relay 与合成数据源

建议新增：

- `app/demo_support/mock_server.py` 或两个最小服务模块；
- `app/services/demo_fixture_source.py`；
- `tests/test_demo_mock_integrations.py`；
- `tests/test_demo_push_flow.py`。

必须真实走 HTTP 到 Mock 服务，并覆盖正常与故障档。Mock 请求日志不得保存完整 `mr_txt` 或病历正文，只保存长度、类型、哈希和结果状态。

本工作包同时完成第 8.3 节列出的配置枚举、AuditTypeRegistry、loader 和四个入口接线；只新增 adapter 文件但没有打通这些分发点，不视为完成。

### WP5：双反馈、查看和复核闭环

分别验证三个概念：

| 链路 | 数据表 | 状态/指标 |
| --- | --- | --- |
| 业务反馈 | QCFeedback / QCFeedbackHistory | pending → acknowledged → rectified → closed |
| Relay/H5反馈 | QCRecordAlertLog / QCAlertFeedback | 发送、查看、acknowledged/rectified/other、重复提交409 |
| 人工复核 | PushLog reviewed/manual_override 字段 | reviewed_at、reviewed_by、权限和统计 |

三条链路的页面、统计和视频话术不得互相替代。需要补充的 API/前端只在现有能力确实缺失时实现，并保持生产语义不变。

### WP6：交互页面与演示专用页面

1. 现有页面接入真实隔离 API；
2. 增加全局测试标识；
3. 如需要，实现“闭环演示中心/Mock消息中心”；
4. 实现从工作台钻取到患者、日志、告警、反馈的路径；
5. 页面刷新后状态保持；
6. 三视口 1366/768/390 验证；
7. 避免为演示改变生产默认入口或菜单。

### WP7：自动验收与零外联证明

实现 `create → serve → verify → destroy → verify-absent` 自动流程。

验证包括：

- 后端 focused pytest；
- `python -m compileall app tests scripts`；
- `python scripts/check_naming_convention.py`；
- 前端 typecheck、unit、build；
- 真实 API smoke；
- 真实后端 Playwright 三视口；
- 12 科室逐项计数；
- API 统计与 SQLite COUNT 对账；
- RBAC 跨科室负例；
- Mock Dify/Relay 故障档；
- H5 重复反馈 409；
- 导出审计和测试水印；
- 进程/网络连接检查，证明无非允许目标访问。

### WP8：服务器隔离部署

进入条件：WP0–WP7 本地通过，用户另行批准服务器测试容器部署。

1. 记录生产容器只读基线，但不重启、不改配置；
2. 使用独立 compose project、目录、端口、网络和容器名；
3. 先运行启动硬门禁和 smoke profile；
4. 再创建 showcase profile；
5. 仅开放经批准的内网访问源；
6. 验证生产容器 digest、启动时间、数据库计数未变化；
7. 记录 Demo 容器和卷的销毁命令。

停止条件：发现任何生产目录挂载、生产地址、生产凭据、外部网络路径或端口冲突，立即停止并销毁未完成 Demo 项目。

### WP9：截图、视频和交付

1. 冻结一个通过验收的 showcase `run_id`；
2. 从 manifest 自动生成数字口径表；
3. 按第 12 节截图清单录制；
4. 视频和截图均保留测试水印；
5. 形成一键重置脚本，录制失败可恢复相同初始状态；
6. 输出环境使用说明、账号交接、验证报告和销毁报告模板。

---

## 11. 功能验收矩阵

| 模块 | 实际操作 | 期望 |
| --- | --- | --- |
| 登录 | 四角色分别登录、刷新、退出 | 使用真实数据库用户，Token 恢复正常 |
| 工作台 | 切换日期/科室/风险并钻取 | 数字与 manifest/SQLite 一致 |
| 患者质控 | 搜索合成患者、分页、查看摘要 | 仅返回角色可见科室 |
| 质控记录 | 查看六类详情和证据 | 证据为合成内容，结构完整 |
| 手动推送 | 选择日期、科室、类型后预检并执行 | fixture adapter → Mock Dify → 真实落库 |
| 推送进度 | 查看成功、失败、跳过、解析失败 | 状态和错误分类准确 |
| 告警 | 触发一条高危合成问题 | 真实请求 Mock Relay，状态 success |
| H5查看 | 用 token 打开详情并多次查看 | view_count 增长、查看人留痕 |
| H5反馈 | 确认/整改/其他 | 首次成功，重复提交 409 |
| 业务反馈 | 确认、整改、关闭 | 历史链完整、状态转换合法 |
| 人工复核 | 管理员/允许角色标记复核 | reviewed 字段和审计正确 |
| 科室隔离 | 主任/医生尝试访问他科 | 菜单隐藏且 API/深链 403 |
| 导出 | 按当前筛选导出 | 记录数一致，含测试标识并写审计 |
| 故障模拟 | Dify/Relay timeout、500、非法响应 | 重试/失败/熔断状态可见且不伪成功 |
| 重置 | 修改若干状态后 reset | 恢复同一 manifest 初始状态 |
| 销毁 | destroy 后访问/查文件 | 服务不可达，run_id 目录不存在 |

---

## 12. 截图和一分钟视频设计

### 12.1 截图清单

每张截图记录：`run_id`、路由、角色、筛选条件、预期数字和文件名。

1. 登录页：测试环境标识；
2. 工作台：12 科室总体分布和风险趋势；
3. 患者质控：合成患者列表和科室筛选；
4. 质控详情：双方合成证据、风险等级和建议；
5. 手动推送：预检结果；
6. 推送进度：成功/失败/跳过状态；
7. Mock 消息中心：Relay 接收记录；
8. H5 详情：查看记录和测试标识；
9. H5 反馈：确认或整改提交成功；
10. 反馈工作台：pending/acknowledged/rectified/closed；
11. RBAC：科室主任只见本科室；
12. 演示中心：闭环时间轴和 manifest 对账通过。

### 12.2 一分钟视频脚本框架

| 时间 | 画面 | 操作/解说重点 |
| --- | --- | --- |
| 0–6秒 | 登录和环境标识 | 说明是12科室脱敏合成交互测试环境 |
| 6–14秒 | 工作台 | 展示多源任务、六类质控和12科室统计 |
| 14–23秒 | 患者质控 → 详情 | 点击合成患者，展示跨文书证据与风险分级 |
| 23–32秒 | 手动推送 → 进度 | 真实调用 fixture adapter 和 Mock Dify |
| 32–42秒 | Mock消息 → H5 | 展示告警接收、打开、查看次数 |
| 42–52秒 | 反馈/整改/复核 | 提交反馈并回到工作台查看状态变化 |
| 52–60秒 | 12科室/RBAC/对账 | 展示科室隔离和 manifest 校验通过 |

视频中不得出现“真实企业微信已送达”“12 科室已生产上线”等表述。推荐解说为：“系统在隔离环境完成 12 科室交互和闭环测试”。

---

## 13. 销毁、恢复与留痕

### 13.1 销毁前提

1. 停止 Demo App 和两个 Mock 服务；
2. 确认目标 `run_id` 与用户输入一致；
3. 使用 `Resolve-Path`/绝对路径校验目标严格位于 `data/demo`、`config/demo`、`logs/demo` 下；
4. 禁止目标为工作区根目录、`data`、`config`、`logs`、用户目录或空路径；
5. 生成最终 manifest、测试报告和可选压缩归档；归档中不含明文凭证。

### 13.2 销毁内容

- SQLite 数据库、WAL、SHM；
- run_id 配置和备份；
- Demo 日志与 Mock 请求元数据；
- 临时凭证；
- 独立容器、网络和命名卷；
- 截图临时缓存（最终选定交付文件除外）。

不得使用现有日志批量删除接口作为回滚方式，因为它不能完整覆盖 Alert、H5、Execution 和 Attempt。恢复应通过销毁整个隔离环境并按同一 seed 重新创建。

### 13.3 生产不变证明

服务器部署前后只读记录：

- 生产容器 ID、镜像 digest、启动时间和 restart count；
- 生产配置 SHA-256；
- 生产应用库类型及关键表聚合计数；
- 生产 Relay 白名单；
- 生产挂载目录。

销毁 Demo 后再次对比。任何差异必须停止并报告，不能把差异解释为 Demo 的正常副作用。

---

## 14. 文件变更预案

实际文件以实施时检索为准，预计范围：

### 新增

- `scripts/demo_env.py`
- `app/demo_support/__init__.py`
- `app/demo_support/environment.py`
- `app/demo_support/seed.py`
- `app/demo_support/scenarios.py`
- `app/demo_support/manifest.py`
- `app/demo_support/mock_server.py` 或独立 Mock 模块
- `app/services/demo_fixture_source.py`
- `config/demo/config.json.template`
- `docker-compose.demo.yml`
- `tests/test_demo_environment_guard.py`
- `tests/test_demo_seed.py`
- `tests/test_demo_mock_integrations.py`
- `tests/test_demo_push_flow.py`
- 前端演示环境标识和可选演示中心组件/测试

### 可能修改

- `app/main.py`：隔离模式门禁和可选测试路由注册；
- `app/config.py`：测试环境路径/标识支持；
- Dify、Relay、notify、Oracle/Vastbase 出口模块：隔离模式 fail-closed；
- `app/routers/demo.py`：修复演示账号语义或缩减为兼容入口；
- `scripts/quick_start.py`：修复过期字段，或改为调用新 CLI；
- UI Next AppShell/Login/H5：测试环境水印；
- `docs/INDEX.md`：实施状态更新；
- 部署说明：仅增加 Demo 独立启动方式，不改变生产命令。

禁止顺带格式化或重写当前工作区其他人的前端改动。文件发生重叠时，逐文件检查 diff 后小块合并。

---

## 15. 风险与控制

| 风险 | 等级 | 控制 |
| --- | --- | --- |
| 误连生产数据库/外部服务 | P0 | 启动硬门禁、运行期 allowlist、internal 网络、零生产挂载 |
| 合成数据被误认为生产证据 | P0 | 全局水印、导出标识、manifest、统一话术 |
| RBAC 跨科泄露 | P0 | UI/API/深链/导出四层负例测试 |
| seed 破坏当前结果唯一索引 | P0 | 使用现役 identity/supersede 语义并自动校验 |
| Demo 页面不可点击 | P1 | 必须真实 API/SQLite；Playwright mock 不计最终验收 |
| Mock success 与真实外发混淆 | P1 | 状态来源字段、Mock消息中心、水印、视频字幕 |
| 旧 demo/quick_start 入口误用 | P1 | 新 CLI 唯一入口；旧入口修复或显式弃用 |
| 销毁范围过宽 | P0 | 双 run_id 确认、绝对路径白名单、停服后删除、verify-absent |
| 大数据造数过慢 | P2 | 批量插入、smoke→showcase→load 分档 |
| 当前 dirty worktree 冲突 | P1 | 不清理、不回滚；只做小块补丁并逐文件复核 |

---

## 16. 验收和完成定义

全部满足后才能宣布完成：

1. 一条命令可创建带 run_id 的隔离环境；
2. 12 科室均有账号、任务、质控结果、告警和反馈测试覆盖；
3. 四类角色可真实登录且科室隔离通过；
4. 手动推送真实经过 fixture adapter、Mock Dify、解析和持久化；
5. 一条高危合成记录真实经过 Mock Relay、H5查看、反馈、整改和复核；
6. 工作台、列表、详情、统计、导出与 SQLite 计数一致；
7. 所有页面和产物包含合成测试标识；
8. 后端、前端、API、Playwright、故障档和零外联测试全部通过；
9. 服务器 Demo 与生产容器、目录、网络和数据库相互隔离；
10. `destroy` 能安全删除整个 run_id 环境且 `verify-absent` 通过；
11. 截图、视频、manifest 和测试报告引用同一 run_id 与相同数字；
12. 文档结论并入现役基线并同步更新 `docs/INDEX.md` 后，才可归档本计划。

---

## 17. 人工批准点与实施顺序

| Gate | 内容 | 当前状态 |
| --- | --- | --- |
| G0 | 本计划、12科室名单和“合成测试”口径 | 待用户确认 |
| G1 | 开始 WP0–WP7 本地开发 | 用户发出“开始开发”后执行 |
| G2 | 使用服务器部署独立 Demo 容器及端口 | 必须另行确认地址、端口和访问范围 |
| G3 | 冻结截图/视频 run_id 和数字 | 本地/服务器验收通过后确认 |
| G4 | 销毁服务器 Demo | 用户确认已完成演示后执行，或按约定到期自动销毁 |

建议顺序：

```text
WP0 基线
  → WP1 隔离门禁/CLI
  → WP2 seed/manifest
  → WP3 RBAC
  → WP4 Mock与真实推送链
  → WP5 双反馈/复核
  → WP6 UI/演示中心
  → WP7 自动验收
  → G2批准
  → WP8服务器部署
  → WP9截图视频
  → G4销毁
```

每个工作包完成后由 Codex 主代理检查代码、测试和安全边界。Luna 可执行 fixture 计数核查、页面清单对照、机械性单测补充和文档一致性检查，但不得处理生产凭据、生产数据库写入、服务器部署、销毁命令或最终安全裁定。

---

## 18. 每个工作包交付模板

```markdown
### WPx 交付报告

- run_id：
- 实施范围：
- 未实施内容：
- 修改文件：
- 真实系统能力：
- 合成数据/Mock能力：
- 数据库与配置变化：
- 防误连检查：
- 测试命令与结果：
- API/SQLite 对账：
- 页面与角色验收：
- 失败项及原因：
- 销毁/回滚方式：
- 是否触碰生产：否/是（若是必须列明批准和只读/写入范围）
- 下一 Gate：
```

---

## 19. 一次性交付结果与运行指令

### 19.1 已实施范围

- `scripts/demo_env.py`：`create/status/verify/reset/serve/stop/destroy/verify-absent` 完整生命周期；环境变量在任何 `app.*` 导入前设置。
- `app/services/isolated_mode.py`：目录、配置、Oracle/PostgreSQL/Vastbase、Dify、Relay、notify/SMTP 出口 fail-closed。
- `app/demo_support/`：固定 12 科室、6 类质控、fixture 数据源、确定性造数、Mock Dify、Mock Relay。
- 真实手动推送链：UI/API 查询 fixture → payload composer → 回环 Dify HTTP → 结构化解析 → SQLite → 回环 Relay HTTP → H5。
- 数据闭环：`QCFeedback/QCFeedbackHistory`、`QCRecordAlertLog/QCAlertFeedback` 和人工复核三套状态分别造数。
- UI/H5：登录页、AppShell、H5 和 API Header 均显示 `SYNTHETIC TEST DATA / 脱敏合成测试数据`。
- `app/routers/demo.py`：真实数据库 demo 用户 token、manifest、测试中心和隔离凭据接口；不再签发不存在的 `user_id=0`。
- `scripts/quick_start.py`：废弃旧 5 科室/错误 `PushLog.dept_id` 写法，统一委托新隔离 CLI。
- `docker-compose.demo.yml`：回环端口、internal network、独立 run_id 目录的一键容器入口。
- Compose 只挂载当前 `run_id` 三个子目录，不向测试容器暴露现役 `data/config/logs` 根目录。

### 19.2 已冻结 showcase 数据

`run_id=demo-showcase-20260813`、`dataset_contract_digest=12bf3458dce9fbe995370ad9dbaabe983fe5b36ed1bb4788f2a79609b392a0ba`：

| 数据 | 数量 |
| --- | ---: |
| 科室 / 用户 / 角色 | 12 / 26 / 4 |
| PushLog | 1,200（每科 100） |
| success / failed / skipped | 1,020 / 120 / 60 |
| 维度 / 结论 | 6,120 / 1,020 |
| 业务反馈 / 历史 | 240 / 420 |
| Relay 告警 / H5反馈 | 144 / 96 |
| Execution / Attempt | 1,200 / 1,200 |

运行元数据、凭据和 manifest 位于忽略提交的 `config/demo/demo-showcase-20260813/`；数据库位于 `data/demo/demo-showcase-20260813/`。
manifest 的总摘要覆盖关键实体的业务身份、关系、状态、严重度、复核与反馈投影；`baseline_entities.json` 保存初始投影。严格验收要求当前摘要和全部投影与基线一致；交互后的 `verify --allow-drift` 要求各实体计数不减少且所有基线投影仍为当前集合的子集。

### 19.3 本地使用

```powershell
# 已创建好的 showcase 环境直接启动
python scripts/demo_env.py serve --run-id demo-showcase-20260813

# 浏览器入口
# http://127.0.0.1:18080/demo-test
# http://127.0.0.1:18080/ui-next/

# 停止服务后复核
python scripts/demo_env.py stop --run-id demo-showcase-20260813
python scripts/demo_env.py verify --run-id demo-showcase-20260813

# 如果已经点击手动推送导致数据增加，使用保留基线约束的漂移验收
python scripts/demo_env.py verify --run-id demo-showcase-20260813 --allow-drift

# 完整还原（只删除该 run_id 三个隔离目录）
python scripts/demo_env.py destroy --run-id demo-showcase-20260813 --force
python scripts/demo_env.py verify-absent --run-id demo-showcase-20260813
```

默认管理员为 `demo_admin`；密码保存在该 run_id 的 `credentials.json`，登录页在隔离模式下自动填充。生产构建不注册这些接口。

### 19.4 验收证据（2026-08-13）

- Python `compileall` 通过；前端 `typecheck` 和生产构建通过；Dify 命名检查通过。
- 新增隔离/Mock 合约测试 6 项通过；Dify、Relay、H5、loader、audit registry 聚焦回归通过。
- 后端完整 pytest 通过；前端 unit 50 项通过；真实 Playwright 在 1366/768/390 三个视口均通过。
- smoke 生命周期完成 `create → verify → serve → API/H5/RBAC → destroy`。
- 管理员可见 12 科室；`clinician_d001` 仅见听觉植入科，筛选耳内科返回 0。
- fixture 查询返回 2 个候选；真实手动推送 2/2 成功并落库；其中高危结果经 Mock Relay 形成消息。
- Mock Relay `/qc-detail/{id}` 307 跳转真实 `/mobile/qc/{id}`，H5 返回 200 且水印存在；首次整改成功、重复反馈返回 409。
- Playwright 已自动复验真实 `fixture → Dify → SQLite → Relay → H5反馈`，并验证临床账号跨科查询返回 0。
- 健康检查在 fixture 模式返回 `healthy`，角色、权限、患者质控、告警、反馈、统计、调度等核心页面 API 均返回 200。
- `docker compose -f docker-compose.demo.yml config` 通过。

真实环境 Playwright 命令（需先 `serve`）：

```powershell
$env:SYNTHETIC_DEMO_E2E='true'
$env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:18080/ui-next/'
$env:PLAYWRIGHT_SKIP_WEBSERVER='1'
Set-Location frontend
npx playwright test tests/e2e/synthetic-demo-real.spec.ts
```

### 19.5 未授权事项

本次没有登录生产服务器、没有部署容器、没有改生产 Oracle/Vastbase、没有调用真实 Dify/Relay/企业微信。若需部署到指定服务器或开放访问，仍须单独确认端口、访问范围和销毁时间；该确认不影响本地一次性交付已完成的结论。
