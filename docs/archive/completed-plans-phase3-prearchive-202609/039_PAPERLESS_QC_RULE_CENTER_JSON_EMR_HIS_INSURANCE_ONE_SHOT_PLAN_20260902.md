# 039 — 无纸化质控规则中心、EMR/HIS JSON 回传与医保质控插件一次性开发升级计划

> 文档编号：039  
> 编制日期：2026-09-02  
> 当前版本：v1.1（已吸收用户 2026-09-02 对 G1/G5/G6/G7/G8 的拍板）  
> 性质：**可直接交给开发 AI 的一次性本地开发作业书 + 分阶段生产启用方案**  
> 上游依据：026、028、029、030、031、032、034、036、`prearchive_service/README.md`、`docs/reference/101-103`、`docs/ACTIVE/多数据源扩展与可视化自定义规则质控实施方案.md`  
> 编号说明：037 已预留其交付报告为 038，因此本计划使用 039；本计划执行报告固定为 040。  
> 授权边界：用户已于 2026-09-02 明确允许本计划范围内的**新增预检表 DDL、代码/UI 部署和安全开关启用**；仍不授权真实 EMR/HIS 外发（接口资料未到）、错误年度医保正式判定、业务源库 DML/DDL、Dify/Relay 语义修改、无关生产配置修改、Git commit/push 或超出第三方实际许可证的再分发。

把本文全文交给开发 AI 即可执行。执行 AI 必须先完整阅读本文，不得只依据聊天摘要开发。

---

## 0. 用户目标、交付结论与执行策略

### 0.1 用户目标

1. 将无纸化系统中的质控规则配置进 Med-Audit，执行自动化质控；
2. 质控结果能够以稳定、版本化的 JSON 传给电子病历系统和 HIS；
3. 质控人员能够自行维护规则配置，而不是每次修改代码；
4. 为医疗质控、病历质控和医保质控预留统一扩展能力；
5. 尽量由一个开发 AI 一次性完成，同时不能影响当前已经运行的六类 Dify 质控、双模式调度、日志、反馈、Relay/H5 和历史数据；
6. 其他业务系统表结构、关系和值域优先复用 `F:\python\数据资产`，必要时才走受控只读查询。

### 0.2 架构裁定

**采用“一次性完成通用平台代码、两阶段完成真实启用”的方案。**

- 阶段 A（开发 AI 可一次完成）：规则中心、不可变版本、审批发布、试运行、JSON Schema、EMR/HIS 通用 Webhook、可靠 Outbox、医保插件接口、OpenDRG 隔离适配器、主系统管理界面、两套前端、权限和完整自动化测试。全部使用 fixture/Mock，新增能力默认关闭。
- 阶段 B（需人工资料/授权）：真实字段映射、真实 EMR/HIS 接口联调、本统筹区 DRG/DIP 规则包、影子运行、生产 DDL、部署和逐级开关。

原因：平台代码可以一次性可靠开发；真实 EMR/HIS 接口地址、认证、回执规范、医保地区版本和业务字段不能由 AI 猜测。强行合并会造成接口误发、错误医保结论或生产回归。

### 0.3 一次性执行前置关系

- 037 与本计划可能同时触及 `app/main.py`、权限、前端和测试。**禁止并行执行。**
- 若 `docs/ACTIVE/038_*` 尚不存在，先完成 037、生成 038、确认工作区交接清楚，再重新读取本文执行 039。
- 若工作区仍有他人未登记改动，执行 AI 必须对照 `开发起步包/01_统一修改记录.md` 确认归属；不得覆盖、回滚或夹带提交。
- 本计划不得借机重构现有六类 Dify 管线。

### 0.4 用户已拍板事项（2026-09-02）

- 规则发布**不强制双人审批**：`require_separate_approver=false`；同一管理员可编辑、审批和发布，但全过程审计、版本和回滚不可关闭；
- 医保地域/类型：**山东省济南市、DRG**；具体年度、分组方案和权重后续在管理界面维护；版本未配置前医保正式判定保持关闭；
- OpenDRG：用户允许本院使用和集成；执行 AI 仍须核对仓库实际 LICENSE/规则数据授权并生成 NOTICE，不能超许可证使用；
- 试点科室、规则范围、只提示/扣分/阻断、推送严重度全部做成可配置项；安全默认仍为“只提示、不扣分、不阻断”；
- 用户允许本计划范围内生产 DDL、部署和开关启用。允许启用管理页面/BFF和 `compare` 影子模式；真实 EMR/HIS destination 在 G2/G3 未完成时必须关闭；DRG 年度包在 G5 未完成时必须关闭；
- 本次授权不包含 Git commit/push，也不包含业务源库写入。

---

## 1. 已核验现状：必须复用，禁止重做

### 1.1 已有能力

当前仓库已经具备以下基础：

- 独立目录 `prearchive_service/`，强制零 `import app.*`；
- 无纸化 `T_MARK_ITEM` 92 条评分项快照；
- `example_rules.json` 正式规则与 `system_push_rules.json` 两轨规则文件；
- 一期 14 条规则，其中 11 条已按 2026-08-29 质控科授权口径回填 FID，检验/首页族仍受数据源门禁；
- `missing_doc`、`time_limit`、`empty_field`、`duplicate` 四类确定性判定器；
- 科室范围、豁免场景、生效窗口、来源水位、词表正负向匹配；
- `paperless_rpa` 过渡锚点、复检、检查键幂等和 current 历史保留；
- JHEMR/HIS/手麻/LIS 以及扩展来源采集器；病理、气管镜、血透、电测听、HIS 基本信息已有实测列契约；
- 独立 `MED_PREARCHIVE_RESULT`、SQLite fixture 仓储、Oracle 手工 DDL；
- 只读 `/api/precheck/{patient_id}/{visit_id}`、健康检查、HMAC 推送和医生提醒助手骨架；
- 主服务 `/api/audit-types/prearchive` 对两轨规则的只读展示；
- 主服务和 UI Next 已有质控类型管理页面，但预检规则目前只能只读查看。

### 1.2 当前缺口

本轮只补以下缺口：

1. 规则草稿、校验、审批、发布、回滚与审计；
2. 安全的可视化维护界面；
3. 文件规则到规则仓的无损导入和双读比对；
4. 统一 JSON 输出契约；
5. EMR/HIS 多目标可靠投递、回执、重试和幂等；
6. 医保质控插件接口及 OpenDRG 可选适配器；
7. 对外接口和规则运行统计；
8. 本地全链路自动化及生产影子切换方案。

### 1.3 旧方案的处理关系

- 026/028/030 继续作为业务来源、规则映射和隔离红线依据；
- `多数据源扩展与可视化自定义规则质控实施方案.md` 中把规则插入主 `push_executor` 的路径**本轮不执行**；当前已存在独立预检服务，继续保持隔离风险更低；
- 本计划不归档旧文档，也不改写其历史结论；执行范围发生冲突时，以 AGENTS.md、本计划和可执行代码为准。

---

## 2. 不影响原系统的硬边界

### 2.1 三个默认关闭开关

必须新增并保持以下默认值：

```json
{
  "rule_registry": {
    "mode": "file"
  },
  "result_delivery": {
    "enabled": false
  },
  "insurance_qc": {
    "enabled": false
  }
}
```

规则来源模式只允许：

- `file`：保持现状，只读既有两个规则文件；默认值；
- `compare`：仍以文件规则给出业务结果，同时用已发布规则仓影子执行并记录差异，不改变结果、不推送；
- `registry`：正式使用规则仓已发布版本；只能在影子比对通过并经人工批准后配置。

### 2.2 禁止影响的既有链路

本轮不得改变下列语义：

- 六类 Dify 审计类型配置、`mr_text → mr_txt` 映射、JSONPath、严重度门禁；
- `BulkPushExecutor`、`PushExecutor`、双模式调度、DB 级独立锁；
- `PushLog` 标志和 skip reason 既有含义；
- Relay 高危告警、H5 token 与反馈幂等；
- `/api/logs`、CSV 导出、统计 `_meta`、历史 NULL 容忍；
- `prearchive_service` 的触发锚点语义；
- `paperless_rpa` 模式禁用 source-ready 水位门、RPTCOUNT 只对账的既有裁定；
- 当前 14 条规则内容、92 条快照和 `system_push_rules.json`。

未经用户另行确认，执行 AI 禁止修改：

- `app/dify_pusher.py`
- `app/services/push_executor.py`
- `app/scheduler.py`
- `app/services/relay_alert_service.py`
- `config/config.json`
- `prearchive_service/rules/example_rules.json`
- `prearchive_service/rules/system_push_rules.json`
- `prearchive_service/rules/paperless_items_snapshot_20260828.json`

若实现确实需要修改这些文件，必须停止并说明原因，不得自行扩大范围。

### 2.3 隔离边界

- `prearchive_service/` 继续禁止 `import app.*`；
- 主服务不得 import `prearchive.*`，只允许通过固定 HTTP 客户端访问预检管理 API；
- BFF/预检服务任一不可用时，主服务必须照常启动；新页面显示“预检管理服务不可用”，不能拖垮质控类型页；
- 禁止使用通用透明代理；主服务 BFF 必须逐个显式列出允许调用的预检 API；
- 新服务异常不改变已有 Dify 推送成功状态；
- 生产业务源始终只读，医保、HIS、JHEMR、无纸化均禁止数据库回写。

---

## 3. 需要用户/医院提前确认的事项

这些事项**不阻塞阶段 A 的通用代码开发**，但会阻塞真实联调或启用。执行 AI 不得猜测；没有资料时按本文默认值完成 Mock 和占位配置。

| 门禁 | 需要确认的内容 | 未确认时的默认处理 | 阻塞范围 |
|---|---|---|---|
| G1 规则治理 | 是否强制“编辑人与审批人不能是同一人” | **已确认：否**。默认 `require_separate_approver=false`；审计/版本/回滚仍强制 | 已关闭 |
| G2 EMR 接口 | URL、方法、认证、超时、字段映射、成功回执、重复事件语义、是否支持 mTLS | 只提供禁用的 `emr_mock` 目标 | 阻塞真实 EMR 推送 |
| G3 HIS 接口 | 同 G2 | 只提供禁用的 `his_mock` 目标 | 阻塞真实 HIS 推送 |
| G4 数据最小集 | 接收方是否必须要患者姓名/住院号；默认只传 patient_id+visit_number | 默认不传姓名、身份证、电话、病历正文 | 阻塞超出最小集的字段开放 |
| G5 医保版本 | 本院统筹区、省市、CHS-DRG/CN-DRG/DIP 名称、年度版本、权重/支付标准来源 | **部分确认：山东济南、DRG；年度/规则包后续维护**。插件可部署但正式判定关闭 | 仅阻塞真实医保结论 |
| G6 OpenDRG | 社区版是否覆盖本院地区；法务/信息科是否接受其具体许可证和数据授权 | **院方使用/集成已允许**；仍须由执行 AI 核对实际 LICENSE/数据授权，超范围则只保留 adapter | 许可证无明确授予时阻塞 vendoring，不阻塞 adapter |
| G7 试点范围 | 试点科室、规则范围、只提示还是允许阻断、推送严重度 | **已确认做成可配置**；默认只提示、不扣分、不阻断，初始科室空集合=不向临床触达 | 已关闭；具体启用值后续维护 |
| G8 生产变更 | 生产 DDL、镜像、配置、重启窗口、回滚点 | **已授权本计划范围内 DDL、部署和安全开关**；执行前仍必须精确备份/回滚/verify | 已关闭；不扩展到业务库写入或真实外发 |

当前仍待外部资料的是 G2、G3、G4 的接收方字段确认，以及 G5 的具体年度规则包。G4 未确认前使用最小患者标识；真实规则仓接管前至少影子观察 7 天。

---

## 4. 目标架构

```text
                       ┌──────────────────────────────┐
                       │ Med-Audit 主服务（既有）       │
                       │ 六类 Dify/调度/日志/Relay 不变  │
                       └──────────────┬───────────────┘
                                      │ 可选、fail-open BFF
                                      ▼
┌──────────────────────────────────────────────────────────────────┐
│ prearchive_service（独立进程/容器）                               │
│                                                                  │
│ 数据采集 → PatientContext → 确定性规则引擎 → MED_PREARCHIVE_RESULT │
│                         │                                        │
│        ┌────────────────┴────────────────┐                       │
│        ▼                                 ▼                       │
│ 规则中心/版本/审批                  统一结果规范化器              │
│ file|compare|registry                   │                         │
│        │                           QC Result JSON v1               │
│        │                                 │                         │
│        └── 试运行/回测/差异 ────────┬────┴───────────┐             │
│                                    ▼                ▼             │
│                              EMR Outbox        HIS Outbox          │
│                              HMAC/mTLS         HMAC/mTLS           │
│                                                                  │
│ 医保插件：Noop（默认）/OpenDRG adapter（经许可后启用）             │
└──────────────────────────────────────────────────────────────────┘
```

### 4.1 所有权

- 规则数据、版本、发布指针、投递 Outbox 和管理审计归 `prearchive_service` 所有；
- 主服务只负责现有登录/RBAC、页面和白名单 BFF；
- 业务源只负责只读输入；
- EMR/HIS 只通过接口接收 JSON，不允许本项目直写其业务表；
- 医保规则包必须带地区、年度、来源、许可证和 SHA-256，禁止出现“最新版”这种不可审计标识。

---

## 5. 规则中心设计

### 5.1 规则轨道

规则必须带 `domain` 与 `origin`，至少支持：

| domain | 用途 | 首期行为 |
|---|---|---|
| `medical_record` | 无纸化病历完整性、时限、空项、重复 | 承接现有正式规则 |
| `medical_quality` | 诊疗过程、医疗安全、跨文书一致性 | 只建接口；不得改变现有六类 Dify |
| `insurance` | DRG/DIP、编码和费用合规提示 | 插件方式、默认关闭 |
| `system_push` | 各业务系统主动提供的提醒规则 | 保持与 T_MARK_ITEM 轨道分离 |

`origin` 至少支持：`paperless_t_mark_item`、`hospital_policy`、`system_push`、`opendrg`、`manual`。

### 5.2 状态机

```text
draft → validated → approved → published → retired
  │         │           │          │
  └─编辑────┘           └─拒绝────>draft
                                  published(old) ← rollback
```

硬规则：

- `published` 内容不可修改，只能基于它创建新版本；
- 运行时只读发布指针，不读取 draft；
- 发布必须是单事务：锁定规则集 → 校验状态/审批人 → 更新指针 → 写审计；
- 回滚是把指针指向旧的已发布版本，不覆盖历史；
- 每个版本保存 canonical JSON 的 SHA-256；
- 审批、发布、回滚必须记录操作者、时间、原因、前后版本和 request_id；
- 两轨规则跨文件/跨规则集 `rule_id` 仍不得重复；
- FID 未确认的规则可以保存草稿，但不得以 `paperless_t_mark_item` 来源发布为自动扣分规则；
- 任何规则默认只产生“提示”，不得直接扣费、扣分、拒绝医保结算或阻断医生操作。

### 5.3 DSL v2 安全边界

在现有四类规则上做向后兼容扩展，但禁止把规则编辑器变成代码执行器：

- 允许：字段存在/空值、等于/不等于、集合、数字范围、日期差、计数、文书匹配、AND/OR/NOT、有限正则；
- 禁止：任意 SQL、Python、JavaScript、Jinja、`eval`、Shell、URL 请求；
- 规则只引用预先注册的 canonical fields 和 source codes；
- 正则限制长度、输入长度和执行时间；
- 数值、日期和枚举转换失败应产诊断并按无法判断处理，不能阻断批次；
- 未就绪数据源不得判“缺失”，必须 `unknown/skipped`；
- `paperless_rpa` 下继续遵守既有特殊水位语义。

### 5.4 建议新增独立表

不得修改既有 `MED_PREARCHIVE_RESULT` 字段语义；新增表使用独立前缀：

| 表 | 用途 | 关键约束 |
|---|---|---|
| `MED_PREARCHIVE_RULE_VERSION` | 不可变规则/规则集版本 | `(RULE_KEY, VERSION)` 唯一、CONTENT_SHA256 唯一校验 |
| `MED_PREARCHIVE_RULE_POINTER` | 每域当前发布指针 | 每 `DOMAIN+TRACK` 一行；乐观版本号防并发覆盖 |
| `MED_PREARCHIVE_RULE_AUDIT` | 编辑/校验/审批/发布/回滚审计 | append-only |
| `MED_PREARCHIVE_DESTINATION` | 非敏感目标配置 | 只存 `secret_ref`，不存明文密钥 |
| `MED_PREARCHIVE_OUTBOX` | 每事件、每目标可靠投递 | `(EVENT_ID, DESTINATION_CODE)` 唯一 |
| `MED_PREARCHIVE_DELIVERY_LOG` | 每次尝试与脱敏回执 | append-only，不存患者正文/密钥 |

要求：

- SQLite 测试可自动建表；Oracle 继续用 `prearchive_service/sql/` 手工 DDL，服务启动禁止自动 DDL；
- Oracle 空字符串等于 NULL，DDL 不得依赖 `DEFAULT '' NOT NULL`；新表的可空性和默认值必须单独验证；
- CLOB/普通列顺序规避 ORA-24816；
- 所有枚举在应用层和数据库检查约束中一致；
- DDL 必须提供反向清理脚本，但生产回滚优先停开关/回镜像，不自动丢表。

### 5.5 文件规则迁移与零差异切换

新增 CLI，建议命令：

```powershell
python -m prearchive.rule_admin import-files --dry-run
python -m prearchive.rule_admin import-files --apply
python -m prearchive.rule_admin compare-fixtures
```

约束：

1. `--dry-run` 默认，只生成规则数、版本、哈希、冲突和校验错误；
2. `--apply` 必须显式给出，生产执行仍需 G8；
3. 导入不能改写原 JSON 文件；
4. 对当前 fixture，file 与 registry 的 problem 集合、severity、FID、message、rule_version 必须逐字段一致；
5. `compare` 模式差异只写脱敏诊断，不改变业务结果；
6. 任何差异未清零时禁止切 `registry`。

---

## 6. 统一 JSON 契约

### 6.1 版本化 Schema

新增仓库内机器可读 Schema：

- `prearchive_service/schemas/qc-result-v1.schema.json`
- `prearchive_service/schemas/qc-ack-v1.schema.json`
- `prearchive_service/schemas/rule-dsl-v2.schema.json`

所有出站 JSON 必须先通过本地 JSON Schema 校验。`schema_version` 使用语义版本；破坏性改字段只能升主版本并保留旧序列化器。

### 6.2 标准输出示例

```json
{
  "schema_version": "1.0.0",
  "event_id": "018f-example-uuid",
  "event_type": "hospital_qc.result.created",
  "occurred_at": "2026-09-02T10:30:00+08:00",
  "producer": "med-audit-prearchive",
  "idempotency_key": "sha256:...",
  "subject": {
    "patient_id": "INTERNAL_PATIENT_ID",
    "visit_number": "2",
    "encounter_type": "inpatient",
    "dept_code": "DEPT001"
  },
  "run": {
    "result_id": "12345",
    "trigger_mode": "paperless_rpa",
    "checked_at": "2026-09-02T10:29:58+08:00",
    "data_snapshot_at": "2026-09-02T10:25:00+08:00",
    "rule_sets": [
      {
        "domain": "medical_record",
        "version": "2026.09.02.1",
        "sha256": "..."
      }
    ]
  },
  "summary": {
    "status": "warn",
    "highest_severity": "medium",
    "issue_count": 1,
    "unknown_count": 0
  },
  "issues": [
    {
      "issue_id": "medical_record:R-MISS-SURGERY-CHECKTABLE",
      "domain": "medical_record",
      "rule_id": "R-MISS-SURGERY-CHECKTABLE",
      "rule_version": "2026.09.02.1",
      "mark_item_fid": 60,
      "name": "缺手术安全核查表",
      "status": "fail",
      "severity": "medium",
      "message": "未找到手术安全核查表",
      "recommendation": "归档前请核对并补齐",
      "source_systems": ["sm_itf", "jhemr_blws"],
      "evidence": {
        "expected_document_code": "surgery_safety_check",
        "matched_count": 0
      },
      "requires_manual_review": false
    }
  ],
  "insurance": null
}
```

约束：

- 字段名固定英文，中文只出现在可读 name/message/recommendation；
- patient name、身份证、电话、地址、医保号和病历原文默认不发送；
- evidence 只发结构化最小证据，禁止整段文书；
- `status` 只允许 `pass|warn|fail|unknown`；severity 只允许 `low|medium|high`；
- 规则数据不足用 `unknown`，不得伪造成 pass；
- `event_id` 全局唯一；`idempotency_key` 对同一接收方重试保持不变；
- 时间带 `Asia/Shanghai` 偏移；
- 接收方字段差异由 destination mapper 完成，不允许污染核心 Schema。

### 6.3 回执契约

```json
{
  "schema_version": "1.0.0",
  "event_id": "018f-example-uuid",
  "accepted": true,
  "received_at": "2026-09-02T10:30:01+08:00",
  "receiver_reference": "EMR-QC-10001",
  "message": "accepted"
}
```

投递语义：

- 2xx + 合法 ACK：成功；
- 409 且明确标识同一 event 已接收：按幂等成功；
- 408/429/5xx：可重试；
- 其他 4xx、ACK event_id 不一致、Schema 不合法：终止自动重试并告警；
- 网络超时视为状态未知，仍按同一 idempotency key 重试；
- 不允许因投递失败回滚或删除质控结果。

---

## 7. EMR/HIS 投递与可靠性

### 7.1 Destination Adapter

每个目标配置：

```json
{
  "code": "emr_mock",
  "kind": "emr",
  "enabled": false,
  "base_url": "http://127.0.0.1:...",
  "endpoint": "/mock/qc-results",
  "auth_type": "hmac_sha256",
  "secret_ref": "env:PREARCHIVE_EMR_HMAC_SECRET",
  "schema_version": "1.0.0",
  "timeout_seconds": 5,
  "max_attempts": 6,
  "send_severities": ["medium", "high"]
}
```

实现要求：

- 首期支持 `hmac_sha256`，接口预留 `mtls`；禁止 Basic 明文口令落库；
- HMAC 使用原始 body，协议要有固定契约向量；
- 目标 URL 必须经 allowlist/协议/主机校验，防 SSRF；
- 内网 HTTP 只能显式设置 `allow_insecure_internal_http=true`，默认 HTTPS；
- secret 只能从环境变量/受控 secret provider 读取，API/UI 永不返回明文；
- destination 修改需版本审计；空 secret 不得覆盖已有 secret_ref；
- “测试连接”只发送合成数据和 `event_type=hospital_qc.contract_test`，禁止选真实患者；
- EMR/HIS 分别独立 Outbox，某一目标失败不得影响另一目标。

### 7.2 Outbox Worker

- 结果事务提交后再生成 Outbox；若生成失败必须可由 reconciliation job 补齐；
- 唯一键 `(event_id, destination_code)`；
- 状态 `pending|sending|sent|retry|dead|disabled`；
- 原子 claim，避免多线程重复发送；
- 指数退避 + jitter，尊重 Retry-After；
- worker 崩溃后超时 lease 可回收；
- 成功后永不自动回退；
- 提供 admin 只读列表和单条 retry，retry 必须记录操作者；
- `result_delivery.enabled=false` 时不创建真实发送任务；可以生成 dry-run preview，但不能联网。

---

## 8. 医保质控插件

### 8.1 首期目标

本轮不承诺替代医保局审核系统，也不自动拒付。一次性开发以下通用接口：

```python
class InsuranceQCPlugin(Protocol):
    code: str
    def validate_configuration(self) -> list[dict]: ...
    def evaluate(self, context: InsuranceContext) -> InsuranceAssessment: ...
```

内置：

- `NoopInsurancePlugin`：默认；返回 disabled；
- `DeterministicCodingPlugin`：只做有明确数据依据的编码格式、主诊断/主手术缺失、重复编码、性别/年龄适用性等配置化提示；
- `OpenDRGAdapter`：可选、隔离、许可通过后启用；不得让核心服务直接依赖某个地区规则文件。

### 8.2 OpenDRG 适配纪律

参考资源：

- `https://github.com/OpenDRG/OpenDRG`
- `https://github.com/OpenDRG/DRG_Python`

但执行 AI 必须遵守：

1. 未完成 G5/G6 前不得下载、复制或提交 OpenDRG 代码/规则包；
2. 不得把“免费版本”自动解释为可任意二次分发；必须读取具体仓库 LICENSE 和规则数据授权；
3. adapter 用进程内协议或本地子进程均可，但失败必须返回 `unknown`，不能影响病历质控；
4. 输入映射独立成 `insurance_mapping`，至少包含诊断、手术、年龄、性别、出生体重、出院方式等，并为缺字段给出 diagnostics；
5. 输出保存 `grouper_code`、`ruleset_region`、`ruleset_year`、`ruleset_version`、`ruleset_sha256`、MDC/ADRG/DRG 和 diagnostics；
6. 规则包切换必须版本化，可回滚，旧结果保留当时版本；
7. 禁止把其他省市或其他年度分组结果当成本院正式医保结论。

### 8.3 明确不直接集成的资源

- OpenHIS/MRQC 只参考交互和流程；其 GPL-3.0 代码不得复制进本仓库；
- OHDSI DataQualityDashboard/Achilles 只借鉴数据质量维度与统计方法，不引入 R/OMOP 运行栈；
- HL7 CQL/CQF Clinical Reasoning 只作为未来导入导出标准，不在一期引入 Java/FHIR 技术栈；
- 未经代码、测试、许可证审计的医疗 AI 演示仓库不得作为生产依赖。

---

## 9. 管理 API、权限与前端

### 9.1 预检服务内部管理 API

建议路径如下；实际命名可以微调，但功能和权限不可缺：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/admin/rules` | 列表/筛选 |
| POST | `/api/admin/rules` | 新建 draft |
| GET | `/api/admin/rules/{rule_id}/versions` | 不可变版本历史 |
| PUT | `/api/admin/rules/{rule_id}/draft` | 修改草稿，需乐观锁 |
| POST | `/api/admin/rules/{rule_id}/validate` | Schema+语义校验 |
| POST | `/api/admin/rules/{rule_id}/dry-run` | 仅 fixture/脱敏 bundle 试运行 |
| POST | `/api/admin/rules/{rule_id}/approve` | 审批 |
| POST | `/api/admin/rules/{rule_id}/publish` | 发布并更新指针 |
| POST | `/api/admin/rules/{rule_id}/rollback` | 回滚发布指针 |
| GET | `/api/admin/rules/{rule_id}/diff` | 版本差异 |
| GET/POST | `/api/admin/destinations` | 目标列表/非敏感配置维护 |
| POST | `/api/admin/destinations/{code}/contract-test` | 合成数据契约测试 |
| GET | `/api/admin/outbox` | 投递状态 |
| POST | `/api/admin/outbox/{id}/retry` | 人工重试 |
| GET | `/api/admin/fields` | 可配置 canonical fields、值域和来源就绪状态 |
| GET | `/api/admin/audit` | 管理审计 |

内部 API 使用独立 service token/HMAC；不得复用患者查询用的 `X-Precheck-Token`。请求需带主服务签名的 actor id/name/permissions/request_id，预检服务必须验签并落审计，不能相信裸 header。

### 9.2 主服务 BFF

新增显式白名单客户端和路由，建议：

- `app/services/prearchive_admin_client.py`
- `app/routers/prearchive_admin.py`

环境变量：

- `PREARCHIVE_ADMIN_ENABLED=false`
- `PREARCHIVE_ADMIN_BASE_URL=`
- `PREARCHIVE_ADMIN_SECRET=`

要求：

- 开关关闭时新写接口返回清晰的 503/feature-disabled，既有 `/api/audit-types/prearchive` 只读接口仍可用；
- 启动时不探测远端，不因远端不可用启动失败；
- 连接/读取/总超时均有上限；
- 不透传任意 URL/path/header；
- 错误响应脱敏，日志不打印 token、患者标识和规则完整 evidence；
- 统一 request_id；
- 保持当前路由注册顺序，静态根路由仍最后挂载。

### 9.3 权限

新增权限时只做 additive seed，默认只赋予 admin：

- `prearchive_rule_view`
- `prearchive_rule_edit`
- `prearchive_rule_approve`
- `prearchive_rule_publish`
- `prearchive_integration_manage`
- `prearchive_delivery_retry`

要求：

- 更新 `app/database.py` 与 demo seed；
- 不改变现有角色权限；
- 后端每个写端点强制校验，不能只隐藏按钮；
- 仅当未来管理员把 `require_separate_approver` 改为 true 时，审批人不能等于草稿创建/最后编辑人；当前用户拍板的默认值为 false；
- 无查看权限的用户看不到规则正文、目标地址和投递日志。

### 9.4 两套前端

当前系统同时保留 legacy 静态前端和 UI Next。一次性开发必须同时补齐，不能只做一套：

1. 在既有“质控类型”页增加“归档前规则中心”区域，不新增平行菜单；
2. 列表展示 domain、名称、类型、FID、状态、当前发布版本、来源、适用科室；
3. 编辑抽屉用表单维护四类现有规则，复杂条件提供高级 JSON；
4. JSON 编辑保存前必须本地+后端双校验；
5. 提供版本 diff、试运行、提交审批、审批、发布、回滚；
6. 提供 EMR/HIS 目标状态与合成契约测试；
7. 提供 Outbox 状态和有权限的 retry；
8. 页面明显显示“文件/影子比对/规则仓”运行模式与“对外推送关闭/开启”；
9. 危险操作二次确认，发布对话框显示版本和 SHA；
10. 预检服务不可用时原质控类型 CRUD、Dify 测试和页面其他区域仍可操作。

UI 首版不做自由拖拽画布；使用结构化表单 + 条件树 + 高级 JSON，降低一次性开发失败和不可维护风险。

---

## 10. `F:\python\数据资产` 使用规则

### 10.1 优先级

开发 AI 按以下顺序获取业务结构：

1. 先读 `F:\python\数据资产\AGENTS.md`；
2. 读 `开发起步包/README.md`、`55_系统未完成事项统一执行计划.md` 和 `三仓库互通地图.md`；
3. 优先读取机器可读资产包：tables/columns/relationships/value_domains/catalog；
4. 再读 `09_数据资产_表结构与关联关系.md`、`10_关系验证报告.md`、病案首页值域文档；
5. 只有资产仍缺字段时，才按数据资产仓库要求使用 `sjzc` 受控只读入口做限量 live 核验。

### 10.2 本轮要核对的契约

阶段 A 只需要建立 adapter 和字段清单，不需要真实患者查询。阶段 B 至少核对：

- 住院主键 `PATIENT_ID + VISIT_ID` 与 JHEMR/无纸化的精确映射；
- 诊断、手术、病案首页、结算、费用、医保结算字段；
- 本地 ICD 编码字段与版本；
- 性别、年龄、出院方式等值域；
- DRG/DIP 已有分组结果或结算回写字段是否存在；
- EMR/HIS 接口接收所需患者标识；
- 数据更新时间、水位和迟到数据窗口。

### 10.3 查询红线

- 只允许 SELECT；不执行 DDL/DML；
- 不全扫 `LAB_RESULT`、费用等巨表；必须按患者键/日期/ROWNUM 限定；
- 值域先查资产包，不猜；
- 不读取或落盘病历正文、姓名、身份证、电话、地址；
- 只将表名、字段名、脱敏值域和聚合数字带回本仓库；
- 凭据不进命令输出、计划、代码、日志或 Git；
- 若当前执行环境没有 `sjzc` 技能，不得另写临时直连脚本绕过，记录为 BLOCKED_DATA_CONTRACT 并继续完成 Mock 框架。

---

## 11. 阶段 A：一次性本地开发包

执行 AI 按 T0→T10 单会话顺序推进；某包失败先修复，不跳过。允许一次性开发，但应按包保持可审查边界。

### T0 — 基线、冲突和契约快照

- 完整执行仓库启动协议；
- 确认 037/038 状态，禁止并行；
- `git status --short`，登记他人改动归属；
- 记录当前 HEAD、Python/Node 版本、测试基线；
- 对三个正式规则文件计算 SHA-256，只读保存到执行报告，不改文件；
- 运行当前 prearchive 测试、isolation、主服务聚焦测试和前端基线；
- 若基线已有失败，区分“既有失败/本轮失败”，不得改测试掩盖。

### T1 — Schema 与领域模型

- 增加 RuleVersion/Pointer/Audit/Destination/Outbox/DeliveryLog 模型；
- 增加 JSON Schema 与 Pydantic 模型；
- 增加 `QCResultEnvelope`、`QCIssue`、`InsuranceAssessment`；
- 对现有 `PrearchiveResult` 建纯序列化适配器，不改变原模型字段和 `to_public_dict()`；
- 补 SQLite 与 Oracle DDL；Oracle DDL 不执行。

### T2 — 规则仓、状态机和 CLI

- 实现不可变版本、乐观锁、双人审批、发布指针、回滚和 append-only 审计；
- 实现 file/compare/registry 三模式；
- 实现文件 dry-run import 与 apply；
- 实现 canonical JSON/SHA-256；
- 规则校验包含 Schema、语义、source、field、FID、重复 ID、危险表达式；
- 新增 fixture golden test，证明 file 与 registry 零差异。

### T3 — 管理 API

- 扩展 `prearchive_service/prearchive/api.py` 或拆分独立 router；
- 实现 §9.1 API、分页、过滤、错误码和鉴权；
- 保持现有 `/healthz` 与患者只读 API 完全兼容；
- 所有写操作支持 request_id、审计、并发冲突 409；
- dry-run 默认只允许 fixture/调用方提交的脱敏 bundle，不查询真实库。

### T4 — JSON 结果与 Outbox

- 实现 v1 序列化器和 ACK 校验；
- 实现 destination mapper、HMAC 契约向量、SSRF 防护；
- 实现 Outbox claim/retry/lease/dead/reconciliation；
- 增加两个本地 Mock receiver，覆盖 EMR/HIS 成功、409、429、5xx、超时、坏 ACK；
- 开关关闭时断言零网络请求。

### T5 — 医保插件骨架

- 实现 plugin protocol、Noop、确定性编码插件；
- 实现 OpenDRGAdapter 壳、配置验证和合成测试；
- 未通过 G5/G6 时不得添加第三方源码、真实规则包或网络下载；
- 将医保结果作为 JSON 的可选 `insurance` 字段，不污染 `issues` 的病历规则语义；
- 插件异常返回 unknown diagnostics，不影响病历结果。

### T6 — 主服务 BFF 与 RBAC

- 新增白名单 BFF、环境开关、超时和签名 actor；
- 注册路由但默认关闭；
- 添加六个权限并仅给 admin 默认赋权；
- demo seed 同步；
- 既有 `/api/audit-types/prearchive` 保持原响应；
- 预检服务不可用/超时/坏 JSON 测试必须证明主 API 和质控类型页不受影响。

### T7 — Legacy 前端

- 在现有 `static/templates/pages/audit_types.html`、对应 JS/CSS 中增加规则中心；
- 不删除或重写当前审计类型 CRUD；
- 权限控制、规则表单、版本 diff、试运行、审批、发布、回滚、目标和 Outbox；
- 使用 API mock 的静态契约测试；
- 对预检不可用、空态、无权限、409 并发、Schema 错误做界面处理。

### T8 — UI Next 前端

- 在 `frontend/src/features/governance/AuditTypesPage.vue` 增加同等能力；
- API 类型放入既有模块或清晰的 prearchive API 文件；
- 增加 Vitest；
- 更新路由/权限不得新增重复菜单；
- build 后按既有流程同步 `static/ui-next`，不得手工改 dist。

### T9 — 数据资产适配与契约占位

- 只读解析 `F:\python\数据资产` 中相关机器资产，生成代码内 canonical field registry；
- 不把外仓大文件复制进本仓库；
- 每个映射注明 `confirmed|candidate|blocked` 和证据路径/快照日期；
- candidate/blocked 字段不能用于发布规则；
- 为真实 EMR/HIS/医保 mapping 留显式占位和诊断，不造假值域。

### T10 — 总门禁、文档和交接

- 运行 §12 全部门禁；
- 生成 `docs/ACTIVE/040_039_EXECUTION_DELIVERY_REPORT_YYYYMMDD.md`；
- 同步 `docs/INDEX.md`；
- 更新 `prearchive_service/README.md` 的运行、配置、API、回滚说明；
- 若新增长期契约文档，放 `docs/reference/` 并同步 INDEX，禁止 docs 顶层散文件；
- 追加 `开发起步包/01_统一修改记录.md`；
- 不经用户批准不 commit、不 push、不部署；
- 最终答复必须列出完成/未完成/阻断、改动文件、测试数字、所有开关默认值、真实网络调用次数（阶段 A 必须为 0）、后续 G1-G8 清单。

---

## 12. 测试与验收门禁

执行时以 T0 实测基线为准；下列历史数字只作最低参考：主服务 1211、prearchive 212、UI Next 52、legacy E2E 5。若 037 已提高基线，不得回退到旧数字。

### 12.1 必须新增的测试类别

| 测试 | 必测内容 |
|---|---|
| Rule schema | 合法/非法类型、字段、source、FID、正则、嵌套深度 |
| Rule lifecycle | draft/validate/approve/publish/retire/rollback；非法跳转；双人审批 |
| Concurrency | 乐观锁冲突 409、双发布只能一胜、Outbox 原子 claim |
| Golden parity | 现有两轨文件导入后 fixture 结果逐字段零差异 |
| Modes | file/compare/registry；compare 永不改变业务结果 |
| JSON Schema | v1 正反例、unknown、时区、最小患者字段、禁止 PHI 哨兵 |
| Delivery | 2xx/409/429/5xx/timeout/bad ack/retry/dead/reconciliation |
| Security | RBAC、actor 签名、SSRF、secret mask、日志脱敏、禁止任意代码/SQL |
| Insurance | Noop、配置缺失、合成 grouping、adapter 崩溃 fail-open |
| BFF | disabled/unavailable/timeout/bad JSON，不影响主服务启动与既有页面 |
| UI | 两套前端 CRUD、diff、试运行、审批发布、无权限、错误态 |
| Regression | Dify/调度/Relay/logs/feedback/现有 audit type 与 prearchive API |

### 12.2 命令门禁

```powershell
# prearchive 独立服务
python -m pytest prearchive_service/tests -q
python prearchive_service/check_isolation.py

# 主服务
python -m pytest
python -m compileall app tests prearchive_service
python scripts/check_naming_convention.py

# UI Next
npm --prefix frontend run typecheck
npm --prefix frontend run test:unit
npm --prefix frontend run build
npm --prefix frontend run test:e2e

# Legacy 真后端 E2E（按仓库既有环境变量/启动方式）
$env:LEGACY_E2E='1'
npm --prefix frontend run test:e2e:legacy
Remove-Item Env:LEGACY_E2E
```

若默认 E2E 需要既有 Mock server，严格沿用当前 Playwright 配置，不另连生产。所有测试禁止外网、禁止真实 Dify、Relay、EMR、HIS、医保接口和业务数据库。

### 12.3 不回归断言

- 新开关全部关闭时，现有 API 路由清单除新增路由外无删除/方法变化；
- 六类 Dify fixture 的 `mr_text`、维度、严重度、skip reason 与基线相同；
- 双调度 job id、run mode、锁名和 status diagnostics 不变；
- Relay 签名向量、H5 反馈、CSV 字段不变；
- 当前 file 规则产生的结果不变；
- `prearchive_service/check_isolation.py` 仍通过；
- 新 UI 不可用时既有“质控类型”编辑仍可使用；
- `result_delivery.enabled=false` 的测试中网络 sender 调用次数为 0；
- `insurance_qc.enabled=false` 时不加载第三方规则包、不改变 JSON summary。

---

## 13. 预计文件范围

执行 AI 可以根据代码结构微调，但不得越过硬边界。

### 13.1 `prearchive_service/` 新增/修改

建议新增：

- `prearchive/rule_models.py`
- `prearchive/rule_repository.py`
- `prearchive/rule_service.py`
- `prearchive/rule_admin.py`
- `prearchive/result_contract.py`
- `prearchive/destinations.py`
- `prearchive/outbox.py`
- `prearchive/delivery_worker.py`
- `prearchive/insurance/base.py`
- `prearchive/insurance/noop.py`
- `prearchive/insurance/deterministic.py`
- `prearchive/insurance/opendrg_adapter.py`
- `schemas/*.schema.json`
- `sql/create_prearchive_rule_center_oracle.sql`
- `sql/drop_prearchive_rule_center_oracle.sql`
- 对应测试和 fixtures。

可能修改：`api.py`、`models.py`、`config.py`、`engine.py`、`run_service.py`、`README.md`、`config.example.json`、`requirements.txt`。第三方依赖非必要不增加；JSON Schema 优先使用已存在/Pydantic 能力，若新增依赖需锁定版本并补离线包评估。

### 13.2 主服务与前端

- `app/services/prearchive_admin_client.py`
- `app/routers/prearchive_admin.py`
- `app/main.py`
- `app/database.py`（只增加 additive permission seed，不增加预检业务表）
- `app/demo_support/seed.py`
- `static/templates/pages/audit_types.html`
- `static/scripts/modules/audit_types.js` 或拆分的子模块
- `static/styles/pages/audit_types.css`
- `frontend/src/features/governance/AuditTypesPage.vue`
- 对应 API 类型、Vitest、主服务和静态契约测试。

---

## 14. 阶段 B：真实联调、升级和启用

阶段 A 全绿后，执行 AI 必须展示 G1-G8 状态。G8 已由用户于 2026-09-02 明确批准，允许在完整备份、回滚点和门禁全绿后继续执行 B3；G2/G3/G5 尚未完整，不得因此启用真实外发或 DRG 正式判定。

### B0 — 资料与许可证门禁

- 固化已拍板的 G1/G6/G7/G8，并收齐当前动作实际需要的 G2/G3/G4/G5；缺失目标保持 disabled，不阻塞安全部署；
- 冻结 EMR/HIS JSON Schema 与 ACK；
- 冻结医保地区/年度/规则来源；
- 完成第三方 LICENSE/NOTICE 清单；
- 未满足的目标保持 disabled，不阻塞其他目标。

### B1 — 受控只读数据核验

- 通过数据资产机器资产与 `sjzc` 限量只读核验；
- 输出字段契约、值域、更新时间和映射覆盖率；
- 不落患者明细；
- 发现键或值域不确定时规则保持 blocked，不得用猜测值上线。

### B2 — 院内 Mock/UAT

- EMR/HIS 先接各自 Mock；
- 使用虚构患者跑完整发送/回执/重复/超时/重试；
- 由对方系统确认字段和幂等语义；
- 真实患者不得用于公网或开发机 Mock。

### B3 — 生产升级但全部业务开关关闭

顺序：

1. 记录当前镜像/config/DB schema/规则文件哈希；
2. 备份应用库相关 schema、配置和镜像，给出恢复命令；
3. DBA 手工执行新增表 DDL；
4. 部署独立 prearchive 服务与主服务/UI；
5. 保持 `rule_registry.mode=file`、delivery=false、insurance=false；
6. 验证健康、六类 Dify、调度、日志、反馈、Relay、两套 UI；
7. 用户先核查新管理页面和合成契约测试。

### B4 — 规则仓影子

- 规则文件 dry-run import；
- 人工核对数量、版本、FID、SHA 后 apply；
- 切 `compare`，至少 7 天；
- file 结果仍是唯一业务结果；
- 比对 problem 集合、严重度、证据和运行耗时；
- 差异未清零不得切 registry。

### B5 — 对外接口影子

- 先向 EMR/HIS 测试目标发送合成事件；
- 再按批准的试点科室发送 shadow 标记事件；
- 对方只落测试/影子区，不弹临床阻断；
- 核对发送数、接收数、去重数、失败数和死信数。

### B6 — 正式启用

每个动作分开批准：

1. `file → registry`；
2. 开启 EMR 目标；
3. 开启 HIS 目标；
4. 开启医保插件；
5. 扩大科室/严重度。

任一步异常先关对应开关，不回滚其他已稳定能力。

---

## 15. 回滚方案

| 故障 | 首选回滚 | 数据处理 |
|---|---|---|
| 规则仓结果异常 | `rule_registry.mode=file` | 保留版本和审计，不删除 |
| EMR 推送异常 | 禁用 EMR destination / delivery 总开关 | Outbox 保留，暂停发送 |
| HIS 推送异常 | 禁用 HIS destination | 不影响 EMR |
| 医保分组异常 | `insurance_qc.enabled=false`，回退 Noop | 旧评估保留版本 |
| 管理服务不可用 | 关闭 BFF 开关 | 主系统继续运行，文件规则继续执行 |
| UI 回归 | 回滚静态资源/镜像 | API 与规则结果不变 |
| 数据库 DDL 问题 | 回滚镜像并停止新服务 | 默认不 DROP 表；确认无数据后才由 DBA 执行清理脚本 |

禁止自动删除规则版本、审计、Outbox 或交付日志。生产回滚点、执行时间和核验结果必须登记到统一修改记录。

---

## 16. 完成定义（DoD）

阶段 A 只有同时满足以下条件才算完成：

- [ ] file/compare/registry 三模式完成且默认 file；
- [ ] 当前规则文件未修改，导入后 fixture 结果零差异；
- [ ] 规则草稿、校验、审批、发布、回滚、审计全链路完成；
- [ ] JSON/ACK Schema 和契约测试完成；
- [ ] EMR/HIS Mock 投递、Outbox、重试、幂等、死信完成；
- [ ] delivery 默认 false，测试证明零真实网络调用；
- [ ] 医保 plugin/Noop/确定性规则/OpenDRG 壳完成，默认 false；
- [ ] 未经许可没有复制第三方源码或规则；
- [ ] Legacy 与 UI Next 均可维护规则；
- [ ] RBAC 后端与按钮双重控制；
- [ ] 预检服务故障不影响主服务和旧质控类型页；
- [ ] 全量测试不低于 T0 基线，新增测试全过；
- [ ] isolation、compileall、命名、typecheck、unit、build、两套 E2E 全过；
- [ ] 040 交付报告、INDEX、README、统一修改记录完成；
- [ ] 零生产访问、零生产写入、零真实业务接口调用；
- [ ] 未经用户批准没有 commit、push 或部署。

阶段 B 只有备份、影子、对账、回滚演练和用户验收完成后，才可称为“规则中心生产启用完成”。EMR/HIS 或医保某个目标仍缺资料时只能称为“框架已部署、目标未启用”，不得宣称真实对接完成。

---

## 17. 给执行 AI 的最终纪律

1. 不要重建 `prearchive_service`，在现有实现上增量开发；
2. 不要把规则引擎插进现有 Dify push executor；
3. 不要修改正式规则内容来让测试通过；
4. 不要用任意 SQL/代码执行实现“灵活配置”；
5. 不要猜 EMR/HIS 接口或医保政策；缺资料就做 Mock/blocked；
6. 不要连接生产或真实业务库完成阶段 A；
7. 不要只做后端而漏掉 Legacy/UI Next，也不要只做页面假数据；
8. 不要跳过不可用、超时、并发、回滚、权限和隐私测试；
9. 不要把开源仓库“能下载”当作许可证已批准；
10. 每完成一包立即跑聚焦测试，最后跑全门禁；上下文不足时以本文 DoD 为准继续，不擅自缩减。
